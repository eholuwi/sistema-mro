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
    ROTAS, ROTAS_MIGRADAS, opcoes_menu, icones_menu, render_pagina,
)


# ── Metadados do router (puro, sem Streamlit) ────────────────────────────────

def test_menu_opcoes_e_icones_alinhados():
    # option_menu recebe options e icons na mesma ordem/tamanho — desalinhar quebra o menu.
    assert len(opcoes_menu()) == len(icones_menu()) == len(ROTAS)
    assert opcoes_menu()[0] == "Dashboard"          # 1º item (default_index=0)
    assert {"Ajuda", "Configurações"} <= set(opcoes_menu())


def test_rotas_migradas_sao_as_com_render():
    # Fonte única: ROTAS_MIGRADAS = exatamente as rotas com render != None.
    assert ROTAS_MIGRADAS == frozenset({"Ajuda", "Configurações", "SCM Integrado",
                                        "Saldo em Estoque", "Gerenciar Itens", "Dashboard"})
    for nome in ROTAS_MIGRADAS:
        assert ROTAS[nome].render is not None


def test_render_pagina_recusa_pagina_nao_migrada():
    # O app só chama render_pagina quando pagina in ROTAS_MIGRADAS; fora disso, erra alto.
    with pytest.raises(KeyError):
        render_pagina("Movimentação")  # ainda inline no app.py (migra na F4b)
    with pytest.raises(KeyError):
        render_pagina("Inexistente")


# ── Smoke de render por página migrada (AppTest sobre banco isolado) ──────────

def _render_em_apptest(nome):
    script = (
        "from ui.router import render_pagina\n"
        f"render_pagina({nome!r})\n"
    )
    at = AppTest.from_string(script)
    at.run()
    return at


@pytest.mark.parametrize("pagina", sorted(ROTAS_MIGRADAS))
def test_pagina_migrada_renderiza_sem_excecao(pagina, db):
    at = _render_em_apptest(pagina)
    assert not at.exception, f"{pagina} lançou: {[e.value for e in at.exception]}"
    assert len(at.title) >= 1, f"{pagina} não renderizou título"
