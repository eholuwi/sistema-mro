"""Página Movimentação (v6.0.0) — a página que mais escreve estoque.

Migrada do bloco inline do `app.py` (migração FIEL). Agrega 4 abas: Receber Material
(Por Material / Por SC), Requisição (Nova / Fila / Histórico), Ajuste Rápido e
Histórico Completo. Os 3 fluxos maiores vivem em helpers module-level
(`_receber_por_sc`, `_render_receber_material`, `_render_requisicao`).

v6.0.0 — a aba "Dashboard movimentações" saiu daqui; ver a docstring de `render()`.

F4b: toda ESCRITA (recebimento, entrada avulsa, criar/entregar/ajustar requisição,
ajuste de saldo) passa a chamar `invalidar_leituras()` antes do rerun — era a única
página migrada que ainda não limpava o cache das leituras (sidebar/Saldo/Dashboard
exibiam estoque velho após uma baixa). Regra de negócio preservada 1:1.
"""

from __future__ import annotations

import time
from datetime import date, datetime

import pandas as pd
import streamlit as st

from services.db_functions import (
    listar_inventario,
    registrar_movimentacao,
    listar_movimentacoes,
    categoria_movimentacao,
    registrar_recebimento_sc,
    listar_scs,
    listar_itens_sc,
    buscar_scs_por_item,
    listar_valores,
    listar_setores_conhecidos,
    sincronizar_setores_config,
    criar_requisicao,
    criar_requisicao_com_baixa,
    listar_requisicoes,
    listar_itens_requisicao,
    mapa_pn_por_requisicao,
    entregar_requisicao,
    adicionar_itens_requisicao,
    atualizar_item_requisicao,
    remover_item_requisicao,
    reenviar_requisicao,
    cancelar_requisicao,
    listar_requisicoes_abertas,
    listar_emitentes_requisicao,
    exportar_movimentacoes_df,
)
from services.ficha import imagem_existente
from ui.cache import invalidar_leituras
from ui.componentes.requisicao import aviso_rejeicao
from ui.tema import paleta_atual
from ui.formatos import fmt
from ui.componentes.exportar import botoes_export
from ui.componentes.graficos import _barv
from ui.componentes.selecao import sel_material
from ui.componentes.status import divergencia_recebimento
from ui.componentes.tabela import chave_editor

# v5.7.0 (CP4) — a exportação não corta mais nada; a partir daqui ela apenas AVISA que o
# recorte ficou grande. O número é o antigo teto silencioso de 5.000 linhas, mantido como
# referência do que a operação já considerava "muita coisa" — só que agora visível.
LIMITE_AVISO_EXPORTACAO = 5000


def _milhar(n):
    """12345 → '12.345' (separador pt-BR, sem depender de locale do servidor)."""
    return f"{n:,}".replace(",", ".")


def chave_editor_recebimento(sc_id, geracao):
    """Chave do `data_editor` do recebimento por SC/PO, versionada por SC e por geração.

    v5.6.0 — CORREÇÃO DO RECEBIMENTO PARCIAL (ver `ui/componentes/tabela.chave_editor`
    para a causa no Streamlit 1.60.0). Com a chave fixa que existia aqui, receber 4 de 10
    reaplicava o `{"Qtd a receber": 4}` antigo sobre o pendente já atualizado (6): o
    parcial nunca andava e um segundo clique recebia 4 de novo. O recebimento TOTAL
    escapava porque o item sai da lista, o nº de linhas muda e a assinatura muda junto.

    - `sc_id` isola cada SC (sem ele, edições vazam entre SCs de mesmo formato);
    - `geracao` é incrementada após cada recebimento, forçando um editor limpo.
    """
    return chave_editor("rec_sc_editor", sc_id, geracao)


def _limpar_editores_recebimento(chave_viva):
    """Descarta o estado dos editores de recebimento que não são mais o atual — evita
    que o `session_state` cresça a cada SC visitada / geração numa sessão longa."""
    for k in [
        k
        for k in st.session_state
        if isinstance(k, str) and k.startswith("rec_sc_editor__") and k != chave_viva
    ]:
        st.session_state.pop(k, None)


def _receber_por_sc():
    """v3.4.0 — Recebimento começando pela SC/PO: escolhe uma SC aberta e recebe todos
    os itens pendentes de uma vez (itera `registrar_recebimento_sc` por item, mesma função
    do fluxo por material — sem duplicar conversão/ledger). Complementa o 'Por Material'.
    v6.5.0 — Centro de Custo saiu da tela: todo recebimento é MRO/Almoxarifado, gravado
    com `centro_custo=""` (já pertence a `CC_GENERICOS`; `categoria_movimentacao` devolve
    "Entrada"). Requisição continua com CC escolhido pelo solicitante."""
    scs = listar_scs(apenas_abertas=True)
    if not scs:
        st.info("Nenhuma SC aberta para receber. Importe o Relatório de SCs ou crie uma SC.")
        return
    with st.container(border=True):
        opc = {
            (
                f"SC {s['numero_sc']} · PO {s.get('numero_po') or '—'} · "
                f"{s.get('fornecedor') or 'sem fornecedor'} · "
                f"{int(s.get('total_itens') or 0)} itens · pendente {float(s.get('total_pendente') or 0):g}"
            ): s
            for s in scs
        }
        sel = st.selectbox(
            "Selecione a SC / PO",
            list(opc.keys()),
            index=None,
            placeholder="Selecione a SC / PO…",
            key="rec_sc_sel",
        )
        if sel not in opc:
            st.info("Selecione uma SC para ver e receber os itens pendentes.")
            return
        sc = opc[sel]
        itens = [it for it in listar_itens_sc(sc["id"]) if (it.get("pendente") or 0) > 0]
        if not itens:
            st.success(":material/check_circle: Todos os itens desta SC já foram recebidos.")
            return

        st.markdown(
            f"**SC {sc['numero_sc']}** · PO `{sc.get('numero_po') or '—'}` · "
            f"Fornecedor: {sc.get('fornecedor') or '—'} · Status: {sc.get('status') or '—'}"
        )
        # v5.7.0 — o "Pendente" da grade sai do recebimento conferido pelo MRO. Onde o Protheus
        # declara mais do que entrou na doca, o almoxarife vê a divergência antes de lançar.
        _pns_div = [it["part_number"] for it in itens if divergencia_recebimento(it)]
        if _pns_div:
            st.caption(
                ":orange[:material/rule: **Divergência de recebimento** com o Protheus em: "
                + ", ".join(f"`{pn}`" for pn in _pns_div)
                + ". O pendente abaixo segue o que o MRO conferiu.]"
            )

        h1, h2 = st.columns(2)
        forn = h1.text_input("Fornecedor", value=sc.get("fornecedor") or "", key="rec_sc_forn")
        dt_r = h2.date_input("Data Recebimento", value=date.today(), key="rec_sc_dt")

        base = pd.DataFrame(
            [
                {
                    "Receber": True,
                    "PN": it["part_number"],
                    "Item": (it.get("nome_item") or "")[:40],
                    "Un": it.get("unidade") or "UN",
                    "Pendente": float(it.get("pendente") or 0),
                    "Qtd a receber": float(it.get("pendente") or 0),
                    "NF / Documento": "",
                    "_item_sc_id": int(it["id"]),
                }
                for it in itens
            ]
        )
        _chave_editor = chave_editor_recebimento(sc["id"], st.session_state.get("rec_sc_gen", 0))
        _limpar_editores_recebimento(_chave_editor)
        edit = st.data_editor(
            base,
            hide_index=True,
            width="stretch",
            key=_chave_editor,
            column_config={
                "Receber": st.column_config.CheckboxColumn(
                    "Receber", help="Desmarque itens que ainda não chegaram."
                ),
                "PN": st.column_config.TextColumn(disabled=True),
                "Item": st.column_config.TextColumn(disabled=True),
                "Un": st.column_config.TextColumn(disabled=True),
                "Pendente": st.column_config.NumberColumn(format="%.0f", disabled=True),
                "Qtd a receber": st.column_config.NumberColumn(
                    format="%.2f", min_value=0.0, help="Default = pendente. Recebimento parcial: reduza aqui."
                ),
                "NF / Documento": st.column_config.TextColumn(
                    help="NF por item (opcional; usa a do lote se vazio)."
                ),
                "_item_sc_id": None,
            },
        )
        nf_lote = st.text_input(
            "Nota Fiscal / Documento do lote",
            key="rec_sc_nf",
            help="Aplicada aos itens sem NF própria na tabela acima.",
        )

        if st.button(
            ":material/download: Confirmar recebimento da SC",
            type="primary",
            width="stretch",
            key="rec_sc_btn",
        ):
            recebidos, erros = 0, []
            for _, r in edit.iterrows():
                if not r["Receber"]:
                    continue
                qtd = float(r["Qtd a receber"] or 0)
                if qtd <= 0:
                    continue
                nf = str(r["NF / Documento"]).strip() or nf_lote.strip()
                ok, msg = registrar_recebimento_sc(
                    sc_id=sc["id"],
                    item_sc_id=int(r["_item_sc_id"]),
                    qtd_recebida=qtd,
                    centro_custo="",
                    solicitante="Almoxarifado",
                    emitente="Almoxarifado",
                    fornecedor=forn,
                    data_recebimento=str(dt_r),
                    obs_nf=nf,
                )
                if ok:
                    recebidos += 1
                else:
                    erros.append(f"{r['PN']}: {msg}")
            if recebidos:
                invalidar_leituras()  # F4b: baixa de estoque no ledger — limpa cache das leituras
                # v5.6.0 — nova geração: o editor renasce limpo e relê o pendente já
                # atualizado, em vez de reaplicar a quantidade digitada no ciclo anterior.
                st.session_state["rec_sc_gen"] = st.session_state.get("rec_sc_gen", 0) + 1
                st.success(
                    f":material/check_circle: {recebidos} item(ns) recebido(s) na SC {sc['numero_sc']}."
                )
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
        "Como quer receber?",
        ["📦 Por Material", "📋 Por SC / PO"],
        horizontal=True,
        key="rec_modo",
        help="Por Material começa pelo item; Por SC / PO escolhe a SC e recebe todos os itens pendentes de uma vez.",
    )
    if _modo_rec == "📋 Por SC / PO":
        _receber_por_sc()
        return
    with st.container(border=True):
        st.markdown("### :material/inventory_2: Registrar Recebimento de Material")
        st.caption("Vincule a uma SC aberta ou registre como entrada avulsa.")

        _, item_rec, _ = sel_material("Material *", "sel_rec")

        if item_rec:
            # v2.9.0: conversão de unidades. A qtd recebida é informada na UNIDADE
            # DE COMPRA; o estoque/ledger vive na UNIDADE DE ESTOQUE. fator=1 (itens
            # de UM única) → sem diferença, tudo como antes.
            _fator_rec = float(item_rec.get("fator_conversao") or 1.0) or 1.0
            _ue_rec = item_rec.get("unidade") or "UN"
            _uc_rec = item_rec.get("unidade_compra") or _ue_rec
            _tem_conv = abs(_fator_rec - 1.0) > 1e-9 and _uc_rec.upper() != _ue_rec.upper()

            st.markdown(
                f"`{item_rec['part_number']}` — **{item_rec['nome_item']}** | Saldo Atual: `{item_rec['estoque_atual']}` {_ue_rec}"
            )
            if item_rec.get("unidade_divergente"):
                st.warning(
                    ":material/warning: Este item é comprado em unidade diferente da de estoque e ainda "
                    "**não tem fator de conversão** definido — o recebimento somará a "
                    "quantidade crua. Cadastre o fator em **Cadastro de Itens → Conversão "
                    "de unidades** antes de receber."
                )

            scs_item = buscar_scs_por_item(item_rec["id"], apenas_abertas=True)
            sc_sel = None

            if scs_item:
                vincular = st.checkbox(":material/link: Vincular a uma S.C. Aberta", value=True)
                if vincular:
                    opc_sc = {
                        f"SC {s['numero_sc']} | PO: {s.get('po_item') or '—'} | Saldo: {s['pendente']} {_uc_rec}": s
                        for s in scs_item
                    }
                    sel_sc_str = st.selectbox(
                        "Selecionar SC", list(opc_sc.keys()), label_visibility="collapsed"
                    )
                    sc_sel = opc_sc[sel_sc_str]

                    with st.container(border=True):
                        st.markdown(
                            f":material/check_circle: **SC {sc_sel['numero_sc']}** | PO: `{sc_sel['numero_po'] or '—'}` | Fornecedor: {sc_sel.get('fornecedor_item') or sc_sel['fornecedor'] or '—'}"
                        )
                        st.markdown(
                            f"Solicitado: `{sc_sel['quantidade_solicitada']}` | Negociado: `{sc_sel.get('quantidade_negociada') or sc_sel['quantidade_solicitada']}` | Recebido: `{sc_sel['quantidade_recebida']}` | **Saldo Residual: `{sc_sel['pendente']}` {_uc_rec}**"
                        )
                        # v5.7.0 — o pendente sai do que o MRO conferiu; se o Protheus declara
                        # mais, o almoxarife precisa ver a diferença antes de lançar a entrada.
                        _div_rec = divergencia_recebimento(sc_sel)
                        if _div_rec:
                            st.caption(f":orange[{_div_rec}]")
            else:
                st.info("ℹ️ Nenhuma SC aberta para este material. A entrada será registrada como avulsa.")

            # v2.9.0: qtd fora do form → conversão em tempo real (form não faz rerun).
            limite_rec = float(sc_sel["pendente"]) if sc_sel else None
            qtd_default = min(1.0, limite_rec) if limite_rec else 1.0
            lbl_qtd = f"Qtd Recebida (em {_uc_rec}) *" if _tem_conv else "Qtd Recebida *"
            if limite_rec:
                qtd_r = st.number_input(
                    lbl_qtd, min_value=0.01, max_value=limite_rec, step=1.0, value=qtd_default, key="rec_qtd"
                )
            else:
                qtd_r = st.number_input(lbl_qtd, min_value=0.01, step=1.0, key="rec_qtd")
            if _tem_conv:
                _incr = qtd_r / _fator_rec
                st.caption(
                    f":material/straighten: **{qtd_r:g} {_uc_rec}** ÷ fator {_fator_rec:g} = **+{_incr:g} {_ue_rec}** no estoque."
                )

            with st.form("form_rec"):
                st.markdown("##### :material/download: Dados do Recebimento")
                c2, c3 = st.columns(2)
                # v2.7.1: Fornecedor não é obrigatório (pré-preenche da SC quando há).
                forn = c2.text_input(
                    "Fornecedor",
                    value=(sc_sel.get("fornecedor_item") or sc_sel.get("fornecedor") or "") if sc_sel else "",
                )
                dt_r = c3.date_input("Data Recebimento", value=date.today())

                obs_nf = st.text_input("Nota Fiscal / Documento *" if sc_sel else "Obs / Nota Fiscal")

                rec_b = st.form_submit_button(
                    ":material/download: Confirmar Recebimento", width="stretch", type="primary"
                )

            if rec_b:
                if sc_sel and not obs_nf.strip():
                    st.warning(":material/warning: Informe o número da Nota Fiscal para rastreabilidade.")
                elif sc_sel:
                    # qtd_r na UM de compra; registrar_recebimento_sc converte ao estoque.
                    ok, msg = registrar_recebimento_sc(
                        sc_id=sc_sel["id"],
                        item_sc_id=sc_sel["item_sc_id"],
                        qtd_recebida=qtd_r,
                        centro_custo="",
                        solicitante="Almoxarifado",
                        emitente="Almoxarifado",
                        fornecedor=forn,
                        data_recebimento=str(dt_r),
                        obs_nf=obs_nf,
                    )
                    if ok:
                        invalidar_leituras()
                        st.success(f":material/check_circle: **Recebimento registrado!** {msg}")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(f":material/cancel: {msg}")
                else:
                    # v2.9.0: entrada avulsa converte aqui (registrar_movimentacao é
                    # primitivo em unidade de ESTOQUE — a conversão é responsabilidade
                    # da borda, como no recebimento de SC).
                    _qtd_estoque = qtd_r / _fator_rec
                    _obs_conv = (
                        (f" | convertido {qtd_r:g} {_uc_rec} ÷ {_fator_rec:g} = {_qtd_estoque:g} {_ue_rec}")
                        if _tem_conv
                        else ""
                    )
                    ok, msg = registrar_movimentacao(
                        item_id=item_rec["id"],
                        tipo="entrada",
                        quantidade=_qtd_estoque,
                        centro_custo="",
                        solicitante="Almoxarifado",
                        emitente="Almoxarifado",
                        observacao=f"Fornecedor: {forn} | {obs_nf}{_obs_conv}",
                    )
                    if ok:
                        invalidar_leituras()
                        st.success(f":material/check_circle: **Entrada avulsa registrada!** {msg}")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(f":material/cancel: {msg}")


def _fila_visao_almoxarife(autorizadores_lista):
    """Visão do Almoxarife (default) — a fila de trabalho: separar, entregar, dar baixa.

    v5.7.0 — extraída da aba Fila para conviver com a Visão do Solicitante. O corpo é o da
    v4.7.0, acrescido do toggle "incluir entregues": sem ele a requisição Entregue não é
    selecionável e o "Adicionar item" (que agora a reabre) fica inalcançável pela tela."""
    st.caption(
        "Requisições aguardando entrega. Registre a saída (parcial ou total) — só aqui o "
        "estoque é baixado. Material só sai com autorização (gestor; +SESMT se for EPI/SSO)."
    )

    incluir_entregues = st.toggle(
        "Incluir requisições já entregues",
        key="fila_incluir_entregues",
        help="Para o caso 'escreve no mesmo papel': o solicitante volta com mais um item num "
        "pedido já fechado. Ao incluir o item, a requisição reabre como Parcial e volta à fila.",
    )
    abertas = listar_requisicoes_abertas(incluir_entregues=incluir_entregues)
    if not abertas:
        st.success(":material/inventory: Nenhuma requisição pendente na fila. Tudo em dia!")
        return

    pendentes = [a for a in abertas if a["status"] != "Entregue"]
    mp1, mp2 = st.columns(2)
    mp1.metric(":material/pending_actions: Requisições na fila", len(pendentes))
    mp2.metric(
        ":material/hourglass_top: Mais antiga",
        str(min(a["data_hora"] for a in pendentes))[:10] if pendentes else "—",
    )

    def _fmt_fila(a):
        _falt = int(a.get("itens_pendentes") or 0)
        return (
            f"{a['numero_requisicao']} · {a['setor']} · {a['emitente']} · {a['status']} · {_falt} pendente(s)"
        )

    opc_fila = {_fmt_fila(a): a for a in abertas}
    sel_f = st.selectbox(
        "Escolha a requisição para separar/entregar:", [""] + list(opc_fila.keys()), key="fila_sel"
    )

    req = opc_fila.get(sel_f) if sel_f else None
    if not req:
        return
    req_id = req["id"]
    st.markdown(f"#### :material/assignment: {req['numero_requisicao']} — {req['setor']} · {req['emitente']}")
    st.caption(
        f"Aberta em {str(req['data_hora'])[:16]} · "
        f"C.Custo: {req.get('centro_custo') or '—'} · Status: **{req['status']}**"
    )
    if req.get("observacoes"):
        st.info(f":material/sticky_note_2: {req['observacoes']}")
    if req["status"] == "Entregue":
        st.info(
            ":material/task_alt: Requisição já **entregue por completo**. Para incluir mais um "
            "material no mesmo pedido, use **Adicionar item** abaixo — ela reabre como Parcial "
            "e volta à fila."
        )

    itens_f = listar_itens_requisicao(req_id)

    st.markdown("##### 1. Itens — quanto entregar agora")
    entregas = []
    for it in itens_f:
        falta = float(it["quantidade_solicitada"]) - float(it["quantidade_atendida"])
        disp = float(it.get("estoque_atual") or 0)
        ci1, ci2, ci3 = st.columns([3, 2, 2])
        ci1.markdown(f"**{it['part_number']}** — {it['nome_item']}")
        ci1.caption(
            f"Solicitado {float(it['quantidade_solicitada']):g} · "
            f"atendido {float(it['quantidade_atendida']):g} · "
            f"falta {max(falta, 0):g} {it['unidade']}"
        )
        ci2.markdown(f":material/inventory_2: Disp.: **{disp:g}** {it['unidade']}")
        if falta <= 0:
            ci3.success("Completo")
            continue
        _max = float(min(falta, disp))
        q = ci3.number_input(
            "Entregar",
            min_value=0.0,
            max_value=float(disp) if disp > 0 else 0.0,
            value=_max if _max > 0 else 0.0,
            step=1.0,
            key=f"ent_{req_id}_{it['id']}",
            help="Sem saldo em estoque para este item." if disp <= 0 else None,
        )
        if q > 0:
            entregas.append({"item_req_id": it["id"], "quantidade": float(q)})

    st.markdown("##### 2. Autorização da saída")
    ca1, ca2 = st.columns(2)
    f_aut_tipo = ca1.selectbox("Tipo de Autorizador *", autorizadores_lista, key=f"aut_t_{req_id}")
    f_aut_nome = ca2.text_input("Nome do Autorizador (gestor) *", key=f"aut_n_{req_id}")
    f_sesmt = st.checkbox("Material SESMT? (EPI/SSO — exige responsável do SESMT)", key=f"sesmt_{req_id}")
    f_sesmt_resp = ""
    if f_sesmt:
        f_sesmt_resp = st.text_input("Responsável SESMT *", key=f"sesmt_r_{req_id}")

    # v5.9.0 — data REAL da saída. Material que saiu ontem e só foi lançado hoje era
    # contabilizado no dia errado, distorcendo consumo médio, ABC, giro e cobertura.
    f_data_saida = None
    if st.checkbox("Material saindo agora", value=True, key=f"agora_{req_id}"):
        st.caption(":material/schedule: A saída será registrada com a data e hora deste momento.")
    else:
        cd1, cd2 = st.columns(2)
        _d = cd1.date_input(
            "Data real da saída",
            value=date.today(),
            max_value=date.today(),
            key=f"dt_saida_{req_id}",
            help="Quando o material saiu de fato do almoxarifado. Não aceita data futura.",
        )
        _h = cd2.time_input("Hora real da saída", value=datetime.now().time(), key=f"hr_saida_{req_id}")
        f_data_saida = datetime.combine(_d, _h)
        st.caption(
            f":material/history: Saída lançada para **{f_data_saida:%d/%m/%Y %H:%M}** — "
            "é esta data que entra no consumo do item."
        )

    if st.button(
        ":material/local_shipping: REGISTRAR ENTREGA",
        type="primary",
        width="stretch",
        key=f"btn_ent_{req_id}",
    ):
        if not entregas:
            st.warning("Informe ao menos um item com quantidade a entregar.")
        else:
            ok, res = entregar_requisicao(
                req_id,
                entregas,
                f_aut_tipo,
                f_aut_nome,
                f_sesmt,
                f_sesmt_resp,
                data_saida=f_data_saida,
            )
            if ok:
                invalidar_leituras()  # F4b: entrega baixa estoque
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
                    req_id, [{"item_id": item_add_f["id"], "quantidade_solicitada": qadd}]
                )
                if ok:
                    invalidar_leituras()
                    st.success(res)
                    st.rerun()
                else:
                    st.error(res)

    if req["status"] == "Aberta":
        if st.button(":material/cancel: Cancelar requisição (nada foi entregue)", key=f"btn_cancel_{req_id}"):
            ok, res = cancelar_requisicao(req_id)
            if ok:
                invalidar_leituras()
                st.warning(res)
                st.rerun()
            else:
                st.error(res)


def _req_ajustar_e_reenviar(req, chave):
    """v6.4.0 — Painel de correção do pedido devolvido pelo gestor.

    Fecha o ciclo que `rejeitar_requisicao` abre: o requisitante corrige a quantidade ou
    tira o item que o gestor apontou e reenvia, e o pedido volta para a fila de aprovação.
    Só aparece para quem está logado como dono do pedido (`permitir_cancelar`, o mesmo
    critério que já libera o cancelamento): na simulação sem login qualquer pessoa editaria
    o pedido de qualquer um.

    Item já entregue não é editável — a guarda é do serviço (`atualizar_item_requisicao` /
    `remover_item_requisicao`); aqui ele só aparece esmaecido, para o requisitante entender
    por que não dá para mexer."""
    st.markdown("###### :material/edit_note: Ajustar o pedido")
    itens = listar_itens_requisicao(req["id"])
    for it in itens:
        atendida = float(it["quantidade_atendida"] or 0)
        ca, cb, cc = st.columns([3, 1, 1])
        ca.markdown(f"**{it['part_number']}** — {it['nome_item']} ({it['unidade']})")
        if atendida > 0:
            cb.caption(f"Já entregue: {atendida:g}")
            cc.caption("Não editável")
            continue
        nova = cb.number_input(
            "Qtd",
            min_value=1.0,
            step=1.0,
            value=float(it["quantidade_solicitada"]),
            key=f"{chave}_qtd_{it['id']}",
            label_visibility="collapsed",
        )
        if nova != float(it["quantidade_solicitada"]):
            if cc.button("Salvar", key=f"{chave}_salvar_{it['id']}", width="stretch"):
                ok, msg = atualizar_item_requisicao(it["id"], nova)
                (st.success if ok else st.error)(msg)
                if ok:
                    invalidar_leituras()
                    st.rerun()
        elif cc.button("Remover", key=f"{chave}_rm_{it['id']}", width="stretch"):
            ok, msg = remover_item_requisicao(it["id"])
            (st.warning if ok else st.error)(msg)
            if ok:
                invalidar_leituras()
                st.rerun()

    if st.button(
        ":material/send: Reenviar para aprovação",
        key=f"{chave}_reenviar_{req['id']}",
        type="primary",
        width="stretch",
        disabled=not itens,
        help="Devolve o pedido corrigido para a fila do gestor.",
    ):
        ok, msg = reenviar_requisicao(req["id"])
        if ok:
            invalidar_leituras()
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)


def _req_painel_pedidos(reqs, chave, permitir_cancelar=False):
    """Acompanhamento dos pedidos de UMA pessoa: métricas, tabela e detalhe item a item.

    v6.2.0 — extraído da Visão do Solicitante para a tela "Minhas Requisições" do
    Requisitante logado. As duas mostram a mesma coisa; o que muda é como o nome chega
    (seletor de simulação × sessão) e o direito de cancelar. `chave` prefixa as keys dos
    widgets, para as duas telas nunca disputarem o mesmo `session_state`.

    `permitir_cancelar` liga o botão de cancelar no pedido aberto: quem está logado cancela
    o próprio pedido, mas na simulação sem login qualquer pessoa cancelaria o de qualquer
    um. Espera `reqs` não vazio (a mensagem de lista vazia é de quem chama, que sabe se o
    caso é "ninguém escolhido ainda" ou "você não tem pedidos")."""
    na_fila = [r for r in reqs if r["status"] in ("Aberta", "Parcial")]
    ms1, ms2, ms3 = st.columns(3)
    ms1.metric(":material/receipt_long: Meus pedidos", len(reqs))
    ms2.metric(":material/pending_actions: Aguardando separação", len(na_fila))
    ms3.metric(":material/task_alt: Entregues", len([r for r in reqs if r["status"] == "Entregue"]))

    df_s = pd.DataFrame(reqs).reindex(
        columns=[
            "numero_requisicao",
            "data_hora",
            "setor",
            "centro_custo",
            "status",
            "total_itens",
            "total_atendido",
        ]
    )
    st.dataframe(
        df_s,
        width="stretch",
        hide_index=True,
        column_config={
            "numero_requisicao": "Nº",
            "data_hora": "Aberta em",
            "setor": "Setor",
            "centro_custo": "Centro de Custo",
            "status": "Status",
            "total_itens": st.column_config.NumberColumn("Itens", format="%d"),
            "total_atendido": st.column_config.NumberColumn("Qtd entregue", format="%.0f"),
        },
    )

    opc_s = {f"{r['numero_requisicao']} · {r['status']}": r for r in reqs}
    sel_s = st.selectbox("Ver os itens de um pedido:", [""] + list(opc_s.keys()), key=f"{chave}_req")
    if not sel_s:
        return
    r_sel = opc_s[sel_s]
    # v6.4.0 — pedido devolvido pelo gestor abre com o motivo em destaque. É a primeira
    # coisa que o requisitante tem de ler: sem o motivo, "sua requisição voltou" não diz
    # o que corrigir, e ele reenviaria exatamente o mesmo pedido.
    devolvido = aviso_rejeicao(r_sel, para_requisitante=True) and not r_sel.get("reenviado_em")
    for it in listar_itens_requisicao(r_sel["id"]):
        falta = float(it["quantidade_solicitada"]) - float(it["quantidade_atendida"])
        marca = ":material/check_circle:" if falta <= 0 else ":material/pending:"
        st.markdown(
            f"{marca} **{it['part_number']}** — {it['nome_item']} · "
            f"pedido {float(it['quantidade_solicitada']):g} · "
            f"recebido {float(it['quantidade_atendida']):g} {it['unidade']}"
        )
    if r_sel.get("aprovado_por"):
        st.caption(
            f":material/how_to_reg: Aprovado por **{r_sel['aprovado_por']}** em {r_sel['aprovado_em']}"
        )
    if permitir_cancelar and devolvido:
        _req_ajustar_e_reenviar(r_sel, chave)
    if permitir_cancelar and r_sel["status"] == "Aberta":
        if st.button(
            ":material/cancel: Cancelar requisição (nada foi entregue)",
            key=f"{chave}_cancelar_{r_sel['id']}",
        ):
            ok, msg = cancelar_requisicao(r_sel["id"])
            if ok:
                invalidar_leituras()
                st.warning(msg)
                st.rerun()
            else:
                st.error(msg)


def _fila_visao_solicitante():
    """Visão do Solicitante (v5.7.0, decisão nº5 de 27/07/2026) — SIMULAÇÃO, sem login.

    O MRO não autentica ninguém, e esta tela não inventa autenticação: o "Estou vendo como"
    é um seletor sobre os emitentes que já abriram requisição, e qualquer pessoa pode
    escolher qualquer nome. Serve para o Luis demonstrar como o self-service se pareceria.
    Mostra TODOS os status — inclusive Entregue e Cancelada, que é justamente o que quem
    pediu o material quer acompanhar (a fila do almoxarife, ao contrário, só mostra o que
    falta separar)."""
    st.caption(
        "Acompanhe os pedidos de um solicitante e abra um novo em nome dele. "
        "Aqui aparecem todos os status, inclusive os já entregues."
    )
    st.warning(
        ":material/science: **Simulação — o sistema não tem login.** Escolher um nome só "
        "filtra a visualização; não é controle de acesso e não restringe nada."
    )

    emitentes = listar_emitentes_requisicao()
    if not emitentes:
        st.info("Nenhuma requisição registrada ainda — não há solicitante para simular.")
        return

    nome = st.selectbox("Estou vendo como:", [""] + emitentes, key="fila_solicitante_nome")
    if not nome:
        st.caption("Escolha um nome para ver os pedidos daquela pessoa.")
        return

    reqs = listar_requisicoes(limit=500, emitente=nome)
    if not reqs:
        st.info(f"**{nome}** ainda não tem requisições registradas.")
    else:
        _req_painel_pedidos(reqs, "fila_solicitante")

    st.markdown("---")
    if st.button(
        f":material/edit_note: Abrir nova requisição como **{nome}**",
        width="stretch",
        key="fila_solicitante_nova",
    ):
        st.session_state["_req_emit_prefill"] = nome
        st.success(f"Nome **{nome}** preenchido. Abra a aba **Nova Requisição** acima para montar o pedido.")


def _opcoes_setor(setor_padrao=""):
    """Setores do select da Requisição, com `setor_padrao` garantido na lista (v6.2.0).

    `listar_setores_conhecidos()` é a união Configurações + histórico; o departamento de
    quem está logado (`usuarios.departamento`) vem de outro vocabulário e frequentemente
    NÃO está lá — sem este empurrão, a tela do Requisitante abriria com o setor da pessoa
    ausente do select. Quando o setor já existe (em qualquer caixa), a forma cadastrada
    vence e nada é duplicado. Função pura de propósito: é a parte testável do prefill."""
    setores = listar_setores_conhecidos()
    padrao = str(setor_padrao or "").strip()
    if padrao and padrao.upper() not in {s.upper() for s in setores}:
        return [padrao] + setores
    return setores


def _req_bloco_identificacao(setor_padrao="", emitente_fixo=None):
    """Bloco 1 — Identificação da Demanda. Comum aos dois fluxos (v5.7.0).

    Sem `key` nos widgets, de propósito: a aba Nova renderiza antes da Fila e definir o
    `session_state` de um widget já instanciado nesta mesma execução levantaria
    `StreamlitAPIException` (o "Abrir nova requisição como…" da Visão do Solicitante
    escreve `_req_emit_prefill`). Como só um dos fluxos renderiza por execução, os rótulos
    iguais fazem o Streamlit reaproveitar o estado — trocar Padrão↔Digital preserva o que
    já foi digitado, que é o comportamento desejado.

    v6.2.0 — parâmetros para a tela do Requisitante, com os defaults do fluxo do balcão:
    `setor_padrao` pré-seleciona o setor (editável — o pedido pode ser de outro setor) e
    `emitente_fixo` trava o emitente no nome de quem está logado (ali o solicitante é quem
    é; digitar outro nome seria abrir pedido no nome alheio). Padrão/Digital chamam sem
    argumento e continuam idênticas."""
    st.markdown("##### 1. Identificação da Demanda")
    c1, c2, c3 = st.columns(3)
    opcoes_setor = [""] + _opcoes_setor(setor_padrao)
    padrao = str(setor_padrao or "").strip()
    # Índice case-insensitive: `_opcoes_setor` pode ter devolvido a forma CADASTRADA do
    # setor ('Manutenção') no lugar da digitada no cadastro do usuário ('MANUTENÇÃO').
    idx_setor = 0
    if padrao:
        idx_setor = next((i for i, v in enumerate(opcoes_setor) if v.upper() == padrao.upper()), 0)
    req_setor = c1.selectbox(
        "Setor Solicitante *",
        options=opcoes_setor,
        index=idx_setor,
        accept_new_options=True,
        help="Escolha um setor já usado ou digite um novo para padronizar o cadastro.",
    )
    if emitente_fixo:
        req_emit = c2.text_input(
            "Nome do Emitente *",
            value=emitente_fixo,
            disabled=True,
            help="Você está logado — o pedido sai no seu nome.",
        )
    else:
        req_emit = c2.text_input("Nome do Emitente *", value=st.session_state.get("_req_emit_prefill", ""))
    opcoes_cc = [""] + (listar_valores("centro_custo") or [])
    req_cc = c3.selectbox("Centro de Custo *", options=opcoes_cc, index=0)
    return req_setor, req_emit, req_cc


def _saldo_visivel(item, ocultar_saldo):
    """O saldo deste item pode ser mostrado a quem está montando o pedido? (v6.4.0)

    Duas condições, e as duas importam: `ocultar_saldo` diz QUEM está olhando (só a tela do
    Requisitante pede o ocultamento — almoxarife e comprador continuam vendo tudo, decisão
    do Luis), e `mostrar_saldo_requisitante` diz PARA QUAIS itens o almoxarife liberou a
    visão. Item sem a coluna preenchida (legado, antes da migração) conta como visível: o
    default da coluna é 1 e esconder saldo por omissão surpreenderia. Pura/testável."""
    if not ocultar_saldo:
        return True
    valor = (item or {}).get("mostrar_saldo_requisitante")
    return True if valor is None else bool(valor)


def _req_bloco_materiais(PAL, ajuda_qtd, ocultar_saldo=False):
    """Bloco 2 — Adicionar Materiais + lista temporária. Comum aos dois fluxos (v5.7.0).

    `ajuda_qtd` muda porque o significado de "Qtd Solicitada" muda: na Digital a entrega é
    decidida depois, na Fila; na Padrão o material sai agora. A lista vive em
    `st.session_state.itens_req` e é compartilhada pelos dois fluxos — trocar o seletor não
    faz o usuário remontar o pedido.

    v6.4.0 — `ocultar_saldo` é ligado SÓ pela tela do Requisitante: o bloco é o mesmo que a
    Movimentação usa no balcão, e lá quem monta o pedido é o almoxarife, que precisa do
    saldo para trabalhar. O item ainda pode liberar a visão individualmente (ver
    `_saldo_visivel`). A **foto do material** aparece para todo mundo — é conferência
    ("é esta peça mesmo?"), não informação restrita."""
    st.markdown("##### 2. Adicionar Materiais")
    _, item_req_add, _ = sel_material("Pesquise o material para requisitar", "sel_req_add")

    if item_req_add:
        foto = imagem_existente(item_req_add)
        if foto:
            c_foto, c_saldo = st.columns([1, 3])
            c_foto.image(foto, width="stretch")
        else:
            c_saldo = st.container()
        if _saldo_visivel(item_req_add, ocultar_saldo):
            # Card de disponibilidade rápida (cores acompanham o tema via PAL)
            c_saldo.markdown(
                f"""
            <div style="border: 1px solid {PAL["painel_borda"]}; padding: 10px; border-radius: 5px; background-color: {PAL["painel_bg"]}; margin-bottom: 10px;">
                <span style="color: {PAL["accent"]}; font-weight: bold;">DISPONÍVEL:</span> {item_req_add.get("estoque_atual", 0)} {item_req_add.get("unidade", "UN")}
            </div>
        """,
                unsafe_allow_html=True,
            )
        else:
            c_saldo.caption(
                ":material/visibility_off: Peça a quantidade que você precisa — o almoxarifado "
                "confere o saldo na separação."
            )

    with st.form("form_add_item_req", clear_on_submit=True):
        qtd_sol = st.number_input("Qtd Solicitada *", min_value=1.0, step=1.0, value=1.0, help=ajuda_qtd)
        add_item = st.form_submit_button(":material/add: ADICIONAR À LISTA", width="stretch")

    if add_item:
        if not item_req_add:
            st.warning(":material/warning: Selecione um material antes de adicionar.")
        else:
            st.session_state.itens_req.append(
                {
                    "item_id": item_req_add["id"],
                    "part_number": item_req_add["part_number"],
                    "nome_item": item_req_add["nome_item"],
                    "unidade": item_req_add.get("unidade", "UN"),
                    "estoque_disponivel": item_req_add.get("estoque_atual", 0),
                    "quantidade_solicitada": qtd_sol,
                    # v6.4.0 — a permissão de ver saldo viaja com o item na lista: ela
                    # vive no cadastro (`inventario`), e a lista temporária do
                    # session_state não guarda o item inteiro para reconsultar.
                    "mostrar_saldo_requisitante": item_req_add.get("mostrar_saldo_requisitante"),
                    "imagem_path": item_req_add.get("imagem_path"),
                }
            )
            st.rerun()

    if st.session_state.itens_req:
        st.markdown("###### :material/inventory_2: Itens na Requisição Atual:")
        for idx, it in enumerate(st.session_state.itens_req):
            with st.expander(f"{it['part_number']} — {it['nome_item']}", expanded=True):
                foto_it = imagem_existente(it)
                if foto_it:
                    c_img, c_info, c_del = st.columns([1, 4, 1])
                    c_img.image(foto_it, width="stretch")
                else:
                    c_info, c_del = st.columns([5, 1])
                saldo_txt = (
                    f" · _saldo hoje:_ {it.get('estoque_disponivel', 0):g}"
                    if _saldo_visivel(it, ocultar_saldo)
                    else ""
                )
                c_info.write(f"**Solicitado:** {it['quantidade_solicitada']:g} {it['unidade']}{saldo_txt}")

                if c_del.button("Remover", key=f"rm_req_{idx}", type="primary"):
                    st.session_state.itens_req.pop(idx)
                    st.rerun()
    else:
        st.info("Aguardando adição de materiais...")


def _req_bloco_destinatarios():
    """Entrega Individual (EPI/Uniforme) — só na Padrão (v5.7.0, decisão nº3 de 27/07/2026).

    Vários destinatários, cada um com Matrícula e Nome em campos SEPARADOS. O fluxo antigo
    pedia uma `text_area` livre no formato "MATRÍCULA — NOME (um por linha)" e adivinhava o
    separador; digitar o travessão errado silenciosamente juntava tudo no campo matrícula.
    A serialização gravada é a mesma de antes (`[{"matricula":…, "nome":…}]`), então o
    conteúdo de `requisicoes.destinatarios` continua compatível com o histórico.

    Devolve `(entrega_individual, destinatarios)`."""
    entrega_ind = st.checkbox(":material/inventory_2: Entrega Individual (EPI/Uniforme)")
    if not entrega_ind:
        return False, []

    st.caption("Quem vai receber o material. Adicione um por vez — EPI é entregue nominalmente.")
    with st.form("form_add_destinatario", clear_on_submit=True):
        d1, d2 = st.columns(2)
        matricula = d1.text_input("Matrícula")
        nome_dest = d2.text_input("Nome do destinatário")
        add_dest = st.form_submit_button(":material/person_add: ADICIONAR DESTINATÁRIO", width="stretch")

    if add_dest:
        if not matricula.strip() and not nome_dest.strip():
            st.warning(":material/warning: Informe ao menos a matrícula ou o nome.")
        else:
            st.session_state.req_destinatarios.append(
                {"matricula": matricula.strip(), "nome": nome_dest.strip()}
            )
            st.rerun()

    if st.session_state.req_destinatarios:
        for idx, d in enumerate(st.session_state.req_destinatarios):
            cd1, cd2 = st.columns([5, 1])
            cd1.write(f":material/person: **{d['matricula'] or '—'}** · {d['nome'] or '—'}")
            if cd2.button("Remover", key=f"rm_dest_{idx}"):
                st.session_state.req_destinatarios.pop(idx)
                st.rerun()
    else:
        st.info("Nenhum destinatário informado ainda.")

    return True, list(st.session_state.req_destinatarios)


def _req_nova_padrao(autorizadores_lista, PAL):
    """Requisição **Padrão** — o fluxo real do balcão (v5.7.0, decisões nº1 e nº2).

    O material sai na hora: autorização e SESMT são exigidos AQUI, e não na Fila, porque é
    aqui que o estoque é baixado. Falta de saldo não recusa o pedido — baixa o que tem e o
    resto vai para a Fila de Separação."""
    st.caption(
        "O material sai agora, no balcão: ao finalizar, o estoque é baixado na hora. "
        "O que não tiver saldo fica pendente e vai para a Fila de Separação."
    )
    req_setor, req_emit, req_cc = _req_bloco_identificacao()
    st.markdown("---")
    _req_bloco_materiais(
        PAL,
        "Quanto o setor está pedindo. A baixa acontece ao finalizar; se o saldo não cobrir, "
        "baixa o disponível e o restante vai para a Fila de Separação.",
    )
    st.markdown("---")

    st.markdown("##### 3. Regras de Entrega e SESMT")
    entrega_ind, destinatarios = _req_bloco_destinatarios()
    is_sesmt = st.checkbox(":material/engineering: Requer Aprovação SESMT")
    sesmt_resp = st.text_input("Responsável SESMT *") if is_sesmt else ""

    st.markdown("##### 4. Autorização da Saída")
    st.caption("Material só sai autorizado — na Padrão isto é exigido na criação, porque a baixa é agora.")
    ca1, ca2 = st.columns(2)
    aut_tipo = ca1.selectbox("Tipo de Autorizador *", autorizadores_lista)
    aut_nome = ca2.text_input("Nome do Autorizador (gestor) *")

    # v5.9.0 — mesma data REAL da saída da Fila (`_fila_visao_almoxarife`). Aqui pesa ainda
    # mais: é o fluxo do balcão, onde o material já saiu e só depois é lançado no sistema.
    f_data_saida = None
    if st.checkbox("Material saindo agora", value=True, key="pad_agora"):
        st.caption(":material/schedule: A saída será registrada com a data e hora deste momento.")
    else:
        cd1, cd2 = st.columns(2)
        _d = cd1.date_input(
            "Data real da saída",
            value=date.today(),
            max_value=date.today(),
            key="pad_dt_saida",
            help="Quando o material saiu de fato do almoxarifado. Não aceita data futura.",
        )
        _h = cd2.time_input("Hora real da saída", value=datetime.now().time(), key="pad_hr_saida")
        f_data_saida = datetime.combine(_d, _h)
        st.caption(
            f":material/history: Saída lançada para **{f_data_saida:%d/%m/%Y %H:%M}** — "
            "é esta data que entra no consumo do item."
        )

    st.markdown("##### 5. Observações e Envio")
    obs_req = st.text_area(
        "Observações Gerais da Requisição",
        height=70,
        placeholder="Opcional. Ex.: urgência, referência de OS, local de entrega...",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button(":material/check_circle: FINALIZAR E BAIXAR ESTOQUE", type="primary", width="stretch"):
        erros = []
        if not req_setor or not req_emit:
            erros.append("Preencha Setor e Emitente (campos com *).")
        if not aut_nome.strip():
            erros.append("Informe o autorizador (gestor): o material sai na criação.")
        if not st.session_state.itens_req:
            erros.append("A lista de materiais está vazia.")
        if entrega_ind and not destinatarios:
            erros.append("Entrega individual marcada: adicione ao menos um destinatário.")
        if is_sesmt and not sesmt_resp.strip():
            erros.append("Material SESMT: informe o responsável do SESMT.")

        if erros:
            for e in erros:
                st.error(e)
        else:
            with st.spinner("Criando requisição e baixando estoque..."):
                ok, resultado = criar_requisicao_com_baixa(
                    setor=req_setor,
                    emitente=req_emit,
                    centro_custo=req_cc,
                    autorizador_tipo=aut_tipo,
                    autorizador_nome=aut_nome,
                    entrega_individual=entrega_ind,
                    destinatarios=destinatarios,
                    sesmt=is_sesmt,
                    sesmt_responsavel=sesmt_resp,
                    itens=st.session_state.itens_req,
                    observacoes=obs_req,
                    data_saida=f_data_saida,
                )
            if ok:
                invalidar_leituras()  # a Padrão escreve estoque
                st.session_state.itens_req = []
                st.session_state.req_destinatarios = []
                st.session_state.req_confirmada = {"fluxo": "Padrão", **resultado}
                st.rerun()
            else:
                st.error(f"Erro ao criar requisição: {resultado}")


def _req_nova_digital(PAL):
    """Requisição **Digital** — protótipo de vitrine do self-service (v5.7.0, decisão nº1).

    Corpo idêntico ao da v4.7.0: abre o pedido na fila e NÃO baixa estoque (autorização e
    SESMT ficam para a entrega, na aba Fila). O que mudou é só o enquadramento — a tela
    agora diz que este fluxo é experimental."""
    st.info(
        ":material/science: **Fluxo experimental.** Serve para demonstrar o self-service: o "
        "solicitante abre o pedido, que entra na Fila, e o almoxarife dá baixa na entrega "
        "(parcial ou total). O fluxo usado na operação hoje é o **Padrão**."
    )
    req_setor, req_emit, req_cc = _req_bloco_identificacao()
    st.markdown("---")
    _req_bloco_materiais(
        PAL,
        "Quanto o setor está pedindo. A quantidade efetivamente ENTREGUE é definida na aba "
        "Fila, na hora da entrega (pode ser parcial). Pode-se solicitar mais do que o saldo "
        "atual — a fila mostra o que dá para atender.",
    )
    st.markdown("---")

    # v4.7.0: autorização e SESMT saíram da criação — passaram para a ENTREGA
    # (aba Fila / Separação), que é o momento em que o material realmente sai.
    # Aqui só se ABRE o pedido; nada é baixado do estoque ainda.
    st.markdown("##### 3. Observações e Envio")
    obs_req = st.text_area(
        "Observações Gerais da Requisição",
        height=70,
        placeholder="Opcional. Ex.: urgência, referência de OS, local de entrega...",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button(":material/send: CRIAR REQUISIÇÃO (enviar para a fila)", type="primary", width="stretch"):
        erros = []
        if not req_setor or not req_emit:
            erros.append("Preencha Setor e Emitente (campos com *).")
        if not st.session_state.itens_req:
            erros.append("A lista de materiais está vazia.")

        if erros:
            for e in erros:
                st.error(e)
        else:
            with st.spinner("Criando requisição..."):
                ok, resultado = criar_requisicao(
                    setor=req_setor,
                    emitente=req_emit,
                    centro_custo=req_cc,
                    autorizador_tipo="",
                    autorizador_nome="",
                    entrega_individual=False,
                    destinatarios=[],
                    sesmt=False,
                    sesmt_responsavel="",
                    itens=st.session_state.itens_req,
                    observacoes=obs_req,
                )
                if ok:
                    invalidar_leituras()
                    st.session_state.itens_req = []
                    st.session_state.req_confirmada = {"fluxo": "Digital", "numero": resultado}
                    st.rerun()
                else:
                    st.error(f"Erro ao criar requisição: {resultado}")


def _req_tela_confirmacao(conf):
    """Recibo da criação, para os dois fluxos (v5.7.0).

    Na Padrão o desfecho não é único: `Entregue` (tudo baixado), `Parcial` (baixou o que
    tinha) ou `Aberta` (nenhum item tinha saldo). Como decidido na entrevista, faltar saldo
    não recusa o pedido — então a tela precisa dizer exatamente o que saiu e o que ficou na
    fila, senão o almoxarife acha que entregou tudo."""
    # Até a v5.6.0 `req_confirmada` guardava só o número (string). Uma aba aberta durante a
    # atualização carrega esse valor antigo no `session_state` e cairia num TypeError já no
    # `conf['numero']` — o recibo é o primeiro lugar que a pessoa veria depois do deploy.
    if isinstance(conf, str):
        conf = {"fluxo": "Digital", "numero": conf}
    st.success(f"### :material/check_circle: Requisição {conf['numero']} criada!")
    if conf.get("fluxo") != "Padrão":
        st.info(
            "A requisição entrou na **Fila / Separação**. O estoque só é baixado quando o "
            "almoxarife registrar a entrega (com autorização)."
        )
    else:
        faltas = conf.get("faltas") or []
        status = conf.get("status")
        if not faltas:
            st.info(
                ":material/inventory_2: Estoque baixado na hora, pedido atendido por completo "
                f"(status **{status}**)."
            )
        else:
            baixou_algo = status != "Aberta"
            st.warning(
                (
                    ":material/pending_actions: Baixado o que havia em estoque. "
                    if baixou_algo
                    else ":material/pending_actions: **Nenhum item tinha saldo** — nada foi baixado. "
                )
                + f"A requisição ficou **{status}** e o pendente foi para a **Fila / Separação**:"
            )
            for f in faltas:
                st.markdown(
                    f"- **{f['part_number']}** — {f['nome_item']}: "
                    f"pedido {f['solicitada']:g}, entregue {f['atendida']:g}, "
                    f"**falta {f['falta']:g} {f['unidade']}**"
                )
    if st.button("Iniciar Nova Requisição", width="stretch"):
        st.session_state.req_confirmada = None
        st.rerun()


def _render_requisicao():
    """Requisição de material — Nova Requisição + Histórico. v3.8.0: movido da página
    própria para uma aba da Movimentação. Usa guarda if/else (NÃO st.stop()) no fluxo
    de sucesso, para não matar as abas irmãs da Movimentação."""
    PAL = paleta_atual()
    st.markdown("### :material/assignment: Requisição de Material")
    st.caption(
        "Dois fluxos: na **Padrão** o material sai no balcão e o estoque é baixado na criação "
        "(o que não tiver saldo vai para a Fila); na **Digital**, experimental, o pedido entra "
        "na Fila e o almoxarife dá baixa na entrega — sempre com autorização."
    )

    aba_nova, aba_fila, aba_hist_req = st.tabs(
        [
            ":material/edit_note: Nova Requisição",
            ":material/list_alt: Fila / Separação",
            ":material/history: Histórico",
        ]
    )

    autorizadores_lista = listar_valores("autorizador") or ["Gestor", "Líder", "Reserva"]

    with aba_nova:
        if "itens_req" not in st.session_state:
            st.session_state.itens_req = []
        if "req_destinatarios" not in st.session_state:
            st.session_state.req_destinatarios = []
        if "req_confirmada" not in st.session_state:
            st.session_state.req_confirmada = None

        # v3.8.0: guarda if/else (sem st.stop(), que mataria as abas irmãs da Movimentação).
        if st.session_state.req_confirmada:
            _req_tela_confirmacao(st.session_state.req_confirmada)
        else:
            # Padroniza os setores: registra em Configurações os que só existiam no
            # histórico (uma vez por sessão, idempotente) e monta o select a partir da
            # união (Configurações + histórico de movimentações/requisições).
            if not st.session_state.get("_setores_sync"):
                sincronizar_setores_config()
                st.session_state["_setores_sync"] = True

            # v5.7.0 (decisão nº1 de 27/07/2026) — os dois fluxos convivem, e o **Padrão**
            # é o default porque é o que a operação usa: o material sai no balcão e a baixa
            # é na criação. A Digital continua existindo como protótipo do self-service.
            fluxo = st.radio(
                "Tipo de requisição",
                ["Padrão", "Digital (experimental)"],
                index=0,
                horizontal=True,
                key="req_fluxo",
                help="Padrão: o material sai agora e o estoque é baixado na criação. "
                "Digital: o pedido entra na Fila e a baixa acontece na entrega.",
            )
            if fluxo == "Padrão":
                _req_nova_padrao(autorizadores_lista, PAL)
            else:
                _req_nova_digital(PAL)

    # --- ABA: FILA / SEPARAÇÃO (v4.7.0; duas visões na v5.7.0) ---
    with aba_fila:
        st.markdown("### :material/list_alt: Fila de Separação")
        visao = st.segmented_control(
            "Estou usando como",
            ["Almoxarife", "Solicitante"],
            default="Almoxarife",
            key="fila_visao",
            help="Almoxarife separa e entrega. Solicitante acompanha os próprios pedidos "
            "(simulação — o sistema não tem login).",
        )
        # `segmented_control` devolve None se o usuário desmarcar: cai no default operacional.
        if visao == "Solicitante":
            _fila_visao_solicitante()
        else:
            _fila_visao_almoxarife(autorizadores_lista)

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
            f_txt = fc2.text_input(
                ":material/search: Buscar (Nº, emitente, autorizador ou PN/material)", key="hist_req_busca"
            )

            fil = df_all.copy()
            if f_set != "Todos":
                fil = fil[fil["setor"] == f_set]
            if f_txt.strip():
                t = f_txt.strip().lower()
                # v4.3.0 — índice PN/nome por requisição (1 query; só quando há busca).
                mapa_pn = mapa_pn_por_requisicao()
                fil = fil[
                    fil.apply(
                        lambda r: (
                            t in str(r.get("numero_requisicao", "")).lower()
                            or t in str(r.get("emitente", "")).lower()
                            or t in str(r.get("autorizador_nome", "")).lower()
                            or t in mapa_pn.get(r.get("id"), "")
                        ),
                        axis=1,
                    )
                ]

            # v3.4.0 — mini-gráfico: requisições por setor
            if not fil.empty:
                by_set = fil["setor"].fillna("—").value_counts()
                if len(by_set):
                    st.plotly_chart(
                        _barv(list(by_set.index), [int(v) for v in by_set.values]),
                        width="stretch",
                        config={"displayModeBar": False},
                    )

            # v4.1.0 — "Detalhes da Requisição" vem ANTES da tabela e mais completo
            # (emitente, autorizador, centro de custo, setor e a lista de itens).
            st.markdown("#### :material/search: Detalhes da Requisição")
            opcoes_req = {
                f"REQ-{r['numero_requisicao']} | {r['setor']} | {str(r['data_hora'])[:10]}": r
                for r in fil.to_dict("records")
            }
            sel_req = st.selectbox(
                "Escolha uma requisição para ver os detalhes:", [""] + list(opcoes_req.keys())
            )

            if sel_req:
                r_det = opcoes_req[sel_req]
                with st.container(border=True):
                    st.markdown(
                        f"**Resumo REQ-{r_det['numero_requisicao']}** · "
                        f"{str(r_det.get('data_hora', ''))[:16]} · "
                        f"Status: **{r_det.get('status') or '—'}**"
                    )
                    c_a, c_b, c_c, c_d = st.columns(4)
                    c_a.write(f":material/person: **Emitente:** {r_det['emitente']}")
                    c_b.write(f":material/edit: **Autorizador:** {r_det.get('autorizador_nome') or '—'}")
                    c_c.write(f":material/apartment: **C.Custo:** {r_det['centro_custo']}")
                    c_d.write(f":material/domain: **Setor:** {r_det.get('setor') or '—'}")

                    itens_det = listar_itens_requisicao(r_det["id"])
                    if itens_det:
                        df_det = pd.DataFrame(itens_det)[
                            [
                                "part_number",
                                "nome_item",
                                "quantidade_solicitada",
                                "quantidade_atendida",
                                "unidade",
                            ]
                        ]
                        df_det.columns = ["PN", "Material", "Solicitado", "Atendido", "UN"]
                        st.caption(f"{len(df_det)} item(ns) nesta requisição:")
                        st.dataframe(df_det, width="stretch", hide_index=True)
                    else:
                        st.caption("Sem itens detalhados para esta requisição.")

            st.markdown("---")
            st.markdown("##### :material/table_rows: Todas as requisições")
            df_reqs = fil.reindex(
                columns=[
                    "numero_requisicao",
                    "data_hora",
                    "status",
                    "tipo_fluxo",
                    "setor",
                    "emitente",
                    "autorizador_nome",
                    "total_itens",
                ]
            ).copy()
            # v5.7.0 — requisição anterior à coluna não tem fluxo conhecido: "—" é a
            # informação correta. Inferir Padrão/Digital pela data seria chute.
            df_reqs["tipo_fluxo"] = df_reqs["tipo_fluxo"].fillna("—").replace("", "—")
            df_reqs.columns = [
                "Nº Req",
                "Data/Hora",
                "Status",
                "Fluxo",
                "Setor",
                "Emitente",
                "Autorizador",
                "Qtd Itens",
            ]
            st.dataframe(df_reqs, width="stretch", hide_index=True)


def render() -> None:
    """Movimentacao (v6.0.0): 4 abas - Receber, Requisicao, Ajuste Rapido e
    Historico Completo. Migrada do elif inline (F4b).

    v6.0.0 — a aba "Dashboard movimentações" saiu. Tendência de Consumo, Top Capital
    Parado, Maior Valor em Estoque, Top Itens com Divergências e Ruptura de Estoque
    migraram para o **Dashboard › Almoxarifado** (painel operacional único). Volume de
    Movimentações (redundante com o Histórico mensal do Almoxarifado), a Evolução do
    valor imobilizado e a Curva ABC 90d foram descontinuadas — decisão registrada no
    plano de refatoração de UX. As funções de service seguem intactas."""
    st.title(":material/sync: Movimentação")

    # v3.8.0 — Requisição e Receber Material aninhados aqui (abas), ao lado de
    # Ajuste Rápido e Histórico. Os corpos vivem em _render_receber_material /
    # _render_requisicao (module-level) — sem duplicar nem mover blocos indentados.
    tab_rec, tab_req, tab_ajuste, tab_hist = st.tabs(
        [
            ":material/inventory_2: Receber Material",
            ":material/assignment: Requisição",
            ":material/balance: Ajuste Rápido",
            ":material/history: Histórico Completo",
        ]
    )

    with tab_rec:
        _render_receber_material()
    with tab_req:
        _render_requisicao()

    # === TAB: AJUSTE RÁPIDO DE ESTOQUE (v4.3.0 — 4 tipos) ===
    with tab_ajuste:
        with st.container(border=True):
            st.subheader(":material/balance: Ajuste Manual de Saldo")
            st.caption(
                "Lançamentos avulsos (sem SC/Requisição): entradas e saídas pontuais, devoluções e perdas."
            )

            # Rótulo -> (tipo do ledger, sinal: +1 soma / -1 subtrai do estoque).
            # O CHECK de movimentacoes.tipo continua ('entrada','saida','devolucao');
            # o rótulo é guardado em `motivo` para o filtro do Histórico (v4.3.0).
            TIPOS_AJUSTE = {
                "Entrada Avulsa": ("entrada", +1),
                "Devolução": ("devolucao", +1),
                "Perda de Material": ("saida", -1),
                "Saída Avulsa": ("saida", -1),
            }

            _, item_aj, _ = sel_material("Selecione o Item para Ajuste", "sel_ajuste_estoque")

            if item_aj:
                st.info(
                    f"**Item:** `{item_aj['part_number']} — {item_aj['nome_item']}` | **Saldo Atual:** `{item_aj['estoque_atual']}`"
                )

                c1, c2 = st.columns(2)
                rotulo_aj = c1.selectbox("Tipo de Ajuste", list(TIPOS_AJUSTE.keys()))
                tp, _sinal = TIPOS_AJUSTE[rotulo_aj]
                _hint = "soma ao estoque" if _sinal > 0 else "subtrai do estoque"
                qtd_aj = c2.number_input(
                    "Quantidade", min_value=0.01, step=1.0, help=f"'{rotulo_aj}' {_hint}."
                )

                obs_aj = st.text_input(
                    "Motivo / Observação *",
                    placeholder="Ex: Avaria, sobra de contagem, devolução do setor...",
                )
                resp_aj = st.text_input("Responsável pelo Ajuste *")

                if st.button(":material/check_circle: Confirmar Ajuste", type="primary", width="stretch"):
                    if not resp_aj or not obs_aj:
                        st.error("Preencha o responsável e o motivo para auditoria.")
                    elif _sinal < 0 and qtd_aj > item_aj["estoque_atual"]:
                        st.error(
                            f"Quantidade ({qtd_aj}) superior ao estoque disponível ({item_aj['estoque_atual']})."
                        )
                    else:
                        ok, msg = registrar_movimentacao(
                            item_id=item_aj["id"],
                            tipo=tp,
                            quantidade=qtd_aj,
                            centro_custo=None,
                            solicitante=resp_aj,
                            emitente=resp_aj,
                            observacao=f"AJUSTE: {obs_aj}",
                            motivo=rotulo_aj,
                            data_hora=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        )
                        if ok:
                            invalidar_leituras()  # F4b: ajuste altera saldo
                            st.success(f":material/check_circle: '{rotulo_aj}' registrado! Novo saldo: {msg}")
                            time.sleep(1.2)
                            st.rerun()
                        else:
                            st.error(f":material/cancel: Erro: {msg}")

    # === TAB 2: HISTÓRICO COMPLETO ===
    with tab_hist:
        PAL = paleta_atual()
        with st.container(border=True):
            st.subheader(":material/history: Histórico de Movimentações")

            c1, c3 = st.columns([3, 1])
            f_item = c1.selectbox(
                "Filtrar por Item",
                ["Todos"] + [f"{i['part_number']} - {i['nome_item']}" for i in listar_inventario()],
            )
            limit = c3.number_input("Limite", min_value=50, max_value=1000, value=200, step=50)

            item_id_f = None
            if f_item != "Todos":
                pn_busca = f_item.split(" - ")[0]
                for i in listar_inventario():
                    if i["part_number"] == pn_busca:
                        item_id_f = i["id"]
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
                df_mov["data_hora"] = df_mov["data_hora"].apply(fmt)

                cols_exib = [
                    "data_hora",
                    "part_number",
                    "nome_item",
                    "_categoria",
                    "tipo",
                    "quantidade",
                    "saldo_apos",
                    "emitente",
                    "observacao",
                ]
                df_exib = df_mov[cols_exib].copy()
                df_exib.columns = [
                    "Data/Hora",
                    "PN",
                    "Nome",
                    "Categoria",
                    "Tipo",
                    "Qtd",
                    "Saldo Pós",
                    "Responsável",
                    "Obs",
                ]

                # Estilização por tipo
                # v6.0.0 — cores semânticas do tema (services/tema.py), não hex solto.
                _CORES_TIPO = {
                    "entrada": PAL["positivo"],
                    "saida": PAL["negativo"],
                    "devolucao": PAL["info"],
                }

                def colorir_tipo(val):
                    cor = _CORES_TIPO.get(val)
                    return f"color: {cor}; font-weight: bold;" if cor else ""

                st.dataframe(
                    df_exib.style.map(colorir_tipo, subset=["Tipo"]),  # Mantém a cor original do tipo banco
                    width="stretch",
                    hide_index=True,
                    height=600,
                    column_config={
                        "Qtd": st.column_config.NumberColumn(format="%.2f"),
                        "Saldo Pós": st.column_config.NumberColumn(format="%.2f"),
                    },
                )
            else:
                st.info("Nenhuma movimentação encontrada para os filtros selecionados.")

            # --- RELATÓRIO DE MOVIMENTAÇÕES (v5.7.0 / CP4) ---
            # O "Limite" acima é da TELA. A exportação não tem mais teto: o antigo
            # limit=5.000 cortava as movimentações mais ANTIGAS em silêncio. Quem recorta
            # agora é o período abaixo — escolha explícita, e o volume é sempre avisado.
            st.markdown("---")
            st.markdown("##### :material/download: Relatório de Movimentações")
            st.caption(
                "Exportação larga, para o rateio mensal por Centro de Custo/Setor e para auditoria: "
                "cada informação em sua coluna (requisição, fluxo, NF, SC/PO, setor, solicitante) "
                "em vez de empacotada no texto da Observação. Sem período, sai o histórico inteiro."
            )

            cper1, cper2 = st.columns(2)
            d_ini_exp = cper1.date_input("Período — de", value=None, format="DD/MM/YYYY", key="exp_mov_ini")
            d_fim_exp = cper2.date_input("Período — até", value=None, format="DD/MM/YYYY", key="exp_mov_fim")

            if d_ini_exp and d_fim_exp and d_ini_exp > d_fim_exp:
                st.error(":material/cancel: A data inicial é posterior à final — o período está invertido.")
            else:
                # Passamos os filtros atuais para a função
                _cats_all = bool(f_cat) and len(f_cat) == len(cats_presentes)
                df_exp_mov = exportar_movimentacoes_df(
                    item_id=item_id_f,
                    categorias_selecionadas=None if _cats_all else (f_cat or None),
                    data_inicio=d_ini_exp,
                    data_fim=d_fim_exp,
                )

                if df_exp_mov.empty:
                    st.info(
                        ":material/info: Nenhuma movimentação no recorte selecionado — "
                        "amplie o período ou os filtros acima."
                    )
                else:
                    _n = len(df_exp_mov)
                    st.caption(f"**{_milhar(_n)} linhas** no recorte · {len(df_exp_mov.columns)} colunas.")
                    if _n > LIMITE_AVISO_EXPORTACAO:
                        st.warning(
                            f":material/warning: São {_milhar(_n)} linhas. O arquivo fica pesado para abrir "
                            "no Excel — se o objetivo é o rateio do mês, recorte pelo período acima. "
                            "Nada será cortado: a planilha sai inteira do jeito que está."
                        )

                    _sufixo = (
                        f"_{d_ini_exp:%d-%m-%Y}_a_{d_fim_exp:%d-%m-%Y}" if (d_ini_exp and d_fim_exp) else None
                    )
                    botoes_export(
                        df_exp_mov,
                        "movimentacoes",
                        key="btn_exp_mov",
                        sheet_name="Movimentacoes",
                        csv=False,
                        label_excel="⬇️ Baixar planilha Excel do Relatório de Movimentações",
                        sufixo=_sufixo,
                    )
