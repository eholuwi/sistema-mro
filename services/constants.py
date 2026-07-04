"""Constantes de dominio centralizadas (Fase 4.1 / F4-08 parcial).

Apenas da nome unico a valores numericos que estavam hardcoded no codigo.
NAO altera logica, enums, schema nem CHECK constraints -- os valores sao
identicos aos que ja existiam; somente foram extraidos para um unico lugar."""

# --- Status de estoque ---
MARGEM_ATENCAO = 1.2           # limite da zona ATENCAO = estoque_minimo * 1.2
FATOR_ESTOQUE_MAXIMO = 2       # estoque_maximo = estoque_minimo * 2
FATOR_ESTOQUE_SEGURANCA = 1.5  # estoque_seguranca = consumo * lead_time * 1.5

# --- Consumo real / "Sem Movimentação" (v2.7.0) ---
# "Consumo real" = saída por REQUISIÇÃO (requisicao_id preenchido). Exclui os
# ajustes/saldo inicial/testes (que têm requisicao_id NULL) — validado no mro.db
# real como idêntico ao filtro manual do comprador por Observação "Req%".
# Fragmento WHERE compartilhado (DRY) por listar_inventario, obter_dados_dashboard
# e a Curva ABC, para que a definição de consumo real viva num único lugar.
SAIDA_REAL_WHERE = "tipo='saida' AND requisicao_id IS NOT NULL"

# Status atribuído ao item que NUNCA teve consumo real (0 requisições de saída).
# Sobrepõe 🔴/🟡/🟢 em listar_inventario → some da lista de compra e ganha balde
# próprio, filtrável. NÃO altera a base do Neidson nem apaga nada.
STATUS_SEM_MOVIMENTACAO = "⚪ Sem Movimentação"

# --- Consumo / ruptura ---
JANELA_CONSUMO_DIAS = 30            # janela do consumo medio diario (dias)
PREVISAO_RUPTURA_SEM_RISCO = 999   # dias; sentinela "sem ruptura prevista"
ORDENACAO_RUPTURA_INFINITO = 9999  # sentinela de ordenacao (ruptura "infinita")
RUPTURA_CRISE_DIAS = 15            # limite do filtro "focar em ruptura < N dias"

# --- Aging de SC (dias desde a abertura) ---
AGING_ALERTA_DIAS = 7    # > 7 dias  -> alerta  (amarelo)
AGING_CRITICO_DIAS = 15  # > 15 dias -> critico (vermelho)

# ══════════════════════════════════════════════════════════════════════════════
# v2.2.1 — Cálculos & Transparência
# ══════════════════════════════════════════════════════════════════════════════

JANELAS_CONSUMO = (30, 60, 90)   # janelas (dias) do consumo médio diário
TENDENCIA_LIMIAR_PCT = 15        # |Δ%| > 15 -> "Alta"/"Queda"; senão "Estável"
GIRO_JANELA_DIAS = 90            # janela padrão do giro / estoque médio
LEAD_TIME_MAX_DIAS = 365         # cap de outlier no cálculo de Lead Time (SC7/recebimento)

# ══════════════════════════════════════════════════════════════════════════════
# v2.3.0 — Pilar Financeiro / Valoração
# ══════════════════════════════════════════════════════════════════════════════

# Curva ABC por VALOR consumido (qtd × preço): classe pela % acumulada do valor.
# Curva clássica 80/15/5 → A até 80%, B até 95%, C o restante.
ABC_LIMIAR_A = 80
ABC_LIMIAR_B = 95
VALOR_CONSUMIDO_JANELA_DIAS = 90   # janela padrão de valor consumido / ABC-valor

# ══════════════════════════════════════════════════════════════════════════════
# v2.2.0 — Ingestão do Relatório de SCs / Pilar Financeiro / Snapshots
# ══════════════════════════════════════════════════════════════════════════════

# Decodificação do código numérico de Moeda usado no Protheus/SCM.
# 1 = BRL (assunção padrão; confirmar demais códigos com o ERP). Códigos não
# mapeados são exibidos como "COD:<n>" para manter transparência.
MOEDA_PADRAO = "BRL"
MOEDA_MAP = {
    1: "BRL",
    2: "USD",
    3: "EUR",
}

def decodificar_moeda(codigo):
    """Converte o código de moeda (numérico ou texto) para sigla legível."""
    if codigo is None:
        return MOEDA_PADRAO
    # Já é sigla textual (ex.: 'BRL', 'USD')
    try:
        texto = str(codigo).strip()
    except Exception:
        return MOEDA_PADRAO
    if not texto:
        return MOEDA_PADRAO
    if texto.replace(".", "").isalpha():
        return texto.upper()
    try:
        n = int(float(texto))
    except (ValueError, TypeError):
        return MOEDA_PADRAO
    return MOEDA_MAP.get(n, f"COD:{n}")

# Retenção de fotos diárias de estoque (estoque_snapshots), em dias.
SNAPSHOT_RETENCAO_DIAS = 730  # ~24 meses

# Nomes das abas esperadas no "Relatório de SCs" e a linha de cabeçalho (0-based)
# de cada uma (descobertas por inspeção da planilha real).
RELATORIO_SCS_ABAS = {
    "SCM": 0,
    "SC7": 3,
    "FORNECEDORES": 0,
    "SCM USERS": 1,
}

# ══════════════════════════════════════════════════════════════════════════════
# v2.5.0 — Assistente de Reposição (Planejamento)
# ══════════════════════════════════════════════════════════════════════════════

# Horizonte de abastecimento alvo (meta do PO: ~2 meses). Usado no alvo HÍBRIDO
# da quantidade sugerida: alvo = max(estoque_maximo_Neidson, consumo_dia × N).
HORIZONTE_REPOSICAO_DIAS = 60

# Antecedência da abertura da SC (meta do PO: ~15 dias). O gatilho de reposição
# dispara quando (estoque + guarda-chuva) ≤ ROP + consumo_dia × N, antecipando o
# pedido em N dias além do ponto de pedido clássico.
ANTECEDENCIA_REPOSICAO_DIAS = 15

# Fallback de lead time (dias) quando o item não tem lead time cadastrado (Neidson)
# nem calculado. Rotulado como "lead time desconhecido" para transparência — NÃO
# sobrescreve nem grava nada na base; é usado apenas no cálculo da sugestão.
LEAD_TIME_DEFAULT_DIAS = 30

# Desfechos válidos de uma sugestão de reposição (auditoria em sugestoes_reposicao).
REPOSICAO_DESFECHOS = ("gerada", "criou_sc", "adiada", "ignorada")

# ══════════════════════════════════════════════════════════════════════════════
# v2.8.0 — SCs agrupadas "de mão beijada" (natureza + centro de custo sugeridos)
# ══════════════════════════════════════════════════════════════════════════════

# Natureza/categoria da SC = campo `descricao_solicitacao` das SCs (vocabulário real
# do Protheus, ex.: "SOLICITAÇÃO DE COMPRA - CONSUMÍVEIS PRODUÇÃO"). As SCs sugeridas
# são agrupadas por essa natureza, derivada do histórico de SCs de cada item. Itens
# sem histórico caem na categoria padrão abaixo (categoria legítima da taxonomia).
CATEGORIA_SC_PADRAO = "SOLICITAÇÃO DE COMPRA - OUTROS"

# Centros de custo genéricos/contábeis que NÃO indicam o setor consumidor real
# (dominam as saídas por serem conta residual/rótulos de ajuste). São ignorados ao
# sugerir o CC de uma SC, para não sugerir "99000" em tudo.
CC_GENERICOS = frozenset({
    "99000 - ATIVO PASSIVO RES. F", "INVENTÁRIO", "EDIÇÃO", "",
})

# Rótulo quando não há CC significativo (todos os consumos do grupo são genéricos).
CC_SUGERIDO_PADRAO = "(a definir)"
