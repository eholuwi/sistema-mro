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

import streamlit as st
from streamlit_option_menu import option_menu

from services.db_functions import listar_inventario, listar_scs
from ui.router import opcoes_menu, icones_menu
from ui.tema import paleta_atual

VERSAO = "v5.5.0"

# v5.5.0 (F5) — caminho ABSOLUTO do logo. Em dev o Streamlit roda com cwd = raiz do
# projeto e o caminho relativo funcionava; no servidor o `iniciar_mro.bat` sobe a partir
# de C:\MRO\ apontando para app\app.py, então "inventus_logo.png" seria procurado em
# C:\MRO\ e a sidebar subiria sem logo.
LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "inventus_logo.png")


def render_sidebar() -> str:
    """Desenha a sidebar e devolve a página escolhida no menu."""
    pal = paleta_atual()
    with st.sidebar:
        # 1. Cabeçalho com Logo/Título (v4.1.0 — logo Inventus; versão no rodapé da nav)
        st.image(LOGO, width="stretch")
        st.markdown("""
        <div class="sidebar-title">
            <span style="font-size: 1.4rem;">MRO Inventus</span>
        </div>
        """, unsafe_allow_html=True)

        # 2. Navegação (Option Menu) — opções/ícones vêm do router (fonte única).
        pagina = option_menu(
            menu_title=None,
            options=opcoes_menu(),
            icons=icones_menu(),
            menu_icon="cast",
            default_index=0,
            styles=pal["option_menu_styles"],
        )

        # 2b. Tema (claro/escuro) — controlado pelo app e lembrado na URL (?tema=).
        # O Streamlit 1.57 não troca o tema por código; aqui gravamos a escolha e o topo
        # do script reaplica a paleta. Padrão claro. (Tabelas seguem o tema base do config.)
        _op_tema = {"Claro": "light", "Escuro": "dark"}
        _lbl_atual = "Escuro" if pal["tipo"] == "dark" else "Claro"
        _escolha_tema = st.radio("Tema", list(_op_tema.keys()),
                                 index=list(_op_tema.keys()).index(_lbl_atual),
                                 horizontal=True, key="sb_tema")
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

        st.markdown(f"""
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
        """, unsafe_allow_html=True)

        # 4. Barra de Progresso de Inventário
        progresso = inv_count / total if total > 0 else 0
        st.markdown(f"""
        <div class="progress-container">
            <div class="progress-label">Inventariados: {inv_count}/{total}</div>
        </div>
        """, unsafe_allow_html=True)

        # Usa o st.progress nativo, mas o CSS acima tenta estilizar o container se possível
        st.progress(progresso)

        # 5. Perfil do Usuário (Rodapé)
        avatar_url = "https://ui-avatars.com/api/?name=Luis+Oliveira&background=F36F21&color=fff"
        st.markdown(f"""
        <div class="user-profile">
            <img src="{avatar_url}" class="user-avatar" alt="User">
            <div class="user-info">
                <h4>Luis Oliveira</h4>
                <p>Inventus Power</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # v4.1.0 — versão do sistema no rodapé da barra de navegação
        st.markdown(
            "<div style='text-align:center; margin-top:10px; color: var(--primary-orange); "
            f"font-weight:700; font-size:0.8rem; letter-spacing:0.5px;'>{VERSAO}</div>",
            unsafe_allow_html=True,
        )

    return pagina
