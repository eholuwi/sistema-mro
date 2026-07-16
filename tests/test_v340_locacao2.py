"""v3.4.0 — 2ª locação na Contagem Física: coluna idempotente + persistência.

A coluna `local_armazenagem_2` é adicionada APÓS o rebuild v2.1.0 (que só preserva um
conjunto fixo de colunas), garantindo que sobreviva em bancos novos. O Ajuste Rápido de
Movimentações permanece intacto — a 2ª locação é um 2º ponto de armazenagem do item.
"""
import database
from services import db_functions as F


def _cols():
    conn = database.get_connection()
    c = {r[1] for r in conn.execute("PRAGMA table_info(inventario)")}
    conn.close()
    return c


def test_coluna_local_2_existe_e_idempotente(db):
    assert "local_armazenagem_2" in _cols()          # sobreviveu ao rebuild v2.1.0
    database.criar_banco()                            # 2ª execução — não deve falhar
    assert "local_armazenagem_2" in _cols()


def test_persiste_segunda_locacao(db, make_item):
    item_id = make_item("PN-LOC", local="ARM-01")
    ok, _ = F.atualizar_localizacao_e_inventariar(item_id, "ARM-01", "obs", novo_local_2="ARM-09")
    assert ok
    it = next(i for i in F.listar_inventario() if i["id"] == item_id)
    assert it["local_armazenagem"] == "ARM-01"
    assert it["local_armazenagem_2"] == "ARM-09"


def test_segunda_locacao_opcional(db, make_item):
    # Sem 2ª locação: fica vazia; a assinatura antiga (3 args) segue compatível.
    item_id = make_item("PN-LOC2", local="ARM-01")
    ok, _ = F.atualizar_localizacao_e_inventariar(item_id, "ARM-01", "obs")
    assert ok
    it = next(i for i in F.listar_inventario() if i["id"] == item_id)
    assert (it.get("local_armazenagem_2") or "") == ""


def test_v456_gerenciar_itens_persiste_segunda_locacao(db, make_item):
    # v4.5.6 — a 2ª locação passou a ser editável também em Gerenciar Itens → Editar,
    # via atualizar_item_inventario (antes só a Contagem Física gravava o campo).
    item_id = make_item("PN-LOC3", local="ARM-01")
    ok, _ = F.atualizar_item_inventario(item_id, {"local_armazenagem_2": "ARM-07"})
    assert ok
    it = next(i for i in F.listar_inventario() if i["id"] == item_id)
    assert it["local_armazenagem_2"] == "ARM-07"
    # Em branco limpa o campo (mesma semântica da Contagem Física).
    ok, _ = F.atualizar_item_inventario(item_id, {"local_armazenagem_2": ""})
    assert ok
    it = next(i for i in F.listar_inventario() if i["id"] == item_id)
    assert (it.get("local_armazenagem_2") or "") == ""
