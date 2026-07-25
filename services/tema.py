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

ACCENT = "#F36F21"  # laranja Inventus — constante nos dois temas
ACCENT_HOVER = "#d65a12"

# Tokens de cor por tema (v4.0.0 — redesign profissional laranja/cinza; CLARO é o padrão).
# O claro usa uma tela cinza-clara com superfícies brancas + sombras leves; o escuro é o
# espelho coerente. Ambos carregam shadow/shadow_lg/accent_tint p/ o CSS global.
_TEMAS = {
    "dark": {
        "plotly_template": "plotly_dark",
        "bg_sidebar": "#17181C",
        "bg_main": "#0E0F12",
        "bg_card": "#1F2126",
        "bg_metric": "#17181C",
        "bg_grid": "#1F2126",  # grid de métricas da sidebar
        "bg_th": "#22242A",  # cabeçalho de tabela
        "bg_expander": "#17181C",
        "bg_input_foco": "#22242A",
        "borda": "#2A2C31",
        "texto": "#F4F5F7",
        "texto_suave": "#A0A6B0",
        "accent_borda": "#0E0F12",  # borda das barras (contraste no escuro)
        "menu_hover": "#1F2126",
        "menu_sel_bg": "#2A1B10",  # laranja bem escuro no item selecionado
        "painel_bg": "#1F2126",  # divs inline (ex.: cartões de contexto)
        "painel_borda": "#2A2C31",
        "accent_tint": "#2A1B10",  # tint do accent (anel de foco/seleção)
        "shadow": "0 1px 3px rgba(0,0,0,.45)",
        "shadow_lg": "0 8px 24px rgba(0,0,0,.55)",
    },
    "light": {
        "plotly_template": "plotly_white",
        "bg_sidebar": "#FFFFFF",
        "bg_main": "#F6F7F9",
        "bg_card": "#FFFFFF",
        "bg_metric": "#FFFFFF",
        "bg_grid": "#F1F3F5",
        "bg_th": "#F1F3F5",
        "bg_expander": "#FCFCFD",
        "bg_input_foco": "#FFFFFF",
        "borda": "#E4E7EB",
        "texto": "#1A1D21",
        "texto_suave": "#5B6470",
        "accent_borda": "#FFFFFF",
        "menu_hover": "#F1F3F5",
        "menu_sel_bg": "#FFF1E8",  # laranja bem claro no item selecionado
        "painel_bg": "#F6F7F9",
        "painel_borda": "#E4E7EB",
        "accent_tint": "#FFF1E8",  # tint do accent (anel de foco/seleção)
        "shadow": "0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.07)",
        "shadow_lg": "0 6px 18px rgba(16,24,40,.10)",
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
            "nav-link": {
                "font-size": "14px",
                "text-align": "left",
                "margin": "0px",
                "--hover-color": base["menu_hover"],
                "color": base["texto_suave"],
            },
            "nav-link-selected": {
                "background-color": base["menu_sel_bg"],
                "color": base["texto"],
                "border-left": f"4px solid {ACCENT}",
            },
        },
    }
