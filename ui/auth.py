"""v6.1.0 — Sessão, tela de login e gate de acesso.

Metade de UI do login local: `services/usuarios.py` decide **quem pode entrar**, este
módulo decide **o que a tela faz com isso**. A sessão é o `st.session_state` do Streamlit
(por aba do navegador, some ao recarregar o servidor) — não há cookie nem token.

O gate é **opt-in**: com a flag `exigir_login` desligada (o padrão) `gate()` é no-op e o
app roda exatamente como na v6.0.0. É o que permite entregar a fundação sem surpreender
o almoxarifado no meio do expediente.
"""

from __future__ import annotations

import streamlit as st

from services.usuarios import ROTULO_PAPEL, autenticar, exigir_login

SESSAO_USUARIO = "mro_usuario"

MSG_CREDENCIAL_INVALIDA = "Usuário ou PIN inválidos."


def usuario_logado() -> dict | None:
    """Usuário da sessão atual, ou None. É a única leitura de sessão do sistema —
    sidebar, router e páginas passam por aqui em vez de tocar `st.session_state`."""
    return st.session_state.get(SESSAO_USUARIO)


def papel_atual() -> str | None:
    """Papel de quem está logado, ou None (deslogado = menu completo, flag off)."""
    usuario = usuario_logado()
    return usuario["papel"] if usuario else None


def fazer_login(identificador: str, pin: str) -> tuple[bool, str]:
    """Autentica e grava a sessão. Retorna (ok, msg).

    O `st.rerun()` fica com o CHAMADOR (`render_login`), não aqui: `st.rerun()` levanta
    exceção de controle e nenhum `return` depois dele seria alcançado — a função ficaria
    com um contrato mentiroso e impossível de testar fora do runtime do Streamlit.
    """
    usuario = autenticar(identificador, pin)
    if usuario is None:
        return False, MSG_CREDENCIAL_INVALIDA
    st.session_state[SESSAO_USUARIO] = usuario
    return True, f"Bem-vindo(a), {usuario['nome']}."


def fazer_logout() -> None:
    """Encerra a sessão e recarrega a página."""
    st.session_state.pop(SESSAO_USUARIO, None)
    st.rerun()


def render_login() -> None:
    """Tela de acesso: nome (ou `primeiro.sobrenome`) + PIN de 4 dígitos."""
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        with st.container(border=True):
            st.subheader(":material/lock: Acesso ao MRO")
            st.caption(
                "Entre com o seu **nome** (ou `primeiro.sobrenome`) e o **PIN de 4 dígitos**. "
                "Não tem PIN? Fale com o almoxarife — ele define o seu em "
                "**Configurações › Usuários**."
            )

            with st.form("form_login", clear_on_submit=False):
                identificador = st.text_input(
                    "Nome ou login",
                    key="login_ident",
                    placeholder="ex.: Jasiva Lopes  ou  jasiva.lopes",
                )
                pin = st.text_input(
                    "PIN",
                    key="login_pin",
                    type="password",
                    max_chars=4,
                    help="PIN de 4 dígitos.",
                )
                entrar = st.form_submit_button(":material/login: Entrar", type="primary", width="stretch")

            if entrar:
                ok, msg = fazer_login(identificador, pin)
                if ok:
                    st.rerun()
                # Mensagem genérica de propósito: não revela se o nome existe, se o
                # usuário está inativo ou se só o PIN está errado.
                st.error(msg)

            # Só faz sentido quando `render_login` é aberta COM sessão viva (troca de
            # usuário): sem isso o botão prometeria uma volta que não existe.
            if usuario_logado() and st.button("Voltar", key="login_voltar"):
                st.rerun()


def gate() -> None:
    """Trava o app quando `exigir_login` está ligada e não há sessão.

    No-op no padrão (flag desligada). Chamado no `app.py` ANTES da sidebar, para que o
    menu não apareça a quem ainda não entrou.
    """
    if exigir_login() and not usuario_logado():
        render_login()
        st.stop()


def rotulo_papel(papel: str | None) -> str:
    """Rótulo em pt-BR do papel (fallback: o próprio valor cru)."""
    return ROTULO_PAPEL.get(papel or "", papel or "")
