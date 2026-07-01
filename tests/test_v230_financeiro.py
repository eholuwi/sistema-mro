"""v2.3.0 — Pilar Financeiro / Valoração: preço de valoração (SCM + fallback SC7),
valor em estoque/imobilizado, valor consumido (estimativa), Curva ABC por valor,
evolução de preço e evolução do valor imobilizado. Tudo derivado na leitura."""
from datetime import datetime, timedelta
from services import db_functions as F
import database

CC = "21106 - MANUTENÇÃO"


def _dias_atras(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")


def _set_preco_ref(item_id, preco):
    with database.transaction() as c:
        c.execute("UPDATE inventario SET preco_referencia=? WHERE id=?", (preco, item_id))


def _add_preco_hist(item_id, data, preco, origem="SC7", moeda="BRL"):
    with database.transaction() as c:
        c.execute("""INSERT INTO precos_historico
                     (item_id,data,preco_unitario,moeda,fornecedor,numero_sc,numero_po,origem)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (item_id, data, preco, moeda, "Forn X", None, "PO1", origem))


# ── Preço de valoração ────────────────────────────────────────────────────────

def test_preco_valoracao_usa_scm(db, make_item):
    item_id = make_item("PN-V1", estoque=10)
    _set_preco_ref(item_id, 5.0)
    with database.transaction() as c:
        preco, origem, moeda = F._preco_valoracao(c, item_id)
    assert preco == 5.0
    assert origem == "SCM"
    assert moeda == "BRL"


def test_preco_valoracao_fallback_sc7(db, make_item):
    item_id = make_item("PN-V2", estoque=10)  # preco_referencia = 0
    _add_preco_hist(item_id, "2026-06-01", 8.0, origem="SC7")
    with database.transaction() as c:
        preco, origem, moeda = F._preco_valoracao(c, item_id)
    assert preco == 8.0
    assert origem == "SC7"


def test_preco_valoracao_sem_preco(db, make_item):
    item_id = make_item("PN-V3", estoque=10)
    with database.transaction() as c:
        preco, origem, _ = F._preco_valoracao(c, item_id)
    assert preco == 0.0
    assert origem is None


# ── Valor em estoque / imobilizado ────────────────────────────────────────────

def test_valor_imobilizado_total_e_sem_preco(db, make_item):
    a = make_item("PN-I1", estoque=10)
    _set_preco_ref(a, 5.0)          # 10 × 5 = 50
    b = make_item("PN-I2", estoque=4)  # estoque mas sem preço
    make_item("PN-I3", estoque=0)      # sem estoque e sem preço → não conta como "sem preço"
    vi = F.obter_valor_imobilizado()
    assert vi["total_brl"] == 50.0
    assert vi["itens_valorados"] == 1
    assert vi["itens_sem_preco"] == 1   # só o PN-I2 (estoque > 0, sem preço)


def test_valor_imobilizado_fallback_sc7_soma(db, make_item):
    a = make_item("PN-I4", estoque=3)
    _add_preco_hist(a, "2026-06-01", 7.0, origem="SC7")  # 3 × 7 = 21
    vi = F.obter_valor_imobilizado()
    assert vi["total_brl"] == 21.0
    assert vi["itens_valorados"] == 1


# ── Valor consumido (estimativa) ──────────────────────────────────────────────

def test_valor_consumido_estimativa(db, make_item):
    item_id = make_item("PN-VC", estoque=1000, minimo=10)
    _set_preco_ref(item_id, 5.0)
    F.registrar_movimentacao(item_id, "saida", 20, CC, "x", "x", data_hora=_dias_atras(10))
    F.registrar_movimentacao(item_id, "saida", 100, CC, "x", "x", data_hora=_dias_atras(200))  # fora da janela 90d
    vc = F.calcular_valor_consumido(item_id, dias=90)
    assert vc["qtd"] == 20.0
    assert vc["valor"] == 100.0   # 20 × 5
    assert vc["origem"] == "SCM"


# ── Curva ABC por valor ───────────────────────────────────────────────────────

def test_abc_valor_classes_a_b_c(db, make_item):
    # preços = 1 → valor = qtd. Total = 1000. Cumulativo 800/950/1000 → A/B/C.
    a = make_item("PN-A", estoque=1000, minimo=1); _set_preco_ref(a, 1.0)
    b = make_item("PN-B", estoque=1000, minimo=1); _set_preco_ref(b, 1.0)
    c = make_item("PN-C", estoque=1000, minimo=1); _set_preco_ref(c, 1.0)
    F.registrar_movimentacao(a, "saida", 800, CC, "x", "x", data_hora=_dias_atras(5))
    F.registrar_movimentacao(b, "saida", 150, CC, "x", "x", data_hora=_dias_atras(5))
    F.registrar_movimentacao(c, "saida", 50, CC, "x", "x", data_hora=_dias_atras(5))
    abc = F.obter_abc_valor(dias=90)
    por_pn = {x["part_number"]: x for x in abc}
    assert [x["part_number"] for x in abc] == ["PN-A", "PN-B", "PN-C"]  # ordenado por valor desc
    assert por_pn["PN-A"]["valor"] == 800.0
    assert por_pn["PN-A"]["classe"] == "A"   # acum 80% ≤ 80
    assert por_pn["PN-B"]["classe"] == "B"   # acum 95% ≤ 95
    assert por_pn["PN-C"]["classe"] == "C"   # acum 100%


def test_abc_valor_ignora_item_sem_preco(db, make_item):
    a = make_item("PN-SP", estoque=100, minimo=1)  # sem preço → valor 0 → fora do ABC
    F.registrar_movimentacao(a, "saida", 10, CC, "x", "x", data_hora=_dias_atras(5))
    assert F.obter_abc_valor(dias=90) == []


# ── Evolução de preço / valor imobilizado ─────────────────────────────────────

def test_evolucao_preco_ordenada(db, make_item):
    item_id = make_item("PN-EP", estoque=1)
    _add_preco_hist(item_id, "2026-05-01", 10.0, origem="SC7")
    _add_preco_hist(item_id, "2026-03-01", 8.0, origem="SCM")
    _add_preco_hist(item_id, "2026-06-01", 12.0, origem="SC7")
    serie = F.obter_evolucao_preco(item_id)
    assert [r["data"] for r in serie] == ["2026-03-01", "2026-05-01", "2026-06-01"]
    assert serie[0]["preco_unitario"] == 8.0


def test_evolucao_valor_imobilizado(db, make_item):
    item_id = make_item("PN-EV", estoque=10)
    with database.transaction() as c:
        for d, val in [(_dias_atras(3)[:10], 100.0), (_dias_atras(1)[:10], 150.0)]:
            c.execute("""INSERT INTO estoque_snapshots (item_id,data,estoque_atual,valor_estoque)
                         VALUES (?,?,?,?)""", (item_id, d, 10, val))
    ev = F.obter_evolucao_valor_imobilizado(dias=30)
    assert ev["n_snapshots"] == 2
    assert [p["valor"] for p in ev["serie"]] == [100.0, 150.0]   # ordenado por data


# ── Export ────────────────────────────────────────────────────────────────────

def test_export_colunas_financeiras(db, make_item):
    item_id = make_item("PN-EX", estoque=10, minimo=1)
    _set_preco_ref(item_id, 5.0)
    F.registrar_movimentacao(item_id, "saida", 2, CC, "x", "x", data_hora=_dias_atras(5))
    df = F.exportar_inventario_df()
    for col in ["Preço Ref", "Origem Preço", "Valor em Estoque",
                "Valor Consumido(90d)", "Classe ABC(valor)"]:
        assert col in df.columns
    linha = df[df["PN"] == "PN-EX"].iloc[0]
    assert linha["Valor em Estoque"] == 40.0   # (10-2) × 5
    assert linha["Origem Preço"] == "SCM"
