"""Sidebar da UI (v5.0.0) — logo, navegação (option_menu), tema e métricas.

Extraída de app.py na fundação da refatoração. `render_sidebar()` desenha a barra
lateral e devolve o NOME da página escolhida. As opções/ícones do menu vêm do router
(ui.router) — fonte única. A paleta vem de `ui.tema.paleta_atual()`.

Cache: a leitura `listar_inventario()` das métricas segue direta (sem `@st.cache_data`)
nesta fase — a ativação do cache é progressiva e pareada com invalidação nas páginas
migradas, para não arriscar métricas desatualizadas enquanto a maioria das telas ainda
escreve pelo caminho antigo (ver ui/cache.py e docs/PLANO_V5_EVOLUCAO.md).
"""

from __future__ import annotations

import os
from urllib.parse import quote_plus

import streamlit as st
from streamlit_option_menu import option_menu

from services.constants import VERSAO_ROTULO
from services.db_functions import listar_inventario, listar_scs
from ui.auth import em_modo_publico, fazer_logout, rotulo_papel, sair_modo_publico, usuario_logado
from ui.router import ROTAS, ROTA_PUBLICA, opcoes_menu, icones_menu
from ui.tema import paleta_atual

# v6.0.0 — o número deixou de ser digitado aqui e vem de `services/constants.py`
# (fonte única). Este alias existe porque o rodapé e `scripts/release.py` já o usavam.
VERSAO = VERSAO_ROTULO

# v5.5.0 (F5) — caminho ABSOLUTO do logo. Em dev o Streamlit roda com cwd = raiz do
# projeto e o caminho relativo funcionava; no servidor o `iniciar_mro.bat` sobe a partir
# de C:\MRO\ apontando para app\app.py, então "inventus_logo.png" seria procurado em
# C:\MRO\ e a sidebar subiria sem logo.
LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "inventus_logo.png")


def _render_perfil(usuario: dict | None) -> None:
    """Cartão do usuário no rodapé da barra (v6.1.0).

    Deslogado (flag `exigir_login` off, o padrão) mantém o bloco fixo "Luis Oliveira /
    Inventus Power" que existe desde a v4.1.0 — o app segue idêntico para quem não ligou
    o login. Logado, mostra a pessoa de verdade, o papel e o botão de sair.
    """
    nome = usuario["nome"] if usuario else "Luis Oliveira"
    subtitulo = rotulo_papel(usuario["papel"]) if usuario else "Inventus Power"
    avatar_url = f"https://ui-avatars.com/api/?name={quote_plus(nome)}&background=F36F21&color=fff"
    st.markdown(
        f"""
    <div class="user-profile">
        <img src="{avatar_url}" class="user-avatar" alt="User">
        <div class="user-info">
            <h4>{nome}</h4>
            <p>{subtitulo}</p>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )
    if usuario and st.button(":material/logout: Sair", key="sb_sair", width="stretch"):
        fazer_logout()


def _sidebar_publica(pal) -> str:
    """Barra do modo público da Portaria (v6.2.0): UMA rota e nada mais.

    Sem as métricas de estoque do rodapé, de propósito — a guarita consulta requisição, e
    total de itens/críticos/SCs abertas é informação interna que não precisa aparecer num
    terminal compartilhado (de quebra, poupa o `listar_inventario()` a cada consulta).
    """
    with st.sidebar:
        st.image(LOGO, width="stretch")
        st.markdown(
            """
        <div class="sidebar-title">
            <span style="font-size: 1.4rem;">MRO Inventus</span>
        </div>
        """,
            unsafe_allow_html=True,
        )
        option_menu(
            menu_title=None,
            options=[ROTA_PUBLICA],
            icons=[ROTAS[ROTA_PUBLICA].icone],
            menu_icon="cast",
            default_index=0,
            styles=pal["option_menu_styles"],
        )
        st.markdown("---")
        st.caption(":material/badge: **Portaria** · consulta pública")
        if st.button(":material/logout: Sair do modo público", key="sb_sair_publico", width="stretch"):
            sair_modo_publico()
        st.markdown(
            "<div style='text-align:center; margin-top:10px; color: var(--primary-orange); "
            f"font-weight:700; font-size:0.8rem; letter-spacing:0.5px;'>{VERSAO}</div>",
            unsafe_allow_html=True,
        )
    return ROTA_PUBLICA


def render_sidebar() -> str:
    """Desenha a sidebar e devolve a página escolhida no menu."""
    pal = paleta_atual()
    usuario = usuario_logado()
    papel = usuario["papel"] if usuario else None
    # v6.2.0 — o modo público é checado ANTES de qualquer coisa e é o único jeito correto:
    # `papel_atual()` é None tanto para quem entrou pela consulta da Portaria quanto para
    # quem abre o app com a flag desligada, e para este segundo caso `opcoes_menu(None)`
    # devolve o menu INTEIRO (contrato legado). Inverter a ordem entregaria as 10 rotas a
    # quem entrou sem credencial nenhuma.
    if em_modo_publico() and not usuario:
        return _sidebar_publica(pal)
    with st.sidebar:
        # 1. Cabeçalho com Logo/Título (v4.1.0 — logo Inventus; versão no rodapé da nav)
        st.image(LOGO, width="stretch")
        st.markdown(
            """
        <div class="sidebar-title">
            <span style="font-size: 1.4rem;">MRO Inventus</span>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # 2. Navegação (Option Menu) — opções/ícones vêm do router (fonte única), agora
        # filtrados pelo papel de quem entrou (v6.1.0). Sem login, `papel` é None e o
        # menu é o completo de sempre.
        opcoes = opcoes_menu(papel)
        if not opcoes:
            # v6.2.0 — os 5 papéis do domínio têm rota; sobra o papel DESCONHECIDO (banco
            # editado à mão, papel removido numa versão futura), que nega por omissão. Sai
            # daqui COM o botão Sair renderizado — deixar a pessoa presa numa tela sem
            # saída seria a pior versão desta borda.
            st.info("Seu perfil ainda não tem telas. Fale com o almoxarife.")
            _render_perfil(usuario)
            st.stop()

        pagina = option_menu(
            menu_title=None,
            options=opcoes,
            icons=icones_menu(papel),
            menu_icon="cast",
            default_index=0,
            styles=pal["option_menu_styles"],
        )

        # 2b. Tema (claro/escuro) — controlado pelo app e lembrado na URL (?tema=).
        # O Streamlit 1.57 não troca o tema por código; aqui gravamos a escolha e o topo
        # do script reaplica a paleta. Padrão claro. (Tabelas seguem o tema base do config.)
        _op_tema = {"Claro": "light", "Escuro": "dark"}
        _lbl_atual = "Escuro" if pal["tipo"] == "dark" else "Claro"
        _escolha_tema = st.radio(
            "Tema",
            list(_op_tema.keys()),
            index=list(_op_tema.keys()).index(_lbl_atual),
            horizontal=True,
            key="sb_tema",
        )
        if _op_tema[_escolha_tema] != pal["tipo"]:
            st.query_params["tema"] = _op_tema[_escolha_tema]
            st.rerun()

        st.markdown("---")

        # 3. Métricas em Grid (Visual da Imagem)
        itens_all = listar_inventario()
        total = len(itens_all)
        # Ajuste conforme sua lógica de status atual (OK, ATENÇÃO, COMPRAR)
        comprar = sum(1 for i in itens_all if "COMPRAR" in i.get("status_material", ""))
        atencao = sum(1 for i in itens_all if "ATENÇÃO" in i.get("status_material", ""))
        scs_abertas = len(listar_scs(apenas_abertas=True))
        inv_count = sum(1 for i in itens_all if i.get("data_inventario"))

        st.markdown(
            f"""
        <div class="sidebar-metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Total</div>
                <div class="metric-value">{total}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Alerta <span class="dot dot-yellow"></span></div>
                <div class="metric-value">{atencao}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Críticos <span class="dot dot-red"></span></div>
                <div class="metric-value">{comprar}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">SCs</div>
                <div class="metric-value">{scs_abertas}</div>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # 4. Barra de Progresso de Inventário
        progresso = inv_count / total if total > 0 else 0
        st.markdown(
            f"""
        <div class="progress-container">
            <div class="progress-label">Inventariados: {inv_count}/{total}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Usa o st.progress nativo, mas o CSS acima tenta estilizar o container se possível
        st.progress(progresso)

        # 5. Perfil do Usuário (Rodapé)
        _render_perfil(usuario)

        # v4.1.0 — versão do sistema no rodapé da barra de navegação
        st.markdown(
            "<div style='text-align:center; margin-top:10px; color: var(--primary-orange); "
            f"font-weight:700; font-size:0.8rem; letter-spacing:0.5px;'>{VERSAO}</div>",
            unsafe_allow_html=True,
        )

    return pagina
