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

# v6.2.0 — modo público da Portaria. A consulta de saída roda num terminal COMPARTILHADO
# na guarita: exigir login ali significaria um PIN coletivo colado no monitor, que é pior
# que não ter login. Quem entra por aqui não tem usuário nem papel — a sidebar dá uma rota
# só ("Portaria"), que é leitura pura.
SESSAO_PUBLICA = "mro_portaria_publica"

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
    st.session_state.pop(SESSAO_PUBLICA, None)
    st.rerun()


def em_modo_publico() -> bool:
    """A aba está na consulta pública da Portaria (v6.2.0)?

    Lido pelo `gate()` e pela sidebar. **Não é papel**: `papel_atual()` continua None aqui,
    exatamente como para quem abre o app com a flag desligada — quem distingue os dois
    casos é esta função, e é por isso que a sidebar a consulta ANTES de montar o menu.
    """
    return st.session_state.get(SESSAO_PUBLICA) is True


def entrar_modo_publico() -> None:
    """Abre a consulta pública (botão da tela de login) e recarrega."""
    st.session_state[SESSAO_PUBLICA] = True
    st.rerun()


def sair_modo_publico() -> None:
    """Fecha a consulta pública — a próxima execução cai de volta no `gate()`."""
    st.session_state.pop(SESSAO_PUBLICA, None)
    st.rerun()


def render_login() -> None:
    """Tela de acesso: nome (ou `primeiro.sobrenome`) + PIN de 4 dígitos."""
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        with st.container(border=True):
            st.subheader(":material/lock: Acesso ao MRO")
            st.caption(
                "Entre com o seu **nome completo** (como está no cadastro) e o **PIN de 4 "
                "dígitos**. O atalho `primeiro.sobrenome` também serve — menos quando duas "
                "pessoas cadastradas compartilham o mesmo atalho; aí vale o nome completo. "
                "Não tem PIN? Fale com o almoxarife — ele define o seu em "
                "**Configurações › Usuários**."
            )

            with st.form("form_login", clear_on_submit=False):
                identificador = st.text_input(
                    "Nome completo ou login",
                    key="login_ident",
                    placeholder="ex.: Ana Clara Pascoal de Carvalho  ou  ana.carvalho",
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

            # v6.2.0 — saída pública da guarita, FORA do `st.form` (o form já tem o seu
            # único submit). Escondido para quem tem sessão viva: trocar de usuário e cair
            # no modo público seria um downgrade acidental de acesso.
            if not usuario_logado():
                st.markdown("---")
                st.caption(
                    "Consulta pública de requisições. Não é necessário login — funciona num "
                    "terminal compartilhado."
                )
                if st.button(
                    ":material/badge: Consulta de saída — Portaria (sem login)",
                    key="login_portaria_publica",
                    width="stretch",
                ):
                    entrar_modo_publico()


def gate() -> None:
    """Trava o app quando `exigir_login` está ligada e não há sessão.

    No-op no padrão (flag desligada). Chamado no `app.py` ANTES da sidebar, para que o
    menu não apareça a quem ainda não entrou.

    v6.2.0 — o modo público da Portaria também passa: quem clicou "Consulta de saída" na
    tela de login entra sem credencial. O que limita esse acesso é a sidebar, que em modo
    público monta um menu de UMA rota (`ui/sidebar.py`) — não este gate.
    """
    if exigir_login() and not usuario_logado() and not em_modo_publico():
        render_login()
        st.stop()


def rotulo_papel(papel: str | None) -> str:
    """Rótulo em pt-BR do papel (fallback: o próprio valor cru)."""
    return ROTULO_PAPEL.get(papel or "", papel or "")
