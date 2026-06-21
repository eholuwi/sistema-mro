"""Fase 2 (DT-6): comportamento de baixa de estoque em requisicoes.

Contem um teste de CARACTERIZACAO marcado com `fase1_baseline`: ele documenta o
BUG ATUAL (baixa pela quantidade_solicitada, ignorando a atendida) e DEVE SER
REMOVIDO durante a Fase 2, quando o teste-alvo `test_alvo_baixa_pela_atendida`
(hoje xfail) passar a valer."""
import pytest
from services import db_functions as F

CC = "21106 - MANUTENÇÃO"


def test_alvo_baixa_pela_atendida(db, make_item):
    item_id = make_item("PN-REQ2", estoque=100, minimo=10)
    itens = [{"item_id": item_id, "part_number": "PN-REQ2",
              "quantidade_solicitada": 10, "quantidade_atendida": 4}]
    ok, num = F.criar_requisicao("Manut", "Joao", CC, "Gestor", "Chefe",
                                 False, [], False, "", itens)
    assert ok, num
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 96  # baixa 4 (atendida)


def test_estoque_insuficiente_faz_rollback(db, make_item):
    item_id = make_item("PN-X", estoque=3, minimo=1)
    itens = [{"item_id": item_id, "part_number": "PN-X",
              "quantidade_solicitada": 5, "quantidade_atendida": 5}]
    ok, msg = F.criar_requisicao("S", "E", CC, "Gestor", "N",
                                 False, [], False, "", itens)
    assert ok is False
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 3  # rollback preservou


# --- Fase 5 (T-01): ampliacao de cobertura ---

def test_requisicao_sem_itens_rejeita(db):
    ok, msg = F.criar_requisicao("S", "E", CC, "Gestor", "N",
                                 False, [], False, "", [])
    assert ok is False


def test_requisicao_multiplos_itens_baixa_cada_um(db, make_item):
    a = make_item("PN-MR-A", estoque=100)
    b = make_item("PN-MR-B", estoque=50)
    itens = [
        {"item_id": a, "part_number": "PN-MR-A",
         "quantidade_solicitada": 10, "quantidade_atendida": 10},
        {"item_id": b, "part_number": "PN-MR-B",
         "quantidade_solicitada": 5, "quantidade_atendida": 5},
    ]
    ok, num = F.criar_requisicao("Manut", "Joao", CC, "Gestor", "Chefe",
                                 False, [], False, "", itens)
    assert ok, num
    assert F.buscar_item_por_id(a)["estoque_atual"] == 90
    assert F.buscar_item_por_id(b)["estoque_atual"] == 45


def test_requisicao_rollback_atomico_entre_itens(db, make_item):
    a = make_item("PN-MR-C", estoque=100)
    b = make_item("PN-MR-D", estoque=1)  # saldo insuficiente -> aborta tudo
    itens = [
        {"item_id": a, "part_number": "PN-MR-C",
         "quantidade_solicitada": 10, "quantidade_atendida": 10},
        {"item_id": b, "part_number": "PN-MR-D",
         "quantidade_solicitada": 5, "quantidade_atendida": 5},
    ]
    ok, msg = F.criar_requisicao("Manut", "Joao", CC, "Gestor", "Chefe",
                                 False, [], False, "", itens)
    assert ok is False
    # rollback: o item A (processado antes da falha) nao pode ter sido baixado
    assert F.buscar_item_por_id(a)["estoque_atual"] == 100
