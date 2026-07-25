"""v2.2.1 — Cálculos & Transparência: consumo 30/60/90 + tendência, dias de
cobertura, Lead Time calculado (SC7 + recebimento, sem sobrescrever o cadastrado),
giro via snapshots e maturidade de histórico."""

from datetime import datetime, timedelta
import pandas as pd
from services import db_functions as F
import database

CC = "21106 - MANUTENÇÃO"


def _dias_atras(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")


# ── Consumo multi-janela + tendência ──────────────────────────────────────────


def test_consumo_janelas_e_tendencia_alta(db, make_item):
    item_id = make_item("PN-C", estoque=1000, minimo=10)
    F.registrar_movimentacao(item_id, "saida", 30, CC, "x", "x", data_hora=_dias_atras(45))  # janela anterior
    F.registrar_movimentacao(item_id, "saida", 90, CC, "x", "x", data_hora=_dias_atras(10))  # janela recente
    it = F.buscar_item_por_id(item_id)
    assert round(it["consumo_30d"], 2) == 3.0  # 90/30
    assert round(it["consumo_medio_diario"], 2) == 3.0
    assert it["tendencia_label"] == "Alta"  # 3.0 vs 1.0 = +200%


def test_tendencia_queda(db, make_item):
    item_id = make_item("PN-CQ", estoque=1000, minimo=10)
    F.registrar_movimentacao(item_id, "saida", 90, CC, "x", "x", data_hora=_dias_atras(45))
    F.registrar_movimentacao(item_id, "saida", 30, CC, "x", "x", data_hora=_dias_atras(10))
    assert F.buscar_item_por_id(item_id)["tendencia_label"] == "Queda"


def test_tendencia_estavel(db, make_item):
    item_id = make_item("PN-CE", estoque=1000, minimo=10)
    F.registrar_movimentacao(item_id, "saida", 30, CC, "x", "x", data_hora=_dias_atras(45))
    F.registrar_movimentacao(item_id, "saida", 31, CC, "x", "x", data_hora=_dias_atras(10))
    assert F.buscar_item_por_id(item_id)["tendencia_label"] == "Estável"


# ── Dias de cobertura ─────────────────────────────────────────────────────────


def test_cobertura_formula_e_sentinela():
    # v3.1.0: cobertura = estoque atual / consumo diário (sem somar guarda-chuva).
    assert F.calcular_cobertura(9, 3) == 3.0
    assert F.calcular_cobertura(10, 0) == F.PREVISAO_RUPTURA_SEM_RISCO  # sem consumo


def test_cobertura_em_listar_inventario(db, make_item):
    item_id = make_item("PN-COV", estoque=60, minimo=10)
    F.registrar_movimentacao(item_id, "saida", 30, CC, "x", "x", data_hora=_dias_atras(5))
    it = {i["part_number"]: i for i in F.listar_inventario()}["PN-COV"]
    # estoque 30, consumo 30d = 1/dia → cobertura 30 dias (guarda-chuva não entra mais)
    assert it["dias_cobertura"] == 30.0


# ── Lead Time calculado (SC7 backfill) ────────────────────────────────────────


def test_lead_time_sc7_nao_sobrescreve_cadastrado(db, make_item, tmp_path):
    item_id = make_item("PN-LT", estoque=0, lead=7)
    linhas = [
        {
            "Filial": 1,
            "Tipo": 1,
            "Item": 1,
            "Pedido": "F1",
            "DT Emissao": "2026-05-01",
            "Produto": "PN-LT",
            "Descricao": "x",
            "Unidade": "UN",
            "Moeda": 1,
            "Quantidade": 10,
            "Prc Unitario": 5.0,
            "Vlr.Total": 50,
            "Qtd.Entregue": 10,
            "Saldo": 0,
            "Observacoes": "SC: 1",
            "Dt. Entrega": "2026-05-11",
        },  # delta 10
        {
            "Filial": 1,
            "Tipo": 1,
            "Item": 1,
            "Pedido": "F2",
            "DT Emissao": "2026-05-01",
            "Produto": "PN-LT",
            "Descricao": "x",
            "Unidade": "UN",
            "Moeda": 1,
            "Quantidade": 10,
            "Prc Unitario": 5.0,
            "Vlr.Total": 50,
            "Qtd.Entregue": 10,
            "Saldo": 0,
            "Observacoes": "SC: 2",
            "Dt. Entrega": "2026-05-21",
        },  # delta 20
    ]
    path = str(tmp_path / "rel.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame(linhas).to_excel(w, sheet_name="SC7", index=False, startrow=3)  # header na linha 3
    F.importar_relatorio_scs(path, "rel.xlsx")
    it = F.buscar_item_por_id(item_id)
    assert it["lead_time_dias"] == 7  # cadastrado (Neidson) intacto
    assert it["lead_time_calculado"] == 15  # mediana [10, 20]
    assert it["lead_time_calculado_amostras"] == 2
    assert it["lead_time_calculado_origem"] == "SC7"


def test_lead_time_sc7_ignora_delta_zero(db, make_item, tmp_path):
    item_id = make_item("PN-LT0", estoque=0, lead=9)
    linhas = [
        {
            "Filial": 1,
            "Item": 1,
            "Pedido": "F1",
            "DT Emissao": "2026-05-01",
            "Produto": "PN-LT0",
            "Moeda": 1,
            "Quantidade": 1,
            "Prc Unitario": 5.0,
            "Qtd.Entregue": 1,
            "Observacoes": "SC: 1",
            "Dt. Entrega": "2026-05-01",
        },  # delta 0 → ignorado
    ]
    path = str(tmp_path / "rel.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame(linhas).to_excel(w, sheet_name="SC7", index=False, startrow=3)
    F.importar_relatorio_scs(path, "rel.xlsx")
    it = F.buscar_item_por_id(item_id)
    assert it["lead_time_calculado"] is None  # nenhum delta válido (0 dia)
    assert it["lead_time_dias"] == 9


# ── Lead Time calculado (recebimento) ─────────────────────────────────────────


def test_lead_time_recebimento_nao_sobrescreve(db, make_item):
    item_id = make_item("PN-LTR", estoque=0, lead=7)
    ok, _ = F.criar_sc(
        "SC-LTR",
        "2026-01-01",
        [
            {
                "item_id": item_id,
                "part_number": "PN-LTR",
                "nome_item": "i",
                "quantidade_solicitada": 10,
                "quantidade_pedido": 10,
            }
        ],
        "",
    )
    assert ok
    with database.transaction() as c:
        sc_id = c.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc='SC-LTR'").fetchone()["id"]
    item_sc_id = F.listar_itens_sc(sc_id)[0]["id"]
    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 10, CC, "a", "a", "F", "2026-03-01", "NF")
    assert ok, msg
    it = F.buscar_item_por_id(item_id)
    assert it["lead_time_dias"] == 7  # cadastrado intacto
    assert it["lead_time_calculado"] is not None  # ~ jan→mar
    assert it["lead_time_calculado_origem"] == "Recebimento"


# ── Giro / tempo em estoque via snapshots ─────────────────────────────────────


def test_giro_via_snapshots(db, make_item):
    item_id = make_item("PN-G", estoque=100, minimo=10)
    F.registrar_movimentacao(item_id, "saida", 90, CC, "x", "x", data_hora=_dias_atras(30))
    with database.transaction() as c:
        for d, est in [(_dias_atras(60)[:10], 100), (_dias_atras(30)[:10], 50), (_dias_atras(1)[:10], 10)]:
            c.execute(
                "INSERT INTO estoque_snapshots (item_id,data,estoque_atual,valor_estoque) VALUES (?,?,?,0)",
                (item_id, d, est),
            )
    g = F.calcular_giro(item_id, dias=90)
    assert g["n_snapshots"] == 3
    assert g["estoque_medio"] == round((100 + 50 + 10) / 3, 2)
    assert g["consumo_periodo"] == 90
    assert g["giro_anual"] > 0
    assert g["tempo_medio_dias"] is not None


def test_giro_sem_snapshot_usa_estoque_atual(db, make_item):
    item_id = make_item("PN-G2", estoque=50, minimo=10)
    F.registrar_movimentacao(item_id, "saida", 25, CC, "x", "x", data_hora=_dias_atras(10))
    g = F.calcular_giro(item_id, dias=90)
    assert g["n_snapshots"] == 0
    assert g["estoque_medio"] == 25.0  # fallback: estoque atual (50-25)


# ── Maturidade de histórico ───────────────────────────────────────────────────


def test_maturidade_dados(db, make_item):
    item_id = make_item("PN-M", estoque=10)
    F.registrar_movimentacao(item_id, "saida", 2, CC, "x", "x", data_hora=_dias_atras(20))
    m = F.obter_maturidade_dados()
    assert m["dias"] >= 19
    assert m["data_inicio"] is not None
