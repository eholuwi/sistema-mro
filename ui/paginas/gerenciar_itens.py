"""Página Gerenciar Itens MRO (v5.3.0 / F4a) — cadastro e edição de itens.

Migrada do bloco inline do `app.py`. É uma página de FORMULÁRIO (2 abas: Cadastrar
Novo / Editar Existente) — o item é escolhido por `sel_material` (selectbox), não há
lista/tabela navegável, então não há adoção de `barra_filtros`/`tabela_paginada`
aqui. Toda escrita (salvar/atualizar/alterar PN) chama `invalidar_leituras()` para
as telas cacheadas (Saldo/Dashboard/sidebar) não exibirem dado velho. Regra de
negócio (conversão de unidades, alteração de PN, lead time) preservada 1:1.
"""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from services.constants import (
    UNIDADES, TIPOS, IMPORTANCIAS, FATOR_CONVERSAO_PADRAO, UNIDADES_COMPRA_SUGERIDAS,
)
from services.db_functions import (
    listar_valores, listar_inventario, salvar_item, atualizar_item_inventario,
    alterar_part_number, listar_historico_part_number, sugerir_conversao,
)
from ui.cache import invalidar_leituras
from ui.formatos import fmt
from ui.componentes.selecao import sel_material, opcoes_com_atual


def render() -> None:
    st.title(":material/add: Gerenciar Itens MRO")

    # --- TABS PARA ORGANIZAÇÃO ---
    tab_editar, tab_novo = st.tabs([":material/edit: Editar Item Existente", ":material/fiber_new: Cadastrar Novo Item"])

    # === TAB 1: CADASTRAR NOVO ===
    with tab_novo:
        with st.container(border=True):
            st.subheader("Dados do Novo Item")
            c1, c2 = st.columns(2)

            with c1:
                pn_novo = st.text_input("Part Number (PN) *", placeholder="Ex: 12345-ABC")
                nome_novo = st.text_input("Nome do Item *", placeholder="Ex: Parafuso Sextavado M8")
                desc_novo = st.text_area("Observação", placeholder="Informações adicionais sobre o item", height=80)
                un_novo = st.selectbox("Unidade", UNIDADES, index=0)
                tipo_novo = st.selectbox("Tipo / Categoria", TIPOS, index=0)

            with c2:
                imp_novo = st.selectbox("Importância", IMPORTANCIAS, index=0)
                loc_novo = st.selectbox("Localidade", listar_valores("local") or ["Geral"], index=0)
                caixa_novo = st.selectbox("Caixa/ID", listar_valores("local") or ["Geral"], index=0)
                lead_novo = st.number_input("Lead Time (Dias)", min_value=1, value=20)

            c3, c4 = st.columns(2)
            min_novo = c3.number_input("Estoque Mínimo *", min_value=0, value=10)
            est_ini_novo = c4.number_input("Estoque Inicial", min_value=0.0, value=0.0)

            # ── Conversão de unidades (curadoria v2.9.0) — opcional ──────────────
            st.markdown("###### :material/sync: Conversão de unidades (se comprado em outra unidade)")
            _sug_novo = sugerir_conversao(
                {"nome_item": nome_novo, "descricao": desc_novo, "unidade": un_novo})
            cvn1, cvn2 = st.columns(2)
            uc_novo = cvn1.text_input(
                "Unidade de compra", value=(_sug_novo['unidade_compra_sugerida'] or un_novo),
                help="Unidade em que o fornecedor vende (L, KG, BB, par…). "
                     "Igual à de estoque se não houver diferença.")
            fator_novo = cvn2.number_input(
                "Fator de conversão", min_value=0.0,
                value=float(_sug_novo['fator_sugerido'] or 1.0), step=1.0,
                help="Quantas unidades de compra cabem em 1 de estoque. Ex.: 1 GL = 5 L → 5.")
            if _sug_novo['fator_sugerido']:
                st.caption(f":material/lightbulb: Sugestão automática pelo nome do item: {_sug_novo['origem']}.")

            if st.button(":material/save: Salvar Novo Item", type="primary", width="stretch"):
                if not pn_novo or not nome_novo:
                    st.error("Preencha Part Number e Nome.")
                else:
                    # Verificar duplicidade
                    itens_existentes = listar_inventario()
                    if any(i['part_number'].lower() == pn_novo.lower() for i in itens_existentes):
                        st.error(f"PN '{pn_novo}' já cadastrado!")
                    else:
                        ok, msg = salvar_item(
                            part_number=pn_novo,
                            nome_item=nome_novo,
                            descricao=desc_novo,
                            unidade=un_novo,
                            importancia=imp_novo,
                            tipo_material=tipo_novo,
                            setor="Improdutivo",
                            local=loc_novo,
                            caixa=caixa_novo,
                            estoque_atual=est_ini_novo,
                            estoque_minimo=min_novo,
                            lead_time=lead_novo,
                            unidade_compra=(uc_novo or "").strip() or None,
                            fator_conversao=fator_novo if fator_novo > 0 else FATOR_CONVERSAO_PADRAO,
                        )
                        if ok:
                            invalidar_leituras()
                            st.success(msg)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

    # === TAB 2: EDITAR EXISTENTE ===
    with tab_editar:
        with st.container(border=True):
            st.subheader("Selecionar Item para Edição")
            _, item_sel, _ = sel_material("Busque pelo PN ou Nome", "sel_edit_item")

            if item_sel:
                st.info(f"**Editando:** `{item_sel['part_number']} — {item_sel['nome_item']}`")
                if item_sel.get("unidade_divergente"):
                    st.warning(
                        ":material/warning: **Revisar unidade:** este item é comprado numa unidade diferente "
                        "da de estoque (visto nos POs). Defina a *unidade de compra* e o *fator* abaixo para que "
                        "o recebimento converta corretamente."
                    )
                ed_desc = st.text_area("Observação", value=item_sel.get('descricao', ''), height=70, key="ed_desc")

                st.markdown("---")

                c1, c2, c3 = st.columns(3)
                tipos_opts = opcoes_com_atual(TIPOS, item_sel.get('tipo_material'))
                locais_opts = listar_valores("local") or ["Geral"]
                with c1:
                    ed_un = st.selectbox("Unidade", UNIDADES, index=UNIDADES.index(item_sel['unidade']) if item_sel['unidade'] in UNIDADES else 0, key="ed_un")
                    ed_tipo = st.selectbox("Tipo / Categoria", tipos_opts, index=tipos_opts.index(item_sel['tipo_material']) if item_sel.get('tipo_material') in tipos_opts else 0, key="ed_tipo")
                    ed_imp = st.selectbox("Importância", IMPORTANCIAS, index=IMPORTANCIAS.index(item_sel['importancia']) if item_sel['importancia'] in IMPORTANCIAS else 0, key="ed_imp")

                with c2:
                    ed_loc = st.selectbox("Localidade", locais_opts,
                                          index=locais_opts.index(item_sel.get('local_armazenagem', 'Geral')) if item_sel.get('local_armazenagem') in locais_opts else 0, key="ed_loc")
                    # v4.5.6 — 2ª locação (opcional) editável aqui, além da Contagem Física.
                    _op_loc2 = [""] + locais_opts
                    _l2_atual = item_sel.get("local_armazenagem_2") or ""
                    if _l2_atual and _l2_atual not in _op_loc2:
                        _op_loc2.insert(1, _l2_atual)
                    ed_loc2 = st.selectbox(
                        "Localidade (2ª)", _op_loc2,
                        index=_op_loc2.index(_l2_atual) if _l2_atual in _op_loc2 else 0,
                        key="ed_loc2",
                        help="2º ponto de armazenagem do mesmo item (opcional). Deixe em branco se não houver.")
                    ed_caixa = st.selectbox("Caixa/ID", locais_opts,
                                            index=locais_opts.index(item_sel.get('caixa_identificacao', 'Geral')) if item_sel.get('caixa_identificacao') in locais_opts else 0, key="ed_caixa")
                    ed_lead = st.number_input("Lead Time (Dias)", min_value=0, value=int(item_sel.get('lead_time_dias') or 0), key="ed_lead")

                with c3:
                    ed_min = st.number_input("Estoque Mínimo (30 dias)", min_value=0.0, value=float(item_sel.get('estoque_minimo') or 0), key="ed_min")
                    ed_max = st.number_input("Estoque Máximo (60 dias)", min_value=0.0, value=float(item_sel.get('estoque_maximo') or 0), key="ed_max",
                                             help="0 = usa o cálculo automático (Mínimo × 2).")
                    # v3.7.0: Estoque de Segurança desativado — o buffer virou o próprio
                    # Mínimo do Neidson (não deixar atingir o mínimo nem passar do máximo).
                    # Nota: Estoque atual NÃO deve ser editado aqui, apenas via Movimentação/Inventário
                    st.markdown(f"**Estoque Atual:** `{item_sel['estoque_atual']}` (Alterar em *Inventário*)")
                    st.markdown(f"**Status:** `{item_sel['status_material']}`")

                # ── Conversão de unidades (curadoria v2.9.0) ─────────────────────
                st.markdown("---")
                st.markdown("##### :material/sync: Conversão de unidades (compra ↔ estoque)")
                _sug = sugerir_conversao(item_sel)
                _un_est = item_sel.get('unidade') or 'UN'
                _stored_fator = float(item_sel.get('fator_conversao') or 1.0)
                _stored_uc = item_sel.get('unidade_compra')
                # Item ainda não curado (fator=1 e sem UM de compra) → pré-preenche com
                # a sugestão; já curado → mostra o que o gestor gravou.
                _nao_curado = abs(_stored_fator - 1.0) < 1e-9 and not _stored_uc
                _def_uc = (_stored_uc or (_sug['unidade_compra_sugerida'] if _nao_curado else None)
                           or _un_est)
                _def_fator = (_sug['fator_sugerido'] or 1.0) if (_nao_curado and _sug['fator_sugerido']) else _stored_fator
                cvc1, cvc2 = st.columns([1, 1])
                ed_uc = cvc1.text_input(
                    "Unidade de compra", value=_def_uc, key="ed_uc",
                    help="Unidade em que o fornecedor vende (L, KG, BB, par…). "
                         "Deixe igual à de estoque se não houver diferença. "
                         f"Sugestões: {', '.join(UNIDADES_COMPRA_SUGERIDAS[:10])}…")
                ed_fator = cvc2.number_input(
                    "Fator de conversão", min_value=0.0, value=float(_def_fator), step=1.0,
                    key="ed_fator",
                    help="Quantas unidades de COMPRA cabem em 1 unidade de ESTOQUE. "
                         "Ex.: 1 GL = 5 L → fator 5. Fator 1 = mesma unidade (sem conversão).")
                _uc_txt = (ed_uc or _un_est).strip() or _un_est
                if abs(ed_fator - 1.0) > 1e-9 and _uc_txt.upper() != _un_est.upper():
                    st.caption(f":material/straighten: **1 {_un_est}** de estoque = **{ed_fator:g} {_uc_txt}** de compra. "
                               f"No recebimento, cada {ed_fator:g} {_uc_txt} recebidos viram 1 {_un_est} no estoque.")
                else:
                    st.caption(":material/straighten: Sem conversão (compra e estoque na mesma unidade).")
                st.caption(f":material/lightbulb: Sugestão do sistema: {_sug['origem']}.")

                if st.button(":material/check_circle: Atualizar Item", type="primary", width="stretch"):
                    dados_edicao = {
                        "descricao": ed_desc,
                        "unidade": ed_un,
                        "tipo_material": ed_tipo,
                        "importancia": ed_imp,
                        "local_armazenagem": ed_loc,
                        "local_armazenagem_2": (ed_loc2 or "").strip(),
                        "caixa_identificacao": ed_caixa,
                        "lead_time_dias": ed_lead,
                        "estoque_minimo": ed_min,
                        "estoque_maximo": ed_max,
                        "unidade_compra": (ed_uc or "").strip() or None,
                        "fator_conversao": ed_fator if ed_fator > 0 else FATOR_CONVERSAO_PADRAO,
                    }
                    ok, msg = atualizar_item_inventario(item_sel['id'], dados_edicao)
                    if ok:
                        invalidar_leituras()
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)

                # ── Lead Time: cadastrado vs calculado (sugestão) — v2.2.1 ──────
                _lt_calc = item_sel.get('lead_time_calculado')
                if _lt_calc is not None:
                    _lt_cad = int(item_sel.get('lead_time_dias') or 0)
                    _amostras = int(item_sel.get('lead_time_calculado_amostras') or 0)
                    _origem = item_sel.get('lead_time_calculado_origem') or "—"
                    st.markdown("---")
                    lc1, lc2 = st.columns([2, 1])
                    lc1.info(
                        f":material/timer: **Lead Time** — cadastrado (Compras): **{_lt_cad}d** · "
                        f"calculado: **{_lt_calc}d** ({_amostras} amostras, origem {_origem}). "
                        f"O calculado é apenas uma sugestão; a base cadastrada não é alterada automaticamente."
                    )
                    if int(_lt_calc) != _lt_cad and lc2.button("Usar calculado", key="btn_usar_lt_calc", width="stretch"):
                        ok, msg = atualizar_item_inventario(item_sel['id'], {"lead_time_dias": int(_lt_calc)})
                        if ok:
                            invalidar_leituras()
                            st.success(f"Lead time atualizado para {int(_lt_calc)}d.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

                # ── Alteração de Part Number (Item 2 / v2.1.0) ───────────────
                st.markdown("---")
                st.markdown("##### :material/sync: Alterar Part Number")
                st.caption("Use quando o PN for corrigido no Protheus. O histórico (movimentações, "
                           "SCs e requisições) é preservado e o PN antigo continua pesquisável.")
                cpn1, cpn2 = st.columns([1, 1])
                novo_pn = cpn1.text_input("Novo Part Number", key="pn_novo", placeholder=item_sel['part_number'])
                motivo_pn = cpn2.text_input("Motivo da alteração", key="pn_motivo", placeholder="Ex: padronização Protheus")
                confirma_pn = st.checkbox("Confirmo a alteração do Part Number", key="pn_confirma")
                if st.button(":material/sync: Alterar Part Number", key="btn_alterar_pn", width="stretch"):
                    if not confirma_pn:
                        st.warning("Marque a confirmação para prosseguir.")
                    else:
                        ok, msg = alterar_part_number(item_sel['id'], novo_pn, motivo=motivo_pn, usuario="Luis Oliveira")
                        if ok:
                            invalidar_leituras()
                            st.success(msg)
                            time.sleep(1.2)
                            st.rerun()
                        else:
                            st.error(msg)

                hist_pn = listar_historico_part_number(item_sel['id'])
                if hist_pn:
                    with st.expander(f":material/history: Histórico de Part Numbers ({len(hist_pn)})"):
                        st.dataframe(
                            pd.DataFrame([{
                                "Data": fmt(h["data_hora"]), "PN Antigo": h["pn_antigo"],
                                "PN Novo": h["pn_novo"], "Motivo": h.get("motivo") or "—",
                                "Usuário": h.get("usuario") or "—",
                            } for h in hist_pn]),
                            width="stretch", hide_index=True
                        )
