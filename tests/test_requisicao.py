"""Requisição Digital (v4.7.0): a CRIAÇÃO não baixa estoque — a requisição nasce
'Aberta' e vai para a fila. A baixa acontece só na ENTREGA (`entregar_requisicao`),
o que permite atendimento parcial e em lote (o jeito do Juan). Este arquivo cobre o
núcleo criação+entrega; o fluxo estendido (adicionar item, cancelar, SESMT, fila)
está em test_v470_requisicao_digital.py.
"""
import pytest
from services import db_functions as F

CC = "21106 - MANUTENÇÃO"


def _req_id(db, numero):
    conn = db.get_connection()
    row = conn.execute("SELECT id FROM requisicoes WHERE numero_requisicao=?", (numero,)).fetchone()
    conn.close()
    return row["id"]


def _status(db, req_id):
    conn = db.get_connection()
    row = conn.execute("SELECT status FROM requisicoes WHERE id=?", (req_id,)).fetchone()
    conn.close()
    return row["status"]


def _criar(item_id, qtd=10):
    return F.criar_requisicao("Manut", "Joao", CC, "", "", False, [], False, "",
                              [{"item_id": item_id, "quantidade_solicitada": qtd}])


def test_criacao_nao_baixa_estoque(db, make_item):
    item_id = make_item("PN-REQ2", estoque=100, minimo=10)
    ok, num = _criar(item_id, 10)
    assert ok, num
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 100  # criação não toca estoque
    assert _status(db, _req_id(db, num)) == "Aberta"


def test_requisicao_sem_itens_rejeita(db):
    ok, msg = F.criar_requisicao("S", "E", CC, "", "", False, [], False, "", [])
    assert ok is False


def test_entrega_total_baixa_e_status_entregue(db, make_item):
    item_id = make_item("PN-REQ3", estoque=100)
    ok, num = _criar(item_id, 10)
    rid = _req_id(db, num)
    it = F.listar_itens_requisicao(rid)[0]
    ok, status = F.entregar_requisicao(rid, [{"item_req_id": it["id"], "quantidade": 10}],
                                       "Gestor", "Chefe")
    assert ok, status
    assert status == "Entregue"
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 90  # baixa 10 (entregue)


def test_entrega_parcial_status_parcial_e_acumula(db, make_item):
    item_id = make_item("PN-REQ4", estoque=100)
    ok, num = _criar(item_id, 10)
    rid = _req_id(db, num)
    it_id = F.listar_itens_requisicao(rid)[0]["id"]

    ok, status = F.entregar_requisicao(rid, [{"item_req_id": it_id, "quantidade": 4}],
                                       "Gestor", "Chefe")
    assert ok and status == "Parcial"
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 96  # baixa só do entregue

    ok, status = F.entregar_requisicao(rid, [{"item_req_id": it_id, "quantidade": 6}],
                                       "Gestor", "Chefe")
    assert ok and status == "Entregue"
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 90  # 4 + 6 acumulados


def test_entrega_sem_autorizador_rejeita(db, make_item):
    item_id = make_item("PN-REQ5", estoque=100)
    ok, num = _criar(item_id, 5)
    rid = _req_id(db, num)
    it_id = F.listar_itens_requisicao(rid)[0]["id"]
    ok, msg = F.entregar_requisicao(rid, [{"item_req_id": it_id, "quantidade": 5}], "Gestor", "")
    assert ok is False
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 100  # nada baixado


def test_entrega_estoque_insuficiente_faz_rollback(db, make_item):
    item_id = make_item("PN-REQ6", estoque=3)
    ok, num = _criar(item_id, 5)
    rid = _req_id(db, num)
    it_id = F.listar_itens_requisicao(rid)[0]["id"]
    ok, msg = F.entregar_requisicao(rid, [{"item_req_id": it_id, "quantidade": 5}], "Gestor", "Chefe")
    assert ok is False
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 3  # rollback preservou
    assert _status(db, rid) == "Aberta"


def test_entrega_multiplos_itens_rollback_atomico(db, make_item):
    a = make_item("PN-MR-A", estoque=100)
    b = make_item("PN-MR-B", estoque=1)  # saldo insuficiente -> aborta a entrega inteira
    ok, num = F.criar_requisicao("Manut", "Joao", CC, "", "", False, [], False, "",
        [{"item_id": a, "quantidade_solicitada": 10},
         {"item_id": b, "quantidade_solicitada": 5}])
    rid = _req_id(db, num)
    itens = F.listar_itens_requisicao(rid)
    ent = [{"item_req_id": it["id"], "quantidade": 10 if it["item_id"] == a else 5} for it in itens]
    ok, msg = F.entregar_requisicao(rid, ent, "Gestor", "Chefe")
    assert ok is False
    assert F.buscar_item_por_id(a)["estoque_atual"] == 100  # item A não pode ter sido baixado
