"""Página Gestor (v6.2.0) — "Aprovações do Setor".

O gestor registra que autorizou o pedido do seu setor. A aprovação é **não bloqueante**
(decisão do Luis em 02/08/2026): não cria status, não trava a fila e não substitui o
autorizador que o almoxarife informa na entrega — é a autorização antecipada, para o
setor deixar registrado que o pedido tem aval antes de o material sair.

Filtro = igualdade simples entre `requisicoes.setor` e o setor escolhido (case/trim
insensível). `requisicoes.setor` e `usuarios.departamento` são vocabulários diferentes e
só se cruzam em parte; o fluxo novo casa porque a tela do Requisitante já pré-preenche o
setor com o departamento, e o seletor editável alcança o que ficou de fora.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from services.db_functions import aprovar_requisicao, listar_requisicoes_por_setor
from ui.auth import usuario_logado
from ui.cache import invalidar_leituras
from ui.paginas.movimentacao import _opcoes_setor

LIMITE_APROVADAS = 20

COLUNAS_FILA = {
    "numero_requisicao": "Nº",
    "data_hora": "Aberta em",
    "emitente": "Emitente",
    "setor": "Setor",
    "status": "Status",
}


def _tabela(reqs, extras=None):
    """Tabela das requisições no shape de `listar_requisicoes_por_setor`."""
    colunas = dict(COLUNAS_FILA) | (extras or {})
    df = pd.DataFrame(reqs).reindex(columns=list(colunas))
    st.dataframe(df, width="stretch", hide_index=True, column_config=colunas)


def _escolher_setor(usuario):
    """Setor da tela. Devolve (setor, aprovador) — `aprovador` é quem assina a aprovação.

    Logado: setor = departamento do cadastro, mas o select continua EDITÁVEL (pedido
    explícito do Luis: ele precisa testar aprovações de mais de um setor). Sem login:
    simulação — escolhe setor e digita em nome de quem está aprovando, no mesmo espírito
    da Visão do Solicitante."""
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
    for req in fila:
        with st.container(border=True):
            c_info, c_btn = st.columns([4, 1])
            c_info.markdown(
                f"**{req['numero_requisicao']}** · {req['emitente']} · "
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


def render():
    st.title(":material/fact_check: Aprovações do Setor")
    st.caption(
        "Registre a autorização do setor para as requisições dos seus solicitantes. "
        "A aprovação **não bloqueia** a separação: o almoxarifado continua entregando com a "
        "autorização registrada na entrega."
    )
    usuario = usuario_logado()
    setor, aprovador = _escolher_setor(usuario)
    if not setor:
        st.info("Escolha um setor para ver as requisições.")
        return

    _fila_de_aprovacao(setor, aprovador)
    st.markdown("---")
    _ja_aprovadas(setor)
