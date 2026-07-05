"""Paleta de tema (v2.11.0) — ponto único de verdade de cores para claro/escuro.

Streamlit 1.57 deixa o app DETECTAR o tema ativo (`st.context.theme.type`) mas NÃO
trocá-lo por código — a troca é pelo menu embutido (☰ → Settings → Theme). Este módulo
é PURO (sem importar streamlit) para ser testável: dado o tipo ("light"/"dark"), devolve
todas as cores que a UI aplica — no CSS global (`services.styles`), nos gráficos Plotly,
no `option_menu` e nos painéis inline — para tudo acompanhar o tema em vez de ficar preso
no dark hardcoded de antes.

A cor de marca (laranja Inventus `#F36F21`) é constante nos dois temas; o dark reproduz os
valores que já existiam; o light é o espelho coerente com o tema claro do Streamlit.
"""
from __future__ import annotations

ACCENT = "#F36F21"        # laranja Inventus — constante nos dois temas
ACCENT_HOVER = "#d65a12"

# Tokens de cor por tema. O dark reproduz o que estava hardcoded em services/styles.py
# e nos gráficos; o light é o espelho.
_TEMAS = {
    "dark": {
        "plotly_template": "plotly_dark",
        "bg_sidebar":   "#050505",
        "bg_main":      "#0E0E0E",
        "bg_card":      "#1A1A1A",
        "bg_metric":    "#121212",
        "bg_grid":      "#0A0A0A",   # grid de métricas da sidebar
        "bg_th":        "#252525",   # cabeçalho de tabela
        "bg_expander":  "#121212",
        "bg_input_foco":"#222222",
        "borda":        "#2A2A2A",
        "texto":        "#FFFFFF",
        "texto_suave":  "#B3B3B3",
        "accent_borda": "#0E0E0E",   # borda das barras (contraste no escuro)
        "menu_hover":   "#1A1A1A",
        "menu_sel_bg":  "#1A1A1A",
        "painel_bg":    "#1e2130",   # divs inline (ex.: cartões de contexto)
        "painel_borda": "#3e424b",
    },
    "light": {
        "plotly_template": "plotly_white",
        "bg_sidebar":   "#F4F5F7",
        "bg_main":      "#FFFFFF",
        "bg_card":      "#F5F6F8",
        "bg_metric":    "#FFFFFF",
        "bg_grid":      "#EEF0F3",
        "bg_th":        "#EEF0F3",
        "bg_expander":  "#FAFBFC",
        "bg_input_foco":"#FFFFFF",
        "borda":        "#D9DCE1",
        "texto":        "#0E1117",
        "texto_suave":  "#4A4F57",
        "accent_borda": "#FFFFFF",
        "menu_hover":   "#E6E9EF",
        "menu_sel_bg":  "#FFE9DC",   # laranja bem claro no item selecionado
        "painel_bg":    "#F0F2F6",
        "painel_borda": "#D0D3D9",
    },
}

_BG_TRANSPARENTE = "rgba(0,0,0,0)"  # gráficos herdam o fundo da página em qualquer tema


def paleta(tipo="dark"):
    """Devolve a paleta do tema. `tipo` = 'light' | 'dark' (qualquer outro → dark).

    Chaves de alto nível usadas pela UI (gráficos/painéis/menu): accent, plotly_template,
    paper_bg, plot_bg, texto, texto_suave, accent_borda, painel_bg, painel_borda,
    option_menu_styles. `css` traz o dicionário completo de tokens para services.styles."""
    base = _TEMAS.get(tipo, _TEMAS["dark"])
    return {
        "tipo": "light" if tipo == "light" else "dark",
        "accent": ACCENT,
        "plotly_template": base["plotly_template"],
        "paper_bg": _BG_TRANSPARENTE,
        "plot_bg": _BG_TRANSPARENTE,
        "texto": base["texto"],
        "texto_suave": base["texto_suave"],
        "accent_borda": base["accent_borda"],
        "painel_bg": base["painel_bg"],
        "painel_borda": base["painel_borda"],
        "css": {**base, "accent": ACCENT, "accent_hover": ACCENT_HOVER},
        "option_menu_styles": {
            "container": {"padding": "0!important", "background-color": base["bg_sidebar"]},
            "icon": {"color": ACCENT, "font-size": "18px"},
            "nav-link": {"font-size": "14px", "text-align": "left", "margin": "0px",
                         "--hover-color": base["menu_hover"], "color": base["texto_suave"]},
            "nav-link-selected": {"background-color": base["menu_sel_bg"],
                                  "color": base["texto"], "border-left": f"4px solid {ACCENT}"},
        },
    }
