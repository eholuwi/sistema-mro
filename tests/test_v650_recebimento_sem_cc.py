"""v6.5.0 — Task 2: Centro de Custo sai da tela de recebimento.

Todo recebimento (por SC ou avulso) passa a gravar `centro_custo=""` — decisão do Luis,
NÃO `CC_INVENTARIO` (que rotularia a movimentação como "Ajuste de Inventário"). `""` já
pertence a `CC_GENERICOS` e `categoria_movimentacao` devolve "Entrada" para ele. A
requisição continua com CC escolhido pelo solicitante — este arquivo não mexe nela.
"""

import database
from services import db_functions as F


def _abrir_sc(numero, itens):
    ok, msg = F.criar_sc(numero, "2026-01-01", itens, "")
    assert ok, msg
    conn = database.get_connection()
    sc_id = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero,)).fetchone()["id"]
    conn.close()
    return sc_id


def test_recebimento_por_sc_grava_cc_vazio_e_categoria_entrada(db, make_item):
    a = make_item("PN-CC1", estoque=0, minimo=5, lead=7)
    sc_id = _abrir_sc(
        "SC-CC-1",
        [
            {
                "item_id": a,
                "part_number": "PN-CC1",
                "nome_item": "A",
                "quantidade_solicitada": 4,
                "quantidade_pedido": 4,
            },
        ],
    )
    it = F.listar_itens_sc(sc_id)[0]
    ok, msg = F.registrar_recebimento_sc(sc_id, it["id"], 4, "", "Alm", "Alm", "Forn", "2026-01-10", "NF-1")
    assert ok, msg

    conn = database.get_connection()
    mov = conn.execute(
        "SELECT * FROM movimentacoes WHERE item_id=? ORDER BY id DESC LIMIT 1", (a,)
    ).fetchone()
    conn.close()
    assert mov["centro_custo"] == ""
    assert F.categoria_movimentacao(dict(mov)) == "Entrada"


def test_entrada_avulsa_grava_cc_vazio_e_categoria_entrada(db, make_item):
    a = make_item("PN-CC2", estoque=0, minimo=5, lead=7)
    ok, msg = F.registrar_movimentacao(
        item_id=a,
        tipo="entrada",
        quantidade=10,
        centro_custo="",
        solicitante="Almoxarifado",
        emitente="Almoxarifado",
        observacao="Fornecedor: Forn | NF-2",
    )
    assert ok, msg

    conn = database.get_connection()
    mov = conn.execute(
        "SELECT * FROM movimentacoes WHERE item_id=? ORDER BY id DESC LIMIT 1", (a,)
    ).fetchone()
    conn.close()
    assert mov["centro_custo"] == ""
    assert F.categoria_movimentacao(dict(mov)) == "Entrada"
