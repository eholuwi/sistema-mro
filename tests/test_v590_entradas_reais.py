"""v5.9.0 — card "Entradas" do Almoxarifado conta só RECEBIMENTO real de material.

O schema não tem tipo='AJUSTE' (só entrada|saida|devolucao), então todo ajuste positivo
é gravado como 'entrada': contagem física, conferência, ajuste por edição de item e
entrada avulsa. O card contava os quatro. `ENTRADA_REAL_WHERE` isola o recebimento pelo
único sinal confiável — `sc_item_id`, preenchido apenas por `registrar_recebimento_sc` —
espelhando o que `SAIDA_REAL_WHERE` já fazia do lado das saídas.

O teste antigo (`test_v360_almoxarifado.py`) usava `>=`, frouxo demais para pegar isso:
aqui a asserção é de igualdade e cada tipo de ajuste é semeado explicitamente.
"""

from datetime import date, timedelta

import database
from services.constants import CC_EDICAO, CC_INVENTARIO
from services.dashboards import montar_visao_almoxarifado
from services.drill_down import rows_mov_periodo


def _entrada(item_id, qtd, *, sc_item_id=None, centro_custo="", motivo="", dias_atras=1):
    dt = (date.today() - timedelta(days=dias_atras)).strftime("%Y-%m-%d") + " 08:00:00"
    with database.transaction() as c:
        c.execute(
            "INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,"
            "centro_custo,setor,solicitante,emitente,observacao,motivo,sc_item_id) "
            "VALUES (?,'entrada',?,?,?,?,?,?,?,?,?,?)",
            (item_id, qtd, None, dt, centro_custo, "", "x", "x", "t", motivo, sc_item_id),
        )


def _sc_item_id(sc_id):
    conn = database.get_connection()
    try:
        return conn.execute("SELECT id FROM itens_sc WHERE sc_id=?", (sc_id,)).fetchone()["id"]
    finally:
        conn.close()


def _cenario(make_item, make_sc):
    """1 recebimento real + os 4 tipos de ajuste que hoje entram como 'entrada'."""
    item = make_item("PN-REC", nome="Item Recebido")
    sc_item = _sc_item_id(make_sc(numero_sc="SC-REC", item_id=item))

    _entrada(item, 10, sc_item_id=sc_item)  # recebimento de SC — o único real
    _entrada(item, 7, centro_custo=CC_INVENTARIO)  # contagem física
    _entrada(item, 0, centro_custo=CC_INVENTARIO)  # conferência (não moveu nada)
    _entrada(item, 3, centro_custo=CC_EDICAO)  # ajuste por edição de item
    _entrada(item, 5, motivo="Compra avulsa")  # entrada avulsa
    return item


def test_card_entradas_ignora_os_quatro_tipos_de_ajuste(db, make_item, make_sc):
    _cenario(make_item, make_sc)
    vm = montar_visao_almoxarifado()

    # 5 linhas de entrada no ledger, 1 é recebimento de material.
    assert vm["entradas"]["semana"]["n"] == 1
    assert vm["entradas"]["semana"]["q"] == 10.0
    assert vm["entradas"]["mes"]["n"] == 1


def test_top_recebidos_e_historico_seguem_o_mesmo_criterio(db, make_item, make_sc):
    _cenario(make_item, make_sc)
    vm = montar_visao_almoxarifado()

    # A quantidade do "mais recebido" não pode somar os ajustes (10, não 25).
    assert [r["q"] for r in vm["top_recebidos"] if r["pn"] == "PN-REC"] == [10.0]
    assert vm["historico_mensal"]["entradas"] == [10.0]


def test_drill_do_card_bate_com_o_numero_do_card(db, make_item, make_sc):
    """Card e drill precisam contar a mesma coisa — senão o clique desmente o card."""
    _cenario(make_item, make_sc)
    vm = montar_visao_almoxarifado()

    df = rows_mov_periodo("entrada", "semana")
    assert len(df) == vm["entradas"]["semana"]["n"] == 1
    assert df.iloc[0]["Qtd"] == 10


def test_ajustes_continuam_no_ledger(db, make_item, make_sc):
    """Os ajustes saem do INDICADOR, não do histórico — nada é apagado."""
    item = _cenario(make_item, make_sc)
    conn = database.get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) n FROM movimentacoes WHERE tipo='entrada' AND item_id=?", (item,)
        ).fetchone()["n"]
    finally:
        conn.close()
    assert n == 6  # 5 semeadas + o saldo inicial do make_item
