"""v3.7.0 — Estoque de Segurança DESATIVADO (recálculo e recebimento).

O buffer do MRO passou a ser o próprio Mínimo do Neidson. `_recalcular_ruptura_by_pn`
não grava mais `estoque_seguranca_calculado` (só `previsao_ruptura_dias`, usado pelo
Monitor de SC), e nenhum fluxo (inclusive o recebimento de SC) toca nas colunas de
segurança — que permanecem no schema, porém órfãs.
"""

import database
from services import db_functions as F

CC = "21194 - ALMOXARIFADO"


def _set(item_id, **campos):
    sets = ", ".join(f"{k}=?" for k in campos)
    with database.transaction() as c:
        c.execute(f"UPDATE inventario SET {sets} WHERE id=?", (*campos.values(), item_id))


def _seg(item_id):
    conn = database.get_connection()
    try:
        r = conn.execute(
            "SELECT estoque_seguranca, estoque_seguranca_calculado, previsao_ruptura_dias "
            "FROM inventario WHERE id=?",
            (item_id,),
        ).fetchone()
        return dict(r)
    finally:
        conn.close()


def _abrir_sc(item_id, numero_sc="SC-SEG", qtd=10):
    ok, msg = F.criar_sc(
        numero_sc,
        "2026-01-01",
        [
            {
                "item_id": item_id,
                "part_number": "PN-SEG",
                "nome_item": "Item",
                "quantidade_solicitada": qtd,
                "quantidade_pedido": qtd,
            }
        ],
        "",
    )
    assert ok, msg
    conn = database.get_connection()
    sc_id = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)).fetchone()[
        "id"
    ]
    conn.close()
    return sc_id, F.listar_itens_sc(sc_id)[0]["id"]


def test_recalcular_atualiza_ruptura_mas_nao_seguranca(db, make_item):
    # A previsão de ruptura é recomputada; a segurança calculada NÃO é mais escrita.
    item_id = make_item("PN-SEG2", estoque=100, minimo=10, lead=7)
    _set(item_id, consumo_medio_diario=2.0, estoque_seguranca_calculado=0)
    with database.transaction() as c:
        F._recalcular_ruptura_by_pn(c, "PN-SEG2")
    seg = _seg(item_id)
    assert seg["previsao_ruptura_dias"] == 50  # 100 / 2 = 50 dias
    assert seg["estoque_seguranca_calculado"] == 0  # órfã: não é mais recomputada


def test_recebimento_nao_toca_colunas_de_seguranca(db, make_item):
    item_id = make_item("PN-SEG", estoque=0, minimo=5, lead=5)
    _set(item_id, consumo_medio_diario=0.4667, estoque_seguranca=3, estoque_seguranca_calculado=0)

    sc_id, item_sc_id = _abrir_sc(item_id)
    ok, msg = F.registrar_recebimento_sc(
        sc_id, item_sc_id, 4, CC, "Alm", "Alm", "Forn X", "2026-01-10", "NF-1"
    )
    assert ok, msg

    seg = _seg(item_id)
    # Ambas as colunas de segurança permanecem intactas (o recebimento não as altera).
    assert seg["estoque_seguranca"] == 3
    assert seg["estoque_seguranca_calculado"] == 0
