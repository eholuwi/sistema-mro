"""Página Controle de SC (v6.0.0) — 7 abas de acompanhamento das SCs.

Migrada do bloco inline do `app.py` (último checkpoint da F4a). Abas: Guarda-Chuva ·
Assistente de Reposição · SCM Integrado · Nova SC · Detalhes SC · Histórico ·
Importar Relatório de SCs.

v6.0.0 (refatoração de UX) — três mudanças de NAVEGAÇÃO; nenhuma regra de negócio,
cálculo ou layout de bloco mudou:
  • saiu a aba **Monitor**. O "Controle Manual de Críticos" (dados do usuário na tabela
    `monitor_livre`) foi preservado num expander do Guarda-Chuva; o cruzamento SCM × SC7
    por upload, que era efêmero, saiu com a aba. `services/monitor_*.py` seguem intactos.
  • saiu a aba **Fornecedores & Cotação**. A lista de fornecedores por item continua na
    **Ficha 360** (expander "Fornecedores"); o rascunho de e-mail de cotação foi
    descontinuado junto com a aba. `obter_fornecedores_por_item` segue no service.
  • entrou **SCM Integrado**, que era item do menu lateral (reverte a separação da
    v5.2.0/F3, a pedido do usuário). A aba chama `scm_integrado.conteudo()`.

Cache: as escritas de SC/guarda-chuva chamam `invalidar_leituras()` para que as telas
cacheadas (Dashboard, Saldo, sidebar) não exibam contagem/estoque velhos.
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime

import pandas as pd
import streamlit as st

from services.constants import PREVISAO_RUPTURA_SEM_RISCO, STATUS_SC
from services.db_functions import (
    GUARDA_CHUVA_ESTAGIOS,
    atualizar_sc,
    carregar_planilha_livre,
    criar_sc,
    importar_relatorio_scs,
    importar_solicitacoes_protheus,
    ingerir_sc7_consumo,
    itens_com_sc_aberta,
    listar_itens_sc,
    listar_recebimentos_sc,
    listar_scs,
    listar_valores,
    salvar_planilha_livre,
    setor_dominante_por_item,
    sincronizar_monitor_sc,
)
from services.guarda_chuva import (
    MESES_ACORDO_MAX,
    MESES_ACORDO_MIN,
    adicionar_item_gc,
    atualizar_itens_gc,
    atualizar_pedido_gc,
    criar_pedido_gc,
    exportar_guarda_chuva_df,
    listar_pedidos_gc,
    obter_pedido_gc,
    remover_item_gc,
    remover_pedido_gc,
)
from services.monitor_cruzamento import preparar_df
from services.scm_pedido import buscar_pedido
from services.planejamento import (
    agrupar_por_tipo_material,
    buscar_sc_id_por_numero,
    gerar_sugestoes_reposicao,
    registrar_desfecho_sugestao,
    resumir_grupo_sc,
    sugestao_para_item_sc,
)
from ui.cache import invalidar_leituras
from ui.paginas import scm_integrado
from ui.componentes.exportar import botoes_export
from ui.componentes.selecao import sel_material
from ui.componentes.status import divergencia_recebimento
from ui.componentes.tabela import chave_editor
from ui.formatos import fmt, fmt_brl, fmt_date_input


def render() -> None:
    st.title(":material/receipt_long: Controle de SC")

    # v3.8.0 — "Receber Material" saiu daqui (agora vive na Movimentação).
    # v4.9.0 — "☂️ Guarda-Chuva" (controle manual) entrou logo após o Monitor.
    # v6.0.0 — 8 → 7 abas: saíram **Monitor** e **Fornecedores & Cotação** (pedido do
    # usuário) e entrou **SCM Integrado**, que era item do menu lateral. O "Controle
    # Manual de Críticos", que morava no Monitor e guarda dados do usuário na tabela
    # `monitor_livre`, foi preservado dentro do Guarda-Chuva — sem ele, a planilha
    # colada pela operação ficaria no banco sem tela para abri-la.
    aba_gc, aba_assist, aba_scm, aba_nova_sc, aba_ed, aba_h, aba_import = st.tabs(
        [
            ":material/umbrella: Guarda-Chuva",
            ":material/psychology: Assistente de Reposição",
            ":material/cloud_sync: SCM Integrado",
            ":material/add: Nova SC",
            ":material/sync: Detalhes SC",
            ":material/history: Histórico",
            ":material/download: Importar Relatório de SCs",
        ]
    )

    # ══════════════════════════════════════════════════════════════════════════════
    # ☂️ GUARDA-CHUVA (controle manual por PEDIDO DE COMPRA — v5.9.0)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_gc:
        _render_guarda_chuva_controle()
        if st.session_state.get("_gc_pedido_edit"):
            _dialog_guarda_chuva()
        st.divider()
        with st.expander(":material/edit_note: Controle Manual de Críticos"):
            _render_controle_manual_criticos()

    # ══════════════════════════════════════════════════════════════════════════════
    # ☁️ SCM INTEGRADO (v6.0.0 — era página do menu; virou aba desta tela)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_scm:
        scm_integrado.conteudo()

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
                        sc7c = resultado.get("SC7_CONSUMO", {}) or {}
                        forn = resultado.get("FORNECEDORES", {}) or {}
                        usr = resultado.get("SCM USERS", {}) or {}
                        c1, c4, c2, c3 = st.columns(4)
                        c1.metric(
                            ":material/attach_money: Preços SC7",
                            sc7.get("precos_inseridos", 0) if isinstance(sc7, dict) else 0,
                        )
                        # v6.5.0 — a mesma aba SC7 também alimenta o consumo por pedido.
                        c4.metric(
                            ":material/local_shipping: Pedidos (consumo)",
                            sc7c.get("pedidos_gravados", 0) if isinstance(sc7c, dict) else 0,
                            help=f"Novos: {sc7c.get('inseridos', 0)} · "
                            f"Atualizados: {sc7c.get('atualizados', 0)}"
                            if isinstance(sc7c, dict)
                            else None,
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

        _render_import_relatorio_compras()
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
            # v5.6.0 — chave versionada pelo conjunto filtrado: com `key` fixa, o Streamlit
            # 1.60.0 reaplicava os checkboxes "Incluir" de um filtro anterior sobre outro
            # conjunto de mesmo tamanho, selecionando itens errados para as SCs sugeridas.
            edit_sel = st.data_editor(
                df_sel,
                hide_index=True,
                width="stretch",
                key=chave_editor("rep_sel_editor", [s["part_number"] for s in filtradas]),
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

            botoes_export(
                pd.DataFrame([_linha_rep(s) for s in filtradas]),
                "reposicao_mro",
                key="rep_export",
                sheet_name="Sugestões",
                label_excel="⬇️ Exportar sugestões (Excel)",
                label_csv="⬇️ Exportar sugestões (CSV)",
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
                        cap += f"  ·  :material/payments: Valor estimado: ~{fmt_brl(r['valor_estimado'])}"
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
                            ci7.metric(
                                "Já Recebido",
                                item_sc.get("quantidade_recebida") or 0,
                                help="Recebimento conferido pelo MRO. Só muda por 'Receber Material'.",
                            )
                            # v5.7.0 — o número do Protheus não sobrescreve mais o do MRO; quando
                            # os dois discordam, a diferença fica visível aqui em vez de sumir.
                            _div_rec = divergencia_recebimento(item_sc)
                            if _div_rec:
                                st.caption(f":orange[{_div_rec}]")

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


def _gc_estado_busca():
    """Resultado da busca na API entre reruns (prévia → confirmação)."""
    return st.session_state.get("_gc_busca")


def _render_import_relatorio_compras():
    """v6.5.0 — segunda porta de entrada do SC7: o "Relatório de Compras.xlsx" sozinho.

    Fica aqui, e não em Configurações, porque é o mesmo dado da aba de import que já existe
    — só que num arquivo separado, que o comprador exporta do Protheus com a aba SC7 em
    outra linha de cabeçalho (0 no arquivo cru, 3 dentro do "Relatório de SCs"). Quem
    resolve isso é `preparar_df`, que varre abas e as 6 primeiras linhas; sem ele, esta
    tela precisaria perguntar ao usuário onde está o cabeçalho."""
    with st.container(border=True):
        st.markdown("### :material/local_shipping: Importar Relatório de Compras (SC7)")
        st.caption(
            "Upload do **Relatório de Compras.xlsx** (aba SC7, dados crus do Protheus). Alimenta o "
            "**Consumo/Mensal (SC7)** da Ficha 360 e o Mín/Máx sugerido: guarda cada linha de pedido "
            "com Qtd.Entregue e Saldo. Só pedido **atendido** (saldo zero) entra na conta. "
            "Reimportar o mesmo arquivo atualiza os saldos e **não duplica** nada. "
            ":material/schedule: O export cru tem ~1 milhão de linhas (limite do Excel) — **a "
            "leitura leva alguns minutos**; a gravação é rápida."
        )
        arq_sc7 = st.file_uploader(
            "Arquivo Excel (.xlsx / .xls)", type=["xlsx", "xls"], key="upload_relatorio_compras"
        )
        if arq_sc7 and st.button(
            ":material/sync: Processar Relatório de Compras", width="stretch", type="primary"
        ):
            with st.spinner("Lendo a aba SC7 (arquivo grande — pode levar alguns minutos)..."):
                df_sc7, meta = preparar_df(arq_sc7, "SC7")
            if df_sc7 is None:
                st.error(f":material/cancel: {meta.get('erro', 'Falha ao ler o arquivo.')}")
                return
            with st.spinner("Gravando pedidos de compra..."):
                res = ingerir_sc7_consumo(df_sc7, arq_sc7.name)
            if res.get("erro"):
                st.error(f":material/cancel: {res['erro']}")
                return
            invalidar_leituras()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(
                ":material/description: Linhas lidas",
                res.get("linhas_lidas", 0),
                help=f"Linhas em branco descartadas: {res.get('linhas_vazias', 0)} "
                "(o export cru do Protheus vem com o limite do Excel).",
            )
            m2.metric(":material/add: Pedidos novos", res.get("inseridos", 0))
            m3.metric(":material/sync: Atualizados", res.get("atualizados", 0))
            m4.metric(":material/block: Ignorados", res.get("ignorados", 0))
            st.success(
                f":material/check_circle: {res.get('pedidos_gravados', 0)} pedido(s) gravado(s) "
                f"a partir da aba **{meta.get('aba')}** (cabeçalho na linha {meta.get('header')})."
            )


def _render_guarda_chuva_controle():
    """v5.9.0 — Guarda-Chuva POR PEDIDO DE COMPRA.

    Reescrito: até a v5.8.0 o acordo era (material × fornecedor) e `numero_po` era texto
    decorativo; um pedido real tem N itens e não existia como entidade. Fluxo novo:
    **Adicionar Pedido → buscar os itens na API do SCM → completar manualmente**, com
    tabela editável por item e recebimentos mês a mês (1 a 12 colunas).

    Continua sendo CONTROLE, não ledger: abate o saldo do acordo e **não toca estoque
    nem histórico de movimentações**.
    """
    st.markdown("### :material/umbrella: Guarda-Chuva — acordos por Pedido de Compra")
    st.caption(
        "Acordo com o fornecedor para **congelar o preço** de um pedido e receber em "
        "**parcelas mês a mês**. Informe o nº do Pedido e o sistema busca os itens na API "
        "do SCM; o que não vier (ou não for material MRO) você completa à mão. "
        "**Controle manual — abate o saldo do acordo. NÃO mexe no estoque nem no "
        "histórico de movimentações.**"
    )

    _render_gc_adicionar_pedido()

    pedidos = listar_pedidos_gc()
    if not pedidos:
        st.info("Nenhum pedido no Guarda-Chuva ainda. Use **Adicionar Pedido** acima.")
        return

    _render_gc_kanban(pedidos)

    # ── Exportação da planilha completa ──────────────────────────────────────
    st.divider()
    st.markdown("##### :material/download: Exportar planilha do Guarda-Chuva")
    st.caption("Uma linha por item, com uma coluna para cada mês de recebimento.")
    botoes_export(
        exportar_guarda_chuva_df(),
        "guarda_chuva_mro",
        key="gc_export",
        sheet_name="Guarda-Chuva",
        label_excel="⬇️ Exportar Guarda-Chuva (Excel)",
        label_csv="⬇️ Exportar Guarda-Chuva (CSV)",
        width="stretch",
    )


def _render_gc_adicionar_pedido():
    """Expander 'Adicionar Pedido': busca na API com fallback manual."""
    with st.expander(":material/add: Adicionar Pedido ao Guarda-Chuva", expanded=False):
        c1, c2, c3 = st.columns([2, 1, 1])
        numero = c1.text_input("Nº do Pedido de Compra *", key="gc_novo_num", placeholder="Ex.: F63955")
        meses = c2.number_input(
            "Meses do acordo",
            min_value=MESES_ACORDO_MIN,
            max_value=MESES_ACORDO_MAX,
            value=2,
            step=1,
            key="gc_novo_meses",
            help="Define quantas colunas de recebimento a tabela do pedido terá (1 a 12).",
        )
        if c3.button(":material/cloud_download: Buscar na API", width="stretch", key="gc_buscar"):
            if not (numero or "").strip():
                st.warning("Informe o número do pedido.")
            else:
                ok, res = buscar_pedido(numero)
                st.session_state["_gc_busca"] = {"ok": ok, "res": res, "numero": numero.strip()}
                st.rerun()

        busca = _gc_estado_busca()
        if busca and busca.get("numero") == (numero or "").strip():
            if busca["ok"]:
                _render_gc_previa_api(busca["res"], meses)
            else:
                st.warning(f":material/cloud_off: {busca['res']}")

        # Fallback manual — sempre disponível, mesmo com a API fora do ar.
        st.markdown("---")
        st.markdown("**Cadastro manual** (se a API não trouxer o pedido)")
        m1, m2, m3 = st.columns(3)
        f_sc = m1.text_input("SC (opcional)", key="gc_novo_sc")
        f_cod = m2.text_input("Código do fornecedor", key="gc_novo_cod")
        f_nome = m3.text_input("Nome do fornecedor", key="gc_novo_nome")
        if st.button(":material/add: Criar pedido manualmente", key="gc_criar_manual", width="stretch"):
            if not (numero or "").strip():
                st.warning("Informe o número do pedido.")
            else:
                ok, res = criar_pedido_gc(
                    numero,
                    numero_sc=f_sc,
                    fornecedor_codigo=f_cod,
                    fornecedor_nome=f_nome,
                    meses_acordo=meses,
                    origem="manual",
                )
                if ok:
                    invalidar_leituras()
                    st.session_state.pop("_gc_busca", None)
                    st.success(":material/check_circle: Pedido criado. Abra-o para lançar os itens.")
                    st.rerun()
                else:
                    st.error(f":material/cancel: {res}")


def _render_gc_previa_api(dados, meses):
    """Prévia dos itens encontrados na API + confirmação."""
    cab = dados["cabecalho"]
    mro, descartados = dados["itens_mro"], dados["descartados"]

    st.success(
        f":material/cloud_done: Pedido **{cab['numero_pedido']}** encontrado · "
        f"fornecedor **{cab.get('fornecedor_codigo') or '—'} · {cab.get('fornecedor_nome') or '—'}**"
        + (f" · SC **{cab['numero_sc']}**" if cab.get("numero_sc") else "")
    )
    if mro:
        st.markdown(f"**{len(mro)} item(ns) de material MRO:**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "PN": it["part_number"],
                        "Produto": it["nome_item"],
                        "Qtd": it["quantidade"],
                        "Un": it["unidade"],
                        "Preço": it["preco_unitario"],
                    }
                    for it in mro
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.warning("Nenhum item deste pedido está no inventário MRO.")

    if descartados:
        # Descartados são LISTADOS, não silenciados: o comprador precisa saber que o
        # pedido tinha mais linhas do que as que entraram no acordo.
        with st.expander(f":material/filter_alt: {len(descartados)} item(ns) fora do inventário MRO"):
            st.dataframe(
                pd.DataFrame([{"PN": it["part_number"], "Descrição": it["descricao"]} for it in descartados]),
                width="stretch",
                hide_index=True,
            )

    if st.button(
        ":material/check: Confirmar e criar pedido", type="primary", key="gc_confirmar", width="stretch"
    ):
        ok, res = criar_pedido_gc(
            cab["numero_pedido"],
            numero_sc=cab.get("numero_sc"),
            fornecedor_codigo=cab.get("fornecedor_codigo"),
            fornecedor_nome=cab.get("fornecedor_nome"),
            meses_acordo=meses,
            origem="api",
            itens=[
                {
                    "item_id": it["item_id"],
                    "qtd_negociada": it["quantidade"],
                    "preco_congelado": it["preco_unitario"],
                }
                for it in mro
            ],
        )
        if ok:
            invalidar_leituras()
            st.session_state.pop("_gc_busca", None)
            st.success(":material/check_circle: Pedido adicionado ao Guarda-Chuva.")
            st.rerun()
        else:
            st.error(f":material/cancel: {res}")


def _render_gc_kanban(pedidos):
    """Kanban dos 4 estágios, agora no nível do PEDIDO (era por acordo material×fornecedor)."""
    st.markdown("##### :material/view_kanban: Pedidos por estágio")
    cols = st.columns(len(GUARDA_CHUVA_ESTAGIOS))
    for col, nome in zip(cols, GUARDA_CHUVA_ESTAGIOS):
        with col:
            grupo = [p for p in pedidos if (p.get("estagio") or GUARDA_CHUVA_ESTAGIOS[0]) == nome]
            st.markdown(f"**{nome}** · {len(grupo)}")
            for p in grupo:
                with st.container(border=True):
                    st.markdown(f"**{p['numero_pedido']}**")
                    st.caption(
                        f"{p.get('fornecedor_nome') or p.get('fornecedor_codigo') or '—'}"
                        + (f" · SC {p['numero_sc']}" if p.get("numero_sc") else "")
                    )
                    st.caption(
                        f"{p['n_itens']} item(ns) · Neg. {float(p['qtd_negociada'] or 0):g} · "
                        f"Receb. {float(p['qtd_recebida'] or 0):g} · "
                        f"Saldo {float(p['saldo_residual'] or 0):g}"
                    )
                    if st.button(":material/edit: Abrir", key=f"gc_open_{p['id']}", width="stretch"):
                        st.session_state["_gc_pedido_edit"] = int(p["id"])
                        st.rerun()


def _clear_gc_pedido_edit():
    st.session_state.pop("_gc_pedido_edit", None)


@st.dialog("Pedido — Guarda-Chuva", width="large", on_dismiss=_clear_gc_pedido_edit)
def _dialog_guarda_chuva():
    """v5.9.0 — Edita um pedido do Guarda-Chuva: cabeçalho + tabela editável de itens
    com os recebimentos mês a mês. Relê do banco a cada render (`obter_pedido_gc`).

    Controle manual: NÃO toca estoque nem movimentações."""
    pedido_id = st.session_state.get("_gc_pedido_edit")
    p = obter_pedido_gc(pedido_id) if pedido_id else None
    if not p:
        st.info("Pedido não encontrado (pode ter sido removido).")
        return

    meses = p["meses_acordo"]
    st.markdown(f"### Pedido `{p['numero_pedido']}`")

    # ── Cabeçalho ────────────────────────────────────────────────────────────
    with st.form("form_gc_pedido_cab"):
        c1, c2, c3, c4 = st.columns(4)
        f_sc = c1.text_input("SC", value=p.get("numero_sc") or "")
        f_cod = c2.text_input("Código do fornecedor", value=p.get("fornecedor_codigo") or "")
        f_nome = c3.text_input("Nome do fornecedor", value=p.get("fornecedor_nome") or "")
        _idx = (
            list(GUARDA_CHUVA_ESTAGIOS).index(p["estagio"])
            if p.get("estagio") in GUARDA_CHUVA_ESTAGIOS
            else 0
        )
        f_est = c4.selectbox("Estágio", GUARDA_CHUVA_ESTAGIOS, index=_idx)
        c5, c6 = st.columns([1, 3])
        f_meses = c5.number_input(
            "Meses do acordo",
            min_value=MESES_ACORDO_MIN,
            max_value=MESES_ACORDO_MAX,
            value=int(meses),
            step=1,
            help="Nº de colunas de recebimento da tabela abaixo.",
        )
        f_obs = c6.text_input("Observação", value=p.get("observacao") or "")
        if st.form_submit_button(":material/save: Salvar cabeçalho", type="primary", width="stretch"):
            ok, msg = atualizar_pedido_gc(
                pedido_id,
                {
                    "numero_sc": f_sc,
                    "fornecedor_codigo": f_cod,
                    "fornecedor_nome": f_nome,
                    "estagio": f_est,
                    "meses_acordo": f_meses,
                    "observacao": f_obs,
                },
            )
            if ok:
                invalidar_leituras()
                st.success(f":material/check_circle: {msg}")
                st.rerun()
            else:
                st.error(f":material/cancel: {msg}")

    # ── Tabela editável: itens × recebimento por mês ─────────────────────────
    st.markdown("##### :material/table_rows: Itens do acordo")
    st.caption(
        "**PN** e **Produto** vêm do cadastro e não são editáveis. As colunas de mês são "
        "o quanto já foi recebido — controle do acordo, sem efeito no estoque."
    )
    if not p["itens"]:
        st.info("Nenhum material neste pedido ainda. Use **Adicionar material** abaixo.")
    else:
        cols_mes = [f"{m}º mês" for m in range(1, meses + 1)]
        df = pd.DataFrame(
            [
                {
                    "_id": it["id"],
                    "PN": it["part_number"],
                    "Produto": it["nome_item"],
                    "Qtd Negociada": float(it.get("qtd_negociada") or 0),
                    "Qtd prevista/mês": (
                        float(it["qtd_prevista_mes"]) if it.get("qtd_prevista_mes") is not None else None
                    ),
                    "Preço congelado": (
                        float(it["preco_congelado"]) if it.get("preco_congelado") is not None else None
                    ),
                    **{rot: float(it["recebimentos"].get(m, 0.0)) for m, rot in enumerate(cols_mes, start=1)},
                    "Saldo": it["saldo_residual"],
                }
                for it in p["itens"]
            ]
        )
        edit = st.data_editor(
            df,
            width="stretch",
            hide_index=True,
            num_rows="fixed",
            # A key precisa mudar quando muda o CONJUNTO de linhas/colunas, senão o
            # data_editor reaplica edições antigas sobre dados novos (ver chave_editor).
            key=chave_editor("gc_itens", pedido_id, meses, [i["id"] for i in p["itens"]]),
            column_config={
                "_id": None,
                "PN": st.column_config.TextColumn(disabled=True),
                "Produto": st.column_config.TextColumn(disabled=True),
                "Saldo": st.column_config.NumberColumn(disabled=True, format="%.2f"),
                "Preço congelado": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )
        if st.button(":material/save: Salvar itens", type="primary", width="stretch", key="gc_salvar_itens"):
            linhas = [
                {
                    "id": int(r["_id"]),
                    "qtd_negociada": r["Qtd Negociada"],
                    "qtd_prevista_mes": r["Qtd prevista/mês"],
                    "preco_congelado": r["Preço congelado"],
                    "recebimentos": {m: r[rot] for m, rot in enumerate(cols_mes, start=1)},
                }
                for r in edit.to_dict("records")
            ]
            ok, msg = atualizar_itens_gc(pedido_id, linhas)
            if ok:
                invalidar_leituras()
                st.success(f":material/check_circle: {msg}")
                st.rerun()
            else:
                st.error(f":material/cancel: {msg}")

    # ── Inclusão / remoção manual de material ────────────────────────────────
    with st.expander(":material/add_circle: Adicionar material ao pedido"):
        _, item_gc, _ = sel_material(
            "Material (busque por PN, nome ou descrição)", "gc_add_item", incluir_descricao=True
        )
        qn = st.number_input("Qtd negociada", min_value=0.0, step=1.0, key="gc_add_qtd")
        if st.button(":material/add: Adicionar ao pedido", key="gc_add_btn", width="stretch"):
            if not item_gc:
                st.warning("Selecione um material.")
            else:
                ok, msg = adicionar_item_gc(pedido_id, item_gc["id"], qtd_negociada=qn)
                if ok:
                    invalidar_leituras()
                    st.success(f":material/check_circle: {msg}")
                    st.rerun()
                else:
                    st.error(f":material/cancel: {msg}")

    if p["itens"]:
        with st.expander(":material/remove_circle: Remover material do pedido"):
            _rot = {f"{i['part_number']} — {i['nome_item']}": i["id"] for i in p["itens"]}
            alvo = st.selectbox("Material", list(_rot), key="gc_rm_item")
            if st.button(":material/delete: Remover material", key="gc_rm_btn"):
                ok, msg = remover_item_gc(_rot[alvo])
                if ok:
                    invalidar_leituras()
                    st.success(f":material/check_circle: {msg}")
                    st.rerun()
                else:
                    st.error(f":material/cancel: {msg}")

    st.divider()
    if st.button(":material/delete_forever: Remover este pedido do Guarda-Chuva", key="gc_rm_pedido"):
        ok, msg = remover_pedido_gc(pedido_id)
        if ok:
            invalidar_leituras()
            _clear_gc_pedido_edit()
            st.rerun()
        else:
            st.error(f":material/cancel: {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# 📡 MONITOR DE SC — seções: (1) Controle Manual de Críticos, (2) fallback de
# cruzamento por upload. v5.6.0: "SCs/Itens não atendidos" foi removido.
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
