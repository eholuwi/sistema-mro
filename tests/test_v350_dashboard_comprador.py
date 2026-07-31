"""v3.5.0 — Dashboard de Comprador: assembler `montar_visao_compras_mro`.

Valida o escopo ANO CORRENTE (exclui SCs antigas nunca fechadas), o comprador real,
o valor e o fornecedor (nome válido).

v5.9.0 — a aba foi reduzida a 4 cards + 5 gráficos e o contrato do view-model mudou
junto: saíram `aging_dist`, `scpo_hist`, `por_comprador`, `por_solicitante`,
`lead_time_fornecedor`, `evolucao_semanal`, `status_pos` e `itens_por_pedido`; os
KPIs viraram os 4 cards, todos contados no grão de ITEM de SC. Entraram
`dispendio_mensal` e `dispendio_setor`. As asserções de aging/lead time/evolução
foram removidas com os agregados que as sustentavam.
"""

from datetime import date

import database
from services.dashboards import montar_visao_compras_mro

ANO = date.today().year


def _sc(
    numero,
    data_abertura,
    comprador=None,
    data_po=None,
    numero_po=None,
    status="Em Cotação",
    solicitante="Fulano",
    departamento=None,
    data_aprovacao=None,
):
    with database.transaction() as c:
        cur = c.execute(
            "INSERT INTO solicitacoes_compra "
            "(numero_sc,data_abertura,status,comprador,data_po,numero_po,solicitante,"
            "departamento,data_aprovacao) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                numero,
                data_abertura,
                status,
                comprador,
                data_po,
                numero_po,
                solicitante,
                departamento,
                data_aprovacao,
            ),
        )
        return cur.lastrowid


def _item_sc(sc_id, item_id, qtd=5, receb=0, valor=100.0, fornecedor="NEW HORIZON", numero_po=None):
    with database.transaction() as c:
        c.execute(
            "INSERT INTO itens_sc (sc_id,item_id,quantidade_solicitada,quantidade_recebida,"
            "saldo_residual,valor_total,fornecedor_item,status_item,numero_po) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sc_id, item_id, qtd, receb, qtd - receb, valor, fornecedor, "Aberto", numero_po),
        )


def test_assembler_estrutura_ano_corrente_e_comprador(db, make_item):
    it = make_item("PN-DASH", estoque=0, minimo=5)
    sc1 = _sc("SC-ATUAL", f"{ANO}-02-01", comprador="Miguel", data_po=f"{ANO}-02-10", numero_po="PO-1")
    _item_sc(sc1, it, qtd=5, valor=500.0, fornecedor="NEW HORIZON")
    # SC de ano anterior — deve ser EXCLUÍDA pelo escopo do ano corrente
    sc0 = _sc("SC-VELHA", f"{ANO - 2}-02-01", comprador="Miguel", numero_po="PO-0")
    _item_sc(sc0, it, qtd=3, valor=999.0)

    vm = montar_visao_compras_mro()
    assert set(vm) >= {
        "kpis",
        "painel_prioridades",
        "por_departamento",
        "fornecedores_top",
        "volume_mensal",
        "dispendio_mensal",
        "dispendio_setor",
        "wk",
        "ano",
    }
    # Ano corrente: só a SC-ATUAL conta (a velha é ignorada)
    assert vm["kpis"]["pos_emitidos"] == 1
    assert vm["kpis"]["itens_com_po"] == 1
    # Fornecedor com nome válido capturado (não o lixo "1.0"/"2.0")
    assert any(f["fornecedor"] == "NEW HORIZON" for f in vm["fornecedores_top"])
    # Dispêndio atribuído ao MÊS DO PO (fev), não ao mês de abertura
    assert vm["dispendio_mensal"]["meses"] == [f"{ANO}-02"]
    assert vm["dispendio_mensal"]["valores"] == [500.0]


def test_cards_contam_item_e_pedido_nao_sc(db, make_item):
    """Os 4 cards são no grão de item; 'Pedidos Emitidos' são POs DISTINTOS.

    Uma SC com 3 itens e 2 POs distintos: 3 itens com PO, 2 pedidos — não 1 e 1.
    """
    a = make_item("PN-A", estoque=0, minimo=5)
    b = make_item("PN-B", estoque=0, minimo=5)
    c = make_item("PN-C", estoque=0, minimo=5)
    sc = _sc("SC-MULTI", f"{ANO}-05-01", status="Em Cotação", numero_po=None)
    _item_sc(sc, a, valor=10.0, numero_po="PO-100")
    _item_sc(sc, b, valor=20.0, numero_po="PO-100")
    _item_sc(sc, c, valor=30.0, numero_po="PO-200")

    vm = montar_visao_compras_mro()
    assert vm["kpis"]["itens_com_po"] == 3  # 3 linhas de item
    assert vm["kpis"]["pos_emitidos"] == 2  # PO-100 e PO-200
    assert vm["kpis"]["itens_abertos"] == 3  # 3 itens numa SC em cotação
    assert vm["kpis"]["scs_abertas"] == 1  # ...mas 1 SC só


def test_dispendio_por_setor_usa_consumo_real(db, make_item, registrar_consumo):
    """O setor vem do CONSUMO REAL do item, não do cadastro; sem consumo, fica fora."""
    com_consumo = make_item("PN-COM", estoque=10, minimo=1)
    sem_consumo = make_item("PN-SEM", estoque=10, minimo=1)
    registrar_consumo(com_consumo)  # cria saída real com setor "MANUTENÇÃO"

    sc = _sc("SC-SETOR", f"{ANO}-06-01", data_po=f"{ANO}-06-05", numero_po="PO-S")
    _item_sc(sc, com_consumo, valor=700.0)
    _item_sc(sc, sem_consumo, valor=300.0)

    vm = montar_visao_compras_mro()
    setores = {r["setor"]: r["valor"] for r in vm["dispendio_setor"]}
    assert setores == {"MANUTENÇÃO": 700.0}  # os 300 do item sem consumo ficam fora
    # O total mensal, porém, conta os dois (o mês não depende de setor).
    assert vm["dispendio_mensal"]["valores"] == [1000.0]


def test_assembler_sem_dados_nao_quebra(db):
    vm = montar_visao_compras_mro()
    assert vm["kpis"] == {
        "itens_abertos": 0,
        "scs_abertas": 0,
        "pos_emitidos": 0,
        "itens_com_po": 0,
    }
    assert vm["painel_prioridades"] == []
    assert vm["fornecedores_top"] == []
    assert vm["volume_mensal"]["meses"] == []
    assert vm["dispendio_mensal"]["meses"] == []
    assert vm["dispendio_setor"] == []
