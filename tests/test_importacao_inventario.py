"""Item 1 (v2.1.0): importador da base do Neidson (Tipo/Categoria, Mínimo, Máximo,
Lead Time). Cobre parsing de lead time, aceitação de categorias novas (pós-rebuild
sem CHECK), match/ignore por PN, dry-run sem gravação e idempotência."""
from services import db_functions as F
import database


def test_atualiza_campos_e_parseia_lead_time(db, make_item, xlsx_factory):
    item_id = make_item("PN-INV1", minimo=10, lead=7)
    cols = ["PN", "Tipo / Categoria", "Mínimo (30 dias)", "Máximo ( 60 dias)", "LEADTIME TOTAL"]
    rows = [["PN-INV1", "Químico", 96, 192, "20 dias"]]
    ok, s = F.importar_inventario_neidson(xlsx_factory(rows, cols), "t.xlsx")
    assert ok, s
    assert s["atualizados"] == 1
    item = F.buscar_item_por_id(item_id)
    assert item["tipo_material"] == "Químico"     # categoria nova aceita (sem CHECK)
    assert item["estoque_minimo"] == 96
    assert item["estoque_maximo"] == 192
    assert item["lead_time_dias"] == 20           # "20 dias" -> 20


def test_pn_nao_encontrado_apenas_relatado(db, xlsx_factory):
    cols = ["PN", "Mínimo (30 dias)"]
    rows = [["PN-NAO-EXISTE", 5]]
    ok, s = F.importar_inventario_neidson(xlsx_factory(rows, cols), "t.xlsx")
    assert ok, s
    assert s["atualizados"] == 0
    assert s["ignorados"] == 1
    assert "PN-NAO-EXISTE" in s["pns_nao_encontrados"]
    assert F.buscar_item_por_pn("PN-NAO-EXISTE") is None   # não cria item


def test_dry_run_nao_grava(db, make_item, xlsx_factory):
    item_id = make_item("PN-DRY", minimo=10)
    cols = ["PN", "Mínimo (30 dias)"]
    rows = [["PN-DRY", 99]]
    ok, s = F.importar_inventario_neidson(xlsx_factory(rows, cols), "t.xlsx", dry_run=True)
    assert ok, s
    assert s["atualizados"] == 1 and s["dry_run"] is True
    assert F.buscar_item_por_id(item_id)["estoque_minimo"] == 10   # inalterado
    conn = database.get_connection()
    n = conn.execute("SELECT COUNT(*) c FROM log_importacoes").fetchone()["c"]
    conn.close()
    assert n == 0                                                  # auditoria não gravada


def test_real_run_grava_log(db, make_item, xlsx_factory):
    make_item("PN-LOG", minimo=10)
    cols = ["PN", "Mínimo (30 dias)"]
    rows = [["PN-LOG", 42]]
    ok, s = F.importar_inventario_neidson(xlsx_factory(rows, cols), "arq.xlsx")
    assert ok, s
    conn = database.get_connection()
    log = conn.execute("SELECT * FROM log_importacoes ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert log["tipo"] == "inventario_neidson"
    assert log["arquivo"] == "arq.xlsx"
    assert log["atualizados"] == 1


def test_idempotente(db, make_item, xlsx_factory):
    make_item("PN-IDEM", minimo=10)
    cols = ["PN", "Mínimo (30 dias)", "LEADTIME TOTAL"]
    rows = [["PN-IDEM", 50, "25 dias"]]
    ok1, s1 = F.importar_inventario_neidson(xlsx_factory(rows, cols), "t.xlsx")
    ok2, s2 = F.importar_inventario_neidson(xlsx_factory(rows, cols), "t.xlsx")
    assert ok1 and ok2
    assert s1["atualizados"] == s2["atualizados"] == 1
    item = F.buscar_item_por_id(F.buscar_item_por_pn("PN-IDEM")["id"])
    assert item["estoque_minimo"] == 50
    assert item["lead_time_dias"] == 25
