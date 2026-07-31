"""v5.9.0 — Cadastro de Itens: trocar de item ATUALIZA o formulário (bug do selectbox).

Causa raiz coberta aqui: widgets com `key=` fixo tomam a key como identidade principal
no Streamlit (`key_as_main_identity`), o que tira `options`/`index`/`value` do cálculo do
id do widget. Resultado: `index=`/`value=` só valiam na 1ª renderização e, ao trocar de
item, o formulário continuava exibindo — e GRAVANDO — os dados do item anterior.

Não é teste cosmético: o último caso prova que os valores do item A não vazam para o
item B no banco. As keys continuam existindo (as duas abas da tela têm widgets de mesmo
rótulo/opções e sem key colidiriam em `StreamlitDuplicateElementId`); quem devolve a
identidade ao item é `resetar_campos_ao_trocar`.
"""

import pytest
from streamlit.testing.v1 import AppTest

import database

SCRIPT = "from ui.router import render_pagina\nrender_pagina('Cadastro de Itens')\n"

ROTULO_A = "PN-A — Item A"
ROTULO_B = "PN-B — Item B"


@pytest.fixture
def dois_itens(db, make_item):
    """Dois itens com TODOS os campos editáveis diferentes entre si."""
    make_item(
        part_number="PN-A",
        nome="Item A",
        unidade="UN",
        tipo="Spare Parts",
        importancia="Importante",
        lead=7,
        minimo=10,
    )
    make_item(
        part_number="PN-B",
        nome="Item B",
        unidade="CX",
        tipo="Consumivel",
        importancia="Admin",
        lead=45,
        minimo=99,
    )
    return db


def _selecionar(at, rotulo):
    at.selectbox(key="sel_edit_item").select(rotulo).run()
    return at


def test_trocar_de_item_atualiza_todos_os_campos(dois_itens):
    at = AppTest.from_string(SCRIPT)
    at.run()

    _selecionar(at, ROTULO_A)
    assert at.selectbox(key="ed_un").value == "UN"
    assert at.selectbox(key="ed_tipo").value == "Spare Parts"
    assert at.selectbox(key="ed_imp").value == "Importante"
    assert at.number_input(key="ed_lead").value == 7
    assert at.number_input(key="ed_min").value == 10.0

    # A troca é o ponto do bug: antes da correção, tudo abaixo continuava mostrando A.
    _selecionar(at, ROTULO_B)
    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox(key="ed_un").value == "CX"
    assert at.selectbox(key="ed_tipo").value == "Consumivel"
    assert at.selectbox(key="ed_imp").value == "Admin"
    assert at.number_input(key="ed_lead").value == 45
    assert at.number_input(key="ed_min").value == 99.0


def test_salvar_apos_trocar_nao_vaza_valores_do_item_anterior(dois_itens):
    """O dano real do bug: gravar em B os dados que ainda estavam na tela vindos de A."""
    at = AppTest.from_string(SCRIPT)
    at.run()
    _selecionar(at, ROTULO_A)
    _selecionar(at, ROTULO_B)

    botao = [b for b in at.button if "Atualizar Item" in b.label][0]
    botao.click().run()
    assert not at.exception, [e.value for e in at.exception]

    conn = database.get_connection()
    try:
        b = conn.execute(
            "SELECT unidade, tipo_material, importancia, lead_time_dias, estoque_minimo "
            "FROM inventario WHERE part_number='PN-B'"
        ).fetchone()
        a = conn.execute("SELECT unidade FROM inventario WHERE part_number='PN-A'").fetchone()
    finally:
        conn.close()

    assert b["unidade"] == "CX"
    assert b["tipo_material"] == "Consumivel"
    assert b["importancia"] == "Admin"
    assert b["lead_time_dias"] == 45
    assert b["estoque_minimo"] == 99.0
    assert a["unidade"] == "UN"  # o item A segue intacto


def test_pagina_com_item_selecionado_nao_colide_id_com_a_aba_de_cadastro(dois_itens):
    """As duas abas têm widgets de mesmo rótulo/opções (Unidade, Tipo, Importância…).

    Com o item na unidade padrão (`UNIDADES[0]`), remover as keys faria os ids baterem e
    o Streamlit levantaria `StreamlitDuplicateElementId` — a página inteira quebraria.
    """
    at = AppTest.from_string(SCRIPT)
    at.run()
    _selecionar(at, ROTULO_A)  # PN-A está em "UN" = UNIDADES[0], o caso que colide
    assert not at.exception, [e.value for e in at.exception]
