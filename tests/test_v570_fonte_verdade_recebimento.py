"""v5.7.0 — O MRO é a fonte de verdade do recebimento (achado nº1 do `docs/prompt.md`).

Contexto do bug: `itens_sc.quantidade_recebida` era sobrescrita com a "Qtd.Entregue" do
Protheus a cada import (`importar_solicitacoes_protheus`, `ingerir_scm`) e a cada edição
manual (`criar_sc`, `atualizar_sc`). Um recebimento parcial conferido na doca — 4 de 10 —
era apagado na reimportação seguinte e o pendente saltava de volta para 10 (ou zerava, se
o ERP declarasse a entrega total), sem deixar rastro. A v5.6.0 corrigiu a UI do parcial;
o dado seguia sendo destruído pela porta dos fundos.

A partir daqui `quantidade_recebida` só é escrita por `registrar_recebimento_sc` — o que o
`changelog/4.5.7.md:27` já declarava e nunca foi verdade — e o número do ERP vive na coluna
espelho `quantidade_recebida_protheus`, que não entra no cálculo do saldo.
"""

import sqlite3

import pytest

from services import db_functions as F
from ui.componentes.status import divergencia_recebimento

CC = "21194 - ALMOXARIFADO"

# Colunas do Relatório de SCs (Protheus) usadas por `importar_solicitacoes_protheus`.
COLS_IMPORT = [
    "Numero da Solicitacao",
    "Solicitante",
    "Produto",
    "Quantidade",
    "Quantidade.1",
    "Qtd.Entregue",
    "Status",
]


@pytest.fixture
def sc_parcial(db, make_item):
    """SC de 10 unidades com 4 já recebidas pelo MRO (parcial conferido na doca)."""
    item_id = make_item("PN-VERDADE", estoque=0, minimo=5)
    ok, msg = F.criar_sc(
        "SC-VERDADE-1",
        "2026-01-01",
        [{"item_id": item_id, "quantidade_solicitada": 10, "quantidade_pedido": 10}],
    )
    assert ok, msg
    conn = db.get_connection()
    sc_id = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc='SC-VERDADE-1'").fetchone()["id"]
    conn.close()
    item_sc_id = F.listar_itens_sc(sc_id)[0]["id"]
    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 4, CC, "Alm", "Alm", "Forn X", "2026-01-10")
    assert ok, msg
    return {"sc_id": sc_id, "item_sc_id": item_sc_id, "item_id": item_id}


def _linha(sc_id):
    return F.listar_itens_sc(sc_id)[0]


# ── Import do Relatório de SCs ────────────────────────────────────────────────


def test_parcial_sobrevive_a_reimportacao(db, sc_parcial, xlsx_factory):
    """O caso que motivou o CP1: o Protheus declara 10 entregues, o MRO conferiu 4.

    Antes, o import gravava 10 em `quantidade_recebida`, o saldo ia a zero e as 6 unidades
    que nunca chegaram desapareciam do pendente."""
    rows = [["SC-VERDADE-1", "Jasiva Lopes", "PN-VERDADE", 10, 10, 10, "Pedido"]]
    ok, stats = F.importar_solicitacoes_protheus(xlsx_factory(rows, COLS_IMPORT), "reimport.xlsx")
    assert ok, stats

    it = _linha(sc_parcial["sc_id"])
    assert it["quantidade_recebida"] == 4, "o recebimento do MRO não pode ser sobrescrito pelo ERP"
    assert it["quantidade_recebida_protheus"] == 10, "o número do ERP tem de ficar visível"
    assert it["pendente"] == 6, "o saldo segue o MRO — 6 unidades ainda não chegaram"
    assert it["status_item"] == "Parcial"


def test_protheus_maior_nao_altera_o_saldo_nem_o_estoque(db, sc_parcial, xlsx_factory):
    """A reimportação é leitura: não pode mexer no estoque nem no ledger."""
    conn = db.get_connection()
    estoque_antes = conn.execute(
        "SELECT estoque_atual FROM inventario WHERE id=?", (sc_parcial["item_id"],)
    ).fetchone()["estoque_atual"]
    movs_antes = conn.execute("SELECT COUNT(*) AS n FROM movimentacoes").fetchone()["n"]
    conn.close()

    rows = [["SC-VERDADE-1", "Jasiva Lopes", "PN-VERDADE", 10, 10, 9, "Pedido"]]
    ok, stats = F.importar_solicitacoes_protheus(xlsx_factory(rows, COLS_IMPORT), "reimport.xlsx")
    assert ok, stats

    conn = db.get_connection()
    estoque_depois = conn.execute(
        "SELECT estoque_atual FROM inventario WHERE id=?", (sc_parcial["item_id"],)
    ).fetchone()["estoque_atual"]
    movs_depois = conn.execute("SELECT COUNT(*) AS n FROM movimentacoes").fetchone()["n"]
    conn.close()
    assert estoque_depois == estoque_antes
    assert movs_depois == movs_antes
    assert _linha(sc_parcial["sc_id"])["pendente"] == 6


def test_item_novo_nasce_com_o_valor_do_protheus(db, make_item, xlsx_factory):
    """Linha que ainda não existe não tem o que preservar: o ERP inicializa as duas colunas."""
    make_item("PN-NOVO", estoque=0, minimo=5)
    rows = [["SC-NOVA-1", "Jasiva Lopes", "PN-NOVO", 10, 10, 3, "Pedido"]]
    ok, stats = F.importar_solicitacoes_protheus(xlsx_factory(rows, COLS_IMPORT), "novo.xlsx")
    assert ok, stats

    conn = db.get_connection()
    sc_id = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc='SC-NOVA-1'").fetchone()["id"]
    conn.close()
    it = _linha(sc_id)
    assert it["quantidade_recebida"] == 3
    assert it["quantidade_recebida_protheus"] == 3
    assert it["pendente"] == 7
    assert it["status_item"] == "Parcial"


def test_recebimento_posterior_ao_import_continua_partindo_do_valor_do_mro(db, sc_parcial, xlsx_factory):
    """Depois de um import que declarava 10, receber as 6 restantes ainda tem de fechar em 10
    — e não ser recusado por 'excede o pendente'."""
    rows = [["SC-VERDADE-1", "Jasiva Lopes", "PN-VERDADE", 10, 10, 10, "Pedido"]]
    ok, stats = F.importar_solicitacoes_protheus(xlsx_factory(rows, COLS_IMPORT), "reimport.xlsx")
    assert ok, stats

    ok, msg = F.registrar_recebimento_sc(
        sc_parcial["sc_id"], sc_parcial["item_sc_id"], 6, CC, "Alm", "Alm", "Forn X", "2026-01-20"
    )
    assert ok, msg
    it = _linha(sc_parcial["sc_id"])
    assert it["quantidade_recebida"] == 10
    assert it["pendente"] == 0
    assert it["status_item"] == "Recebido"


# ── Caminhos manuais (Controle de SC) ─────────────────────────────────────────


def test_criar_sc_sobre_item_existente_nao_reescreve_o_recebimento(db, sc_parcial):
    """`criar_sc` também faz upsert: reenviar a SC com 'quantidade_recebida' do ERP não
    pode apagar o parcial do MRO."""
    ok, msg = F.criar_sc(
        "SC-VERDADE-1",
        "2026-01-01",
        [
            {
                "item_id": sc_parcial["item_id"],
                "quantidade_solicitada": 10,
                "quantidade_pedido": 10,
                "quantidade_recebida": 10,
            }
        ],
    )
    assert ok, msg
    it = _linha(sc_parcial["sc_id"])
    assert it["quantidade_recebida"] == 4
    assert it["quantidade_recebida_protheus"] == 10
    assert it["pendente"] == 6


def test_atualizar_sc_deriva_o_saldo_do_banco_e_nao_do_payload(db, sc_parcial):
    """A tela devolve o número que leu; o saldo não pode ficar à mercê do chamador."""
    ok, msg = F.atualizar_sc(
        sc_parcial["sc_id"],
        itens=[
            {
                "item_sc_id": sc_parcial["item_sc_id"],
                "quantidade_solicitada": 10,
                "quantidade_pedido": 10,
                "quantidade_recebida": 10,  # payload mentiroso
            }
        ],
    )
    assert ok, msg
    it = _linha(sc_parcial["sc_id"])
    assert it["quantidade_recebida"] == 4
    assert it["pendente"] == 6, "o saldo sai de itens_sc.quantidade_recebida, não do payload"
    assert it["status_item"] == "Parcial"


def test_atualizar_sc_recalcula_o_saldo_quando_a_negociada_muda(db, sc_parcial):
    """Regressão do comportamento legítimo: editar a quantidade negociada continua
    reabrindo o saldo, agora contra o recebimento real (12 − 4 = 8)."""
    ok, msg = F.atualizar_sc(
        sc_parcial["sc_id"],
        itens=[
            {
                "item_sc_id": sc_parcial["item_sc_id"],
                "quantidade_solicitada": 10,
                "quantidade_pedido": 12,
            }
        ],
    )
    assert ok, msg
    it = _linha(sc_parcial["sc_id"])
    assert it["pendente"] == 8
    assert it["quantidade_recebida"] == 4


# ── Sinal de divergência (UI) ─────────────────────────────────────────────────


def test_divergencia_so_aparece_quando_o_erp_declara_mais():
    assert divergencia_recebimento({"quantidade_recebida": 4, "quantidade_recebida_protheus": 10})
    # Legado (sem espelho) e valores iguais não podem gerar alarme falso.
    assert divergencia_recebimento({"quantidade_recebida": 4, "quantidade_recebida_protheus": None}) is None
    assert divergencia_recebimento({"quantidade_recebida": 4, "quantidade_recebida_protheus": 4}) is None
    # MRO à frente do ERP (recebeu antes de o ERP registrar) não é divergência a sinalizar.
    assert divergencia_recebimento({"quantidade_recebida": 10, "quantidade_recebida_protheus": 4}) is None
    assert divergencia_recebimento(None) is None


def test_mensagem_de_divergencia_traz_os_dois_numeros():
    msg = divergencia_recebimento({"quantidade_recebida": 4, "quantidade_recebida_protheus": 10})
    assert "10" in msg and "4" in msg


# ── Migração ──────────────────────────────────────────────────────────────────


def test_migracao_idempotente_e_preserva_os_dados(db, sc_parcial):
    """`criar_banco()` roda a cada boot do app: a migração precisa aguentar N execuções."""
    db.criar_banco()
    db.criar_banco()
    it = _linha(sc_parcial["sc_id"])
    assert it["quantidade_recebida"] == 4
    assert it["pendente"] == 6

    conn = db.get_connection()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(itens_sc)")]
    conn.close()
    assert cols.count("quantidade_recebida_protheus") == 1


def test_migracao_e_aditiva_e_reversivel(db, sc_parcial):
    """Rollback: derrubar a coluna nova devolve o schema anterior com os dados intactos —
    a migração não reescreve nada de `quantidade_recebida` (regra nº4 do projeto)."""
    conn = db.get_connection()
    try:
        conn.execute("ALTER TABLE itens_sc DROP COLUMN quantidade_recebida_protheus")
        conn.commit()
    except sqlite3.OperationalError as e:  # SQLite < 3.35 não tem DROP COLUMN
        conn.close()
        pytest.skip(f"DROP COLUMN indisponível nesta versão do SQLite: {e}")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(itens_sc)")]
    assert "quantidade_recebida_protheus" not in cols
    linha = conn.execute("SELECT quantidade_recebida, saldo_residual FROM itens_sc").fetchone()
    assert linha["quantidade_recebida"] == 4
    assert linha["saldo_residual"] == 6
    conn.close()

    # E a migração recria a coluna no boot seguinte, sem tocar nos dados.
    db.criar_banco()
    it = _linha(sc_parcial["sc_id"])
    assert it["quantidade_recebida"] == 4
    assert it["quantidade_recebida_protheus"] is None, "sem backfill: NULL = o ERP nada declarou"
    assert it["pendente"] == 6
