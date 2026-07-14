# -*- coding: utf-8 -*-
"""services/drill_down.py — v4.2.1 (Provedores de linhas para drill-down)

Funções que retornam DataFrames para as populações "detalhes" (v4.2.0: Explicabilidade
& Drill-down). Cada função = query + transformação mínima, retornando um DataFrame
simples pronto para exibição em st.dataframe + busca + export.

Reutiliza queries existentes (montar_visao_compras_mro, listar_inventario, etc.) e não
requer migração (PURO).

v4.2.1 (hotfix): correção de encoding e de 3 provedores que quebravam em runtime —
rows_top_consumo (referenciava colunas inexistentes em movimentacoes) e
rows_dist_status/rows_cobertura_faixa (tratavam a lista de listar_inventario como
DataFrame). O consumo real usa o fragmento canônico SAIDA_REAL_WHERE.
"""

import pandas as pd
from datetime import date, timedelta
from services.constants import SAIDA_REAL_WHERE, PREVISAO_RUPTURA_SEM_RISCO
from services.db_functions import transaction, listar_inventario
from services.dashboards import montar_visao_compras_mro, _faixa_cobertura


# ──────────────────────────────────────────────────────────────────────────────
# v4.5.0 — Provedores parametrizados p/ drill-down do Dashboard Almoxarifado.
# Espelham EXATAMENTE os filtros do view-model (services/dashboards.py) para que a
# tabela aberta ao clicar componha o mesmo número do card.
# ──────────────────────────────────────────────────────────────────────────────

def _df_itens(itens):
    """Lista de itens (dicts de listar_inventario) -> DataFrame de exibição."""
    cols = [("part_number", "PN"), ("nome_item", "Material"),
            ("estoque_atual", "Estoque"), ("estoque_minimo", "Mínimo"),
            ("dias_cobertura", "Cobertura (d)"), ("status_material", "Status"),
            ("importancia", "Criticidade"), ("local_armazenagem", "Local")]
    rows = [{lbl: i.get(k) for k, lbl in cols} for i in itens]
    return pd.DataFrame(rows, columns=[lbl for _, lbl in cols])


def _urgente(i):
    """Mesma regra de 'compra_urgente' de montar_visao_almoxarifado."""
    est = i.get("estoque_atual") or 0
    mn = i.get("estoque_minimo") or 0
    if not (mn > 0 and est <= mn):
        return False
    parada = i.get("importancia") == "Parada de Linha"
    com_giro = not i.get("sem_movimentacao")
    return parada or (est <= 0 and com_giro)


def _tem(campo, i, termo):
    return termo in (i.get(campo) or "")


# Predicados por chave — espelham o if/elif dos view-models (gestão + almoxarifado).
_PRED_INV = {
    "todos":          lambda i: True,
    # Distribuição "base de compra" (só itens com consumo) — status_material
    "ok":             lambda i: not i.get("sem_movimentacao") and _tem("status_material", i, "OK"),
    "atencao":        lambda i: not i.get("sem_movimentacao") and _tem("status_material", i, "ATENÇÃO"),
    "comprar":        lambda i: not i.get("sem_movimentacao") and _tem("status_material", i, "COMPRAR"),
    "sem_mov":        lambda i: bool(i.get("sem_movimentacao")),
    "zerados":        lambda i: (i.get("estoque_atual") or 0) <= 0,
    "inventariado":   lambda i: bool(i.get("data_inventario")),
    # Saúde física (TODO material) — status_estoque_fisico
    "fis_ok":         lambda i: (i.get("estoque_atual") or 0) > 0 and not _tem("status_estoque_fisico", i, "COMPRAR") and not _tem("status_estoque_fisico", i, "ATENÇÃO"),
    "fis_atencao":    lambda i: (i.get("estoque_atual") or 0) > 0 and _tem("status_estoque_fisico", i, "ATENÇÃO"),
    "fis_critico":    lambda i: (i.get("estoque_atual") or 0) > 0 and _tem("status_estoque_fisico", i, "COMPRAR"),
    "fis_zerado":     lambda i: (i.get("estoque_atual") or 0) <= 0,
    # KPIs
    "compra_urgente": _urgente,
    "com_valor":      lambda i: (i.get("estoque_atual") or 0) > 0,
    "cobertura":      lambda i: (not i.get("sem_movimentacao")) and i.get("dias_cobertura") is not None and i.get("dias_cobertura") != PREVISAO_RUPTURA_SEM_RISCO,
}


def rows_inventario_filtro(filtro="todos"):
    """Itens do inventário filtrados por `filtro` (ver _PRED_INV). DataFrame de exibição."""
    pred = _PRED_INV.get(filtro, lambda i: True)
    return _df_itens([i for i in listar_inventario() if pred(i)])


def rows_mov_periodo(tipo="entrada", periodo="hoje"):
    """Movimentações por tipo/período (entradas ou saídas reais). Espelha o _periodo do vm:
    hoje = data exata; semana = últimos 7 dias; mês = últimos 30 dias."""
    hoje = date.today()
    if periodo == "hoje":
        cond, arg = "substr(m.data_hora,1,10) = ?", hoje.strftime("%Y-%m-%d")
    elif periodo == "semana":
        cond, arg = "substr(m.data_hora,1,10) >= ?", (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
    else:
        cond, arg = "substr(m.data_hora,1,10) >= ?", (hoje - timedelta(days=30)).strftime("%Y-%m-%d")
    where_tipo = "m.tipo='entrada'" if tipo == "entrada" else SAIDA_REAL_WHERE

    with transaction() as conn:
        rows = conn.execute(f"""
            SELECT DATE(m.data_hora) AS Data, inv.part_number AS PN, inv.nome_item AS Material,
                   m.quantidade AS Qtd, m.emitente AS Responsável, m.observacao AS Obs
            FROM movimentacoes m JOIN inventario inv ON inv.id = m.item_id
            WHERE {where_tipo} AND {cond}
            ORDER BY m.data_hora DESC
        """, (arg,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["Data", "PN", "Material", "Qtd", "Responsável", "Obs"])


def rows_padrao_demanda(padrao):
    """Itens classificados com um padrão de demanda (Suave/Intermitente/Errático/…).
    Espelha o Counter(padrao_demanda) do view-model de gestão."""
    return _df_itens([i for i in listar_inventario() if (i.get("padrao_demanda") or "") == padrao])


def rows_requisicoes_dia():
    """Requisições emitidas hoje (cada linha = 1 requisição)."""
    hoje = date.today().strftime("%Y-%m-%d")
    with transaction() as conn:
        rows = conn.execute("""
            SELECT numero_requisicao AS "Nº Req", data_hora AS "Data/Hora",
                   setor AS Setor, emitente AS Emitente, autorizador_nome AS Autorizador
            FROM requisicoes WHERE substr(data_hora,1,10) = ?
            ORDER BY data_hora DESC
        """, (hoje,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows],
                        columns=["Nº Req", "Data/Hora", "Setor", "Emitente", "Autorizador"])


def rows_itens_em_aberto(filtro_fornecedor: str = None) -> pd.DataFrame:
    """Itens do painel de prioridades (SCs abertas com consumo/estoque crítico).
    Colunas: numero_sc, item_nome, part_number, comprador, dias_desde_abertura."""
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
        "aging": "dias_desde_abertura",
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
    Colunas: setor, n, valor."""
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
    """Itens filtrados por status de saúde (ok, atenção, crítico).
    Colunas: part_number, nome_item, estoque_atual, estoque_minimo, dias_cobertura."""
    inventario = listar_inventario()  # lista de dicts
    if not inventario:
        return pd.DataFrame()

    # Mapeamento de status simples (OK, Atenção, Crítico)
    status_map = {
        "ok": lambda r: (r.get("estoque_atual", 0) or 0) >= (r.get("estoque_minimo", 0) or 0)
                        and (r.get("dias_cobertura", 0) or 0) >= 30,
        "atenção": lambda r: (r.get("estoque_atual", 0) or 0) >= (r.get("estoque_minimo", 0) or 0)
                             and (r.get("dias_cobertura", 0) or 0) < 30,
        "critico": lambda r: (r.get("estoque_atual", 0) or 0) < (r.get("estoque_minimo", 0) or 0),
    }

    filtro_fn = status_map.get(status_code.lower())
    rows = [r for r in inventario if filtro_fn(r)] if filtro_fn else inventario
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    if df.empty:
        return df

    colunas = ["part_number", "nome_item", "estoque_atual", "estoque_minimo", "dias_cobertura"]
    cols_disponiveis = [c for c in colunas if c in df.columns]
    return df[cols_disponiveis] if cols_disponiveis else df


def rows_top_consumo(dias: int = 30, limite: int = 10) -> pd.DataFrame:
    """Top N itens por consumo real no período (últimos `dias` dias).
    Consumo real = saída por requisição (SAIDA_REAL_WHERE), excluindo ajustes.
    Colunas: part_number, nome_item, quantidade_consumida, n_saidas."""
    hoje = date.today()
    data_inicio_str = (hoje - timedelta(days=dias)).strftime("%Y-%m-%d")

    with transaction() as conn:
        rows = conn.execute(f"""
            SELECT inv.part_number, inv.nome_item,
                   SUM(m.quantidade) AS quantidade_consumida,
                   COUNT(*)          AS n_saidas
            FROM movimentacoes m
            JOIN inventario inv ON inv.id = m.item_id
            WHERE {SAIDA_REAL_WHERE}
              AND m.data_hora >= ?
            GROUP BY inv.id, inv.part_number, inv.nome_item
            ORDER BY quantidade_consumida DESC
            LIMIT ?
        """, (data_inicio_str, limite)).fetchall()

    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df

    colunas = ["part_number", "nome_item", "quantidade_consumida", "n_saidas"]
    cols_disponiveis = [c for c in colunas if c in df.columns]
    return df[cols_disponiveis] if cols_disponiveis else df


def rows_entradas_saidas(periodo: str = "hoje") -> pd.DataFrame:
    """Volume de entradas e saídas por período.
    Colunas: tipo, data, quantidade, part_number, nome_item."""
    hoje = date.today()

    # Mapeia período para intervalo de datas
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
    if df.empty:
        return df

    colunas = ["tipo", "data", "quantidade", "part_number", "nome_item"]
    cols_disponiveis = [c for c in colunas if c in df.columns]
    return df[cols_disponiveis] if cols_disponiveis else df


def rows_cobertura_faixa(faixa: str = "≤7") -> pd.DataFrame:
    """Itens numa faixa de cobertura (≤7, 8-15, 16-30, …), espelhando o gráfico do
    Almoxarifado: só itens COM consumo e com cobertura válida (exclui a sentinela 999)."""
    itens = []
    for i in listar_inventario():
        cob = i.get("dias_cobertura")
        if cob is None or cob == PREVISAO_RUPTURA_SEM_RISCO or i.get("sem_movimentacao"):
            continue
        if _faixa_cobertura(cob) == faixa:
            itens.append(i)
    return _df_itens(itens)
