"""v3.4.0 — Piso do estoque de segurança pelo mínimo do gestor.

Itens SEM consumo zeravam a segurança calculada (consumo × lead × 1,5 = 0). Como ~40%
do catálogo são spares/sem giro (147 de 361 no mro.db real), a Ficha 360 e o Assistente
mostravam "0". Agora, quando não há base de consumo (manual=0 e calculado=0) mas o gestor
definiu um mínimo, a segurança EFETIVA cai para o `estoque_minimo` (piso do gestor). Além
disso, o cálculo da sugestão passa a usar o lead default quando não há lead cadastrado,
para não zerar itens que têm consumo mas não têm lead.
"""
import database
from services import db_functions as F
from services.planejamento import estoque_seguranca_efetivo, calcular_ponto_reposicao


# ── estoque_seguranca_efetivo: prioridade manual > calculado > piso(mínimo) > 0 ──

def test_piso_pelo_minimo_quando_sem_consumo():
    # Sem manual e sem calculado, mas com mínimo → efetivo = mínimo (piso do gestor).
    item = {"estoque_seguranca": 0, "estoque_seguranca_calculado": 0, "estoque_minimo": 8}
    val, origem = estoque_seguranca_efetivo(item)
    assert val == 8
    assert "piso" in origem


def test_manual_tem_prioridade_sobre_piso():
    item = {"estoque_seguranca": 3, "estoque_seguranca_calculado": 0, "estoque_minimo": 8}
    val, origem = estoque_seguranca_efetivo(item)
    assert val == 3
    assert origem == "manual (gestor)"


def test_calculado_tem_prioridade_sobre_piso():
    item = {"estoque_seguranca": 0, "estoque_seguranca_calculado": 5, "estoque_minimo": 8}
    val, origem = estoque_seguranca_efetivo(item)
    assert val == 5
    assert "calculado" in origem


def test_sem_consumo_e_sem_minimo_continua_zero():
    item = {"estoque_seguranca": 0, "estoque_seguranca_calculado": 0, "estoque_minimo": 0}
    val, origem = estoque_seguranca_efetivo(item)
    assert val == 0
    assert origem == "não definido"


def test_rop_usa_piso_para_item_sem_consumo():
    # ROP = consumo×lead + segurança; sem consumo, o ROP passa a valer o piso (mínimo).
    item = {"consumo_medio_diario": 0, "estoque_seguranca": 0,
            "estoque_seguranca_calculado": 0, "estoque_minimo": 8, "lead_time_dias": 0}
    calc = calcular_ponto_reposicao(item)
    assert calc["estoque_seguranca"] == 8
    assert "piso" in calc["estoque_seguranca_origem"]
    assert calc["rop"] == 8   # 0 × lead + 8


# ── _recalcular_ruptura_by_pn: usa lead default quando não há lead cadastrado ──

def test_calculado_usa_lead_default_sem_lead(db, make_item):
    item_id = make_item("PN-NOLEAD", estoque=0, minimo=5, lead=0)
    with database.transaction() as c:
        c.execute("UPDATE inventario SET consumo_medio_diario=? WHERE id=?", (2.0, item_id))
        F._recalcular_ruptura_by_pn(c, "PN-NOLEAD")
    conn = database.get_connection()
    ssc = conn.execute(
        "SELECT estoque_seguranca_calculado FROM inventario WHERE id=?", (item_id,)
    ).fetchone()[0]
    conn.close()
    # ceil(2 × 30 (lead default) × 1,5) = 90 — não zera por falta de lead cadastrado.
    assert ssc == 90


def test_item_sem_consumo_com_minimo_nao_mostra_zero(db, make_item):
    # Integração: item sem consumo (make_item não gera requisição) mas com mínimo → o
    # efetivo derivado do inventário real deixa de ser 0.
    item_id = make_item("PN-SPARE", estoque=2, minimo=6, lead=10)
    it = next(i for i in F.listar_inventario() if i["id"] == item_id)
    val, origem = estoque_seguranca_efetivo(it)
    assert val == 6
    assert "piso" in origem
