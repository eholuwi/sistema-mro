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
from services.constants import ENTRADA_REAL_WHERE, SAIDA_REAL_WHERE, PREVISAO_RUPTURA_SEM_RISCO
from services.db_functions import transaction, listar_inventario
from services.dashboards import montar_visao_compras_mro, _faixa_cobertura


# ──────────────────────────────────────────────────────────────────────────────
# v4.5.0 — Provedores parametrizados p/ drill-down do Dashboard Almoxarifado.
# Espelham EXATAMENTE os filtros do view-model (services/dashboards.py) para que a
# tabela aberta ao clicar componha o mesmo número do card.
# ──────────────────────────────────────────────────────────────────────────────


def _df_itens(itens):
    """Lista de itens (dicts de listar_inventario) -> DataFrame de exibição."""
    cols = [
        ("part_number", "PN"),
        ("nome_item", "Material"),
        ("estoque_atual", "Estoque"),
        ("estoque_minimo", "Mínimo"),
        ("dias_cobertura", "Cobertura (d)"),
        ("status_material", "Status"),
        ("importancia", "Criticidade"),
        ("local_armazenagem", "Local"),
    ]
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
    "todos": lambda i: True,
    # Distribuição "base de compra" (só itens com consumo) — status_material
    "ok": lambda i: not i.get("sem_movimentacao") and _tem("status_material", i, "OK"),
    "atencao": lambda i: not i.get("sem_movimentacao") and _tem("status_material", i, "ATENÇÃO"),
    "comprar": lambda i: not i.get("sem_movimentacao") and _tem("status_material", i, "COMPRAR"),
    "sem_mov": lambda i: bool(i.get("sem_movimentacao")),
    "zerados": lambda i: (i.get("estoque_atual") or 0) <= 0,
    "inventariado": lambda i: bool(i.get("data_inventario")),
    # Saúde física (TODO material) — status_estoque_fisico
    "fis_ok": lambda i: (
        (i.get("estoque_atual") or 0) > 0
        and not _tem("status_estoque_fisico", i, "COMPRAR")
        and not _tem("status_estoque_fisico", i, "ATENÇÃO")
    ),
    "fis_atencao": lambda i: (
        (i.get("estoque_atual") or 0) > 0 and _tem("status_estoque_fisico", i, "ATENÇÃO")
    ),
    "fis_critico": lambda i: (
        (i.get("estoque_atual") or 0) > 0 and _tem("status_estoque_fisico", i, "COMPRAR")
    ),
    "fis_zerado": lambda i: (i.get("estoque_atual") or 0) <= 0,
    # KPIs
    "compra_urgente": _urgente,
    "com_valor": lambda i: (i.get("estoque_atual") or 0) > 0,
    "cobertura": lambda i: (
        (not i.get("sem_movimentacao"))
        and i.get("dias_cobertura") is not None
        and i.get("dias_cobertura") != PREVISAO_RUPTURA_SEM_RISCO
    ),
    # KPI Mensal (executivo)
    "ruptura": lambda i: (not i.get("sem_movimentacao")) and (i.get("estoque_atual") or 0) <= 0,
    "com_consumo": lambda i: not i.get("sem_movimentacao"),
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
    # Mesmos predicados do view-model (services/constants.py) — o drill precisa
    # devolver exatamente as linhas que o card contou, ajustes fora dos dois lados.
    where_tipo = ENTRADA_REAL_WHERE if tipo == "entrada" else SAIDA_REAL_WHERE

    with transaction() as conn:
        rows = conn.execute(
            f"""
            SELECT DATE(m.data_hora) AS Data, inv.part_number AS PN, inv.nome_item AS Material,
                   m.quantidade AS Qtd, m.emitente AS Responsável, m.observacao AS Obs
            FROM movimentacoes m JOIN inventario inv ON inv.id = m.item_id
            WHERE {where_tipo} AND {cond}
            ORDER BY m.data_hora DESC
        """,
            (arg,),
        ).fetchall()
    return pd.DataFrame(
        [dict(r) for r in rows], columns=["Data", "PN", "Material", "Qtd", "Responsável", "Obs"]
    )


def rows_padrao_demanda(padrao):
    """Itens classificados com um padrão de demanda (Suave/Intermitente/Errático/…).
    Espelha o Counter(padrao_demanda) do view-model de gestão."""
    return _df_itens([i for i in listar_inventario() if (i.get("padrao_demanda") or "") == padrao])


def rows_abc_classe(classe="A"):
    """Itens de uma classe da Curva ABC por valor consumido. Espelha o Counter(classe)
    de obter_abc_valor que alimenta o vm['abc']."""
    from services.db_functions import obter_abc_valor

    itens = [x for x in obter_abc_valor() if x.get("classe") == classe]
    df = pd.DataFrame(itens)
    if df.empty:
        return df
    ren = {
        "part_number": "PN",
        "nome_item": "Material",
        "qtd": "Qtd consumida",
        "valor": "Valor (R$)",
        "pct_acumulado": "% acum.",
    }
    keep = [c for c in ren if c in df.columns]
    return df[keep].rename(columns=ren)


def rows_mov_mes(ym):
    """Todas as movimentações de um mês (ym = 'YYYY-MM') — compõe as barras do
    Histórico mensal (Entradas × Saídas)."""
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT DATE(m.data_hora) AS Data, m.tipo AS Tipo, m.quantidade AS Qtd,
                   inv.part_number AS PN, inv.nome_item AS Material, m.emitente AS Responsável
            FROM movimentacoes m JOIN inventario inv ON inv.id = m.item_id
            WHERE substr(m.data_hora,1,7) = ?
            ORDER BY m.data_hora DESC
        """,
            (ym,),
        ).fetchall()
    return pd.DataFrame(
        [dict(r) for r in rows], columns=["Data", "Tipo", "Qtd", "PN", "Material", "Responsável"]
    )


def rows_saidas_item(pn, dias=30):
    """Saídas reais (requisições) de um item (por PN) nos últimos `dias`."""
    ini = (date.today() - timedelta(days=dias)).strftime("%Y-%m-%d")
    with transaction() as conn:
        rows = conn.execute(
            f"""
            SELECT DATE(m.data_hora) AS Data, m.quantidade AS Qtd, m.setor AS Setor,
                   m.emitente AS Responsável, m.observacao AS Obs
            FROM movimentacoes m JOIN inventario inv ON inv.id = m.item_id
            WHERE inv.part_number = ? AND {SAIDA_REAL_WHERE} AND m.data_hora >= ?
            ORDER BY m.data_hora DESC
        """,
            (pn, ini),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["Data", "Qtd", "Setor", "Responsável", "Obs"])


# ──────────────────────────────────────────────────────────────────────────────
# v4.5.4 — Provedores do Dashboard KPI Mensal (executivo, YTD). Reaproveitam os
# MESMOS cálculos do view-model (services/dashboards.py) para garantir acuracidade.
# ──────────────────────────────────────────────────────────────────────────────


def _df_consumo(itens):
    """Lista de consumo YTD (dicts com qtd/valor) -> DataFrame de exibição."""
    df = pd.DataFrame(itens)
    if df.empty:
        return df
    if "valor" in df.columns:
        df = df.sort_values("valor", ascending=False)
    ren = {
        "part_number": "PN",
        "nome_item": "Material",
        "tipo_material": "Tipo",
        "unidade": "UN",
        "qtd": "Qtd consumida",
        "valor": "Valor (R$)",
        "pct_acumulado": "% acum.",
        "classe": "Classe",
    }
    return df[[c for c in ren if c in df.columns]].rename(columns=ren)


def rows_consumo_ytd(ano=None):
    """Itens com consumo real no ano (YTD). len == 'Itens movimentados (YTD)' e a soma
    de Valor == 'Consumido no ano'."""
    from services.dashboards import _consumo_ytd_por_item

    return _df_consumo(_consumo_ytd_por_item(ano or date.today().year))


def rows_abc_ytd_classe(classe="A", ano=None):
    """Itens de uma classe da Curva ABC do KPI Mensal (YTD). Espelha _classificar_abc."""
    from services.dashboards import _consumo_ytd_por_item, _classificar_abc

    itens, _tot = _classificar_abc(_consumo_ytd_por_item(ano or date.today().year))
    return _df_consumo([x for x in itens if x.get("classe") == classe])


def rows_consumo_ytd_tipo(tipo, ano=None):
    """Itens consumidos YTD de um tipo de material — compõe o donut 'Consumo por tipo'."""
    from services.dashboards import _consumo_ytd_por_item

    itens = _consumo_ytd_por_item(ano or date.today().year)
    return _df_consumo([x for x in itens if (x.get("tipo_material") or "—") == tipo])


def rows_requisicoes_ano(ano=None):
    """Requisições com consumo real no ano (distintas) — compõe 'Requisições (YTD)'."""
    ano = ano or date.today().year
    with transaction() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT r.numero_requisicao AS "Nº Req", r.data_hora AS "Data/Hora",
                   r.setor AS Setor, r.emitente AS Emitente, r.autorizador_nome AS Autorizador
            FROM requisicoes r JOIN movimentacoes m ON m.requisicao_id = r.id
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', m.data_hora) = ?
            ORDER BY r.data_hora DESC
        """,
            (str(ano),),
        ).fetchall()
    return pd.DataFrame(
        [dict(r) for r in rows], columns=["Nº Req", "Data/Hora", "Setor", "Emitente", "Autorizador"]
    )


def rows_saidas_mes(ym):
    """Saídas reais (requisições) de um mês (YYYY-MM) — compõe o 'Consumo mês a mês'."""
    with transaction() as conn:
        rows = conn.execute(
            f"""
            SELECT DATE(m.data_hora) AS Data, m.quantidade AS Qtd, inv.part_number AS PN,
                   inv.nome_item AS Material, m.setor AS Setor, m.emitente AS Responsável
            FROM movimentacoes m JOIN inventario inv ON inv.id = m.item_id
            WHERE {SAIDA_REAL_WHERE} AND substr(m.data_hora,1,7) = ?
            ORDER BY m.data_hora DESC
        """,
            (ym,),
        ).fetchall()
    return pd.DataFrame(
        [dict(r) for r in rows], columns=["Data", "Qtd", "PN", "Material", "Setor", "Responsável"]
    )


# ──────────────────────────────────────────────────────────────────────────────
# v4.5.5 — Provedores do Dashboard Comprador (SCM WK29, só MRO). Reusam a mesma
# base de SCs do ano do view-model (montar_visao_compras_mro).
# ──────────────────────────────────────────────────────────────────────────────


def _scs_ano(ano=None):
    """SCs do ano corrente (uma linha por SC) — mesma base do view-model do Comprador."""
    ano = ano or date.today().year
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT sc.numero_sc, sc.status, sc.data_abertura, sc.numero_po, sc.fornecedor,
                   sc.comprador, sc.departamento, COUNT(i.id) AS n_itens,
                   COALESCE(SUM(i.valor_total), 0) AS valor
            FROM solicitacoes_compra sc LEFT JOIN itens_sc i ON i.sc_id = sc.id
            WHERE substr(sc.data_abertura, 1, 4) = ?
            GROUP BY sc.id ORDER BY sc.data_abertura DESC
        """,
            (str(ano),),
        ).fetchall()
    return [dict(r) for r in rows]


def _df_scs(scs):
    df = pd.DataFrame(scs)
    if df.empty:
        return df
    ren = {
        "numero_sc": "SC",
        "status": "Status",
        "data_abertura": "Abertura",
        "numero_po": "PO",
        "fornecedor": "Fornecedor",
        "comprador": "Comprador",
        "departamento": "Depto",
        "n_itens": "Itens",
        "valor": "Valor (R$)",
    }
    keep = [c for c in ren if c in df.columns]
    return df[keep].rename(columns=ren)


def rows_scs_status(status):
    """SCs de um status (compõe 'Status dos POs')."""
    return _df_scs([s for s in _scs_ano() if (s.get("status") or "—") == status])


def rows_scs_mes(ym):
    """SCs abertas num mês (YYYY-MM) — compõe 'Itens/SCs por mês'."""
    return _df_scs([s for s in _scs_ano() if (s.get("data_abertura") or "")[:7] == ym])


# v5.9.0 — `rows_scs_comprador` e `rows_scs_itens_faixa` saíram junto com os gráficos
# que as chamavam ("Itens por comprador" e "Itens por Pedido"), removidos do Dashboard
# do Comprador. Ficaram sem nenhum chamador.


def rows_criticos_reposicao():
    """Itens críticos do KPI Mensal = sugestões de reposição de prioridade máxima
    (tier 0). Espelha comprador['kpis']['criticos']."""
    from services.planejamento import gerar_sugestoes_reposicao

    sug = [s for s in gerar_sugestoes_reposicao() if s.get("prioridade_tier") == 0]
    df = pd.DataFrame(sug)
    if df.empty:
        return df
    pref = ["part_number", "nome_item", "estoque_atual", "estoque_minimo", "qtd_sugerida", "dias_cobertura"]
    cols = [c for c in pref if c in df.columns] or list(df.columns)[:8]
    ren = {
        "part_number": "PN",
        "nome_item": "Material",
        "estoque_atual": "Estoque",
        "estoque_minimo": "Mínimo",
        "qtd_sugerida": "Sugerido",
        "dias_cobertura": "Cobertura (d)",
    }
    return df[cols].rename(columns={k: v for k, v in ren.items() if k in cols})


def rows_requisicoes_dia():
    """Requisições emitidas hoje (cada linha = 1 requisição)."""
    hoje = date.today().strftime("%Y-%m-%d")
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT numero_requisicao AS "Nº Req", data_hora AS "Data/Hora",
                   setor AS Setor, emitente AS Emitente, autorizador_nome AS Autorizador
            FROM requisicoes WHERE substr(data_hora,1,10) = ?
            ORDER BY data_hora DESC
        """,
            (hoje,),
        ).fetchall()
    return pd.DataFrame(
        [dict(r) for r in rows], columns=["Nº Req", "Data/Hora", "Setor", "Emitente", "Autorizador"]
    )


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
        "ok": lambda r: (
            (r.get("estoque_atual", 0) or 0) >= (r.get("estoque_minimo", 0) or 0)
            and (r.get("dias_cobertura", 0) or 0) >= 30
        ),
        "atenção": lambda r: (
            (r.get("estoque_atual", 0) or 0) >= (r.get("estoque_minimo", 0) or 0)
            and (r.get("dias_cobertura", 0) or 0) < 30
        ),
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
        rows = conn.execute(
            f"""
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
        """,
            (data_inicio_str, limite),
        ).fetchall()

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
        rows = conn.execute(
            """
            SELECT m.tipo, DATE(m.data_hora) AS data, m.quantidade,
                   inv.part_number, inv.nome_item
            FROM movimentacoes m
            JOIN inventario inv ON inv.id = m.item_id
            WHERE m.data_hora >= ? AND m.data_hora < ?
            ORDER BY m.data_hora DESC
        """,
            (data_inicio_str, data_fim_str),
        ).fetchall()

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
