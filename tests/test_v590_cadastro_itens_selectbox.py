"""v5.9.0 — Cadastro de Itens: trocar de item ATUALIZA o formulário (bug do selectbox).

Causa raiz coberta aqui: widgets com `key=` fixo tomam a key como identidade principal
no Streamlit (`key_as_main_identity`), o que tira `options`/`index`/`value` do cálculo do
id do widget. Resultado: `index=`/`value=` só valiam na 1ª renderização e, ao trocar de
item, o formulário continuava exibindo — e GRAVANDO — os dados do item anterior.

Não é teste cosmético: o segundo caso prova que os valores do item A não vazam para o
item B no banco. As keys continuam existindo (as duas abas da tela têm widgets de mesmo
rótulo/opções e sem key colidiriam em `StreamlitDuplicateElementId`) — o que mudou na
**v6.5.1** é que elas passaram a carregar o id do item (`k_ed`), em vez de serem limpas
no `session_state` a cada troca. Ver o último teste: a limpeza tinha uma corrida que só
aparecia no navegador.
"""

import pytest
from streamlit.testing.v1 import AppTest

import database
from ui.paginas.gerenciar_itens import k_ed

SCRIPT = "from ui.router import render_pagina\nrender_pagina('Cadastro de Itens')\n"

ROTULO_A = "PN-A — Item A"
ROTULO_B = "PN-B — Item B"


@pytest.fixture
def dois_itens(db, make_item):
    """Dois itens com TODOS os campos editáveis diferentes entre si."""
    id_a = make_item(
        part_number="PN-A",
        nome="Item A",
        unidade="UN",
        tipo="Spare Parts",
        importancia="Importante",
        lead=7,
        minimo=10,
    )
    id_b = make_item(
        part_number="PN-B",
        nome="Item B",
        unidade="CX",
        tipo="Consumivel",
        importancia="Admin",
        lead=45,
        minimo=99,
    )
    return id_a, id_b


def _selecionar(at, rotulo):
    at.selectbox(key="sel_edit_item").select(rotulo).run()
    return at


def test_trocar_de_item_atualiza_todos_os_campos(dois_itens):
    id_a, id_b = dois_itens
    at = AppTest.from_string(SCRIPT)
    at.run()

    _selecionar(at, ROTULO_A)
    assert at.selectbox(key=k_ed("un", id_a)).value == "UN"
    assert at.selectbox(key=k_ed("tipo", id_a)).value == "Spare Parts"
    assert at.selectbox(key=k_ed("imp", id_a)).value == "Importante"
    assert at.number_input(key=k_ed("lead", id_a)).value == 7
    assert at.number_input(key=k_ed("min", id_a)).value == 10.0

    # A troca é o ponto do bug: antes da correção, tudo abaixo continuava mostrando A.
    _selecionar(at, ROTULO_B)
    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox(key=k_ed("un", id_b)).value == "CX"
    assert at.selectbox(key=k_ed("tipo", id_b)).value == "Consumivel"
    assert at.selectbox(key=k_ed("imp", id_b)).value == "Admin"
    assert at.number_input(key=k_ed("lead", id_b)).value == 45
    assert at.number_input(key=k_ed("min", id_b)).value == 99.0


def test_valor_do_item_anterior_nao_alcanca_o_widget_do_item_novo(dois_itens):
    """v6.5.1 — a corrida que fazia o formulário travar no item anterior no navegador.

    A limpeza por `session_state` acontecia ANTES dos widgets serem desenhados; se a
    execução fosse cancelada no meio (o Streamlit cancela a que está em curso quando
    chega uma nova interação, e esta tela redesenha as 3 abas a cada rerun), a trava
    "item atual" já dizia "não mudou" e os valores do item anterior voltavam do
    navegador — só um F5 resolvia.

    O teste simula o estado sujo que sobrava: valores do item A presentes no
    `session_state` no momento em que o item B é renderizado. Com a key carregando o id,
    eles pertencem a OUTRO widget e não têm como contaminar o formulário de B.
    """
    id_a, id_b = dois_itens
    at = AppTest.from_string(SCRIPT)
    at.run()
    _selecionar(at, ROTULO_A)

    at.session_state[k_ed("un", id_a)] = "UN"
    at.session_state[k_ed("tipo", id_a)] = "Spare Parts"
    at.session_state[k_ed("min", id_a)] = 10.0
    _selecionar(at, ROTULO_B)

    assert at.selectbox(key=k_ed("un", id_b)).value == "CX"
    assert at.selectbox(key=k_ed("tipo", id_b)).value == "Consumivel"
    assert at.number_input(key=k_ed("min", id_b)).value == 99.0


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
