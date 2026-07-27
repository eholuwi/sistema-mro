"""v5.6.0 — Ingestão: Centro de Custo e origem do item de SC.

Dois campos que a tela do SCM Integrado exibia sempre vazios porque a ingestão Excel
nunca os gravava, embora o dado estivesse na planilha (Centro Custo) ou na coluna do
banco (itens_sc.origem, preenchida só pelo sync da API — que nunca rodou).

Reusa os helpers de `test_ingestao_relatorio_scs.py` para montar o Relatório de SCs.
"""

import pandas as pd
import pytest
from services import db_functions as F
import database

from tests.test_ingestao_relatorio_scs import _build_relatorio, _linha_scm


# ── Item 3: Centro de Custo ───────────────────────────────────────────────────


def test_centro_custo_da_planilha_e_persistido(db, make_item, tmp_path):
    """A coluna "Centro Custo" sempre existiu no export; era lida e descartada."""
    make_item("PN-ING", estoque=5, minimo=10)
    p = _build_relatorio(str(tmp_path / "rel.xlsx"))
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert ok, res
    with database.transaction() as c:
        sc = c.execute("SELECT centro_custo FROM solicitacoes_compra WHERE numero_sc='5001'").fetchone()
    assert sc["centro_custo"] == "21106"


@pytest.mark.parametrize("rotulo", ["Centro Custo", "Centro de Custo", "CC"])
def test_variacoes_de_rotulo_da_coluna(db, make_item, tmp_path, rotulo):
    """O export muda de rótulo entre versões; todos precisam cair no mesmo campo."""
    make_item("PN-ING", estoque=5)
    linha = _linha_scm()
    linha.pop("Centro Custo")
    linha[rotulo] = "21194 - ALMOXARIFADO"
    p = _build_relatorio(str(tmp_path / f"rel_{rotulo.replace(' ', '_')}.xlsx"), scm_rows=[linha])
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert ok, res
    with database.transaction() as c:
        sc = c.execute("SELECT centro_custo FROM solicitacoes_compra WHERE numero_sc='5001'").fetchone()
    assert sc["centro_custo"] == "21194 - ALMOXARIFADO"


def test_planilha_sem_centro_de_custo_nao_quebra(db, make_item, tmp_path):
    """Nem todo export traz a coluna — a ingestão tem de seguir normalmente."""
    make_item("PN-ING", estoque=5)
    linha = _linha_scm()
    linha.pop("Centro Custo")
    p = _build_relatorio(str(tmp_path / "rel_sem_cc.xlsx"), scm_rows=[linha])
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert ok, res
    assert res["SCM"]["linhas_importadas"] == 1
    with database.transaction() as c:
        sc = c.execute("SELECT centro_custo FROM solicitacoes_compra WHERE numero_sc='5001'").fetchone()
    assert sc["centro_custo"] is None


def test_import_sem_cc_nao_apaga_o_cc_ja_gravado(db, make_item, tmp_path):
    """Regressão que o COALESCE protege: reimportar de um export sem a coluna não
    pode zerar o centro de custo que um import anterior já trouxe."""
    make_item("PN-ING", estoque=5)
    F.importar_relatorio_scs(str(_build_relatorio(str(tmp_path / "com.xlsx"))), "com.xlsx")

    linha = _linha_scm()
    linha.pop("Centro Custo")
    F.importar_relatorio_scs(str(_build_relatorio(str(tmp_path / "sem.xlsx"), scm_rows=[linha])), "sem.xlsx")
    with database.transaction() as c:
        sc = c.execute("SELECT centro_custo FROM solicitacoes_compra WHERE numero_sc='5001'").fetchone()
    assert sc["centro_custo"] == "21106", "o import sem a coluna apagou o CC já gravado"


def test_centro_custo_traco_vira_nulo(db, make_item, tmp_path):
    """'-' é o preenchimento vazio do Protheus — mesmo tratamento de comprador/departamento."""
    make_item("PN-ING", estoque=5)
    linha = _linha_scm()
    linha["Centro Custo"] = "-"
    p = _build_relatorio(str(tmp_path / "rel_traco.xlsx"), scm_rows=[linha])
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert ok, res
    with database.transaction() as c:
        sc = c.execute("SELECT centro_custo FROM solicitacoes_compra WHERE numero_sc='5001'").fetchone()
    assert sc["centro_custo"] is None


# ── Item 4: origem do item de SC ──────────────────────────────────────────────


def test_ingestao_excel_marca_origem(db, make_item, tmp_path):
    make_item("PN-ING", estoque=5)
    p = _build_relatorio(str(tmp_path / "rel.xlsx"))
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert ok, res
    with database.transaction() as c:
        isc = c.execute("SELECT origem FROM itens_sc").fetchall()
    assert [r["origem"] for r in isc] == ["excel"]


def test_reimportacao_mantem_origem_excel(db, make_item, tmp_path):
    """O UPDATE do upsert também grava a origem — não pode voltar a NULL."""
    make_item("PN-ING", estoque=5)
    p = _build_relatorio(str(tmp_path / "rel.xlsx"))
    F.importar_relatorio_scs(p, "rel.xlsx")
    F.importar_relatorio_scs(p, "rel.xlsx")
    with database.transaction() as c:
        isc = c.execute("SELECT origem FROM itens_sc").fetchall()
    assert all(r["origem"] == "excel" for r in isc)


def test_sc_manual_nasce_com_origem_manual(db, make_item):
    item_id = make_item("PN-MAN", estoque=0)
    ok, msg = F.criar_sc(
        "SC-MANUAL-1",
        "2026-01-01",
        [{"item_id": item_id, "quantidade_solicitada": 5, "quantidade_pedido": 5}],
        "",
    )
    assert ok, msg
    with database.transaction() as c:
        isc = c.execute("SELECT origem FROM itens_sc").fetchone()
    assert isc["origem"] == "manual"


# ── Item 4: backfill da migração ──────────────────────────────────────────────


def test_backfill_marca_itens_antigos_como_excel(db, make_item):
    """Simula o legado (658 itens com origem NULL) e roda a migração."""
    item_id = make_item("PN-LEGADO", estoque=0)
    F.criar_sc(
        "SC-LEGADO",
        "2026-01-01",
        [{"item_id": item_id, "quantidade_solicitada": 5, "quantidade_pedido": 5}],
        "",
    )
    with database.transaction() as c:
        c.execute("UPDATE itens_sc SET origem=NULL")

    with database.transaction() as c:
        database._migrar(c)
        assert c.execute("SELECT origem FROM itens_sc").fetchone()["origem"] == "excel"


def test_backfill_nao_regride_origem_da_api(db, make_item):
    """A garantia que importa: quem veio da API não pode ser remarcado como Excel."""
    item_id = make_item("PN-API", estoque=0)
    F.criar_sc(
        "SC-API",
        "2026-01-01",
        [{"item_id": item_id, "quantidade_solicitada": 5, "quantidade_pedido": 5}],
        "",
    )
    with database.transaction() as c:
        c.execute("UPDATE itens_sc SET origem='api_scm'")

    with database.transaction() as c:
        database._migrar(c)
        assert c.execute("SELECT origem FROM itens_sc").fetchone()["origem"] == "api_scm"


def test_backfill_idempotente(db, make_item):
    """Roda a cada boot do app: a segunda passada não pode encontrar trabalho."""
    item_id = make_item("PN-IDEM", estoque=0)
    F.criar_sc(
        "SC-IDEM",
        "2026-01-01",
        [{"item_id": item_id, "quantidade_solicitada": 5, "quantidade_pedido": 5}],
        "",
    )
    with database.transaction() as c:
        c.execute("UPDATE itens_sc SET origem=NULL")
    with database.transaction() as c:
        database._migrar(c)
    with database.transaction() as c:
        database._migrar(c)
        assert c.execute("SELECT COUNT(*) n FROM itens_sc WHERE origem IS NULL").fetchone()["n"] == 0
        assert c.execute("SELECT origem FROM itens_sc").fetchone()["origem"] == "excel"


def test_ingestao_preenche_ambos_os_campos_de_uma_vez(db, make_item, tmp_path):
    """Fecha o ciclo dos itens 3 e 4: uma ingestão normal resolve os dois campos que a
    tela mostrava vazios."""
    make_item("PN-ING", estoque=5)
    p = _build_relatorio(str(tmp_path / "rel.xlsx"))
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert ok, res
    with database.transaction() as c:
        linha = c.execute(
            """SELECT sc.centro_custo, isc.origem
               FROM itens_sc isc JOIN solicitacoes_compra sc ON sc.id = isc.sc_id"""
        ).fetchone()
    assert linha["centro_custo"] == "21106"
    assert linha["origem"] == "excel"


def test_pandas_nan_no_centro_de_custo_nao_vira_texto(db, make_item, tmp_path):
    """Célula vazia no Excel chega como NaN; não pode gravar a string 'nan'."""
    make_item("PN-ING", estoque=5)
    linha = _linha_scm()
    linha["Centro Custo"] = None
    p = _build_relatorio(str(tmp_path / "rel_nan.xlsx"), scm_rows=[linha])
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert ok, res
    with database.transaction() as c:
        sc = c.execute("SELECT centro_custo FROM solicitacoes_compra WHERE numero_sc='5001'").fetchone()
    assert sc["centro_custo"] is None, f"gravou {sc['centro_custo']!r} em vez de NULL"


def test_ingestao_protheus_aceita_centro_de_custo_quando_existe(db, make_item, tmp_path):
    """O export `Solicitações.xlsx` nem sempre traz a coluna; quando trouxer, grava."""
    make_item("PN-PROT", estoque=0)
    df = pd.DataFrame(
        [
            {
                "Numero da Solicitacao": 7001,
                "Descricao da Solicitacao": "Compra Protheus",
                "Status": "Pedido",
                "Solicitante": "Luis Gabriel Arruda de Oliveira",
                "Produto": "PN-PROT",
                "Descricao Detalhada": "Item Protheus",
                "Quantidade": 8,
                "Data Necessidade": "2026-06-01",
                "Emissao": "2026-05-01",
                "Centro Custo": "21106 - MANUTENÇÃO",
            }
        ]
    )
    p = str(tmp_path / "solicitacoes.xlsx")
    df.to_excel(p, index=False)
    ok, res = F.importar_solicitacoes_protheus(p, "solicitacoes.xlsx")
    assert ok, res
    with database.transaction() as c:
        sc = c.execute("SELECT centro_custo FROM solicitacoes_compra WHERE numero_sc='7001'").fetchone()
    assert sc["centro_custo"] == "21106 - MANUTENÇÃO"
