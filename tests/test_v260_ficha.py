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


_req_seq = 0


def _saida(item_id, qtd, centro_custo="", setor="", quando=None, requisicao=True):
    """Insere uma SAÍDA direta em movimentacoes (determinístico p/ agregação).

    v2.7.1: 'quem consome' passou a contar só CONSUMO REAL (saída por requisição),
    então por padrão geramos uma linha em `requisicoes` e ligamos via requisicao_id.
    `requisicao=False` simula um ajuste/inventário (não deve ser contado)."""
    global _req_seq
    quando = quando or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    req_id = None
    with database.transaction() as c:
        if requisicao:
            _req_seq += 1
            cur = c.execute(
                "INSERT INTO requisicoes (numero_requisicao, data_hora, setor, emitente, centro_custo) "
                "VALUES (?,?,?,?,?)",
                (
                    f"REQ-T{_req_seq}",
                    quando,
                    setor or "MANUTENÇÃO",
                    "t",
                    centro_custo or "21106 - MANUTENÇÃO",
                ),
            )
            req_id = cur.lastrowid
        c.execute(
            """INSERT INTO movimentacoes
                 (item_id,tipo,quantidade,saldo_apos,data_hora,centro_custo,setor,
                  solicitante,emitente,observacao,requisicao_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (item_id, "saida", qtd, 0, quando, centro_custo, setor, "t", "t", "", req_id),
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
    assert cc["21106 - MANUTENÇÃO"]["pct"] == 80.0  # 40/50
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


def test_quem_consome_ignora_ajuste_sem_requisicao(db, make_item):
    # v2.7.1: só CONSUMO REAL (requisição) conta como "quem consome". Ajustes
    # (ex.: "Inventário", retirada sem requisição) NÃO devem aparecer.
    item_id = make_item("PN-DEP4", estoque=1000, minimo=10)
    _saida(item_id, 40, centro_custo="21106 - MANUTENÇÃO", setor="MANUTENÇÃO")  # requisição real
    _saida(
        item_id, 999, centro_custo="INVENTÁRIO", setor="INVENTÁRIO", requisicao=False
    )  # ajuste — não conta
    dep = ficha.obter_consumo_por_departamento(item_id)
    chaves = {r["chave"] for r in dep["por_centro_custo"]}
    assert "INVENTÁRIO" not in chaves
    assert dep["total"] == 40
    assert dep["por_centro_custo"][0]["chave"] == "21106 - MANUTENÇÃO"


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
    assert arquivos == [f"item_{item_id}.jpg"]  # png antigo removido
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
    "item",
    "imagem_path",
    "imagem_abs",
    "reposicao",
    "giro",
    "valor",
    "abc",
    "fornecedores",
    "melhor_fornecedor",
    "departamentos",
    "movimentacoes",
    "scs_pos",
    "evolucao_preco",
    "historico_pn",
    "maturidade",
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
    assert f["reposicao"]["precisa"] is True  # estoque 8 < mínimo 10


# ── Saldo Residual (Guarda-Chuva) por Fornecedor — v3.1.0 (fundação) ─────────


def test_agrupar_saldo_residual_ignora_pedidos_sem_saldo():
    scs_pos = [
        {"numero_sc": "SC-1", "fornecedor_item": "Fornecedor A", "pendente": 0, "quantidade_recebida": 10},
    ]
    assert ficha.agrupar_saldo_residual_por_fornecedor(scs_pos) == []


def test_agrupar_saldo_residual_soma_por_fornecedor():
    scs_pos = [
        {
            "numero_sc": "SC-1",
            "numero_po": "PO-1",
            "status": "Parcial",
            "fornecedor_item": "Fornecedor A",
            "quantidade_negociada": 10,
            "quantidade_recebida": 4,
            "pendente": 6,
            "preco_unitario": 12.5,
            "valor_total": 125.0,
            "moeda": "BRL",
        },
        {
            "numero_sc": "SC-2",
            "numero_po": "PO-2",
            "status": "Aberto",
            "fornecedor_item": "Fornecedor A",
            "quantidade_negociada": 20,
            "quantidade_recebida": 0,
            "pendente": 20,
            "preco_unitario": 12.5,
            "valor_total": 250.0,
            "moeda": "BRL",
        },
        {
            "numero_sc": "SC-3",
            "numero_po": "PO-3",
            "status": "Aberto",
            "fornecedor_item": "Fornecedor B",
            "quantidade_negociada": 5,
            "quantidade_recebida": 0,
            "pendente": 5,
            "preco_unitario": 8.0,
            "valor_total": 40.0,
            "moeda": "BRL",
        },
    ]
    grupos = ficha.agrupar_saldo_residual_por_fornecedor(scs_pos)
    assert [g["fornecedor"] for g in grupos] == ["Fornecedor A", "Fornecedor B"]  # maior saldo primeiro
    a = grupos[0]
    assert a["saldo_pendente"] == 26
    assert a["n_pedidos"] == 2
    assert any(l["entrega_parcial"] for l in a["linhas"])  # SC-1 recebeu parte
    assert not any(l["entrega_parcial"] for l in grupos[1]["linhas"])  # Fornecedor B: nada recebido ainda


def test_agrupar_saldo_residual_sem_fornecedor_usa_rotulo_padrao():
    scs_pos = [{"numero_sc": "SC-9", "fornecedor_item": None, "quantidade_recebida": 0, "pendente": 3}]
    grupos = ficha.agrupar_saldo_residual_por_fornecedor(scs_pos)
    assert grupos[0]["fornecedor"] == "Sem fornecedor"
