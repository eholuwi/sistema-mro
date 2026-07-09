---
created: 2026-07-08
status: active
tags:
  - meta
  - segundo-cerebro
---

# Segundo Cérebro — MRO System (memória operacional do agente)

Este arquivo é a memória operacional do Claude Code quando o trabalho é feito **dentro desta pasta `vault/`** (ex.: abrindo `vault/` como pasta de trabalho, ou quando o usuário pede algo relacionado à apresentação/KPIs do MRO System a partir da raiz do repo). Ele segue o método "AI Second Brain": Obsidian guarda o conhecimento em Markdown, o CLAUDE.md dá o protocolo, e os Session Logs garantem continuidade entre sessões que não têm memória própria.

## Quem é o usuário

- Luis Gabriel Arruda de Oliveira, desenvolvedor do MRO System na **Inventus Power** (Manaus). É o autor do próprio sistema — nível técnico alto, não precisa de explicações básicas de programação.
- Objetivo imediato: preparar uma apresentação do MRO System para a **reunião mensal de KPI** da empresa, onde cada setor entrega um dashboard de KPI atualizado. A apresentação precisa ser **completa** (antecipar perguntas) mas **não maçante**.
- Ver [[Apresentação Inventus Power - KPI Mensal]] para o estado atual desse objetivo.

## Escopo deste vault

Dedicado **só ao MRO System** — não é um segundo cérebro genérico do usuário (ele tem outros projetos em `Tarefas Diárias\` que não entram aqui). Fica dentro do repositório do MRO System (`vault/`) e é **versionado no git** (decisão revertida em relação à ideia inicial de ignorá-lo) justamente para sincronizar entre máquinas diferentes — ver `CLAUDE.md` da raiz, seção "Segundo Cérebro (Obsidian)".

## Estrutura do vault

- `Inbox/` — capturas rápidas (ideias soltas, perguntas que surgirem, dados brutos ainda não organizados). Processar e mover para o lugar certo em vez de deixar acumular.
- `Projects/` — projeto ativo único por enquanto: [[Apresentação Inventus Power - KPI Mensal]] (a nota-mestre — objetivo, público, estrutura de slides/roteiro, perguntas em aberto).
- `Resources/` — conhecimento de referência sobre o MRO System, reaproveitável entre sessões:
  - [[MRO System - Visão Geral]]
  - [[MRO System - Catálogo de KPIs]]
  - [[MRO System - Histórico de Versões]]
  - [[Referência - Estilo Dashboard KPI Indireto]]
  - [[MRO System - Contexto, Origem e Pessoas]]
- `Archive/` — o que sair de escopo (ex.: depois que a apresentação acontecer).
- `AI/Sessions/` — um arquivo por sessão de trabalho relevante (o que foi feito, decisões, próximos passos).
- `AI/Summaries/` — resumos de leituras/pesquisas maiores (ex.: se o usuário trouxer PDFs/artigos para embasar a apresentação).
- `AI/Logs/` — reservado para logs mais técnicos, se necessário.
- `Templates/` — [[Template - Daily Note]] e [[Template - Session Log]].
- `Daily Notes/` — uma nota por dia de trabalho (`YYYY-MM-DD.md`), com Prioridades / Open Loops / Contexto para IA / Agent Log.

## Protocolo de sessão

### Ao iniciar uma sessão de trabalho ligada à apresentação/KPI

1. Ler a Daily Note mais recente em `Daily Notes/`.
2. Ler o Session Log mais recente em `AI/Sessions/` (ordenar por data no nome do arquivo).
3. Ler [[Apresentação Inventus Power - KPI Mensal]] para saber o estado atual (open loops, decisões já tomadas).
4. Só então prosseguir com a tarefa pedida.

### Ao finalizar uma sessão que produziu algo relevante (decisão, conteúdo novo, dado levantado)

1. Criar um novo arquivo em `AI/Sessions/YYYY-MM-DD - <resumo curto>.md` usando [[Template - Session Log]].
2. Atualizar a seção "Agent Log" da Daily Note do dia (criar a nota do dia a partir de [[Template - Daily Note]] se ainda não existir).
3. Registrar decisões e novas pendências em [[Apresentação Inventus Power - KPI Mensal]] (seção "Open Loops").
4. Não é necessário fazer isso para interações triviais (ex.: uma pergunta rápida sem produzir conteúdo novo) — só quando há algo que a próxima sessão precisa saber.

## Preferências

- Idioma: **português (Brasil)**, sempre.
- Estilo: direto, objetivo, sem enrolação — o usuário já é técnico e já conhece o sistema; o valor está em organizar/conectar/resumir, não em explicar o óbvio.
- Para a apresentação em si: priorizar **poucos números que contam uma história** (evolução, impacto) sobre listas exaustivas de features — o objetivo é "completo mas não maçante".

## Ferramentas e fontes disponíveis

- Repositório do MRO System (raiz, um nível acima deste vault): código-fonte, `docs/Blueprint - Plataforma de Inteligencia de Materiais.md`, `changelog/*.md` (histórico versão a versão), `README.md`/`LEIA-ME.md`.
- `graphify-out/` na raiz do repo — grafo de conhecimento do código (usar `graphify query/path/explain` para dúvidas de arquitetura; ver `CLAUDE.md` da raiz).
- Referência visual de outro setor da empresa (Compras Indireto): ver [[Referência - Estilo Dashboard KPI Indireto]].
