"""Página Gestor (v6.2.0) — "Aprovações do Setor".

O gestor registra que autorizou o pedido do seu setor. A aprovação é **não bloqueante**
(decisão do Luis em 02/08/2026): não cria status, não trava a fila e não substitui o
autorizador que o almoxarife informa na entrega — é a autorização antecipada, para o
setor deixar registrado que o pedido tem aval antes de o material sair.

Filtro = igualdade simples entre `requisicoes.setor` e o setor escolhido (case/trim
insensível). `requisicoes.setor` e `usuarios.departamento` são vocabulários diferentes e
só se cruzam em parte; o fluxo novo casa porque a tela do Requisitante já pré-preenche o
setor com o departamento, e o seletor editável alcança o que ficou de fora.

v6.3.0 — a tela passou a ter **dois públicos**. O almoxarife (admin) cai num ramo próprio,
com a fila CONSOLIDADA de todos os setores: ele não tem departamento cadastrado, então no
ramo do gestor a tela não lhe mostrava nada, e mesmo com um cadastrado ele veria um setor
por vez. Gestor e simulação seguem exatamente como na v6.2.0.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from services.db_functions import (
    aprovar_requisicao,
    listar_itens_requisicao,
    listar_requisicoes_para_aprovacao,
    listar_requisicoes_por_setor,
    rejeitar_requisicao,
)
from ui.auth import usuario_logado
from ui.cache import invalidar_leituras
from ui.componentes.requisicao import aviso_rejeicao, tabela_itens_requisicao
from ui.paginas.movimentacao import _opcoes_setor

LIMITE_APROVADAS = 20
LIMITE_FILA = 100

COLUNAS_FILA = {
    "numero_requisicao": "Nº",
    "data_hora": "Aberta em",
    "emitente": "Emitente",
    "setor": "Setor",
    "status": "Status",
}

# v6.3.0 — na fila consolidada o Setor deixa de ser redundante (era sempre o mesmo) e
# vira a informação principal: é por ele que o almoxarife sabe para quem está aprovando.
COLUNAS_FILA_CONSOLIDADA = {
    "numero_requisicao": "Nº",
    "setor": "Setor",
    "data_hora": "Aberta em",
    "emitente": "Emitente",
    "status": "Status",
}


def _norm(setor) -> str:
    """Setor comparável. `requisicoes.setor` tem a mesma área grafada de várias formas
    ('TI' × 'ti', 'ADAPTADOR' × 'ADAPTADOR '), e agrupar sem normalizar parte o setor em
    duas linhas do filtro — a armadilha que `setor_dominante_por_item` já paga desde a
    v5.9.0."""
    return str(setor or "").strip().upper()


def _tabela(reqs, extras=None, base=None):
    """Tabela das requisições no shape de `listar_requisicoes_por_setor`."""
    colunas = dict(base or COLUNAS_FILA) | (extras or {})
    df = pd.DataFrame(reqs).reindex(columns=list(colunas))
    st.dataframe(df, width="stretch", hide_index=True, column_config=colunas)


def _cartoes(fila, aprovador, mostrar_setor=False):
    """Um cartão por requisição: o que está sendo pedido, Aprovar e Devolver.

    v6.4.0 — o cartão ganhou os ITENS (num expander) e o botão de devolução. Até aqui o
    gestor decidia por número, emitente e contagem de itens: aprovava sem saber o que
    estava aprovando, e não tinha como dizer "isso está errado". Os dois lados do mesmo
    problema."""
    for req in fila:
        with st.container(border=True):
            c_info, c_btn = st.columns([4, 1])
            setor = f"{req['setor']} · " if mostrar_setor else ""
            c_info.markdown(
                f"**{req['numero_requisicao']}** · {setor}{req['emitente']} · "
                f"{req['data_hora']} · {int(req['total_itens'] or 0)} item(ns) · "
                f"status **{req['status']}**"
            )
            if c_btn.button(
                ":material/how_to_reg: Aprovar",
                key=f"gestor_aprovar_{req['id']}",
                type="primary",
                width="stretch",
            ):
                ok, msg = aprovar_requisicao(req["id"], aprovador)
                if ok:
                    invalidar_leituras()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

            # Rejeição já cumprida e reenviada aparece como histórico — o gestor precisa
            # lembrar o que pediu para ajustar ao rever o mesmo pedido.
            aviso_rejeicao(req)

            with st.expander(":material/receipt_long: Ver requisição completa"):
                tabela_itens_requisicao(listar_itens_requisicao(req["id"]))
                if req.get("centro_custo"):
                    st.caption(f"Centro de custo: **{req['centro_custo']}**")
                if req.get("observacoes"):
                    st.caption(f"Observações: {req['observacoes']}")

            c_mot, c_rej = st.columns([4, 1])
            motivo = c_mot.text_input(
                "Motivo da devolução",
                key=f"gestor_motivo_{req['id']}",
                placeholder="Ex.: quantidade acima do necessário; peça 2 em vez de 10.",
                label_visibility="collapsed",
            )
            if c_rej.button(
                ":material/assignment_return: Devolver",
                key=f"gestor_rejeitar_{req['id']}",
                width="stretch",
                help="Devolve ao requisitante para ajuste. Ele corrige e reenvia — o pedido "
                "volta para esta fila.",
            ):
                ok, msg = rejeitar_requisicao(req["id"], aprovador, motivo)
                if ok:
                    invalidar_leituras()
                    st.warning(msg)
                    st.rerun()
                else:
                    st.error(msg)


def _escolher_setor(usuario):
    """Setor da tela. Devolve (setor, aprovador) — `aprovador` é quem assina a aprovação.

    Logado: setor = departamento do cadastro, mas o select continua EDITÁVEL (pedido
    explícito do Luis: ele precisa testar aprovações de mais de um setor). Sem login:
    simulação — escolhe setor e digita em nome de quem está aprovando, no mesmo espírito
    da Visão do Solicitante. O almoxarife não passa por aqui (v6.3.0)."""
    if not usuario:
        st.warning(
            ":material/science: **Sem login — simulação.** Escolha o setor e diga quem está "
            "aprovando. Com o login ligado, o setor vem do **departamento** do seu cadastro "
            "e o nome é o seu."
        )
        c1, c2 = st.columns(2)
        setor = c1.selectbox("Setor", [""] + _opcoes_setor(), index=0, key="gestor_setor_sim")
        aprovador = c2.text_input("Aprovando como", key="gestor_nome_sim")
        return setor, aprovador.strip()

    departamento = (usuario.get("departamento") or "").strip()
    if not departamento:
        st.warning(
            "Seu cadastro não tem departamento — fale com o almoxarife para cadastrá-lo em "
            "**Configurações › Usuários**. Sem ele não dá para saber quais requisições são do "
            "seu setor."
        )
        return "", usuario["nome"]

    opcoes = [""] + _opcoes_setor(departamento)
    idx = next((i for i, v in enumerate(opcoes) if v.upper() == departamento.upper()), 0)
    setor = st.selectbox("Setor", opcoes, index=idx, key="gestor_setor")
    st.caption(
        "Mostra as requisições cujo **Setor** é igual ao selecionado — a tela do Requisitante "
        "já preenche o setor com o departamento de quem pede. Trocar o setor aqui serve para "
        "acompanhar outra área."
    )
    return setor, usuario["nome"]


def _fila_de_aprovacao(setor, aprovador):
    st.markdown("### :material/pending_actions: Aguardando aprovação")
    fila = listar_requisicoes_por_setor(setor, so_abertas=True, apenas_aprovadas=False)
    if not fila:
        st.info("Nenhuma requisição do setor aguardando aprovação.")
        return

    _tabela(fila, {"total_itens": "Itens"})
    _cartoes(fila, aprovador)


def _ja_aprovadas(setor):
    st.markdown("### :material/task_alt: Já aprovadas")
    aprovadas = listar_requisicoes_por_setor(
        setor, so_abertas=False, apenas_aprovadas=True, limite=LIMITE_APROVADAS
    )
    if not aprovadas:
        st.caption("Nenhuma requisição aprovada neste setor ainda.")
        return
    st.caption(
        f"Últimas {LIMITE_APROVADAS} aprovações do setor. Somente leitura — aprovar não muda "
        "o status nem impede a entrega; o almoxarifado continua separando normalmente."
    )
    _tabela(aprovadas, {"aprovado_por": "Aprovado por", "aprovado_em": "Aprovado em"})


def _devolvidas(setor=None, base=None):
    """v6.4.0 — Terceira metade da tela: o que o gestor devolveu e ainda não voltou.

    Sem esta seção a devolução seria invisível para quem a fez: o pedido some da fila de
    aprovação e não aparece em "já aprovadas". `setor=None` = visão consolidada do
    almoxarife, exatamente como nas outras duas listas."""
    st.markdown("### :material/assignment_return: Devolvidas para ajuste")
    reqs = (
        listar_requisicoes_para_aprovacao(so_abertas=True, apenas_rejeitadas=True, limite=LIMITE_APROVADAS)
        if setor is None
        else listar_requisicoes_por_setor(
            setor, so_abertas=True, apenas_rejeitadas=True, limite=LIMITE_APROVADAS
        )
    )
    if not reqs:
        st.caption("Nenhuma requisição devolvida aguardando ajuste.")
        return
    st.caption(
        "Estão com o requisitante. Assim que ele corrigir e **reenviar**, voltam para a fila "
        "de aprovação acima — devolver não cancela nem bloqueia a separação."
    )
    _tabela(
        reqs,
        {
            "rejeitado_por": "Devolvida por",
            "rejeitado_em": "Em",
            "motivo_rejeicao": "Motivo",
        },
        base=base,
    )


# ── Ramo do almoxarife (admin) — v6.3.0 ───────────────────────────────────────


def _filtro_setor(fila):
    """Seletor opcional de setor, montado a partir da PRÓPRIA fila. Devolve o setor
    normalizado escolhido, ou None para "todos".

    As opções saem do que existe na fila (com a contagem), e não de
    `listar_setores_conhecidos()`: a união Configurações + histórico passa de 60 valores,
    dos quais um punhado tem pedido aguardando — filtrar por um setor vazio seria o único
    resultado provável. Requisição sem setor preenchido (legado) continua aparecendo em
    "todos"; ela só não vira uma opção do filtro, porque "" é justamente o valor que
    `listar_requisicoes_por_setor` recusa.

    **Sem `key=` de propósito:** aprovar um pedido pode tirar o último do setor e mudar as
    opções. Com `key`, a identidade do widget congela (`key_as_main_identity`) e um valor
    guardado que sumiu das opções levanta `StreamlitAPIException`; sem ela, a mudança de
    opções recria o widget e o filtro volta a "Todos os setores"."""
    contagem = {}
    for req in fila:
        setor = _norm(req["setor"])
        if setor:
            contagem[setor] = contagem.get(setor, 0) + 1
    opcoes = [None] + sorted(contagem)
    return st.selectbox(
        "Setor",
        opcoes,
        format_func=lambda s: "Todos os setores" if s is None else f"{s} ({contagem[s]})",
        help="Opcional. O padrão é ver tudo o que há para aprovar, de todos os setores.",
    )


def _render_consolidado(usuario):
    """Fila de tudo o que há para aprovar, de todos os setores (papel `almoxarife`)."""
    st.markdown("### :material/pending_actions: Aguardando aprovação")
    fila = listar_requisicoes_para_aprovacao(so_abertas=True, apenas_aprovadas=False, limite=LIMITE_FILA)
    setor = _filtro_setor(fila)
    if setor:
        fila = [r for r in fila if _norm(r["setor"]) == setor]

    if not fila:
        st.info(
            "Nenhuma requisição aguardando aprovação."
            if setor is None
            else f"Nenhuma requisição de **{setor}** aguardando aprovação."
        )
    else:
        n_setores = len({_norm(r["setor"]) for r in fila})
        st.caption(
            f"**{len(fila)}** requisição(ões) aguardando aprovação, em **{n_setores}** setor(es). "
            "Aprovar registra a autorização e não muda o status nem trava a entrega."
        )
        _tabela(fila, {"total_itens": "Itens"}, base=COLUNAS_FILA_CONSOLIDADA)
        _cartoes(fila, usuario["nome"], mostrar_setor=True)
        if len(fila) == LIMITE_FILA:
            st.caption(f":material/info: Mostrando as {LIMITE_FILA} mais antigas — pode haver mais na fila.")

    st.markdown("---")
    st.markdown("### :material/task_alt: Já aprovadas")
    aprovadas = (
        listar_requisicoes_para_aprovacao(so_abertas=False, apenas_aprovadas=True, limite=LIMITE_APROVADAS)
        if setor is None
        else listar_requisicoes_por_setor(
            setor, so_abertas=False, apenas_aprovadas=True, limite=LIMITE_APROVADAS
        )
    )
    if not aprovadas:
        st.caption("Nenhuma requisição aprovada ainda.")
    else:
        escopo = "de todos os setores" if setor is None else f"de **{setor}**"
        st.caption(
            f"Últimas {LIMITE_APROVADAS} aprovações {escopo}. Somente leitura — aprovar não muda "
            "o status nem impede a entrega; o almoxarifado continua separando normalmente."
        )
        _tabela(
            aprovadas,
            {"aprovado_por": "Aprovado por", "aprovado_em": "Aprovado em"},
            base=COLUNAS_FILA_CONSOLIDADA,
        )

    # v6.4.0 — sem `return` acima: a seção de devolvidas tem de aparecer mesmo quando não
    # há nenhuma aprovação ainda, que é justamente o estado de quem acabou de devolver o
    # primeiro pedido.
    st.markdown("---")
    _devolvidas(setor, base=COLUNAS_FILA_CONSOLIDADA)


def render():
    st.title(":material/fact_check: Aprovações do Setor")
    st.caption(
        "Registre a autorização do setor para as requisições dos seus solicitantes. "
        "A aprovação **não bloqueia** a separação: o almoxarifado continua entregando com a "
        "autorização registrada na entrega."
    )
    usuario = usuario_logado()

    # v6.3.0 — o admin vê tudo de uma vez. A checagem é pelo PAPEL da sessão: sem login
    # (`exigir_login` desligada) a tela segue no ramo de simulação, que pede o setor —
    # decisão do Luis em 03/08/2026, para o modo legado não mudar de comportamento.
    if usuario and usuario.get("papel") == "almoxarife":
        _render_consolidado(usuario)
        return

    setor, aprovador = _escolher_setor(usuario)
    if not setor:
        st.info("Escolha um setor para ver as requisições.")
        return

    _fila_de_aprovacao(setor, aprovador)
    st.markdown("---")
    _ja_aprovadas(setor)
    st.markdown("---")
    _devolvidas(setor)
