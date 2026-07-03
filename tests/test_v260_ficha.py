"""v2.6.0 — Ficha 360 do Material.

Cobre as PEÇAS NOVAS (o resto da ficha é montagem de funções já testadas):
consumo por departamento/centro de custo, imagem do produto (save/remove/validação,
com isolamento via docs/itens/ ancorado ao diretório do banco de teste) e o
assembler `montar_ficha_360` (item cheio, item vazio, inexistente). Nada aqui
altera a base do Neidson.
"""
from datetime import datetime

import pytest

import database
from services import db_functions as F
from services import ficha


def _saida(item_id, qtd, centro_custo="", setor="", quando=None):
    """Insere uma SAÍDA direta em movimentacoes (determinístico p/ agregação)."""
    quando = quando or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with database.transaction() as c:
        c.execute(
            """INSERT INTO movimentacoes
                 (item_id,tipo,quantidade,saldo_apos,data_hora,centro_custo,setor,
                  solicitante,emitente,observacao)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (item_id, "saida", qtd, 0, quando, centro_custo, setor, "t", "t", ""),
        )


# ── Schema ──────────────────────────────────────────────────────────────────

def test_schema_imagem_path(db):
    with database.transaction() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(inventario)")}
    assert "imagem_path" in cols


# ── Consumo por departamento / centro de custo ──────────────────────────────

def test_consumo_por_departamento_agrega_e_percentua(db, make_item):
    item_id = make_item("PN-DEP", estoque=1000, minimo=10)
    _saida(item_id, 30, centro_custo="21106 - MANUTENÇÃO", setor="MANUTENÇÃO")
    _saida(item_id, 10, centro_custo="21106 - MANUTENÇÃO", setor="MANUTENÇÃO")
    _saida(item_id, 10, centro_custo="21194 - ALMOXARIFADO", setor="ALMOXARIFADO")

    dep = ficha.obter_consumo_por_departamento(item_id)
    assert dep["total"] == 50
    cc = {r["chave"]: r for r in dep["por_centro_custo"]}
    assert cc["21106 - MANUTENÇÃO"]["qtd"] == 40
    assert cc["21106 - MANUTENÇÃO"]["pct"] == 80.0        # 40/50
    assert cc["21194 - ALMOXARIFADO"]["pct"] == 20.0
    # Ordenado do maior p/ o menor.
    assert dep["por_centro_custo"][0]["chave"] == "21106 - MANUTENÇÃO"
    setores = {r["chave"]: r for r in dep["por_setor"]}
    assert setores["MANUTENÇÃO"]["qtd"] == 40


def test_consumo_por_departamento_vazio_para_null(db, make_item):
    item_id = make_item("PN-DEP2", estoque=100, minimo=10)
    _saida(item_id, 5)  # sem centro de custo / setor
    dep = ficha.obter_consumo_por_departamento(item_id)
    assert dep["por_centro_custo"][0]["chave"] == "(não informado)"
    assert dep["total"] == 5


def test_consumo_sem_saidas(db, make_item):
    item_id = make_item("PN-DEP3", estoque=100, minimo=10)
    dep = ficha.obter_consumo_por_departamento(item_id)
    assert dep["por_centro_custo"] == []
    assert dep["total"] == 0


# ── Imagem do produto (isolada em tmp via DB_PATH monkeypatchado no fixture db) ──

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64  # bytes quaisquer com extensão válida


def test_salvar_imagem_grava_arquivo_e_path(db, make_item):
    item_id = make_item("PN-IMG", estoque=10, minimo=1)
    ok, rel = ficha.salvar_imagem_item(item_id, "foto.png", _PNG)
    assert ok, rel
    assert rel == f"docs/itens/item_{item_id}.png"
    abs_path = ficha.caminho_absoluto_imagem(rel)
    assert abs_path and abs_path.endswith(f"item_{item_id}.png")
    import os
    assert os.path.exists(abs_path)
    it = F.buscar_item_por_id(item_id)
    assert it["imagem_path"] == rel


def test_salvar_imagem_rejeita_formato(db, make_item):
    item_id = make_item("PN-IMG2", estoque=10, minimo=1)
    ok, msg = ficha.salvar_imagem_item(item_id, "doc.txt", _PNG)
    assert ok is False
    assert "Formato" in msg
    assert F.buscar_item_por_id(item_id)["imagem_path"] is None


def test_salvar_imagem_rejeita_tamanho(db, make_item):
    item_id = make_item("PN-IMG3", estoque=10, minimo=1)
    grande = b"0" * (ficha.IMAGEM_MAX_BYTES + 1)
    ok, msg = ficha.salvar_imagem_item(item_id, "foto.jpg", grande)
    assert ok is False and "limite" in msg


def test_troca_de_formato_nao_deixa_orfao(db, make_item):
    import os
    item_id = make_item("PN-IMG4", estoque=10, minimo=1)
    ficha.salvar_imagem_item(item_id, "a.png", _PNG)
    ok, rel = ficha.salvar_imagem_item(item_id, "b.jpg", _PNG)
    assert ok
    arquivos = sorted(os.listdir(ficha._itens_dir()))
    assert arquivos == [f"item_{item_id}.jpg"]        # png antigo removido
    assert F.buscar_item_por_id(item_id)["imagem_path"] == rel


def test_remover_imagem(db, make_item):
    import os
    item_id = make_item("PN-IMG5", estoque=10, minimo=1)
    _, rel = ficha.salvar_imagem_item(item_id, "foto.png", _PNG)
    abs_path = ficha.caminho_absoluto_imagem(rel)
    assert os.path.exists(abs_path)
    ok, _ = ficha.remover_imagem_item(item_id)
    assert ok
    assert not os.path.exists(abs_path)
    assert F.buscar_item_por_id(item_id)["imagem_path"] is None


# ── Assembler ───────────────────────────────────────────────────────────────

_CHAVES_FICHA = {
    "item", "imagem_path", "imagem_abs", "reposicao", "giro", "valor", "abc",
    "fornecedores", "melhor_fornecedor", "departamentos", "movimentacoes",
    "scs_pos", "evolucao_preco", "historico_pn", "maturidade",
}


def test_montar_ficha_item_inexistente(db):
    assert ficha.montar_ficha_360(999999) is None


def test_montar_ficha_item_vazio(db, make_item):
    item_id = make_item("PN-F0", estoque=5, minimo=2)
    f = ficha.montar_ficha_360(item_id)
    assert _CHAVES_FICHA <= set(f.keys())
    assert f["item"]["id"] == item_id
    # Sem consumo: nenhuma saída (o estoque inicial gera só uma 'entrada' no ledger).
    assert all(m["tipo"] != "saida" for m in f["movimentacoes"])
    assert f["fornecedores"] == []
    assert f["departamentos"]["total"] == 0
    assert f["imagem_abs"] is None
    # Recomendação de reposição presente e coerente (reusa v2.5).
    assert "qtd_sugerida" in f["reposicao"]


def test_montar_ficha_item_cheio(db, make_item, make_sc):
    item_id = make_item("PN-F1", estoque=8, minimo=10, lead=10)
    _saida(item_id, 20, centro_custo="21106 - MANUTENÇÃO", setor="MANUTENÇÃO")
    make_sc(numero_sc="SC-F1", item_id=item_id, quantidade_solicitada=30)
    with database.transaction() as c:
        c.execute(
            """INSERT INTO precos_historico
                 (item_id,data,preco_unitario,moeda,numero_po,origem)
               VALUES (?,?,?,?,?,?)""",
            (item_id, "2026-06-01", 12.5, "BRL", "PO-F1", "SCM"),
        )
    ficha.salvar_imagem_item(item_id, "foto.png", _PNG)

    f = ficha.montar_ficha_360(item_id)
    assert _CHAVES_FICHA <= set(f.keys())
    assert f["departamentos"]["total"] == 20
    assert len(f["scs_pos"]) >= 1
    assert len(f["evolucao_preco"]) >= 1
    assert f["imagem_abs"] is not None
    assert f["reposicao"]["precisa"] is True     # estoque 8 < mínimo 10
