"""Página Controle de SC (v5.3.0 / F4a) — 8 abas de acompanhamento das SCs.

Migrada do bloco inline do `app.py` (último checkpoint da F4a). Abas: Monitor ·
Guarda-Chuva · Assistente de Reposição · Fornecedores & Cotação · Nova SC ·
Detalhes SC · Histórico · Importar Relatório de SCs.

Migração FIEL: nenhuma regra de negócio, cálculo ou layout muda. A aba **Monitor**
mantém o aviso apontando para a página **SCM Integrado** — a UI de sincronização
"Atualizar agora" migrou para lá na F3 e NÃO deve ser reintroduzida aqui.

Cache: as escritas de SC/guarda-chuva chamam `invalidar_leituras()` para que as telas
cacheadas (Dashboard, Saldo, sidebar) não exibam contagem/estoque velhos.
"""

from __future__ import annotations

import io
import math
import os
import time
import urllib.parse
from datetime import date, datetime

import pandas as pd
import streamlit as st

from services import scm_client
from services.constants import PREVISAO_RUPTURA_SEM_RISCO, STATUS_SC
from services.db_functions import (
    GUARDA_CHUVA_ESTAGIOS,
    atualizar_guarda_chuva,
    atualizar_sc,
    carregar_planilha_livre,
    criar_guarda_chuva,
    criar_sc,
    filtrar_itens_por_busca,
    importar_relatorio_scs,
    importar_solicitacoes_protheus,
    itens_com_sc_aberta,
    listar_guarda_chuva,
    listar_inventario,
    listar_itens_sc,
    listar_monitor_sc,
    listar_recebimentos_sc,
    listar_scs,
    listar_valores,
    obter_cadastro_mro_para_cruzamento,
    obter_fornecedores_por_item,
    obter_guarda_chuva,
    registrar_recebimento_guarda_chuva,
    remover_guarda_chuva,
    saldo_total_por_material,
    salvar_planilha_livre,
    setor_dominante_por_item,
    sincronizar_monitor_sc,
)
from services.monitor_cruzamento import cruzar_scm_sc7, preparar_df
from services.monitor_scm import (
    COLUNAS_SCS_NAO_ATENDIDAS,
    cotacoes_no_escopo,
    montar_scs_nao_atendidas,
)
from services.planejamento import (
    agrupar_por_tipo_material,
    buscar_sc_id_por_numero,
    gerar_sugestoes_reposicao,
    registrar_desfecho_sugestao,
    resumir_grupo_sc,
    sugestao_para_item_sc,
)
from ui.cache import invalidar_leituras
from ui.componentes.selecao import sel_material
from ui.formatos import fmt, fmt_date_input


def render() -> None:
    st.title(":material/receipt_long: Controle de SC")

    # Estrutura de abas mantida conforme solicitado
    # v3.8.0 — "Receber Material" saiu daqui (agora vive na Movimentação).
    # v4.9.0 — "☂️ Guarda-Chuva" (controle manual) entrou logo após o Monitor. 8 abas.
    aba_mon, aba_gc, aba_assist, aba_forn, aba_nova_sc, aba_ed, aba_h, aba_import = st.tabs(
        [
            ":material/sensors: Monitor",
            ":material/umbrella: Guarda-Chuva",
            ":material/psychology: Assistente de Reposição",
            ":material/apartment: Fornecedores & Cotação",
            ":material/add: Nova SC",
            ":material/sync: Detalhes SC",
            ":material/history: Histórico",
            ":material/download: Importar Relatório de SCs",
        ]
    )

    # ══════════════════════════════════════════════════════════════════════════════
    # ☂️ GUARDA-CHUVA (controle manual — v4.9.0)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_gc:
        _render_guarda_chuva_controle()
        if st.session_state.get("_gc_manual_edit"):
            _dialog_guarda_chuva()
    # ══════════════════════════════════════════════════════════════════════════════
    # 📡 MONITOR DE COMPRAS
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_mon:
        # v4.11.0 — Monitor reordenado: (1) Controle Manual de Críticos (topo), (2) SCs/Itens
        # não atendidos via API do SCM, (3) fallback de cruzamento por upload (sem rede). A
        # grade técnica de 15 linhas (sync diário) saiu da UI — o vivo do SCM a substitui;
        # `sincronizar_monitor_sc`/`listar_monitor_sc` seguem no db_functions só p/ regressão.
        # v5.2.0 (F3) — a sincronização SCM (API → banco) e a consulta das SCs migraram para
        # a página **SCM Integrado** (menu, abaixo de Controle de SC).
        _render_controle_manual_criticos()
        st.divider()
        st.info(
            ":material/cloud_sync: A **sincronização SCM (API → banco)** e a consulta "
            "unificada das SCs agora vivem na página **SCM Integrado** (menu lateral)."
        )
        st.divider()
        _render_scs_nao_atendidas()
        st.divider()
        _render_cruzamento_upload_fallback()

    # ══════════════════════════════════════════════════════════════════════════════
    #   📥 IMPORTAR PROTHEUS
    # ═══════════════════════════════════════════════════════════════════════════════
    with aba_import:
        with st.container(border=True):
            st.markdown("### :material/download: Importar Relatório de SCs")
            st.caption(
                "Upload da planilha diária dos compradores. Roteia por aba: **SCM** (SCs + preço), "
                "**SC7** (histórico de preços), **FORNECEDORES** (cadastro + e-mails) e **SCM USERS** "
                "(solicitantes). Upsert com histórico preservado; backup automático antes de gravar."
            )
            arquivo = st.file_uploader(
                "Arquivo Excel (.xlsx / .xls)", type=["xlsx", "xls"], key="upload_relatorio_scs"
            )

            if arquivo:
                if st.button(":material/sync: Processar Relatório de SCs", width="stretch", type="primary"):
                    with st.spinner("Processando abas do Relatório de SCs..."):
                        ok, resultado = importar_relatorio_scs(arquivo, arquivo.name)
                    if ok:
                        invalidar_leituras()
                        # v3.9.0 — refaz o sync do Monitor de SC para refletir o import na hora.
                        try:
                            sincronizar_monitor_sc(force=True)
                        except Exception:
                            pass
                        scm = resultado.get("SCM", {}) or {}
                        if isinstance(scm, dict) and not scm.get("erro"):
                            st.markdown("**:material/description: SCM — Solicitações + Preço**")
                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric(":material/download: Importadas", scm.get("linhas_importadas", 0))
                            m2.metric(":material/block: Ignoradas", scm.get("linhas_ignoradas", 0))
                            m3.metric(":material/attach_money: Preços", scm.get("precos_capturados", 0))
                            m4.metric("🔴 Rupturas", scm.get("rupturas", 0))
                            m5, m6, m7, m8 = st.columns(4)
                            m5.metric(":material/description: SCs Criadas", scm.get("scs_criadas", 0))
                            m6.metric(":material/sync: SCs Atualizadas", scm.get("scs_atualizadas", 0))
                            m7.metric(":material/warning: Divergências", scm.get("divergencias", 0))
                            m8.metric(":material/local_fire_department: Críticos", scm.get("criticos", 0))

                        st.markdown("**:material/link: Demais fontes**")
                        sc7 = resultado.get("SC7", {}) or {}
                        forn = resultado.get("FORNECEDORES", {}) or {}
                        usr = resultado.get("SCM USERS", {}) or {}
                        c1, c2, c3 = st.columns(3)
                        c1.metric(
                            ":material/attach_money: Preços SC7",
                            sc7.get("precos_inseridos", 0) if isinstance(sc7, dict) else 0,
                        )
                        c2.metric(
                            ":material/apartment: Fornecedores",
                            f"{forn.get('upserted', 0)}" if isinstance(forn, dict) else "—",
                            help=f"Com e-mail: {forn.get('com_email', 0)}"
                            if isinstance(forn, dict)
                            else None,
                        )
                        c3.metric(
                            ":material/group: Solicitantes",
                            usr.get("upserted", 0) if isinstance(usr, dict) else 0,
                        )

                        erros = {
                            aba: r.get("erro")
                            for aba, r in resultado.items()
                            if isinstance(r, dict) and r.get("erro")
                        }
                        if erros:
                            st.warning(
                                "Abas com aviso: " + " · ".join(f"**{a}**: {e}" for a, e in erros.items())
                            )
                        if isinstance(scm, dict) and scm.get("ignorados_amostra"):
                            with st.expander("Amostra de linhas ignoradas (SCM)"):
                                st.dataframe(
                                    pd.DataFrame(scm["ignorados_amostra"]), width="stretch", hide_index=True
                                )
                        st.success(
                            f":material/check_circle: Importação concluída. Foto de estoque do dia: "
                            f"{resultado.get('_snapshot_criados', 0)} itens."
                        )
                    else:
                        erros = {
                            aba: r.get("erro")
                            for aba, r in resultado.items()
                            if isinstance(r, dict) and r.get("erro")
                        }
                        st.error(
                            ":material/cancel: Falha ao importar. "
                            + ("; ".join(f"{a}: {e}" for a, e in erros.items()) if erros else str(resultado))
                        )

            with st.expander("↩️ Importação antiga (export cru do SCM — fallback)"):
                arq_old = st.file_uploader(
                    "Arquivo Excel (export cru)", type=["xlsx", "xls"], key="upload_protheus_legacy"
                )
                if arq_old and st.button("Processar (fallback)", key="btn_import_legacy"):
                    with st.spinner("Processando..."):
                        ok_o, res_o = importar_solicitacoes_protheus(arq_old, arq_old.name)
                    if ok_o:
                        invalidar_leituras()
                        st.success(f"Importado: {res_o.get('linhas_importadas', 0)} linhas.")
                    else:
                        st.error(f"Falha: {res_o.get('erro', 'erro')}")
    # ══════════════════════════════════════════════════════════════════════════════
    #   🏢 FORNECEDORES & COTAÇÃO (v2.4.0) — busca material → fornecedores/preços,
    #   melhor fornecedor (menor último preço), lead time por fornecedor e rascunho
    #   de e-mail. Assistente: o sistema prepara a cotação; o comprador revisa e ENVIA.
    # ══════════════════════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════════════════════
    #   🧠 ASSISTENTE DE REPOSIÇÃO (v2.5.0) — recomenda o quê/quando/quanto/de quem;
    #   o comprador decide e cria a SC. Nada sobrescreve a base do Neidson.
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_assist:
        st.markdown("### :material/psychology: Assistente de Reposição")
        st.caption(
            "Fila priorizada do que repor — o quê, quando, quanto, por quê e de quem. "
            "O sistema **recomenda**; o comprador decide e cria a SC. Nada aqui "
            "sobrescreve a base do Compras (mín/máx/lead time/categoria)."
        )

        incluir_sem_mov = st.checkbox(
            "⚪ Mostrar itens sem movimentação (revisão)",
            value=False,
            key="rep_incl_semmov",
            help="Por padrão, itens que nunca tiveram consumo real ficam fora da fila. "
            "Marque para revisá-los — inclui os spares 'Parada de Linha' que o "
            "Compras estoca sem giro.",
        )

        with st.spinner("Calculando sugestões de reposição…"):
            sugestoes = gerar_sugestoes_reposicao(incluir_sem_movimentacao=incluir_sem_mov)

        # v3.7.0 — Setor DOMINANTE (derivado do consumo real) no lugar do
        # `setor_responsavel` (98% "Improdutivo", inútil); e Qtd Sugerida = MÁXIMO
        # cadastrado do material (decisão D2). Fallback ao híbrido só quando não há
        # máximo resolvido (> 0), para nunca criar SC com quantidade 0.
        _setor_dom = setor_dominante_por_item([s["item_id"] for s in sugestoes])
        for s in sugestoes:
            s["setor"] = _setor_dom.get(s["item_id"], "—")
            _qmax = int(math.ceil(s.get("estoque_maximo") or 0))
            if _qmax > 0:
                s["qtd_sugerida"] = _qmax

        if not sugestoes:
            st.success(
                ":material/check_circle: Nenhuma reposição necessária agora. Estoque + saldo "
                "residual cobrem o horizonte planejado para todos os itens."
            )
        else:
            # --- Filtros ---
            # v3.10.0: a fila do Assistente mostra SÓ material CRÍTICO (no/abaixo do ROP)
            # e que AINDA não tem SC aberta — é exatamente o que precisa virar SC agora.
            _itens_com_sc = itens_com_sc_aberta()
            base_criticos = [
                s for s in sugestoes if s["prioridade_tier"] == 0 and s["item_id"] not in _itens_com_sc
            ]

            setores = sorted({s["setor"] for s in base_criticos if s["setor"] and s["setor"] != "—"})
            f_setor = st.selectbox("Setor (consumo real)", ["Todos"] + setores, key="rep_setor")

            filtradas = base_criticos
            if f_setor != "Todos":
                filtradas = [s for s in filtradas if s["setor"] == f_setor]

            def _cate(s):
                """'Comprar até' formatado (⏰ = já atrasado; '—' = sem consumo)."""
                ca = s.get("comprar_ate")
                if not ca:
                    return "—"
                dd = datetime.strptime(ca, "%Y-%m-%d").strftime("%d/%m/%Y")
                return f"⏰ {dd}" if s.get("comprar_atrasado") else dd

            st.caption(
                f"🔴 **{len(filtradas)}** item(ns) crítico(s) sem SC — no/abaixo do ponto "
                "de pedido (ROP) e ainda sem SC aberta."
            )
            if not filtradas:
                st.success(
                    ":material/check_circle: Nenhum item crítico sem SC agora — tudo o que "
                    "está no/abaixo do ROP já tem SC aberta."
                )

            st.divider()

            # v3.4.0 — tabela ENRIQUECIDA + SELEÇÃO (pedido do §3): o comprador marca o
            # que entra nas "SCs sugeridas" (default: tudo). Colunas: estoque, mín, máx,
            # segurança (efetivo, c/ piso pelo mínimo), cobertura, consumo/dia+un, setores.
            def _linha_rep(s, incluir=None):
                d = {
                    "PN": s["part_number"],
                    "Item": s["nome_item"],
                    "Estoque": s.get("estoque_atual"),
                    "Mín": s.get("estoque_minimo"),
                    "Máx": s.get("estoque_maximo"),
                    "Cobertura(d)": (
                        s["cobertura_dias"] if s["cobertura_dias"] < PREVISAO_RUPTURA_SEM_RISCO else None
                    ),
                    "Consumo/dia": round(float(s.get("consumo_diario") or 0), 2),
                    "Un": s["unidade"],
                    "Comprar até": _cate(s),
                    "Setor": s.get("setor") or "—",
                    "Qtd Sugerida": s["qtd_sugerida"],
                    "Fornecedor (melhor preço)": s["fornecedor_sugerido"] or "—",
                }
                return {"Incluir": incluir, **d} if incluir is not None else d

            _num_cols = {
                "Estoque": "%.0f",
                "Mín": "%.0f",
                "Máx": "%.0f",
                "Cobertura(d)": "%.1f",
                "Consumo/dia": "%.2f",
                "Qtd Sugerida": "%d",
            }
            df_sel = pd.DataFrame([_linha_rep(s, incluir=True) for s in filtradas])
            edit_sel = st.data_editor(
                df_sel,
                hide_index=True,
                width="stretch",
                key="rep_sel_editor",
                column_config={
                    "Incluir": st.column_config.CheckboxColumn(
                        "Incluir", help="Marque os itens que entram nas SCs sugeridas abaixo."
                    ),
                    **{
                        c: st.column_config.NumberColumn(format=f, disabled=True)
                        for c, f in _num_cols.items()
                    },
                    **{
                        c: st.column_config.TextColumn(disabled=True)
                        for c in ("PN", "Item", "Un", "Comprar até", "Setor", "Fornecedor (melhor preço)")
                    },
                },
            )
            _incluir = list(edit_sel["Incluir"]) if "Incluir" in edit_sel else [True] * len(filtradas)
            selecionadas = [s for s, inc in zip(filtradas, _incluir) if inc]
            st.caption(
                f"**{len(selecionadas)}** de {len(filtradas)} itens selecionados · "
                "Qtd Sugerida = **Máximo** cadastrado do material · Setor = consumo real."
            )

            _df_export = pd.DataFrame([_linha_rep(s) for s in filtradas])
            buf_rep = io.BytesIO()
            with pd.ExcelWriter(buf_rep, engine="openpyxl") as w:
                _df_export.to_excel(w, index=False, sheet_name="Sugestões")
            exp1, exp2 = st.columns(2)
            exp1.download_button(
                "⬇️ Exportar sugestões (Excel)",
                data=buf_rep.getvalue(),
                file_name=f"reposicao_mro_{date.today():%d-%m-%Y}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="rep_export",
                width="stretch",
            )
            exp2.download_button(
                "⬇️ Exportar sugestões (CSV)",
                data=_df_export.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"reposicao_mro_{date.today():%d-%m-%Y}.csv",
                mime="text/csv",
                key="rep_export_csv",
                width="stretch",
            )

            # --- 📦 SCs sugeridas (agrupadas por TIPO DO MATERIAL) — "de mão beijada" ---
            st.divider()
            st.markdown("#### :material/inventory_2: SCs sugeridas")
            st.caption(
                "Itens juntados pelo **Tipo do material** (campo do cadastro do item), com "
                "título, justificativa e **centro de custo** sugeridos. Revise, edite e crie "
                "a SC agrupada em um clique — o sistema recomenda, você decide."
            )
            grupos_sc = agrupar_por_tipo_material(selecionadas)
            resumos = [
                resumir_grupo_sc(label, sugs, criterio="tipo de material")
                for label, sugs in grupos_sc.items()
            ]
            if not resumos:
                st.info("Marque ao menos um item na tabela acima para gerar as SCs sugeridas.")
            for gi, r in enumerate(resumos):
                label_curto = r["label"]
                cabecalho = f"{label_curto} · {r['n_itens']} itens · {r['prioridade']}"
                if r["comprar_ate_min"]:
                    cabecalho += " · comprar até " + datetime.strptime(
                        r["comprar_ate_min"], "%Y-%m-%d"
                    ).strftime("%d/%m")
                with st.expander(cabecalho, expanded=(gi == 0 and r["prioridade_tier"] == 0)):
                    st.dataframe(
                        pd.DataFrame([_linha_rep(s) for s in r["itens"]]),
                        hide_index=True,
                        width="stretch",
                        column_config={
                            c: st.column_config.NumberColumn(format=f) for c, f in _num_cols.items()
                        },
                    )
                    cap = f":material/sell: Centro de custo sugerido: **{r['cc_sugerido']}**"
                    if r["valor_estimado"] > 0:
                        cap += f"  ·  :material/payments: Valor estimado: ~R$ {r['valor_estimado']:,.2f}"
                    st.caption(cap)
                    with st.form(f"form_sc_grupo_{gi}", clear_on_submit=False):
                        gc1, gc2 = st.columns([2, 1])
                        titulo_g = gc1.text_input(
                            "Título da SC (tipo do material)", value=r["titulo"], key=f"sc_tit_{gi}"
                        )
                        num_sc_g = gc2.text_input(
                            "Número da SC *",
                            value=f"REP-{datetime.now():%Y%m%d-%H%M}-{gi + 1}",
                            key=f"sc_num_{gi}",
                        )
                        gc3, gc4 = st.columns([1, 1])
                        cc_g = gc3.text_input(
                            "Centro de custo (sugestão)", value=r["cc_sugerido"], key=f"sc_cc_{gi}"
                        )
                        dt_g = gc4.date_input("Data de abertura", value=date.today(), key=f"sc_dt_{gi}")
                        just_g = st.text_area(
                            "Justificativa", value=r["justificativa"], height=90, key=f"sc_just_{gi}"
                        )
                        criar_g = st.form_submit_button(
                            f":material/check_circle: Criar esta SC ({r['n_itens']} itens)",
                            type="primary",
                            width="stretch",
                        )
                    if criar_g:
                        if not num_sc_g.strip():
                            st.warning(":material/warning: Informe o número da SC.")
                        else:
                            itens_g = [
                                sugestao_para_item_sc(s, data_necessidade=str(date.today()))
                                for s in r["itens"]
                            ]
                            _snap = pd.DataFrame([_linha_rep(s) for s in r["itens"]]).to_string(index=False)
                            obs_g = (
                                f"{titulo_g}\nCentro de custo sugerido: {cc_g}\n\n{just_g}\n\n"
                                f"— Tabela de reposição (anexo) —\n{_snap}"
                            )
                            ok, msg = criar_sc(num_sc_g.strip(), str(dt_g), itens_g, obs_g)
                            if ok:
                                invalidar_leituras()
                                sc_id_g = buscar_sc_id_por_numero(num_sc_g.strip())
                                for s in r["itens"]:
                                    registrar_desfecho_sugestao(s, "criou_sc", sc_id=sc_id_g)
                                st.success(
                                    f":material/check_circle: {msg} Desfechos registrados no histórico."
                                )
                            else:
                                st.error(f":material/cancel: {msg}")

    with aba_forn:
        st.markdown("### :material/apartment: Fornecedores & Cotação")
        st.caption(
            "Busque um material para ver seus fornecedores, último preço e lead time, "
            "e gerar um e-mail de cotação pronto. O sistema recomenda; o comprador decide."
        )

        # v3.3.0 — busca única: o próprio select filtra por PN, nome OU descrição (o
        # rótulo inclui a descrição), eliminando o campo de busca redundante acima.
        opcoes_forn = {}
        for i in listar_inventario():
            desc = (i.get("descricao") or "").strip()
            rot = f"{i['part_number']} — {i['nome_item']}"
            if desc and desc.lower() not in (i.get("nome_item") or "").lower():
                rot += f" · {desc}"
            opcoes_forn[rot] = i
        lista_forn = [" "] + list(opcoes_forn.keys())
        sel_forn = st.selectbox(
            "Selecione o material (busque por PN, nome ou descrição)",
            lista_forn,
            index=0,
            key="forn_item_sel",
        )
        item_forn = opcoes_forn.get(sel_forn) if sel_forn != " " else None
        if not item_forn:
            st.info("Selecione um material para consultar os fornecedores.")
        else:
            lt_cad = int(item_forn.get("lead_time_dias") or 0)
            lt_calc = item_forn.get("lead_time_calculado")
            lt_calc_txt = (
                (
                    f" · Lead time calculado: {int(lt_calc)}d "
                    f"({item_forn.get('lead_time_calculado_amostras') or 0} amostras, "
                    f"{item_forn.get('lead_time_calculado_origem') or '—'})"
                )
                if lt_calc
                else ""
            )
            st.info(
                f"**{item_forn['part_number']} — {item_forn['nome_item']}**  \n"
                f"Saldo: {(item_forn.get('estoque_atual') or 0):g} {item_forn.get('unidade', '')} · "
                f"Mínimo: {(item_forn.get('estoque_minimo') or 0):g} · "
                f"Lead time cadastrado (Compras): {lt_cad}d{lt_calc_txt}"
            )

            fs = obter_fornecedores_por_item(item_forn["id"])
            if not fs:
                st.warning(
                    "Sem fornecedores para este item ainda. Os fornecedores vêm dos "
                    "pedidos importados no Relatório de SCs (Nome Fantasia por nº do pedido)."
                )
            else:
                melhor = next((f for f in fs if f.get("melhor")), None)
                if melhor:
                    st.success(
                        f":material/star: **Melhor fornecedor: {melhor['fornecedor']}** — {melhor['melhor_motivo']}. "
                        f"E-mail: {melhor['email'] or 'sem e-mail no cadastro'}."
                    )

                df_fs = pd.DataFrame(
                    [
                        {
                            "Fornecedor": f["fornecedor"],
                            "Último Preço": f["ultimo_preco"],
                            "Moeda": f["moeda"],
                            "Nº Compras": f["n_compras"],
                            "Última Compra": fmt(f["ultima_data"]),
                            "Lead Time (d)": f["lead_time_fornecedor"],
                            "E-mail": f["email"] or "—",
                            "Contato": f["contato"] or "—",
                            "Telefone": f["telefone"] or "—",
                            "Cadastro": ":material/check_circle:"
                            if f["no_cadastro"]
                            else ":material/warning:",
                        }
                        for f in fs
                    ]
                )
                st.dataframe(
                    df_fs,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Último Preço": st.column_config.NumberColumn(format="%.2f"),
                        "Lead Time (d)": st.column_config.NumberColumn(
                            format="%d",
                            help="Mediana do prazo real (SC7) atribuído ao fornecedor via nº do pedido.",
                        ),
                    },
                )
                st.caption(
                    "Ordenado por menor último preço. Lead time por fornecedor = mediana do "
                    "prazo real (SC7) atribuído pelo nº do pedido. ‘:material/warning:’ = fornecedor sem "
                    "correspondência no cadastro (sem e-mail para cotação)."
                )

                # --- Rascunho de cotação (não envia) ---
                st.markdown("#### :material/mail: Rascunho de cotação")
                nomes = [f["fornecedor"] for f in fs]
                default_sel = [melhor["fornecedor"]] if melhor else nomes[:1]
                sel_forn = st.multiselect(
                    "Fornecedores para cotar", nomes, default=default_sel, key="forn_cotar"
                )
                qtd_cotar = st.number_input(
                    "Quantidade a cotar",
                    min_value=0.0,
                    value=float(item_forn.get("estoque_minimo") or 0),
                    step=1.0,
                    key="forn_qtd",
                )
                prazo = st.text_input(
                    "Prazo desejado (opcional)", placeholder="Ex.: até 15 dias", key="forn_prazo"
                )

                escolhidos = [f for f in fs if f["fornecedor"] in sel_forn]
                emails = [f["email"] for f in escolhidos if f["email"]]
                sem_email = [f["fornecedor"] for f in escolhidos if not f["email"]]

                assunto = f"Cotação — {item_forn['part_number']} ({item_forn['nome_item']})"
                corpo = (
                    "Prezados,\n\n"
                    "Solicitamos cotação para o item abaixo:\n\n"
                    f"• Part Number: {item_forn['part_number']}\n"
                    f"• Descrição: {item_forn['nome_item']}\n"
                    f"• Quantidade: {qtd_cotar:g} {item_forn.get('unidade', '')}\n"
                    + (f"• Prazo desejado: {prazo}\n" if prazo else "")
                    + "\nFavor informar preço unitário, prazo de entrega e condições de pagamento.\n\n"
                    "Atenciosamente,\nCompras — Inventus Power"
                )
                st.text_area("Corpo do e-mail (copie ou edite)", corpo, height=220, key="forn_corpo")
                if emails:
                    st.markdown("**Destinatários:**")
                    st.code(", ".join(emails), language=None)
                    mailto = (
                        "mailto:"
                        + ",".join(emails)
                        + "?subject="
                        + urllib.parse.quote(assunto)
                        + "&body="
                        + urllib.parse.quote(corpo)
                    )
                    st.link_button(":material/mail: Abrir e-mail no meu cliente", mailto)
                elif escolhidos:
                    st.warning("Nenhum fornecedor selecionado tem e-mail no cadastro.")
                if sem_email:
                    st.caption("Sem e-mail no cadastro: " + ", ".join(sem_email))
                st.caption(
                    "O sistema **prepara** a cotação; o envio é feito pelo comprador, "
                    "no próprio cliente de e-mail."
                )
    # ══════════════════════════════════════════════════════════════════════════════
    #   ➕ NOVA SC (Formulário em Grid + Agrupamento Lógico)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_nova_sc:
        st.markdown("### :material/add: Nova SC")
        st.caption(
            "**Nova SC (caso não esteja no sistema MRO).** Cadastro manual de uma "
            "solicitação de compra que ainda não veio do Relatório de SCs."
        )
        if "itens_nova_sc" not in st.session_state:
            st.session_state.itens_nova_sc = []
        if "sc_criada" not in st.session_state:
            st.session_state.sc_criada = None

        if st.session_state.sc_criada:
            st.success(f":material/check_circle: {st.session_state.sc_criada}")
            if st.button(":material/add: Criar outra SC", width="stretch"):
                st.session_state.sc_criada = None
                st.rerun()
            st.stop()

        # UX: Seletor de material isolado
        _, item_sc_add, _ = sel_material("Selecionar Material", "sel_sc_add")

        with st.form("form_add_isc", clear_on_submit=True):
            st.markdown("##### :material/inventory_2: Adicionar Item à Lista ")
            c1, c2 = st.columns(2)
            # Apenas Quantidade e Data de Necessidade na criação
            qtd_i = c1.number_input("Qtd Solicitada *", min_value=0.01, step=1.0)
            d_nec = c2.date_input("Data de Necessidade *", value=date.today())

            obs_i = st.text_area(
                "Justificativa / Urgência", placeholder="Ex: Parada de linha iminente...", height=60
            )

            add_isc = st.form_submit_button(":material/add: Adicionar à Lista", width="stretch")

        if add_isc:
            if not item_sc_add:
                st.warning(":material/warning: Selecione um material antes de adicionar.")
            else:
                st.session_state.itens_nova_sc.append(
                    {
                        "item_id": item_sc_add["id"],
                        "part_number": item_sc_add["part_number"],
                        "nome_item": item_sc_add["nome_item"],
                        "quantidade_solicitada": qtd_i,
                        "quantidade_pedido": qtd_i,  # Inicialmente negociada = solicitada
                        "numero_po": "",  # Vazio na criação
                        "data_necessidade": str(d_nec) if d_nec else None,
                        "data_prev_nfe": None,  # Vazio na criação
                        "fornecedor_item": "",  # Vazio na criação
                        "observacao_item": obs_i,
                    }
                )
                st.rerun()

        if st.session_state.itens_nova_sc:
            st.markdown("###### :material/assignment: Itens Pré-cadastrados:")
            df_prev_sc = pd.DataFrame(st.session_state.itens_nova_sc)[
                ["part_number", "nome_item", "quantidade_solicitada", "data_necessidade"]
            ]
            df_prev_sc.columns = ["PN", "Nome", "Qtd Solic.", "Data Nec."]
            df_prev_sc["Data Nec."] = df_prev_sc["Data Nec."].apply(fmt)
            st.dataframe(df_prev_sc, width="stretch", hide_index=True)

            if st.button(":material/delete: Limpar Lista", type="secondary"):
                st.session_state.itens_nova_sc = []
                st.rerun()

        st.divider()
        with st.form("form_criar_sc"):
            st.markdown("##### :material/edit_note: Finalizar S.C. (Registro Inicial)")
            c1, c2 = st.columns(2)
            num_sc = c1.text_input("Número da SC *", placeholder="Ex: SC-2026-001")
            dt_ab = c2.date_input("Data de Abertura *", value=date.today())
            obs_sc = st.text_area("Observações Gerais", height=60)
            criar_b = st.form_submit_button(
                ":material/check_circle: Criar S.C.", width="stretch", type="primary"
            )

        if criar_b:
            if not num_sc.strip():
                st.warning(":material/warning: O Número da SC é obrigatório.")
            elif not st.session_state.itens_nova_sc:
                st.warning(":material/warning: Adicione ao menos um item à lista.")
            else:
                ok, msg = criar_sc(num_sc.strip(), str(dt_ab), st.session_state.itens_nova_sc, obs_sc)
                if ok:
                    invalidar_leituras()
                    st.session_state.itens_nova_sc = []
                    st.session_state.sc_criada = msg
                    st.rerun()
                else:
                    st.error(f":material/cancel: {msg}")

    # ══════════════════════════════════════════════════════════════════════════════
    # 🔄 ATUALIZAR STATUS E DADOS DA S.C. (Corrigido: Variáveis definidas antes do uso)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_ed:
        with st.container(border=True):
            st.markdown("### :material/sync: Atualizar Status e Dados da S.C.")
            st.caption(
                "Preencha as informações conforme elas chegarem (PO, Fornecedor, Previsões). O status será sugerido automaticamente."
            )

            scs_todas = listar_scs()
            opc_ed = {f"SC {s['numero_sc']} — {s['status']}": s for s in scs_todas} if scs_todas else {}
            sel_ed = (
                st.selectbox(
                    "Selecionar SC",
                    list(opc_ed.keys()),
                    index=None,
                    placeholder="Selecione a S.C.…",
                    label_visibility="collapsed",
                )
                if scs_todas
                else None
            )
            if not scs_todas:
                st.info("Nenhuma SC cadastrada para atualização.")
            elif sel_ed not in opc_ed:
                st.info("Selecione uma S.C. para editar seus dados.")
            else:
                sc_ed = opc_ed[sel_ed]

                # ✅ CORREÇÃO 1: Carregar fornecedores das configurações
                fornecedores_cfg = listar_valores("fornecedor") or [""]
                forn_atual = sc_ed.get("fornecedor") or ""
                if forn_atual and forn_atual not in fornecedores_cfg:
                    fornecedores_cfg.insert(0, forn_atual)

                idx_forn = fornecedores_cfg.index(forn_atual) if forn_atual in fornecedores_cfg else 0

                # ✅ CORREÇÃO 2: Carregar itens da SC AGORA, antes de usar na lógica de status
                itens_atuais = listar_itens_sc(sc_ed["id"])

                with st.form("form_ed_sc"):
                    st.markdown("##### :material/assignment: Informações Gerais (Cabeçalho)")

                    c1, c2 = st.columns(2)

                    # 1. Data de Aprovação (Gatilho para sair de 'Aguardando')
                    dt_aprovacao_val = fmt_date_input(sc_ed.get("data_aprovacao"))
                    dt_aprovacao = c1.date_input("Data de Aprovação/Cotação", value=dt_aprovacao_val)

                    # 2. Fornecedor Principal (Gatilho para 'Aguardando Entrega')
                    opcoes_forn = [""] + fornecedores_cfg
                    idx_select = idx_forn + 1 if forn_atual else 0
                    fornecedor_sel = c2.selectbox("Fornecedor Principal", opcoes_forn, index=idx_select)
                    forn_final = fornecedor_sel if fornecedor_sel != "" else None

                    # 3. PO Geral (Opcional, pois cada item pode ter seu PO)
                    n_po = st.text_input("Número PO Geral (Protheus)", value=sc_ed.get("numero_po") or "")

                    # 4. Observações
                    obs_ed = st.text_area(
                        "Observações Gerais", value=sc_ed.get("observacoes") or "", height=60
                    )

                    # ✅ LÓGICA DE SUGESTÃO DE STATUS INTELIGENTE (Usa itens_atuais definido acima)
                    status_atual_db = sc_ed["status"]
                    sugestao_status = status_atual_db

                    # Regra 1: Se tem Fornecedor E (PO Geral ou PO em algum item), sugere Aguardando Entrega
                    tem_po_geral = bool(n_po.strip())
                    # Verifica se algum item já tem PO preenchido (usando a variável carregada anteriormente)
                    tem_po_item = any(it.get("numero_po") for it in itens_atuais if it.get("numero_po"))

                    if (
                        forn_final
                        and (tem_po_geral or tem_po_item)
                        and status_atual_db not in ["Recebido", "Cancelado"]
                    ):
                        sugestao_status = "Aguardando Entrega"

                    # Regra 2: Se tem Data Aprovação mas não tem Fornecedor, sugere Em Cotação
                    elif dt_aprovacao and not forn_final and status_atual_db == "Aguardando Aprovação":
                        sugestao_status = "Em Cotação"

                    st_ed = st.selectbox(
                        "Status Atual (Sugestão Automática)",
                        STATUS_SC,
                        index=STATUS_SC.index(sugestao_status) if sugestao_status in STATUS_SC else 0,
                    )

                    st.divider()
                    st.markdown(
                        "##### :material/inventory_2: Detalhes dos Itens (PO, Fornecedor e Previsões por Item)"
                    )

                    itens_editados = []
                    # Loop pelos itens carregados anteriormente
                    for item_sc in itens_atuais:
                        with st.container(border=True):
                            st.markdown(f"`{item_sc['part_number']}` — **{item_sc['nome_item']}**")

                            ci1, ci2, ci3, ci4 = st.columns(4)
                            qtd_solic = ci1.number_input(
                                "Qtd Solic.",
                                min_value=0.0,
                                step=1.0,
                                value=float(item_sc.get("quantidade_solicitada") or 0),
                                key=f"ed_qs_{item_sc['id']}",
                            )
                            qtd_neg = ci2.number_input(
                                "Qtd Neg./Pedido",
                                min_value=0.0,
                                step=1.0,
                                value=float(
                                    item_sc.get("quantidade_pedido")
                                    or item_sc.get("quantidade_solicitada")
                                    or 0
                                ),
                                key=f"ed_qn_{item_sc['id']}",
                            )

                            # Campos cruciais para o status "Aguardando Entrega"
                            po_ind = ci3.text_input(
                                "PO Item", value=item_sc.get("numero_po") or "", key=f"ed_po_{item_sc['id']}"
                            )
                            forn_ind = ci4.text_input(
                                "Fornecedor Item",
                                value=item_sc.get("fornecedor_item") or "",
                                key=f"ed_forn_{item_sc['id']}",
                            )

                            ci5, ci6, ci7 = st.columns(3)
                            # Previsão de Entrega/NFe
                            prev_item_none = ci5.checkbox(
                                "Sem Previsão",
                                value=not bool(item_sc.get("data_prev_nfe")),
                                key=f"ed_prev_none_{item_sc['id']}",
                            )
                            prev_item = (
                                None
                                if prev_item_none
                                else ci5.date_input(
                                    "Previsão NFe/Entrega",
                                    value=fmt_date_input(item_sc.get("data_prev_nfe")),
                                    key=f"ed_prev_{item_sc['id']}",
                                )
                            )

                            nec_item = ci6.date_input(
                                "Data Necessidade",
                                value=fmt_date_input(item_sc.get("data_necessidade")),
                                key=f"ed_nec_{item_sc['id']}",
                            )
                            ci7.metric("Já Recebido", item_sc.get("quantidade_recebida") or 0)

                        itens_editados.append(
                            {
                                "item_sc_id": item_sc["id"],
                                "quantidade_solicitada": qtd_solic,
                                "quantidade_pedido": qtd_neg,
                                "quantidade_recebida": item_sc.get("quantidade_recebida") or 0,
                                "numero_po": po_ind,
                                "fornecedor_item": forn_ind,
                                "data_prev_nfe": str(prev_item) if prev_item else None,
                                "data_necessidade": str(nec_item) if nec_item else None,
                                "observacao_item": item_sc.get("observacao_item") or "",
                            }
                        )

                    salv_sc = st.form_submit_button(
                        ":material/save: Salvar Atualizações", width="stretch", type="primary"
                    )

                if salv_sc:
                    data_aprovacao_str = str(dt_aprovacao) if dt_aprovacao else None

                    ok, msg = atualizar_sc(
                        sc_ed["id"],
                        data_aprovacao_str,
                        n_po or None,
                        forn_final,
                        None,
                        st_ed,
                        obs_ed or None,
                        itens=itens_editados,
                    )

                    if ok:
                        invalidar_leituras()
                        st.success(
                            f":material/check_circle: **SC Atualizada!** Status definido como: `{st_ed}`"
                        )
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(f":material/cancel: {msg}")
    # ══════════════════════════════════════════════════════════════════════════════
    # 📜 HISTÓRICO (Lista Limpa + Detalhes em Caption)
    # ══════════════════════════════════════════════════════════════════════════════

    with aba_h:
        with st.container(border=True):
            st.markdown("### :material/history: Linha do Tempo de Recebimentos")
            st.caption(
                "Registro cronológico de entradas vinculadas a S.C. — quem "
                "entregou, quanto, contra qual PO e o que ainda falta na SC."
            )

            recebimentos = listar_recebimentos_sc(limit=300)
            if not recebimentos:
                st.info("ℹ️ Nenhum recebimento vinculado a SC encontrado no histórico.")
            else:
                _tot_qtd = sum(float(r["quantidade"] or 0) for r in recebimentos)
                _forns = len({(r["fornecedor"] or "").strip() for r in recebimentos if r["fornecedor"]})
                _rc = st.columns(3)
                _rc[0].metric("Recebimentos", len(recebimentos))
                _rc[1].metric("Qtd total recebida", f"{_tot_qtd:g}")
                _rc[2].metric("Fornecedores distintos", _forns)
                st.caption(f"Últimos {len(recebimentos)} recebimentos (mais recentes primeiro).")
                st.divider()

                from itertools import groupby

                for _dia, _grupo in groupby(recebimentos, key=lambda r: (r["data_hora"] or "")[:10]):
                    _grupo = list(_grupo)
                    st.markdown(f"#### :material/calendar_month: {fmt(_dia)} · {len(_grupo)} recebimento(s)")
                    for r in _grupo:
                        with st.container(border=True):
                            _un = r["unidade"] or "UN"
                            _pend = r.get("pendente")
                            _pend_txt = (
                                f"Ainda falta **{float(_pend):g} {_un}**"
                                if _pend is not None and float(_pend) > 0
                                else "**SC completa**"
                            )
                            _hora = (r["data_hora"] or "")[11:16] or "—"
                            st.markdown(
                                f"`{r['part_number']}` — **{r['nome_item']}**  |  "
                                f":material/add_box: **+{float(r['quantidade'] or 0):g} {_un}**"
                                f"  ·  {_pend_txt}"
                            )
                            _c1, _c2, _c3 = st.columns([3, 3, 2])
                            _c1.caption(f":material/apartment: **Fornecedor:** {r['fornecedor'] or '—'}")
                            _c2.caption(
                                f":material/receipt_long: **SC:** {r['numero_sc']} · "
                                f"**PO:** {r['numero_po'] or '—'} · "
                                f"**NF:** {r['documento_nf'] or '—'}"
                            )
                            _c3.caption(f":material/schedule: **{_hora}**")
                            _d1, _d2 = st.columns([3, 3])
                            _qs = r.get("qtd_solicitada")
                            _d1.caption(
                                f":material/inventory_2: Solicitado na SC: "
                                f"{_qs if _qs is not None else '—'} {_un}"
                            )
                            _d2.caption(
                                f":material/person: Recebido por: "
                                f"{r['emitente'] or '—'}"
                                + (f" · {r['observacao']}" if r["observacao"] else "")
                            )


# ══════════════════════════════════════════════════════════════════════════════
# ☂️ GUARDA-CHUVA MANUAL (v4.9.0) — controle próprio em Controle de SC
# ══════════════════════════════════════════════════════════════════════════════


def _render_guarda_chuva_controle():
    """v4.9.0 — Guarda-Chuva MANUAL: acordos de congelamento de preço por (produto +
    fornecedor) com entregas parciais. Controle 100% manual e desacoplado das SCs
    importadas (tabela `guarda_chuva`). Fluxo: adicionar produto (busca por PN/descrição)
    → adicionar código de fornecedor → kanban dos 4 estágios (editável) → 'Saldo total de
    todos os fornecedores' por material."""
    st.markdown("### :material/umbrella: Guarda-Chuva — saldo por fornecedor (controle manual)")
    st.caption(
        "Acordo com o fornecedor para **congelar o preço** de um produto e fazer um pedido "
        "com **entregas parciais** (ideal: X por mês, para não faturar tudo de uma vez). "
        "É um **controle manual**: cadastre o produto e o(s) fornecedor(es) e mova os cards "
        "pelos estágios. Serve para saber **quanto ainda temos de saldo** daquele material "
        "com **quais fornecedores**."
    )

    # ── Adicionar produto + código de fornecedor ──────────────────────────────
    with st.expander(":material/add: Adicionar um produto ao Guarda-Chuva", expanded=False):
        _busca = st.text_input("Pesquisar produto (part number ou descrição)", key="gc_busca_add")
        _itens = filtrar_itens_por_busca(listar_inventario(), _busca) if _busca else []
        if _busca and not _itens:
            st.warning("Nenhum material encontrado para a busca.")
        _opcoes = {f"{i['part_number']} — {i['nome_item']}": i["id"] for i in _itens[:50]}
        _sel = st.selectbox("Material", ["—"] + list(_opcoes.keys()), key="gc_sel_add", disabled=not _opcoes)
        with st.form("form_gc_add", clear_on_submit=True):
            st.markdown("**Adicionar código de fornecedor**")
            f1, f2 = st.columns(2)
            _cod = f1.text_input("Código do fornecedor *", key="gc_add_cod")
            _nome = f2.text_input("Nome do fornecedor (opcional)", key="gc_add_nome")
            f3, f4, f5 = st.columns(3)
            _qneg = f3.number_input("Qtd negociada", min_value=0.0, step=1.0, key="gc_add_qneg")
            _preco = f4.number_input("Preço congelado (R$)", min_value=0.0, step=0.01, key="gc_add_preco")
            _ideal = f5.number_input("Ideal por mês", min_value=0.0, step=1.0, key="gc_add_ideal")
            _add = st.form_submit_button(
                ":material/add: Adicionar ao Guarda-Chuva", type="primary", width="stretch"
            )
        if _add:
            _item_id = _opcoes.get(_sel)
            if not _item_id:
                st.error("Selecione um material (busque por PN ou descrição).")
            elif not (_cod or "").strip():
                st.error("Informe o código do fornecedor.")
            else:
                ok, res = criar_guarda_chuva(
                    _item_id,
                    _cod,
                    fornecedor_nome=(_nome or None),
                    qtd_negociada=_qneg,
                    preco_congelado=(_preco or None),
                    qtd_ideal_mes=(_ideal or None),
                )
                if ok:
                    invalidar_leituras()
                    st.success(":material/check_circle: Acordo adicionado ao Guarda-Chuva.")
                    st.rerun()
                else:
                    st.error(f":material/cancel: {res}")

    # ── Foco por material + saldo total de todos os fornecedores ──────────────
    _todos = listar_guarda_chuva()
    if not _todos:
        st.info("Nenhum acordo guarda-chuva cadastrado ainda. Use **Adicionar um produto** acima.")
        return

    _mats = {}
    for g in _todos:
        _mats.setdefault(g["item_id"], f"{g['part_number']} — {g['nome_item']}")
    _rotulos = {v: k for k, v in _mats.items()}
    _foco = st.selectbox("Material em foco", ["Todos"] + sorted(_rotulos.keys()), key="gc_foco")
    _foco_id = _rotulos.get(_foco)
    _linhas = _todos if _foco == "Todos" else [g for g in _todos if g["item_id"] == _foco_id]
    _un = (_linhas[0].get("unidade") or "") if _linhas else ""

    if _foco_id is not None:
        st.metric("Saldo total de todos os fornecedores", f"{saldo_total_por_material(_foco_id):g} {_un}")
    else:
        _tot = sum(max(float(g.get("saldo_residual") or 0), 0.0) for g in _todos)
        st.metric("Saldo total de todos os fornecedores (todos os materiais)", f"{_tot:g}")

    # ── Kanban dos 4 estágios (editável) ──────────────────────────────────────
    st.markdown("##### :material/view_kanban: Kanban de acordos (manual)")
    _cols = st.columns(len(GUARDA_CHUVA_ESTAGIOS))
    for _col, _nome in zip(_cols, GUARDA_CHUVA_ESTAGIOS):
        with _col:
            _grupo = [g for g in _linhas if (g.get("estagio") or "Pedido Colocado") == _nome]
            st.markdown(f"**{_nome}** · {len(_grupo)}")
            for g in _grupo:
                with st.container(border=True):
                    _u = g.get("unidade") or ""
                    st.caption(f"`{g.get('part_number') or '—'}`")
                    st.markdown(
                        f"**Forn. {g.get('fornecedor_codigo') or '—'}**"
                        + (f" · {g.get('fornecedor_nome')}" if g.get("fornecedor_nome") else "")
                    )
                    st.caption(
                        f"Neg. {(g.get('qtd_negociada') or 0):g} · "
                        f"Receb. {(g.get('qtd_recebida') or 0):g} · "
                        f"Saldo {(g.get('saldo_residual') or 0):g} {_u}"
                    )
                    if g.get("preco_congelado"):
                        st.caption(f":material/sell: R$ {float(g['preco_congelado']):.2f} congelado")
                    if st.button(":material/edit: Editar", key=f"gc_m_edit_{g['id']}", width="stretch"):
                        st.session_state["_gc_manual_edit"] = int(g["id"])
                        st.rerun()

    # ── Tabela: saldo por fornecedor ─────────────────────────────────────────
    st.markdown("##### :material/inventory: Saldo por fornecedor")
    _agg = {}
    for g in _linhas:
        _k = (g.get("fornecedor_codigo") or "—", g.get("fornecedor_nome") or "")
        _d = _agg.setdefault(_k, {"n": 0, "saldo": 0.0})
        _d["n"] += 1
        _d["saldo"] += max(float(g.get("saldo_residual") or 0), 0.0)
    if _agg:
        _df_gc = pd.DataFrame(
            [
                {
                    "Fornecedor (código)": k[0],
                    "Nome": k[1],
                    "Acordos": v["n"],
                    f"Saldo pendente ({_un})": round(v["saldo"], 2),
                }
                for k, v in _agg.items()
            ]
        )
        st.dataframe(_df_gc, width="stretch", hide_index=True)


def _clear_gc_manual_edit():
    st.session_state.pop("_gc_manual_edit", None)


@st.dialog("Acordo — Guarda-Chuva", width="large", on_dismiss=_clear_gc_manual_edit)
def _dialog_guarda_chuva():
    """v4.9.0 — Edita um acordo guarda-chuva (manual) e registra recebimento parcial. Relê
    do banco a cada render (`obter_guarda_chuva`). Controle manual: não toca estoque."""
    gc_id = st.session_state.get("_gc_manual_edit")
    g = obter_guarda_chuva(gc_id) if gc_id else None
    if not g:
        st.info("Acordo não encontrado (pode ter sido removido).")
        return
    un = g.get("unidade") or ""
    saldo = float(g.get("saldo_residual") or 0)
    st.markdown(f"`{g.get('part_number') or '—'}` — **{g.get('nome_item') or '—'}**")
    m1, m2, m3 = st.columns(3)
    m1.metric("Negociada", f"{(g.get('qtd_negociada') or 0):g} {un}")
    m2.metric("Recebida", f"{(g.get('qtd_recebida') or 0):g} {un}")
    m3.metric("Saldo", f"{saldo:g} {un}")

    with st.form("form_gc_manual"):
        st.markdown("##### :material/edit: Dados do acordo")
        c1, c2 = st.columns(2)
        cod = c1.text_input("Código do fornecedor", value=g.get("fornecedor_codigo") or "")
        nome = c2.text_input("Nome do fornecedor", value=g.get("fornecedor_nome") or "")
        qneg = c1.number_input(
            "Qtd negociada", min_value=0.0, step=1.0, value=float(g.get("qtd_negociada") or 0)
        )
        preco = c2.number_input(
            "Preço congelado (R$)", min_value=0.0, step=0.01, value=float(g.get("preco_congelado") or 0)
        )
        ideal = c1.number_input(
            "Ideal por mês", min_value=0.0, step=1.0, value=float(g.get("qtd_ideal_mes") or 0)
        )
        _est_idx = (
            list(GUARDA_CHUVA_ESTAGIOS).index(g["estagio"])
            if g.get("estagio") in GUARDA_CHUVA_ESTAGIOS
            else 0
        )
        estagio = c2.selectbox("Estágio", GUARDA_CHUVA_ESTAGIOS, index=_est_idx)
        po = c1.text_input("Nº PO (opcional)", value=g.get("numero_po") or "")
        obs = st.text_area("Observação", value=g.get("observacao") or "")
        salvar = st.form_submit_button(":material/save: Salvar dados", type="primary", width="stretch")
    if salvar:
        ok, msg = atualizar_guarda_chuva(
            gc_id,
            {
                "fornecedor_codigo": cod,
                "fornecedor_nome": nome,
                "qtd_negociada": qneg,
                "preco_congelado": preco,
                "qtd_ideal_mes": ideal,
                "estagio": estagio,
                "numero_po": po,
                "observacao": obs,
            },
        )
        if ok:
            invalidar_leituras()
            st.success(f":material/check_circle: {msg}")
            st.rerun()
        else:
            st.error(f":material/cancel: {msg}")

    # ── Recebimento parcial (manual) ──────────────────────────────────────────
    if saldo > 0:
        with st.form("form_gc_manual_receber"):
            st.markdown("##### :material/download: Registrar recebimento (parcial)")
            st.caption(
                "Controle manual — abate o saldo do acordo. NÃO mexe no estoque nem no "
                "histórico de movimentações."
            )
            qtd = st.number_input(
                f"Qtd a receber ({un})", min_value=0.0, max_value=saldo, value=saldo, step=1.0
            )
            receber = st.form_submit_button(
                ":material/download: Confirmar recebimento", type="primary", width="stretch"
            )
        if receber:
            ok, msg = registrar_recebimento_guarda_chuva(gc_id, float(qtd))
            if ok:
                invalidar_leituras()
                st.success(f":material/check_circle: {msg}")
                st.rerun()
            else:
                st.error(f":material/cancel: {msg}")

    st.divider()
    if st.button(":material/delete: Remover este acordo", key="gc_manual_remover"):
        ok, msg = remover_guarda_chuva(gc_id)
        if ok:
            invalidar_leituras()
            _clear_gc_manual_edit()
            st.rerun()
        else:
            st.error(f":material/cancel: {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# 📡 MONITOR DE SC (v4.11.0) — seções reordenadas: (1) Controle Manual de Críticos,
# (2) SCs/Itens não atendidos (via API SCM), (3) fallback de cruzamento por upload.
# ══════════════════════════════════════════════════════════════════════════════


def _render_controle_manual_criticos():
    """v4.11.0 — 'Controle Manual de Críticos' (ex-'Planilha livre'), no TOPO do Monitor:
    grade colável do Excel com colunas configuráveis. Persiste em `monitor_livre`."""
    st.markdown("### :material/edit_note: Controle Manual de Críticos")
    st.caption(
        "Cole um intervalo do Excel direto na grade — seu controle manual de itens "
        "críticos. As colunas começam como A, B, C…, mas você pode **criar** e "
        "**remover** colunas próprias (persistem junto com as linhas). **Crie as "
        "colunas antes de colar** os dados. A **1ª linha** vira o cabeçalho da "
        "pré-visualização abaixo."
    )

    def _mon_nz(v):
        return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v

    _pl = carregar_planilha_livre()
    if "pl_livre_cols" not in st.session_state:
        st.session_state.pl_livre_cols = _pl["colunas"] or list("ABCDEFGHIJ")
    _LIVRE_COLS = st.session_state.pl_livre_cols

    _pc1, _pc2 = st.columns([3, 1])
    with _pc1:
        _nova_col = st.text_input(
            "Nome da nova coluna",
            key="pl_nova_col",
            label_visibility="collapsed",
            placeholder="Nome da nova coluna",
        )
    with _pc2:
        if st.button("➕ Criar coluna", key="pl_criar_col", width="stretch"):
            _nome = (_nova_col or "").strip()
            if not _nome:
                st.warning("Digite um nome para a coluna.")
            elif _nome in _LIVRE_COLS:
                st.warning("Já existe uma coluna com esse nome.")
            else:
                st.session_state.pl_livre_cols = list(_LIVRE_COLS) + [_nome]
                st.rerun()
    _rem = st.multiselect("Remover coluna(s)", _LIVRE_COLS, key="pl_rem_cols")
    if st.button("🗑️ Remover coluna(s) selecionada(s)", key="pl_remover_col", disabled=not _rem):
        _restantes = [c for c in _LIVRE_COLS if c not in _rem]
        st.session_state.pl_livre_cols = _restantes or list("ABCDEFGHIJ")
        st.rerun()

    _linhas_pl = _pl["linhas"]
    if _linhas_pl:
        _df_livre = pd.DataFrame(_linhas_pl)
        for _c in _LIVRE_COLS:
            if _c not in _df_livre.columns:
                _df_livre[_c] = None
        _df_livre = _df_livre.reindex(columns=_LIVRE_COLS)
    else:
        _df_livre = pd.DataFrame({_c: pd.Series(dtype="object") for _c in _LIVRE_COLS})

    _livre_edit = st.data_editor(
        _df_livre,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        height=360,
        key="monitor_livre_editor__" + "|".join(_LIVRE_COLS),
    )

    if st.button("💾 Salvar Controle Manual de Críticos", key="monitor_livre_salvar"):
        _regs = [
            {_c: _mon_nz(r.get(_c)) for _c in _LIVRE_COLS}
            for _, r in _livre_edit.iterrows()
            if any(_mon_nz(r.get(_c)) is not None for _c in _LIVRE_COLS)
        ]
        _n = salvar_planilha_livre(_LIVRE_COLS, _regs)
        st.success(f":material/check_circle: Controle salvo ({_n} linha(s), {len(_LIVRE_COLS)} coluna(s)).")
        time.sleep(1.0)
        st.rerun()

    if len(_livre_edit) > 1:
        _prev = _livre_edit.reset_index(drop=True)
        _header = [str(x) if _mon_nz(x) is not None else "" for x in _prev.iloc[0].tolist()]
        _cols_final, _seen = [], {}
        for _i, _h in enumerate(_header):
            _name = _h or f"Col{_i + 1}"
            if _name in _seen:
                _seen[_name] += 1
                _name = f"{_name}_{_seen[_name]}"
            else:
                _seen[_name] = 0
            _cols_final.append(_name)
        _corpo = _prev.iloc[1:].copy()
        _corpo.columns = _cols_final
        st.caption("Pré-visualização (1ª linha como cabeçalho):")
        st.dataframe(_corpo, width="stretch", hide_index=True)


def _render_scs_nao_atendidas():
    """v4.11.0 — 'SCs/Itens não atendidos' via API do SCM: SCs do almoxarifado em fase de
    cotação (sem pedido) cruzadas com o estoque MRO. Read-only, carregado sob demanda."""
    st.markdown("### :material/assignment_late: SCs/Itens não atendidos")
    st.caption(
        "SCs do **almoxarifado** em **fase de cotação** (ainda sem pedido gerado), "
        "direto do **SCM**, cruzadas com o estoque MRO. **Status**, **Esgotado em** e "
        "**Faltando (d)** vêm do inventário (igual à aba 'Saldo em Estoque')."
    )

    _l1, _l2 = st.columns([3, 1])
    with _l2:
        _load = st.button(
            ":material/cloud_sync: Carregar/Atualizar do SCM", key="scs_na_load", width="stretch"
        )
    if _load:
        for _fn in (scm_client.cotacoes_em_andamento, scm_client.sc_timeline):
            try:
                _fn.clear()
            except Exception:
                pass
        if not scm_client.esta_disponivel():
            st.session_state["_scs_na_rows"] = "OFFLINE"
        else:
            with st.spinner("Consultando SCs em cotação no SCM…"):
                _solic_mro, _pns, _dep = obter_cadastro_mro_para_cruzamento()
                _lic = scm_client.cotacoes_em_andamento()
                _escopo = cotacoes_no_escopo(_lic, _solic_mro)
                _itens = {}
                for _c in _escopo:
                    _tl = scm_client.sc_timeline(_c["sc_id"]) or {}
                    _itens[_c["sc_id"]] = _tl.get("items") or []
                _inv = {
                    str(i["part_number"]).strip().upper(): {
                        "status_material": i.get("status_material"),
                        "unidade": i.get("unidade"),
                        "nome_item": i.get("nome_item"),
                        "previsao_ruptura_dias": i.get("previsao_ruptura_dias"),
                    }
                    for i in listar_inventario()
                }
                st.session_state["_scs_na_rows"] = montar_scs_nao_atendidas(_escopo, _itens, _inv)

    _rows = st.session_state.get("_scs_na_rows")
    if _rows is None:
        st.info(
            ":material/cloud: Clique em **Carregar/Atualizar do SCM** para buscar as SCs "
            "em cotação. (Requer rede até o SCM; senão use o fallback de upload abaixo.)"
        )
        return
    if _rows == "OFFLINE":
        st.warning(
            ":material/cloud_off: Não foi possível conectar ao SCM "
            "(`mansrvapp03:5715`). Use o **fallback de upload** abaixo."
        )
        return
    if not _rows:
        st.success(":material/check_circle: Nenhuma SC/Item do almoxarifado em cotação pendente.")
        return
    _df_na = pd.DataFrame(_rows, columns=COLUNAS_SCS_NAO_ATENDIDAS)
    st.caption(f"**{len(_df_na)}** item(ns) em cotação, do escopo do almoxarifado (mais urgente primeiro).")
    st.dataframe(
        _df_na,
        width="stretch",
        hide_index=True,
        height=460,
        column_config={
            "QTY Solicitada": st.column_config.NumberColumn(format="%.0f"),
            "Saldo PO": st.column_config.NumberColumn(format="%.0f"),
            "Faltando (d)": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    _buf = io.BytesIO()
    with pd.ExcelWriter(_buf, engine="openpyxl") as _w:
        _df_na.to_excel(_w, index=False, sheet_name="SCs nao atendidos")
    st.download_button(
        ":material/download: Baixar (Excel)",
        data=_buf.getvalue(),
        file_name="scs_nao_atendidos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="scs_na_dl",
    )


def _render_cruzamento_upload_fallback():
    """v4.11.0 — Fallback (sem rede ao SCM): cruzamento SCM × SC7 por UPLOAD manual (v4.6.0),
    dentro de um expander. Efêmero: nada é gravado no banco."""
    with st.expander(":material/cloud_off: Sem rede ao SCM? Cruzamento por upload (SCM × SC7)"):
        st.caption(
            "Alternativa manual à tabela acima: envie os **dois exports crus** — "
            "**SCM** (`Solicitações.xlsx`) e **SC7** (`Relatório de Compras.xlsx`) — e o "
            "sistema casa por **PO** + Produto. Traz só material do MRO. Efêmero."
        )
        _cz1, _cz2 = st.columns(2)
        with _cz1:
            _up_scm = st.file_uploader("SCM — Solicitações.xlsx (cru)", type=["xlsx", "xls"], key="cruz_scm")
        with _cz2:
            _up_sc7 = st.file_uploader(
                "SC7 — Relatório de Compras.xlsx (cru)", type=["xlsx", "xls"], key="cruz_sc7"
            )
        if not (_up_scm and _up_sc7):
            st.info(":material/upload: Envie os **dois** arquivos crus (SCM e SC7) para gerar o cruzamento.")
            return
        _df_scm, _meta_scm = preparar_df(_up_scm, "SCM")
        _df_sc7, _meta_sc7 = preparar_df(_up_sc7, "SC7")
        if _df_scm is None:
            st.error(f":material/error: {_meta_scm['erro']}")
            return
        if _df_sc7 is None:
            st.error(f":material/error: {_meta_sc7['erro']}")
            return
        _solic_mro, _pns_mro, _dep_solic = obter_cadastro_mro_para_cruzamento()
        _res = cruzar_scm_sc7(
            _df_scm, _df_sc7, solicitantes_mro=_solic_mro, pns_mro=_pns_mro, dep_por_solic=_dep_solic
        )
        if _res.get("erro"):
            st.error(f":material/error: {_res['erro']}")
            return
        _s = _res["stats"]
        _k1, _k2, _k3, _k4, _k5 = st.columns(5)
        _k1.metric("Casadas", _s["casadas"])
        _k2.metric("Sem pedido", _s["sem_pedido"])
        _k3.metric("PO sem SC7", _s["po_sem_sc7"])
        _k4.metric("Órfãos (PO s/ SC)", _s["orfaos"])
        _k5.metric("Saldo pendente", f"{_s['saldo_pendente_total']:,.0f}")
        st.caption(
            f"Fora do escopo MRO (ignoradas): **{_s['fora_escopo']}** linha(s) do SCM. "
            f"Lidas: SCM {_s['n_scm']} × SC7 {_s['n_sc7']} linhas."
        )
        _df_cruz = pd.DataFrame(_res["linhas"], columns=_res["colunas"])
        _dep_sel = st.selectbox("Filtrar por Departamento", ["Todos"] + _res["departamentos"], key="cruz_dep")
        if _dep_sel != "Todos":
            _df_cruz = _df_cruz[_df_cruz["Departamento"] == _dep_sel]
        if _df_cruz.empty:
            st.info("Nenhuma linha do MRO no cruzamento para o filtro atual.")
        else:
            st.dataframe(
                _df_cruz,
                width="stretch",
                hide_index=True,
                height=460,
                column_config={
                    "Qty (SC)": st.column_config.NumberColumn(format="%.0f"),
                    "Qtd Entregue": st.column_config.NumberColumn(format="%.0f"),
                    "Saldo": st.column_config.NumberColumn(format="%.0f"),
                },
            )
            _buf_cz = io.BytesIO()
            with pd.ExcelWriter(_buf_cz, engine="openpyxl") as _w_cz:
                _df_cruz.to_excel(_w_cz, index=False, sheet_name="Cruzamento")
            st.download_button(
                ":material/download: Baixar cruzamento (Excel)",
                data=_buf_cz.getvalue(),
                file_name="monitor_sc_2_cruzamento.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="cruz_download",
            )
        if _res["orfaos"]:
            with st.expander(f":material/warning: Órfãos — {len(_res['orfaos'])} PO(s) do SC7 sem SC no MRO"):
                st.caption("Compras (PO) de material MRO **sem SC correspondente** na planilha SCM.")
                st.dataframe(pd.DataFrame(_res["orfaos"]), width="stretch", hide_index=True)
