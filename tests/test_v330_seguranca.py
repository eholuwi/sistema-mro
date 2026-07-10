"""v3.3.0 — Correção do estoque de segurança ("números quebrados").

Regressão do bug: o recebimento de SC gravava a SUGESTÃO (consumo × lead time × 1,5,
fracionária) na coluna MANUAL `estoque_seguranca`, contaminando o parâmetro do gestor
(o `estoque_seguranca_efetivo` prioriza o manual → o decimal aparecia na Ficha 360 e no
Assistente). Agora o recebimento delega a `_recalcular_ruptura_by_id`, que grava só a
SUGESTÃO em `estoque_seguranca_calculado` (arredondada p/ CIMA) e NÃO toca no manual.
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
            "SELECT estoque_seguranca, estoque_seguranca_calculado FROM inventario WHERE id=?",
            (item_id,)).fetchone()
        return dict(r)
    finally:
        conn.close()


def _abrir_sc(item_id, numero_sc="SC-SEG", qtd=10):
    ok, msg = F.criar_sc(numero_sc, "2026-01-01",
        [{"item_id": item_id, "part_number": "PN-SEG", "nome_item": "Item",
          "quantidade_solicitada": qtd, "quantidade_pedido": qtd}], "")
    assert ok, msg
    conn = database.get_connection()
    sc_id = conn.execute(
        "SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)).fetchone()["id"]
    conn.close()
    return sc_id, F.listar_itens_sc(sc_id)[0]["id"]


def test_recebimento_nao_sobrescreve_seguranca_manual(db, make_item):
    # Consumo/lead que davam segurança FRACIONÁRIA (o bug): 0,4667 × 5 × 1,5 = 3,50.
    item_id = make_item("PN-SEG", estoque=0, minimo=5, lead=5)
    _set(item_id, consumo_medio_diario=0.4667, estoque_seguranca=3)  # 3 = manual do gestor

    sc_id, item_sc_id = _abrir_sc(item_id)
    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 4, CC,
                                         "Alm", "Alm", "Forn X", "2026-01-10", "NF-1")
    assert ok, msg

    seg = _seg(item_id)
    # 1) O parâmetro MANUAL do gestor permanece INTACTO (o bug o trocava por ~3,5).
    assert seg["estoque_seguranca"] == 3
    # 2) A SUGESTÃO é inteira (arredondada p/ cima), nunca fracionária.
    ssc = seg["estoque_seguranca_calculado"]
    assert ssc == int(ssc)
    assert ssc == 4      # ceil(0,4667 × 5 × 1,5) = ceil(3,50) = 4


def test_sugestao_seguranca_arredonda_para_cima(db, make_item):
    # O cálculo da sugestão sempre devolve INTEIRO (ceil), não fração "quebrada".
    item_id = make_item("PN-SEG2", estoque=100, minimo=10, lead=7)
    _set(item_id, consumo_medio_diario=1.4333)   # 1,4333 × 7 × 1,5 = 15,05
    with database.transaction() as c:
        F._recalcular_ruptura_by_pn(c, "PN-SEG2")
    ssc = _seg(item_id)["estoque_seguranca_calculado"]
    assert ssc == 16          # ceil(15,05) — inteiro, arredonda p/ cima
