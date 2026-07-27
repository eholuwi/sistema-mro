"""v5.1.0 (F2) — Sincronização SCM persistente (API → mro.db).

Testa os parsers PUROS de `services/scm_sync.py` sobre fixtures reais enxutas
(`tests/fixtures/scm/`, versionadas — o app roda no servidor sem `openapi/`), o mapeamento
de status, o helper de datas, e (F2.4/F2.5) o orquestrador `sincronizar` com sessão FALSA e
banco isolado (fixture `db`).
"""

import json
from pathlib import Path

from services import scm_sync as S


_FIX = Path(__file__).parent / "fixtures" / "scm"


def _load(nome):
    return json.loads((_FIX / nome).read_text(encoding="utf-8-sig"))


# ── _data_api ─────────────────────────────────────────────────────────────────


def test_data_api_normaliza_e_trata_nulos():
    assert S._data_api("2026-07-16T11:33:17.6364895") == "2026-07-16"
    assert S._data_api("0001-01-01T00:00:00") is None
    assert S._data_api("") is None
    assert S._data_api(None) is None


# ── _mapear_status_api (reusa _status_sc_importado — mesmos rótulos do Excel) ──


def test_mapear_status_api():
    assert S._mapear_status_api("01") == "Aguardando Aprovação"
    assert S._mapear_status_api("03") == "Em Cotação"
    assert S._mapear_status_api("05") == "Pedido Emitido"
    # código desconhecido (ex.: "09") → default seguro
    assert S._mapear_status_api("09") == "Aguardando Aprovação"
    assert S._mapear_status_api(None) == "Aguardando Aprovação"


# ── normalizar_sc_api (cabeçalho do ByUser) ──────────────────────────────────


def test_normalizar_sc_api_campos():
    scs = _load("byuser.json")
    d = S.normalizar_sc_api(scs[0])
    assert d["sc_id_scm"] == 41468
    assert d["numero_sc"] == "41468"
    assert d["solicitante"] == "Julyo Oliveira"
    assert d["solicitante_codigo"] == "001053"
    assert d["centro_custo"] == "DSI"  # trim do padding Protheus
    assert d["status_code"] == "03"
    assert d["data_abertura"] == "2026-07-16"
    assert d["data_aprovacao"] == "2026-07-16"
    assert d["prioridade_critica"] is True
    assert d["cotacao_codigo"] == "CT41468"


def test_normalizar_sc_api_lista_e_robustez():
    scs = _load("byuser.json")
    normalizadas = [S.normalizar_sc_api(s) for s in scs]
    assert len(normalizadas) == 2
    assert {n["sc_id_scm"] for n in normalizadas} == {41468, 41467}
    # entradas inválidas não quebram
    assert S.normalizar_sc_api({}) is None
    assert S.normalizar_sc_api(None) is None


# ── normalizar_itens_api (items do Timeline) ─────────────────────────────────


def test_normalizar_itens_api():
    result = _load("timeline_41468.json")["result"]
    itens = S.normalizar_itens_api(result)
    assert len(itens) == 2
    a, b = itens
    assert a["part_number"] == "33AD0045"
    assert a["descricao"] == "ADAPTADOR DE TOMADA"  # trim
    assert a["quantidade"] == 10.0
    assert a["unidade"] == "UN"
    assert a["preco_unitario"] == 0.0
    assert a["data_necessidade"] == "2026-07-16"
    # 2º item: valorUnitaro (typo) → preco_unitario
    assert b["part_number"] == "56IF0080"
    assert b["preco_unitario"] == 12.5


def test_normalizar_itens_api_vazio_ou_invalido():
    assert S.normalizar_itens_api({}) == []
    assert S.normalizar_itens_api(None) == []
    assert S.normalizar_itens_api({"items": [{"produto": ""}, {"nao_tem_produto": 1}]}) == []


# ── Orquestrador `sincronizar` (sessão FALSA + banco isolado) ─────────────────

_USUARIOS_FAKE = [
    {"nome": "Julyo Oliveira", "codigo": "001053"},
    {"nome": "Brendo Martins de Lira", "codigo": "000480"},
]


def _instalar_fake_scm(monkeypatch, byuser, timelines, usuarios=None, disponivel=True):
    from services import scm_client

    # v5.6.0 — `diagnostico` passou a ser a fonte do health-check (traz latência e motivo
    # do erro); `esta_disponivel` deriva dele. Fingir os dois mantém coerência.
    monkeypatch.setattr(
        scm_client,
        "diagnostico",
        lambda *a, **k: {
            "ok": disponivel,
            "latencia_ms": 1,
            "erro": None if disponivel else "ConnectionError: fake offline",
            "endpoint": "http://fake/api/Usuario/Compradores",
        },
    )
    monkeypatch.setattr(scm_client, "esta_disponivel", lambda *a, **k: disponivel)
    monkeypatch.setattr(scm_client, "usuarios", lambda: list(usuarios or []))

    def _byuser(usuario, ini, fim):
        return [sc for sc in byuser if str(sc.get("solicitante")) == str(usuario)]

    def _timeline(sc_id):
        return timelines.get(int(sc_id), {"items": []})

    monkeypatch.setattr(scm_client, "sc_por_usuario", _byuser)
    monkeypatch.setattr(scm_client, "sc_timeline", _timeline)


def _seed_solicitante(db, nome):
    from services.db_functions import _normalizar_txt

    conn = db.get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO solicitantes_mro (nome, nome_norm, incluir_mro) VALUES (?,?,1)",
        (nome, _normalizar_txt(nome)),
    )
    conn.commit()
    conn.close()


def test_resolver_codigos_solicitantes(db, monkeypatch):
    _seed_solicitante(db, "Julyo Oliveira")
    _instalar_fake_scm(monkeypatch, [], {}, usuarios=_USUARIOS_FAKE)
    with db.transaction() as conn:
        n = S.resolver_codigos_solicitantes(conn)
        assert n == 1
        cod = conn.execute("SELECT codigo FROM solicitantes_mro WHERE nome='Julyo Oliveira'").fetchone()[0]
    assert cod == "001053"


def test_sincronizar_popula_scs_itens_e_externos(db, make_item, monkeypatch):
    make_item(part_number="33AD0045", nome="Adaptador de Tomada")  # casa → itens_sc
    # 56IF0080 NÃO cadastrado → itens_sc_externos
    _seed_solicitante(db, "Julyo Oliveira")
    _seed_solicitante(db, "Brendo Martins de Lira")
    byuser = _load("byuser.json")
    timelines = {41468: _load("timeline_41468.json")["result"]}
    _instalar_fake_scm(monkeypatch, byuser, timelines, usuarios=_USUARIOS_FAKE)

    resumo = S.sincronizar(periodo_dias=180, backup=False)

    assert resumo["ok"] is True
    assert resumo["solicitantes"] == 2
    assert resumo["scs"] == 2 and resumo["scs_criadas"] == 2
    assert resumo["itens"] == 1 and resumo["externos"] == 1

    conn = db.get_connection()
    sc = conn.execute("SELECT * FROM solicitacoes_compra WHERE numero_sc='41468'").fetchone()
    assert sc["sc_id_scm"] == 41468
    assert sc["status"] == "Em Cotação"
    assert sc["centro_custo"] == "DSI"
    assert sc["solicitante"] == "Julyo Oliveira"
    assert sc["prioridade_critica"] == 1
    assert sc["origem_importacao"] == "api_scm"
    isc = conn.execute(
        "SELECT descricao_detalhada, quantidade_solicitada, origem FROM itens_sc WHERE sc_id=?", (sc["id"],)
    ).fetchall()
    assert len(isc) == 1 and isc[0]["origem"] == "api_scm" and isc[0]["quantidade_solicitada"] == 10.0
    ext = conn.execute(
        "SELECT part_number, preco_unitario FROM itens_sc_externos WHERE sc_id=?", (sc["id"],)
    ).fetchall()
    assert len(ext) == 1 and ext[0]["part_number"] == "56IF0080" and ext[0]["preco_unitario"] == 12.5
    log = conn.execute("SELECT tipo FROM log_importacoes WHERE tipo='api_scm'").fetchall()
    assert len(log) == 1
    conn.close()

    assert S.ultima_sync()["detalhe"]["resumo"]["scs"] == 2


def test_sincronizar_idempotente(db, make_item, monkeypatch):
    make_item(part_number="33AD0045")
    _seed_solicitante(db, "Julyo Oliveira")
    byuser = [_load("byuser.json")[0]]  # só a SC 41468
    timelines = {41468: _load("timeline_41468.json")["result"]}
    _instalar_fake_scm(monkeypatch, byuser, timelines, usuarios=_USUARIOS_FAKE)

    S.sincronizar(backup=False)
    r2 = S.sincronizar(backup=False)  # 2º run: nada novo

    assert r2["scs_criadas"] == 0 and r2["scs_atualizadas"] == 1
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM solicitacoes_compra").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM itens_sc").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM itens_sc_externos").fetchone()[0] == 1
    conn.close()


def test_sincronizar_dedup_vs_excel_preserva_e_nao_regride(db, monkeypatch):
    # Simula uma SC já importada do Excel: mais adiantada (Pedido Emitido) e com campos
    # que só o Excel tem (comprador, PO, saving, fornecedor).
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO solicitacoes_compra (numero_sc, data_abertura, status, comprador, numero_po, "
        "saving, fornecedor, origem_importacao) "
        "VALUES ('41468','2026-07-01','Pedido Emitido','Miguel','F123',50.0,'ACME','excel')"
    )
    conn.commit()
    conn.close()
    _seed_solicitante(db, "Julyo Oliveira")
    byuser = [_load("byuser.json")[0]]
    timelines = {41468: _load("timeline_41468.json")["result"]}
    _instalar_fake_scm(monkeypatch, byuser, timelines, usuarios=_USUARIOS_FAKE)

    resumo = S.sincronizar(backup=False)

    conn = db.get_connection()
    sc = conn.execute("SELECT * FROM solicitacoes_compra WHERE numero_sc='41468'").fetchone()
    # não regride: Pedido Emitido (rank 3) > Em Cotação (rank 2) da API → mantém
    assert sc["status"] == "Pedido Emitido"
    # campos só-Excel preservados
    assert sc["comprador"] == "Miguel" and sc["numero_po"] == "F123"
    assert sc["saving"] == 50.0 and sc["fornecedor"] == "ACME"
    # API enriquece o que faltava
    assert sc["sc_id_scm"] == 41468 and sc["centro_custo"] == "DSI"
    assert conn.execute("SELECT COUNT(*) FROM solicitacoes_compra").fetchone()[0] == 1
    conn.close()
    assert resumo["divergencias"] == 1


def test_sincronizar_api_off_falha_graciosamente(db, monkeypatch):
    """API fora: nenhum dado é tocado — essa é a garantia que importa.

    v5.6.0 — o que mudou: a tentativa falha passou a deixar UMA linha de auditoria em
    `log_importacoes` (antes não deixava nada, e a tela não sabia distinguir "nunca
    sincronizou" de "tentou e a API estava fora"). Nenhuma escrita de dado acontece."""
    _seed_solicitante(db, "Julyo Oliveira")
    _instalar_fake_scm(monkeypatch, [], {}, usuarios=_USUARIOS_FAKE, disponivel=False)
    resumo = S.sincronizar(backup=False)
    assert resumo["ok"] is False and "erro" in resumo
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM solicitacoes_compra").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM itens_sc").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM itens_sc_externos").fetchone()[0] == 0
    conn.close()

    log = S.ultima_sync()
    assert log is not None, "a tentativa falha precisa ficar registrada"
    assert log["detalhe"]["status"] == "falha"
    assert "fake offline" in log["detalhe"]["erro"]
