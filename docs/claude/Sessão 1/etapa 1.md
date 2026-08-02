📋 MAPEAMENTO CONCLUÍDO
Realizei uma análise completa da estrutura do Sistema MRO. Aqui está o que foi descoberto:

Estrutura Encontrada
9 Páginas Renderizáveis (todas em ui/paginas/)
✅ Dashboard · Saldo em Estoque · Ficha 360 · Cadastro de Itens · Movimentação · Controle de SC · SCM Integrado · Ajuda · Configurações

4 Dashboards Principais
Dashboard Comprador (Visão de ação)

KPIs: críticos, compra atrasados, SCs abertas, rupturas
Fila de reposição priorizada + Aging (0-7, 8-15, 15+)
Dashboard Almoxarifado (Saúde do estoque)

Incorporou conteúdo da antiga aba "Gestão" (v4.1.0)
7 KPIs: itens cadastrados, entradas/requisições hoje, compra urgente, sem giro, valor, cobertura
Gráficos: consumo Top 10, distribuição por setor, padrões de demanda
Dashboard KPI Mensal (Visão executiva)

Valor imobilizado, giro, ABC por valor, tendências semanais
Dashboard Compras MRO (Analytics de compras)

Ingestão de Relatório de SCs, aging, fornecedores, departamentos
Cálculos Financeiros (Services)
Cálculo	Arquivo	Função
Valor imobilizado	db_functions.py	obter_valor_imobilizado()
Giro anual	db_functions.py	calcular_giro()
ABC por valor	db_functions.py	obter_abc_valor()
Preço de valoração	db_functions.py	_preco_valoracao()
Moeda (Protheus/SCM)	constants.py	decodificar_moeda()
Constantes:

ABC_LIMIAR_A = 80%, ABC_LIMIAR_B = 95%
VALOR_CONSUMIDO_JANELA_DIAS = 90
MOEDA_MAP = {1: "BRL", 2: "USD", 3: "EUR"}
Formatação de Valores Monetários
Contexto	Função	Exemplo
Gráficos (labels)	_brl_compact()	18800 → "R$ 18,8k"
Tabelas/cards	_dash_fmt_brl()	→ "R$ X.XXX,XX"
Eixo de tempo	_mes_label()	"2026-07" → "jul/26"
Componentes Reutilizáveis (ui/componentes/)
Gráficos Plotly:

_barh() — Barras horizontais (ranking)
_donut() — Donut (composição)
_barv() — Barras verticais (categorias)
_linhas() — Série temporal
_barras_agrupadas() — Comparativo agrupado
Outros:

filtros.py — Widgets de filtro
tabela.py — DataFrames estilizados
selecao.py — Selectors
status.py — Cards de KPI
exportar.py — Downloader XLSX/CSV
Dependências Entre Dashboards

Dashboard (9 páginas)
  ├─ Comprador → montar_visao_comprador() 
  ├─ Almoxarifado → montar_visao_almoxarifado()
  │   └─ listar_inventario() [SAIDA_REAL_WHERE, ENTRADA_REAL_WHERE]
  ├─ KPI Mensal → montar_dashboard(PUBLICO_EXECUTIVO)
  │   └─ gerar_sugestoes_reposicao() [planejamento.py]
  │   └─ gerar_scs_sugeridas() [classificacao.py]
  └─ Compras → montar_visao_compras_mro()
      └─ itens_sc_externos [scm_sync.py]
Arquivos Relevantes Encontrados (131 identificados)
Core: 30 arquivos

Testes: 90 arquivos (138 casos, 638 testes)

Documentação: 60 arquivos (changelog + docs)

Pontos a Analisar na Próxima Etapa
 Todas as chamadas aos formatadores monetários
 Fluxo completo: entrada de preço → cálculo → exibição
 Bordas (zero, None, múltiplas moedas)
 Snapshots de valor (histórico diário, 730 dias)
 Integração com Protheus/SCM (moeda, câmbio)
 Gráficos afetados por mudança em constantes
Documento completo disponível no Artifact acima. Estrutura mapeada, sem propostas de solução. Pronto para próxima fase.