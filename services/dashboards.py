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
    ABC_LIMIAR_A,
    ABC_LIMIAR_B,
    AGING_ALERTA_DIAS,
    AGING_CRITICO_DIAS,
    CC_GENERICOS,
    PREVISAO_RUPTURA_SEM_RISCO,
    ENTRADA_REAL_WHERE,
    SAIDA_REAL_WHERE,
)
from services.db_functions import (
    _preco_valoracao,
    calcular_giro,
    listar_inventario,
    listar_scs,
    obter_valor_imobilizado,
    obter_abc_valor,
    transaction,
    setor_dominante_por_item,
)
from services.planejamento import gerar_scs_sugeridas, gerar_sugestoes_reposicao

# Rótulos dos públicos — fonte única de verdade (app.py e manual de Ajuda consomem).
PUBLICO_COMPRADOR = "Comprador"
PUBLICO_GESTAO = "Gestão"
PUBLICO_EXECUTIVO = "KPI Mensal"  # v3.2.0 apresentação mês a mês; v3.3.0 renomeado (era "Mensal")
PUBLICOS = [PUBLICO_COMPRADOR, PUBLICO_GESTAO, PUBLICO_EXECUTIVO]


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
    sugestoes = gerar_sugestoes_reposicao()  # já ordenada por urgência
    scs_sugeridas = gerar_scs_sugeridas()  # agrupadas por natureza
    scs_abertas = listar_scs(apenas_abertas=True)
    itens = listar_inventario()

    criticos = sum(1 for s in sugestoes if s.get("prioridade_tier") == 0)
    atrasados = sum(1 for s in sugestoes if s.get("comprar_atrasado"))
    # Ruptura = item com consumo real E estoque físico zerado (risco imediato).
    rupturas = sum(1 for i in itens if not i.get("sem_movimentacao") and (i.get("estoque_atual") or 0) <= 0)

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
# 🛒 DASHBOARD COMPRAS MRO (§1) — analytics de COMPRAS sobre o Relatório de SCs
# ══════════════════════════════════════════════════════════════════════════════

# v5.9.0 — saíram daqui, com os blocos que os usavam: AGING_FAIXAS, SCPO_FAIXAS,
# _faixa_aging, _faixa_sc_po e _iso_week (aging, SC→PO e evolução semanal).


def _dias_entre(iso1, iso2):
    """Dias inteiros de iso1 até iso2. None se algum não parsear."""

    def _p(x):
        try:
            return datetime.strptime(str(x).strip()[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError, AttributeError):
            return None

    a, b = _p(iso1), _p(iso2)
    return (b - a).days if (a and b) else None


def _po_do_item(r):
    """Nº do Pedido de Compra de uma linha de item de SC, ou "" se ainda não tem.

    O PO aparece em dois lugares e nem sempre nos dois: `itens_sc.numero_po` (grão
    do item, chega pelo Relatório de SCs) e `solicitacoes_compra.numero_po` (grão da
    SC). Uma SC pode render vários POs, então o campo do item manda quando existe —
    é ele que separa pedidos distintos dentro da mesma SC."""
    return str(r.get("po_item") or "").strip() or str(r.get("po_sc") or "").strip()


def montar_visao_compras_mro(hoje=None):
    """View-model do Dashboard de Comprador (§1): analytics de COMPRAS sobre as SCs
    importadas do Relatório de SCs — comprador real, data do PO (DT Emissão), aging,
    fornecedores, departamentos e solicitantes. PURO (DT-3): monta números/listas;
    o `app.py` só desenha. WK por ISO week (`date.isocalendar`)."""
    from collections import defaultdict
    from services.db_functions import _nome_fornecedor_valido

    hoje = hoje or date.today()
    hoje_iso = hoje.strftime("%Y-%m-%d")
    # Escopo: ANO CORRENTE (pedido do usuário / prompt "Ano corrente quase sempre") —
    # exclui SCs antigas nunca fechadas (backlog de anos anteriores) da fila e do aging.
    ano_f = str(hoje.year)

    with transaction() as conn:
        scs = [
            dict(r)
            for r in conn.execute(
                """
            SELECT sc.id, sc.numero_sc, sc.status, sc.data_abertura, sc.data_aprovacao,
                   sc.data_po, sc.numero_po, sc.fornecedor, sc.comprador, sc.solicitante,
                   sc.departamento,
                   COALESCE(SUM(i.valor_total), 0) AS valor,
                   COUNT(i.id) AS n_itens,
                   SUM(CASE WHEN COALESCE(i.saldo_residual, i.quantidade_solicitada - i.quantidade_recebida) > 0
                            THEN 1 ELSE 0 END) AS n_pendentes
            FROM solicitacoes_compra sc
            LEFT JOIN itens_sc i ON i.sc_id = sc.id
            WHERE substr(sc.data_abertura, 1, 4) = ?
            GROUP BY sc.id
        """,
                (ano_f,),
            ).fetchall()
        ]

        itens_abertos = [
            dict(r)
            for r in conn.execute(
                """
            SELECT sc.numero_sc, sc.data_abertura, sc.data_aprovacao, sc.numero_po, sc.status,
                   sc.comprador, sc.solicitante, sc.departamento,
                   inv.id AS item_id, inv.part_number, inv.nome_item,
                   inv.estoque_atual, inv.estoque_minimo
            FROM itens_sc i
            JOIN solicitacoes_compra sc ON sc.id = i.sc_id
            JOIN inventario inv ON inv.id = i.item_id
            WHERE sc.status NOT IN ('Recebido', 'Cancelado')
              AND substr(sc.data_abertura, 1, 4) = ?
              AND COALESCE(i.saldo_residual, i.quantidade_solicitada - i.quantidade_recebida) > 0
        """,
                (ano_f,),
            ).fetchall()
        ]

        # Base ITEM-LEVEL do ano — uma linha por item de SC. Alimenta os 4 cards, o
        # dispêndio (mensal e por setor) e os fornecedores por valor, sem query nova.
        # O nome do fornecedor válido é escolhido no Python porque o fornecedor_item
        # às vezes traz lixo numérico ("1.0"/"2.0") junto do valor, enquanto o nome
        # real está em sc.fornecedor (ou vice-versa).
        itens_rows = [
            dict(r)
            for r in conn.execute(
                """
            SELECT sc.id AS sc_id, i.fornecedor_item AS fi, sc.fornecedor AS sf,
                   COALESCE(i.valor_total, 0) AS valor,
                   sc.data_abertura AS da, sc.data_po AS dp,
                   sc.status AS status, i.item_id AS item_id,
                   i.numero_po AS po_item, sc.numero_po AS po_sc
            FROM itens_sc i JOIN solicitacoes_compra sc ON sc.id = i.sc_id
            WHERE substr(sc.data_abertura, 1, 4) = ?
        """,
                (ano_f,),
            ).fetchall()
        ]

        row = conn.execute(
            "SELECT MAX(data_hora) AS dh FROM log_importacoes WHERE tipo LIKE 'relatorio%'"
        ).fetchone()
        ultima_atualizacao = row["dh"] if row else None

    # ── Os 4 cards (v5.9.0) — todos contados no grão de ITEM de SC ────────────
    # Antes contavam SC onde o rótulo dizia item: "Em cotação" usava len(em_cotacao)
    # (SCs) e "POs emitidos" usava len(com_po) (SCs com PO, não pedidos distintos).
    itens_cotacao = [r for r in itens_rows if "Cota" in (r["status"] or "")]
    itens_em_aberto = len(itens_cotacao)
    scs_em_aberto = len({r["sc_id"] for r in itens_cotacao})

    itens_com_po = 0
    pos_distintos = set()
    for r in itens_rows:
        po = _po_do_item(r)
        if po:
            itens_com_po += 1
            pos_distintos.add(po)

    # Painel de Prioridades — itens abertos, mais velho primeiro (a fila do dia).
    # Não é desenhado como bloco próprio desde a v5.9.0, mas segue no view-model:
    # `drill_down.rows_itens_em_aberto` (drill do card "SCs em Aberto") o consome.
    # v3.7.0 (A1): sem a coluna "Setor" (setor_responsavel era 98% "Improdutivo").
    painel = []
    for it in itens_abertos:
        aging = _dias_entre(it["data_abertura"], hoje_iso)
        painel.append(
            {
                "aging": aging if aging is not None else -1,
                "sc": it["numero_sc"],
                "item": it["nome_item"],
                "pn": it["part_number"],
                "comprador": (it["comprador"] or "—"),
            }
        )
    painel.sort(key=lambda x: x["aging"], reverse=True)

    # Demanda "em aberto" (D3): só SCs em COTAÇÃO e AINDA sem PO (com saldo pendente).
    # Setor = setor DOMINANTE derivado do consumo real (não o setor_responsavel).
    itens_d3 = [
        it
        for it in itens_abertos
        if "Cota" in (it.get("status") or "") and not (it.get("numero_po") or "").strip()
    ]

    # ── Dispêndio (v5.9.0) — valor do item no MÊS DO PO (decisão do usuário) ──
    # `data_po` é quando o dinheiro foi de fato comprometido; `data_abertura` só diz
    # quando alguém pediu. Item sem PO ainda não é dispêndio e fica de fora.
    # Uma única chamada a `setor_dominante_por_item` serve o Ranking de Setor e a
    # demanda em aberto (a função faz uma query só, então vale juntar os ids).
    ids_com_valor = {r["item_id"] for r in itens_rows if float(r["valor"] or 0) > 0}
    setor_dom = setor_dominante_por_item(list({it["item_id"] for it in itens_d3} | ids_com_valor))

    disp_mes, disp_setor = Counter(), Counter()
    for r in itens_rows:
        v = float(r["valor"] or 0)
        if v <= 0:
            continue
        mes_po = (r["dp"] or "")[:7]
        if mes_po:
            disp_mes[mes_po] += v
        # Item sem consumo real não tem setor dominante — fica fora do ranking em
        # vez de virar balde "—" (mesma regra que a demanda em aberto já usa).
        _setor = setor_dom.get(r["item_id"])
        if _setor:
            disp_setor[_setor] += v

    _meses_disp = sorted(disp_mes)
    dispendio_mensal = {
        "meses": _meses_disp,
        "valores": [round(disp_mes[m], 2) for m in _meses_disp],
    }
    dispendio_setor = [{"setor": s, "valor": round(v, 2)} for s, v in disp_setor.most_common(10)]

    dep_cont = Counter()
    for it in itens_d3:
        # v3.10.0: item sem setor nomeado no consumo real fica FORA de Setores
        # (nada de balde "—").
        _setor = setor_dom.get(it["item_id"])
        if _setor:
            dep_cont[_setor] += 1
    por_departamento = [{"departamento": k, "n": v} for k, v in dep_cont.most_common()]

    # Fornecedor válido (resolve o lixo "1.0"/"2.0" em fornecedor_item).
    def _forn_valido(fi, sf):
        return next((c.strip() for c in (fi, sf) if c and _nome_fornecedor_valido(c)), None)

    forn_agg = defaultdict(lambda: {"valor": 0.0, "itens": 0})
    for r in itens_rows:
        nome = _forn_valido(r["fi"], r["sf"])
        if not nome:
            continue
        forn_agg[nome]["valor"] += float(r["valor"] or 0)
        forn_agg[nome]["itens"] += 1
    fornecedores_top = sorted(
        [
            {"fornecedor": k, "valor": round(v["valor"], 2), "itens": v["itens"]}
            for k, v in forn_agg.items()
            if v["valor"] > 0
        ],
        key=lambda x: x["valor"],
        reverse=True,
    )[:10]

    # Volume mensal: Itens / SCs / POs por mês (YYYY-MM).
    mes_itens, mes_scs, mes_pos = Counter(), Counter(), Counter()
    for s in scs:
        m = (s["data_abertura"] or "")[:7]
        if m:
            mes_scs[m] += 1
            mes_itens[m] += int(s["n_itens"] or 0)
        if s["data_po"]:
            mes_pos[(s["data_po"] or "")[:7]] += 1
    meses = sorted(m for m in (set(mes_scs) | set(mes_pos)) if m)
    volume_mensal = {
        "meses": meses,
        "itens": [mes_itens.get(m, 0) for m in meses],
        "scs": [mes_scs.get(m, 0) for m in meses],
        "pos": [mes_pos.get(m, 0) for m in meses],
    }

    # v5.9.0 — a aba foi reduzida a 4 cards + 5 gráficos (pedido do usuário). Saíram
    # daqui os agregados que só alimentavam blocos redundantes ou extintos:
    # aging_dist, scpo_hist, por_comprador, por_solicitante, lead_time_fornecedor,
    # evolucao_semanal, status_pos, itens_por_pedido — e os KPIs itens_criticos,
    # valor_comprado, aging_medio e scpo_medio.
    # `painel_prioridades` e `por_departamento` PERMANECEM: não são desenhados como
    # bloco, mas `drill_down.rows_itens_em_aberto` e `rows_setores_demanda_aberta`
    # os consomem para compor os drills.
    ano, wk, _ = hoje.isocalendar()
    return {
        "ultima_atualizacao": ultima_atualizacao,
        "wk": wk,
        "ano": ano,
        "kpis": {
            "itens_abertos": itens_em_aberto,
            "scs_abertas": scs_em_aberto,
            "pos_emitidos": len(pos_distintos),
            "itens_com_po": itens_com_po,
        },
        "painel_prioridades": painel,
        "por_departamento": por_departamento,
        "fornecedores_top": fornecedores_top,
        "volume_mensal": volume_mensal,
        "dispendio_mensal": dispendio_mensal,
        "dispendio_setor": dispendio_setor,
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

    dist = {"ok": 0, "atencao": 0, "comprar": 0, "sem_mov": 0, "zerados": 0, "inventariado": 0}
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
            saude["zerado"] += 1  # = 0 (destacado do crítico)
        elif "COMPRAR" in sf:
            saude["critico"] += 1  # abaixo/no mínimo, mas > 0
        elif "ATENÇÃO" in sf:
            saude["atencao"] += 1  # perto de ficar abaixo do mínimo
        else:
            saude["ok"] += 1  # acima do confortável (Mín × 1,2)
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
            "nivel_servico": nivel_servico,  # % (ou None se sem itens com consumo)
            "cobertura_media": cobertura_media,  # dias (ou None)
            "valor_imobilizado": valor["total_brl"],
            "giro_medio": giro_medio,  # x/ano (ou None)
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
# 🏬 ALMOXARIFADO (§2) — saúde do estoque, prioridades do dia, entradas/saídas
# ══════════════════════════════════════════════════════════════════════════════


def _faixa_cobertura(d):
    if d <= 7:
        return "≤7"
    if d <= 15:
        return "8-15"
    if d <= 30:
        return "16-30"
    if d <= 60:
        return "31-60"
    if d <= 180:
        return "60-180"
    if d <= 365:
        return "180-365"
    return "365+"


COBERTURA_FAIXAS = ["≤7", "8-15", "16-30", "31-60", "60-180", "180-365", "365+"]


def montar_visao_almoxarifado(hoje=None):
    """View-model do Dashboard do Almoxarifado (§2): saúde do estoque, prioridades do dia,
    entradas/saídas por período, materiais mais movimentados, setores, consumo e histórico
    mensal. PURO (DT-3). Fora (dependem de dados que não existem): Mapa do Almoxarifado
    (exige modelo de localização/prateleira) e itens de requisição digital.

    v6.0.0 — ganha o bloco `ytd` (Consumido no Ano, Requisições Atendidas no Ano, Itens
    Movimentados no Ano e Consumo por Tipo de Material), herdado do extinto KPI Mensal.
    Nada é recalculado: reusa `_consumo_ytd_por_item`, `_n_requisicoes_ytd` e
    `_composicao_por_tipo` — as MESMAS funções que `montar_visao_executiva` consome."""
    from datetime import timedelta

    hoje = hoje or date.today()
    hoje_iso = hoje.strftime("%Y-%m-%d")
    sem_ini = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
    mes_ini = (hoje - timedelta(days=30)).strftime("%Y-%m-%d")

    itens = listar_inventario()
    total = len(itens)

    dist = {"ok": 0, "atencao": 0, "comprar": 0, "sem_mov": 0}
    cob_faixa = {f: 0 for f in COBERTURA_FAIXAS}
    coberturas = []
    estoque_baixo = compra_urgente = sem_giro = cob_menor_lead = 0
    comprar_agora = []
    for i in itens:
        s = i.get("status_material", "")
        if i.get("sem_movimentacao"):
            dist["sem_mov"] += 1
            sem_giro += 1
        elif "COMPRAR" in s:
            dist["comprar"] += 1
        elif "ATENÇÃO" in s:
            dist["atencao"] += 1
        elif "OK" in s:
            dist["ok"] += 1

        est = i.get("estoque_atual") or 0
        mn = i.get("estoque_minimo") or 0
        if mn > 0 and est <= mn:
            estoque_baixo += 1
            parada = i.get("importancia") == "Parada de Linha"
            com_giro = not i.get("sem_movimentacao")
            urgente = parada or (est <= 0 and com_giro)
            if urgente:
                compra_urgente += 1
            if urgente or com_giro:
                comprar_agora.append(
                    {
                        "pn": i["part_number"],
                        "item": i["nome_item"],
                        "estoque": est,
                        "minimo": mn,
                        "urgente": urgente,
                        "cobertura": i.get("dias_cobertura"),
                    }
                )

        cob = i.get("dias_cobertura")
        if cob is not None and cob != PREVISAO_RUPTURA_SEM_RISCO and not i.get("sem_movimentacao"):
            coberturas.append(cob)
            cob_faixa[_faixa_cobertura(cob)] += 1
            lt = i.get("lead_time_dias") or 0
            if lt and cob < lt:
                cob_menor_lead += 1

    cobertura_media = round(sum(coberturas) / len(coberturas), 1) if coberturas else None
    comprar_agora.sort(key=lambda x: (not x["urgente"], x["estoque"]))

    valor = obter_valor_imobilizado()

    with transaction() as conn:

        def _periodo(where_tipo, ini, dia=False):
            campo = "= ?" if dia else ">= ?"
            r = conn.execute(
                f"SELECT COUNT(*) n, COALESCE(SUM(quantidade),0) q FROM movimentacoes "
                f"WHERE {where_tipo} AND substr(data_hora,1,10) {campo}",
                (ini,),
            ).fetchone()
            return {"n": r["n"], "q": round(r["q"], 1)}

        entradas = {
            "hoje": _periodo(ENTRADA_REAL_WHERE, hoje_iso, dia=True),
            "semana": _periodo(ENTRADA_REAL_WHERE, sem_ini),
            "mes": _periodo(ENTRADA_REAL_WHERE, mes_ini),
        }
        saidas = {
            "hoje": _periodo(SAIDA_REAL_WHERE, hoje_iso, dia=True),
            "semana": _periodo(SAIDA_REAL_WHERE, sem_ini),
            "mes": _periodo(SAIDA_REAL_WHERE, mes_ini),
        }
        req_hoje = conn.execute(
            "SELECT COUNT(*) FROM requisicoes WHERE substr(data_hora,1,10)=?", (hoje_iso,)
        ).fetchone()[0]

        top_recebidos = [
            dict(r)
            for r in conn.execute(
                f"""
            SELECT inv.part_number pn, inv.nome_item item, SUM(m.quantidade) q
            FROM movimentacoes m JOIN inventario inv ON inv.id=m.item_id
            WHERE {ENTRADA_REAL_WHERE} AND substr(m.data_hora,1,10) >= ?
            GROUP BY m.item_id ORDER BY q DESC LIMIT 10
        """,
                (mes_ini,),
            ).fetchall()
        ]
        mais_consumidos = [
            dict(r)
            for r in conn.execute(
                f"""
            SELECT inv.part_number pn, inv.nome_item item, SUM(m.quantidade) q
            FROM movimentacoes m JOIN inventario inv ON inv.id=m.item_id
            WHERE {SAIDA_REAL_WHERE} AND substr(m.data_hora,1,10) >= ?
            GROUP BY m.item_id ORDER BY q DESC LIMIT 10
        """,
                (mes_ini,),
            ).fetchall()
        ]
        setores = [
            dict(r)
            for r in conn.execute(f"""
            SELECT COALESCE(NULLIF(TRIM(setor),''),'—') setor, COUNT(*) n, ROUND(SUM(quantidade),1) q
            FROM movimentacoes WHERE {SAIDA_REAL_WHERE}
            GROUP BY 1 ORDER BY n DESC LIMIT 10
        """).fetchall()
        ]
        hist = [
            dict(r)
            for r in conn.execute(f"""
            SELECT substr(data_hora,1,7) ym,
                   ROUND(SUM(CASE WHEN {ENTRADA_REAL_WHERE} THEN quantidade ELSE 0 END),1) ent,
                   ROUND(SUM(CASE WHEN {SAIDA_REAL_WHERE} THEN quantidade ELSE 0 END),1) sai
            FROM movimentacoes GROUP BY ym ORDER BY ym
        """).fetchall()
        ]

    abc_cont = Counter(r["classe"] for r in obter_abc_valor() if r.get("classe"))
    abc_tot = sum(abc_cont.values()) or 1
    abc = {
        c: {"n": abc_cont.get(c, 0), "pct": round(abc_cont.get(c, 0) / abc_tot * 100, 1)}
        for c in ("A", "B", "C")
    }

    historico_mensal = {
        "meses": [h["ym"] for h in hist],
        "entradas": [h["ent"] for h in hist],
        "saidas": [h["sai"] for h in hist],
    }

    # ── YTD (v6.0.0, herdado do KPI Mensal) — ano corrente, 1º/jan até hoje ─────
    # Consumo = saída REAL por requisição (ajuste de inventário não entra), valorado
    # pelo preço de referência. Uma varredura alimenta os três indicadores + o donut.
    ano = hoje.year
    consumo_itens = _consumo_ytd_por_item(ano)
    ytd = {
        "ano": ano,
        "valor_consumido": _total_consumido(consumo_itens),
        "n_requisicoes": _n_requisicoes_ytd(ano),
        "itens_movimentados": len(consumo_itens),
        "composicao_tipo": _composicao_por_tipo(consumo_itens),
    }

    return {
        "kpis": {
            "itens_cadastrados": total,
            "entradas_hoje": entradas["hoje"]["n"],
            "requisicoes_hoje": req_hoje,
            "estoque_baixo": estoque_baixo,
            "compra_urgente": compra_urgente,
            "sem_giro": sem_giro,
            "valor_estoque": valor["total_brl"],
            "cobertura_media": cobertura_media,
        },
        "prioridades": {
            "comprar_agora": comprar_agora[:15],
            "abaixo_minimo": estoque_baixo,
            "cobertura_menor_lead": cob_menor_lead,
        },
        "distribuicao": dist,
        "cobertura_faixa": cob_faixa,
        "abc": abc,
        "ytd": ytd,
        "entradas": entradas,
        "saidas": saidas,
        "top_recebidos": top_recebidos,
        "mais_consumidos": mais_consumidos,
        "setores": setores,
        "historico_mensal": historico_mensal,
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
        rows = c.execute(
            f"""
            SELECT i.id, i.part_number, i.nome_item, i.tipo_material, i.unidade,
                   COALESCE(SUM(m.quantidade),0) AS qtd
            FROM movimentacoes m JOIN inventario i ON i.id = m.item_id
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', m.data_hora)=?
            GROUP BY i.id HAVING qtd > 0
        """,
            (str(ano),),
        ).fetchall()
        for r in rows:
            preco, _origem, _moeda = _preco_valoracao(c, r["id"])
            itens.append(
                {
                    "item_id": r["id"],
                    "part_number": r["part_number"],
                    "nome_item": r["nome_item"],
                    "tipo_material": r["tipo_material"] or "—",
                    "unidade": r["unidade"],
                    "qtd": round(float(r["qtd"]), 2),
                    "preco": preco,
                    "valor": round(float(r["qtd"]) * preco, 2),
                }
            )
    return itens


def _classificar_abc(itens_consumo):
    """Curva ABC (classe A/B/C por % acumulada do valor) sobre a lista de consumo YTD.
    Mesma convenção de `obter_abc_valor`. Devolve (lista ordenada desc, total)."""
    itens = sorted([dict(x) for x in itens_consumo if x["valor"] > 0], key=lambda x: x["valor"], reverse=True)
    total = sum(x["valor"] for x in itens)
    acc = 0.0
    for x in itens:
        prev = (acc / total * 100.0) if total else 0.0
        acc += x["valor"]
        x["pct_acumulado"] = round((acc / total * 100.0) if total else 0.0, 1)
        x["classe"] = "A" if prev < ABC_LIMIAR_A else ("B" if prev < ABC_LIMIAR_B else "C")
    return itens, round(total, 2)


def _total_consumido(itens_consumo):
    """Valor total (R$) consumido no ano — soma da lista de `_consumo_ytd_por_item`.

    É o indicador **Consumido no Ano** (YTD). Bate com o total do ABC porque
    `_classificar_abc` só descarta itens de valor 0, que somam 0. v6.0.0."""
    return round(sum(x["valor"] for x in itens_consumo), 2)


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
        rows = c.execute(
            f"""
            SELECT strftime('%Y-%m', m.data_hora) AS mes,
                   COALESCE(SUM(m.quantidade * COALESCE(i.preco_referencia,0)),0) AS valor,
                   COALESCE(SUM(m.quantidade),0) AS qtd
            FROM movimentacoes m JOIN inventario i ON i.id = m.item_id
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', m.data_hora)=?
            GROUP BY mes ORDER BY mes
        """,
            (str(ano),),
        ).fetchall()
    return [
        {"mes": r["mes"], "valor": round(float(r["valor"] or 0), 2), "qtd": round(float(r["qtd"] or 0), 2)}
        for r in rows
        if r["mes"]
    ]


def _scs_criadas_por_mes_ytd(ano, conn=None):
    """SCs criadas por mês no ano corrente (exclui canceladas)."""
    with transaction(conn) as c:
        rows = c.execute(
            """
            SELECT strftime('%Y-%m', data_abertura) AS mes, COUNT(*) AS n
            FROM solicitacoes_compra
            WHERE data_abertura IS NOT NULL AND status NOT IN ('Cancelado')
              AND strftime('%Y', data_abertura)=?
            GROUP BY mes ORDER BY mes
        """,
            (str(ano),),
        ).fetchall()
    return [{"mes": r["mes"], "criadas": r["n"]} for r in rows if r["mes"]]


def _n_requisicoes_ytd(ano, conn=None):
    """Nº de requisições distintas com consumo real no ano corrente."""
    with transaction(conn) as c:
        r = c.execute(
            f"""
            SELECT COUNT(DISTINCT requisicao_id) AS n FROM movimentacoes
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', data_hora)=?
        """,
            (str(ano),),
        ).fetchone()
    return r["n"] or 0


def _ranking_cc_ytd(ano, limit=10, conn=None):
    """Top centros de custo por valor consumido (R$) no ano corrente. Exclui os CCs
    genéricos/contábeis (99000/INVENTÁRIO/EDIÇÃO), que não indicam setor consumidor."""
    placeholders = ",".join("?" for _ in CC_GENERICOS)
    with transaction(conn) as c:
        rows = c.execute(
            f"""
            SELECT COALESCE(NULLIF(TRIM(m.centro_custo),''),'(sem CC)') AS rotulo,
                   COALESCE(SUM(m.quantidade * COALESCE(i.preco_referencia,0)),0) AS valor
            FROM movimentacoes m JOIN inventario i ON i.id = m.item_id
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', m.data_hora)=?
              AND TRIM(COALESCE(m.centro_custo,'')) NOT IN ({placeholders})
            GROUP BY rotulo HAVING valor > 0 ORDER BY valor DESC LIMIT ?
        """,
            (str(ano), *CC_GENERICOS, limit),
        ).fetchall()
    return [{"rotulo": r["rotulo"], "valor": round(float(r["valor"] or 0), 2)} for r in rows]


def _ranking_emitente_ytd(ano, limit=10, conn=None):
    """Top emitentes por nº de requisições reais no ano corrente."""
    with transaction(conn) as c:
        rows = c.execute(
            f"""
            SELECT COALESCE(NULLIF(TRIM(emitente),''),'(sem emitente)') AS rotulo,
                   COUNT(DISTINCT requisicao_id) AS n
            FROM movimentacoes
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', data_hora)=?
            GROUP BY rotulo ORDER BY n DESC LIMIT ?
        """,
            (str(ano), limit),
        ).fetchall()
    return [{"rotulo": r["rotulo"], "n": r["n"]} for r in rows]


def _ranking_setor_ytd(ano, limit=10, conn=None):
    """Top setores por nº de requisições reais no ano corrente."""
    with transaction(conn) as c:
        rows = c.execute(
            f"""
            SELECT COALESCE(NULLIF(TRIM(setor),''),'(sem setor)') AS rotulo,
                   COUNT(DISTINCT requisicao_id) AS n
            FROM movimentacoes
            WHERE {SAIDA_REAL_WHERE} AND strftime('%Y', data_hora)=?
            GROUP BY rotulo ORDER BY n DESC LIMIT ?
        """,
            (str(ano), limit),
        ).fetchall()
    return [{"rotulo": r["rotulo"], "n": r["n"]} for r in rows]


def _top_valor_imobilizado(limit=10, conn=None):
    """Top itens por capital PARADO em estoque (estoque_atual × preço de referência)."""
    with transaction(conn) as c:
        rows = c.execute(
            """
            SELECT part_number, nome_item,
                   estoque_atual * COALESCE(preco_referencia,0) AS valor
            FROM inventario
            WHERE COALESCE(preco_referencia,0) > 0 AND COALESCE(estoque_atual,0) > 0
            ORDER BY valor DESC LIMIT ?
        """,
            (limit,),
        ).fetchall()
    return [
        {
            "part_number": r["part_number"],
            "nome_item": r["nome_item"],
            "valor": round(float(r["valor"] or 0), 2),
        }
        for r in rows
    ]


def _top_dead_stock(ano, limit=10, conn=None):
    """Top itens SEM consumo real no ano corrente com maior valor parado — o 'dinheiro
    dormindo' (dead stock). História forte de melhoria p/ a apresentação."""
    with transaction(conn) as c:
        rows = c.execute(
            f"""
            SELECT i.part_number, i.nome_item,
                   i.estoque_atual * COALESCE(i.preco_referencia,0) AS valor
            FROM inventario i
            WHERE COALESCE(i.preco_referencia,0) > 0 AND COALESCE(i.estoque_atual,0) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM movimentacoes m
                  WHERE m.item_id = i.id AND {SAIDA_REAL_WHERE}
                    AND strftime('%Y', m.data_hora)=?)
            ORDER BY valor DESC LIMIT ?
        """,
            (str(ano), limit),
        ).fetchall()
    return [
        {
            "part_number": r["part_number"],
            "nome_item": r["nome_item"],
            "valor": round(float(r["valor"] or 0), 2),
        }
        for r in rows
    ]


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
        "abc": {
            "itens": abc[:12],
            "classes": dict(Counter(x["classe"] for x in abc)),
            "total": total_consumido,
        },
        "composicao_tipo": _composicao_por_tipo(consumo_itens),
        "rankings": {
            "top_valor_consumido": abc[:10],  # já ordenado por valor
            "top_qtd_consumida": sorted(consumo_itens, key=lambda x: x["qtd"], reverse=True)[:10],
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
    if publico == PUBLICO_EXECUTIVO:
        return montar_visao_executiva()
    return montar_visao_gestao()
