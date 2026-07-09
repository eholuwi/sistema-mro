"""services/dashboards.py — v3.0.0 (Dashboards por público)

Assemblers PUROS dos view-models por público (Comprador / Gestão / Diretoria).
Cada função retorna um dict de números/listas/séries montado a partir das funções
que já existem (planejamento, valoração, classificação). NÃO importa streamlit — o
`app.py` só desenha. Mesmo padrão-assembler da Ficha 360 (`services/ficha.py`):
~toda a inteligência já existe; aqui é só montagem por perfil.

Sem SQL na UI (padrão DT-3) e sem migração: tudo derivado na leitura.
"""

from collections import Counter
from datetime import date, datetime

from services.constants import (
    ABC_LIMIAR_A, ABC_LIMIAR_B, AGING_ALERTA_DIAS, AGING_CRITICO_DIAS,
    CC_GENERICOS, PREVISAO_RUPTURA_SEM_RISCO, SAIDA_REAL_WHERE,
)
from services.db_functions import (
    _preco_valoracao, calcular_giro, listar_inventario, listar_scs, obter_abc_valor,
    obter_evolucao_valor_imobilizado, obter_valor_imobilizado, transaction,
)
from services.planejamento import gerar_scs_sugeridas, gerar_sugestoes_reposicao

# Rótulos dos públicos — fonte única de verdade (app.py e manual de Ajuda consomem).
PUBLICO_COMPRADOR = "Comprador"
PUBLICO_GESTAO = "Gestão"
PUBLICO_DIRETORIA = "Diretoria"
PUBLICO_EXECUTIVO = "Mensal"   # v3.2.0 — visão executiva de apresentação (mês a mês)
PUBLICOS = [PUBLICO_COMPRADOR, PUBLICO_GESTAO, PUBLICO_DIRETORIA, PUBLICO_EXECUTIVO]


def _dias_desde(iso, hoje=None):
    """Dias inteiros entre a data ISO ('YYYY-MM-DD' ou com hora) e hoje. None se não parsear."""
    if not iso:
        return None
    hoje = hoje or date.today()
    try:
        d = datetime.strptime(str(iso).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (hoje - d).days


def _giro_medio(itens):
    """Média do giro anual dos itens COM consumo real (giro só faz sentido com saídas).
    Reusa `calcular_giro` com UMA conexão compartilhada (padrão do export) para evitar
    N transações. Ignora giro=0 (sem saída na janela). None se nada aplicável."""
    alvo = [i for i in itens if not i.get("sem_movimentacao")]
    if not alvo:
        return None
    giros = []
    try:
        with transaction() as conn:
            for i in alvo:
                gv = calcular_giro(i["id"], conn=conn).get("giro_anual")
                if gv:
                    giros.append(gv)
    except Exception:
        return None
    return round(sum(giros) / len(giros), 2) if giros else None


# ══════════════════════════════════════════════════════════════════════════════
# 👤 COMPRADOR — "o que fazer agora"
# ══════════════════════════════════════════════════════════════════════════════

def montar_visao_comprador(top_n=12, hoje=None):
    """View-model do Comprador: KPIs de ação, fila priorizada, SCs sugeridas e aging.

    Reusa a fila e os agrupamentos do Assistente de Reposição (v2.5/v2.8) — nada é
    recalculado aqui. `top_n` limita a prévia da fila (o total vem em `total_fila`)."""
    sugestoes = gerar_sugestoes_reposicao()          # já ordenada por urgência
    scs_sugeridas = gerar_scs_sugeridas()            # agrupadas por natureza
    scs_abertas = listar_scs(apenas_abertas=True)
    itens = listar_inventario()

    criticos = sum(1 for s in sugestoes if s.get("prioridade_tier") == 0)
    atrasados = sum(1 for s in sugestoes if s.get("comprar_atrasado"))
    # Ruptura = item com consumo real E estoque físico zerado (risco imediato).
    rupturas = sum(1 for i in itens
                   if not i.get("sem_movimentacao") and (i.get("estoque_atual") or 0) <= 0)

    # Aging das SCs abertas por faixa de dias desde a abertura (transparência do gargalo).
    aging = {"0-7": 0, "8-15": 0, "15+": 0, "sem_data": 0}
    for sc in scs_abertas:
        d = _dias_desde(sc.get("data_abertura"), hoje=hoje)
        if d is None:
            aging["sem_data"] += 1
        elif d <= AGING_ALERTA_DIAS:
            aging["0-7"] += 1
        elif d <= AGING_CRITICO_DIAS:
            aging["8-15"] += 1
        else:
            aging["15+"] += 1

    return {
        "kpis": {
            "criticos": criticos,
            "comprar_atrasados": atrasados,
            "scs_abertas": len(scs_abertas),
            "rupturas": rupturas,
        },
        "fila": sugestoes[:top_n],
        "total_fila": len(sugestoes),
        "scs_sugeridas": scs_sugeridas,
        "aging": aging,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 📊 GESTÃO — "saúde da operação"
# ══════════════════════════════════════════════════════════════════════════════

def montar_visao_gestao():
    """View-model da Gestão: nível de serviço, cobertura, valor, giro, distribuição
    de status e padrões de demanda. Tudo derivado de `listar_inventario` (uma
    varredura) + `obter_valor_imobilizado` + `calcular_giro`."""
    itens = listar_inventario()
    total = len(itens)

    dist = {"ok": 0, "atencao": 0, "comprar": 0, "sem_mov": 0,
            "zerados": 0, "inventariado": 0}
    # Saúde FÍSICA do estoque — Ok/Atenção/Crítico/Zerado sobre TODOS os itens,
    # INCLUSIVE os "Sem Movimentação" (usa `status_estoque_fisico`, que existe em
    # todo item, em vez de `status_material`, que sobrepõe o status por "Sem Mov.").
    # Reusa a classificação Mín×1,2 já validada; só destaca "Zerado" (=0) do crítico.
    saude = {"ok": 0, "atencao": 0, "critico": 0, "zerado": 0}
    com_consumo = 0
    fora_ruptura = 0
    coberturas = []
    for i in itens:
        s = i.get("status_material", "")
        if i.get("sem_movimentacao"):
            dist["sem_mov"] += 1
        elif "COMPRAR" in s:
            dist["comprar"] += 1
        elif "ATENÇÃO" in s:
            dist["atencao"] += 1
        elif "OK" in s:
            dist["ok"] += 1
        if (i.get("estoque_atual") or 0) <= 0:
            dist["zerados"] += 1

        sf = i.get("status_estoque_fisico", "")
        if (i.get("estoque_atual") or 0) <= 0:
            saude["zerado"] += 1           # = 0 (destacado do crítico)
        elif "COMPRAR" in sf:
            saude["critico"] += 1          # abaixo/no mínimo, mas > 0
        elif "ATENÇÃO" in sf:
            saude["atencao"] += 1          # perto de ficar abaixo do mínimo
        else:
            saude["ok"] += 1               # acima do confortável (Mín × 1,2)
        if i.get("data_inventario"):
            dist["inventariado"] += 1
        if not i.get("sem_movimentacao"):
            com_consumo += 1
            if (i.get("estoque_atual") or 0) > 0:
                fora_ruptura += 1
            cob = i.get("dias_cobertura")
            # Exclui a sentinela "sem risco" (999) para não inflar a média.
            if cob is not None and cob != PREVISAO_RUPTURA_SEM_RISCO:
                coberturas.append(cob)

    # Nível de Serviço de Estoque = proxy de disponibilidade (NÃO é OTIF de fornecedor).
    nivel_servico = round(fora_ruptura / com_consumo * 100, 1) if com_consumo else None
    cobertura_media = round(sum(coberturas) / len(coberturas), 1) if coberturas else None
    valor = obter_valor_imobilizado()
    giro_medio = _giro_medio(itens)

    demanda = Counter(i.get("padrao_demanda") for i in itens if i.get("padrao_demanda"))
    xyz = Counter(i.get("classe_xyz") for i in itens if i.get("classe_xyz"))

    return {
        "kpis": {
            "nivel_servico": nivel_servico,        # % (ou None se sem itens com consumo)
            "cobertura_media": cobertura_media,    # dias (ou None)
            "valor_imobilizado": valor["total_brl"],
            "giro_medio": giro_medio,              # x/ano (ou None)
        },
        "valor_detalhe": valor,
        "distribuicao": dist,
        "saude_fisica": saude,
        "total": total,
        "com_consumo": com_consumo,
        "demanda": dict(demanda),
        "xyz": dict(xyz),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 🏛️ DIRETORIA — "retrato financeiro"
# ══════════════════════════════════════════════════════════════════════════════

def montar_visao_diretoria(dias_evolucao=180, top_abc=10):
    """View-model da Diretoria: valor imobilizado (+transparência), evolução e ABC por
    valor. Savings (Spot Saving) fica como placeholder honesto — ADIADO na v2.3.0."""
    valor = obter_valor_imobilizado()
    evolucao = obter_evolucao_valor_imobilizado(dias=dias_evolucao)
    abc = obter_abc_valor(limit=top_abc)
    return {
        "kpis": {
            "valor_imobilizado": valor["total_brl"],
            "savings": None,                # ADIADO → renderizado como "em breve"
        },
        "valor_detalhe": valor,
        "evolucao": evolucao,               # {"serie": [...], "n_snapshots": N}
        "abc_valor": abc,
        "savings_disponivel": False,        # placeholder honesto (sem ingestão nova)
    }


# ══════════════════════════════════════════════════════════════════════════════
# 📊 EXECUTIVO / MENSAL — panorama do ANO CORRENTE (YTD) p/ apresentação (v3.2.0)
# ══════════════════════════════════════════════════════════════════════════════
#
# Visão densa de apresentação, sempre do ANO CORRENTE (1º/jan → hoje): foco em VALOR
# (R$) e em RANKINGS Top 10, além de séries mensais e destaques. Princípios do PO:
#   • CONSUMO REAL sempre = saída por requisição (`SAIDA_REAL_WHERE`) — ajustes físicos
#     de inventário (contagens) NÃO entram (era o que inflava a curva ABC).
#   • Valoração pelo preço de referência (cache SCM) / último preço — mesma base do
#     Valor Imobilizado. Rótulo honesto na UI.
#   • Reaproveita Gestão/Comprador para as métricas de estado (nível de serviço, giro,
#     distribuição, demanda, aging), sem recalcular.


def _consumo_ytd_por_item(ano, conn=None):
    """Consumo REAL do ano (por requisição), por item, com qtd e VALOR (R$ = qtd ×
    preço de valoração). Uma varredura; base dos rankings por valor, do ABC e da
    composição por tipo de material."""
    itens = []
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT i.id, i.part_number, i.nome_item, i.tipo_material, i.unidade,
                   COALESCE(SUM(m.quantidade),0) AS qtd
            FROM movimentacoes m JOIN inventario i ON i.id = m.item_id
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', m.data_hora)=?
            GROUP BY i.id HAVING qtd > 0
        """, (str(ano),)).fetchall()
        for r in rows:
            preco, _origem, _moeda = _preco_valoracao(c, r["id"])
            itens.append({
                "item_id": r["id"], "part_number": r["part_number"],
                "nome_item": r["nome_item"], "tipo_material": r["tipo_material"] or "—",
                "unidade": r["unidade"], "qtd": round(float(r["qtd"]), 2),
                "preco": preco, "valor": round(float(r["qtd"]) * preco, 2),
            })
    return itens


def _classificar_abc(itens_consumo):
    """Curva ABC (classe A/B/C por % acumulada do valor) sobre a lista de consumo YTD.
    Mesma convenção de `obter_abc_valor`. Devolve (lista ordenada desc, total)."""
    itens = sorted([dict(x) for x in itens_consumo if x["valor"] > 0],
                   key=lambda x: x["valor"], reverse=True)
    total = sum(x["valor"] for x in itens)
    acc = 0.0
    for x in itens:
        prev = (acc / total * 100.0) if total else 0.0
        acc += x["valor"]
        x["pct_acumulado"] = round((acc / total * 100.0) if total else 0.0, 1)
        x["classe"] = "A" if prev < ABC_LIMIAR_A else ("B" if prev < ABC_LIMIAR_B else "C")
    return itens, round(total, 2)


def _composicao_por_tipo(itens_consumo, top=8):
    """Valor consumido YTD agregado por tipo de material (donut). Junta a cauda longa
    em 'Outros' para o gráfico não virar confete."""
    agg = Counter()
    for x in itens_consumo:
        agg[x["tipo_material"] or "—"] += x["valor"]
    ordenado = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
    principais = ordenado[:top]
    outros = sum(v for _, v in ordenado[top:])
    dados = [{"tipo": t, "valor": round(v, 2)} for t, v in principais if v > 0]
    if outros > 0:
        dados.append({"tipo": "Outros", "valor": round(outros, 2)})
    return dados


def _consumo_mensal_ytd(ano, conn=None):
    """Valor consumido (R$) e quantidade por mês do ano corrente (evolução). Valor via
    preco_referencia direto no SQL (rápido); coerente com os rankings por valor."""
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT strftime('%Y-%m', m.data_hora) AS mes,
                   COALESCE(SUM(m.quantidade * COALESCE(i.preco_referencia,0)),0) AS valor,
                   COALESCE(SUM(m.quantidade),0) AS qtd
            FROM movimentacoes m JOIN inventario i ON i.id = m.item_id
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', m.data_hora)=?
            GROUP BY mes ORDER BY mes
        """, (str(ano),)).fetchall()
    return [{"mes": r["mes"], "valor": round(float(r["valor"] or 0), 2),
             "qtd": round(float(r["qtd"] or 0), 2)} for r in rows if r["mes"]]


def _scs_criadas_por_mes_ytd(ano, conn=None):
    """SCs criadas por mês no ano corrente (exclui canceladas)."""
    with transaction(conn) as c:
        rows = c.execute("""
            SELECT strftime('%Y-%m', data_abertura) AS mes, COUNT(*) AS n
            FROM solicitacoes_compra
            WHERE data_abertura IS NOT NULL AND status NOT IN ('Cancelado')
              AND strftime('%Y', data_abertura)=?
            GROUP BY mes ORDER BY mes
        """, (str(ano),)).fetchall()
    return [{"mes": r["mes"], "criadas": r["n"]} for r in rows if r["mes"]]


def _n_requisicoes_ytd(ano, conn=None):
    """Nº de requisições distintas com consumo real no ano corrente."""
    with transaction(conn) as c:
        r = c.execute(f"""
            SELECT COUNT(DISTINCT requisicao_id) AS n FROM movimentacoes
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', data_hora)=?
        """, (str(ano),)).fetchone()
    return r["n"] or 0


def _ranking_cc_ytd(ano, limit=10, conn=None):
    """Top centros de custo por valor consumido (R$) no ano corrente. Exclui os CCs
    genéricos/contábeis (99000/INVENTÁRIO/EDIÇÃO), que não indicam setor consumidor."""
    placeholders = ",".join("?" for _ in CC_GENERICOS)
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT COALESCE(NULLIF(TRIM(m.centro_custo),''),'(sem CC)') AS rotulo,
                   COALESCE(SUM(m.quantidade * COALESCE(i.preco_referencia,0)),0) AS valor
            FROM movimentacoes m JOIN inventario i ON i.id = m.item_id
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', m.data_hora)=?
              AND TRIM(COALESCE(m.centro_custo,'')) NOT IN ({placeholders})
            GROUP BY rotulo HAVING valor > 0 ORDER BY valor DESC LIMIT ?
        """, (str(ano), *CC_GENERICOS, limit)).fetchall()
    return [{"rotulo": r["rotulo"], "valor": round(float(r["valor"] or 0), 2)} for r in rows]


def _ranking_emitente_ytd(ano, limit=10, conn=None):
    """Top emitentes por nº de requisições reais no ano corrente."""
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT COALESCE(NULLIF(TRIM(emitente),''),'(sem emitente)') AS rotulo,
                   COUNT(DISTINCT requisicao_id) AS n
            FROM movimentacoes
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', data_hora)=?
            GROUP BY rotulo ORDER BY n DESC LIMIT ?
        """, (str(ano), limit)).fetchall()
    return [{"rotulo": r["rotulo"], "n": r["n"]} for r in rows]


def _ranking_setor_ytd(ano, limit=10, conn=None):
    """Top setores por nº de requisições reais no ano corrente."""
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT COALESCE(NULLIF(TRIM(setor),''),'(sem setor)') AS rotulo,
                   COUNT(DISTINCT requisicao_id) AS n
            FROM movimentacoes
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', data_hora)=?
            GROUP BY rotulo ORDER BY n DESC LIMIT ?
        """, (str(ano), limit)).fetchall()
    return [{"rotulo": r["rotulo"], "n": r["n"]} for r in rows]


def _top_valor_imobilizado(limit=10, conn=None):
    """Top itens por capital PARADO em estoque (estoque_atual × preço de referência)."""
    with transaction(conn) as c:
        rows = c.execute("""
            SELECT part_number, nome_item,
                   estoque_atual * COALESCE(preco_referencia,0) AS valor
            FROM inventario
            WHERE COALESCE(preco_referencia,0) > 0 AND COALESCE(estoque_atual,0) > 0
            ORDER BY valor DESC LIMIT ?
        """, (limit,)).fetchall()
    return [{"part_number": r["part_number"], "nome_item": r["nome_item"],
             "valor": round(float(r["valor"] or 0), 2)} for r in rows]


def _top_dead_stock(ano, limit=10, conn=None):
    """Top itens SEM consumo real no ano corrente com maior valor parado — o 'dinheiro
    dormindo' (dead stock). História forte de melhoria p/ a apresentação."""
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT i.part_number, i.nome_item,
                   i.estoque_atual * COALESCE(i.preco_referencia,0) AS valor
            FROM inventario i
            WHERE COALESCE(i.preco_referencia,0) > 0 AND COALESCE(i.estoque_atual,0) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM movimentacoes m
                  WHERE m.item_id = i.id AND {SAIDA_REAL_WHERE}
                    AND strftime('%Y', m.data_hora)=?)
            ORDER BY valor DESC LIMIT ?
        """, (str(ano), limit)).fetchall()
    return [{"part_number": r["part_number"], "nome_item": r["nome_item"],
             "valor": round(float(r["valor"] or 0), 2)} for r in rows]


def montar_visao_executiva(hoje=None):
    """View-model Executivo/Mensal do ANO CORRENTE (YTD): KPIs em R$/serviço, séries
    mensais, curva ABC e vários rankings Top 10. Reaproveita Gestão/Comprador para as
    métricas de estado. Consumo sempre REAL (por requisição), valoração pelo preço de
    referência (rótulo honesto na UI)."""
    hoje = hoje or date.today()
    ano = hoje.year

    consumo_itens = _consumo_ytd_por_item(ano)
    abc, total_consumido = _classificar_abc(consumo_itens)
    gestao = montar_visao_gestao()
    comprador = montar_visao_comprador(hoje=hoje)
    valor_imob = obter_valor_imobilizado()

    return {
        "ano": ano,
        "kpis": {
            "valor_imobilizado": valor_imob["total_brl"],
            "valor_consumido_ytd": total_consumido,
            "n_requisicoes_ytd": _n_requisicoes_ytd(ano),
            "itens_consumidos_ytd": len(consumo_itens),
            "nivel_servico": gestao["kpis"]["nivel_servico"],
            "giro_medio": gestao["kpis"]["giro_medio"],
            "criticos": comprador["kpis"]["criticos"],
            "rupturas": comprador["kpis"]["rupturas"],
        },
        "valor_detalhe": valor_imob,
        "series": {
            "consumo_mensal": _consumo_mensal_ytd(ano),
            "scs_mensal": _scs_criadas_por_mes_ytd(ano),
        },
        "abc": {"itens": abc[:12], "classes": dict(Counter(x["classe"] for x in abc)),
                "total": total_consumido},
        "composicao_tipo": _composicao_por_tipo(consumo_itens),
        "rankings": {
            "top_valor_consumido": abc[:10],                     # já ordenado por valor
            "top_qtd_consumida": sorted(consumo_itens, key=lambda x: x["qtd"],
                                        reverse=True)[:10],
            "top_valor_imobilizado": _top_valor_imobilizado(10),
            "top_dead_stock": _top_dead_stock(ano, 10),
            "top_centro_custo": _ranking_cc_ytd(ano, 10),
            "top_emitente": _ranking_emitente_ytd(ano, 10),
            "top_setor": _ranking_setor_ytd(ano, 10),
        },
        "destaques": {
            "distribuicao": gestao["distribuicao"],
            "saude_fisica": gestao["saude_fisica"],
            "demanda": gestao["demanda"],
            "xyz": gestao["xyz"],
            "aging": comprador["aging"],
            "total": gestao["total"],
        },
    }


def montar_dashboard(publico):
    """Roteador: devolve o view-model do público pedido (default = Gestão)."""
    if publico == PUBLICO_COMPRADOR:
        return montar_visao_comprador()
    if publico == PUBLICO_DIRETORIA:
        return montar_visao_diretoria()
    if publico == PUBLICO_EXECUTIVO:
        return montar_visao_executiva()
    return montar_visao_gestao()
