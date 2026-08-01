"""v5.0.0 (F1) — Smoke do router e das páginas migradas para ui/paginas/.

Rede de segurança da refatoração faseada (docs/PLANO_V5_EVOLUCAO.md): cada página em
ROTAS_MIGRADAS precisa RENDERIZAR sem exceção sobre um banco isolado. À medida que
novas páginas migram (F3/F4), a parametrização por ROTAS_MIGRADAS passa a cobri-las
automaticamente — este arquivo vira o smoke vivo de toda a refatoração.

Não importa app.py (que exige runtime Streamlit + set_page_config no load): exercita a
UI pelo ponto de entrada modular `render_pagina`, que é exatamente o que o app despacha.
"""

import pytest
from streamlit.testing.v1 import AppTest

from ui.router import (
    ROTAS,
    ROTAS_MIGRADAS,
    opcoes_menu,
    icones_menu,
    render_pagina,
)


# ── Metadados do router (puro, sem Streamlit) ────────────────────────────────


def test_menu_opcoes_e_icones_alinhados():
    # option_menu recebe options e icons na mesma ordem/tamanho — desalinhar quebra o menu.
    assert len(opcoes_menu()) == len(icones_menu()) == len(ROTAS)
    assert opcoes_menu()[0] == "Dashboard"  # 1º item (default_index=0)
    assert "Configurações" in opcoes_menu()


def test_rotas_migradas_sao_as_com_render():
    # Fonte única: ROTAS_MIGRADAS = exatamente as rotas com render != None.
    # F4b encerrou a migração: TODAS as rotas têm render (app.py é só shell).
    assert ROTAS_MIGRADAS == frozenset(ROTAS)
    assert ROTAS_MIGRADAS == frozenset(
        {
            "Configurações",
            "Saldo em Estoque",
            "Cadastro de Itens",  # v5.9.0 — era "Gerenciar Itens"
            "Dashboard",
            "Controle de SC",
            "Ficha 360",
            "Movimentação",
        }
    )
    for nome in ROTAS_MIGRADAS:
        assert ROTAS[nome].render is not None


def test_menu_v600_nao_tem_mais_ajuda_nem_scm_integrado():
    """v6.0.0 — as duas telas saíram do MENU, mas NÃO do sistema: viraram abas
    (SCM Integrado → Controle de SC; Ajuda → Configurações). O teste protege as duas
    metades: sumiram da navegação E continuam chamáveis por `conteudo()`."""
    from ui.paginas import ajuda, scm_integrado

    assert {"Ajuda", "SCM Integrado"}.isdisjoint(set(opcoes_menu()))
    assert len(opcoes_menu()) == 7
    assert callable(ajuda.conteudo)
    assert callable(scm_integrado.conteudo)


def test_render_pagina_recusa_pagina_inexistente():
    # render_pagina erra alto para uma rota que não existe no menu (nome inválido).
    # (Após a F4b não há mais páginas inline: toda rota do menu tem render.)
    with pytest.raises(KeyError):
        render_pagina("Inexistente")


# ── Smoke de render por página migrada (AppTest sobre banco isolado) ──────────


def _render_em_apptest(nome):
    script = f"from ui.router import render_pagina\nrender_pagina({nome!r})\n"
    at = AppTest.from_string(script)
    at.run()
    return at


@pytest.mark.parametrize("pagina", sorted(ROTAS_MIGRADAS))
def test_pagina_migrada_renderiza_sem_excecao(pagina, db):
    at = _render_em_apptest(pagina)
    assert not at.exception, f"{pagina} lançou: {[e.value for e in at.exception]}"
    assert len(at.title) >= 1, f"{pagina} não renderizou título"
