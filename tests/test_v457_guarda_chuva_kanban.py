"""v4.5.7 — Kanban FUNCIONAL do Guarda-Chuva (Ficha 360).

A UI (dialog por card) é coberta pelo smoke E2E. Aqui ficam as funções de serviço
testáveis: `atualizar_pedido_guarda_chuva` (edita metadados de 1 pedido SEM tocar o
ledger) e `obter_pedido_sc` (linha única com campos derivados), além da composição com
`registrar_recebimento_sc` (o único caminho que mexe em estoque/movimentações).
"""

import database
from services import db_functions as F

CC = "21194 - ALMOXARIFADO"


# ── Helpers ────────────────────────────────────────────────────────────────────
def _abrir_sc(numero, itens):
    ok, msg = F.criar_sc(numero, "2026-01-01", itens, "")
    assert ok, msg
    conn = database.get_connection()
    sc_id = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero,)).fetchone()["id"]
    conn.close()
    return sc_id


def _first_item_sc_id(sc_id):
    conn = database.get_connection()
    r = conn.execute("SELECT id FROM itens_sc WHERE sc_id=? ORDER BY id LIMIT 1", (sc_id,)).fetchone()
    conn.close()
    return r["id"]


def _col(sql, params):
    conn = database.get_connection()
    v = conn.execute(sql, params).fetchone()[0]
    conn.close()
    return v


def _estoque(item_id):
    return _col("SELECT estoque_atual FROM inventario WHERE id=?", (item_id,))


def _n_mov(item_id):
    return _col("SELECT COUNT(*) FROM movimentacoes WHERE item_id=?", (item_id,))


def _recebida(item_sc_id):
    return _col("SELECT quantidade_recebida FROM itens_sc WHERE id=?", (item_sc_id,))


def _sc_status(sc_id):
    return _col("SELECT status FROM solicitacoes_compra WHERE id=?", (sc_id,))


def _estagio(p):
    """Réplica da derivação de estágio de app._estagio, para asserção de reclassificação."""
    if (p.get("pendente") or 0) <= 0:
        return "Recebido"
    if p.get("documento_nf"):
        return "NF Emitida"
    if p.get("data_prev_nfe") or p.get("data_necessidade"):
        return "Aguardando Entrega"
    return "Pedido Colocado"


# ── obter_pedido_sc ──────────────────────────────────────────────────────────────
def test_obter_pedido_sc_campos_derivados(db, make_item):
    item = make_item("PN-OBT", estoque=0, minimo=5)
    sc_id = _abrir_sc("SC-OBT", [{"item_id": item, "quantidade_solicitada": 8, "quantidade_pedido": 8}])
    isc = _first_item_sc_id(sc_id)

    p = F.obter_pedido_sc(isc)
    assert p is not None
    assert p["item_sc_id"] == isc
    assert p["id"] == sc_id
    assert p["quantidade_negociada"] == 8
    assert p["pendente"] == 8
    assert p["documento_nf"] is None
    assert p["part_number"] == "PN-OBT"
    assert "unidade" in p


def test_obter_pedido_sc_inexistente(db):
    assert F.obter_pedido_sc(999999) is None
    assert F.obter_pedido_sc(None) is None


# ── atualizar_pedido_guarda_chuva: metadados ────────────────────────────────────
def test_atualizar_grava_metadados_e_recomputa_saldo(db, make_item):
    item = make_item("PN-META", estoque=0, minimo=5)
    sc_id = _abrir_sc("SC-META", [{"item_id": item, "quantidade_solicitada": 10, "quantidade_pedido": 10}])
    isc = _first_item_sc_id(sc_id)

    ok, msg = F.atualizar_pedido_guarda_chuva(
        isc,
        {
            "numero_po": "PO-123",
            "fornecedor_item": "Fornecedor X",
            "documento_nf": "NF-55",
            "data_prev_nfe": "2026-03-01",
            "data_necessidade": "2026-02-15",
            "quantidade_pedido": 12,
        },
    )
    assert ok, msg

    p = F.obter_pedido_sc(isc)
    assert p["po_item"] == "PO-123"
    assert p["fornecedor_item"] == "Fornecedor X"
    assert p["documento_nf"] == "NF-55"
    assert str(p["data_prev_nfe"]) == "2026-03-01"
    assert str(p["data_necessidade"]) == "2026-02-15"
    assert p["quantidade_negociada"] == 12
    assert p["pendente"] == 12  # recebida 0 → saldo = negociada
    assert p["status_item"] == "Aberto"


def test_editar_qtd_negociada_nao_toca_ledger(db, make_item):
    item = make_item("PN-LEDGER", estoque=100, minimo=5)
    sc_id = _abrir_sc("SC-LEDGER", [{"item_id": item, "quantidade_solicitada": 10, "quantidade_pedido": 10}])
    isc = _first_item_sc_id(sc_id)

    est0, nmov0, rec0 = _estoque(item), _n_mov(item), _recebida(isc)

    ok, msg = F.atualizar_pedido_guarda_chuva(isc, {"quantidade_pedido": 20})
    assert ok, msg

    # Metadado persistido…
    assert F.obter_pedido_sc(isc)["quantidade_negociada"] == 20
    # …mas o ledger e o recebido ficam INTACTOS.
    assert _estoque(item) == est0
    assert _n_mov(item) == nmov0
    assert _recebida(isc) == rec0


def test_move_estagios_via_edicao_e_limpar_nf_volta(db, make_item):
    item = make_item("PN-STAGE", estoque=0, minimo=5)
    sc_id = _abrir_sc("SC-STAGE", [{"item_id": item, "quantidade_solicitada": 10, "quantidade_pedido": 10}])
    isc = _first_item_sc_id(sc_id)

    assert _estagio(F.obter_pedido_sc(isc)) == "Pedido Colocado"

    ok, _ = F.atualizar_pedido_guarda_chuva(isc, {"data_prev_nfe": "2026-02-01"})
    assert ok
    assert _estagio(F.obter_pedido_sc(isc)) == "Aguardando Entrega"

    ok, _ = F.atualizar_pedido_guarda_chuva(isc, {"documento_nf": "NF-77"})
    assert ok
    assert _estagio(F.obter_pedido_sc(isc)) == "NF Emitida"

    # Limpar a NF (string vazia → NULL) volta o card para 'Aguardando Entrega'.
    ok, _ = F.atualizar_pedido_guarda_chuva(isc, {"documento_nf": ""})
    assert ok
    p = F.obter_pedido_sc(isc)
    assert p["documento_nf"] is None
    assert _estagio(p) == "Aguardando Entrega"


def test_negociada_menor_que_recebida_fecha_pedido_e_sc(db, make_item):
    item = make_item("PN-CLAMP", estoque=0, minimo=5)
    sc_id = _abrir_sc("SC-CLAMP", [{"item_id": item, "quantidade_solicitada": 10, "quantidade_pedido": 10}])
    isc = _first_item_sc_id(sc_id)

    # Recebe 4 de 10 (ledger).
    ok, msg = F.registrar_recebimento_sc(sc_id, isc, 4, CC, "Alm", "Alm", "Forn", "2026-01-10", "NF-1")
    assert ok, msg
    assert _sc_status(sc_id) == "Parcial"

    # Ajusta a negociada para 3 (< recebida 4) → saldo clampa a 0, pedido/SC fecham.
    ok, msg = F.atualizar_pedido_guarda_chuva(isc, {"quantidade_pedido": 3})
    assert ok, msg
    p = F.obter_pedido_sc(isc)
    assert p["pendente"] == 0
    assert p["status_item"] == "Recebido"
    assert _sc_status(sc_id) == "Recebido"


# ── Composição: metadados (sem ledger) + recebimento (com ledger) ────────────────
def test_composicao_metadados_mais_recebimento(db, make_item):
    item = make_item("PN-COMP", estoque=0, minimo=5)
    sc_id = _abrir_sc("SC-COMP", [{"item_id": item, "quantidade_solicitada": 5, "quantidade_pedido": 5}])
    isc = _first_item_sc_id(sc_id)

    # 1) Edita metadados (não mexe no estoque).
    ok, _ = F.atualizar_pedido_guarda_chuva(isc, {"numero_po": "PO-COMP", "data_prev_nfe": "2026-02-01"})
    assert ok
    nmov_antes = _n_mov(item)

    # 2) Recebe tudo (ledger).
    ok, msg = F.registrar_recebimento_sc(sc_id, isc, 5, CC, "Alm", "Alm", "Forn", "2026-01-10", "NF-9")
    assert ok, msg

    p = F.obter_pedido_sc(isc)
    assert p["po_item"] == "PO-COMP"  # metadado preservado após o recebimento
    assert p["pendente"] == 0
    assert p["status_item"] == "Recebido"
    assert _estagio(p) == "Recebido"
    assert _estoque(item) == 5  # 0 + 5 recebidos
    assert _n_mov(item) == nmov_antes + 1  # exatamente 1 entrada no ledger
    assert _sc_status(sc_id) == "Recebido"
