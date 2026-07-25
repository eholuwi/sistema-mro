"""v2.2.0 — Fundação de Dados: guarda-chuva, estoque de segurança manual,
integridade do ledger e snapshots de estoque."""

from services import db_functions as F
import database

CC = "21106 - MANUTENÇÃO"


def _sc_aberta_com_saldo(item_id, numero_sc, saldo, status="Aguardando Aprovação"):
    """Cria uma SC com um item e saldo_residual definido (SQL direto)."""
    with database.transaction() as c:
        cur = c.execute(
            "INSERT INTO solicitacoes_compra (numero_sc,data_abertura,status) VALUES (?,?,?)",
            (numero_sc, "2026-01-01", status),
        )
        c.execute(
            """INSERT INTO itens_sc
               (sc_id,item_id,quantidade_solicitada,quantidade_pedido,saldo_residual,status_item)
               VALUES (?,?,?,?,?,'Aberto')""",
            (cur.lastrowid, item_id, saldo, saldo, saldo),
        )
    return cur.lastrowid


# ── Guarda-Chuva ──────────────────────────────────────────────────────────────


def test_guarda_chuva_soma_todas_scs_abertas(db, make_item):
    item_id = make_item("PN-GC")
    _sc_aberta_com_saldo(item_id, "SC-GC1", 10)
    _sc_aberta_com_saldo(item_id, "SC-GC2", 25)
    assert F.calcular_guarda_chuva(item_id) == 35


def test_guarda_chuva_ignora_sc_recebida_ou_cancelada(db, make_item):
    item_id = make_item("PN-GC2")
    _sc_aberta_com_saldo(item_id, "SC-OPEN", 10)
    _sc_aberta_com_saldo(item_id, "SC-REC", 99, status="Recebido")
    _sc_aberta_com_saldo(item_id, "SC-CANC", 50, status="Cancelado")
    assert F.calcular_guarda_chuva(item_id) == 10


# ── Estoque de Segurança manual ───────────────────────────────────────────────


def test_seguranca_manual_nao_e_sobrescrita_por_calculo(db, make_item):
    item_id = make_item("PN-SEG", estoque=100, minimo=10, lead=5)
    ok, _ = F.atualizar_item_inventario(item_id, {"estoque_seguranca": 42})
    assert ok
    # Uma saída dispara _recalcular_ruptura_by_pn (que antes sobrescrevia a segurança).
    F.registrar_movimentacao(item_id, "saida", 5, CC, "x", "x")
    it = F.buscar_item_por_id(item_id)
    assert it["estoque_seguranca"] == 42  # manual preservado
    assert it["estoque_seguranca_calculado"] is not None  # sugestão gravada à parte


# ── Integridade do ledger ─────────────────────────────────────────────────────


def test_saldo_inicial_gera_movimento(db, make_item):
    item_id = make_item("PN-LED", estoque=30)
    movs = F.listar_movimentacoes(item_id=item_id)
    assert len(movs) == 1
    assert movs[0]["tipo"] == "entrada"
    assert movs[0]["saldo_apos"] == 30
    assert "inicial" in (movs[0]["observacao"] or "").lower()


def test_item_sem_estoque_inicial_nao_gera_movimento(db, make_item):
    item_id = make_item("PN-LED0", estoque=0)
    assert F.listar_movimentacoes(item_id=item_id) == []


def test_edicao_de_saldo_via_salvar_item_gera_delta(db, make_item):
    item_id = make_item("PN-LED2", estoque=10)  # 1 mov inicial
    # Edita o saldo para 25 via salvar_item → gera movimento de ajuste de +15
    F.salvar_item(
        "PN-LED2",
        "Item",
        "",
        "UN",
        "Importante",
        "Spare Parts",
        "Improdutivo",
        "ARM-01",
        "",
        25,
        10,
        7,
        item_id=item_id,
    )
    movs = F.listar_movimentacoes(item_id=item_id)
    assert len(movs) == 2
    # (o timestamp pode empatar no mesmo segundo; localiza o ajuste pela observação)
    ajuste = [m for m in movs if "edição" in (m["observacao"] or "").lower()]
    assert len(ajuste) == 1
    assert ajuste[0]["tipo"] == "entrada"
    assert ajuste[0]["quantidade"] == 15
    assert ajuste[0]["saldo_apos"] == 25
    assert F.buscar_item_por_id(item_id)["estoque_atual"] == 25


# ── Snapshots de estoque ──────────────────────────────────────────────────────


def test_snapshot_idempotente_por_dia(db, make_item):
    make_item("PN-S1", estoque=10)
    make_item("PN-S2", estoque=0)
    assert F.tirar_snapshot_estoque() == 2  # 1 foto por item
    assert F.tirar_snapshot_estoque() == 0  # mesmo dia → no-op


def test_snapshot_valor_estoque_usa_preco_referencia(db, make_item):
    item_id = make_item("PN-S3", estoque=4)
    with database.transaction() as c:
        c.execute("UPDATE inventario SET preco_referencia=2.5 WHERE id=?", (item_id,))
    F.tirar_snapshot_estoque(data="2026-06-15")  # data fixa recente (dentro da retenção)
    with database.transaction() as c:
        row = c.execute(
            "SELECT estoque_atual, valor_estoque FROM estoque_snapshots WHERE item_id=? AND data='2026-06-15'",
            (item_id,),
        ).fetchone()
    assert row["estoque_atual"] == 4
    assert row["valor_estoque"] == 10.0  # 4 × 2.5
