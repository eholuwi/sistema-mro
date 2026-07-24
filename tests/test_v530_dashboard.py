"""Smoke COM DADOS da página Dashboard (v5.3.0 / F4a).

Por que este arquivo existe: o smoke do router (`test_v500_router`) renderiza sobre um
banco VAZIO, e o Dashboard retorna cedo quando não há item cadastrado — ou seja, os
`_render_dash_*` (≈700 linhas migradas na F4a) e os gráficos de
`ui/componentes/graficos.py` NÃO seriam exercitados. Aqui semeamos inventário +
movimentações para que as 3 abas rodem de verdade, pegando NameError/import faltando
que o smoke vazio não pegaria.
"""
from streamlit.testing.v1 import AppTest


def _render_dashboard():
    script = (
        "import streamlit as st\n"
        "st.cache_data.clear()\n"          # não herdar cache de outro teste
        "from ui.router import render_pagina\n"
        "render_pagina('Dashboard')\n"
    )
    at = AppTest.from_string(script)
    at.run()
    return at


def test_dashboard_renderiza_com_dados(db, make_item):
    """As 3 abas do Dashboard renderizam sobre um banco com dados reais (não vazio)."""
    from services import db_functions as F

    id_a = make_item(part_number="PN-DASH-1", nome="Item Dashboard 1",
                     estoque=50, minimo=10, tipo="Spare Parts")
    id_b = make_item(part_number="PN-DASH-2", nome="Item Dashboard 2",
                     estoque=2, minimo=20, tipo="Consumivel")

    F.registrar_movimentacao(item_id=id_a, tipo="entrada", quantidade=10,
                             centro_custo="MANUTENÇÃO", solicitante="teste",
                             emitente="teste", observacao="smoke F4a")
    F.registrar_movimentacao(item_id=id_b, tipo="saida", quantidade=3,
                             centro_custo="PRODUÇÃO", solicitante="teste",
                             emitente="teste", observacao="smoke F4a")

    at = _render_dashboard()
    assert not at.exception, f"Dashboard lançou: {[e.value for e in at.exception]}"
    assert len(at.title) >= 1, "Dashboard não renderizou título"


def test_dashboard_banco_vazio_avisa_e_nao_quebra(db):
    """Sem item cadastrado, a página avisa e sai — sem exceção (guarda do render)."""
    at = _render_dashboard()
    assert not at.exception, f"Dashboard lançou: {[e.value for e in at.exception]}"
    assert len(at.info) >= 1, "Deveria exibir o aviso de 'nenhum item cadastrado'"
