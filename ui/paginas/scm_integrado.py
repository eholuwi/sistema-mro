"""Página SCM Integrado (v5.2.0 / F3) — consulta unificada das SCs.

Página de CONSULTA (almoxarifado E compradores) sobre as SCs já persistidas no
`mro.db` (pelo Relatório Excel e/ou pela sincronização da API do SCM, v5.1.0).
Cabeçalho com a sincronização "Atualizar agora" (movida da aba Monitor de Controle
de SC, onde era provisória na F2) + 3 abas: Solicitações de Compra / Itens das SCs /
Detalhes da SC.

Regra de rede: `render()` é livre de rede — a API do SCM só é consultada em ações
explícitas do usuário ("Atualizar agora" e "Buscar dados ao vivo"). Isso mantém a
página rápida e o smoke (test_v500_router) determinístico.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services import scm_consulta, scm_sync
from ui.cache import invalidar_leituras
from ui.componentes.filtros import barra_filtros
from ui.componentes.tabela import tabela_paginada
from ui.componentes.status import badge_origem, ponto_status_api

_ABERTAS_EXCLUI = {"Recebido", "Cancelado"}
_DATA_COLS_SC = ["data_abertura", "data_aprovacao", "proxima_necessidade"]


def render() -> None:
    st.title(":material/cloud_sync: SCM Integrado")
    st.caption("Consulta unificada das Solicitações de Compra — do **Relatório de SCs** "
               "(Excel) e da **API do SCM**. Para almoxarifado e compradores.")

    _cabecalho_sync()

    scs = scm_consulta.listar_scs_consulta()
    itens = scm_consulta.listar_itens_consulta()

    aba_scs, aba_itens, aba_det = st.tabs([
        ":material/description: Solicitações de Compra",
        ":material/inventory_2: Itens das SCs",
        ":material/manage_search: Detalhes da SC",
    ])
    with aba_scs:
        _aba_solicitacoes(scs)
    with aba_itens:
        _aba_itens(itens)
    with aba_det:
        _aba_detalhes(scs)


# ── Cabeçalho: sincronização SCM (API → banco) ────────────────────────────────

def _cabecalho_sync():
    """Sincronização SCM persistente (API → mro.db). Movida da aba Monitor (F2). Só
    toca a rede quando o usuário clica em 'Atualizar agora'."""
    with st.container(border=True):
        _u = scm_sync.ultima_sync()
        c1, c2 = st.columns([3, 1])
        with c1:
            if _u:
                _res = (_u.get("detalhe") or {}).get("resumo", {})
                _st = (_u.get("detalhe") or {}).get("status", "")
                st.markdown(
                    f":material/cloud_sync: **Última sincronização:** {_u['data_hora']}  ·  "
                    f"{_res.get('scs', 0)} SC(s), {_res.get('itens', 0)} item(ns), "
                    f"{_res.get('externos', 0)} externo(s)" + (f"  ·  _{_st}_" if _st else ""))
            else:
                st.markdown(":material/cloud_sync: **Última sincronização:** _nunca_ — "
                            "clique em **Atualizar agora**.")
            st.caption("Puxa as SCs dos **solicitantes MRO** da API do SCM e **grava no banco** "
                       "(status, datas, itens, preços, itens fora do inventário). O **Relatório "
                       "de SCs (Excel)** segue como alternativa — a API nunca é dependência "
                       "exclusiva. Escopo em **Configurações › Solicitantes MRO (SCM)**.")
        with c2:
            _go = st.button(":material/sync: Atualizar agora", key="scm_sync_go",
                            width="stretch", type="primary")

        if _go:
            with st.status("Sincronizando SCM…", expanded=True) as _s:
                _prog = st.progress(0.0, text="Iniciando…")

                def _cb(nome, i, n):
                    frac = (i / n) if n else 1.0
                    _prog.progress(min(frac, 1.0),
                                   text=(f"Sincronizando {nome}… ({i + 1}/{n})" if nome else "Concluindo…"))

                resumo = scm_sync.sincronizar(progress_cb=_cb)
                if not resumo.get("ok"):
                    _s.update(label="API do SCM indisponível", state="error")
                else:
                    invalidar_leituras()
                    _s.update(label="Sincronização concluída", state="complete")

            if not resumo.get("ok"):
                st.warning(resumo.get("erro", "Não foi possível sincronizar. Use o Relatório de SCs (Excel)."))
            else:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric(":material/description: SCs", resumo["scs"])
                m2.metric(":material/inventory_2: Itens", resumo["itens"])
                m3.metric(":material/help_center: Externos", resumo["externos"])
                m4.metric(":material/difference: Divergências", resumo["divergencias"])
                st.caption(f"Solicitantes: {resumo['solicitantes']}  ·  SCs criadas: "
                           f"{resumo['scs_criadas']}  ·  atualizadas: {resumo['scs_atualizadas']}"
                           + (f"  ·  {len(resumo['erros'])} aviso(s)" if resumo.get("erros") else ""))
                if resumo.get("erros"):
                    with st.expander(f"Ver {len(resumo['erros'])} aviso(s) da sincronização"):
                        st.json(resumo["erros"])


# ── Aba 1: Solicitações de Compra ─────────────────────────────────────────────

def _df_scs(scs):
    """DataFrame das SCs com as datas convertidas p/ datetime (ordenáveis/filtráveis)."""
    df = pd.DataFrame(scs)
    if df.empty:
        return df
    for c in _DATA_COLS_SC:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c].astype(str).str.slice(0, 10),
                                   format="%Y-%m-%d", errors="coerce")
    return df


def _aba_solicitacoes(scs):
    df = _df_scs(scs)
    if df.empty:
        st.info("Nenhuma solicitação de compra registrada ainda. Importe o Relatório de SCs "
                "ou use **Atualizar agora** (API do SCM).")
        return

    hoje = pd.Timestamp.today().normalize()
    filtros_rapidos = {
        "Abertas": lambda d: ~d["status"].isin(_ABERTAS_EXCLUI),
        "Com PO": lambda d: d["pos"].fillna("").str.strip() != "",
        "Sem PO": lambda d: d["pos"].fillna("").str.strip() == "",
        "Críticas": lambda d: d["prioridade_critica"] == True,  # noqa: E712 (Series comparison)
        "Últimos 30 dias": lambda d: d["data_abertura"] >= (hoje - pd.Timedelta(days=30)),
    }
    avancados = {
        "periodo": ("Período de emissão", "data_abertura"),
        "multiselect": [("Comprador", "comprador"), ("Status", "status"),
                        ("Centro de Custo", "centro_custo")],
    }
    filtrado = barra_filtros(
        df, chave="scm_scs",
        campos_pesquisa=["numero_sc", "solicitante", "comprador", "descricao_solicitacao",
                         "justificativa"],
        filtros_rapidos=filtros_rapidos, avancados=avancados)

    colunas = ["numero_sc", "status", "solicitante", "comprador", "centro_custo",
               "descricao_solicitacao", "justificativa", "data_abertura", "data_aprovacao",
               "proxima_necessidade", "pos"]
    vis = filtrado.reindex(columns=colunas)
    config = {
        "numero_sc": st.column_config.TextColumn("SC"),
        "status": st.column_config.TextColumn("Status"),
        "solicitante": st.column_config.TextColumn("Solicitante"),
        "comprador": st.column_config.TextColumn("Comprador"),
        "centro_custo": st.column_config.TextColumn("Centro de Custo"),
        "descricao_solicitacao": st.column_config.TextColumn("Descrição", width="medium"),
        "justificativa": st.column_config.TextColumn("Justificativa", width="medium"),
        "data_abertura": st.column_config.DateColumn("Emissão", format="DD/MM/YYYY"),
        "data_aprovacao": st.column_config.DateColumn("Aprovação", format="DD/MM/YYYY"),
        "proxima_necessidade": st.column_config.DateColumn("Necessidade", format="DD/MM/YYYY"),
        "pos": st.column_config.TextColumn("PO(s)"),
    }

    def _selecionar(linha):
        st.session_state["scm_sc_selecionada"] = linha.get("numero_sc")

    st.caption("Clique numa linha para abrir a aba **Detalhes da SC**.")
    tabela_paginada(vis, chave="scm_scs_tab", colunas_config=config, on_select=_selecionar)


# ── Aba 2: Itens das SCs ──────────────────────────────────────────────────────

def _aba_itens(itens):
    df = pd.DataFrame(itens)
    if df.empty:
        st.info("Nenhum item de SC registrado ainda.")
        return

    filtros_rapidos = {
        "Fora do inventário MRO": lambda d: d["fora_do_inventario"] == True,  # noqa: E712
        "Com PO": lambda d: d["numero_po"].fillna("").astype(str).str.strip() != "",
        "Sem PO": lambda d: d["numero_po"].fillna("").astype(str).str.strip() == "",
    }
    filtrado = barra_filtros(
        df, chave="scm_itens",
        campos_pesquisa=["part_number", "descricao", "numero_sc"],
        filtros_rapidos=filtros_rapidos)

    colunas = ["numero_sc", "part_number", "descricao", "quantidade", "unidade",
               "preco_unitario", "valor_total", "numero_po", "status_item", "origem",
               "fora_do_inventario"]
    vis = filtrado.reindex(columns=colunas)
    config = {
        "numero_sc": st.column_config.TextColumn("SC"),
        "part_number": st.column_config.TextColumn("PN"),
        "descricao": st.column_config.TextColumn("Descrição", width="medium"),
        "quantidade": st.column_config.NumberColumn("Qtd", format="%.2f"),
        "unidade": st.column_config.TextColumn("UN"),
        "preco_unitario": st.column_config.NumberColumn("Preço Unit.", format="R$ %.2f"),
        "valor_total": st.column_config.NumberColumn("Valor Total", format="R$ %.2f"),
        "numero_po": st.column_config.TextColumn("PO"),
        "status_item": st.column_config.TextColumn("Status Item"),
        "origem": st.column_config.TextColumn("Origem"),
        "fora_do_inventario": st.column_config.CheckboxColumn("Fora do inv."),
    }
    tabela_paginada(vis, chave="scm_itens_tab", colunas_config=config)


# ── Aba 3: Detalhes da SC ─────────────────────────────────────────────────────

def _aba_detalhes(scs):
    if not scs:
        st.info("Nenhuma SC para detalhar ainda.")
        return

    numeros = [s["numero_sc"] for s in scs]
    sel = st.session_state.get("scm_sc_selecionada")
    idx = numeros.index(sel) if sel in numeros else 0
    numero_sc = st.selectbox("Solicitação de Compra", numeros, index=idx, key="scm_det_sel")
    if not numero_sc:
        return

    det = scm_consulta.detalhes_sc_banco(numero_sc)
    if not det:
        st.warning("SC não encontrada no banco.")
        return

    cab = det["cabecalho"]
    _quando = cab.get("data_sync_api") or cab.get("data_importacao")
    st.markdown(f"### SC {cab['numero_sc']}  ·  {badge_origem(cab.get('origem_importacao'), _quando)}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", cab.get("status") or "—")
    c2.metric("Solicitante", cab.get("solicitante") or "—")
    c3.metric("Comprador", cab.get("comprador") or "—")
    c4.metric("Centro de Custo", cab.get("centro_custo") or "—")
    if cab.get("descricao_solicitacao"):
        st.caption(f"**Descrição:** {cab['descricao_solicitacao']}")
    if cab.get("observacoes"):
        st.caption(f"**Justificativa:** {cab['observacoes']}")

    # Itens (inventário MRO) + externos
    st.markdown("#### :material/inventory_2: Itens")
    itens = det["itens"]
    if itens:
        df_it = pd.DataFrame(itens).reindex(columns=[
            "part_number", "nome_item", "quantidade_solicitada", "quantidade_recebida",
            "preco_unitario", "valor_total", "numero_po", "status_item", "origem"])
        st.dataframe(df_it, width="stretch", hide_index=True, column_config={
            "part_number": "PN", "nome_item": "Descrição",
            "quantidade_solicitada": st.column_config.NumberColumn("Qtd", format="%.2f"),
            "quantidade_recebida": st.column_config.NumberColumn("Recebido", format="%.2f"),
            "preco_unitario": st.column_config.NumberColumn("Preço Unit.", format="R$ %.2f"),
            "valor_total": st.column_config.NumberColumn("Valor Total", format="R$ %.2f"),
            "numero_po": "PO", "status_item": "Status", "origem": "Origem"})
    else:
        st.caption("Sem itens do inventário MRO nesta SC.")

    externos = det["externos"]
    if externos:
        st.markdown("#### :material/help_center: Itens fora do inventário MRO")
        df_ex = pd.DataFrame(externos).reindex(columns=[
            "part_number", "descricao", "quantidade", "unidade", "preco_unitario",
            "valor_total", "numero_po", "origem"])
        st.dataframe(df_ex, width="stretch", hide_index=True, column_config={
            "part_number": "PN", "descricao": "Descrição",
            "quantidade": st.column_config.NumberColumn("Qtd", format="%.2f"),
            "unidade": "UN",
            "preco_unitario": st.column_config.NumberColumn("Preço Unit.", format="R$ %.2f"),
            "valor_total": st.column_config.NumberColumn("Valor Total", format="R$ %.2f"),
            "numero_po": "PO", "origem": "Origem"})

    precos = det["precos"]
    if precos:
        with st.expander(f":material/attach_money: Preços históricos ({len(precos)})"):
            df_pr = pd.DataFrame(precos).reindex(columns=[
                "part_number", "data", "preco_unitario", "moeda", "fornecedor",
                "numero_sc", "numero_po", "lead_time_dias"])
            st.dataframe(df_pr, width="stretch", hide_index=True, column_config={
                "part_number": "PN", "data": "Data",
                "preco_unitario": st.column_config.NumberColumn("Preço", format="R$ %.2f"),
                "moeda": "Moeda", "fornecedor": "Fornecedor", "numero_sc": "SC",
                "numero_po": "PO",
                "lead_time_dias": st.column_config.NumberColumn("Lead (d)")})

    _ao_vivo_api(cab)


def _ao_vivo_api(cab):
    """Expander de enriquecimento ao vivo pela API do SCM. Só bate na rede quando o
    usuário clica em 'Buscar dados ao vivo'. O resultado fica em session_state por SC
    (não repete a chamada a cada rerun)."""
    with st.expander(":material/cloud: Ao vivo da API do SCM"):
        numero_sc = cab["numero_sc"]
        ck = f"_scm_live__{numero_sc}"
        if st.button(":material/cloud_download: Buscar dados ao vivo", key=f"scm_live_go__{numero_sc}"):
            with st.spinner("Consultando a API do SCM…"):
                st.session_state[ck] = scm_consulta.detalhes_sc_api(
                    cab.get("sc_id_scm"), numero_po=cab.get("numero_po"),
                    cotacao_codigo=cab.get("cotacao_codigo"))

        live = st.session_state.get(ck)
        if live is None:
            st.caption("Clique acima para consultar Timeline, cotação, pedido e aprovadores "
                       "diretamente do SCM (não altera o banco).")
            return
        if not live.get("disponivel"):
            st.warning("API do SCM offline — exibindo apenas os dados do banco acima.")
            return

        ponto_status_api()
        if live.get("eventos"):
            st.markdown("**Linha do tempo (eventos)**")
            st.dataframe(pd.DataFrame(live["eventos"]), width="stretch", hide_index=True)
        if live.get("itens"):
            st.markdown("**Itens (Timeline ao vivo)**")
            st.dataframe(pd.DataFrame(live["itens"]), width="stretch", hide_index=True)
        if live.get("cotacao"):
            st.markdown("**Cotação**")
            st.json(live["cotacao"], expanded=False)
        if live.get("pedido"):
            st.markdown("**Pedido (Protheus SC7)**")
            st.dataframe(pd.DataFrame(live["pedido"]), width="stretch", hide_index=True)
        if live.get("aprovadores"):
            st.markdown("**Aprovadores do pedido**")
            st.dataframe(pd.DataFrame(live["aprovadores"]), width="stretch", hide_index=True)
        if live.get("erros"):
            with st.expander(f"{len(live['erros'])} aviso(s) da consulta ao vivo"):
                st.json(live["erros"])
