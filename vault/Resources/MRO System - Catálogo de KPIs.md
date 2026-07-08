---
created: 2026-07-08
status: active
tags:
  - mro-system
  - kpi
  - catalogo
related:
  - [[MRO System - Visão Geral]]
  - [[Apresentação Inventus Power - KPI Mensal]]
---

# MRO System — Catálogo de KPIs

Fonte: `services/dashboards.py` (v3.0.0, refinado na v3.0.1), `services/planejamento.py`, `services/classificacao.py` e `docs/Blueprint - Plataforma de Inteligencia de Materiais.md` (catálogo de fórmulas). Cada indicador do sistema é desenhado para ser **explicável em 1 frase** (princípio do PO) — útil para os slides: usar a explicação simples, deixar a fórmula para um "como é calculado" se alguém perguntar.

## 👤 Visão Comprador — "o que fazer agora"

| KPI | Cálculo | Explicação em 1 frase |
|---|---|---|
| 🔴 Críticos | itens com prioridade tier 0 (no/abaixo do ponto de pedido) | Itens que já precisam de compra agora. |
| ⏰ Comprar até atrasados | itens cuja data-limite "Comprar até" já passou | Itens que já deveriam ter sido comprados. |
| 🧾 SCs abertas | contagem de SCs com status aberto | Quantas solicitações de compra estão em andamento. |
| 🚨 Rupturas | consumo real E estoque atual = 0 | Itens que zeraram e têm demanda de verdade (risco imediato). |
| Fila de reposição | fila priorizada (urgência → criticidade → menor cobertura) | O que comprar, em que ordem. |
| SCs sugeridas "de mão beijada" | itens agrupados por natureza da SC (histórico real) | SCs prontas para criar em 1 clique, no vocabulário do Protheus. |
| Aging de SCs abertas | dias desde abertura, baldes 0-7 / 8-15 / 15+ | Há quanto tempo as SCs estão paradas — mede o gargalo comprador. |

## 📊 Visão Gestão — "saúde da operação"

| KPI | Cálculo | Explicação em 1 frase |
|---|---|---|
| 🎯 Nível de Serviço de Estoque | % de itens com consumo real fora de ruptura | Proxy de disponibilidade — **não** é o OTIF do fornecedor. |
| 📅 Cobertura média | média de `dias_cobertura` (exclui sentinela "sem risco") | Em média, quantos dias o estoque dos itens ativos dura. |
| 💰 Valor imobilizado | Σ (estoque × preço de referência) | Quanto capital está parado em estoque (estimativa rotulada). |
| 🔄 Giro médio (ano) | média do giro anual dos itens com consumo real | Quantas vezes por ano o estoque se renova, em média. |
| Distribuição de status | Ok / Atenção / Comprar / Sem Mov. / Zerados / Inventariado | Como o inventário se divide por situação. |
| **Saúde física do estoque** (v3.0.1) | Ok / Atenção / Crítico / Zerado sobre **todos** os itens (inclusive Sem Movimentação) | Visão física pura do estoque, sem misturar com "vale a pena comprar". |
| Padrões de demanda (SBC) | ver seção abaixo | Como cada item se comporta na demanda. |
| Classe XYZ | coeficiente de variação do consumo mensal (limiares 0,5 / 1,0) | Estável (X) / variável (Y) / errático (Z). |
| Top 10 Consumidores / Requisições por Setor | agregação de consumo real | Quem mais consome material MRO. |

## 🏛️ Visão Diretoria — "retrato financeiro"

| KPI | Cálculo | Explicação em 1 frase |
|---|---|---|
| 💰 Valor imobilizado | mesmo cálculo da Gestão | Quanto dinheiro está parado em estoque. |
| 📈 Evolução do valor imobilizado | série de `estoque_snapshots` (fotos diárias) | Como o capital parado mudou ao longo do tempo. |
| 🏆 ABC por valor | ranking por valor consumido (qtd × preço), classes A/B/C nos limiares 80/95% | Onde está concentrado o gasto (poucos itens = maior parte do valor). |
| 💹 Savings | **"em breve"** — placeholder honesto | Ainda não há ingestão de dados de Spot Saving; não se inventa número. |

## Classificação de Demanda (Syntetos-Boylan) — usada pela Gestão

Cada item é classificado pelo padrão das suas **saídas reais** (por requisição, não ajustes/inventário), usando dois eixos: **ADI** (regularidade do tempo entre demandas, limiar 1,32) e **CV²** (variabilidade do tamanho, limiar 0,49).

| Padrão | Explicação |
|---|---|
| 🟢 Suave | Sai com regularidade e em quantidades parecidas — o mais previsível de repor. |
| 🔵 Intermitente | Sai de vez em quando, mas em quantidades parecidas — previsível no tamanho, não no tempo. |
| 🟠 Errático | Sai com regularidade, porém em quantidades bem diferentes a cada vez. |
| 🔴 Irregular | Sai raramente e em quantidades imprevisíveis — o mais difícil de planejar (lumpy). |

Honestidade de dado: com ~3 meses de histórico, os indicadores de série (XYZ, giro, sazonalidade) vêm **rotulados por maturidade** ("baseado em N dias/meses") — nunca apresentados como verdade definitiva. Isso é um ponto forte para a apresentação: mostra rigor metodológico.

## Fórmulas de apoio (Blueprint, catálogo completo)

| Indicador | Fórmula |
|---|---|
| Consumo médio diário | Σ saídas(janela) / dias (janelas 30/60/90) |
| Dias de cobertura | (estoque + guarda-chuva) / consumo diário |
| Previsão de ruptura | estoque / consumo diário |
| Guarda-Chuva | Σ (qtd pedido − qtd entregue) das SCs abertas |
| Ponto de Pedido (ROP) | consumo diário × lead time + estoque de segurança |
| Giro de estoque | consumo do período / estoque médio (via snapshots) |
| Tempo médio em estoque | 365 / giro |
| "Comprar até" | hoje + (cobertura − lead time − 15 dias) |
| Qtd sugerida de compra | teto(alvo híbrido − estoque − guarda-chuva), alvo = max(máximo Neidson, consumo × 60d) |

**Nota para a apresentação:** os números reais do mês corrente (ex.: nível de serviço %, valor imobilizado em R$, quantos críticos hoje) ainda precisam ser puxados do `mro.db` de produção — este catálogo documenta *como* cada KPI é calculado, não os valores atuais. Ver "Open Loops" em [[Apresentação Inventus Power - KPI Mensal]].
