"""Página Portaria (v6.2.0) — "Consulta de Saída".

A guarita confere o que está saindo: digita o número da requisição e vê o pedido, quem
autorizou e o que foi de fato entregue. **Leitura pura** — nenhum botão desta tela escreve
no banco, o que é o que torna seguro abri-la sem login (`ui/auth.em_modo_publico`): o
terminal da portaria é compartilhado e um PIN coletivo colado no monitor seria pior que
não ter login nenhum.

Roda nos dois modos: logada como `portaria` (menu de uma rota) e no modo público.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from services.db_functions import buscar_requisicao_por_numero

MARCA_STATUS = {
    "Aberta": ":material/pending: **Aberta** — nada entregue ainda.",
    "Parcial": ":material/pending_actions: **Parcial** — parte dos itens já saiu.",
    "Entregue": ":material/check_circle: **Entregue** — pedido atendido por completo.",
    "Cancelada": ":material/cancel: **Cancelada** — não deve sair material.",
}


def _destinatarios(req):
    """`requisicoes.destinatarios` é JSON `[{"matricula":…, "nome":…}]` desde a v5.7.0.
    Histórico antigo pode ter texto livre — daí o fallback, em vez de estourar na guarita."""
    bruto = req.get("destinatarios")
    if not bruto or not req.get("entrega_individual"):
        return []
    try:
        dados = json.loads(bruto)
    except (TypeError, ValueError):
        return [str(bruto)]
    return [f"{d.get('matricula') or '—'} · {d.get('nome') or '—'}" for d in dados if isinstance(d, dict)]


def _cartao(req):
    st.markdown(f"## {req['numero_requisicao']}")
    st.markdown(MARCA_STATUS.get(req["status"], f"**{req['status']}**"))

    c1, c2, c3 = st.columns(3)
    c1.metric(":material/person: Emitente", req["emitente"] or "—")
    c2.metric(":material/domain: Setor", req["setor"] or "—")
    c3.metric(":material/schedule: Aberta em", req["data_hora"] or "—")

    st.markdown(f"**Centro de custo:** {req['centro_custo'] or '—'}")
    if req.get("autorizador_nome"):
        st.markdown(
            f":material/verified_user: **Autorizado na entrega por** {req['autorizador_nome']}"
            + (f" ({req['autorizador_tipo']})" if req.get("autorizador_tipo") else "")
        )
    if req.get("aprovado_por"):
        st.markdown(f":material/how_to_reg: **Aprovado por** {req['aprovado_por']} em {req['aprovado_em']}")
    if req.get("sesmt"):
        st.markdown(f":material/engineering: **SESMT:** {req.get('sesmt_responsavel') or '—'}")
    if req.get("observacoes"):
        st.info(f"**Observações:** {req['observacoes']}")

    destinatarios = _destinatarios(req)
    if destinatarios:
        st.markdown("**Entrega individual — destinatários:**")
        for d in destinatarios:
            st.markdown(f"- :material/person: {d}")

    st.markdown("#### :material/inventory_2: Itens")
    itens = req.get("itens") or []
    if not itens:
        st.caption("Requisição sem itens registrados.")
        return
    df = pd.DataFrame(itens).reindex(
        columns=["part_number", "nome_item", "unidade", "quantidade_solicitada", "quantidade_atendida"]
    )
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "part_number": "PN",
            "nome_item": "Material",
            "unidade": "Un.",
            "quantidade_solicitada": st.column_config.NumberColumn("Solicitado", format="%.0f"),
            "quantidade_atendida": st.column_config.NumberColumn("Entregue", format="%.0f"),
        },
    )
    pendentes = [
        i for i in itens if float(i["quantidade_atendida"] or 0) < float(i["quantidade_solicitada"] or 0)
    ]
    if pendentes:
        st.warning(
            f":material/pending: {len(pendentes)} item(ns) ainda não saíram por completo — "
            "confira a coluna **Entregue** antes de liberar."
        )


def render():
    st.title(":material/badge: Consulta de Saída — Portaria")
    st.caption(
        "Informe o número da requisição para conferir o pedido e a baixa. Consulta pública — "
        "não requer login e não altera nada no sistema."
    )

    with st.form("form_portaria"):
        numero = st.text_input("Número da requisição", placeholder="ex.: REQ-20260802-001")
        consultar = st.form_submit_button(":material/search: Consultar", type="primary")

    if not consultar:
        return
    if not numero.strip():
        st.warning("Digite o número da requisição.")
        return

    req = buscar_requisicao_por_numero(numero)
    if req is None:
        st.info(
            f"Requisição **{numero.strip()}** não encontrada. Confira o número — ele tem o "
            "formato `REQ-AAAAMMDD-000`."
        )
        return
    _cartao(req)
