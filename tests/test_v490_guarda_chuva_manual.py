"""v4.9.0 — Guarda-Chuva MANUAL (Controle de SC).

Controle 100% manual e desacoplado das SCs importadas: tabela `guarda_chuva`, estágio
explícito/editável, saldo derivado (negociada − recebida). NÃO toca estoque/movimentacoes.
Cobre CRUD, recebimento parcial (abate saldo, fecha em 'Recebido'), a métrica
`saldo_total_por_material` (soma por fornecedor) e a idempotência da migração.
"""

import database
from services import db_functions as F


def _estoque(item_id):
    conn = database.get_connection()
    v = conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (item_id,)).fetchone()[0]
    conn.close()
    return v


def _n_mov(item_id):
    conn = database.get_connection()
    v = conn.execute("SELECT COUNT(*) FROM movimentacoes WHERE item_id=?", (item_id,)).fetchone()[0]
    conn.close()
    return v


# ── criar / listar ───────────────────────────────────────────────────────────


def test_criar_e_listar_guarda_chuva(db, make_item):
    item = make_item("PN-GC1", estoque=0, minimo=5)
    ok, gc_id = F.criar_guarda_chuva(
        item,
        "F001",
        fornecedor_nome="Fornecedor Um",
        qtd_negociada=100,
        preco_congelado=12.5,
        qtd_ideal_mes=20,
    )
    assert ok
    linhas = F.listar_guarda_chuva(item)
    assert len(linhas) == 1
    g = linhas[0]
    assert g["fornecedor_codigo"] == "F001"
    assert g["fornecedor_nome"] == "Fornecedor Um"
    assert g["qtd_negociada"] == 100
    assert g["qtd_recebida"] == 0
    assert g["saldo_residual"] == 100  # derivado
    assert g["estagio"] == "Pedido Colocado"
    assert g["part_number"] == "PN-GC1"  # join com inventario


def test_criar_exige_item_e_fornecedor(db, make_item):
    item = make_item("PN-GC-VAL", estoque=0, minimo=5)
    ok, _ = F.criar_guarda_chuva(None, "F001")
    assert not ok
    ok, _ = F.criar_guarda_chuva(item, "   ")  # código em branco
    assert not ok
    ok, _ = F.criar_guarda_chuva(item, "")
    assert not ok


# ── recebimento parcial (manual, sem ledger) ──────────────────────────────────


def test_recebimento_parcial_abate_saldo_sem_tocar_estoque(db, make_item):
    item = make_item("PN-GC2", estoque=50, minimo=5)
    est0, nmov0 = _estoque(item), _n_mov(item)
    ok, gc_id = F.criar_guarda_chuva(item, "F002", qtd_negociada=40)
    assert ok

    ok, _ = F.registrar_recebimento_guarda_chuva(gc_id, 15)
    assert ok
    g = F.obter_guarda_chuva(gc_id)
    assert g["qtd_recebida"] == 15
    assert g["saldo_residual"] == 25
    assert g["estagio"] == "Pedido Colocado"  # ainda não fechou
    # Controle manual: estoque e ledger INTACTOS.
    assert _estoque(item) == est0
    assert _n_mov(item) == nmov0


def test_recebimento_total_fecha_em_recebido_e_limita(db, make_item):
    item = make_item("PN-GC3", estoque=0, minimo=5)
    ok, gc_id = F.criar_guarda_chuva(item, "F003", qtd_negociada=30)
    assert ok
    # Recebe mais do que o negociado → limita ao negociado e fecha.
    ok, _ = F.registrar_recebimento_guarda_chuva(gc_id, 999)
    assert ok
    g = F.obter_guarda_chuva(gc_id)
    assert g["qtd_recebida"] == 30
    assert g["saldo_residual"] == 0
    assert g["estagio"] == "Recebido"


def test_recebimento_qtd_invalida(db, make_item):
    item = make_item("PN-GC3B", estoque=0, minimo=5)
    ok, gc_id = F.criar_guarda_chuva(item, "F003B", qtd_negociada=10)
    assert ok
    ok, _ = F.registrar_recebimento_guarda_chuva(gc_id, 0)
    assert not ok
    ok, _ = F.registrar_recebimento_guarda_chuva(gc_id, -5)
    assert not ok


# ── atualizar ────────────────────────────────────────────────────────────────


def test_atualizar_campos_e_estagio(db, make_item):
    item = make_item("PN-GC4", estoque=0, minimo=5)
    ok, gc_id = F.criar_guarda_chuva(item, "F004", qtd_negociada=20)
    assert ok
    ok, _ = F.atualizar_guarda_chuva(
        gc_id,
        {
            "fornecedor_codigo": "F004-B",
            "qtd_negociada": 35,
            "estagio": "Aguardando Entrega",
            "numero_po": "PO-9",
            "observacao": "teste",
        },
    )
    assert ok
    g = F.obter_guarda_chuva(gc_id)
    assert g["fornecedor_codigo"] == "F004-B"
    assert g["qtd_negociada"] == 35
    assert g["estagio"] == "Aguardando Entrega"
    assert g["numero_po"] == "PO-9"
    assert g["saldo_residual"] == 35


def test_atualizar_estagio_invalido_mantem_atual(db, make_item):
    item = make_item("PN-GC5", estoque=0, minimo=5)
    ok, gc_id = F.criar_guarda_chuva(item, "F005", qtd_negociada=20)
    assert ok
    ok, _ = F.atualizar_guarda_chuva(gc_id, {"estagio": "Inexistente"})
    assert ok
    assert F.obter_guarda_chuva(gc_id)["estagio"] == "Pedido Colocado"


def test_atualizar_recebida_maior_que_negociada_coage_recebido(db, make_item):
    item = make_item("PN-GC6", estoque=0, minimo=5)
    ok, gc_id = F.criar_guarda_chuva(item, "F006", qtd_negociada=10)
    assert ok
    # Sem setar estágio à mão: recebida >= negociada força 'Recebido'.
    ok, _ = F.atualizar_guarda_chuva(gc_id, {"qtd_recebida": 10})
    assert ok
    assert F.obter_guarda_chuva(gc_id)["estagio"] == "Recebido"


# ── saldo total por material (métrica) ────────────────────────────────────────


def test_saldo_total_por_material_soma_fornecedores(db, make_item):
    item = make_item("PN-GC7", estoque=0, minimo=5)
    F.criar_guarda_chuva(item, "FA", qtd_negociada=100)
    ok, gc_b = F.criar_guarda_chuva(item, "FB", qtd_negociada=50)
    assert ok
    assert F.saldo_total_por_material(item) == 150.0
    # Recebe 30 no fornecedor B → total cai para 120.
    F.registrar_recebimento_guarda_chuva(gc_b, 30)
    assert F.saldo_total_por_material(item) == 120.0
    assert F.saldo_total_por_material(None) == 0.0


# ── remover ──────────────────────────────────────────────────────────────────


def test_remover_guarda_chuva(db, make_item):
    item = make_item("PN-GC8", estoque=0, minimo=5)
    ok, gc_id = F.criar_guarda_chuva(item, "F008", qtd_negociada=10)
    assert ok
    ok, _ = F.remover_guarda_chuva(gc_id)
    assert ok
    assert F.obter_guarda_chuva(gc_id) is None
    assert F.listar_guarda_chuva(item) == []


# ── migração idempotente ──────────────────────────────────────────────────────


def test_criar_banco_idempotente_mantem_guarda_chuva(db, make_item):
    item = make_item("PN-GC9", estoque=0, minimo=5)
    ok, gc_id = F.criar_guarda_chuva(item, "F009", qtd_negociada=10)
    assert ok
    database.criar_banco()  # roda de novo: CREATE TABLE IF NOT EXISTS não apaga dados
    assert F.obter_guarda_chuva(gc_id) is not None
