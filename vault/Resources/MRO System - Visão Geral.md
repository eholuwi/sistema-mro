---
created: 2026-07-08
status: active
tags:
  - mro-system
  - visao-geral
related:
  - [[MRO System - Catálogo de KPIs]]
  - [[MRO System - Histórico de Versões]]
  - [[Apresentação Inventus Power - KPI Mensal]]
---

# MRO System — Visão Geral

## O que é

Plataforma interna da **Inventus Power** (Streamlit + SQLite) para gestão de materiais **MRO** (Manutenção, Reparo e Operações). Não é um produto para cliente externo — é ferramenta operacional da própria empresa, usada pelos compradores indiretos e pelo Almoxarifado.

## O problema que resolve

A falta de material MRO **não** vem de deixar de solicitar — vem do gargalo entre abrir a SC (Solicitação de Compra) e a compra efetiva de fato acontecer. Antes do sistema, os dados viviam espalhados em planilhas paralelas; o comprador perdia tempo procurando informação e voltando com dúvidas para o Almoxarifado.

**Lema do sistema:** nunca deixar faltar material, sem excesso de estoque.

**Princípio inegociável:** o sistema é **assistente, não piloto automático** — ele recomenda o quê/quando/quanto comprar, com justificativa; quem decide e cria a SC é sempre o comprador. A base de referência do Sr. Neidson (Mínimo/Máximo/Categoria/Lead Time) nunca é sobrescrita por cálculo automático — o sistema só **sugere ao lado** ("calculado X · cadastrado Y").

## Módulos principais

- **Dashboard por público** (`services/dashboards.py`) — três visões: [[MRO System - Catálogo de KPIs|Comprador / Gestão / Diretoria]].
- **Assistente de Reposição** (`services/planejamento.py`) — motor de ROP (ponto de pedido), fila priorizada, quantidade sugerida (alvo híbrido), SCs agrupadas "de mão beijada" por natureza, data-limite "Comprar até".
- **Ficha 360 do Material** (`services/ficha.py`) — tela única com todo o ciclo de vida do item: estoque, consumo, compras, fornecedores, ABC, imagem do produto.
- **Classificação de Demanda — SBC** (`services/classificacao.py`, `services/constants.py`) — padrão Syntetos-Boylan (Suave/Intermitente/Errático/Irregular) + classe XYZ + fundação de sazonalidade.
- Importação do Relatório de SCs (planilha diária dos compradores) como fonte primária de dados: preço, guarda-chuva, fornecedores, solicitantes.
- Rastreabilidade completa: movimentações, histórico de Part Number, snapshots diários de estoque.

## Arquitetura (via grafo de conhecimento `graphify-out/`)

- 62 arquivos, ~800 nós, 66 comunidades, sem ciclos de import.
- Hubs principais: `planejamento.py`, `db_functions.py`, `app.py`, `ficha.py`, `dashboards.py`, `classificacao.py`.
- Funções "god node": `make_item()` (138 conexões), `transaction()` (74), `registrar_consumo()`.
- Padrão de release consolidado desde a v2.7.0: a maioria das novas funcionalidades é **derivada na leitura** (sem migração de schema), o que explica o ritmo rápido de entregas.

## Como contar a evolução

O sistema saiu de um MVP de inventário (v2.0.2) para uma plataforma de inteligência de materiais completa (v3.0.1) em poucos meses, seguindo o roadmap do [[MRO System - Catálogo de KPIs|Blueprint]]: Fundação de Precisão → Pilar Financeiro → Fornecedores → Assistente de Reposição → Ficha 360 → Classificação de Demanda → Dashboards por público. Ver linha do tempo completa em [[MRO System - Histórico de Versões]].
