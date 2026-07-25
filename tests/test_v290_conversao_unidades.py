"""v2.9.0 — Conversão de Unidades (Fundação + Recebimento).

O item é CADASTRADO numa unidade de estoque (base do Neidson) mas COMPRADO em outra
(litro, par, bombona…). Esta suíte cobre a fundação de dados da conversão:
  - migração aditiva (colunas novas, idempotente);
  - regex de embalagem (fator sugerido da descrição/nome);
  - sugestão + persistência CURADA do fator (o sistema sugere, o gestor confirma);
  - captura da UM na ingestão (SCM/SC7 → precos_historico.unidade);
  - CONVERSÃO no recebimento (5 L com fator 5 → +1 GL; itens_sc segue na UM de compra);
  - exibição dupla no Assistente (qtd de compra) e sinal forward-only de UM divergente.
Princípio do PO: assistente, não piloto automático; base do Neidson intacta; default no-op.
"""

import math

import pandas as pd
import pytest

import database
from services import db_functions as F
from services import planejamento as P
from services.constants import extrair_fator_embalagem


CC = "21194 - ALMOXARIFADO"


# ══════════════════════════════════════════════════════════════════════════════
# MIGRAÇÃO ADITIVA
# ══════════════════════════════════════════════════════════════════════════════


def _cols(tabela):
    with database.transaction() as c:
        return {r[1] for r in c.execute(f"PRAGMA table_info({tabela})")}


def test_migracao_colunas_existem(db):
    assert {"unidade_compra", "fator_conversao"} <= _cols("inventario")
    assert "unidade" in _cols("precos_historico")


def test_fator_default_1(db, make_item):
    make_item("PN-DEF")
    with database.transaction() as c:
        r = c.execute(
            "SELECT fator_conversao, unidade_compra FROM inventario WHERE part_number='PN-DEF'"
        ).fetchone()
    assert r["fator_conversao"] == 1
    assert r["unidade_compra"] is None  # no-op: usa a unidade de estoque


def test_migracao_idempotente(db):
    # Rodar criar_banco de novo não deve duplicar colunas nem quebrar.
    database.criar_banco()
    assert {"unidade_compra", "fator_conversao"} <= _cols("inventario")
    assert "unidade" in _cols("precos_historico")


# ══════════════════════════════════════════════════════════════════════════════
# REGEX DE EMBALAGEM (fator sugerido)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("SOLVENTE ALFATEC BOMBONA C/ 5,0 LT", 5.0),
        ("GRAMPO CX C/ 4000PCS", 4000.0),
        ("AGUA DESMINERALIZADA GL C/ 5L", 5.0),
        ("CAIXA COM 12 UN", 12.0),
        ("LUVA CX C/ 100 PARES", 100.0),
        ("FRASCO C/ 2,5 ML", 2.5),
        ("CAIXA C/ 1.000 UN", 1000.0),  # ponto como milhar PT-BR
        ("ROLO PANO WIPER", None),  # sem padrão claro
        ("PAPEL TOALHA", None),
        ("SOLVENTE ALFATEC 1200", None),  # número de modelo não vira fator (sem "C/")
        ("", None),
        (None, None),
    ],
)
def test_extrair_fator_embalagem(texto, esperado):
    assert extrair_fator_embalagem(texto) == esperado


# ══════════════════════════════════════════════════════════════════════════════
# sugerir_conversao — o sistema SUGERE (não persiste)
# ══════════════════════════════════════════════════════════════════════════════


def test_sugerir_conversao_fator_do_nome(db, make_item):
    make_item("PN-SOLV", nome="SOLVENTE ALFATEC 1200 BOMBONA C/ 5,0 LT", unidade="GL")
    item = next(i for i in F.listar_inventario() if i["part_number"] == "PN-SOLV")
    sug = F.sugerir_conversao(item)
    assert sug["fator_sugerido"] == 5.0
    assert "descrição" in sug["origem"].lower()


def test_sugerir_conversao_sem_padrao(db, make_item):
    make_item("PN-SEMPAD", nome="ROLO PANO WIPER", unidade="UN")
    item = next(i for i in F.listar_inventario() if i["part_number"] == "PN-SEMPAD")
    sug = F.sugerir_conversao(item)
    assert sug["fator_sugerido"] is None  # não inventa fator
    assert "manualmente" in sug["origem"].lower()


def test_sugerir_conversao_um_observada(db, make_item):
    iid = make_item("PN-UOBS", nome="SOLVENTE GENERICO", unidade="GL")
    # UM observada nos POs = L (capturada da ingestão)
    with database.transaction() as c:
        c.execute(
            "INSERT INTO precos_historico (item_id, data, preco_unitario, origem, unidade) "
            "VALUES (?,?,?,?,?)",
            (iid, "2026-06-01", 10.0, "SC7", "L"),
        )
    item = next(i for i in F.listar_inventario() if i["id"] == iid)
    sug = F.sugerir_conversao(item)
    assert sug["unidade_compra_sugerida"] == "L"  # diverge da de estoque (GL)


# ══════════════════════════════════════════════════════════════════════════════
# mapear_unidade_compra_por_item — UM mais frequente
# ══════════════════════════════════════════════════════════════════════════════


def test_mapear_unidade_compra_mais_frequente(db, make_item):
    iid = make_item("PN-MAP", unidade="GL")
    linhas = [("2026-01-01", "L"), ("2026-02-01", "L"), ("2026-03-01", "KG")]
    with database.transaction() as c:
        for data, un in linhas:
            c.execute(
                "INSERT INTO precos_historico (item_id,data,preco_unitario,origem,unidade) "
                "VALUES (?,?,?,?,?)",
                (iid, data, 5.0, "SC7", un),
            )
    mapa = F.mapear_unidade_compra_por_item([iid])
    assert mapa[iid] == "L"  # 2× L vs 1× KG


def test_mapear_unidade_compra_ignora_vazio(db, make_item):
    iid = make_item("PN-MAP2", unidade="GL")
    with database.transaction() as c:
        c.execute(
            "INSERT INTO precos_historico (item_id,data,preco_unitario,origem,unidade) VALUES (?,?,?,?,?)",
            (iid, "2026-01-01", 5.0, "SC7", None),
        )
    assert iid not in F.mapear_unidade_compra_por_item([iid])


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTÊNCIA CURADA (salvar_item / atualizar_item_inventario)
# ══════════════════════════════════════════════════════════════════════════════


def test_salvar_item_novo_grava_conversao(db):
    ok, msg = F.salvar_item(
        "PN-NOVO",
        "Solvente",
        "",
        "GL",
        "Importante",
        "Consumivel",
        "Improdutivo",
        "ARM-01",
        "",
        0,
        10,
        7,
        unidade_compra="L",
        fator_conversao=5,
    )
    assert ok, msg
    it = next(i for i in F.listar_inventario() if i["part_number"] == "PN-NOVO")
    assert it["unidade_compra"] == "L"
    assert it["fator_conversao"] == 5


def test_atualizar_item_grava_conversao(db, make_item):
    iid = make_item("PN-UPD", unidade="GL")
    ok, msg = F.atualizar_item_inventario(iid, {"unidade_compra": "L", "fator_conversao": 5})
    assert ok, msg
    it = F.buscar_item_por_id(iid)
    assert it["unidade_compra"] == "L"
    assert it["fator_conversao"] == 5


def test_salvar_item_coalesce_preserva(db, make_item):
    """Na edição via salvar_item, None NÃO sobrescreve o fator já curado (COALESCE)."""
    iid = make_item("PN-COAL", unidade="GL")
    F.atualizar_item_inventario(iid, {"unidade_compra": "L", "fator_conversao": 5})
    # salvar_item de edição SEM passar conversão → preserva o que o gestor curou.
    ok, _ = F.salvar_item(
        "PN-COAL",
        "Novo Nome",
        "",
        "GL",
        "Importante",
        "Consumivel",
        "Improdutivo",
        "ARM-01",
        "",
        0,
        10,
        7,
        item_id=iid,
    )
    assert ok
    it = F.buscar_item_por_id(iid)
    assert it["fator_conversao"] == 5  # preservado
    assert it["unidade_compra"] == "L"  # preservado
    assert it["nome_item"] == "Novo Nome"  # o resto foi atualizado


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSÃO NO RECEBIMENTO (a borda que resolve o ledger corrompido)
# ══════════════════════════════════════════════════════════════════════════════


def _sc_com_item(iid, part_number, pedido):
    ok, msg = F.criar_sc(
        "SC-CV",
        "2026-01-01",
        [
            {
                "item_id": iid,
                "part_number": part_number,
                "nome_item": "Item",
                "quantidade_solicitada": pedido,
                "quantidade_pedido": pedido,
            }
        ],
        "",
    )
    assert ok, msg
    with database.transaction() as c:
        sc_id = c.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc='SC-CV'").fetchone()["id"]
    return sc_id, F.listar_itens_sc(sc_id)[0]["id"]


def test_recebimento_converte_fator(db, make_item):
    iid = make_item("PN-RCV", nome="SOLVENTE", unidade="GL", estoque=0, minimo=5)
    F.atualizar_item_inventario(iid, {"unidade_compra": "L", "fator_conversao": 5})
    sc_id, isc_id = _sc_com_item(iid, "PN-RCV", pedido=5)  # 5 L pedidos
    ok, msg = F.registrar_recebimento_sc(sc_id, isc_id, 5, CC, "Alm", "Alm", "F", "2026-01-10", "NF")
    assert ok, msg
    # Estoque cresce em UNIDADE DE ESTOQUE: 5 L ÷ fator 5 = +1 GL.
    assert F.buscar_item_por_id(iid)["estoque_atual"] == 1
    isc = F.listar_itens_sc(sc_id)[0]
    # quantidade_recebida segue na UM de compra (consistente com o pedido).
    assert isc["quantidade_recebida"] == 5
    assert isc["status_item"] == "Recebido"
    # a movimentação de entrada é registrada em unidade de ESTOQUE.
    mov = F.listar_movimentacoes(iid, limit=1)[0]
    assert mov["quantidade"] == 1
    assert mov["tipo"] == "entrada"


def test_recebimento_fator_1_noop(db, make_item):
    """Item de UM única (fator 1): recebimento soma cru — comportamento de sempre."""
    iid = make_item("PN-NOOP", unidade="UN", estoque=0, minimo=5)
    sc_id, isc_id = _sc_com_item(iid, "PN-NOOP", pedido=10)
    ok, msg = F.registrar_recebimento_sc(sc_id, isc_id, 10, CC, "Alm", "Alm", "F", "2026-01-10", "NF")
    assert ok, msg
    assert F.buscar_item_por_id(iid)["estoque_atual"] == 10


def test_recebimento_parcial_converte(db, make_item):
    iid = make_item("PN-PARC", unidade="GL", estoque=0, minimo=5)
    F.atualizar_item_inventario(iid, {"unidade_compra": "L", "fator_conversao": 5})
    sc_id, isc_id = _sc_com_item(iid, "PN-PARC", pedido=10)  # 10 L
    ok, msg = F.registrar_recebimento_sc(sc_id, isc_id, 5, CC, "Alm", "Alm", "F", "2026-01-10", "NF")
    assert ok, msg
    assert F.buscar_item_por_id(iid)["estoque_atual"] == 1  # 5 L → 1 GL
    isc = F.listar_itens_sc(sc_id)[0]
    assert isc["quantidade_recebida"] == 5  # UM de compra
    assert isc["saldo_residual"] == 5  # 10 − 5, em L
    assert isc["status_item"] == "Parcial"


# ══════════════════════════════════════════════════════════════════════════════
# EXIBIÇÃO DUPLA NO ASSISTENTE (montar_sugestao)
# ══════════════════════════════════════════════════════════════════════════════


def test_montar_sugestao_qtd_compra(db, make_item):
    # Estoque baixo força reposição; fator 5 → qtd de compra = qtd_estoque × 5.
    iid = make_item("PN-SUG", unidade="GL", estoque=0, minimo=10)
    F.atualizar_item_inventario(iid, {"unidade_compra": "L", "fator_conversao": 5})
    item = next(i for i in F.listar_inventario() if i["id"] == iid)
    s = P.montar_sugestao(item, incluir_fornecedor=False)
    assert s["unidade_compra"] == "L"
    assert s["fator_conversao"] == 5
    assert s["qtd_sugerida_compra"] == math.ceil(s["qtd_sugerida"] * 5)
    assert s["qtd_sugerida_compra"] > 0


def test_montar_sugestao_fator_1_igual(db, make_item):
    iid = make_item("PN-SUG1", unidade="UN", estoque=0, minimo=10)
    item = next(i for i in F.listar_inventario() if i["id"] == iid)
    s = P.montar_sugestao(item, incluir_fornecedor=False)
    # sem conversão: qtd de compra == qtd de estoque.
    assert s["qtd_sugerida_compra"] == s["qtd_sugerida"]
    assert s["unidade_compra"] == "UN"


# ══════════════════════════════════════════════════════════════════════════════
# SINALIZAÇÃO FORWARD-ONLY (unidade_divergente)
# ══════════════════════════════════════════════════════════════════════════════


def test_unidade_divergente_flag(db, make_item):
    iid = make_item("PN-DIV", unidade="GL")
    # UM de compra observada (L) diverge da de estoque (GL) e fator ainda = 1.
    with database.transaction() as c:
        c.execute(
            "INSERT INTO precos_historico (item_id,data,preco_unitario,origem,unidade) VALUES (?,?,?,?,?)",
            (iid, "2026-06-01", 10.0, "SC7", "L"),
        )
    item = next(i for i in F.listar_inventario() if i["id"] == iid)
    assert item["unidade_divergente"] is True

    # Após curar (fator≠1), o aviso some.
    F.atualizar_item_inventario(iid, {"unidade_compra": "L", "fator_conversao": 5})
    item2 = next(i for i in F.listar_inventario() if i["id"] == iid)
    assert item2["unidade_divergente"] is False


def test_unidade_igual_nao_diverge(db, make_item):
    iid = make_item("PN-IGUAL", unidade="UN")
    with database.transaction() as c:
        c.execute(
            "INSERT INTO precos_historico (item_id,data,preco_unitario,origem,unidade) VALUES (?,?,?,?,?)",
            (iid, "2026-06-01", 10.0, "SC7", "UN"),
        )
    item = next(i for i in F.listar_inventario() if i["id"] == iid)
    assert item["unidade_divergente"] is False  # UM de compra == UM de estoque


# ══════════════════════════════════════════════════════════════════════════════
# CAPTURA DA UM NA INGESTÃO (SCM e SC7 → precos_historico.unidade)
# ══════════════════════════════════════════════════════════════════════════════


def _relatorio_com_unidade(path):
    scm = pd.DataFrame(
        [
            {
                "SC": 7001,
                "Descrição da Solicitação": "Compra",
                "Status": "Pedido",
                "Solicitante": "Luis Gabriel Arruda de Oliveira",
                "Produto": "PN-UM",
                "Descrição": "Solvente",
                "Qty": 5,
                "Justificativa/Projeto": "reposição",
                "Data Necessidade": "2026-06-01",
                "Emissão": "2026-05-01",
                "Aprovação": "2026-05-02",
                "Pedido": "F700",
                "Quantidade": 5,
                "Qtd.Entregue": 0,
                "Nome Fantasia": "FORN Y",
                "Previsão NFe": "2026-06-10",
                "Documento": "",
                "Prc Unitario": 20.0,
                "Vlr.Total": 100.0,
                "Moeda": 1,
                "Unidade": "L",
            }
        ]
    )
    sc7 = pd.DataFrame(
        [
            {
                "Filial": 1,
                "Tipo": 1,
                "Item": 1,
                "Pedido": "F701",
                "DT Emissao": "2026-05-01",
                "Produto": "PN-UM",
                "Descricao": "Solvente",
                "Unidade": "L",
                "Moeda": 1,
                "Quantidade": 5,
                "Prc Unitario": 21.0,
                "Vlr.Total": 105.0,
                "Qtd.Entregue": 0,
                "Saldo": 5,
                "Observacoes": "SC: 7001",
                "OBS 1": "",
            }
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        scm.to_excel(w, sheet_name="SCM", index=False)
        sc7.to_excel(w, sheet_name="SC7", index=False, startrow=3)
    return path


def test_ingestao_captura_unidade_scm_e_sc7(db, make_item, tmp_path):
    make_item("PN-UM", nome="SOLVENTE", unidade="GL", estoque=0, minimo=10)
    p = _relatorio_com_unidade(str(tmp_path / "rel.xlsx"))
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert ok, res
    with database.transaction() as c:
        unidades = {r[0] for r in c.execute("SELECT unidade FROM precos_historico WHERE unidade IS NOT NULL")}
    assert unidades == {"L"}  # UM capturada tanto do SCM quanto do SC7

    # E a sugestão passa a usar a UM observada.
    item = next(i for i in F.listar_inventario() if i["part_number"] == "PN-UM")
    assert F.sugerir_conversao(item)["unidade_compra_sugerida"] == "L"
    # O item aparece como "revisar unidade" (diverge de GL e fator ainda 1).
    assert item["unidade_divergente"] is True
