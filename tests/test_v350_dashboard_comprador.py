"""v3.5.0 — Dashboard de Comprador: assembler `montar_visao_compras_mro`.

Valida o escopo ANO CORRENTE (exclui SCs antigas nunca fechadas), o comprador real,
o valor, o fornecedor (nome válido) e o aging SC→PO.
"""
from datetime import date
import database
from services.dashboards import montar_visao_compras_mro

ANO = date.today().year


def _sc(numero, data_abertura, comprador=None, data_po=None, numero_po=None,
        status="Em Cotação", solicitante="Fulano", departamento=None):
    with database.transaction() as c:
        cur = c.execute(
            "INSERT INTO solicitacoes_compra "
            "(numero_sc,data_abertura,status,comprador,data_po,numero_po,solicitante,departamento) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (numero, data_abertura, status, comprador, data_po, numero_po, solicitante, departamento))
        return cur.lastrowid


def _item_sc(sc_id, item_id, qtd=5, receb=0, valor=100.0, fornecedor="NEW HORIZON"):
    with database.transaction() as c:
        c.execute(
            "INSERT INTO itens_sc (sc_id,item_id,quantidade_solicitada,quantidade_recebida,"
            "saldo_residual,valor_total,fornecedor_item,status_item) VALUES (?,?,?,?,?,?,?,?)",
            (sc_id, item_id, qtd, receb, qtd - receb, valor, fornecedor, "Aberto"))


def test_assembler_estrutura_ano_corrente_e_comprador(db, make_item):
    it = make_item("PN-DASH", estoque=0, minimo=5)
    sc1 = _sc("SC-ATUAL", f"{ANO}-02-01", comprador="Miguel", data_po=f"{ANO}-02-10", numero_po="PO-1")
    _item_sc(sc1, it, qtd=5, valor=500.0, fornecedor="NEW HORIZON")
    # SC de ano anterior — deve ser EXCLUÍDA pelo escopo do ano corrente
    sc0 = _sc("SC-VELHA", f"{ANO - 2}-02-01", comprador="Miguel", numero_po="PO-0")
    _item_sc(sc0, it, qtd=3, valor=999.0)

    vm = montar_visao_compras_mro()
    assert set(vm) >= {"kpis", "painel_prioridades", "aging_dist", "scpo_hist",
                       "por_comprador", "por_departamento", "fornecedores_top", "wk", "ano"}
    # Ano corrente: só a SC-ATUAL conta (a velha é ignorada)
    assert vm["kpis"]["pos_emitidos"] == 1
    assert vm["kpis"]["valor_comprado"] == 500.0
    # Comparativo por comprador
    mig = next(c for c in vm["por_comprador"] if c["comprador"] == "Miguel")
    assert mig["pos"] == 1
    # Fornecedor com nome válido capturado (não o lixo "1.0"/"2.0")
    assert any(f["fornecedor"] == "NEW HORIZON" for f in vm["fornecedores_top"])
    # Aging SC→PO = 9 dias (01→10/02)
    assert vm["kpis"]["scpo_medio"] == 9.0


def test_assembler_sem_dados_nao_quebra(db):
    vm = montar_visao_compras_mro()
    assert vm["kpis"]["scs_abertas"] == 0
    assert vm["painel_prioridades"] == []
    assert vm["fornecedores_top"] == []
