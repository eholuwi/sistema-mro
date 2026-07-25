"""v5.2.0 (F3) — Página SCM Integrado.

Cobre as três camadas novas sem depender de rede nem de Streamlit em execução:
- `services/scm_consulta.py` — consultas puras (banco isolado, fixtures `db`/`make_sc`)
  e o "ao vivo da API" com cliente FALSO (degrada sozinho, nunca lança);
- funções PURAS de `ui/componentes/filtros.py` e `ui/componentes/tabela.py`;
- os 3 endpoints novos de `services/scm_client.py` (sessão FALSA, sem rede);
- persistência de `cotacao_codigo` no upsert do sync (F3 aditivo).
"""

import pandas as pd
import pytest

from services import scm_consulta, scm_sync
from services.db_functions import _upsert_item_sc_externo
from ui.componentes import filtros as FL
from ui.componentes import tabela as TB


# ── Helpers de seed ───────────────────────────────────────────────────────────


def _externo(db, sc_id, pn, desc="Externo", qtd=3.0, preco=9.9, origem="excel"):
    with db.transaction() as conn:
        _upsert_item_sc_externo(
            conn, sc_id, pn, desc, qtd, "UN", preco, preco * qtd, "POEXT", "2026-07-20", origem
        )


# ── scm_consulta.listar_scs_consulta ──────────────────────────────────────────


def test_listar_scs_consulta_consolida_pos_e_externos(db, make_sc):
    sc_id = make_sc(numero_sc="SC-900", part_number="PN-A", quantidade_solicitada=5)
    with db.transaction() as conn:
        conn.execute("UPDATE itens_sc SET numero_po='PO-1' WHERE sc_id=?", (sc_id,))
    _externo(db, sc_id, "PN-EXT", origem="api_scm")

    linhas = scm_consulta.listar_scs_consulta()
    assert len(linhas) == 1
    d = linhas[0]
    assert d["numero_sc"] == "SC-900"
    # PO do item interno + PO do externo, deduplicados e ordenados
    assert d["pos"] == "PO-1, POEXT"
    assert isinstance(d["prioridade_critica"], bool)


def test_listar_scs_consulta_vazio(db):
    assert scm_consulta.listar_scs_consulta() == []


# ── scm_consulta.listar_itens_consulta ────────────────────────────────────────


def test_listar_itens_consulta_marca_externos(db, make_sc):
    sc_id = make_sc(numero_sc="SC-901", part_number="PN-B", quantidade_solicitada=7)
    _externo(db, sc_id, "PN-EXT-2", origem="api_scm")

    itens = scm_consulta.listar_itens_consulta()
    assert len(itens) == 2
    por_pn = {i["part_number"]: i for i in itens}
    assert por_pn["PN-B"]["fora_do_inventario"] is False
    assert por_pn["PN-EXT-2"]["fora_do_inventario"] is True
    assert por_pn["PN-EXT-2"]["origem"] == "api_scm"
    # item interno traz descrição do inventário; externo, a sua própria
    assert por_pn["PN-B"]["descricao"] is not None


# ── scm_consulta.detalhes_sc_banco ────────────────────────────────────────────


def test_detalhes_sc_banco_estrutura(db, make_sc):
    sc_id = make_sc(numero_sc="SC-902", part_number="PN-C", quantidade_solicitada=4)
    _externo(db, sc_id, "PN-EXT-3")

    det = scm_consulta.detalhes_sc_banco("SC-902")
    assert det is not None
    assert det["cabecalho"]["numero_sc"] == "SC-902"
    assert len(det["itens"]) == 1 and det["itens"][0]["part_number"] == "PN-C"
    assert len(det["externos"]) == 1 and det["externos"][0]["part_number"] == "PN-EXT-3"
    assert isinstance(det["precos"], list)


def test_detalhes_sc_banco_inexistente(db):
    assert scm_consulta.detalhes_sc_banco("NAO-EXISTE") is None


# ── scm_consulta.detalhes_sc_api (cliente FALSO; nunca lança) ─────────────────


def test_detalhes_sc_api_offline(db, monkeypatch):
    from services import scm_client

    monkeypatch.setattr(scm_client, "esta_disponivel", lambda *a, **k: False)
    out = scm_consulta.detalhes_sc_api(41468, numero_po="F1", cotacao_codigo="CT1")
    assert out["disponivel"] is False
    assert out["itens"] is None and out["erros"] == []


def test_detalhes_sc_api_online_agrega_blocos(db, monkeypatch):
    from services import scm_client

    monkeypatch.setattr(scm_client, "esta_disponivel", lambda *a, **k: True)
    monkeypatch.setattr(
        scm_client,
        "sc_timeline",
        lambda sid: {
            "items": [
                {
                    "produto": "PN-X",
                    "quantidade": 2,
                    "um": "UN",
                    "valorUnitaro": 1.5,
                    "valorTotal": 3.0,
                    "dataNecessidade": "2026-07-16",
                }
            ]
        },
    )
    monkeypatch.setattr(scm_client, "sc_timeline_v2", lambda sid: [{"title": "Criada"}])
    monkeypatch.setattr(scm_client, "cotacao_por_codigo", lambda c: {"codigo": c})
    monkeypatch.setattr(scm_client, "pedido", lambda f, n: [{"C7_NUM": n}])
    monkeypatch.setattr(scm_client, "aprovadores_pedido", lambda f, n: [{"CR_USER": "000719"}])

    out = scm_consulta.detalhes_sc_api(41468, numero_po="F64899", cotacao_codigo="CT41468")
    assert out["disponivel"] is True
    assert out["itens"][0]["part_number"] == "PN-X"
    assert out["eventos"] == [{"title": "Criada"}]
    assert out["cotacao"] == {"codigo": "CT41468"}
    assert out["pedido"][0]["C7_NUM"] == "F64899"
    assert out["aprovadores"][0]["CR_USER"] == "000719"
    assert out["erros"] == []


def test_detalhes_sc_api_bloco_falho_nao_derruba(db, monkeypatch):
    from services import scm_client

    monkeypatch.setattr(scm_client, "esta_disponivel", lambda *a, **k: True)
    monkeypatch.setattr(scm_client, "sc_timeline", lambda sid: {"items": []})
    monkeypatch.setattr(scm_client, "sc_timeline_v2", lambda sid: [])

    def _boom(*a, **k):
        raise RuntimeError("API reciclando")

    monkeypatch.setattr(scm_client, "pedido", _boom)
    monkeypatch.setattr(scm_client, "aprovadores_pedido", _boom)

    out = scm_consulta.detalhes_sc_api(41468, numero_po="F64899")
    assert out["disponivel"] is True
    assert out["pedido"] is None and out["aprovadores"] is None
    assert len(out["erros"]) == 2  # um aviso por bloco que falhou


# ── cotacao_codigo persistido no sync (F3) ────────────────────────────────────


def test_upsert_sc_api_persiste_cotacao_codigo(db):
    cab = {
        "sc_id_scm": 41468,
        "numero_sc": "41468",
        "solicitante": "Julyo",
        "solicitante_codigo": "001053",
        "centro_custo": "DSI",
        "descricao_sc": "SC de teste",
        "status_code": "03",
        "data_abertura": "2026-07-16",
        "data_aprovacao": "2026-07-16",
        "justificativa": "urgente",
        "prioridade_critica": True,
        "cotacao_codigo": "CT41468",
    }
    resumo = scm_sync._resumo_zerado()
    with db.transaction() as conn:
        scm_sync._upsert_sc_api(conn, cab, [], resumo, [])
        row = conn.execute(
            "SELECT cotacao_codigo FROM solicitacoes_compra WHERE numero_sc='41468'"
        ).fetchone()
    assert row["cotacao_codigo"] == "CT41468"


# ── ui/componentes/filtros.py (puro) ─────────────────────────────────────────


def _df_scs():
    return pd.DataFrame(
        [
            {
                "numero_sc": "SC-1",
                "solicitante": "João",
                "status": "Em Cotação",
                "comprador": "Miguel",
                "data_abertura": "2026-07-01",
                "pos": "",
            },
            {
                "numero_sc": "SC-2",
                "solicitante": "Maria",
                "status": "Recebido",
                "comprador": "Davi",
                "data_abertura": "2026-06-01",
                "pos": "PO-9",
            },
            {
                "numero_sc": "SC-3",
                "solicitante": "José",
                "status": "Em Cotação",
                "comprador": "Miguel",
                "data_abertura": "2026-05-01",
                "pos": "",
            },
        ]
    )


def test_filtrar_texto_acento_insensivel():
    df = _df_scs()
    # "jose" casa "José" (sem acento) e "João"? não — só "José". "joao" casaria "João".
    assert set(FL._filtrar_texto(df, ["solicitante"], "jose")["numero_sc"]) == {"SC-3"}
    assert set(FL._filtrar_texto(df, ["numero_sc"], "sc-")["numero_sc"]) == {"SC-1", "SC-2", "SC-3"}
    # termo vazio → tudo
    assert len(FL._filtrar_texto(df, ["solicitante"], "")) == 3


def test_aplicar_pills_and():
    df = _df_scs()
    pills = {
        "Abertas": lambda d: ~d["status"].isin({"Recebido", "Cancelado"}),
        "Sem PO": lambda d: d["pos"].fillna("").str.strip() == "",
    }
    out = FL._aplicar_pills(df, pills, ["Abertas", "Sem PO"])
    assert set(out["numero_sc"]) == {"SC-1", "SC-3"}
    # nenhum pill → df inteiro
    assert len(FL._aplicar_pills(df, pills, [])) == 3


def test_filtrar_periodo_e_multiselect():
    df = _df_scs()
    dentro = FL._filtrar_periodo(df, "data_abertura", pd.Timestamp("2026-05-15"), pd.Timestamp("2026-07-15"))
    assert set(dentro["numero_sc"]) == {"SC-1", "SC-2"}
    so_miguel = FL._filtrar_multiselect(df, "comprador", ["Miguel"])
    assert set(so_miguel["numero_sc"]) == {"SC-1", "SC-3"}


# ── ui/componentes/tabela.py (puro) ──────────────────────────────────────────


def test_paginar():
    df = pd.DataFrame({"x": range(0, 125)})
    fatia, total, pagina = TB._paginar(df, pagina=0, page_size=50)
    assert len(fatia) == 50 and total == 3 and pagina == 0
    fatia, total, pagina = TB._paginar(df, pagina=2, page_size=50)
    assert len(fatia) == 25 and pagina == 2
    # página fora do intervalo é corrigida para a última
    fatia, total, pagina = TB._paginar(df, pagina=9, page_size=50)
    assert pagina == 2
    # page_size<=0 desliga a paginação
    fatia, total, pagina = TB._paginar(df, pagina=0, page_size=0)
    assert len(fatia) == 125 and total == 1


# ── services/scm_client.py — 3 endpoints novos (sessão FALSA) ─────────────────


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_session(monkeypatch, capturar):
    from services import scm_client

    def _get(url, timeout=None):
        capturar["url"] = url
        return _FakeResp(capturar["payload"])

    monkeypatch.setattr(scm_client._session, "get", _get)


def test_sc_timeline_v2_endpoint(monkeypatch):
    from services import scm_client

    cap = {"payload": {"succeeded": True, "errors": [], "result": [{"title": "Criada"}]}}
    _fake_session(monkeypatch, cap)
    scm_client.sc_timeline_v2.clear()
    out = scm_client.sc_timeline_v2(41468)
    assert cap["url"].endswith("/SolicitacaoCompras/Timelinev2/41468")
    assert out == [{"title": "Criada"}]


def test_cotacao_por_codigo_endpoint(monkeypatch):
    from services import scm_client

    cap = {"payload": {"succeeded": True, "errors": [], "result": {"codigo": "CT41468"}}}
    _fake_session(monkeypatch, cap)
    scm_client.cotacao_por_codigo.clear()
    out = scm_client.cotacao_por_codigo("CT41468")
    assert cap["url"].endswith("/Cotacao/GetByCodigo/CT41468")
    assert out == {"codigo": "CT41468"}


def test_aprovadores_pedido_endpoint(monkeypatch):
    from services import scm_client

    cap = {"payload": [{"CR_USER": "000719", "CR_STATUS": "02"}]}
    _fake_session(monkeypatch, cap)
    scm_client.aprovadores_pedido.clear()
    out = scm_client.aprovadores_pedido("01", "F64899")
    assert cap["url"].endswith("/Pedidos/getAprovadores/01/F64899")
    assert out[0]["CR_USER"] == "000719"
