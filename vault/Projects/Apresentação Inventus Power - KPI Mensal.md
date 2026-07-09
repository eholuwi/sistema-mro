---
created: 2026-07-08
status: active
tags:
  - projeto
  - apresentacao
  - inventus-power
related:
  - [[MRO System - Visão Geral]]
  - [[MRO System - Catálogo de KPIs]]
  - [[MRO System - Histórico de Versões]]
  - [[Referência - Estilo Dashboard KPI Indireto]]
---

# Apresentação Inventus Power — Reunião Mensal de KPI

Nota-mestre do projeto. Toda sessão de trabalho relacionada a essa apresentação deve ler e atualizar esta nota (ver protocolo em `vault/CLAUDE.md`).

## Objetivo

**PRIMEIRA APRESENTAÇÃO** do MRO System na reunião mensal de KPI da Inventus Power. Apresentar o MVP que já está em produção e entregando resultados reais (melhor do que o estado anterior), com ênfase em:
- O problema operacional que existia
- A solução pronta (MVP funcional)
- Os resultados concretos já alcançados
- O caminho futuro (roadmap)

A apresentação precisa:
- Ser **completa** — antecipar dúvidas (o que é, por que importa, o que já melhorou).
- **Não ser maçante** — poucos números bem escolhidos que contam a história do impacto.

## Público

Reunião multissetorial de KPI mensal (não é uma apresentação só para TI/dev). Provavelmente inclui gestão e possivelmente diretoria — ver [[MRO System - Catálogo de KPIs]] para as visões que o próprio sistema já modela por público (Comprador/Gestão/Diretoria), que podem inspirar a estrutura da fala.

## Insumos já levantados

- [[MRO System - Visão Geral]] — o que o sistema é e o problema que resolve.
- [[MRO System - Catálogo de KPIs]] — indicadores por público, com fórmulas e explicações em 1 frase.
- [[MRO System - Histórico de Versões]] — linha do tempo de entregas (maio→julho 2026), boa para mostrar ritmo e evolução.
- [[Referência - Estilo Dashboard KPI Indireto]] — benchmark visual de como outro setor já apresenta KPI mensal na empresa.

## Estrutura da apresentação (PRIMEIRA ESTREIA)

1. **O Problema** — estado anterior (processos manuais, dados em planilhas, SC→compra lento, sem visibilidade).
2. **A Solução** — o MRO System como assistente inteligente de materiais (MVP funcional, já em produção).
3. **Resultados já alcançados** — números reais que mostram melhoria vs. antes (ex.: tempo SC→compra, precisão da previsão, redução de críticos). Ver números concretos abaixo.
4. **Como funciona** — fluxo visual do sistema (entender o que o sistema faz no dia a dia).
5. **Roadmap** — próximos passos (Savings, OTIF real, modulação por demanda) — contexto futuro, não promessa de hoje.

**Números concretos a puxar do mro.db:**
- Tempo médio SC→PO antes vs. depois (ou evolução ao longo das versões)
- Redução de itens em lista de compra (ex.: 227 → 77, já documentado na v2.7.0)
- Taxa de acerto de previsão / redução de críticos
- Valor imobilizado economizado ou desbloqueado
- Qualquer outra métrica que mostre "isto funcionava pior antes, agora funciona melhor"

## Open Loops (pendências)

- [ ] **Números reais de impacto**: puxar do `mro.db` de produção métricas que mostrem melhoria vs. estado anterior (tempo SC→PO, redução críticos, acurácia previsão, valor desbloqueado). Fórmulas estão em [[MRO System - Catálogo de KPIs]].
- [ ] **Data/contexto da reunião**: quando é a apresentação? Quem vai estar lá? Quanto tempo de fala? (para calibrar profundidade).
- [ ] **Formato de entrega**: slides tradicionais, dashboard HTML interativo, ou ambos?
- [ ] Gerar rascunho de slides e roteiro (sem pressa — somente após validar os pontos acima).

## Decisões já tomadas

- Segundo cérebro criado dentro do repo (`vault/`), dedicado só ao MRO System — ver Session Log de 2026-07-08. Decisão inicial era ignorá-lo no git; revertida logo em seguida para versioná-lo e sincronizá-lo entre máquinas (ver `CLAUDE.md` da raiz).
- **É PRIMEIRA APRESENTAÇÃO do sistema** (não mensal recorrente) → foco em "problema → solução MVP → resultados reais já alcançados → roadmap futuro".
- **Não gerar slides/roteiro ainda** — esperar dados reais de impacto e contexto da reunião (data/duração/público).
