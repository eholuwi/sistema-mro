"""v4.2.1 — Hotfix da Fase 2: provedores de drill-down (services/drill_down.py).

Regressão dos 3 provedores que quebravam em runtime na v4.2.0:
- rows_top_consumo: a query referenciava m.origem / m.preco_unitario (colunas
  inexistentes em movimentacoes) → OperationalError.
- rows_dist_status / rows_cobertura_faixa: tratavam o retorno de listar_inventario()
  (uma LISTA de dicts) como DataFrame (.empty/.to_dict/.iterrows) → AttributeError.

Testa a camada de serviço com DB isolado (fixtures do conftest).
"""
from datetime import date

import pandas as pd

from services import drill_down as D
from services import db_functions as F


def test_dist_status_retorna_dataframe(db, make_item):
    # Regressão: antes quebrava com AttributeError ('list' object has no attribute 'empty').
    make_item("PN-CRIT", estoque=1, minimo=50)      # crítico: estoque_atual < estoque_minimo
    df = D.rows_dist_status("critico")
    assert isinstance(df, pd.DataFrame)
    assert "PN-CRIT" in set(df["part_number"])


def test_cobertura_faixa_retorna_dataframe(db, make_item):
    # Regressão: antes quebrava com AttributeError (list.iterrows).
    make_item("PN-COB", estoque=100, minimo=10)
    df = D.rows_cobertura_faixa("30+")
    assert isinstance(df, pd.DataFrame)


def test_top_consumo_conta_so_saida_real(db, make_item, registrar_consumo):
    # Regressão do SQL + semântica: consumo real = saída COM requisicao_id (SAIDA_REAL_WHERE).
    item_id = make_item("PN-TOP", estoque=100, minimo=10)
    hoje = date.today().strftime("%Y-%m-%d %H:%M:%S")
    registrar_consumo(item_id, quantidade=7.0, data_hora=hoje)

    df = D.rows_top_consumo(dias=30, limite=10)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["part_number", "nome_item", "quantidade_consumida", "n_saidas"]
    linha = df[df["part_number"] == "PN-TOP"]
    assert not linha.empty
    assert float(linha.iloc[0]["quantidade_consumida"]) == 7.0


def test_top_consumo_ignora_saida_sem_requisicao(db, make_item):
    # Saída manual (ajuste/perda, sem requisicao_id) NÃO é consumo real → não entra no Top.
    item_id = make_item("PN-ADJ", estoque=100, minimo=10)
    F.registrar_movimentacao(
        item_id=item_id, tipo="saida", quantidade=5,
        centro_custo=None, solicitante="tester", emitente="tester",
        observacao="AJUSTE: perda",
    )
    df = D.rows_top_consumo(dias=30, limite=10)
    pns = set(df["part_number"]) if not df.empty else set()
    assert "PN-ADJ" not in pns
