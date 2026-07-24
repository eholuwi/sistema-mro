import streamlit as st
import pandas as pd
import io, os, sys, time
from datetime import date, datetime
from services.styles import inject_custom_css
from services.logging_config import setup_logging
from services.constants import PREVISAO_RUPTURA_SEM_RISCO

sys.path.insert(0, os.path.dirname(__file__))
from database import criar_banco
from services.db_functions import (
    listar_inventario,
    registrar_movimentacao, listar_movimentacoes, categoria_movimentacao,
    registrar_recebimento_sc, listar_scs,
    listar_itens_sc, buscar_scs_por_item, exportar_inventario_df,
    listar_valores,
    listar_setores_conhecidos, sincronizar_setores_config,
    criar_requisicao, listar_requisicoes, listar_itens_requisicao, mapa_pn_por_requisicao,
    entregar_requisicao, adicionar_itens_requisicao,
    cancelar_requisicao, listar_requisicoes_abertas,
    obter_analitico_movimentacoes, obter_analitico_divergencias,
    obter_analitico_rupturas, exportar_movimentacoes_df,
    tirar_snapshot_estoque,
    sincronizar_monitor_sc,
    obter_valor_imobilizado, obter_evolucao_valor_imobilizado,
    obter_abc_valor,
)
from services.ficha import (
    montar_ficha_360, salvar_imagem_item, remover_imagem_item,
    agrupar_saldo_residual_por_fornecedor,
)
from ui.tema import paleta_atual
from ui.formatos import fmt
from ui.sidebar import render_sidebar
from ui.componentes.selecao import sel_material
# Gráficos usados pelos blocos ainda inline (Movimentação/Requisição e Ficha 360 — F4b).
from ui.componentes.graficos import _barv, _mes_label
from ui.router import ROTAS_MIGRADAS, render_pagina

setup_logging()
criar_banco()

# v2.2.0 — foto diária do estoque (idempotente por dia; sem scheduler externo).
# Só executa a primeira vez que o app abre no dia; nas demais é praticamente no-op.
try:
    tirar_snapshot_estoque()
except Exception:
    pass

# v3.9.0 — sync diário do Monitor de SC (mesmo hook "1ª abertura do dia"): recalcula as
# colunas técnicas das SCs abertas e reseta o "Revisado". Gated por dia (no-op nas demais).
try:
    sincronizar_monitor_sc()
except Exception:
    pass

st.set_page_config(page_title="MRO Inventus Power 5.3.0", page_icon=":material/build:", layout="wide", initial_sidebar_state="expanded")


# Paleta única do tema escolhido (via ui.tema.paleta_atual) — consumida pelo CSS
# global, pelo option_menu e pelos gráficos, p/ tudo acompanhar claro/escuro (v2.11.0).
PAL = paleta_atual()
inject_custom_css(PAL)

# Constantes de cadastro/filtros (IMPORTANCIAS/TIPOS/SETORES/UNIDADES/STATUS_SC) e os
# selecionadores de material (sel_material/itens_select/opcoes_com_atual) foram
# centralizados na F4a (v5.3.0) em services.constants e ui.componentes.selecao (imports no topo).

# ── Sidebar ───────────────────────────────────────────────────────────────────

pagina = render_sidebar()

def _receber_por_sc(centros):
    """v3.4.0 — Recebimento começando pela SC/PO: escolhe uma SC aberta e recebe todos
    os itens pendentes de uma vez (itera `registrar_recebimento_sc` por item, mesma função
    do fluxo por material — sem duplicar conversão/ledger). Complementa o 'Por Material'."""
    scs = listar_scs(apenas_abertas=True)
    if not scs:
        st.info("Nenhuma SC aberta para receber. Importe o Relatório de SCs ou crie uma SC.")
        return
    with st.container(border=True):
        opc = {
            (f"SC {s['numero_sc']} · PO {s.get('numero_po') or '—'} · "
             f"{s.get('fornecedor') or 'sem fornecedor'} · "
             f"{int(s.get('total_itens') or 0)} itens · pendente {float(s.get('total_pendente') or 0):g}"): s
            for s in scs
        }
        sel = st.selectbox("Selecione a SC / PO", list(opc.keys()), index=None,
                           placeholder="Selecione a SC / PO…", key="rec_sc_sel")
        if sel not in opc:
            st.info("Selecione uma SC para ver e receber os itens pendentes.")
            return
        sc = opc[sel]
        itens = [it for it in listar_itens_sc(sc["id"]) if (it.get("pendente") or 0) > 0]
        if not itens:
            st.success(":material/check_circle: Todos os itens desta SC já foram recebidos.")
            return

        st.markdown(f"**SC {sc['numero_sc']}** · PO `{sc.get('numero_po') or '—'}` · "
                    f"Fornecedor: {sc.get('fornecedor') or '—'} · Status: {sc.get('status') or '—'}")

        h1, h2, h3 = st.columns(3)
        forn = h1.text_input("Fornecedor", value=sc.get("fornecedor") or "", key="rec_sc_forn")
        dt_r = h2.date_input("Data Recebimento", value=date.today(), key="rec_sc_dt")
        _cc_opts = centros if centros else ["—"]
        _cc_def = next((i for i, c in enumerate(_cc_opts) if "ALMOXARIFADO" in str(c).upper()), 0)
        cc_r = h3.selectbox("Centro de Custo", _cc_opts, index=_cc_def, key="rec_sc_cc",
                            help="Padrão MRO: Almoxarifado.")

        base = pd.DataFrame([{
            "Receber": True,
            "PN": it["part_number"],
            "Item": (it.get("nome_item") or "")[:40],
            "Un": it.get("unidade") or "UN",
            "Pendente": float(it.get("pendente") or 0),
            "Qtd a receber": float(it.get("pendente") or 0),
            "NF / Documento": "",
            "_item_sc_id": int(it["id"]),
        } for it in itens])
        edit = st.data_editor(
            base, hide_index=True, width="stretch", key="rec_sc_editor",
            column_config={
                "Receber": st.column_config.CheckboxColumn("Receber", help="Desmarque itens que ainda não chegaram."),
                "PN": st.column_config.TextColumn(disabled=True),
                "Item": st.column_config.TextColumn(disabled=True),
                "Un": st.column_config.TextColumn(disabled=True),
                "Pendente": st.column_config.NumberColumn(format="%.0f", disabled=True),
                "Qtd a receber": st.column_config.NumberColumn(format="%.2f", min_value=0.0,
                    help="Default = pendente. Recebimento parcial: reduza aqui."),
                "NF / Documento": st.column_config.TextColumn(help="NF por item (opcional; usa a do lote se vazio)."),
                "_item_sc_id": None,
            },
        )
        nf_lote = st.text_input("Nota Fiscal / Documento do lote", key="rec_sc_nf",
                                help="Aplicada aos itens sem NF própria na tabela acima.")

        if st.button(":material/download: Confirmar recebimento da SC", type="primary",
                     width="stretch", key="rec_sc_btn"):
            recebidos, erros = 0, []
            for _, r in edit.iterrows():
                if not r["Receber"]:
                    continue
                qtd = float(r["Qtd a receber"] or 0)
                if qtd <= 0:
                    continue
                nf = str(r["NF / Documento"]).strip() or nf_lote.strip()
                ok, msg = registrar_recebimento_sc(
                    sc_id=sc["id"], item_sc_id=int(r["_item_sc_id"]),
                    qtd_recebida=qtd, centro_custo=cc_r,
                    solicitante="Almoxarifado", emitente="Almoxarifado",
                    fornecedor=forn, data_recebimento=str(dt_r), obs_nf=nf)
                if ok:
                    recebidos += 1
                else:
                    erros.append(f"{r['PN']}: {msg}")
            if recebidos:
                st.success(f":material/check_circle: {recebidos} item(ns) recebido(s) na SC {sc['numero_sc']}.")
            if erros:
                st.error(":material/warning: Não recebidos — " + " | ".join(erros))
            if recebidos and not erros:
                time.sleep(1.5)
                st.rerun()


def _render_receber_material():
    """Recebimento de material — Por Material (item → SC/avulsa) ou Por SC / PO.
    v3.8.0: movido do Controle de SC para uma aba da Movimentação. `_receber_por_sc`
    é module-level; nada de estado global além do já usado."""
    _modo_rec = st.radio(
        "Como quer receber?", ["📦 Por Material", "📋 Por SC / PO"],
        horizontal=True, key="rec_modo",
        help="Por Material começa pelo item; Por SC / PO escolhe a SC e recebe todos os itens pendentes de uma vez.")
    if _modo_rec == "📋 Por SC / PO":
        _receber_por_sc(listar_valores("centro_custo"))
        return
    with st.container(border=True):
        st.markdown("### :material/inventory_2: Registrar Recebimento de Material")
        st.caption("Vincule a uma SC aberta ou registre como entrada avulsa.")

        centros = listar_valores("centro_custo")
        _, item_rec, _ = sel_material("Material *", "sel_rec")

        if item_rec:
            # v2.9.0: conversão de unidades. A qtd recebida é informada na UNIDADE
            # DE COMPRA; o estoque/ledger vive na UNIDADE DE ESTOQUE. fator=1 (itens
            # de UM única) → sem diferença, tudo como antes.
            _fator_rec = float(item_rec.get('fator_conversao') or 1.0) or 1.0
            _ue_rec = item_rec.get('unidade') or 'UN'
            _uc_rec = item_rec.get('unidade_compra') or _ue_rec
            _tem_conv = abs(_fator_rec - 1.0) > 1e-9 and _uc_rec.upper() != _ue_rec.upper()

            st.markdown(f"`{item_rec['part_number']}` — **{item_rec['nome_item']}** | Saldo Atual: `{item_rec['estoque_atual']}` {_ue_rec}")
            if item_rec.get("unidade_divergente"):
                st.warning(":material/warning: Este item é comprado em unidade diferente da de estoque e ainda "
                           "**não tem fator de conversão** definido — o recebimento somará a "
                           "quantidade crua. Cadastre o fator em **Gerenciar Itens → Conversão "
                           "de unidades** antes de receber.")

            scs_item = buscar_scs_por_item(item_rec["id"], apenas_abertas=True)
            sc_sel = None

            if scs_item:
                vincular = st.checkbox(":material/link: Vincular a uma S.C. Aberta", value=True)
                if vincular:
                    opc_sc = {f"SC {s['numero_sc']} | PO: {s.get('po_item') or '—'} | Saldo: {s['pendente']} {_uc_rec}": s for s in scs_item}
                    sel_sc_str = st.selectbox("Selecionar SC", list(opc_sc.keys()), label_visibility="collapsed")
                    sc_sel = opc_sc[sel_sc_str]

                    with st.container(border=True):
                        st.markdown(f":material/check_circle: **SC {sc_sel['numero_sc']}** | PO: `{sc_sel['numero_po'] or '—'}` | Fornecedor: {sc_sel.get('fornecedor_item') or sc_sel['fornecedor'] or '—'}")
                        st.markdown(f"Solicitado: `{sc_sel['quantidade_solicitada']}` | Negociado: `{sc_sel.get('quantidade_negociada') or sc_sel['quantidade_solicitada']}` | Recebido: `{sc_sel['quantidade_recebida']}` | **Saldo Residual: `{sc_sel['pendente']}` {_uc_rec}**")
            else:
                st.info("ℹ️ Nenhuma SC aberta para este material. A entrada será registrada como avulsa.")

            # v2.9.0: qtd fora do form → conversão em tempo real (form não faz rerun).
            limite_rec = float(sc_sel["pendente"]) if sc_sel else None
            qtd_default = min(1.0, limite_rec) if limite_rec else 1.0
            lbl_qtd = f"Qtd Recebida (em {_uc_rec}) *" if _tem_conv else "Qtd Recebida *"
            if limite_rec:
                qtd_r = st.number_input(lbl_qtd, min_value=0.01, max_value=limite_rec, step=1.0, value=qtd_default, key="rec_qtd")
            else:
                qtd_r = st.number_input(lbl_qtd, min_value=0.01, step=1.0, key="rec_qtd")
            if _tem_conv:
                _incr = qtd_r / _fator_rec
                st.caption(f":material/straighten: **{qtd_r:g} {_uc_rec}** ÷ fator {_fator_rec:g} = **+{_incr:g} {_ue_rec}** no estoque.")

            with st.form("form_rec"):
                st.markdown("##### :material/download: Dados do Recebimento")
                c2, c3 = st.columns(2)
                # v2.7.1: Fornecedor não é obrigatório (pré-preenche da SC quando há).
                forn   = c2.text_input("Fornecedor", value=(sc_sel.get("fornecedor_item") or sc_sel.get("fornecedor") or "") if sc_sel else "")
                dt_r   = c3.date_input("Data Recebimento", value=date.today())

                # v2.7.1: CC não é obrigatório — recebimentos MRO caem no Almoxarifado
                # por padrão (quase todas as SCs deste time vão para o MRO).
                _cc_opts = centros if centros else ["—"]
                _cc_default = next((i for i, c in enumerate(_cc_opts)
                                    if "ALMOXARIFADO" in str(c).upper()), 0)
                cc_r   = st.selectbox("Centro de Custo", _cc_opts, index=_cc_default,
                                      help="Padrão MRO: Almoxarifado. Ajuste se necessário.")
                obs_nf = st.text_input("Nota Fiscal / Documento *" if sc_sel else "Obs / Nota Fiscal")

                rec_b  = st.form_submit_button(":material/download: Confirmar Recebimento", width="stretch", type="primary")

            if rec_b:
                if sc_sel and not obs_nf.strip():
                    st.warning(":material/warning: Informe o número da Nota Fiscal para rastreabilidade.")
                elif sc_sel:
                    # qtd_r na UM de compra; registrar_recebimento_sc converte ao estoque.
                    ok, msg = registrar_recebimento_sc(
                        sc_id=sc_sel["id"], item_sc_id=sc_sel["item_sc_id"],
                        qtd_recebida=qtd_r, centro_custo=cc_r,
                        solicitante="Almoxarifado", emitente="Almoxarifado",
                        fornecedor=forn, data_recebimento=str(dt_r), obs_nf=obs_nf
                    )
                    if ok: st.success(f":material/check_circle: **Recebimento registrado!** {msg}"); time.sleep(2); st.rerun()
                    else:  st.error(f":material/cancel: {msg}")
                else:
                    # v2.9.0: entrada avulsa converte aqui (registrar_movimentacao é
                    # primitivo em unidade de ESTOQUE — a conversão é responsabilidade
                    # da borda, como no recebimento de SC).
                    _qtd_estoque = qtd_r / _fator_rec
                    _obs_conv = (f" | convertido {qtd_r:g} {_uc_rec} ÷ {_fator_rec:g} = "
                                 f"{_qtd_estoque:g} {_ue_rec}") if _tem_conv else ""
                    ok, msg = registrar_movimentacao(
                        item_id=item_rec["id"], tipo="entrada", quantidade=_qtd_estoque,
                        centro_custo=cc_r, solicitante="Almoxarifado", emitente="Almoxarifado",
                        observacao=f"Fornecedor: {forn} | {obs_nf}{_obs_conv}"
                    )
                    if ok: st.success(f":material/check_circle: **Entrada avulsa registrada!** {msg}"); time.sleep(2); st.rerun()
                    else:  st.error(f":material/cancel: {msg}")


def _render_requisicao():
    """Requisição de material — Nova Requisição + Histórico. v3.8.0: movido da página
    própria para uma aba da Movimentação. Usa guarda if/else (NÃO st.stop()) no fluxo
    de sucesso, para não matar as abas irmãs da Movimentação."""
    st.markdown("### :material/assignment: Requisição de Material")
    st.caption("Fluxo digital: abre-se a requisição (vai para a fila) e o almoxarife entrega o "
               "material (parcial ou total), dando baixa no estoque só na entrega — com autorização.")

    aba_nova, aba_fila, aba_hist_req = st.tabs([
        ":material/edit_note: Nova Requisição",
        ":material/list_alt: Fila / Separação",
        ":material/history: Histórico"])

    autorizadores_lista = listar_valores("autorizador") or ["Gestor", "Líder", "Reserva"]

    with aba_nova:
        if "itens_req" not in st.session_state: st.session_state.itens_req = []
        if "req_confirmada" not in st.session_state: st.session_state.req_confirmada = None

        # v3.8.0: guarda if/else (sem st.stop(), que mataria as abas irmãs da Movimentação).
        if st.session_state.req_confirmada:
            st.success(f"### :material/check_circle: Requisição {st.session_state.req_confirmada} criada!")
            st.info("A requisição entrou na **Fila / Separação**. O estoque só é baixado quando o "
                    "almoxarife registrar a entrega (com autorização).")
            if st.button("Iniciar Nova Requisição", width="stretch"):
                st.session_state.req_confirmada = None
                st.rerun()
        else:
            # Padroniza os setores: registra em Configurações os que só existiam no
            # histórico (uma vez por sessão, idempotente) e monta o select a partir da
            # união (Configurações + histórico de movimentações/requisições).
            if not st.session_state.get("_setores_sync"):
                sincronizar_setores_config()
                st.session_state["_setores_sync"] = True

            # --- BLOCO 1: IDENTIFICAÇÃO ---
            with st.container():
                st.markdown("##### 1. Identificação da Demanda")
                c1, c2, c3 = st.columns(3)
                req_setor = c1.selectbox(
                    "Setor Solicitante *", options=[""] + listar_setores_conhecidos(),
                    index=0, accept_new_options=True,
                    help="Escolha um setor já usado ou digite um novo para padronizar o cadastro.")
                req_emit  = c2.text_input("Nome do Emitente *")
                opcoes_cc = [""] + (listar_valores("centro_custo") or [])
                req_cc    = c3.selectbox("Centro de Custo *", options=opcoes_cc, index=0)

            st.markdown("---")

            # --- BLOCO 2: SELEÇÃO DE MATERIAIS ---
            with st.container():
                st.markdown("##### 2. Adicionar Materiais")
                _, item_req_add, _ = sel_material("Pesquise o material para requisitar", "sel_req_add")

                if item_req_add:
                    # Card de disponibilidade rápida (cores acompanham o tema via PAL)
                    st.markdown(f"""
                        <div style="border: 1px solid {PAL['painel_borda']}; padding: 10px; border-radius: 5px; background-color: {PAL['painel_bg']}; margin-bottom: 10px;">
                            <span style="color: {PAL['accent']}; font-weight: bold;">DISPONÍVEL:</span> {item_req_add.get('estoque_atual',0)} {item_req_add.get('unidade','UN')}
                        </div>
                    """, unsafe_allow_html=True)

                with st.form("form_add_item_req", clear_on_submit=True):
                    qtd_sol = st.number_input(
                        "Qtd Solicitada *", min_value=1.0, step=1.0, value=1.0,
                        help="Quanto o setor está pedindo. A quantidade efetivamente ENTREGUE é definida "
                             "na aba Fila, na hora da entrega (pode ser parcial). Pode-se solicitar mais "
                             "do que o saldo atual — a fila mostra o que dá para atender.")
                    add_item = st.form_submit_button(":material/add: ADICIONAR À LISTA", width="stretch")

                if add_item:
                    if not item_req_add:
                        st.warning(":material/warning: Selecione um material antes de adicionar.")
                    else:
                        st.session_state.itens_req.append({
                            "item_id": item_req_add["id"], "part_number": item_req_add["part_number"],
                            "nome_item": item_req_add["nome_item"], "unidade": item_req_add.get("unidade","UN"),
                            "estoque_disponivel": item_req_add.get("estoque_atual",0),
                            "quantidade_solicitada": qtd_sol,
                        })
                        st.rerun()

            # --- LISTA DE ITENS TEMPORÁRIA ---
            if st.session_state.itens_req:
                st.markdown("###### :material/inventory_2: Itens na Requisição Atual:")
                for idx, it in enumerate(st.session_state.itens_req):
                    with st.expander(f"{it['part_number']} — {it['nome_item']}", expanded=True):
                        c_info, c_del = st.columns([5, 1])
                        c_info.write(f"**Solicitado:** {it['quantidade_solicitada']:g} {it['unidade']} "
                                     f"· _saldo hoje:_ {it.get('estoque_disponivel', 0):g}")

                        if c_del.button("Remover", key=f"rm_req_{idx}", type="primary"):
                            st.session_state.itens_req.pop(idx)
                            st.rerun()
            else:
                st.info("Aguardando adição de materiais...")

            st.markdown("---")

            # --- BLOCO 3: OBSERVAÇÕES E ENVIO ---
            # v4.7.0: autorização e SESMT saíram da criação — passaram para a ENTREGA
            # (aba Fila / Separação), que é o momento em que o material realmente sai.
            # Aqui só se ABRE o pedido; nada é baixado do estoque ainda.
            with st.container():
                st.markdown("##### 3. Observações e Envio")
                obs_req = st.text_area(
                    "Observações Gerais da Requisição", height=70,
                    placeholder="Opcional. Ex.: urgência, referência de OS, local de entrega...")

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(":material/send: CRIAR REQUISIÇÃO (enviar para a fila)", type="primary", width="stretch"):
                erros = []
                if not req_setor or not req_emit:
                    erros.append("Preencha Setor e Emitente (campos com *).")
                if not st.session_state.itens_req:
                    erros.append("A lista de materiais está vazia.")

                if erros:
                    for e in erros: st.error(e)
                else:
                    with st.spinner("Criando requisição..."):
                        ok, resultado = criar_requisicao(
                            setor=req_setor, emitente=req_emit, centro_custo=req_cc,
                            autorizador_tipo="", autorizador_nome="",
                            entrega_individual=False, destinatarios=[],
                            sesmt=False, sesmt_responsavel="",
                            itens=st.session_state.itens_req, observacoes=obs_req
                        )
                        if ok:
                            st.session_state.itens_req = []
                            st.session_state.req_confirmada = resultado
                            st.rerun()
                        else:
                            st.error(f"Erro ao criar requisição: {resultado}")

    # --- ABA: FILA / SEPARAÇÃO (v4.7.0) ---
    with aba_fila:
        st.markdown("### :material/list_alt: Fila de Separação")
        st.caption("Requisições aguardando entrega. Registre a saída (parcial ou total) — só aqui o "
                   "estoque é baixado. Material só sai com autorização (gestor; +SESMT se for EPI/SSO).")

        abertas = listar_requisicoes_abertas()
        if not abertas:
            st.success(":material/inventory: Nenhuma requisição pendente na fila. Tudo em dia!")
        else:
            mp1, mp2 = st.columns(2)
            mp1.metric(":material/pending_actions: Requisições na fila", len(abertas))
            mp2.metric(":material/hourglass_top: Mais antiga",
                       str(min(a["data_hora"] for a in abertas))[:10])

            def _fmt_fila(a):
                _falt = int(a.get("itens_pendentes") or 0)
                return (f"{a['numero_requisicao']} · {a['setor']} · {a['emitente']} "
                        f"· {a['status']} · {_falt} pendente(s)")

            opc_fila = {_fmt_fila(a): a for a in abertas}
            sel_f = st.selectbox("Escolha a requisição para separar/entregar:",
                                 [""] + list(opc_fila.keys()), key="fila_sel")

            req = opc_fila.get(sel_f) if sel_f else None
            if req:
                req_id = req["id"]
                st.markdown(f"#### :material/assignment: {req['numero_requisicao']} "
                            f"— {req['setor']} · {req['emitente']}")
                st.caption(f"Aberta em {str(req['data_hora'])[:16]} · "
                           f"C.Custo: {req.get('centro_custo') or '—'} · Status: **{req['status']}**")
                if req.get("observacoes"):
                    st.info(f":material/sticky_note_2: {req['observacoes']}")

                itens_f = listar_itens_requisicao(req_id)

                st.markdown("##### 1. Itens — quanto entregar agora")
                entregas = []
                for it in itens_f:
                    falta = float(it["quantidade_solicitada"]) - float(it["quantidade_atendida"])
                    disp = float(it.get("estoque_atual") or 0)
                    ci1, ci2, ci3 = st.columns([3, 2, 2])
                    ci1.markdown(f"**{it['part_number']}** — {it['nome_item']}")
                    ci1.caption(f"Solicitado {float(it['quantidade_solicitada']):g} · "
                                f"atendido {float(it['quantidade_atendida']):g} · "
                                f"falta {max(falta, 0):g} {it['unidade']}")
                    ci2.markdown(f":material/inventory_2: Disp.: **{disp:g}** {it['unidade']}")
                    if falta <= 0:
                        ci3.success("Completo")
                        continue
                    _max = float(min(falta, disp))
                    q = ci3.number_input(
                        "Entregar", min_value=0.0,
                        max_value=float(disp) if disp > 0 else 0.0,
                        value=_max if _max > 0 else 0.0, step=1.0,
                        key=f"ent_{req_id}_{it['id']}",
                        help="Sem saldo em estoque para este item." if disp <= 0 else None)
                    if q > 0:
                        entregas.append({"item_req_id": it["id"], "quantidade": float(q)})

                st.markdown("##### 2. Autorização da saída")
                ca1, ca2 = st.columns(2)
                f_aut_tipo = ca1.selectbox("Tipo de Autorizador *", autorizadores_lista, key=f"aut_t_{req_id}")
                f_aut_nome = ca2.text_input("Nome do Autorizador (gestor) *", key=f"aut_n_{req_id}")
                f_sesmt = st.checkbox("Material SESMT? (EPI/SSO — exige responsável do SESMT)",
                                      key=f"sesmt_{req_id}")
                f_sesmt_resp = ""
                if f_sesmt:
                    f_sesmt_resp = st.text_input("Responsável SESMT *", key=f"sesmt_r_{req_id}")

                if st.button(":material/local_shipping: REGISTRAR ENTREGA", type="primary",
                             width="stretch", key=f"btn_ent_{req_id}"):
                    if not entregas:
                        st.warning("Informe ao menos um item com quantidade a entregar.")
                    else:
                        ok, res = entregar_requisicao(
                            req_id, entregas, f_aut_tipo, f_aut_nome, f_sesmt, f_sesmt_resp)
                        if ok:
                            st.success(f":material/check_circle: Entrega registrada. Status: **{res}**.")
                            st.rerun()
                        else:
                            st.error(f":material/cancel: {res}")

                st.markdown("---")
                with st.expander(":material/add_circle: Adicionar item (o caso 'põe no mesmo pedido')"):
                    _, item_add_f, _ = sel_material("Material para incluir nesta requisição", f"add_fila_{req_id}")
                    qadd = st.number_input("Qtd Solicitada", min_value=1.0, step=1.0, value=1.0, key=f"qadd_{req_id}")
                    if st.button(":material/add: Incluir item", key=f"btn_add_{req_id}"):
                        if not item_add_f:
                            st.warning("Selecione um material.")
                        else:
                            ok, res = adicionar_itens_requisicao(
                                req_id, [{"item_id": item_add_f["id"], "quantidade_solicitada": qadd}])
                            if ok:
                                st.success(res)
                                st.rerun()
                            else:
                                st.error(res)

                if req["status"] == "Aberta":
                    if st.button(":material/cancel: Cancelar requisição (nada foi entregue)",
                                 key=f"btn_cancel_{req_id}"):
                        ok, res = cancelar_requisicao(req_id)
                        if ok:
                            st.warning(res)
                            st.rerun()
                        else:
                            st.error(res)

    # --- ABA: HISTÓRICO ---
    with aba_hist_req:
        st.markdown("### :material/history: Histórico de Requisições")
        reqs = listar_requisicoes(limit=500)
        if not reqs:
            st.info("Nenhuma requisição registrada até o momento.")
        else:
            df_all = pd.DataFrame(reqs)

            # v3.4.0 — resumo em métricas
            _itens = int(pd.to_numeric(df_all.get("total_itens"), errors="coerce").fillna(0).sum())
            m1, m2, m3 = st.columns(3)
            m1.metric(":material/receipt_long: Requisições", len(df_all))
            m2.metric(":material/inventory_2: Itens requisitados", _itens)
            m3.metric(":material/domain: Setores atendidos", int(df_all["setor"].nunique()))

            # v3.4.0 — filtros (setor + busca livre)  ·  v4.3.0 — busca também por PN/material
            fc1, fc2 = st.columns(2)
            setores_op = ["Todos"] + sorted(s for s in df_all["setor"].dropna().unique())
            f_set = fc1.selectbox("Setor", setores_op, key="hist_req_setor")
            f_txt = fc2.text_input(":material/search: Buscar (Nº, emitente, autorizador ou PN/material)", key="hist_req_busca")

            fil = df_all.copy()
            if f_set != "Todos":
                fil = fil[fil["setor"] == f_set]
            if f_txt.strip():
                t = f_txt.strip().lower()
                # v4.3.0 — índice PN/nome por requisição (1 query; só quando há busca).
                mapa_pn = mapa_pn_por_requisicao()
                fil = fil[fil.apply(
                    lambda r: t in str(r.get("numero_requisicao", "")).lower()
                    or t in str(r.get("emitente", "")).lower()
                    or t in str(r.get("autorizador_nome", "")).lower()
                    or t in mapa_pn.get(r.get("id"), ""), axis=1)]

            # v3.4.0 — mini-gráfico: requisições por setor
            if not fil.empty:
                by_set = fil["setor"].fillna("—").value_counts()
                if len(by_set):
                    st.plotly_chart(
                        _barv(list(by_set.index), [int(v) for v in by_set.values]),
                        width="stretch", config={"displayModeBar": False})

            # v4.1.0 — "Detalhes da Requisição" vem ANTES da tabela e mais completo
            # (emitente, autorizador, centro de custo, setor e a lista de itens).
            st.markdown("#### :material/search: Detalhes da Requisição")
            opcoes_req = {f"REQ-{r['numero_requisicao']} | {r['setor']} | {str(r['data_hora'])[:10]}": r
                          for r in fil.to_dict("records")}
            sel_req = st.selectbox("Escolha uma requisição para ver os detalhes:",
                                   [""] + list(opcoes_req.keys()))

            if sel_req:
                r_det = opcoes_req[sel_req]
                with st.container(border=True):
                    st.markdown(f"**Resumo REQ-{r_det['numero_requisicao']}** · "
                                f"{str(r_det.get('data_hora',''))[:16]} · "
                                f"Status: **{r_det.get('status') or '—'}**")
                    c_a, c_b, c_c, c_d = st.columns(4)
                    c_a.write(f":material/person: **Emitente:** {r_det['emitente']}")
                    c_b.write(f":material/edit: **Autorizador:** {r_det.get('autorizador_nome') or '—'}")
                    c_c.write(f":material/apartment: **C.Custo:** {r_det['centro_custo']}")
                    c_d.write(f":material/domain: **Setor:** {r_det.get('setor') or '—'}")

                    itens_det = listar_itens_requisicao(r_det["id"])
                    if itens_det:
                        df_det = pd.DataFrame(itens_det)[["part_number", "nome_item", "quantidade_solicitada", "quantidade_atendida", "unidade"]]
                        df_det.columns = ["PN", "Material", "Solicitado", "Atendido", "UN"]
                        st.caption(f"{len(df_det)} item(ns) nesta requisição:")
                        st.dataframe(df_det, width="stretch", hide_index=True)
                    else:
                        st.caption("Sem itens detalhados para esta requisição.")

            st.markdown("---")
            st.markdown("##### :material/table_rows: Todas as requisições")
            df_reqs = fil[["numero_requisicao", "data_hora", "status", "setor", "emitente",
                           "autorizador_nome", "total_itens"]].copy()
            df_reqs.columns = ["Nº Req", "Data/Hora", "Status", "Setor", "Emitente",
                               "Autorizador", "Qtd Itens"]
            st.dataframe(df_reqs, width="stretch", hide_index=True)


def _render_ficha_visao_geral(ficha):
    """Corpo original da Ficha 360 (v4.4.0: extraido para a 1a aba \"Visao Geral\")."""
    it = ficha["item"]
    rep = ficha["reposicao"]
    mat = ficha["maturidade"]

    def _g(v):  # número curto e seguro (None -> 0)
        return f"{(v or 0):g}"

    def _g1(v):  # arredonda a 1 casa (4.46667 -> 4.5); inteiros ficam sem ".0"
        return f"{round(v or 0, 1):g}"

    # ── Cabeçalho: imagem + cadastro ──────────────────────────────────
    col_img, col_cad = st.columns([1, 2])
    with col_img:
        if ficha["imagem_abs"]:
            st.image(ficha["imagem_abs"], use_container_width=True)
        else:
            st.markdown(
                f"<div style='border:1px dashed {PAL['painel_borda']};border-radius:8px;"
                f"padding:32px;text-align:center;color:{PAL['texto_suave']};'>Sem imagem</div>",
                unsafe_allow_html=True)
        with st.expander(":material/image: Imagem do produto"):
            up = st.file_uploader(
                "Enviar/atualizar (png/jpg/webp, até 5 MB)",
                type=["png", "jpg", "jpeg", "webp", "gif"], key="ficha_img_up")
            cb1, cb2 = st.columns(2)
            if cb1.button(":material/save: Salvar", key="ficha_img_save",
                          disabled=up is None, width="stretch"):
                ok, msg = salvar_imagem_item(it["id"], up.name, up.getvalue())
                if ok:
                    st.success("Imagem salva."); st.rerun()
                else:
                    st.error(msg)
            if ficha["imagem_abs"] and cb2.button(
                    ":material/delete: Remover", key="ficha_img_del", width="stretch"):
                remover_imagem_item(it["id"]); st.rerun()
    with col_cad:
        st.subheader(f"{it['part_number']} — {it['nome_item']}")
        # v4.1.0: "Setor que mais consome" (top do consumo real por setor) no lugar do
        # antigo "Setor responsável" (campo estático, ~98% "Improdutivo"); Local mostra
        # as 2 locações quando houver.
        _top_setor = (ficha["departamentos"]["por_setor"][0]["chave"]
                      if ficha["departamentos"]["por_setor"] else "—")
        _locais = " · ".join(
            x for x in [it.get('local_armazenagem'), it.get('local_armazenagem_2')] if x
        ) or "—"
        st.markdown(
            f"**Categoria/Tipo:** {it.get('tipo_material') or '—'}  \n"
            f"**Unidade:** {it.get('unidade') or '—'} · "
            f"**Criticidade:** {it.get('importancia') or '—'}  \n"
            f"**Setor que mais consome:** {_top_setor}  \n"
            f"**Local:** {_locais}"
            + (f" · Caixa {it.get('caixa_identificacao')}" if it.get('caixa_identificacao') else "")
        )
        if it.get("descricao"):
            st.caption(it["descricao"])

        # v2.7.0 — Situação de consumo (real = saída por requisição)
        if it.get("sem_movimentacao"):
            st.caption("⚪ **Situação de consumo:** Sem movimentação "
                       "(nunca teve saída por requisição) — fora da lista de compra.")
        else:
            _ult = it.get("ultima_requisicao_data")
            _ult_txt = f" · última em {fmt(_ult)}" if _ult else ""
            st.caption(f"🟢 **Situação de consumo:** {it.get('qtd_requisicoes', 0)} "
                       f"requisição(ões){_ult_txt}.")

    # ── Conversão de unidades (v2.9.0) ────────────────────────────────
    _fat_f = float(it.get("fator_conversao") or 1.0) or 1.0
    _uc_f = it.get("unidade_compra")
    if abs(_fat_f - 1.0) > 1e-9 and _uc_f:
        st.caption(f":material/sync: **Conversão:** compra em **{_uc_f}** · **1 {it.get('unidade') or 'UN'}** "
                   f"de estoque = **{_fat_f:g} {_uc_f}** (fator {_fat_f:g}).")

    # ── Recomendação de reposição (read-only, reusa v2.5) ─────────────
    un = it.get("unidade") or "UN"
    if it.get("sem_movimentacao"):
        st.info("⚪ **Sem movimentação** — item sem consumo real; fora da lista "
                "de compra. Revise no **Assistente de Reposição** (opção "
                "\"Mostrar itens sem movimentação\") se for um spare a manter em estoque.")
    elif rep["precisa"] and rep["qtd_sugerida"] > 0:
        st.warning(f":material/shopping_cart: **{rep['prioridade']}** — repor **{rep['qtd_sugerida']} "
                   f"{un}**. {rep['justificativa']}")
    elif rep["precisa"]:
        # v2.7.1: gatilho ativo mas qtd = 0 → o saldo residual já cobre o alvo
        # (antes aparecia "repor 0", confuso).
        st.info(f"🟡 **{rep['prioridade']}** — **sem compra agora**: o saldo residual "
                f"(**{_g(it.get('estoque_em_transito'))} {un}** já negociados) "
                f"cobre o alvo de **{_g(rep['alvo'])} {un}**. Reavaliar quando o material chegar.")
    else:
        st.success(":material/check_circle: Sem necessidade de reposição no momento "
                   "(estoque + saldo residual cobrem o horizonte).")

    # ── Estoque / cobertura / giro ────────────────────────────────────
    st.divider()
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Estoque atual", _g(it.get("estoque_atual")))
    e2.metric("Quantidade Mínima", _g(it.get("estoque_minimo")),
              help="Baseado no reajuste de compras.")
    e3.metric("Quantidade Máxima", _g(it.get("estoque_maximo")),
              help="Baseado no reajuste de compras.")
    e4.metric("Saldo Item (PO)", _g(it.get("estoque_em_transito")),
              help="Qtd já negociada em pedidos (PO/SC) aprovados que ainda falta chegar.")

    cob = it.get("dias_cobertura")
    giro = ficha["giro"]
    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Dias até acabar",
              f"{cob:.0f} d" if cob is not None and cob < PREVISAO_RUPTURA_SEM_RISCO else "—",
              help="Quantos dias o estoque atual ainda dura no ritmo de consumo atual "
                   "(estoque atual ÷ consumo médio diário). '—' = sem consumo registrado, "
                   "logo não há previsão de término.")
    tend = it.get("tendencia_label")
    tend_txt = (f"{tend} {'+' if (it.get('tendencia_pct') or 0) >= 0 else ''}"
                f"{_g(it.get('tendencia_pct'))}%") if tend else None
    g2.metric("Consumo/dia", f"{_g1(it.get('consumo_medio_diario'))} {un}/dia", delta=tend_txt,
              delta_color="inverse",
              help="Média de quanto sai por dia deste item, pelas saídas reais por requisição "
                   "na janela de 30 dias. A seta indica a tendência vs. os 30 dias anteriores.")
    _cons_mes = (ficha.get("classificacao") or {}).get("consumo_mensal_ponderado")
    g3.metric("Consumo/Mensal",
              f"{_g1(_cons_mes)} {un}/mês" if _cons_mes is not None else "—", delta=tend_txt,
              delta_color="inverse",
              help="Consumo médio por mês: média PONDERADA dos últimos 3 meses completos, com o "
                   "mês mais recente pesando mais (3/2/1). Usa as saídas reais por mês (dias úteis "
                   "já embutidos); meses sem saída contam 0 e a média decai se o item parar. A "
                   "seta é a mesma tendência do Consumo/dia.")
    g4.metric("Giro anual", _g(giro["giro_anual"]),
              help="Quantas vezes o estoque \"vira\" no ano: "
                   "(saídas dos últimos 90 d ÷ estoque médio das fotos diárias) × (365 ÷ 90). "
                   "Base: estoque_snapshots (fotos diárias do saldo) + saídas de movimentações. "
                   "Maior = gira mais rápido; menor = parado. "
                   f"Tempo médio em estoque: "
                   f"{giro['tempo_medio_dias'] if giro['tempo_medio_dias'] else '—'} d · "
                   f"baseado em {giro['n_snapshots']} fotos.")
    lt_calc = it.get("lead_time_calculado")
    g5.metric("Lead time (Compras)", f"{int(it.get('lead_time_dias') or 0)} d",
              help=(f"Calculado (sugestão): {int(lt_calc)} d "
                    f"({it.get('lead_time_calculado_amostras') or 0} amostras, "
                    f"{it.get('lead_time_calculado_origem') or '—'})" if lt_calc
                    else "Sem lead time calculado ainda."))

    # ── Consumo (30/60/90) + Valor ────────────────────────────────────
    cc1, cc2 = st.columns(2)
    with cc1:
        with st.container(border=True):
            st.markdown("##### :material/trending_down: Consumo médio/dia por janela")
            st.caption("Média de saída por dia em 3 janelas (30/60/90 dias). Comparar as três "
                       "mostra se o consumo está **acelerando** (30d > 90d) ou **desacelerando**.")
            _cons_j = [round(it.get("consumo_30d") or 0, 1),
                       round(it.get("consumo_60d") or 0, 1),
                       round(it.get("consumo_90d") or 0, 1)]
            st.plotly_chart(
                _barv(["30 dias", "60 dias", "90 dias"], _cons_j,
                      textos=[f"{v:g}" for v in _cons_j]),
                width="stretch", config={"displayModeBar": False})
    with cc2:
        with st.container(border=True):
            st.markdown("##### :material/payments: Valor")
            st.caption("Quanto este item representa em dinheiro: **parado em estoque** hoje e "
                       "**consumido no ano** (estimado pelo último preço de compra).")
            vc = ficha["valor"]["valor_consumido"]
            st.metric("Valor em estoque",
                      f"R$ {ficha['valor']['valor_estoque']:,.2f}")
            # v2.7.1: valor unitário (preço de referência) logo abaixo
            _preco_un = vc.get("preco") or 0
            st.caption(f"Valor unitário: **{vc['moeda']} {_preco_un:,.2f}** / {un} "
                       f"· origem {vc['origem']}")
            st.metric(f"Valor consumido (YTD {date.today().year})",
                      f"{vc['moeda']} {vc['valor']:,.2f}",
                      help=f"Estimativa (último preço, origem {vc['origem']}). "
                           f"Acumulado de 01/01/{date.today().year} até hoje.")
            if ficha["abc"]:
                st.caption(f"Curva ABC (valor): classe **{ficha['abc']['classe']}** "
                           f"· {ficha['abc']['pct_acumulado']}% acumulado.")

    # ── Evolução de preço ─────────────────────────────────────────────
    ep = ficha["evolucao_preco"]
    if ep:
        st.markdown("##### :material/trending_up: Evolução de preço")
        df_ep = pd.DataFrame(ep)
        df_ep["data"] = pd.to_datetime(df_ep["data"], errors="coerce")
        st.line_chart(df_ep.dropna(subset=["data"]).set_index("data")["preco_unitario"])

    # ── Quem consome (departamentos / centros de custo) ───────────────
    st.markdown("##### :material/group: Quem consome (últimos 180 dias)")
    dep = ficha["departamentos"]
    if dep["total"] <= 0:
        st.caption("Sem saídas registradas no período.")
    else:
        d1, d2 = st.columns(2)
        d1.caption("Por centro de custo")
        d1.dataframe(pd.DataFrame([
            {"Centro de custo": r["chave"], "Qtd": r["qtd"], "%": r["pct"]}
            for r in dep["por_centro_custo"]], ), hide_index=True, width="stretch")
        d2.caption("Por setor")
        d2.dataframe(pd.DataFrame([
            {"Setor": r["chave"], "Qtd": r["qtd"], "%": r["pct"]}
            for r in dep["por_setor"]]), hide_index=True, width="stretch")

    # ── Fornecedores ──────────────────────────────────────────────────
    with st.expander(f":material/apartment: Fornecedores ({len(ficha['fornecedores'])})"):
        fs = ficha["fornecedores"]
        if not fs:
            st.caption("Sem fornecedores vinculados (vêm dos pedidos do Relatório de SCs).")
        else:
            st.dataframe(pd.DataFrame([{
                "Fornecedor": f["fornecedor"], "Último Preço": f["ultimo_preco"],
                "Moeda": f["moeda"], "Nº Compras": f["n_compras"],
                "Lead Time (d)": f["lead_time_fornecedor"], "E-mail": f["email"] or "—",
                "Melhor preço": "⭐" if f.get("melhor") else "",
            } for f in fs]), hide_index=True, width="stretch")

    # ── Histórico de SCs / POs ────────────────────────────────────────
    with st.expander(f":material/receipt_long: Histórico de SCs / POs ({len(ficha['scs_pos'])})"):
        sp = ficha["scs_pos"]
        if not sp:
            st.caption("Nenhuma SC registrada para este item.")
        else:
            st.dataframe(pd.DataFrame([{
                "SC": s["numero_sc"], "PO": s.get("po_item") or s.get("numero_po") or "—",
                "Fornecedor": s.get("fornecedor_item") or "—", "Status": s.get("status"),
                "Abertura": fmt(s.get("data_abertura")),
                "Solic.": s.get("quantidade_solicitada"),
                "Receb.": s.get("quantidade_recebida"), "Pendente": s.get("pendente"),
            } for s in sp]), hide_index=True, width="stretch")

    # ── Histórico de movimentações ────────────────────────────────────
    with st.expander(f":material/sync: Movimentações recentes ({len(ficha['movimentacoes'])})"):
        mv = ficha["movimentacoes"]
        if not mv:
            st.caption("Sem movimentações.")
        else:
            st.dataframe(pd.DataFrame([{
                "Data": fmt(m.get("data_hora")), "Tipo": m.get("tipo"),
                "Qtd": m.get("quantidade"), "Saldo": m.get("saldo_apos"),
                "Centro de custo": m.get("centro_custo") or "—",
                "Setor": m.get("setor") or "—", "Obs": m.get("observacao") or "",
            } for m in mv]), hide_index=True, width="stretch")

    # ── Histórico de Part Number ──────────────────────────────────────
    if ficha["historico_pn"]:
        with st.expander(f":material/bookmark: Histórico de Part Number ({len(ficha['historico_pn'])})"):
            st.dataframe(pd.DataFrame(ficha["historico_pn"]),
                         hide_index=True, width="stretch")

    # ── Classificação de demanda / XYZ / Sazonalidade (v2.10.0) ───────
    st.divider()
    st.markdown("##### :material/science: Padrão de demanda & variabilidade")
    cls = ficha.get("classificacao") or {}
    dem = cls.get("demanda") or {}
    xyz = cls.get("xyz") or {}
    saz = cls.get("sazonalidade") or {}
    cm = cls.get("consumo_mensal") or []

    xd1, xd2 = st.columns(2)
    with xd1:
        _emoji = dem.get("emoji") or "⚪"
        _pad = dem.get("padrao") or "Sem dados"
        st.markdown(f"**Demanda:** {_emoji} **{_pad}**")
        st.caption(dem.get("explicacao") or "")
        if dem.get("adi") is not None:
            st.caption(f"ADI {dem['adi']} · CV² {dem['cv2']} · "
                       f"{dem['n_eventos']} semana(s) com consumo · "
                       f"confiança {dem.get('confianca', '—')}.")
    with xd2:
        _cx = xyz.get("classe")
        if _cx:
            _rot = {"X": "estável", "Y": "variável", "Z": "errático"}.get(_cx, "")
            st.markdown(f"**XYZ:** **{_cx}** ({_rot})")
            st.caption(f"Coef. de variação mensal {xyz.get('cv')} · "
                       f"{xyz.get('n_meses')} mês(es) · confiança {xyz.get('confianca', '—')}.")
        else:
            st.markdown("**XYZ:** —")
            st.caption("Precisa de ≥2 meses de consumo para medir a variabilidade.")

    if cm:
        st.markdown("###### :material/calendar_month: Consumo real por mês")
        st.plotly_chart(
            _barv([_mes_label(x["mes"]) for x in cm],
                  [round(x["qtd"], 1) for x in cm],
                  textos=[f"{round(x['qtd'], 1):g}" for x in cm]),
            width="stretch", config={"displayModeBar": False})

    if not saz.get("disponivel"):
        st.caption(f":material/eco: **Sazonalidade:** amadurecendo — "
                   f"{saz.get('meses_atuais', 0)}/{saz.get('meses_necessarios', 12)} "
                   "meses (precisa de 1 ciclo anual completo para um perfil confiável).")
    st.caption(f":material/calendar_month: Indicadores de série baseados em ~{mat['dias']} dias de histórico — "
               "diagnóstico que amadurece conforme os dados acumulam. A base do "
               "Compras (mín/máx/lead time/categoria) permanece intocada.")


def _render_ficha_guarda_chuva(ficha):
    """[DEPRECADO em v4.9.0 — NÃO MAIS LIGADO À UI] A sub-aba Guarda-Chuva saiu da Ficha
    360 e virou um controle MANUAL próprio em "Controle de SC → ☂️ Guarda-Chuva"
    (`_render_guarda_chuva_controle`, tabela `guarda_chuva`). Esta versão baseada em SCs
    reais (`ficha['scs_pos']`) fica aqui só como referência e pode ser removida num
    follow-up (os serviços que ela usa seguem cobertos por test_v457).

    v4.4.0 — Guarda-Chuva: pedidos (SC/PO) do material por fornecedor, com kanban de
    4 estágios (Pedido Colocado → Aguardando Entrega → NF Emitida → Recebido) e o saldo
    residual pendente agregado por fornecedor, sobre ficha['scs_pos'].

    v4.5.7 — kanban FUNCIONAL: cada card tem 'Editar / Receber' que abre um dialog para
    editar os metadados do pedido (Nº PO, datas, NF, qtd negociada) via
    `atualizar_pedido_guarda_chuva` e registrar entrega via `registrar_recebimento_sc`
    (ledger). O estágio continua DERIVADO dos campos — mover o card = editar o campo que o
    define; nada de estágio armazenado."""
    it = ficha["item"]
    scs = ficha.get("scs_pos") or []
    un = it.get("unidade") or ""

    # v4.5.6 — removidos os cards "Em trânsito (pedidos)" e "Saldo total projetado"
    # (pedido do usuário); o saldo pendente já é detalhado no kanban e na tabela por
    # fornecedor logo abaixo.
    est = float(it.get("estoque_atual") or 0)
    st.metric("Saldo em estoque", f"{est:g} {un}")

    if not scs:
        st.info("Este material não tem pedidos (SC/PO) registrados.")
        return

    fornecedores = sorted({(s.get("fornecedor_item") or "Sem fornecedor") for s in scs})
    escolha = st.selectbox("Fornecedor", ["Todos"] + fornecedores, key="gc_fornecedor")
    linhas = scs if escolha == "Todos" else [
        s for s in scs if (s.get("fornecedor_item") or "Sem fornecedor") == escolha]

    def _estagio(s):
        if (s.get("pendente") or 0) <= 0:
            return "Recebido"
        if s.get("documento_nf"):
            return "NF Emitida"
        if s.get("data_prev_nfe") or s.get("data_necessidade"):
            return "Aguardando Entrega"
        return "Pedido Colocado"

    st.markdown("##### :material/view_kanban: Kanban de pedidos")
    estagios = ["Pedido Colocado", "Aguardando Entrega", "NF Emitida", "Recebido"]
    cols = st.columns(len(estagios))
    for col, nome in zip(cols, estagios):
        with col:
            grupo = [s for s in linhas if _estagio(s) == nome]
            st.markdown(f"**{nome}** · {len(grupo)}")
            for s in grupo:
                with st.container(border=True):
                    st.caption(f"SC {s.get('numero_sc') or '—'} · "
                               f"PO {s.get('po_item') or s.get('numero_po') or '—'}")
                    st.markdown(f"**{s.get('fornecedor_item') or '—'}**")
                    st.caption(
                        f"Neg. {(s.get('quantidade_negociada') or 0):g} · "
                        f"Receb. {(s.get('quantidade_recebida') or 0):g} · "
                        f"Pend. {(s.get('pendente') or 0):g} {un}")
                    _prev = s.get("data_prev_nfe") or s.get("data_necessidade")
                    if _prev:
                        st.caption(f":material/event: Prev.: {str(_prev)[:10]}")
                    if s.get("documento_nf"):
                        st.caption(f":material/receipt_long: NF {s.get('documento_nf')}")
                    if st.button(":material/edit: Editar / Receber",
                                 key=f"gc_edit_{s['item_sc_id']}", width="stretch"):
                        st.session_state["_gc_pedido_edit"] = int(s["item_sc_id"])
                        st.rerun()

    grupos = agrupar_saldo_residual_por_fornecedor(scs)
    if grupos:
        st.markdown("##### :material/inventory: Saldo residual pendente por fornecedor")
        df = pd.DataFrame([{
            "Fornecedor": g["fornecedor"],
            "Pedidos c/ saldo": g["n_pedidos"],
            f"Saldo pendente ({un})": round(g["saldo_pendente"], 2),
        } for g in grupos])
        st.dataframe(df, width="stretch", hide_index=True)


if pagina in ROTAS_MIGRADAS:
    render_pagina(pagina)

# ══════════════════════════════════════════════════════════════════════════════
# MOVIMENTAÇÕES
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Movimentação":
    st.title(":material/sync: Movimentação")

    # v3.8.0 — Requisição e Receber Material aninhados aqui (abas), ao lado de Analytics,
    # Ajuste Rápido e Histórico. Os corpos vivem em _render_receber_material /
    # _render_requisicao (module-level) — sem duplicar nem mover blocos indentados.
    tab_dash, tab_rec, tab_req, tab_ajuste, tab_hist = st.tabs([
        ":material/bar_chart: Dashboard movimentações", ":material/inventory_2: Receber Material",
        ":material/assignment: Requisição", ":material/balance: Ajuste Rápido",
        ":material/history: Histórico Completo"])

    centros = listar_valores("centro_custo") or ["Geral"]

    with tab_rec:
        _render_receber_material()
    with tab_req:
        _render_requisicao()

    # === TAB: AJUSTE RÁPIDO DE ESTOQUE (v4.3.0 — 4 tipos) ===
    with tab_ajuste:
        with st.container(border=True):
            st.subheader(":material/balance: Ajuste Manual de Saldo")
            st.caption("Lançamentos avulsos (sem SC/Requisição): entradas e saídas pontuais, devoluções e perdas.")

            # Rótulo -> (tipo do ledger, sinal: +1 soma / -1 subtrai do estoque).
            # O CHECK de movimentacoes.tipo continua ('entrada','saida','devolucao');
            # o rótulo é guardado em `motivo` para o filtro do Histórico (v4.3.0).
            TIPOS_AJUSTE = {
                "Entrada Avulsa":    ("entrada",   +1),
                "Devolução":         ("devolucao", +1),
                "Perda de Material": ("saida",     -1),
                "Saída Avulsa":      ("saida",     -1),
            }

            _, item_aj, _ = sel_material("Selecione o Item para Ajuste", "sel_ajuste_estoque")

            if item_aj:
                st.info(f"**Item:** `{item_aj['part_number']} — {item_aj['nome_item']}` | **Saldo Atual:** `{item_aj['estoque_atual']}`")

                c1, c2 = st.columns(2)
                rotulo_aj = c1.selectbox("Tipo de Ajuste", list(TIPOS_AJUSTE.keys()))
                tp, _sinal = TIPOS_AJUSTE[rotulo_aj]
                _hint = "soma ao estoque" if _sinal > 0 else "subtrai do estoque"
                qtd_aj = c2.number_input("Quantidade", min_value=0.01, step=1.0,
                                         help=f"'{rotulo_aj}' {_hint}.")

                obs_aj = st.text_input("Motivo / Observação *",
                                       placeholder="Ex: Avaria, sobra de contagem, devolução do setor...")
                resp_aj = st.text_input("Responsável pelo Ajuste *")

                if st.button(":material/check_circle: Confirmar Ajuste", type="primary", width="stretch"):
                    if not resp_aj or not obs_aj:
                        st.error("Preencha o responsável e o motivo para auditoria.")
                    elif _sinal < 0 and qtd_aj > item_aj['estoque_atual']:
                        st.error(f"Quantidade ({qtd_aj}) superior ao estoque disponível ({item_aj['estoque_atual']}).")
                    else:
                        ok, msg = registrar_movimentacao(
                            item_id=item_aj["id"], tipo=tp, quantidade=qtd_aj,
                            centro_custo=None, solicitante=resp_aj, emitente=resp_aj,
                            observacao=f"AJUSTE: {obs_aj}", motivo=rotulo_aj,
                            data_hora=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )
                        if ok:
                            st.success(f":material/check_circle: '{rotulo_aj}' registrado! Novo saldo: {msg}")
                            time.sleep(1.2)
                            st.rerun()
                        else:
                            st.error(f":material/cancel: Erro: {msg}")

    # === TAB 2: HISTÓRICO COMPLETO ===
    with tab_hist:
        with st.container(border=True):
            st.subheader(":material/history: Histórico de Movimentações")
            
            c1, c3 = st.columns([3, 1])
            f_item = c1.selectbox("Filtrar por Item", ["Todos"] + [f"{i['part_number']} - {i['nome_item']}" for i in listar_inventario()])
            limit = c3.number_input("Limite", min_value=50, max_value=1000, value=200, step=50)

            item_id_f = None
            if f_item != "Todos":
                pn_busca = f_item.split(" - ")[0]
                for i in listar_inventario():
                    if i['part_number'] == pn_busca:
                        item_id_f = i['id']
                        break

            movs = listar_movimentacoes(item_id=item_id_f, limit=int(limit))
            for _m in movs:
                _m["_categoria"] = categoria_movimentacao(_m)

            # v4.3.0 — filtro por Categoria (derivada de tipo+motivo): Requisição,
            # Entrada/Saída Avulsa, Devolução, Perda de Material, Conferência, etc.
            cats_presentes = sorted({_m["_categoria"] for _m in movs})
            f_cat = st.multiselect("Filtrar por Categoria", cats_presentes, default=cats_presentes)
            if f_cat:
                movs = [_m for _m in movs if _m["_categoria"] in f_cat]

            if movs:
                df_mov = pd.DataFrame(movs)
                df_mov['data_hora'] = df_mov['data_hora'].apply(fmt)
                
                cols_exib = ["data_hora", "part_number", "nome_item", "_categoria", "tipo", "quantidade", "saldo_apos", "emitente", "observacao"]
                df_exib = df_mov[cols_exib].copy()
                df_exib.columns = ["Data/Hora", "PN", "Nome", "Categoria", "Tipo", "Qtd", "Saldo Pós", "Responsável", "Obs"]

                # Estilização por tipo
                def colorir_tipo(val):
                    if val == 'entrada': return 'color: #2ecc71; font-weight: bold;'
                    if val == 'saida': return 'color: #e74c3c; font-weight: bold;'
                    if val == 'devolucao': return 'color: #3498db; font-weight: bold;'
                    return ''

                st.dataframe(
                    df_exib.style.map(colorir_tipo, subset=['Tipo']), # Mantém a cor original do tipo banco
                    width="stretch",
                    hide_index=True,
                    height=600,
                    column_config={
                        "Qtd": st.column_config.NumberColumn(format="%.2f"),
                        "Saldo Pós": st.column_config.NumberColumn(format="%.2f")
                    }
                )
            else:
                st.info("Nenhuma movimentação encontrada para os filtros selecionados.")
            
        # --- BOTÃO DE EXPORTAR (Abaixo do dataframe de histórico) ---
            st.markdown("---")
            col_btn, _ = st.columns([1, 4])
            with col_btn:
                    # Passamos os filtros atuais para a função
                _cats_all = bool(f_cat) and len(f_cat) == len(cats_presentes)
                df_exp_mov = exportar_movimentacoes_df(
                    item_id=item_id_f,
                    categorias_selecionadas=None if _cats_all else (f_cat or None))
                    
                if not df_exp_mov.empty:
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as w:
                        df_exp_mov.to_excel(w, index=False, sheet_name="Movimentacoes")
                        
                    st.download_button(
                        label="⬇️ Baixar planilha excel completo de todas as movimentações",
                        data=buf.getvalue(),
                        file_name=f"movimentacoes_{date.today().strftime('%d-%m-%Y')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_exp_mov"
                    )


    # === TAB 3: DASHBOARD MOVIMENTAÇÕES (VOLUME + DIVERGÊNCIAS + RUPTURA) ===
    with tab_dash:
        st.subheader(":material/bar_chart: Dashboard movimentações")

        # v4.1.0 — Tendência de consumo (comparação 30d vs. 30d anteriores)
        with st.container(border=True):
            st.markdown("#### :material/psychology: Tendência de consumo")
            st.caption("Compara o consumo dos últimos 30 dias com os 30 dias anteriores, item a item.")
            try:
                df_series = exportar_inventario_df()
            except Exception as e:
                df_series = pd.DataFrame()
                st.error(f"Erro ao calcular indicadores: {e}")
            if df_series.empty:
                st.caption("Sem dados suficientes.")
            else:
                if "Tendência" in df_series.columns:
                    vc = df_series["Tendência"].value_counts()
                    tca = st.columns(3)
                    tca[0].metric("🔺 Em alta", int(vc.get("Alta", 0)),
                                  help="Itens cujo consumo dos últimos 30 dias está mais de 15% ACIMA "
                                       "dos 30 dias anteriores (demanda aumentando vs. o mês passado).")
                    tca[1].metric("🔻 Em queda", int(vc.get("Queda", 0)),
                                  help="Itens cujo consumo dos últimos 30 dias está mais de 15% ABAIXO "
                                       "dos 30 dias anteriores (demanda diminuindo vs. o mês passado).")
                    tca[2].metric(":material/remove: Estável", int(vc.get("Estável", 0)),
                                  help="Itens cujo consumo dos últimos 30 dias variou menos de 15% "
                                       "em relação aos 30 dias anteriores (demanda estável).")

        st.markdown("---")

        # v2.3.0 — 💰 Financeiro: valor imobilizado · ABC por valor · evolução de preço
        with st.container(border=True):
            st.markdown("#### :material/payments: Financeiro (Valoração — estimativas rotuladas)")
            st.caption(
                "Valores são **estimativas** baseadas no **último preço** conhecido "
                "(SCM; na falta, último preço de PO/SC7). Não substituem o custo contábil."
            )
            try:
                vi = obter_valor_imobilizado()
            except Exception as e:
                vi = None
                st.error(f"Erro ao calcular valoração: {e}")

            if vi:
                k1, k2, k3 = st.columns(3)
                k1.metric(
                    ":material/payments: Valor imobilizado (BRL)", f"R$ {vi['total_brl']:,.2f}",
                    help="Σ (estoque atual × preço de valoração) dos itens em BRL. "
                         "Estimativa pelo último preço.",
                )
                k2.metric(
                    ":material/check_circle: Itens valorados", vi["itens_valorados"],
                    help="Itens com preço de referência conhecido (SCM ou histórico).",
                )
                k3.metric(
                    ":material/warning: Sem preço", vi["itens_sem_preco"],
                    help="Itens COM estoque mas SEM preço conhecido — subestimam o total. "
                         "Aparecem quando o material ainda não foi comprado via SCM/SC7.",
                )
                if vi["itens_nao_brl"]:
                    st.caption(
                        f":material/language: {vi['itens_nao_brl']} item(ns) com moeda ≠ BRL "
                        f"(≈ {vi['total_nao_brl']:,.2f} na moeda original) somados à parte — "
                        "sem conversão cambial nesta versão."
                    )

            fa, fb = st.columns(2)

            # Evolução do valor imobilizado (fotos diárias)
            with fa:
                st.markdown("**:material/trending_up: Evolução do valor imobilizado**")
                st.caption("Soma diária de (estoque × preço) — capital parado ao longo do tempo.")
                try:
                    ev = obter_evolucao_valor_imobilizado(dias=180)
                except Exception:
                    ev = {"serie": [], "n_snapshots": 0}
                if ev["serie"]:
                    df_ev = pd.DataFrame(ev["serie"]).set_index("data")
                    st.line_chart(df_ev["valor"], height=240)
                    st.caption(f"Baseado em {ev['n_snapshots']} foto(s) de estoque.")
                else:
                    st.info("Ainda sem fotos suficientes — a série amadurece a cada import diário.")

            # Curva ABC por valor
            with fb:
                st.markdown("**:material/bar_chart: Curva ABC por valor (últimos 90d)**")
                st.caption("Ranking pelo valor consumido = qtd saída × preço. A=80% · B=95% · C=resto.")
                try:
                    abc = obter_abc_valor(dias=90, limit=15)
                except Exception:
                    abc = []
                if abc:
                    df_abc_v = pd.DataFrame(abc)
                    df_abc_v["Item"] = df_abc_v["part_number"] + " • " + \
                        df_abc_v["nome_item"].astype(str).str.slice(0, 18)
                    st.dataframe(
                        df_abc_v[["Item", "classe", "valor", "pct_acumulado", "origem"]]
                        .rename(columns={"classe": "Classe", "valor": "Valor (R$)",
                                         "pct_acumulado": "% Acum.", "origem": "Origem"}),
                        hide_index=True, width="stretch", height=280,
                        column_config={
                            "Valor (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                            "% Acum.": st.column_config.NumberColumn(format="%.1f%%"),
                        },
                    )
                else:
                    st.info("Sem saídas valorizáveis no período.")

            # Top capital parado (valor alto + giro 0) — alvo de redução de imobilizado
            if not df_series.empty and "Valor em Estoque" in df_series.columns \
                    and "Giro(anual)" in df_series.columns:
                st.markdown("**:material/ac_unit: Top capital parado (maior valor em estoque, giro 0)**")
                st.caption("Dinheiro parado sem saída no período — candidatos a reduzir/realocar.")
                _cols_cap = [c for c in ["PN", "Nome", "UN", "Estoque Atual", "Valor em Estoque"]
                             if c in df_series.columns]
                parado_val = (df_series[(df_series["Giro(anual)"] == 0) &
                                        (df_series["Valor em Estoque"] > 0)]
                              .nlargest(8, "Valor em Estoque")[_cols_cap])
                if not parado_val.empty:
                    st.dataframe(
                        parado_val, hide_index=True, width="stretch",
                        column_config={"Valor em Estoque":
                                       st.column_config.NumberColumn(format="R$ %.2f")},
                    )
                else:
                    st.success(":material/check_circle: Nenhum item de valor relevante totalmente parado.")

        st.markdown("---")

        # --- LINHA 1: VOLUME E DIVERGÊNCIAS (Lado a Lado) ---
        c_vol, c_div = st.columns(2)

        # 1. VOLUME DE ENTRADAS E SAÍDAS
        with c_vol:
            with st.container(border=True):
                st.markdown("#### :material/inventory_2: Volume de Movimentações")
                periodo_sel = st.selectbox("Agrupar por:", ["Mensal", "Semanal", "Diário"], index=0, key="sel_periodo_vol")
                periodo_map = {"Mensal": "mensal", "Semanal": "semanal", "Diário": "diario"}
                df_anal = obter_analitico_movimentacoes(periodo=periodo_map[periodo_sel])

                if df_anal.empty:
                    st.caption("Sem dados no período.")
                else:
                    try:
                        df_pivot = df_anal.pivot_table(index='periodo', columns='tipo', values='vol_unidades', aggfunc='sum', fill_value=0)
                        for col in ['entrada', 'saida', 'devolucao']:
                            if col not in df_pivot.columns: df_pivot[col] = 0
                        
                        df_pivot = df_pivot.rename(columns={'entrada': 'Entradas', 'saida': 'Saídas', 'devolucao': 'Dev'})
                        df_pivot = df_pivot.sort_index(ascending=True)

                        t1, t2 = st.columns(2)
                        t1.metric("Total Entradas", f"{df_pivot['Entradas'].sum():,.0f}")
                        t2.metric("Total Saídas", f"{df_pivot['Saídas'].sum():,.0f}")

                        st.bar_chart(df_pivot[['Entradas', 'Saídas']], color=["#2ecc71", "#e74c3c"])
                    except Exception as e:
                        st.error(f"Erro ao processar volume: {e}")

        # 2. DIVERGÊNCIAS DE INVENTÁRIO
        with c_div:
            with st.container(border=True):
                st.markdown("#### :material/balance: Top Itens com Divergências")
                st.caption("Ajustes manuais frequentes (sem Req/SC) indicam erro de processo.")
                
                df_div = obter_analitico_divergencias(days=90)
                
                if df_div.empty:
                    st.success(":material/check_circle: Nenhuma divergência significativa.")
                else:
                    df_div_display = df_div.copy()
                    df_div_display.columns = ["PN", "Item", "Nº Ajustes", "Vol. Ajustado"]
                    
                    st.dataframe(
                        df_div_display,
                        width="stretch",
                        hide_index=True,
                        height=320,
                        column_config={
                            "Nº Ajustes": st.column_config.ProgressColumn("Freq.", format="%d", min_value=0, max_value=int(df_div_display["Nº Ajustes"].max()), color="#F7941E"),
                            "Vol. Ajustado": st.column_config.NumberColumn(format="%.2f")
                        }
                    )

        st.markdown("---")

        # --- LINHA 2: RUPTURA DE ESTOQUE (Destaque Total) ---
        with st.container(border=True):
            st.markdown("#### :material/emergency: Ruptura de Estoque (Impacto na Operação)")
            st.caption("Itens que zeraram o estoque durante uma requisição nos últimos 90 dias. Indica falha de abastecimento.")
            
            df_rup = obter_analitico_rupturas(days=90)
            
            if df_rup.empty:
                st.success(":material/check_circle: **Operação Fluida:** Nenhuma ruptura registrada no período. O estoque atendeu todas as requisições.")
            else:
                # Formatar data para exibição
                df_rup['ultima_ocorrencia'] = df_rup['ultima_ocorrencia'].apply(fmt)
                
                # Renomear colunas
                df_rup_display = df_rup.rename(columns={
                    "part_number": "PN",
                    "nome_item": "Item Crítico",
                    "qtd_rupturas": "Qtd. Rupturas",
                    "ultima_ocorrencia": "Última Falha"
                })

                # Estilização: Vermelho para alta frequência
                def highlight_ruptura(val):
                    if isinstance(val, (int, float)) and val >= 3:
                        return 'color: #e74c3c; font-weight: bold;'
                    return ''

                st.dataframe(
                    df_rup_display.style.map(highlight_ruptura, subset=['Qtd. Rupturas']),
                    width="stretch",
                    hide_index=True,
                    height=250,
                    column_config={
                        "Qtd. Rupturas": st.column_config.ProgressColumn(
                            "Freq. Ruptura", 
                            format="%d", 
                            min_value=0, 
                            max_value=int(df_rup_display["Qtd. Rupturas"].max()),
                            color="#e74c3c" # Vermelho para alertar
                        ),
                        "Última Falha": st.column_config.TextColumn(width="small")
                    }
                )
                
                st.warning(":material/lightbulb: **Ação Recomendada:** Revise o **Estoque Mínimo** e o **Lead Time** destes itens imediatamente para evitar paradas de linha.")

# ══════════════════════════════════════════════════════════════════════════════
# 📇 FICHA 360 DO MATERIAL (v2.6.0) — vida útil do item em uma tela (read-only,
#     exceto a imagem do produto). Montagem de dados já existentes (v2.2–v2.5).
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Ficha 360":
    st.title(":material/badge: Ficha 360 do Material")
    st.caption("Toda a vida útil do material em uma tela — cadastro, estoque, consumo, "
               "compras, utilização, indicadores e recomendação. Somente leitura "
               "(a única escrita é a imagem do produto).")

    _, item_f, _ = sel_material("Selecione o material (PN ou nome)", "ficha_item")
    if not item_f:
        st.info("Selecione um material para ver a ficha completa.")
    else:
        ficha = montar_ficha_360(item_f["id"])
        if not ficha:
            st.error("Material não encontrado.")
        else:
            # v4.9.0 — a sub-aba Guarda-Chuva saiu da Ficha 360 e virou um controle
            # próprio e manual em "Controle de SC → ☂️ Guarda-Chuva" (tabela guarda_chuva).
            # A Ficha 360 volta a ser só a Visão Geral (read-only).
            _render_ficha_visao_geral(ficha)
