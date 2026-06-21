"""Fase 0 (cobertura central): caracteriza listar_inventario(), que monta
status_material, estoque_em_transito, estoque_maximo e integra
calcular_status_inventario(). Deve permanecer verde nas Fases 1 e 3
(refatoracoes sem mudanca de comportamento)."""
from services import db_functions as F


def _item(itens, pn):
    return next(i for i in itens if i["part_number"] == pn)


def test_status_material_ok_e_estoque_maximo(db, make_item):
    make_item("PN-OK", estoque=100, minimo=10)
    item = _item(F.listar_inventario(), "PN-OK")
    assert "OK" in item["status_material"]
    assert item["estoque_maximo"] == 20            # regra atual: minimo * 2


def test_status_material_comprar(db, make_item):
    make_item("PN-LOW", estoque=5, minimo=10)
    item = _item(F.listar_inventario(), "PN-LOW")
    assert "COMPRAR" in item["status_material"]


def test_status_material_atencao(db, make_item):
    make_item("PN-AT", estoque=11, minimo=10)
    item = _item(F.listar_inventario(), "PN-AT")
    assert "ATENÇÃO" in item["status_material"]


def test_sem_sc_status_e_transito_zero(db, make_item):
    make_item("PN-NOSC", estoque=50, minimo=10)
    item = _item(F.listar_inventario(), "PN-NOSC")
    assert item["status_sc"] == "Sem SC"
    assert item["estoque_em_transito"] == 0


def test_estoque_em_transito_reflete_saldo_da_sc(db, make_item):
    item_id = make_item("PN-SC", estoque=0, minimo=5)
    ok, msg = F.criar_sc("SC-T", "2026-01-01",
        [{"item_id": item_id, "part_number": "PN-SC", "nome_item": "Item",
          "quantidade_solicitada": 10, "quantidade_pedido": 10}], "")
    assert ok, msg
    item = _item(F.listar_inventario(), "PN-SC")
    assert item["estoque_em_transito"] == 10


def test_integracao_com_calcular_status(db, make_item):
    make_item("PN-A", estoque=100, minimo=10)
    make_item("PN-B", estoque=5, minimo=10)
    make_item("PN-C", estoque=11, minimo=10)
    for item in F.listar_inventario():
        esperado = F.calcular_status_inventario(
            item["estoque_atual"], item["estoque_minimo"], item["estoque_em_transito"])
        assert item["status_material"] == esperado
