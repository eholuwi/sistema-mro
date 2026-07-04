"""Motor de Reposição (v2.5.0) — Assistente de Reposição.

Recomenda o quê / quando / quanto comprar, com justificativa, fornecedor sugerido
e prioridade. Princípio inegociável do PO: ASSISTENTE, NÃO PILOTO AUTOMÁTICO — o
sistema recomenda, o comprador decide e cria a SC. NUNCA sobrescreve a base do
Sr. Neidson (mín/máx/lead time/categoria); os cálculos são apoio à decisão,
rotulados por origem e maturidade (transparência).

As funções de cálculo são PURAS: recebem um `item` (dict de
`db_functions.listar_inventario`, que já traz estoque, guarda-chuva
(`estoque_em_transito`), cobertura (`dias_cobertura`), consumo, tendência e os
lead times) e devolvem números/rótulos — fáceis de testar e de explicar.
"""
from __future__ import annotations

import math
from datetime import datetime, date, timedelta

from collections import Counter

from database import transaction
from services.constants import (
    HORIZONTE_REPOSICAO_DIAS,
    ANTECEDENCIA_REPOSICAO_DIAS,
    LEAD_TIME_DEFAULT_DIAS,
    PREVISAO_RUPTURA_SEM_RISCO,
    REPOSICAO_DESFECHOS,
    SAIDA_REAL_WHERE,
    CATEGORIA_SC_PADRAO,
    CC_GENERICOS,
    CC_SUGERIDO_PADRAO,
)
from services.db_functions import (
    listar_inventario,
    obter_fornecedores_por_item,
)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _num(valor):
    """Converte para float de forma tolerante (None/erro → 0.0)."""
    try:
        return float(valor) if valor is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fmt_num(valor):
    """Número curto em PT-BR: inteiro quando redondo, senão 1 casa decimal."""
    v = _num(valor)
    s = f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"
    return s.replace(".", ",")


def _fmt_data(iso):
    """ISO 'YYYY-MM-DD' → 'DD/MM/YYYY' (devolve o original se não parsear)."""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return iso


def _disponivel(item):
    """Estoque disponível para cobrir a demanda = estoque atual + guarda-chuva
    (qtd já negociada que ainda falta chegar; `estoque_em_transito` do inventário)."""
    return _num(item.get("estoque_atual")) + _num(item.get("estoque_em_transito"))


def calcular_comprar_ate(cobertura_dias, lead_time, hoje=None):
    """Data-limite para emitir a SC e o material chegar antes de acabar (v2.8.0).

    Deriva da COBERTURA (dias), não do ROP (quantidade):
        Comprar até = hoje + (cobertura − lead_time − ANTECEDENCIA)
    A folga de ANTECEDENCIA (~15 d) honra a regra do Sr. Neidson de comprar com
    antecedência. Sem consumo (cobertura ≥ PREVISAO_RUPTURA_SEM_RISCO) → não há
    relógio de ruptura, logo sem data. Se o prazo já passou, a data é hoje (atrasado).

    Retorna (comprar_ate:str|None ISO 'YYYY-MM-DD', dias_para_comprar:int|None,
    atrasado:bool)."""
    cobertura = _num(cobertura_dias)
    if cobertura >= PREVISAO_RUPTURA_SEM_RISCO:
        return None, None, False
    hoje = hoje or date.today()
    dias = int(round(cobertura - _num(lead_time) - ANTECEDENCIA_REPOSICAO_DIAS))
    atrasado = dias <= 0
    comprar_ate = (hoje + timedelta(days=max(0, dias))).isoformat()
    return comprar_ate, dias, atrasado


# ══════════════════════════════════════════════════════════════════════════════
# PARÂMETROS EFETIVOS (não sobrescrevem a base — apenas escolhem o valor a usar)
# ══════════════════════════════════════════════════════════════════════════════

def lead_time_efetivo(item):
    """Lead time (dias) a usar no cálculo, com origem e rótulo de maturidade.

    Ordem de preferência (a base do Neidson tem prioridade e nunca é sobrescrita):
      1. `lead_time_dias` cadastrado (Neidson);
      2. `lead_time_calculado` (sugestão, do SC7/recebimentos);
      3. `LEAD_TIME_DEFAULT_DIAS` rotulado "lead time desconhecido".
    Retorna (dias:int, origem:str, maturidade:str|None)."""
    lt = _num(item.get("lead_time_dias"))
    if lt > 0:
        return int(round(lt)), "cadastrado (Neidson)", None
    ltc = _num(item.get("lead_time_calculado"))
    if ltc > 0:
        amostras = int(_num(item.get("lead_time_calculado_amostras")))
        origem = item.get("lead_time_calculado_origem") or "SC7"
        return int(round(ltc)), f"calculado ({origem}, {amostras} amostra(s))", "sugestão"
    return LEAD_TIME_DEFAULT_DIAS, f"default {LEAD_TIME_DEFAULT_DIAS}d", "lead time desconhecido"


def estoque_seguranca_efetivo(item):
    """Estoque de segurança a usar + origem. O manual (gestor) tem prioridade; se
    0, cai para o calculado (sugestão); se ambos 0, retorna (0, 'não definido').
    Retorna (valor:float, origem:str)."""
    ss = _num(item.get("estoque_seguranca"))
    if ss > 0:
        return ss, "manual (gestor)"
    ssc = _num(item.get("estoque_seguranca_calculado"))
    if ssc > 0:
        return ssc, "calculado (sugestão)"
    return 0.0, "não definido"


# ══════════════════════════════════════════════════════════════════════════════
# CÁLCULOS DE REPOSIÇÃO (puros)
# ══════════════════════════════════════════════════════════════════════════════

def calcular_ponto_reposicao(item):
    """Ponto de pedido (ROP) = consumo_diário × lead_time + estoque_segurança.

    Devolve o número e os componentes/origens (para a transparência da UI)."""
    consumo = _num(item.get("consumo_medio_diario"))
    lt, lt_org, lt_mat = lead_time_efetivo(item)
    ss, ss_org = estoque_seguranca_efetivo(item)
    return {
        "rop": round(consumo * lt + ss, 2),
        "consumo_diario": consumo,
        "lead_time": lt,
        "lead_time_origem": lt_org,
        "lead_time_maturidade": lt_mat,
        "estoque_seguranca": ss,
        "estoque_seguranca_origem": ss_org,
    }


def precisa_repor(item):
    """True quando o item deve entrar na fila de reposição.

    Gatilho de consumo (antecipa a SC ~15 dias além do ponto de pedido):
        (estoque + guarda-chuva) ≤ ROP + consumo_diário × ANTECEDENCIA
    Gatilho de piso do Neidson (protege a base mesmo sem consumo recente):
        estoque_atual ≤ estoque_minimo (quando há mínimo cadastrado)."""
    consumo = _num(item.get("consumo_medio_diario"))
    rop = calcular_ponto_reposicao(item)["rop"]
    gatilho = rop + consumo * ANTECEDENCIA_REPOSICAO_DIAS
    disponivel = _disponivel(item)
    minimo = _num(item.get("estoque_minimo"))
    piso_furado = minimo > 0 and _num(item.get("estoque_atual")) <= minimo
    return disponivel <= gatilho or piso_furado


def calcular_qtd_sugerida(item):
    """Quantidade sugerida (alvo HÍBRIDO — decisão do PO):
        alvo = max(estoque_maximo_Neidson, consumo_diário × HORIZONTE)
        qtd  = teto( max(alvo − estoque_atual − guarda_chuva, 0) )
    Nunca compra abaixo da base do Neidson E cobre o horizonte de ~2 meses.

    `estoque_maximo` já vem resolvido por `listar_inventario` (valor do Neidson
    quando > 0; senão o fallback histórico mínimo × fator)."""
    consumo = _num(item.get("consumo_medio_diario"))
    est_max = _num(item.get("estoque_maximo"))
    base_horizonte = consumo * HORIZONTE_REPOSICAO_DIAS
    alvo = max(est_max, base_horizonte)
    bruto = alvo - _num(item.get("estoque_atual")) - _num(item.get("estoque_em_transito"))
    qtd = int(math.ceil(bruto)) if bruto > 0 else 0
    return {
        "qtd": qtd,
        "alvo": round(alvo, 2),
        "alvo_neidson": round(est_max, 2),
        "alvo_horizonte": round(base_horizonte, 2),
        "alvo_origem": (
            "máx. Neidson" if est_max >= base_horizonte
            else f"horizonte {HORIZONTE_REPOSICAO_DIAS}d"
        ),
        "horizonte_dias": HORIZONTE_REPOSICAO_DIAS,
    }


def classificar_prioridade(item):
    """Urgência + rótulo. 'Parada de Linha' eleva o item dentro do mesmo tier.
      🔴 Crítico   — disponível ≤ ROP (já no/abaixo do ponto de pedido);
      🟠 Antecipar — ROP < disponível ≤ ROP + consumo × ANTECEDENCIA;
      🟡 Atenção   — demais (ex.: piso do Neidson furado, sem consumo)."""
    calc = calcular_ponto_reposicao(item)
    rop = calc["rop"]
    consumo = calc["consumo_diario"]
    disponivel = _disponivel(item)
    gatilho = rop + consumo * ANTECEDENCIA_REPOSICAO_DIAS
    if consumo <= 0:
        # Sem consumo não há "relógio" de ruptura: é atenção (piso do Neidson
        # furado), não urgência crítica. A criticidade (Parada de Linha) segue no
        # rótulo/KPI/filtro — o 🔴 fica reservado ao que vai romper por consumo.
        tier, rotulo = 2, "🟡 Atenção"
    elif disponivel <= rop:
        tier, rotulo = 0, "🔴 Crítico"
    elif disponivel <= gatilho:
        tier, rotulo = 1, "🟠 Antecipar"
    else:
        tier, rotulo = 2, "🟡 Atenção"
    parada = item.get("importancia") == "Parada de Linha"
    if parada:
        rotulo += " · Parada de Linha"
    return {"tier": tier, "rotulo": rotulo, "parada_linha": parada}


def montar_justificativa(item, calc=None, qtd=None, fornecedor=None):
    """Justificativa "mastigada" em 1 frase, a partir dos números do item."""
    calc = calc or calcular_ponto_reposicao(item)
    qtd = qtd or calcular_qtd_sugerida(item)
    unidade = item.get("unidade") or "UN"
    consumo = calc["consumo_diario"]
    cobertura = _num(item.get("dias_cobertura"))

    partes = []
    if consumo > 0 and cobertura < PREVISAO_RUPTURA_SEM_RISCO:
        partes.append(
            f"Cobertura {_fmt_num(cobertura)} d vs. lead time {calc['lead_time']} d "
            f"+ {ANTECEDENCIA_REPOSICAO_DIAS} d de antecedência"
        )
    else:
        partes.append("Estoque no/abaixo do mínimo do Neidson")

    if consumo > 0:
        cons_txt = f"consumo {_fmt_num(consumo)}/dia"
        tend = item.get("tendencia_label")
        if tend:
            tp = _num(item.get("tendencia_pct"))
            sinal = "+" if tp >= 0 else ""
            cons_txt += f" (tendência {tend} {sinal}{_fmt_num(tp)}%)"
        partes.append(cons_txt)

    gc = _num(item.get("estoque_em_transito"))
    if gc > 0:
        partes.append(f"guarda-chuva {_fmt_num(gc)} {unidade}")

    partes.append(
        f"sugerido {qtd['qtd']} {unidade} p/ alvo de {_fmt_num(qtd['alvo'])} "
        f"({qtd['alvo_origem']})"
    )
    if fornecedor and fornecedor.get("fornecedor"):
        partes.append(f"fornecedor sugerido: {fornecedor['fornecedor']}")
    return "; ".join(partes) + "."


# ══════════════════════════════════════════════════════════════════════════════
# GERAÇÃO DA FILA
# ══════════════════════════════════════════════════════════════════════════════

def melhor_fornecedor_item(item_id):
    """Melhor fornecedor do item (menor último preço) via v2.4.0, ou None."""
    fornecedores = obter_fornecedores_por_item(item_id)
    if not fornecedores:
        return None
    return next((f for f in fornecedores if f.get("melhor")), fornecedores[0])


def montar_sugestao(item, incluir_fornecedor=True):
    """Monta o dict completo de sugestão de UM item (cálculo + fornecedor +
    prioridade + justificativa). Não persiste."""
    calc = calcular_ponto_reposicao(item)
    qtd = calcular_qtd_sugerida(item)
    fornecedor = melhor_fornecedor_item(item["id"]) if incluir_fornecedor else None
    prioridade = classificar_prioridade(item)
    justificativa = montar_justificativa(item, calc, qtd, fornecedor)
    comprar_ate, dias_para_comprar, comprar_atrasado = calcular_comprar_ate(
        item.get("dias_cobertura"), calc["lead_time"]
    )
    forn = fornecedor or {}
    # v2.9.0 — exibição dupla: a qtd sugerida (unidade de ESTOQUE) também na unidade
    # de COMPRA do fornecedor, para o comprador pedir na unidade certa.
    #   qtd_compra = ceil(qtd_sugerida × fator).  fator=1 → sem diferença (no-op).
    fator = _num(item.get("fator_conversao")) or 1.0
    if fator <= 0:
        fator = 1.0
    unidade_compra = item.get("unidade_compra") or item.get("unidade") or "UN"
    qtd_sugerida_compra = int(math.ceil(qtd["qtd"] * fator)) if qtd["qtd"] > 0 else 0
    return {
        "item_id": item["id"],
        "part_number": item.get("part_number"),
        "nome_item": item.get("nome_item"),
        "descricao": item.get("descricao"),
        "unidade": item.get("unidade") or "UN",
        "unidade_compra": unidade_compra,
        "fator_conversao": fator,
        "qtd_sugerida_compra": qtd_sugerida_compra,
        "tipo_material": item.get("tipo_material"),
        "setor": item.get("setor_responsavel"),
        "importancia": item.get("importancia"),
        "sem_movimentacao": bool(item.get("sem_movimentacao")),
        "estoque_atual": _num(item.get("estoque_atual")),
        "estoque_minimo": _num(item.get("estoque_minimo")),
        "estoque_maximo": _num(item.get("estoque_maximo")),
        "guarda_chuva": _num(item.get("estoque_em_transito")),
        "cobertura_dias": _num(item.get("dias_cobertura")),
        "comprar_ate": comprar_ate,
        "dias_para_comprar": dias_para_comprar,
        "comprar_atrasado": comprar_atrasado,
        "consumo_diario": calc["consumo_diario"],
        "tendencia_label": item.get("tendencia_label"),
        "tendencia_pct": _num(item.get("tendencia_pct")),
        "rop": calc["rop"],
        "lead_time": calc["lead_time"],
        "lead_time_origem": calc["lead_time_origem"],
        "lead_time_maturidade": calc["lead_time_maturidade"],
        "estoque_seguranca": calc["estoque_seguranca"],
        "estoque_seguranca_origem": calc["estoque_seguranca_origem"],
        "alvo": qtd["alvo"],
        "alvo_neidson": qtd["alvo_neidson"],
        "alvo_horizonte": qtd["alvo_horizonte"],
        "alvo_origem": qtd["alvo_origem"],
        "horizonte_dias": qtd["horizonte_dias"],
        "qtd_sugerida": qtd["qtd"],
        "prioridade": prioridade["rotulo"],
        "prioridade_tier": prioridade["tier"],
        "parada_linha": prioridade["parada_linha"],
        "fornecedor_sugerido": forn.get("fornecedor"),
        "fornecedor_email": forn.get("email"),
        "fornecedor_ultimo_preco": forn.get("ultimo_preco"),
        "fornecedor_moeda": forn.get("moeda"),
        "fornecedor_lead_time": forn.get("lead_time_fornecedor"),
        "justificativa": justificativa,
    }


# ══════════════════════════════════════════════════════════════════════════════
# NATUREZA (categoria da SC) + CENTRO DE CUSTO — derivados do HISTÓRICO (v2.8.0)
# ══════════════════════════════════════════════════════════════════════════════

def _natureza_curta(natureza):
    """Remove o prefixo 'SOLICITAÇÃO DE COMPRA - ' para exibição curta."""
    if not natureza:
        return natureza
    for pref in ("SOLICITAÇÃO DE COMPRA - ", "SOLICITAÇÃO DE COMPRA – "):
        if natureza.startswith(pref):
            return natureza[len(pref):]
    return natureza


def mapear_categoria_sc_por_item(item_ids=None, conn=None):
    """{item_id: natureza da SC} derivado do HISTÓRICO real de SCs de cada item.

    Natureza = `solicitacoes_compra.descricao_solicitacao` (vocabulário do Protheus,
    ex.: 'SOLICITAÇÃO DE COMPRA - CONSUMÍVEIS PRODUÇÃO'). Para cada item, escolhe a
    natureza MAIS FREQUENTE entre suas SCs (desempate: a da SC mais recente). Itens
    sem histórico não entram no mapa — o chamador aplica CATEGORIA_SC_PADRAO."""
    with transaction(conn) as c:
        rows = c.execute("""
            SELECT isc.item_id AS item_id, s.descricao_solicitacao AS nat,
                   COALESCE(s.data_abertura, '') AS da
            FROM itens_sc isc
            JOIN solicitacoes_compra s ON s.id = isc.sc_id
            WHERE s.descricao_solicitacao IS NOT NULL
              AND TRIM(s.descricao_solicitacao) <> ''
        """).fetchall()
    filtro = set(item_ids) if item_ids is not None else None
    por_item = {}
    for r in rows:
        if filtro is not None and r["item_id"] not in filtro:
            continue
        por_item.setdefault(r["item_id"], []).append((r["nat"], r["da"]))
    mapa = {}
    for iid, lst in por_item.items():
        cont = Counter(nat for nat, _ in lst)
        top = max(cont.values())
        candidatas = {nat for nat, n in cont.items() if n == top}
        # desempate: natureza da SC mais recente entre as candidatas
        mapa[iid] = max((da, nat) for nat, da in lst if nat in candidatas)[1]
    return mapa


def mapear_cc_por_item(item_ids=None, conn=None):
    """{item_id: centro de custo} sugerido a partir do CONSUMO REAL de cada item.

    CC = o mais frequente nas saídas por requisição (SAIDA_REAL_WHERE), IGNORANDO os
    CCs genéricos/contábeis (CC_GENERICOS, ex.: '99000 - ATIVO PASSIVO RES. F'), que
    dominam por serem conta residual e não indicam o setor consumidor. Itens sem CC
    significativo não entram no mapa."""
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT item_id, centro_custo
            FROM movimentacoes
            WHERE {SAIDA_REAL_WHERE}
              AND centro_custo IS NOT NULL AND TRIM(centro_custo) <> ''
        """).fetchall()
    filtro = set(item_ids) if item_ids is not None else None
    por_item = {}
    for r in rows:
        cc = r["centro_custo"]
        if cc in CC_GENERICOS:
            continue
        if filtro is not None and r["item_id"] not in filtro:
            continue
        por_item.setdefault(r["item_id"], Counter())[cc] += 1
    return {iid: cont.most_common(1)[0][0] for iid, cont in por_item.items()}


def gerar_sugestoes_reposicao(incluir_fornecedor=True, incluir_sem_movimentacao=False):
    """Fila priorizada de reposições.

    Percorre o inventário (`listar_inventario`), filtra por `precisa_repor` e
    quantidade > 0, monta cada sugestão e ordena por urgência (tier) → criticidade
    (Parada de Linha) → menor cobertura → part number.

    v2.7.0: por padrão, exclui itens SEM MOVIMENTAÇÃO (nunca consumidos por
    requisição) para não poluir a fila. `incluir_sem_movimentacao=True` os traz de
    volta para revisão (ex.: spares "Parada de Linha" que o Neidson estoca sem
    giro) — marcados com `sem_movimentacao=True` na sugestão."""
    sugestoes = []
    for item in listar_inventario():
        if not incluir_sem_movimentacao and item.get("sem_movimentacao"):
            continue
        if not precisa_repor(item):
            continue
        if calcular_qtd_sugerida(item)["qtd"] <= 0:
            # Já coberto pelo estoque + guarda-chuva; nada a comprar agora.
            continue
        sugestoes.append(montar_sugestao(item, incluir_fornecedor=incluir_fornecedor))
    sugestoes.sort(key=lambda s: (
        s["prioridade_tier"],
        0 if s["parada_linha"] else 1,
        s["cobertura_dias"],
        s["part_number"] or "",
    ))
    # v2.8.0: enriquece com a natureza da SC (do histórico) e o CC sugerido (do
    # consumo real) — base das "SCs de mão beijada" agrupadas por natureza.
    if sugestoes:
        ids = [s["item_id"] for s in sugestoes]
        categorias = mapear_categoria_sc_por_item(ids)
        ccs = mapear_cc_por_item(ids)
        for s in sugestoes:
            s["categoria_sc"] = categorias.get(s["item_id"]) or CATEGORIA_SC_PADRAO
            s["cc_sugerido"] = ccs.get(s["item_id"])   # None = sem CC significativo
    return sugestoes


def agrupar_por_fornecedor(sugestoes):
    """Agrupa as sugestões pelo fornecedor sugerido (para reduzir o nº de SCs).
    Fornecedor None vira o grupo 'Sem fornecedor sugerido'. Grupos ordenados por
    prioridade do item mais urgente."""
    grupos = {}
    for s in sugestoes:
        chave = s.get("fornecedor_sugerido") or "Sem fornecedor sugerido"
        grupos.setdefault(chave, []).append(s)
    return dict(sorted(
        grupos.items(),
        key=lambda kv: min(x["prioridade_tier"] for x in kv[1]),
    ))


def agrupar_por_natureza(sugestoes):
    """Agrupa as sugestões pela NATUREZA da SC (`categoria_sc`, derivada do histórico)
    — base das "SCs de mão beijada" (v2.8.0). Junta itens que a operação historicamente
    comprou sob a mesma natureza (vocabulário real do Protheus, ex.: 'CONSUMÍVEIS
    PRODUÇÃO'), reduzindo o nº de SCs a aprovar. Itens sem histórico caem em
    CATEGORIA_SC_PADRAO. Grupos ordenados pela prioridade do item mais urgente."""
    grupos = {}
    for s in sugestoes:
        chave = s.get("categoria_sc") or CATEGORIA_SC_PADRAO
        grupos.setdefault(chave, []).append(s)
    return dict(sorted(
        grupos.items(),
        key=lambda kv: min(x["prioridade_tier"] for x in kv[1]),
    ))


def _cc_sugerido_grupo(sugs):
    """CC sugerido do grupo = o CC significativo mais comum entre os itens (do consumo
    real, já sem os genéricos). CC_SUGERIDO_PADRAO quando nenhum item tem CC."""
    cont = Counter(s["cc_sugerido"] for s in sugs if s.get("cc_sugerido"))
    return cont.most_common(1)[0][0] if cont else CC_SUGERIDO_PADRAO


def resumir_grupo_sc(label, sugs):
    """Título + justificativa + CC + agregados de um grupo (natureza) de sugestões (v2.8.0).

    Determinístico e transparente (sem NLP): o comprador edita tudo antes de criar a SC.
    Título = a própria natureza (vocabulário real das SCs). Justificativa responde
    'por quê' agrupar (natureza), volume/consumo, prioridade, data-limite e o CC sugerido."""
    if not sugs:
        return {
            "label": label, "titulo": label, "justificativa": "", "n_itens": 0,
            "qtd_total": 0, "valor_estimado": 0.0, "comprar_ate_min": None,
            "cc_sugerido": CC_SUGERIDO_PADRAO, "prioridade_tier": 2,
            "prioridade": "—", "itens": [],
        }
    n = len(sugs)
    natureza_curta = _natureza_curta(label)
    n_criticos = sum(1 for s in sugs if s.get("prioridade_tier") == 0)
    tier_min = min(s.get("prioridade_tier", 2) for s in sugs)
    prio_max = next(
        (s["prioridade"] for s in sugs if s.get("prioridade_tier") == tier_min), "—"
    )
    soma_consumo = sum(_num(s.get("consumo_diario")) for s in sugs)
    qtd_total = sum(int(_num(s.get("qtd_sugerida"))) for s in sugs)
    valor_estimado = sum(
        _num(s.get("qtd_sugerida")) * _num(s.get("fornecedor_ultimo_preco"))
        for s in sugs if s.get("fornecedor_ultimo_preco")
    )
    cc_sugerido = _cc_sugerido_grupo(sugs)
    # menor "comprar até" do grupo (item mais urgente); ignora None (sem consumo).
    com_data = [s for s in sugs if s.get("comprar_ate")]
    if com_data:
        mais_urgente = min(com_data, key=lambda s: s["comprar_ate"])
        comprar_ate_min = mais_urgente["comprar_ate"]
        pn_urgente = mais_urgente.get("part_number")
    else:
        comprar_ate_min, pn_urgente = None, None

    unid = "item" if n == 1 else "itens"
    linhas = [
        f"Agrupa {n} {unid} da natureza {natureza_curta}.",
        f"{n_criticos} crítico(s); prioridade máxima: {prio_max}; "
        f"consumo agregado ~{_fmt_num(soma_consumo)} un/dia.",
    ]
    if comprar_ate_min:
        linhas.append(f"Comprar até {_fmt_data(comprar_ate_min)} (mais urgente: {pn_urgente}).")
    linhas.append(f"Centro de custo sugerido: {cc_sugerido}.")
    return {
        "label": label,
        "titulo": label,                       # a natureza É o título
        "justificativa": " ".join(linhas),
        "n_itens": n,
        "qtd_total": qtd_total,
        "valor_estimado": round(valor_estimado, 2),
        "comprar_ate_min": comprar_ate_min,
        "cc_sugerido": cc_sugerido,
        "prioridade_tier": tier_min,
        "prioridade": prio_max,
        "itens": sugs,
    }


def gerar_scs_sugeridas(incluir_fornecedor=True, incluir_sem_movimentacao=False):
    """SCs sugeridas prontas (agrupadas por natureza, com título/justificativa/CC) — v2.8.0.
    Encadeia gerar_sugestoes_reposicao → agrupar_por_natureza → resumir_grupo_sc.
    Lista já ordenada pela prioridade do grupo mais urgente."""
    sugestoes = gerar_sugestoes_reposicao(
        incluir_fornecedor=incluir_fornecedor,
        incluir_sem_movimentacao=incluir_sem_movimentacao,
    )
    grupos = agrupar_por_natureza(sugestoes)
    return [resumir_grupo_sc(label, sugs) for label, sugs in grupos.items()]


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTÊNCIA / AUDITORIA (desfecho da decisão do comprador)
# ══════════════════════════════════════════════════════════════════════════════

def registrar_desfecho_sugestao(sugestao, desfecho, sc_id=None, observacao=None, conn=None):
    """Grava a FOTO do cálculo + o desfecho (gerada|criou_sc|adiada|ignorada) em
    `sugestoes_reposicao`. É o registro de auditoria da decisão do comprador; não
    altera a base do Neidson. Retorna o id inserido."""
    if desfecho not in REPOSICAO_DESFECHOS:
        raise ValueError(f"Desfecho inválido: {desfecho!r} (válidos: {REPOSICAO_DESFECHOS})")
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction(conn) as c:
        cur = c.execute("""
            INSERT INTO sugestoes_reposicao
                (item_id, data_geracao, cobertura_dias, rop, alvo, horizonte_dias,
                 qtd_sugerida, fornecedor_sugerido, prioridade, justificativa,
                 desfecho, sc_id, data_desfecho, observacao)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            sugestao["item_id"], agora, sugestao.get("cobertura_dias"),
            sugestao.get("rop"), sugestao.get("alvo"), sugestao.get("horizonte_dias"),
            sugestao.get("qtd_sugerida"), sugestao.get("fornecedor_sugerido"),
            sugestao.get("prioridade"), sugestao.get("justificativa"),
            desfecho, sc_id, (None if desfecho == "gerada" else agora), observacao,
        ))
        return cur.lastrowid


def listar_sugestoes(desfecho=None, item_id=None, limit=200, conn=None):
    """Histórico de desfechos de reposição (auditoria)."""
    clausulas, params = [], []
    if desfecho:
        clausulas.append("s.desfecho = ?")
        params.append(desfecho)
    if item_id:
        clausulas.append("s.item_id = ?")
        params.append(item_id)
    where = ("WHERE " + " AND ".join(clausulas)) if clausulas else ""
    params.append(limit)
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT s.*, i.part_number, i.nome_item
            FROM sugestoes_reposicao s
            JOIN inventario i ON i.id = s.item_id
            {where}
            ORDER BY s.data_geracao DESC, s.id DESC
            LIMIT ?
        """, params).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# PONTE PARA "CRIAR SC" (reaproveita criar_sc — não duplica o fluxo Nova SC)
# ══════════════════════════════════════════════════════════════════════════════

def buscar_sc_id_por_numero(numero_sc, conn=None):
    """id da SC a partir do número (para amarrar o desfecho 'criou_sc' à SC)."""
    with transaction(conn) as c:
        r = c.execute(
            "SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)
        ).fetchone()
    return r["id"] if r else None


def sugestao_para_item_sc(sugestao, data_necessidade=None):
    """Converte uma sugestão no dict de item aceito por `criar_sc()`.

    A quantidade sugerida vira a quantidade solicitada; a justificativa vira a
    observação do item; o fornecedor sugerido preenche `fornecedor_item`."""
    return {
        "item_id": sugestao["item_id"],
        "part_number": sugestao.get("part_number"),
        "nome_item": sugestao.get("nome_item"),
        "quantidade_solicitada": sugestao["qtd_sugerida"],
        "quantidade_pedido": sugestao["qtd_sugerida"],
        "numero_po": "",
        "data_necessidade": data_necessidade,
        "data_prev_nfe": None,
        "fornecedor_item": sugestao.get("fornecedor_sugerido") or "",
        "observacao_item": sugestao.get("justificativa"),
    }
