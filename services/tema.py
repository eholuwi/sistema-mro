"""Paleta de tema (v6.0.0) — ponto único de verdade de cores para claro/escuro.

Streamlit 1.57 deixa o app DETECTAR o tema ativo (`st.context.theme.type`) mas NÃO
trocá-lo por código — a troca é pelo menu embutido (☰ → Settings → Theme). Este módulo
é PURO (sem importar streamlit) para ser testável: dado o tipo ("light"/"dark"), devolve
todas as cores que a UI aplica — no CSS global (`services.styles`), nos gráficos Plotly,
no `option_menu` e nos painéis inline — para tudo acompanhar o tema em vez de ficar preso
no dark hardcoded de antes.

A cor de marca (laranja Inventus) é constante nos dois temas; o dark reproduz os valores
que já existiam; o light é o espelho coerente com o tema claro do Streamlit.

v6.0.0 — os tokens foram alinhados ao **`docs/template_moderno.html`**, a referência de
identidade visual do projeto, e o módulo ganhou uma camada SEMÂNTICA (positivo/negativo/
neutro/série categórica) que antes vivia como hex solto espalhado pelas páginas.
"""

from __future__ import annotations

# ── Marca (docs/template_moderno.html: --primary / --primary-d / --primary-soft) ──
ACCENT = "#F58220"  # laranja Inventus — constante nos dois temas
ACCENT_HOVER = "#D97314"
ACCENT_SOFT = "#FEF2E6"
ACCENT_GLOW = "rgba(245,130,32,.35)"  # sombra do botão primário (o accent com alpha)
RAIO = "14px"  # --radius do template (cards/containers)

# ── Camada semântica (v6.0.0) ────────────────────────────────────────────────
# Antes cada página escolhia o seu verde/vermelho na mão (#22c55e, #2ecc71, #ef4444,
# #e74c3c, #3498db…) — cinco tons para três significados. Aqui há UM de cada.
POSITIVO = "#16A34A"  # entrada, alta, "está OK"
NEGATIVO = "#DC2626"  # saída, ruptura, crítico
NEUTRO = "#5B5B5B"  # estável, sem sinal (--sidebar do template)
INFO = "#1D4ED8"  # devolução, dado auxiliar
ATENCAO = "#D97706"  # alerta intermediário (mesmo tom do .dot-yellow do CSS)

# Série categórica de gráficos (donut/pizza/multi-série). A ORDEM importa e vem com uma
# razão documentada no template: laranja → azul → vermelho ANTES de qualquer verde,
# porque laranja e verde ficam a ΔE 3,3 em protanopia — indistinguíveis lado a lado.
# A lista antiga começava com três laranjas seguidos (#F36F21/#F7941E/#FFB65C).
SERIE_CATEGORICA = [
    ACCENT,  # laranja da marca
    "#1D4ED8",  # azul
    "#B91C1C",  # vermelho
    "#5B5B5B",  # cinza
    "#7C3AED",  # violeta
    "#0E7490",  # petróleo
    "#B45309",  # âmbar escuro
    "#15803D",  # verde (só depois dos contrastantes)
    "#9CA3AF",  # cinza claro — cauda "Outros"
]

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
    # v6.0.0 — valores de docs/template_moderno.html (--bg, --surface, --border,
    # --text, --muted, --gray-soft, --primary-soft, --shadow).
    "light": {
        "plotly_template": "plotly_white",
        "bg_sidebar": "#FFFFFF",
        "bg_main": "#F5F5F5",
        "bg_card": "#FFFFFF",
        "bg_metric": "#FFFFFF",
        "bg_grid": "#EEF0F2",
        "bg_th": "#EEF0F2",
        "bg_expander": "#FCFCFD",
        "bg_input_foco": "#FFFFFF",
        "borda": "#E5E5E5",
        "texto": "#2B2B2B",
        "texto_suave": "#7A7F87",
        "accent_borda": "#FFFFFF",
        "menu_hover": "#EEF0F2",
        "menu_sel_bg": ACCENT_SOFT,  # laranja bem claro no item selecionado
        "painel_bg": "#F5F5F5",
        "painel_borda": "#E5E5E5",
        "accent_tint": ACCENT_SOFT,  # tint do accent (anel de foco/seleção)
        "shadow": "0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.06)",
        "shadow_lg": "0 6px 18px rgba(15,23,42,.10)",
    },
}

_BG_TRANSPARENTE = "rgba(0,0,0,0)"  # gráficos herdam o fundo da página em qualquer tema


def paleta(tipo="dark"):
    """Devolve a paleta do tema. `tipo` = 'light' | 'dark' (qualquer outro → dark).

    Chaves de alto nível usadas pela UI (gráficos/painéis/menu): accent, plotly_template,
    paper_bg, plot_bg, texto, texto_suave, accent_borda, painel_bg, painel_borda,
    positivo, negativo, neutro, info, atencao, serie, option_menu_styles. `css` traz o
    dicionário completo de tokens para services.styles."""
    base = _TEMAS.get(tipo, _TEMAS["dark"])
    escuro = tipo != "light"
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
        # Semânticas (v6.0.0). No escuro, verde/vermelho/azul sobem de luminosidade —
        # os tons do template são calibrados para fundo claro e somem no #0E0F12.
        "positivo": "#22C55E" if escuro else POSITIVO,
        "negativo": "#F87171" if escuro else NEGATIVO,
        "neutro": "#9CA3AF" if escuro else NEUTRO,
        "info": "#60A5FA" if escuro else INFO,
        "atencao": "#FBBF24" if escuro else ATENCAO,
        "serie": list(SERIE_CATEGORICA),
        "css": {
            **base,
            "accent": ACCENT,
            "accent_hover": ACCENT_HOVER,
            # Tokens que o CSS global consumia como hex fixo até a v5.x.
            "positivo": POSITIVO,
            "negativo": NEGATIVO,
            "atencao": ATENCAO,
            "raio": RAIO,
            "accent_glow": ACCENT_GLOW,
        },
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
