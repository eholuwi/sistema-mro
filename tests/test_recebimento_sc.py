"""Fase 3 (DT-2): recebimento de SC. Caracteriza parcial/total/excesso (que
devem permanecer estaveis) e especifica a ATOMICIDADE alvo (rollback total em
falha), hoje impossivel pois itens_sc e commitado antes da movimentacao."""
import pytest
from services import db_functions as F

CC = "21194 - ALMOXARIFADO"


@pytest.fixture
def sc_aberta(db, make_item):
    item_id = make_item("PN-SC", estoque=0, minimo=5)
    ok, msg = F.criar_sc("SC-001", "2026-01-01",
        [{"item_id": item_id, "part_number": "PN-SC", "nome_item": "Item",
          "quantidade_solicitada": 10, "quantidade_pedido": 10}], "")
    assert ok, msg
    conn = db.get_connection()
    sc_id = conn.execute(
        "SELECT id FROM solicitacoes_compra WHERE numero_sc='SC-001'").fetchone()["id"]
    conn.close()
    item_sc_id = F.listar_itens_sc(sc_id)[0]["id"]
    return item_id, sc_id, item_sc_id


def test_recebimento_parcial(db, sc_aberta):
    item_id, sc_id, item_sc_id = sc_aberta
    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 4, CC,
                                         "Alm", "Alm", "Forn X", "2026-01-10", "NF-1")
    assert ok, msg
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 4
    it = F.listar_itens_sc(sc_id)[0]
    assert it["quantidade_recebida"] == 4
    assert it["saldo_residual"] == 6
    assert it["status_item"] == "Parcial"


def test_recebimento_total_fecha_sc(db, sc_aberta):
    item_id, sc_id, item_sc_id = sc_aberta
    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 10, CC,
                                         "Alm", "Alm", "Forn", "2026-01-10", "NF-2")
    assert ok, msg
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 10
    assert F.listar_itens_sc(sc_id)[0]["status_item"] == "Recebido"
    assert len(F.listar_scs(apenas_abertas=True)) == 0


def test_recebimento_excede_pendente_rejeita(db, sc_aberta):
    _, sc_id, item_sc_id = sc_aberta
    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 999, CC,
                                         "Alm", "Alm", "Forn", "2026-01-10", "NF")
    assert ok is False


def test_atomicidade_rollback_em_falha(db, sc_aberta, monkeypatch):
    """DT-2 resolvido: o recebimento roda numa transacao unica. Uma falha no meio
    (aqui, no recalculo de lead time, ja com itens_sc/movimentacao/inventario/status
    escritos mas nao commitados) deve causar rollback TOTAL."""
    item_id, sc_id, item_sc_id = sc_aberta

    conn = db.get_connection()
    status_antes = conn.execute(
        "SELECT status FROM solicitacoes_compra WHERE id=?", (sc_id,)).fetchone()["status"]
    conn.close()

    def boom(*a, **k):
        raise RuntimeError("falha simulada no meio da transacao de recebimento")

    monkeypatch.setattr(F, "_recalcular_lead_time_real", boom)
    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 4, CC,
                                         "Alm", "Alm", "Forn", "2026-01-10", "NF")
    assert ok is False  # falha reportada via rollback, nao propagada ao chamador

    # ALVO DT-2: rollback TOTAL -- nada persistido parcialmente
    assert F.listar_itens_sc(sc_id)[0]["quantidade_recebida"] == 0
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 0
    conn = db.get_connection()
    n_mov = conn.execute(
        "SELECT COUNT(*) AS n FROM movimentacoes WHERE item_id=?", (item_id,)).fetchone()["n"]
    status_depois = conn.execute(
        "SELECT status FROM solicitacoes_compra WHERE id=?", (sc_id,)).fetchone()["status"]
    conn.close()
    assert n_mov == 0                     # nenhuma movimentacao gravada
    assert status_depois == status_antes  # status da SC inalterado
