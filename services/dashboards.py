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
    AGING_ALERTA_DIAS, AGING_CRITICO_DIAS, PREVISAO_RUPTURA_SEM_RISCO,
)
from services.db_functions import (
    calcular_giro, listar_inventario, listar_scs, obter_abc_valor,
    obter_evolucao_valor_imobilizado, obter_valor_imobilizado, transaction,
)
from services.planejamento import gerar_scs_sugeridas, gerar_sugestoes_reposicao

# Rótulos dos públicos — fonte única de verdade (app.py e manual de Ajuda consomem).
PUBLICO_COMPRADOR = "Comprador"
PUBLICO_GESTAO = "Gestão"
PUBLICO_DIRETORIA = "Diretoria"
PUBLICOS = [PUBLICO_COMPRADOR, PUBLICO_GESTAO, PUBLICO_DIRETORIA]


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


def montar_dashboard(publico):
    """Roteador: devolve o view-model do público pedido (default = Gestão)."""
    if publico == PUBLICO_COMPRADOR:
        return montar_visao_comprador()
    if publico == PUBLICO_DIRETORIA:
        return montar_visao_diretoria()
    return montar_visao_gestao()
