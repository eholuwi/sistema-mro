"""v3.4.0 — Receber por SC: começar pela SC/PO e receber todos os itens pendentes.

A UI itera `registrar_recebimento_sc` por item pendente (mesma função do fluxo por
material). Estes testes validam o padrão no nível de serviço: receber tudo fecha a SC;
receber parcial mantém aberta com o saldo residual correto.
"""

import database
from services import db_functions as F

CC = "21194 - ALMOXARIFADO"


def _abrir_sc(numero, itens):
    ok, msg = F.criar_sc(numero, "2026-01-01", itens, "")
    assert ok, msg
    conn = database.get_connection()
    sc_id = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero,)).fetchone()["id"]
    conn.close()
    return sc_id


def _status(sc_id):
    conn = database.get_connection()
    s = conn.execute("SELECT status FROM solicitacoes_compra WHERE id=?", (sc_id,)).fetchone()["status"]
    conn.close()
    return s


def test_receber_todos_itens_pendentes_fecha_sc(db, make_item):
    a = make_item("PN-A", estoque=0, minimo=5, lead=7)
    b = make_item("PN-B", estoque=0, minimo=5, lead=7)
    sc_id = _abrir_sc(
        "SC-REC-1",
        [
            {
                "item_id": a,
                "part_number": "PN-A",
                "nome_item": "A",
                "quantidade_solicitada": 4,
                "quantidade_pedido": 4,
            },
            {
                "item_id": b,
                "part_number": "PN-B",
                "nome_item": "B",
                "quantidade_solicitada": 6,
                "quantidade_pedido": 6,
            },
        ],
    )
    pend = [it for it in F.listar_itens_sc(sc_id) if (it.get("pendente") or 0) > 0]
    assert len(pend) == 2
    for it in pend:  # replica o loop da UI "Receber por SC"
        ok, msg = F.registrar_recebimento_sc(
            sc_id, it["id"], it["pendente"], CC, "Alm", "Alm", "Forn", "2026-01-10", "NF-1"
        )
        assert ok, msg
    assert [it for it in F.listar_itens_sc(sc_id) if (it.get("pendente") or 0) > 0] == []
    assert _status(sc_id) == "Recebido"


def test_recebimento_parcial_mantem_sc_aberta(db, make_item):
    a = make_item("PN-C", estoque=0, minimo=5, lead=7)
    sc_id = _abrir_sc(
        "SC-REC-2",
        [
            {
                "item_id": a,
                "part_number": "PN-C",
                "nome_item": "C",
                "quantidade_solicitada": 10,
                "quantidade_pedido": 10,
            },
        ],
    )
    it = F.listar_itens_sc(sc_id)[0]
    ok, msg = F.registrar_recebimento_sc(sc_id, it["id"], 4, CC, "Alm", "Alm", "Forn", "2026-01-10", "NF-1")
    assert ok, msg
    assert F.listar_itens_sc(sc_id)[0]["pendente"] == 6
    assert _status(sc_id) == "Parcial"
