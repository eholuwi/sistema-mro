"""v2.4.0 — Fornecedores & Cotação.

Modelo (validado nos dados reais): o elo confiável é o Nº DO PEDIDO (numero_po).
`itens_sc.fornecedor_item` dá PO→fornecedor (Nome Fantasia real); `precos_historico`
dá PO→preço (SCM/SC7) e lead time (SC7). O join por numero_po reconstrói preço +
lead time por fornecedor. Nomes inválidos ('1.0'/'None') são descartados. Também
cobre a persistência do lead time por linha SC7 (precos_historico.lead_time_dias)."""
import pandas as pd
from services import db_functions as F
import database


# ── Helpers de seed ────────────────────────────────────────────────────────────

def _compra(make_sc, item_id, numero_sc, numero_po, fornecedor):
    """Linha de SC (itens_sc) amarrando item → (numero_po, fornecedor_item),
    como faz a ingestão da aba SCM."""
    sc_id = make_sc(numero_sc=numero_sc, item_id=item_id)
    with database.transaction() as c:
        c.execute(
            "UPDATE itens_sc SET numero_po=?, fornecedor_item=? WHERE sc_id=? AND item_id=?",
            (numero_po, fornecedor, sc_id, item_id))


def _preco(item_id, numero_po, preco, data="2026-01-01", origem="SCM", lead=None, moeda="BRL"):
    """Preço por PO em precos_historico (SCM ou SC7); `lead` só para SC7."""
    with database.transaction() as c:
        c.execute(
            """INSERT INTO precos_historico
               (item_id,data,preco_unitario,moeda,fornecedor,numero_sc,numero_po,origem,lead_time_dias)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (item_id, data, preco, moeda, None, None, numero_po, origem, lead))


def _add_fornecedor(codigo, nome_fantasia, email="", razao="", loja="1",
                    telefone="", contato=""):
    with database.transaction() as c:
        c.execute(
            """INSERT INTO fornecedores
               (codigo,loja,razao_social,nome_fantasia,cnpj,email,telefone,contato,
                cond_pagto,ativo,ultima_importacao)
               VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
            (codigo, loja, razao, nome_fantasia, "", email, telefone, contato,
             "", "2026-01-01"))


# ── Schema ─────────────────────────────────────────────────────────────────────

def test_schema_tem_lead_time_dias(db):
    with database.transaction() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(precos_historico)")}
    assert "lead_time_dias" in cols


# ── Agregação por fornecedor (PO → fornecedor → preço) ─────────────────────────

def test_agrega_por_fornecedor_ultimo_preco(db, make_item, make_sc):
    item_id = make_item("PN-F1", estoque=10)
    _compra(make_sc, item_id, "SC-1", "POA1", "Forn A")
    _compra(make_sc, item_id, "SC-2", "POA2", "Forn A")
    _compra(make_sc, item_id, "SC-3", "POB1", "Forn B")
    _preco(item_id, "POA1", 12.0, "2026-01-01")
    _preco(item_id, "POA2", 10.0, "2026-03-01")   # mais recente
    _preco(item_id, "POB1", 20.0, "2026-02-01")
    fs = F.obter_fornecedores_por_item(item_id)
    por = {f["fornecedor"]: f for f in fs}
    assert por["Forn A"]["ultimo_preco"] == 10.0   # mais recente
    assert por["Forn A"]["n_compras"] == 2         # 2 POs
    assert por["Forn A"]["preco_min"] == 10.0
    assert por["Forn A"]["preco_max"] == 12.0
    assert por["Forn B"]["n_compras"] == 1


def test_item_sem_historico_retorna_vazio(db, make_item):
    item_id = make_item("PN-F7", estoque=10)
    assert F.obter_fornecedores_por_item(item_id) == []


# ── Nome inválido é descartado (achado dos dados reais: '1.0' = nº da loja) ─────

def test_descarta_nome_invalido_tipo_loja(db, make_item, make_sc):
    item_id = make_item("PN-F8", estoque=10)
    _compra(make_sc, item_id, "SC-1", "PO-1", "1.0")       # lixo
    _compra(make_sc, item_id, "SC-2", "PO-2", "Forn Bom")
    _preco(item_id, "PO-1", 5.0, "2026-01-01")
    _preco(item_id, "PO-2", 7.0, "2026-01-01")
    fs = F.obter_fornecedores_por_item(item_id)
    assert [f["fornecedor"] for f in fs] == ["Forn Bom"]


# ── Casamento com o cadastro (SA1) ─────────────────────────────────────────────

def test_casamento_cadastro_normalizado_traz_email(db, make_item, make_sc):
    item_id = make_item("PN-F2", estoque=10)
    _compra(make_sc, item_id, "SC-1", "PO1", "  SKF Brasil  ")   # espaços/caixa
    _preco(item_id, "PO1", 5.0, "2026-01-01")
    _add_fornecedor("F001", "skf brasil", email="vendas@skf.com", contato="João")
    fs = F.obter_fornecedores_por_item(item_id)
    assert len(fs) == 1
    assert fs[0]["email"] == "vendas@skf.com"
    assert fs[0]["contato"] == "João"
    assert fs[0]["no_cadastro"] is True


def test_sem_correspondencia_lista_sem_email(db, make_item, make_sc):
    item_id = make_item("PN-F3", estoque=10)
    _compra(make_sc, item_id, "SC-1", "PO1", "Fornecedor Desconhecido")
    _preco(item_id, "PO1", 5.0, "2026-01-01")
    fs = F.obter_fornecedores_por_item(item_id)
    assert len(fs) == 1
    assert fs[0]["email"] is None
    assert fs[0]["no_cadastro"] is False


# ── Melhor fornecedor = menor último preço ─────────────────────────────────────

def test_melhor_fornecedor_menor_ultimo_preco(db, make_item, make_sc):
    item_id = make_item("PN-F4", estoque=10)
    _compra(make_sc, item_id, "SC-1", "P1", "Caro")
    _compra(make_sc, item_id, "SC-2", "P2", "Barato")
    _preco(item_id, "P1", 15.0, "2026-01-01")
    _preco(item_id, "P2", 9.0, "2026-01-01")
    fs = F.obter_fornecedores_por_item(item_id)
    assert fs[0]["fornecedor"] == "Barato"          # ordenado por menor preço
    assert fs[0]["melhor"] is True
    assert "Menor último preço" in fs[0]["melhor_motivo"]
    assert all(not f["melhor"] for f in fs[1:])


def test_fornecedor_sem_preco_nao_e_melhor(db, make_item, make_sc):
    item_id = make_item("PN-F9", estoque=10)
    _compra(make_sc, item_id, "SC-1", "PO-1", "Com Preço")
    _compra(make_sc, item_id, "SC-2", "PO-2", "Sem Preço")
    _preco(item_id, "PO-1", 8.0, "2026-01-01")      # só PO-1 tem preço
    fs = F.obter_fornecedores_por_item(item_id)
    por = {f["fornecedor"]: f for f in fs}
    assert por["Sem Preço"]["ultimo_preco"] is None
    assert por["Sem Preço"]["melhor"] is False
    assert por["Com Preço"]["melhor"] is True
    assert fs[0]["fornecedor"] == "Com Preço"        # com preço vem primeiro


# ── Lead time por fornecedor (SC7 × itens_sc via nº do pedido) ─────────────────

def test_lead_time_por_fornecedor_via_po(db, make_item, make_sc):
    item_id = make_item("PN-F5", estoque=10)
    _compra(make_sc, item_id, "SC-500", "PO-100", "Forn LT")
    _preco(item_id, "PO-100", 10.0, "2026-01-01", origem="SC7", lead=8)
    _preco(item_id, "PO-100", 10.5, "2026-01-02", origem="SC7", lead=12)
    fs = F.obter_fornecedores_por_item(item_id)
    f = next(x for x in fs if x["fornecedor"] == "Forn LT")
    assert f["lead_time_amostras"] == 2
    assert f["lead_time_fornecedor"] == 10          # mediana(8, 12) = 10


def test_po_sem_match_nao_atribui_lead_time(db, make_item, make_sc):
    item_id = make_item("PN-F6", estoque=10)
    _compra(make_sc, item_id, "SC-1", "PO-1", "Forn X")
    _preco(item_id, "PO-1", 10.0, "2026-01-01")
    _preco(item_id, "PO-999", 10.0, "2026-01-01", origem="SC7", lead=9)  # PO sem itens_sc
    fs = F.obter_fornecedores_por_item(item_id)
    f = next(x for x in fs if x["fornecedor"] == "Forn X")
    assert f["lead_time_fornecedor"] is None
    assert f["lead_time_amostras"] == 0


# ── Ingestão SC7: grava e faz backfill de lead_time_dias ───────────────────────

def test_sc7_ingestao_grava_lead_time_dias(db, make_item):
    item_id = make_item("PN-LT1", estoque=10)
    df = pd.DataFrame([{
        "Produto": "PN-LT1", "Pedido": "PO-1",
        "DT Emissao": "2026-01-01", "Dt. Entrega": "2026-01-08",  # delta = 7
        "Qtd.Entregue": 3, "Prc Unitario": 20.0, "Moeda": "BRL",
        "Observacoes": "SC: 123",
    }])
    res = F.ingerir_sc7_precos(df)
    assert res.get("precos_inseridos") == 1
    with database.transaction() as c:
        row = c.execute(
            "SELECT lead_time_dias FROM precos_historico WHERE item_id=? AND origem='SC7'",
            (item_id,)).fetchone()
    assert row["lead_time_dias"] == 7


def test_sc7_reimport_backfill_lead_time(db, make_item):
    item_id = make_item("PN-LT2", estoque=10)
    _preco(item_id, "PO-7", 30.0, "2026-01-01", origem="SC7", lead=None)  # linha pré-v2.4.0
    df = pd.DataFrame([{
        "Produto": "PN-LT2", "Pedido": "PO-7",
        "DT Emissao": "2026-02-01", "Dt. Entrega": "2026-02-11",  # delta = 10
        "Qtd.Entregue": 2, "Prc Unitario": 30.0, "Moeda": "BRL",
        "Observacoes": "",
    }])
    F.ingerir_sc7_precos(df)
    with database.transaction() as c:
        rows = c.execute(
            "SELECT lead_time_dias FROM precos_historico WHERE item_id=? AND origem='SC7'",
            (item_id,)).fetchall()
    assert len(rows) == 1               # dedup: não duplicou
    assert rows[0]["lead_time_dias"] == 10   # backfill idempotente


# ── v3.1.0: busca de materiais em Fornecedores & Cotação (PN, nome ou descrição) ──

_ITENS_BUSCA = [
    {"part_number": "10PP0001", "nome_item": "BOBINA TERMICA TAM.76X30M", "descricao": ""},
    {"part_number": "10PP0008", "nome_item": "PAPEL OFICIO BRANCO A4",
     "descricao": "Consumo: 4 resma por dia"},
    {"part_number": "20AB0002", "nome_item": "LUVA DE PROCEDIMENTO", "descricao": None},
]


def test_filtrar_itens_por_busca_vazio_retorna_tudo():
    assert F.filtrar_itens_por_busca(_ITENS_BUSCA, "") == _ITENS_BUSCA


def test_filtrar_itens_por_busca_por_part_number():
    r = F.filtrar_itens_por_busca(_ITENS_BUSCA, "10pp0001")
    assert [i["part_number"] for i in r] == ["10PP0001"]


def test_filtrar_itens_por_busca_por_nome():
    r = F.filtrar_itens_por_busca(_ITENS_BUSCA, "luva")
    assert [i["part_number"] for i in r] == ["20AB0002"]


def test_filtrar_itens_por_busca_por_descricao():
    # só encontrável pela descrição (não aparece no PN nem no nome do item)
    r = F.filtrar_itens_por_busca(_ITENS_BUSCA, "resma")
    assert [i["part_number"] for i in r] == ["10PP0008"]


def test_filtrar_itens_por_busca_sem_match():
    assert F.filtrar_itens_por_busca(_ITENS_BUSCA, "inexistente") == []
