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


# ══════════════════════════════════════════════════════════════════════════════
# CONTEÚDO DA CENTRAL DE AJUDA — completude do Manual e dos guias
# ══════════════════════════════════════════════════════════════════════════════

from services.ajuda_conteudo import GUIAS_PERSONA, MANUAL


def test_guias_persona_tem_ambos_perfis():
    assert set(GUIAS_PERSONA) == {"assistente", "comprador"}
    for txt in GUIAS_PERSONA.values():
        assert isinstance(txt, str) and len(txt.strip()) > 100


def test_manual_estrutura_por_tela():
    assert len(MANUAL) >= 6  # cobre as principais telas do sistema
    for sec in MANUAL:
        assert sec.get("tela")
        assert sec.get("itens"), f"tela sem itens: {sec.get('tela')}"


def test_manual_todo_item_tem_explicacao_e_eli5():
    # Garante que TODO elemento tem as 3 explicações + a versão 'criança' (ELI5),
    # todas não vazias — é o contrato que a UI (normal vs ELI5) depende.
    for sec in MANUAL:
        for it in sec["itens"]:
            for campo in ("nome", "para_que", "base", "como", "crianca"):
                assert it.get(campo) and it[campo].strip(), \
                    f"[{sec['tela']}] item '{it.get('nome')}' sem '{campo}'"


def test_manual_cobre_telas_essenciais():
    telas = " ".join(s["tela"] for s in MANUAL)
    for chave in ("Dashboard", "Inventário", "Ficha 360", "Requisição",
                  "Compras", "Gerenciar Itens", "Configurações"):
        assert chave in telas, f"Manual não cobre: {chave}"
