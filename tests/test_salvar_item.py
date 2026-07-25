"""Fase 5 (T-01): cobertura de bordas de salvar_item.

O caminho feliz basico ja e exercitado implicitamente pela fixture make_item
(que usa salvar_item). Aqui cobrimos as bordas: INSERT com part_number
duplicado, caminho UPDATE (com item_id) e o recalculo de ruptura.
"""

from services import db_functions as F
from services.constants import PREVISAO_RUPTURA_SEM_RISCO


def _salvar(part_number, nome="Item", estoque=100, minimo=10, lead=7, item_id=None):
    return F.salvar_item(
        part_number,
        nome,
        "",
        "UN",
        "Importante",
        "Spare Parts",
        "Improdutivo",
        "ARM-01",
        "",
        estoque,
        minimo,
        lead,
        item_id,
    )


def test_insert_cria_item(db):
    ok, msg = _salvar("PN-NEW")
    assert ok, msg
    assert (
        F.buscar_item_por_id(next(i["id"] for i in F.listar_inventario() if i["part_number"] == "PN-NEW"))[
            "nome_item"
        ]
        == "Item"
    )


def test_part_number_duplicado_rejeita(db, make_item):
    make_item("PN-DUP")
    ok, msg = _salvar("PN-DUP")  # INSERT (item_id=None) com PN existente
    assert ok is False
    assert "existe" in msg.lower()


def test_update_altera_campos(db, make_item):
    item_id = make_item("PN-EDIT", estoque=100)
    ok, msg = _salvar("PN-EDIT", nome="Nome Novo", estoque=55, item_id=item_id)
    assert ok, msg
    item = F.buscar_item_por_id(item_id)
    assert item["nome_item"] == "Nome Novo"
    assert item["estoque_atual"] == 55


def test_salvar_recalcula_ruptura_sem_consumo(db, make_item):
    item_id = make_item("PN-RUP", estoque=100)
    item = F.buscar_item_por_id(item_id)
    # consumo_medio_diario == 0 -> ruptura assume a sentinela "sem risco"
    assert item["previsao_ruptura_dias"] == PREVISAO_RUPTURA_SEM_RISCO
