"""v3.10.0 — Ajustes de telas (Compras · Saldo · Assistente).

Cobre o novo helper `itens_com_sc_aberta`, usado pelo Assistente de Reposição para
mostrar SÓ material crítico que ainda NÃO tem SC aberta.
"""

from services import db_functions as F


def test_itens_com_sc_aberta_inclui_item_com_sc(db, make_item, make_sc):
    """Item com SC recém-criada (saldo residual > 0, status != Cancelado) entra no set."""
    item_id = make_item(part_number="PN-COM-SC")
    make_sc(numero_sc="SC-ABERTA", item_id=item_id, quantidade_solicitada=5)
    assert item_id in F.itens_com_sc_aberta()


def test_itens_com_sc_aberta_exclui_item_sem_sc(db, make_item):
    """Item sem nenhuma SC não entra no set."""
    item_id = make_item(part_number="PN-SEM-SC")
    assert item_id not in F.itens_com_sc_aberta()


def test_itens_com_sc_aberta_exclui_sc_cancelada(db, make_item, make_sc):
    """SC Cancelada não conta como aberta (mesma definição de listar_scs)."""
    item_id = make_item(part_number="PN-CANC")
    sc_id = make_sc(numero_sc="SC-CANC", item_id=item_id, quantidade_solicitada=5)
    conn = db.get_connection()
    conn.execute("UPDATE solicitacoes_compra SET status='Cancelado' WHERE id=?", (sc_id,))
    conn.commit()
    conn.close()
    assert item_id not in F.itens_com_sc_aberta()


def test_itens_com_sc_aberta_exclui_sc_recebida(db, make_item, make_sc):
    """SC totalmente recebida (saldo residual = 0) não conta como aberta."""
    item_id = make_item(part_number="PN-REC")
    sc_id = make_sc(numero_sc="SC-REC", item_id=item_id, quantidade_solicitada=5)
    conn = db.get_connection()
    conn.execute("UPDATE itens_sc SET saldo_residual=0, quantidade_recebida=5 WHERE sc_id=?", (sc_id,))
    conn.commit()
    conn.close()
    assert item_id not in F.itens_com_sc_aberta()
