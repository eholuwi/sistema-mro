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

Apresentar o MRO System na reunião mensal de KPI da Inventus Power, onde cada setor entrega um dashboard de KPI atualizado do mês. A apresentação precisa:
- Ser **completa** — antecipar as dúvidas prováveis da plateia (o que é, para que serve, o que já entregou, quanto vale).
- **Não ser maçante** — poucos números que contam uma história, não uma lista exaustiva de features.

## Público

Reunião multissetorial de KPI mensal (não é uma apresentação só para TI/dev). Provavelmente inclui gestão e possivelmente diretoria — ver [[MRO System - Catálogo de KPIs]] para as visões que o próprio sistema já modela por público (Comprador/Gestão/Diretoria), que podem inspirar a estrutura da fala.

## Insumos já levantados

- [[MRO System - Visão Geral]] — o que o sistema é e o problema que resolve.
- [[MRO System - Catálogo de KPIs]] — indicadores por público, com fórmulas e explicações em 1 frase.
- [[MRO System - Histórico de Versões]] — linha do tempo de entregas (maio→julho 2026), boa para mostrar ritmo e evolução.
- [[Referência - Estilo Dashboard KPI Indireto]] — benchmark visual de como outro setor já apresenta KPI mensal na empresa.

## Rascunho inicial de estrutura (a validar com o usuário)

1. **Abertura** — o problema (gargalo SC→compra, dados espalhados em planilhas).
2. **Solução** — o MRO System como assistente de inteligência de materiais (não piloto automático).
3. **KPIs atuais** — usar a visão Gestão como base (nível de serviço, cobertura, valor imobilizado, giro, saúde física do estoque) + destaque Comprador (críticos, rupturas, SCs abertas).
4. **Evolução** — linha do tempo de versões, com 1-2 números de impacto concretos (ex.: lista de compra caiu de 227 para 77 itens reais na v2.7.0).
5. **Próximos passos** — o que falta no roadmap (Savings/Spot Saving, OTIF real, modulação por padrão de demanda).

## Open Loops (pendências)

- [ ] **Formato de entrega**: confirmar se a reunião espera slides tradicionais, um dashboard HTML interativo (como o de Compras Indireto), ou os dois.
- [ ] **Números reais do mês corrente**: puxar do `mro.db` de produção os valores atuais (nível de serviço %, valor imobilizado R$, nº de críticos, cobertura média) — o catálogo de KPIs documenta as fórmulas, não os valores ao vivo.
- [ ] Validar com o usuário se o recorte da apresentação é "o sistema como um todo" ou "só o que evoluiu neste mês/período" (formato típico de reunião de KPI mensal costuma ser este último).
- [ ] Depois que os pontos acima estiverem resolvidos: gerar rascunho de slides e roteiro (roteiro = o que falar em cada slide) numa sessão futura.

## Decisões já tomadas

- Segundo cérebro criado dentro do repo (`vault/`), dedicado só ao MRO System, ignorado pelo git — ver Session Log de 2026-07-08.
