"""Constantes de dominio centralizadas (Fase 4.1 / F4-08 parcial).

Apenas da nome unico a valores numericos que estavam hardcoded no codigo.
NAO altera logica, enums, schema nem CHECK constraints -- os valores sao
identicos aos que ja existiam; somente foram extraidos para um unico lugar."""

# --- Status de estoque ---
MARGEM_ATENCAO = 1.2           # limite da zona ATENCAO = estoque_minimo * 1.2
FATOR_ESTOQUE_MAXIMO = 2       # estoque_maximo = estoque_minimo * 2
FATOR_ESTOQUE_SEGURANCA = 1.5  # estoque_seguranca = consumo * lead_time * 1.5

# --- Consumo / ruptura ---
JANELA_CONSUMO_DIAS = 30            # janela do consumo medio diario (dias)
PREVISAO_RUPTURA_SEM_RISCO = 999   # dias; sentinela "sem ruptura prevista"
ORDENACAO_RUPTURA_INFINITO = 9999  # sentinela de ordenacao (ruptura "infinita")

# --- Aging de SC (dias desde a abertura) ---
AGING_ALERTA_DIAS = 7    # > 7 dias  -> alerta  (amarelo)
AGING_CRITICO_DIAS = 15  # > 15 dias -> critico (vermelho)
