---
created: 2026-07-08
status: active
tags:
  - mro-system
  - changelog
  - historico
related:
  - [[MRO System - Visão Geral]]
  - [[Apresentação Inventus Power - KPI Mensal]]
---

# MRO System — Histórico de Versões (linha do tempo condensada)

Fonte: `changelog/*.md`. Útil como insumo direto para a parte da apresentação sobre "o que evoluiu" — dá para contar como uma progressão lógica (fundação → inteligência → decisão por público), não uma lista solta de features.

| Versão | Data | Entrega principal |
|---|---|---|
| **2.0.2** | 14/05/2026 | Observação de inventário em texto livre; correção de auditoria em itens zerados. |
| **2.1.0** | 24/06/2026 | Importação da base do Sr. Neidson (Mín/Máx/Categoria/Lead Time); troca de Part Number rastreável; canal de Feedback. 96 testes. |
| **2.2.0** | 01/07/2026 | Ingestão do Relatório de SCs (preço, fornecedores, solicitantes dinâmicos); "Guarda-Chuva"; Estoque de Segurança vira manual; snapshots diários de estoque. 108 testes. |
| **2.2.1** | 01/07/2026 | Consumo 30/60/90 + tendência; dias de cobertura explícito; Lead Time Real como sugestão (corrige bug que sobrescrevia o cadastrado); giro/tempo em estoque. 119 testes. |
| **2.3.0** | 01/07/2026 | Pilar Financeiro: valor imobilizado, evolução do valor, valor consumido, Curva ABC por valor — sem nenhuma migração de schema. 130 testes. |
| **2.5.0** | 02/07/2026 | Assistente de Reposição: ROP, quantidade sugerida (alvo híbrido), fila priorizada, "Criar SC". 167 testes. |
| **2.6.0** | 03/07/2026 | Ficha 360 do Material (visão consolidada por item, imagem do produto). 180 testes. |
| **2.7.0** | 04/07/2026 | Status "Sem Movimentação": lista de compra cai de 227 para 77 candidatos reais (limpeza de ~150 fantasmas). 190 testes. |
| **2.7.1** | 04/07/2026 | Refinamentos de UX no consumo real e na Ficha 360. |
| **2.8.0** | 04/07/2026 | Assistente de Reposição 2.0: SCs agrupadas "de mão beijada" por natureza, data "Comprar até", críticos automáticos. 206 testes. |
| **2.9.0** | 04/07/2026 | Conversão de Unidades (compra ↔ estoque) — corrige risco de erro de conversão no recebimento (ex.: litros lançados como galões). 237 testes. |
| **2.10.0** | 05/07/2026 | Classificação de Demanda (Syntetos-Boylan) + XYZ + fundação de Sazonalidade. 254 testes. |
| **2.11.0** | 05/07/2026 | Central de Ajuda (com modo "explicar como para uma criança") + tema claro/escuro. 266 testes. |
| **3.0.0** | 05/07/2026 | **Dashboards por público** (Comprador / Gestão / Diretoria) — fecha o roadmap do Blueprint. |
| **3.0.1** | 06/07/2026 | Saúde física do estoque no Dashboard; SBC mais didático; arredondamento na Ficha; Setor Solicitante padronizado; limpeza de emojis → ícones Material. 276 testes. |

## Leitura executiva (para os slides)

- **Ritmo:** ~15 versões entregues entre maio e julho de 2026, cobrindo todo o roadmap planejado no Blueprint (fundação de dados → inteligência → decisão por público) sem nenhuma migração destrutiva.
- **Qualidade:** suíte de testes cresceu de 96 (v2.1.0) para 276 (v3.0.1), acompanhando cada entrega.
- **Princípio mantido em todas as versões:** "assistente, não piloto automático" — nenhuma versão altera a base de referência do Sr. Neidson sem validação humana.
- **Bom exemplo de impacto mensurável:** v2.7.0 reduziu a lista de compra de 227 para 77 itens reais (~66% de "ruído" removido) — um número concreto e fácil de contar em slide.
