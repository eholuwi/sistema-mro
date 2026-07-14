# -*- coding: utf-8 -*-
"""services/drill_down.py — v4.2.0 (Provedores de linhas para drill-down)

Funções que retornam DataFrames para populações "detalhes" (v4.2.0: Explicabilidade &
Drill-down). Cada função = query + transformação mínima, retornando um DataFrame simples
pronto para exibição em st.dataframe + busca + export.

Reutiliza queries existentes (montar_visao_compras_mro, listar_inventario, etc.) e
não requer migração (PURO).
"""

import pandas as pd
from datetime import date, timedelta
from services.db_functions import transaction, listar_inventario, listar_requisicoes
from services.dashboards import montar_visao_compras_mro, montar_visao_almoxarifado


def rows_itens_em_aberto(filtro_fornecedor: str = None) -> pd.DataFrame:
    """Itens do painel de prioridades (SCs abertas com consumo/estoque crítico).
    Colunas: aging, numero_sc, item_nome, part_number, comprador."""
    vm = montar_visao_compras_mro()
    painel = vm.get("painel_prioridades", [])

    df = pd.DataFrame(painel)
    if df.empty:
        return df

    # Renomeia para exibição
    renomes = {
        "sc": "numero_sc",
        "item": "item_nome",
        "pn": "part_number",
        "aging": "dias_desde_abertura"
    }
    df = df.rename(columns={k: v for k, v in renomes.items() if k in df.columns})

    if filtro_fornecedor and "comprador" in df.columns:
        df = df[df["comprador"].str.contains(filtro_fornecedor, case=False, na=False)]

    colunas = ["numero_sc", "item_nome", "part_number", "comprador", "dias_desde_abertura"]
    cols_disponiveis = [c for c in colunas if c in df.columns]
    return df[cols_disponiveis] if cols_disponiveis else df


def rows_fornecedores_aberto() -> pd.DataFrame:
    """Fornecedores com SCs abertas, agrupado por valor.
    Colunas: fornecedor, n, valor."""
    vm = montar_visao_compras_mro()

    forn_data = vm.get("fornecedores_top", [])
    if not forn_data:
        return pd.DataFrame()

    df = pd.DataFrame(forn_data)
    return df.sort_values("valor", ascending=False) if "valor" in df.columns else df


def rows_setores_demanda_aberta() -> pd.DataFrame:
    """Setores com demanda em aberto.
    Colunas: departamento, n, valor."""
    vm = montar_visao_compras_mro()

    setores_data = vm.get("por_departamento", [])
    if not setores_data:
        return pd.DataFrame()

    df = pd.DataFrame(setores_data)
    # Renomeia para clareza
    if "departamento" in df.columns:
        df = df.rename(columns={"departamento": "setor"})

    return df.sort_values("valor", ascending=False) if "valor" in df.columns else df


def rows_dist_status(status_code: str = "ok") -> pd.DataFrame:
    """Itens filtrados por status de saúde (ok, atenção, crítico, etc).
    Colunas: part_number, nome_item, estoque_atual, estoque_minimo, dias_cobertura, status."""
    inventario = listar_inventario()
    if inventario.empty:
        return pd.DataFrame()

    # Mapeamento status simples (OK, Atenção, Crítico)
    status_map = {
        "ok": lambda r: r.get("estoque_atual", 0) >= r.get("estoque_minimo", 0) and r.get("dias_cobertura", 0) >= 30,
        "atenção": lambda r: r.get("estoque_atual", 0) >= r.get("estoque_minimo", 0) and r.get("dias_cobertura", 0) < 30,
        "critico": lambda r: r.get("estoque_atual", 0) < r.get("estoque_minimo", 0),
    }

    filtro_fn = status_map.get(status_code.lower())
    if not filtro_fn:
        return inventario

    # Filtra usando a função lambda
    rows = [dict(r) for r in inventario.to_dict('records') if filtro_fn(r)]
    df = pd.DataFrame(rows) if rows else pd.DataFrame()

    colunas = ["part_number", "nome_item", "estoque_atual", "estoque_minimo", "dias_cobertura"]
    cols_disponiveis = [c for c in colunas if c in df.columns]
    return df[cols_disponiveis] if cols_disponiveis else df


def rows_top_consumo(dias: int = 30, limite: int = 10) -> pd.DataFrame:
    """Top N itens por consumo no período (últimos `dias` dias).
    Colunas: part_number, nome_item, quantidade_consumida, valor_consumido."""
    hoje = date.today()
    data_inicio = hoje - timedelta(days=dias)
    data_inicio_str = data_inicio.strftime("%Y-%m-%d")

    with transaction() as conn:
        rows = conn.execute("""
            SELECT inv.part_number, inv.nome_item,
                   COUNT(*) AS n_movimentacoes,
                   SUM(m.quantidade) AS quantidade_consumida,
                   SUM(m.quantidade * m.preco_unitario) AS valor_consumido
            FROM movimentacoes m
            JOIN inventario inv ON inv.id = m.item_id
            WHERE m.tipo = 'saida'
              AND m.data_hora >= ?
              AND m.origem != 'Ajuste'
            GROUP BY inv.id, inv.part_number, inv.nome_item
            ORDER BY quantidade_consumida DESC
            LIMIT ?
        """, (data_inicio_str, limite)).fetchall()

    df = pd.DataFrame([dict(r) for r in rows])

    colunas = ["part_number", "nome_item", "quantidade_consumida", "valor_consumido"]
    cols_disponiveis = [c for c in colunas if c in df.columns]
    return df[cols_disponiveis] if cols_disponiveis else df


def rows_entradas_saidas(periodo: str = "hoje") -> pd.DataFrame:
    """Volume de entradas e saídas por período.
    Colunas: tipo_movimentacao, data, quantidade, parte_number, nome_item."""
    hoje = date.today()

    # Mapeia período para range de datas
    periodo_map = {
        "hoje": (hoje, hoje),
        "semana": (hoje - timedelta(days=7), hoje),
        "mes": (hoje - timedelta(days=30), hoje),
    }

    data_inicio, data_fim = periodo_map.get(periodo.lower(), (hoje, hoje))
    data_inicio_str = data_inicio.strftime("%Y-%m-%d")
    data_fim_str = (data_fim + timedelta(days=1)).strftime("%Y-%m-%d")

    with transaction() as conn:
        rows = conn.execute("""
            SELECT m.tipo, DATE(m.data_hora) AS data, m.quantidade,
                   inv.part_number, inv.nome_item
            FROM movimentacoes m
            JOIN inventario inv ON inv.id = m.item_id
            WHERE m.data_hora >= ? AND m.data_hora < ?
            ORDER BY m.data_hora DESC
        """, (data_inicio_str, data_fim_str)).fetchall()

    df = pd.DataFrame([dict(r) for r in rows])

    colunas = ["tipo", "data", "quantidade", "part_number", "nome_item"]
    cols_disponiveis = [c for c in colunas if c in df.columns]
    return df[cols_disponiveis] if cols_disponiveis else df


def rows_cobertura_faixa(faixa: str = "<7") -> pd.DataFrame:
    """Itens filtrados por faixa de cobertura (dias até acabar o estoque).
    Colunas: part_number, nome_item, dias_cobertura, estoque_atual, consumo_dia."""
    inventario = listar_inventario()
    if inventario.empty:
        return pd.DataFrame()

    # Faixas de cobertura
    faixa_map = {
        "<7": lambda d: (d is not None and d < 7),
        "7-15": lambda d: (d is not None and 7 <= d < 15),
        "15-30": lambda d: (d is not None and 15 <= d < 30),
        "30+": lambda d: (d is not None and d >= 30),
    }

    filtro_fn = faixa_map.get(faixa)
    if not filtro_fn:
        return inventario

    rows = []
    for _, r in inventario.iterrows():
        dias = r.get("dias_cobertura")
        if filtro_fn(dias):
            rows.append(r.to_dict())

    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    colunas = ["part_number", "nome_item", "dias_cobertura", "estoque_atual", "consumo_dia"]
    cols_disponiveis = [c for c in colunas if c in df.columns]
    return df[cols_disponiveis] if cols_disponiveis else df
