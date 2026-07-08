---
created: 2026-07-08
status: active
tags:
  - referencia
  - estilo-visual
  - benchmark
related:
  - [[Apresentação Inventus Power - KPI Mensal]]
---

# Referência de estilo — Dashboard KPI Indireto (outro setor)

Benchmark visual de como outro setor (Compras Indireto) já entrega o dashboard de KPI mensal na Inventus Power. Útil para calibrar a linguagem visual da apresentação do MRO System com o que a empresa já pratica na reunião mensal.

## Arquivos de referência

- `Tarefas Diárias\03_KPI Indireto Mensal\WK\Primeira Entrega.html` — "KPI de Compras Improdutivo — Inventus Power, Manaus, Jan-Abr 2026". Dashboard HTML autocontido com Chart.js.
- `Tarefas Diárias\03_KPI Indireto Mensal\KPI Dashboard HTML\Dashboard KPI Indireto.html` — versão mais recente/polida, com toggle de tema claro/escuro e modo de edição.

## Padrões observados (para reaproveitar ou contrastar)

- **Paleta:** tema laranja/escuro — coincide com a cor de marca do próprio MRO System (`#F36F21`, ver `services/tema.py`), então dá pra manter consistência visual entre os dois dashboards.
- **Cards de KPI no topo:** poucos números grandes (ex.: Dispêndio Nacional, Saving, PO's Emitidos, Itens Entregues) — mesma filosofia de "poucos números que contam uma história" que vale para a apresentação do MRO.
- **Gráficos de barra mensal** (gasto/saving) + **ranking top-10 de fornecedores** por categoria (Improdutivo/Produtivo/Logística/Importado/Contratos).
- **Tabela de status de contratos** como fechamento.
- Não há um modelo de slides/PPT — o "dashboard" da reunião mensal parece ser, na prática, esse HTML interativo, não uma apresentação estática. Vale confirmar com o usuário se o formato esperado para o MRO System é o mesmo (dashboard HTML) ou se ele quer mesmo slides tradicionais + roteiro falado.

## Pergunta em aberto

Levar para [[Apresentação Inventus Power - KPI Mensal]] → Open Loops: **qual é de fato o formato de entrega esperado na reunião?** (slide deck, dashboard HTML interativo, ou os dois — dashboard como material de apoio e slides para a fala).
