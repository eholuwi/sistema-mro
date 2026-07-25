"""Fase 5 (T-01): cobertura de registrar_movimentacao.

Foco no efeito deterministico sobre estoque_atual (entrada soma, saida/devolucao
ajustam), na rejeicao por estoque insuficiente e no item inexistente. Recalculo
de consumo/ruptura e tratado como efeito secundario (depende de janela temporal).
"""

from services import db_functions as F

CC = "21106 - MANUTENÇÃO"


def test_entrada_soma_estoque(db, make_item):
    item_id = make_item("PN-MOV1", estoque=100)
    ok, msg = F.registrar_movimentacao(item_id, "entrada", 50, CC, "Joao", "Joao")
    assert ok, msg
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 150


def test_saida_subtrai_estoque(db, make_item):
    item_id = make_item("PN-MOV2", estoque=100)
    ok, msg = F.registrar_movimentacao(item_id, "saida", 30, CC, "Joao", "Joao")
    assert ok, msg
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 70


def test_devolucao_soma_estoque(db, make_item):
    item_id = make_item("PN-MOV3", estoque=100)
    ok, msg = F.registrar_movimentacao(item_id, "devolucao", 20, CC, "Joao", "Joao")
    assert ok, msg
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 120


def test_saida_insuficiente_rejeita_sem_alterar(db, make_item):
    item_id = make_item("PN-MOV4", estoque=100)
    ok, msg = F.registrar_movimentacao(item_id, "saida", 200, CC, "Joao", "Joao")
    assert ok is False
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 100  # intacto


def test_item_inexistente_rejeita(db):
    ok, msg = F.registrar_movimentacao(99999, "entrada", 10, CC, "Joao", "Joao")
    assert ok is False
    assert "encontrado" in msg.lower()
