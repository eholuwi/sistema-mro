"""Página Saldo em Estoque (v5.3.0 / F4a) — consulta do inventário + contagem física.

Migrada do bloco inline do `app.py`. Padroniza os filtros/tabela para
`barra_filtros`/`tabela_paginada` (decisão F4a). O read quente do inventário usa
`inventario_cached()`; toda escrita da contagem física chama `invalidar_leituras()`.
Regra de negócio (ajuste físico / conferência / movimentação) preservada 1:1.
"""
from __future__ import annotations

import io
import time
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from services.constants import PREVISAO_RUPTURA_SEM_RISCO
from services.db_functions import (
    listar_valores, exportar_inventario_df, desmarcar_inventariado,
    registrar_movimentacao, atualizar_localizacao_e_inventariar,
)
from ui.cache import inventario_cached, invalidar_leituras
from ui.formatos import fmt
from ui.componentes.filtros import barra_filtros
from ui.componentes.tabela import tabela_paginada
from ui.componentes.selecao import sel_material


# ── Cálculo puro (testável) ───────────────────────────────────────────────────

def acaba_em(dias, hoje=None):
    """Data estimada de ruptura = hoje + dias de cobertura (dd/mm/aaaa).

    "—" quando não há data prevista de término: dias <= 0, sem consumo (sentinela
    `PREVISAO_RUPTURA_SEM_RISCO`) ou valor não numérico. `hoje` é injetável p/ teste."""
    try:
        d = int(dias)
    except (ValueError, TypeError):
        return "—"
    if d <= 0 or d >= PREVISAO_RUPTURA_SEM_RISCO:
        return "—"
    base = hoje or date.today()
    return (base + timedelta(days=d)).strftime("%d/%m/%Y")


# ── Predicados dos filtros rápidos (pills) ────────────────────────────────────

def _pill_status_contem(termo):
    """Fábrica de predicado: linhas cujo status (material) contém `termo` (ex.: 'COMPRAR')."""
    def _pred(df):
        col = "status_material" if "status_material" in df.columns else "status_display"
        if col not in df.columns:
            return pd.Series(True, index=df.index)
        return df[col].astype(str).str.contains(termo, na=False)
    return _pred


def _pill_nao_inventariado(df):
    """Linhas ainda não inventariadas (sem `data_inventario`)."""
    if "data_inventario" not in df.columns:
        return pd.Series(True, index=df.index)
    return ~(df["data_inventario"].fillna("").astype(str).str.strip().str.len() > 0)


_FILTROS_RAPIDOS = {
    "🔴 A comprar": _pill_status_contem("COMPRAR"),
    "🟡 Atenção": _pill_status_contem("ATENÇÃO"),
    "Não inventariados": _pill_nao_inventariado,
}
_AVANCADOS = {"multiselect": [
    ("Localização", "local_armazenagem"),
    ("Importância", "importancia"),
    ("Tipo", "tipo_material"),
    ("Status", "status_material"),
]}
_COLS_TABELA = [
    "part_number", "nome_item", "importancia", "unidade", "tipo_material",
    "local_armazenagem", "local_armazenagem_2",
    "estoque_minimo", "estoque_maximo", "estoque_atual",
    "status_material", "data_inventario", "lead_time_dias", "caixa_identificacao",
]
_COLUNAS_CONFIG = {
    "part_number": st.column_config.TextColumn("PN", width="small"),
    "nome_item": st.column_config.TextColumn("Nome", width="medium"),
    "unidade": st.column_config.TextColumn("UN", width="small"),
    "tipo_material": st.column_config.TextColumn("TIPO", width="small"),
    "local_armazenagem": st.column_config.TextColumn("Localidade", width="small"),
    "local_armazenagem_2": st.column_config.TextColumn(
        "Localidade (2ª)", width="small",
        help="2º ponto de armazenagem do mesmo item (quando houver)."),
    "estoque_minimo": st.column_config.NumberColumn("Mínimo", format="%d"),
    "estoque_maximo": st.column_config.NumberColumn("Máximo", format="%d"),
    "estoque_atual": st.column_config.NumberColumn("Estoque", format="%d"),
    "status_material": st.column_config.TextColumn("Status Material", width="small"),
    "Acaba em": st.column_config.TextColumn(
        "Acaba em", width="small",
        help="Data estimada em que o estoque zera, no ritmo de consumo atual "
             "(hoje + dias de cobertura). '—' = sem consumo registrado, sem data prevista."),
    "data_inventario": st.column_config.TextColumn("Inventariado", width="small"),
    "lead_time_dias": st.column_config.NumberColumn("Lead Time", format="%d"),
    "caixa_identificacao": st.column_config.TextColumn("Obs. Inventário", width="medium"),
    "Demanda": st.column_config.TextColumn(
        "Tipo de Demanda", width="small",
        help="Padrão de demanda (Syntetos-Boylan) pelas saídas reais: Suave/Intermitente/"
             "Errático/Irregular. Diagnóstico — não altera a reposição. Detalhe na Ficha 360."),
}


def render() -> None:
    st.title(":material/assignment: Saldo em Estoque")
    itens = inventario_cached()
    if not itens:
        st.info("Nenhum item cadastrado. Vá em **:material/add: Gerenciar Itens** para começar.")
        return

    df = pd.DataFrame(itens)

    # --- CONTAINER 1: FILTROS (padronizados p/ barra_filtros — F4a) ---
    with st.container(border=True):
        df = barra_filtros(
            df, chave="saldo",
            campos_pesquisa=["part_number", "nome_item"],
            filtros_rapidos=_FILTROS_RAPIDOS, avancados=_AVANCADOS)

    # --- CONTAINER 2: TABELA PRINCIPAL ---
    with st.container(border=True):
        cols_show = [c for c in _COLS_TABELA if c in df.columns]
        df_exib = df[cols_show].copy()
        if "data_inventario" in df_exib.columns:
            df_exib["data_inventario"] = df_exib["data_inventario"].apply(lambda v: fmt(v) if v else "—")
        # v4.1.0: "Acaba em" = data estimada de ruptura (hoje + dias de cobertura).
        if "previsao_ruptura_dias" in df.columns:
            df_exib["Acaba em"] = df["previsao_ruptura_dias"].apply(acaba_em)
        # v2.10.0 (diagnóstico): padrão de demanda (SBC) derivado das saídas reais.
        if "padrao_demanda" in df.columns:
            df_exib["Demanda"] = df["padrao_demanda"].fillna("—")

        tabela_paginada(df_exib, chave="saldo_tabela",
                        colunas_config=_COLUNAS_CONFIG, page_size=50)

    # --- CONTAINER 3: CONTAGEM FÍSICA ---
    with st.container(border=True):
        st.subheader(":material/inventory_2: Realizar Contagem Física")
        _, item_inv, _ = sel_material("Selecione o item para atualizar saldo/localização", "sel_inventario")

        if item_inv:
            st.info(f"**Item:** `{item_inv['part_number']} — {item_inv['nome_item']}` | **Saldo Atual:** `{item_inv['estoque_atual']} {item_inv.get('unidade','UN')}`")

            # Carrega locais disponíveis
            locais_disp = listar_valores("local") or ["Geral"]
            if item_inv.get("local_armazenagem") and item_inv.get("local_armazenagem") not in locais_disp:
                locais_disp.insert(0, item_inv["local_armazenagem"])

            c_q, c_l, c_l2 = st.columns(3)

            # Inicializa com o estoque atual. Se for 0, começa em 0.
            nova_qtd = c_q.number_input("Quantidade Real", min_value=0.0, step=1.0, value=float(item_inv['estoque_atual']))

            # Selectbox de Local (Obrigatório)
            local_atual = item_inv.get("local_armazenagem")
            idx_local_inicial = 0
            if local_atual and local_atual in locais_disp:
                idx_local_inicial = locais_disp.index(local_atual)

            novo_local = c_l.selectbox("Local (1ª Locação)", options=locais_disp, index=idx_local_inicial)

            # v3.4.0: 2ª locação (opcional) — 2º ponto de armazenagem do mesmo item,
            # independente do Ajuste Rápido de Movimentações (que permanece intacto).
            _op_l2 = [""] + locais_disp
            _l2_atual = item_inv.get("local_armazenagem_2") or ""
            _idx_l2 = _op_l2.index(_l2_atual) if _l2_atual in _op_l2 else 0
            novo_local_2 = c_l2.selectbox(
                "Local (2ª Locação)", options=_op_l2, index=_idx_l2,
                help="Opcional — 2º ponto de armazenagem do mesmo item. Deixe em branco se não houver.")

            # ✅ NOVO CAMPO: Observação Operacional (Texto Livre)
            obs_inventario = st.text_input(
                ":material/edit_note: Observação de Inventário",
                value=item_inv.get("caixa_identificacao") or "",
                placeholder="Ex: material danificado, sem etiqueta, divergência física, caixa avariada..."
            )

            col_btn1, col_btn2, _ = st.columns([1, 1, 2])

            if col_btn1.button(":material/check_circle: Confirmar Contagem", type="primary", width="stretch"):
                delta = nova_qtd - item_inv['estoque_atual']

                # Verifica mudanças operacionais
                mudou_local = (novo_local != item_inv.get("local_armazenagem"))
                _l2_val = None if not novo_local_2 else novo_local_2
                _l2_norm = _l2_val or ""
                mudou_local2 = (_l2_norm != (item_inv.get("local_armazenagem_2") or ""))
                mudou_obs = (obs_inventario.strip() != (item_inv.get("caixa_identificacao") or "").strip())
                mudou_qtd = (delta != 0)

                # Se nada mudou, avisa o usuário
                if not mudou_qtd and not mudou_local and not mudou_local2 and not mudou_obs:
                    st.warning(":material/warning: Nenhuma alteração detectada. O item já está com esses dados.")
                else:
                    # 1. Atualiza sempre os metadados (Local, 2ª Locação e Obs) e marca como inventariado
                    ok_loc, msg_loc = atualizar_localizacao_e_inventariar(
                        item_inv["id"], novo_local, obs_inventario, novo_local_2=_l2_val)

                    if ok_loc:
                        # 2. Lógica de Movimentação (Histórico)
                        # Precisamos registrar no histórico se houve mudança de QTD OU de Metadados (Local/Obs)

                        obs_partes = []
                        if mudou_local:
                            obs_partes.append(f"Local: {item_inv.get('local_armazenagem','N/A')} → {novo_local}")
                        if mudou_local2:
                            obs_partes.append(f"2ª Locação: '{item_inv.get('local_armazenagem_2') or ''}' → '{_l2_norm}'")
                        if mudou_obs:
                            obs_partes.append(f"Obs: '{item_inv.get('caixa_identificacao','')}' → '{obs_inventario}'")

                        # Se houve mudança de quantidade, registramos entrada/saída normal
                        if mudou_qtd:
                            tipo_aj = "entrada" if delta > 0 else "saida"
                            qtd_reg = abs(delta)

                            obs_final = f"Ajuste Físico {' | '.join(obs_partes)} | Qtd: {item_inv['estoque_atual']} → {nova_qtd}"

                            registrar_movimentacao(
                                item_id=item_inv["id"], tipo=tipo_aj, quantidade=qtd_reg,
                                centro_custo="INVENTÁRIO", solicitante="Inventário", emitente="Inventário",
                                observacao=obs_final
                            )

                        # ✅ CORREÇÃO: Se NÃO mudou quantidade, mas mudou Local/Obs, registramos uma "Conferência"
                        # Usamos tipo 'entrada' com qtd 0 apenas para gerar o log histórico,
                        # pois a tabela exige um tipo válido.
                        elif mudou_local or mudou_local2 or mudou_obs:
                            obs_final = f"Conferência de Inventário (Sem alteração de Qtd) {' | '.join(obs_partes)}"

                            registrar_movimentacao(
                                item_id=item_inv["id"], tipo="entrada", quantidade=0.0,  # Qtd 0 para não alterar saldo
                                centro_custo="INVENTÁRIO", solicitante="Inventário", emitente="Inventário",
                                observacao=obs_final
                            )

                        invalidar_leituras()
                        st.success(f":material/check_circle: Contagem registrada! Novo saldo: `{nova_qtd}`")
                        time.sleep(1.2)
                        st.rerun()
                    else:
                        st.error(f":material/cancel: Erro ao atualizar localização: {msg_loc}")

            if item_inv.get("data_inventario") and col_btn2.button(":material/cancel: Remover Marcação", width="stretch"):
                desmarcar_inventariado(item_inv["id"])
                invalidar_leituras()
                st.warning("Marcação de inventário removida.")
                time.sleep(1.2)
                st.rerun()

    # --- EXPORTAÇÃO ---
    st.markdown("---")
    col_exp, _, _ = st.columns([1, 3, 1])
    with col_exp:
        df_exp = exportar_inventario_df()
        if not df_exp.empty:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df_exp.to_excel(w, index=False, sheet_name="Inventário")
            st.download_button(
                "⬇️ Exportar todos os itens para planilha Excel", data=buf.getvalue(),
                file_name=f"inventario_mro_{date.today().strftime('%d-%m-%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Baixa a planilha Excel com TODOS os itens do inventário e seus indicadores."
            )
