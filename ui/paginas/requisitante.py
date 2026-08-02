"""Página Requisitante (v6.2.0) — "Minhas Requisições".

A primeira tela do self-service: quem pede material abre o próprio pedido e acompanha o
que já recebeu, sem passar pelo balcão. Nasce no fluxo **Digital** (abre o pedido, o
almoxarife dá baixa na entrega) porque o Padrão baixa estoque na criação — dar isso a
quem não é do almoxarifado seria deixar o solicitante escrever no estoque.

Nada aqui é lógica nova: os blocos de montagem do pedido (`_req_bloco_identificacao`,
`_req_bloco_materiais`, `_req_tela_confirmacao`) e o painel de acompanhamento
(`_req_painel_pedidos`) vêm de `ui/paginas/movimentacao.py`, que continua sendo o dono
deles. Importar helpers privados de outra página é a exceção que a regra "nunca duplicar
lógica" pede: a alternativa era uma segunda cópia da tela de requisição para manter em
sincronia com a do almoxarife.
"""

from __future__ import annotations

import streamlit as st

from services.db_functions import criar_requisicao, listar_requisicoes, sincronizar_setores_config
from ui.auth import usuario_logado
from ui.cache import invalidar_leituras
from ui.paginas.movimentacao import (
    _req_bloco_identificacao,
    _req_bloco_materiais,
    _req_painel_pedidos,
    _req_tela_confirmacao,
)
from ui.tema import paleta_atual

AJUDA_QTD = (
    "Quanto você está pedindo. A quantidade efetivamente ENTREGUE é definida pelo "
    "almoxarifado na hora da separação (pode ser parcial). Dá para pedir mais do que o "
    "saldo atual — o pedido fica na fila."
)


def _aba_nova(usuario, PAL):
    """Abrir pedido no fluxo Digital, com identificação já preenchida pela sessão."""
    if "itens_req" not in st.session_state:
        st.session_state.itens_req = []
    if "req_confirmada" not in st.session_state:
        st.session_state.req_confirmada = None

    # Mesma guarda if/else da Movimentação (sem st.stop(), que mataria a aba irmã).
    if st.session_state.req_confirmada:
        _req_tela_confirmacao(st.session_state.req_confirmada)
        return

    # Padroniza os setores (idempotente, uma vez por sessão) — o select sai da união
    # Configurações + histórico, mais o departamento de quem está logado.
    if not st.session_state.get("_setores_sync"):
        sincronizar_setores_config()
        st.session_state["_setores_sync"] = True

    req_setor, req_emit, req_cc = _req_bloco_identificacao(
        setor_padrao=usuario.get("departamento") or "",
        emitente_fixo=usuario["nome"],
    )
    if not (usuario.get("departamento") or "").strip():
        st.caption(
            ":material/info: Seu cadastro não tem departamento — escolha o setor abaixo. "
            "Peça ao almoxarife para cadastrar o seu, e ele vem preenchido nas próximas."
        )
    st.markdown("---")
    _req_bloco_materiais(PAL, AJUDA_QTD)
    st.markdown("---")

    st.markdown("##### 3. Observações e Envio")
    obs_req = st.text_area(
        "Observações Gerais da Requisição",
        height=70,
        placeholder="Opcional. Ex.: urgência, referência de OS, local de entrega...",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button(":material/send: CRIAR REQUISIÇÃO", type="primary", width="stretch"):
        erros = []
        if not req_setor:
            erros.append("Escolha o Setor Solicitante.")
        if not st.session_state.itens_req:
            erros.append("A lista de materiais está vazia.")
        if erros:
            for e in erros:
                st.error(e)
            return
        with st.spinner("Criando requisição..."):
            # Autorizador e SESMT ficam para a ENTREGA, como no fluxo Digital: quem libera
            # a saída do material é o almoxarife, não quem pede.
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


def _aba_minhas(usuario):
    """Acompanhamento: TODOS os status (é o que quem pediu quer ver), filtrado pelo nome
    da sessão — sem seletor, ao contrário da simulação da Movimentação."""
    reqs = listar_requisicoes(limit=500, emitente=usuario["nome"])
    if not reqs:
        st.info("Você ainda não tem requisições. Abra a primeira na aba **Nova Requisição**.")
        return
    _req_painel_pedidos(reqs, "req_minhas", permitir_cancelar=True)


def render():
    st.title(":material/inbox: Minhas Requisições")
    usuario = usuario_logado()
    if not usuario:
        st.info(
            "Faça login com seu **nome + PIN** para abrir e acompanhar as suas requisições. "
            "Não tem PIN? Fale com o almoxarife."
        )
        st.caption(
            "Sem login, a simulação continua em **Movimentação › Requisição › Fila / "
            "Separação › Solicitante**."
        )
        return

    st.caption(
        "Você abre o pedido, ele entra na **Fila de Separação** do almoxarifado e a baixa "
        "acontece na entrega — total ou parcial. Acompanhe aqui o que já foi entregue."
    )
    PAL = paleta_atual()
    aba_nova, aba_minhas = st.tabs(
        [":material/edit_note: Nova Requisição", ":material/receipt_long: Meus Pedidos"]
    )
    with aba_nova:
        _aba_nova(usuario, PAL)
    with aba_minhas:
        _aba_minhas(usuario)
