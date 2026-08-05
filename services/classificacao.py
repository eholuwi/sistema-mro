"""Classificação de Demanda, XYZ & Sazonalidade (v2.10.0 — Pilar Inteligência).

Lê COMO cada item se comporta na demanda a partir das SAÍDAS REAIS (por requisição —
`SAIDA_REAL_WHERE`, a mesma fonte de consumo da v2.7.0; ajustes/inventário NÃO contam).
Tudo é DERIVADO NA LEITURA (sem coluna/tabela nova), no mesmo espírito da Curva ABC
(`obter_abc_valor`) — e é apenas DIAGNÓSTICO: nada aqui altera a base do Sr. Neidson
nem o cálculo de reposição (isso é decisão futura, com a base já validada).

Dois eixos (Syntetos-Boylan, SBC):
  • ADI  — regularidade do TEMPO entre demandas (nº de períodos ÷ períodos com demanda).
  • CV²  — variabilidade do TAMANHO da demanda ((desvio/média das qtds por período)²).
Com ~3 meses de histórico, o período do SBC é a SEMANA (mês daria só 3 pontos). O XYZ
usa o consumo MENSAL e a Sazonalidade só é liberada com ≥12 meses (1 ciclo anual) —
até lá a UI mostra o rótulo de maturidade, sem inventar perfil.

v6.4.0 acrescenta um TERCEIRO jeito de ler o consumo, ao lado do mensal por
mês-calendário e do ponderado: a **vida útil do lote** (`_vida_util_from_movimentos`) —
quanto tempo cada recebimento durou até o estoque bater o mínimo. É a leitura que o
almoxarifado faz no papel, e a única que responde "quanto dura uma compra deste item".

As funções `_*_from_*` são PURAS (operam sobre listas de eventos/valores) para permitir
testes determinísticos sem banco; as funções públicas apenas leem o banco e delegam.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from database import transaction
from services.constants import (
    SAIDA_REAL_WHERE,
    SBC_ADI_LIMIAR,
    SBC_CV2_LIMIAR,
    XYZ_LIMIAR_X,
    XYZ_LIMIAR_Y,
    XYZ_MIN_MESES_CONFIAVEL,
    SAZONALIDADE_MIN_MESES,
    PADROES_DEMANDA,
    PADRAO_DEMANDA_SEM_DADOS,
    PADRAO_DEMANDA_POUCOS,
)


# ══════════════════════════════════════════════════════════════════════════════
# NÚCLEO PURO — matemática SBC/XYZ sobre listas (sem banco; testável isoladamente)
# ══════════════════════════════════════════════════════════════════════════════


def _std_pop(valores):
    """Desvio-padrão populacional (÷n). Média 0 ou lista vazia → 0.0."""
    n = len(valores)
    if n == 0:
        return 0.0
    media = sum(valores) / n
    var = sum((v - media) ** 2 for v in valores) / n
    return var**0.5


def _confianca_por_eventos(n):
    """Rótulo de confiança do padrão de demanda pelo nº de semanas com demanda."""
    if n >= 8:
        return "média"
    if n >= 4:
        return "baixa"
    return "muito baixa"


def _demanda_from_eventos(eventos):
    """SBC a partir de `eventos` = lista de (datetime, quantidade>0).

    Agrupa em semanas de 7 dias contadas a partir da 1ª demanda; ADI = nº de semanas
    do intervalo ÷ semanas com demanda; CV² = (desvio/média das qtds semanais)².
    Retorna dict uniforme (padrao/emoji/explicacao/adi/cv2/n_eventos/n_semanas/confianca).
    """
    base = dict(
        padrao=PADRAO_DEMANDA_SEM_DADOS["label"],
        emoji=PADRAO_DEMANDA_SEM_DADOS["emoji"],
        explicacao=PADRAO_DEMANDA_SEM_DADOS["explicacao"],
        adi=None,
        cv2=None,
        n_eventos=0,
        n_semanas=0,
        confianca="sem_dados",
    )
    if not eventos:
        return base

    eventos = sorted(eventos, key=lambda e: e[0])
    inicio = eventos[0][0]
    baldes = defaultdict(float)  # índice_semana -> qtd somada
    for dt, qtd in eventos:
        semana = (dt - inicio).days // 7
        baldes[semana] += float(qtd)

    tamanhos = [q for q in baldes.values() if q > 0]
    n_eventos = len(tamanhos)  # semanas COM demanda
    n_semanas = max(baldes.keys()) + 1  # semanas no intervalo (inclusive)

    if n_eventos <= 1:
        # 0 ou 1 ocorrência: não dá para medir variabilidade nem intervalo.
        rot = PADRAO_DEMANDA_SEM_DADOS if n_eventos == 0 else PADRAO_DEMANDA_POUCOS
        base.update(
            padrao=rot["label"],
            emoji=rot["emoji"],
            explicacao=rot["explicacao"],
            n_eventos=n_eventos,
            n_semanas=n_semanas,
            confianca=("sem_dados" if n_eventos == 0 else "muito baixa"),
        )
        return base

    adi = n_semanas / n_eventos
    media = sum(tamanhos) / n_eventos
    cv2 = (_std_pop(tamanhos) / media) ** 2 if media > 0 else 0.0
    info = PADROES_DEMANDA[(adi >= SBC_ADI_LIMIAR, cv2 >= SBC_CV2_LIMIAR)]
    return dict(
        padrao=info["label"],
        emoji=info["emoji"],
        explicacao=info["explicacao"],
        adi=round(adi, 2),
        cv2=round(cv2, 2),
        n_eventos=n_eventos,
        n_semanas=n_semanas,
        confianca=_confianca_por_eventos(n_eventos),
    )


def _xyz_from_meses(valores_mensais):
    """XYZ a partir dos valores de consumo por mês (lista de qtds mensais > 0).

    CV = desvio populacional ÷ média. Precisa de ≥2 meses para medir variabilidade;
    com 1 mês devolve classe None (insuficiente). Retorna classe/cv/n_meses/confianca.
    """
    valores = [float(v) for v in valores_mensais if v is not None]
    n = len(valores)
    if n == 0:
        return {"classe": None, "cv": None, "n_meses": 0, "confianca": "sem_dados"}
    media = sum(valores) / n
    if n < 2 or media <= 0:
        return {"classe": None, "cv": None, "n_meses": n, "confianca": "insuficiente"}
    cv = _std_pop(valores) / media
    classe = "X" if cv <= XYZ_LIMIAR_X else ("Y" if cv <= XYZ_LIMIAR_Y else "Z")
    confianca = "média" if n >= XYZ_MIN_MESES_CONFIAVEL else "baixa"
    return {"classe": classe, "cv": round(cv, 2), "n_meses": n, "confianca": confianca}


def _meses_from_eventos(eventos):
    """Agrega `eventos` (datetime, qtd) por mês-calendário → [{mes:'YYYY-MM', qtd}]."""
    por_mes = defaultdict(float)
    for dt, qtd in eventos:
        por_mes[dt.strftime("%Y-%m")] += float(qtd)
    return [{"mes": m, "qtd": round(q, 2)} for m, q in sorted(por_mes.items()) if q > 0]


def _ultimos_n_meses_completos(hoje, n=3):
    """Rótulos 'YYYY-MM' dos `n` meses-calendário COMPLETOS mais recentes (exclui o mês
    corrente, ainda em andamento), do mais antigo ao mais recente."""
    meses, ano, mes = [], hoje.year, hoje.month
    for _ in range(n):
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
        meses.append(f"{ano:04d}-{mes:02d}")
    return list(reversed(meses))  # antigo -> recente


def _ponderado_from_serie(serie, hoje, n=3, pesos=None):
    """Consumo mensal PONDERADA dos últimos `n` meses completos (o mais recente pesa mais).

    `serie` = [{mes:'YYYY-MM', qtd}] das saídas reais (meses sem saída podem estar
    AUSENTES → contam 0). Ancorada em `hoje` e excluindo o mês corrente, então
    "atualiza conforme os meses passam" e decai para 0 quando o item deixa de sair.
    Pesos default = 1..n (antigo→recente), i.e. 3 meses → 3/2/1 no recente→antigo.
    Retorna float (un/mês) arredondado, ou None se NENHUM dos meses-alvo teve saída
    (item sem consumo recente = 'sem dados', para a UI mostrar '—')."""
    qtd_por_mes = {x["mes"]: float(x["qtd"]) for x in (serie or [])}
    alvo = _ultimos_n_meses_completos(hoje, n)  # antigo -> recente
    valores = [qtd_por_mes.get(mes, 0.0) for mes in alvo]
    if not any(v > 0 for v in valores):
        return None
    pesos = pesos or list(range(1, n + 1))  # [1..n] antigo->recente
    return round(sum(v * p for v, p in zip(valores, pesos)) / sum(pesos), 2)


def _vida_util_from_movimentos(movimentos, minimo):
    """Consumo mensal medido pela VIDA ÚTIL de cada lote recebido (v6.4.0).

    `movimentos` = lista de `(datetime, tipo, quantidade, saldo_apos|None, abre_lote)` em
    ordem cronológica — o ledger INTEIRO do item, não só as saídas: entrada e devolução
    também mexem no saldo, e é o saldo que diz quando o lote acabou.

    Regra travada pelo Luis em 05/08/2026: cada recebimento abre um lote, que dura da data
    em que chegou até o instante em que o estoque **bate o mínimo cadastrado** — e não até
    zerar. `consumo_mensal = qtd recebida ÷ dias de duração × 30`; o número do item é a
    **média simples** dos lotes fechados (escolha do Luis entre média, mediana e ponderada).

    Quatro decisões que a fórmula não cobre e o ledger obriga a tomar:

    - **Saldo corrente**: usa `saldo_apos` quando gravado; sem ele, acumula ± quantidade.
      O `mro.db` real não tem nulos, mas movimentação inserida direto no banco (fixtures,
      importação antiga) pode não ter a coluna — cair para o acumulado mantém a conta viva
      em vez de devolver um número errado em silêncio.
    - **`minimo <= 0` → o piso vira 0**, i.e. o lote dura até zerar (fallback pedido no
      backlog para os itens sem mínimo cadastrado).
    - **Lote que nasce já no piso não conta.** Recebimento que não levanta o estoque acima
      do mínimo não tem vida útil a medir: ele "bate o mínimo" na própria chegada, e
      contá-lo produziria "durou 1 dia" — 30× a quantidade recebida — justamente nos itens
      cronicamente em falta, que são os que mais aparecem na fila de reposição.
    - **Lote ainda vivo não conta** (sem data de fim; não se inventa "hoje" como fim), e
      lote de menos de 1 dia é descartado — mesmo filtro que `_gravar_lead_time_calculado`
      aplica ao lead time, e o que evita a divisão por zero.

    Lotes podem se sobrepor: dois recebimentos antes de o saldo cair fecham no mesmo
    instante, cada um com a duração contada da SUA chegada.
    """
    piso = max(float(minimo or 0), 0.0)
    abertos = []  # [(datetime da chegada, qtd recebida)] — lotes sem fim ainda
    fechados = []
    saldo = 0.0

    for dt, tipo, qtd, saldo_apos, abre_lote in sorted(movimentos, key=lambda m: m[0]):
        q = float(qtd or 0)
        if saldo_apos is not None:
            saldo = float(saldo_apos)
        elif tipo in ("entrada", "devolucao"):
            saldo += q
        else:
            saldo -= q

        if abre_lote and q > 0:
            # A entrada acabou de subir o saldo: ela nunca fecha lote, só abre — e só
            # quando de fato tirou o estoque de cima do mínimo (ver docstring).
            if saldo > piso:
                abertos.append((dt, q))
            continue

        if saldo <= piso and abertos:
            for inicio, qtd_lote in abertos:
                dias = (dt - inicio).days
                if dias >= 1:
                    fechados.append(
                        {
                            "inicio": inicio,
                            "fim": dt,
                            "dias": dias,
                            "quantidade": round(qtd_lote, 2),
                            "consumo_mensal": round(qtd_lote / dias * 30, 2),
                        }
                    )
            abertos = []

    if not fechados:
        return {
            "consumo_mensal": None,
            "n_lotes": 0,
            "n_lotes_vivos": len(abertos),
            "dias_medio": None,
            "lotes": [],
        }
    return {
        "consumo_mensal": round(sum(x["consumo_mensal"] for x in fechados) / len(fechados), 2),
        "n_lotes": len(fechados),
        "n_lotes_vivos": len(abertos),
        "dias_medio": round(sum(x["dias"] for x in fechados) / len(fechados), 1),
        "lotes": fechados,
    }


# ══════════════════════════════════════════════════════════════════════════════
# LEITURA DO BANCO — busca as saídas reais e delega ao núcleo puro
# ══════════════════════════════════════════════════════════════════════════════


def _parse_dt(s):
    """'YYYY-MM-DD HH:MM:SS' → datetime (tolerante; None se não parsear)."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s))
    except ValueError:
        try:
            return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def _eventos_item(c, item_id):
    """Lista de (datetime, quantidade>0) das saídas reais do item, em ordem."""
    rows = c.execute(
        f"""SELECT data_hora, quantidade FROM movimentacoes
            WHERE item_id=? AND {SAIDA_REAL_WHERE}
            ORDER BY data_hora""",
        (item_id,),
    ).fetchall()
    out = []
    for r in rows:
        dt = _parse_dt(r["data_hora"])
        q = float(r["quantidade"] or 0)
        if dt is not None and q > 0:
            out.append((dt, q))
    return out


def _movimentos_item(c, item_id):
    """Ledger COMPLETO do item → `[(datetime, tipo, quantidade, saldo_apos|None, abre_lote)]`.

    Irmã de `_eventos_item`, que lê só as saídas reais: aqui entram entrada e devolução
    também, porque a vida útil do lote é medida pelo SALDO, e o saldo se move nos três
    tipos. `abre_lote` marca o que conta como **recebimento** — entrada com `sc_item_id`
    preenchido, o mesmo predicado de `ENTRADA_REAL_WHERE`. Decisão do Luis em 05/08/2026:
    ajuste de inventário e entrada avulsa mexem no saldo mas NÃO abrem lote (só material
    que chegou por uma SC tem "data em que chegou").

    `ORDER BY data_hora, id` — o desempate por id importa: recebimento e baixa no mesmo
    segundo trocariam de ordem conforme o plano de consulta, e a ordem decide se o lote
    abriu antes ou depois da saída que o fecharia.
    """
    rows = c.execute(
        """SELECT data_hora, tipo, quantidade, saldo_apos, sc_item_id
           FROM movimentacoes WHERE item_id=?
           ORDER BY data_hora, id""",
        (item_id,),
    ).fetchall()
    out = []
    for r in rows:
        dt = _parse_dt(r["data_hora"])
        if dt is None:
            continue
        saldo_apos = None if r["saldo_apos"] is None else float(r["saldo_apos"])
        abre_lote = r["tipo"] == "entrada" and r["sc_item_id"] is not None
        out.append((dt, r["tipo"], float(r["quantidade"] or 0), saldo_apos, abre_lote))
    return out


def consumo_por_vida_util(item_id, conn=None):
    """Consumo mensal do item pela vida útil dos lotes recebidos. Ver
    `_vida_util_from_movimentos` — aqui só se busca o mínimo cadastrado e o ledger."""
    with transaction(conn) as c:
        row = c.execute("SELECT estoque_minimo FROM inventario WHERE id=?", (item_id,)).fetchone()
        minimo = float(row["estoque_minimo"] or 0) if row else 0.0
        movimentos = _movimentos_item(c, item_id)
    return _vida_util_from_movimentos(movimentos, minimo)


def consumo_mensal(item_id, conn=None):
    """Agregado mensal do consumo real → [{mes:'YYYY-MM', qtd}]. Fundação reutilizável
    (XYZ, gráfico da Ficha e — no futuro — sazonalidade)."""
    with transaction(conn) as c:
        return _meses_from_eventos(_eventos_item(c, item_id))


def consumo_mensal_ponderado(item_id, conn=None, hoje=None):
    """Consumo mensal ponderado (3 meses, peso 3/2/1 no recente→antigo) do item.
    Ver `_ponderado_from_serie`. Retorna float (un/mês) ou None (sem consumo recente)."""
    hoje = hoje or date.today()
    return _ponderado_from_serie(consumo_mensal(item_id, conn), hoje)


def classificar_demanda(item_id, conn=None):
    """Padrão de demanda (SBC) do item. Ver `_demanda_from_eventos`."""
    with transaction(conn) as c:
        return _demanda_from_eventos(_eventos_item(c, item_id))


def classificar_xyz(item_id, conn=None):
    """Classe XYZ do item (variabilidade do consumo mensal). Ver `_xyz_from_meses`."""
    serie = consumo_mensal(item_id, conn)
    return _xyz_from_meses([x["qtd"] for x in serie])


def _sazonalidade_from_serie(serie):
    """Perfil sazonal (média por mês-do-ano) a partir de uma série mensal já lida.
    LIBERADO só com ≥12 meses (1 ciclo anual); abaixo disso `disponivel=False` +
    progresso, para a UI mostrar 'amadurecendo (N/12)' sem forjar um perfil."""
    n = len(serie)
    base = {"disponivel": False, "meses_atuais": n, "meses_necessarios": SAZONALIDADE_MIN_MESES, "perfil": []}
    if n < SAZONALIDADE_MIN_MESES:
        return base
    por_mes_ano = defaultdict(list)
    for x in serie:
        por_mes_ano[x["mes"].split("-")[1]].append(x["qtd"])  # '01'..'12'
    perfil = [{"mes": mm, "media": round(sum(v) / len(v), 2)} for mm, v in sorted(por_mes_ano.items())]
    return {**base, "disponivel": True, "perfil": perfil}


def perfil_sazonal(item_id, conn=None):
    """Perfil sazonal do item — ver `_sazonalidade_from_serie` (gate de ≥12 meses)."""
    return _sazonalidade_from_serie(consumo_mensal(item_id, conn))


def classificar_item(item_id, conn=None):
    """Reúne demanda + XYZ + consumo mensal + sazonalidade + vida útil do lote (Ficha 360).

    v6.4.0 — `vida_util` entra por aqui, e não por uma consulta nova em `services/ficha.py`,
    porque a Ficha já recebe este dict inteiro (`ficha["classificacao"]`). Fica de fora de
    `classificar_todos` de propósito: aquela função roda para a base inteira dentro de
    `listar_inventario`, e varrer o ledger completo de 362 itens a cada listagem é
    exatamente o N+1 que ela existe para evitar."""
    with transaction(conn) as c:
        eventos = _eventos_item(c, item_id)
        vida_util = consumo_por_vida_util(item_id, c)
    serie = _meses_from_eventos(eventos)
    return {
        "demanda": _demanda_from_eventos(eventos),
        "xyz": _xyz_from_meses([x["qtd"] for x in serie]),
        "consumo_mensal": serie,
        "consumo_mensal_ponderado": _ponderado_from_serie(serie, date.today()),
        "sazonalidade": _sazonalidade_from_serie(serie),
        "vida_util": vida_util,
    }


def classificar_todos(conn=None):
    """Classifica TODOS os itens numa ÚNICA varredura de `movimentacoes` (evita N+1 no
    Inventário). Retorna {item_id: {padrao_demanda, padrao_emoji, demanda_confianca,
    classe_xyz, xyz_confianca}} — campos compactos para o merge em `listar_inventario`.
    Itens sem saída real não aparecem no mapa (o chamador trata como 'sem dados')."""
    with transaction(conn) as c:
        rows = c.execute(
            f"""SELECT item_id, data_hora, quantidade FROM movimentacoes
                WHERE {SAIDA_REAL_WHERE}
                ORDER BY item_id, data_hora""",
        ).fetchall()

    por_item = defaultdict(list)
    for r in rows:
        dt = _parse_dt(r["data_hora"])
        q = float(r["quantidade"] or 0)
        if dt is not None and q > 0:
            por_item[r["item_id"]].append((dt, q))

    mapa = {}
    for item_id, eventos in por_item.items():
        dem = _demanda_from_eventos(eventos)
        xyz = _xyz_from_meses([x["qtd"] for x in _meses_from_eventos(eventos)])
        mapa[item_id] = {
            "padrao_demanda": dem["padrao"] if dem["confianca"] != "sem_dados" else None,
            "padrao_emoji": dem["emoji"],
            "demanda_confianca": dem["confianca"],
            "classe_xyz": xyz["classe"],
            "xyz_confianca": xyz["confianca"],
        }
    return mapa
