"""v3.6.0 — Dashboard do Almoxarifado: assembler `montar_visao_almoxarifado`.

Valida a estrutura do view-model e os agregados de movimentação (entradas/saídas por
período, setores) + KPIs de saúde a partir de dados reais de teste.
"""

from datetime import date, timedelta
import database
from services.dashboards import montar_visao_almoxarifado


def _req(numero="R1", setor="SMT"):
    with database.transaction() as c:
        cur = c.execute(
            "INSERT INTO requisicoes (numero_requisicao,data_hora,setor,emitente,centro_custo) "
            "VALUES (?,?,?,?,?)",
            (numero, date.today().strftime("%Y-%m-%d") + " 08:00:00", setor, "x", "CC"),
        )
        return cur.lastrowid


def _mov(item_id, tipo, qtd, dias_atras=0, requisicao_id=None, setor=""):
    dt = (date.today() - timedelta(days=dias_atras)).strftime("%Y-%m-%d") + " 08:00:00"
    with database.transaction() as c:
        c.execute(
            "INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,"
            "centro_custo,setor,solicitante,emitente,observacao,requisicao_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, tipo, qtd, None, dt, "CC", setor, "x", "x", "t", requisicao_id),
        )


def test_almox_estrutura_e_agregados(db, make_item):
    it = make_item("PN-A", estoque=2, minimo=10)  # abaixo do mínimo
    rid = _req(setor="SMT")
    _mov(it, "entrada", 5, dias_atras=2)
    _mov(it, "saida", 3, dias_atras=1, requisicao_id=rid, setor="SMT")

    vm = montar_visao_almoxarifado()
    assert set(vm) >= {
        "kpis",
        "prioridades",
        "distribuicao",
        "cobertura_faixa",
        "abc",
        "entradas",
        "saidas",
        "top_recebidos",
        "mais_consumidos",
        "setores",
        "historico_mensal",
    }
    assert vm["kpis"]["itens_cadastrados"] == 1
    assert vm["kpis"]["estoque_baixo"] == 1
    assert vm["entradas"]["semana"]["n"] >= 1
    assert vm["saidas"]["semana"]["n"] == 1
    assert any(s["setor"] == "SMT" for s in vm["setores"])
    assert any(x["pn"] == "PN-A" for x in vm["mais_consumidos"])
    # ABC sempre presente com as 3 classes
    assert set(vm["abc"]) == {"A", "B", "C"}


def test_almox_sem_dados_nao_quebra(db):
    vm = montar_visao_almoxarifado()
    assert vm["kpis"]["itens_cadastrados"] == 0
    assert vm["historico_mensal"]["meses"] == []
    assert vm["prioridades"]["comprar_agora"] == []
