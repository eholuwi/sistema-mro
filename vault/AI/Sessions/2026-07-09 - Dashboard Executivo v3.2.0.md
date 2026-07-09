---
created: 2026-07-09
status: active
tags:
  - session-log
  - dashboard
  - v3.2.0
related:
  - [[Apresentação Inventus Power - KPI Mensal]]
  - [[MRO System - Catálogo de KPIs]]
---

# Session Log — 2026-07-09 — Dashboard Executivo/Mensal (v3.2.0)

## O que foi feito

Nova **4ª visão do Dashboard — "📊 Mensal"** (perfil ao lado de Comprador/Gestão/Diretoria),
redesenhada como painel executivo denso para apresentar todo mês. Panorama do **ano corrente (YTD)**,
foco em **R$** e em **rankings Top 10**.

Conteúdo da visão:
- KPIs: valor imobilizado · valor consumido no ano (YTD) · requisições YTD · itens movimentados · nível de serviço · giro · críticos · rupturas.
- Consumo mês a mês (R$) + composição por tipo de material (donut).
- Curva ABC por valor (corrigida) + contagem A/B/C.
- **7 rankings Top 10:** valor consumido, quantidade, capital parado, "dinheiro dormindo" (dead stock), centros de custo, emitentes, setores.
- Padrões de demanda (SBC), distribuição do inventário (donut), aging de SCs.

## Achado / correção importante (útil para a apresentação)

A **Curva ABC** tinha um bug: contava **ajustes físicos de inventário** (contagens) como se fossem
consumo — inflava valores (um ajuste de 99.999 un num alicate virava R$ 2,1 mi; um grampo aparecia
com R$ 4,2 mi). Corrigido para usar consumo real (saída por requisição). Corrige também a visão
**Diretoria**. Números reais depois do fix: valor consumido YTD ≈ R$ 132,5k; topo do ABC = ROLO DE
PANO WIPER ≈ R$ 18,8k (sem mais absurdos).

## Ganchos para a apresentação

- O ranking **"dinheiro dormindo"** (dead stock — estoque parado sem saída no ano) é uma boa história
  de governança/melhoria para mostrar à gestão.
- A correção do ABC é um exemplo de **melhoria de qualidade de dado** que o sistema passou a garantir.
- A própria visão "Mensal" é candidata a ser a tela projetada na reunião de KPI.

## Estado técnico

- v3.2.0, sem migração de schema. 302 testes verdes. Validada no `mro.db` real + AppTest sem exceção.
- Grafo do Graphify atualizado (`graphify update .`).
- Commitada e enviada ao `main` (junto com o commit pendente da v3.1.0, que não havia sido versionada).

## Próximos passos

- Resolver os Open Loops em [[Apresentação Inventus Power - KPI Mensal]] (formato de entrega, data da reunião).
- Avaliar exportação do panorama (PDF/imagem/Excel) — ficou fora do escopo da v3.2.0.
