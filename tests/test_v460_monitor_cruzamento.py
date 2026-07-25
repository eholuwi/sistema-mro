"""v4.6.0 — Monitor de SC 2.0: cruzamento SCM × SC7 (crus) + Planilha livre com
colunas customizadas.

A função `cruzar_scm_sc7` é PURA (DataFrames + escopo/depto injetados) → testável
sem banco. `preparar_df`/`detectar_header` são exercitados com .xlsx em memória.
A Planilha livre v2 (colunas + linhas, retrocompatível) usa a fixture `db`.
"""

import io
import json

import pandas as pd
import openpyxl

from services import db_functions as F
from services import monitor_cruzamento as MC


# ── Builders de DataFrame cru ────────────────────────────────────────────────
def _scm_df(rows):
    return pd.DataFrame(rows)


def _sc7_df(rows):
    return pd.DataFrame(rows)


def _linha_scm(
    sc="SC1",
    solic="Ana",
    produto="PN1",
    qtd=10,
    pedido="PO1",
    status="Em andamento",
    desc="Item 1",
    justif="",
    data_nec=None,
):
    return {
        "Numero da Solicitacao": sc,
        "Solicitante": solic,
        "Status": status,
        "Produto": produto,
        "Descricao Detalhada": desc,
        "Quantidade": qtd,
        "Data Necessidade": data_nec,
        "Justificativa/Projeto": justif,
        "Pedido": pedido,
        "Documento": "",
    }


def _linha_sc7(
    pedido="PO1",
    produto="PN1",
    entregue=0,
    saldo=0,
    dt="2026-05-01",
    fornecedor="ACME",
    comprador="Miguel",
    desc="Item 1",
):
    return {
        "Numero PC": pedido,
        "Produto": produto,
        "Descricao": desc,
        "Qtd.Entregue": entregue,
        "Saldo": saldo,
        "Dt. Entrega": dt,
        "Nome Fantasia": fornecedor,
        "Comprador": comprador,
    }


# ── cruzar_scm_sc7 (função pura) ─────────────────────────────────────────────
def test_cruzamento_casada_e_agregacao():
    scm = _scm_df([_linha_scm(pedido="PO1", produto="PN1", qtd=10)])
    # Datas como Timestamp (é assim que o pandas lê datas reais do .xlsx).
    sc7 = _sc7_df(
        [
            _linha_sc7("PO1", "PN1", entregue=3, saldo=7, dt=pd.Timestamp("2026-05-01")),
            _linha_sc7("PO1", "PN1", entregue=2, saldo=5, dt=pd.Timestamp("2026-06-01")),
        ]
    )
    res = MC.cruzar_scm_sc7(scm, sc7)
    assert "erro" not in res
    assert res["stats"]["casadas"] == 1
    linha = res["linhas"][0]
    assert linha["Situação"] == "✅ Casada"
    assert linha["Qtd Entregue"] == 5  # 3 + 2 (agregado por PO,PN)
    assert linha["Saldo"] == 12  # 7 + 5
    assert linha["Dt. Entrega"] == "2026-06-01"  # a mais recente
    assert res["stats"]["saldo_pendente_total"] == 12


def test_cruzamento_sem_pedido():
    scm = _scm_df([_linha_scm(pedido="")])
    sc7 = _sc7_df([_linha_sc7("PO1", "PN1", saldo=5)])
    res = MC.cruzar_scm_sc7(scm, sc7)
    linha = res["linhas"][0]
    assert linha["Situação"] == "🟡 Sem pedido"
    assert linha["Saldo"] is None
    assert res["stats"]["sem_pedido"] == 1


def test_cruzamento_po_sem_sc7():
    scm = _scm_df([_linha_scm(pedido="PO9", produto="PN1")])
    sc7 = _sc7_df([_linha_sc7("PO1", "PN1", saldo=5)])
    res = MC.cruzar_scm_sc7(scm, sc7)
    assert res["linhas"][0]["Situação"] == "⚠️ PO sem linha no SC7"
    assert res["stats"]["po_sem_sc7"] == 1


def test_cruzamento_orfao():
    # PO1/PN1 casa; PO2/PN2 no SC7 não tem SC → órfão.
    scm = _scm_df([_linha_scm(sc="SC1", pedido="PO1", produto="PN1")])
    sc7 = _sc7_df(
        [
            _linha_sc7("PO1", "PN1", saldo=3),
            _linha_sc7("PO2", "PN2", saldo=9),
        ]
    )
    res = MC.cruzar_scm_sc7(scm, sc7)
    assert res["stats"]["orfaos"] == 1
    assert res["orfaos"][0]["PO"] == "PO2"
    assert res["orfaos"][0]["Produto"] == "PN2"


def test_cruzamento_filtro_mro_solicitante():
    scm = _scm_df(
        [
            _linha_scm(sc="SC1", solic="Ana", produto="PN1", pedido="PO1"),
            _linha_scm(sc="SC2", solic="Bob", produto="PN1", pedido="PO1"),  # fora do escopo
        ]
    )
    sc7 = _sc7_df([_linha_sc7("PO1", "PN1", saldo=5)])
    res = MC.cruzar_scm_sc7(scm, sc7, solicitantes_mro={F._normalizar_txt("Ana")})
    assert len(res["linhas"]) == 1
    assert res["linhas"][0]["Solicitante"] == "Ana"
    assert res["stats"]["fora_escopo"] == 1


def test_cruzamento_filtro_mro_pn():
    scm = _scm_df(
        [
            _linha_scm(sc="SC1", produto="PN1", pedido="PO1"),
            _linha_scm(sc="SC2", produto="PNX", pedido="PO1"),  # PN fora do inventário
        ]
    )
    sc7 = _sc7_df(
        [
            _linha_sc7("PO1", "PN1", saldo=5),
            _linha_sc7("PO7", "PNX", saldo=9),  # órfão de PN fora do escopo → não entra
        ]
    )
    res = MC.cruzar_scm_sc7(scm, sc7, pns_mro={"PN1"})
    assert len(res["linhas"]) == 1
    assert res["linhas"][0]["Produto"] == "PN1"
    assert res["stats"]["fora_escopo"] == 1
    assert res["stats"]["orfaos"] == 0  # PNX não é MRO → não vira órfão


def test_cruzamento_departamento():
    scm = _scm_df(
        [
            _linha_scm(sc="SC1", solic="Ana", produto="PN1", pedido="PO1"),
            _linha_scm(sc="SC2", solic="Carla", produto="PN1", pedido=""),  # sem depto mapeado
        ]
    )
    sc7 = _sc7_df([_linha_sc7("PO1", "PN1", saldo=5)])
    dep = {F._normalizar_txt("Ana"): "MANUTENÇÃO"}
    res = MC.cruzar_scm_sc7(scm, sc7, dep_por_solic=dep)
    depmap = {l["Solicitante"]: l["Departamento"] for l in res["linhas"]}
    assert depmap["Ana"] == "MANUTENÇÃO"
    assert depmap["Carla"] == "—"
    assert res["departamentos"] == ["MANUTENÇÃO", "—"]  # ordenado


def test_cruzamento_acento_insensivel():
    # Colunas com acento/variação de nome ainda resolvem via _coluna.
    scm = _scm_df(
        [
            {
                "Número da Solicitação": "SC1",
                "Solicitante": "Ana",
                "Status": "OK",
                "Produto": "PN1",
                "Descrição": "Item",
                "Quantidade": 4,
                "Justificativa": "",
                "Pedido": "PO1",
            }
        ]
    )
    sc7 = _sc7_df(
        [
            {
                "Pedido": "PO1",
                "Produto": "PN1",
                "Qtd Entregue": 1,
                "Saldo": 3,
                "Dt Entrega": "2026-05-01",
                "Razão Social": "ACME",
                "Comprador": "Miguel",
            }
        ]
    )
    res = MC.cruzar_scm_sc7(scm, sc7)
    assert res["stats"]["casadas"] == 1
    assert res["linhas"][0]["Saldo"] == 3


def test_cruzamento_coluna_faltando():
    scm = _scm_df([{"Numero da Solicitacao": "SC1", "Produto": "PN1"}])  # falta Pedido
    sc7 = _sc7_df([_linha_sc7("PO1", "PN1", saldo=5)])
    res = MC.cruzar_scm_sc7(scm, sc7)
    assert "erro" in res
    assert "Pedido" in res["erro"]


# ── preparar_df / detectar_header (.xlsx em memória) ─────────────────────────
def test_preparar_df_header0_scm(xlsx_factory):
    buf = xlsx_factory(
        [["SC1", "Ana", "PN1", 10, "PO1"]],
        ["Numero da Solicitacao", "Solicitante", "Produto", "Quantidade", "Pedido"],
    )
    df, meta = MC.preparar_df(buf, "SCM")
    assert df is not None
    assert meta["header"] == 0
    assert MC._coluna(df, ["Pedido"]) == "Pedido"


def _xlsx_header_offset(header, data_rows, n_filler=3, sheet="SC7"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for _ in range(n_filler):
        ws.append(["relatório gerado em ..."])  # linhas de lixo acima do cabeçalho
    ws.append(header)
    for r in data_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_preparar_df_header3_sc7():
    buf = _xlsx_header_offset(
        ["Numero PC", "Produto", "Qtd.Entregue", "Saldo", "Dt. Entrega"],
        [["PO1", "PN1", 1, 3, "2026-05-01"]],
        n_filler=3,
    )
    df, meta = MC.preparar_df(buf, "SC7")
    assert df is not None
    assert meta["header"] == 3
    assert MC._coluna(df, ["Saldo"]) == "Saldo"


def test_preparar_df_erro_sem_colunas(xlsx_factory):
    buf = xlsx_factory([["a", "b"]], ["Foo", "Bar"])
    df, meta = MC.preparar_df(buf, "SC7")
    assert df is None
    assert "erro" in meta


# ── Planilha livre v2 (colunas customizadas, retrocompatível) ────────────────
def _set_raw_monitor_livre(db, dados):
    conn = db.get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO monitor_livre (id, dados_json, data_atualizacao) VALUES (1, ?, ?)",
        (json.dumps(dados, ensure_ascii=False), "2026-01-01 00:00:00"),
    )
    conn.commit()
    conn.close()


def test_planilha_livre_vazia(db):
    pl = F.carregar_planilha_livre()
    assert pl["linhas"] == []
    assert pl["colunas"] == list("ABCDEFGHIJ")
    assert F.carregar_monitor_livre() == []


def test_planilha_livre_migra_legado(db):
    # Legado v4.4.0: uma LISTA de linhas (sem colunas explícitas).
    _set_raw_monitor_livre(db, [{"A": "x", "B": "y"}])
    pl = F.carregar_planilha_livre()
    assert pl["linhas"] == [{"A": "x", "B": "y"}]
    assert pl["colunas"] == ["A", "B"]  # derivadas das chaves
    assert F.carregar_monitor_livre() == [{"A": "x", "B": "y"}]  # shim compat


def test_planilha_livre_roundtrip_colunas(db):
    cols = ["Cliente", "Qtd", "Obs"]
    linhas = [{"Cliente": "ACME", "Qtd": "5", "Obs": "urgente"}]
    n = F.salvar_planilha_livre(cols, linhas)
    assert n == 1
    pl = F.carregar_planilha_livre()
    assert pl["colunas"] == cols
    assert pl["linhas"] == linhas


def test_planilha_livre_shims_compat(db):
    # As funções v4.4.0 continuam funcionando (lista in/out) sobre o shape novo.
    assert F.salvar_monitor_livre([{"A": "1", "B": "2"}]) == 1
    assert F.carregar_monitor_livre() == [{"A": "1", "B": "2"}]
    # E o overwrite continua sendo documento único.
    F.salvar_monitor_livre([{"A": "novo"}])
    assert F.carregar_monitor_livre() == [{"A": "novo"}]
