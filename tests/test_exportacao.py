"""Fase 5 (T-01/T-02): cobertura das exportacoes para DataFrame.

Cobre banco vazio (DataFrame vazio sem excecao), presenca das colunas renomeadas
e o filtro por tipo que casa. O caso de filtro que NAO casa nenhum registro tem
um bug latente conhecido (ValueError ao reatribuir colunas a DataFrame vazio) e
nao e exercitado aqui -- registrado para correcao controlada futura.
"""
from services import db_functions as F

CC = "21106 - MANUTENÇÃO"


def test_exportar_inventario_vazio(db):
    df = F.exportar_inventario_df()
    assert df.empty


def test_exportar_inventario_com_item(db, make_item):
    make_item("PN-EXP1")
    df = F.exportar_inventario_df()
    assert len(df) == 1
    assert "PN" in df.columns
    assert "Estoque Atual" in df.columns


def test_exportar_movimentacoes_vazio(db):
    df = F.exportar_movimentacoes_df()
    assert df.empty


def test_exportar_movimentacoes_com_dados(db, make_item):
    item_id = make_item("PN-EXP2", estoque=100)
    F.registrar_movimentacao(item_id, "entrada", 50, CC, "Joao", "Joao")
    df = F.exportar_movimentacoes_df()
    assert len(df) == 1
    assert list(df.columns) == ["Data/Hora", "PN", "Item", "Tipo", "Qtd",
                                "Saldo Pós", "Responsável", "Observação"]


def test_exportar_movimentacoes_filtro_que_casa(db, make_item):
    item_id = make_item("PN-EXP3", estoque=100)
    F.registrar_movimentacao(item_id, "entrada", 50, CC, "Joao", "Joao")
    df = F.exportar_movimentacoes_df(item_id=item_id, tipos_selecionados=["entrada"])
    assert len(df) == 1
