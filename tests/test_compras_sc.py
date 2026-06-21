"""Fase 5 (T-01): cobertura de comportamento de criar_sc e atualizar_sc.

criar_sc e um upsert por numero_sc (numero repetido ATUALIZA, nao falha).
atualizar_sc tem logica de status; status invalido viola o CHECK do schema e
deve sofrer rollback. Todos os testes usam banco isolado via fixture `db`.
"""
from services import db_functions as F


def _conta_scs(db, numero=None):
    conn = db.get_connection()
    if numero:
        n = conn.execute(
            "SELECT COUNT(*) c FROM solicitacoes_compra WHERE numero_sc=?",
            (numero,),
        ).fetchone()["c"]
    else:
        n = conn.execute("SELECT COUNT(*) c FROM solicitacoes_compra").fetchone()["c"]
    conn.close()
    return n


def _conta_itens_sc(db, sc_id):
    conn = db.get_connection()
    n = conn.execute(
        "SELECT COUNT(*) c FROM itens_sc WHERE sc_id=?", (sc_id,)
    ).fetchone()["c"]
    conn.close()
    return n


def _status_sc(db, sc_id):
    conn = db.get_connection()
    row = conn.execute(
        "SELECT status FROM solicitacoes_compra WHERE id=?", (sc_id,)
    ).fetchone()
    conn.close()
    return row["status"] if row else None


# ---------- criar_sc ----------

def test_criar_sc_cria_sc_e_item(db, make_item):
    item_id = make_item("PN-SC1")
    ok, msg = F.criar_sc("SC-1", "2026-01-01",
                         [{"item_id": item_id, "quantidade_solicitada": 10}])
    assert ok, msg
    assert _conta_scs(db, "SC-1") == 1
    conn = db.get_connection()
    sc_id = conn.execute(
        "SELECT id FROM solicitacoes_compra WHERE numero_sc='SC-1'"
    ).fetchone()["id"]
    conn.close()
    assert _conta_itens_sc(db, sc_id) == 1


def test_criar_sc_sem_itens_rejeita(db):
    ok, msg = F.criar_sc("SC-VAZIA", "2026-01-01", [])
    assert ok is False
    assert _conta_scs(db, "SC-VAZIA") == 0


def test_criar_sc_numero_repetido_faz_upsert(db, make_item):
    item_id = make_item("PN-SC2")
    F.criar_sc("SC-2", "2026-01-01",
               [{"item_id": item_id, "quantidade_solicitada": 10}])
    ok, msg = F.criar_sc("SC-2", "2026-01-01",
                         [{"item_id": item_id, "quantidade_solicitada": 10}])
    assert ok, msg
    assert _conta_scs(db, "SC-2") == 1  # upsert: nao duplica a SC


def test_criar_sc_item_inexistente_faz_rollback(db):
    antes = _conta_scs(db)
    ok, msg = F.criar_sc("SC-BAD", "2026-01-01",
                         [{"item_id": 99999, "quantidade_solicitada": 5}])
    assert ok is False
    assert _conta_scs(db) == antes  # rollback: nenhuma SC persistida


# ---------- atualizar_sc ----------

def test_atualizar_sc_altera_status(db, make_sc):
    sc_id = make_sc(numero_sc="SC-UP1")
    ok, msg = F.atualizar_sc(sc_id, status="Cancelado")
    assert ok, msg
    assert _status_sc(db, sc_id) == "Cancelado"


def test_atualizar_sc_status_invalido_faz_rollback(db, make_sc):
    sc_id = make_sc(numero_sc="SC-UP2")
    original = _status_sc(db, sc_id)
    ok, msg = F.atualizar_sc(sc_id, status="StatusInexistente")
    assert ok is False
    assert _status_sc(db, sc_id) == original  # rollback preservou o status


def test_atualizar_sc_inexistente_nao_quebra(db):
    # Comportamento real: UPDATE em sc_id inexistente e no-op silencioso e
    # retorna sucesso, sem efeito colateral nem excecao.
    ok, msg = F.atualizar_sc(99999, status="Cancelado")
    assert ok is True
    assert _status_sc(db, 99999) is None
