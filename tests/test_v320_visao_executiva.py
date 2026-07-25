"""v3.2.0 — Visão Executivo/Mensal do Dashboard (panorama do ano corrente, YTD).

Cobre a nova camada de `services/dashboards.py`: consumo YTD por item (só saída REAL
por requisição — ajustes de inventário NÃO entram), curva ABC, composição por tipo,
rankings Top 10 e o assembler `montar_visao_executiva`.

Regressão-chave: um AJUSTE FÍSICO (saída sem requisição) com quantidade enorme não
pode inflar consumo/ABC (era a causa dos valores absurdos tipo R$ 4 mi num grampo).
Banco temporário isolado.
"""

from datetime import date

import database
from services import dashboards as D

ANO = 2026
HOJE = date(2026, 7, 9)


def _set_preco(item_id, preco):
    with database.transaction() as c:
        c.execute("UPDATE inventario SET preco_referencia=? WHERE id=?", (preco, item_id))


def _ajuste_saida(item_id, quantidade, data_hora=f"{ANO}-05-10 08:00:00"):
    """Saída SEM requisição (ajuste físico de inventário) — não é consumo real."""
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO movimentacoes (item_id,tipo,quantidade,data_hora,observacao,requisicao_id) "
            "VALUES (?,?,?,?,?,NULL)",
            (item_id, "saida", quantidade, data_hora, "Ajuste Físico"),
        )
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# _consumo_ytd_por_item — consumo real do ano, com valor
# ══════════════════════════════════════════════════════════════════════════════


def test_consumo_ytd_valor_e_ignora_ano_anterior(db, make_item, registrar_consumo):
    it = make_item(part_number="C1")
    _set_preco(it, 10.0)
    registrar_consumo(it, quantidade=5, data_hora=f"{ANO}-03-10 08:00:00")
    registrar_consumo(it, quantidade=3, data_hora=f"{ANO}-06-10 08:00:00")
    registrar_consumo(it, quantidade=99, data_hora=f"{ANO - 1}-06-10 08:00:00")  # ano anterior

    itens = D._consumo_ytd_por_item(ANO)
    assert len(itens) == 1
    x = itens[0]
    assert x["qtd"] == 8  # 5 + 3 (o do ano anterior não conta)
    assert x["valor"] == 80.0  # 8 × R$10


def test_consumo_ytd_ignora_ajuste_fisico(db, make_item, registrar_consumo):
    # REGRESSÃO DO BUG: ajuste físico gigante NÃO pode virar consumo/valor.
    it = make_item(part_number="GRAMPO")
    _set_preco(it, 105.0)
    registrar_consumo(it, quantidade=10, data_hora=f"{ANO}-05-10 08:00:00")  # real
    _ajuste_saida(it, quantidade=39995, data_hora=f"{ANO}-05-22 08:00:00")  # ajuste

    itens = D._consumo_ytd_por_item(ANO)
    assert len(itens) == 1
    assert itens[0]["qtd"] == 10  # só o consumo real
    assert itens[0]["valor"] == 1050.0  # 10 × 105 — não 4,2 milhões


# ══════════════════════════════════════════════════════════════════════════════
# _classificar_abc / _composicao_por_tipo
# ══════════════════════════════════════════════════════════════════════════════


def test_classificar_abc_ordena_classes_e_total():
    itens = [{"valor": 80}, {"valor": 15}, {"valor": 5}]
    abc, total = D._classificar_abc(itens)
    assert total == 100
    assert [x["valor"] for x in abc] == [80, 15, 5]  # ordenado desc
    assert abc[0]["classe"] == "A"  # 0% acumulado antes → A
    assert abc[-1]["classe"] == "C"  # último cruza 95%


def test_composicao_por_tipo_agrupa_e_junta_outros():
    itens = [
        {"tipo_material": "Consumivel", "valor": 100},
        {"tipo_material": "Consumivel", "valor": 50},
        {"tipo_material": "ESD", "valor": 30},
    ]
    comp = D._composicao_por_tipo(itens, top=1)
    # top=1 → só "Consumivel"; ESD cai em "Outros".
    assert comp[0] == {"tipo": "Consumivel", "valor": 150}
    assert comp[-1] == {"tipo": "Outros", "valor": 30}


# ══════════════════════════════════════════════════════════════════════════════
# Séries e rankings YTD
# ══════════════════════════════════════════════════════════════════════════════


def test_consumo_mensal_ytd_valor_por_mes(db, make_item, registrar_consumo):
    it = make_item(part_number="M1")
    _set_preco(it, 2.0)
    registrar_consumo(it, quantidade=10, data_hora=f"{ANO}-04-05 08:00:00")
    registrar_consumo(it, quantidade=20, data_hora=f"{ANO}-05-05 08:00:00")
    serie = D._consumo_mensal_ytd(ANO)
    por_mes = {s["mes"]: s["valor"] for s in serie}
    assert por_mes[f"{ANO}-04"] == 20.0  # 10 × 2
    assert por_mes[f"{ANO}-05"] == 40.0  # 20 × 2


def test_top_dead_stock_lista_parado_sem_consumo(db, make_item, registrar_consumo):
    vivo = make_item(part_number="VIVO", estoque=10)
    morto = make_item(part_number="MORTO", estoque=100)
    _set_preco(vivo, 5.0)
    _set_preco(morto, 7.0)
    registrar_consumo(vivo, quantidade=1, data_hora=f"{ANO}-05-01 08:00:00")  # tem consumo

    dead = D._top_dead_stock(ANO, limit=10)
    pns = [x["part_number"] for x in dead]
    assert "MORTO" in pns and "VIVO" not in pns
    morto_row = next(x for x in dead if x["part_number"] == "MORTO")
    assert morto_row["valor"] == 700.0  # 100 × 7


def test_ranking_cc_exclui_generico(db, make_item):
    it = make_item(part_number="CC1", estoque=50)
    _set_preco(it, 10.0)
    conn = database.get_connection()
    try:
        for cc, q in [("99000 - ATIVO PASSIVO RES. F", 5), ("21106 - MANUTENÇÃO", 3)]:
            cur = conn.execute(
                "INSERT INTO requisicoes (numero_requisicao, data_hora, setor, emitente, centro_custo) "
                "VALUES (?,?,?,?,?)",
                (f"R-{cc[:4]}", f"{ANO}-05-01 08:00:00", "MANUTENÇÃO", "Joao", cc),
            )
            conn.execute(
                "INSERT INTO movimentacoes (item_id,tipo,quantidade,data_hora,centro_custo,requisicao_id) "
                "VALUES (?,?,?,?,?,?)",
                (it, "saida", q, f"{ANO}-05-01 08:00:00", cc, cur.lastrowid),
            )
        conn.commit()
    finally:
        conn.close()
    ccs = [x["rotulo"] for x in D._ranking_cc_ytd(ANO, limit=10)]
    assert any("MANUTENÇÃO" in c for c in ccs)
    assert not any("99000" in c for c in ccs)  # CC genérico/contábil excluído


# ══════════════════════════════════════════════════════════════════════════════
# Assembler + roteador
# ══════════════════════════════════════════════════════════════════════════════


def test_montar_visao_executiva_estrutura(db, make_item, registrar_consumo):
    it = make_item(part_number="E1", estoque=100, minimo=10)
    _set_preco(it, 4.0)
    registrar_consumo(it, quantidade=8, data_hora=f"{ANO}-05-10 08:00:00")
    registrar_consumo(it, quantidade=12, data_hora=f"{ANO}-06-10 08:00:00")

    vm = D.montar_visao_executiva(hoje=HOJE)
    assert vm["ano"] == ANO
    assert set(vm) == {
        "ano",
        "kpis",
        "valor_detalhe",
        "series",
        "abc",
        "composicao_tipo",
        "rankings",
        "destaques",
    }
    k = vm["kpis"]
    assert k["valor_consumido_ytd"] == 80.0  # 20 un × R$4
    assert k["itens_consumidos_ytd"] == 1
    assert k["n_requisicoes_ytd"] == 2
    assert set(vm["rankings"]) == {
        "top_valor_consumido",
        "top_qtd_consumida",
        "top_valor_imobilizado",
        "top_dead_stock",
        "top_centro_custo",
        "top_emitente",
        "top_setor",
    }
    assert vm["abc"]["itens"][0]["part_number"] == "E1"


def test_executiva_nao_infla_com_ajuste_fisico(db, make_item, registrar_consumo):
    # Ponta a ponta: ajuste físico gigante não deve aparecer no valor consumido YTD.
    it = make_item(part_number="ALICATE", estoque=5)
    _set_preco(it, 21.5)
    registrar_consumo(it, quantidade=2, data_hora=f"{ANO}-04-01 08:00:00")  # real
    _ajuste_saida(it, quantidade=99999, data_hora=f"{ANO}-06-30 08:00:00")  # sentinela

    vm = D.montar_visao_executiva(hoje=HOJE)
    assert vm["kpis"]["valor_consumido_ytd"] == 43.0  # 2 × 21,5 — não 2,1 milhões


def test_montar_dashboard_roteia_executivo(db, make_item):
    make_item(part_number="RT1")
    vm = D.montar_dashboard(D.PUBLICO_EXECUTIVO)
    assert "rankings" in vm and vm["ano"] == date.today().year
    assert D.PUBLICO_EXECUTIVO in D.PUBLICOS
