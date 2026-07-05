"""v2.11.0 — Central de Ajuda + Tema claro/escuro.

A Central de Ajuda reusa o Feedback já existente (coberto por test_feedback.py) — aqui
o foco é o núcleo NOVO e testável: a paleta de tema pura (`services.tema.paleta`), que é
o ponto único de verdade de cores para claro/escuro (CSS global, option_menu e gráficos).
"""
from services.tema import paleta, ACCENT


def test_paleta_dark_usa_template_escuro():
    p = paleta("dark")
    assert p["tipo"] == "dark"
    assert p["plotly_template"] == "plotly_dark"


def test_paleta_light_usa_template_claro():
    p = paleta("light")
    assert p["tipo"] == "light"
    assert p["plotly_template"] == "plotly_white"


def test_paleta_tipo_invalido_cai_para_dark():
    # Defensivo: qualquer valor inesperado → dark (padrão da marca).
    assert paleta("qualquer")["tipo"] == "dark"
    assert paleta(None)["tipo"] == "dark"


def test_accent_constante_nos_dois_temas():
    assert paleta("dark")["accent"] == ACCENT == "#F36F21"
    assert paleta("light")["accent"] == ACCENT


def test_paleta_tem_chaves_esperadas():
    chaves = {"tipo", "accent", "plotly_template", "paper_bg", "plot_bg", "texto",
              "texto_suave", "accent_borda", "painel_bg", "painel_borda", "css",
              "option_menu_styles"}
    assert chaves <= set(paleta("dark").keys())


def test_option_menu_styles_bem_formado():
    st = paleta("light")["option_menu_styles"]
    assert set(st.keys()) == {"container", "icon", "nav-link", "nav-link-selected"}
    assert st["icon"]["color"] == ACCENT
    assert ACCENT in st["nav-link-selected"]["border-left"]


def test_css_tokens_presentes_para_styles():
    # services.styles depende destes tokens no :root.
    css = paleta("dark")["css"]
    for k in ("accent", "accent_hover", "bg_sidebar", "bg_main", "bg_card", "bg_metric",
              "bg_grid", "bg_th", "bg_expander", "bg_input_foco", "borda", "texto",
              "texto_suave"):
        assert k in css, k


def test_light_e_dark_tem_fundos_diferentes():
    assert paleta("dark")["css"]["bg_main"] != paleta("light")["css"]["bg_main"]
