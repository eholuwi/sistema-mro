# Sistema MRO — Project Instructions

Base operacional do Sistema MRO da Inventus Power (materiais improdutivos, estoque, reposição,
compras, curva ABC, cobertura, lead time, dashboards, KPIs, integração Protheus/SCM). Streamlit +
SQLite. Você sabe ler código — este arquivo só diz **onde está cada coisa** e como não desperdiçar
contexto.

## Onde está cada coisa

| Domínio | Arquivo |
|---|---|
| UI — shell + páginas ainda inline | `app.py` (encolhendo a cada fase da refatoração v5.x) |
| UI — router (fonte única do menu) | `ui/router.py` (`ROTAS`, `ROTAS_MIGRADAS`, `render_pagina`) |
| UI — sidebar / tema / formatos / cache | `ui/sidebar.py`, `ui/tema.py`, `ui/formatos.py`, `ui/cache.py` |
| UI — páginas migradas (`render()`) | `ui/paginas/` (por ora: `ajuda.py`, `configuracoes.py`) |
| Lógica + acesso a dados | `services/db_functions.py` |
| Banco / schema / migração | `database.py`, `migrations/` |
| Planejamento (min/máx, cobertura, lead time) | `services/planejamento.py` |
| Curva ABC / classificação de demanda | `services/classificacao.py` |
| Dashboards / KPIs / drill-down | `services/dashboards.py`, `services/drill_down.py` |
| Ficha 360 | `services/ficha.py` |
| SCM / Monitor de SC | `services/monitor_scm.py`, `services/monitor_cruzamento.py`, `services/scm_client.py` |
| Constantes / tema / estilos | `services/constants.py`, `services/tema.py`, `services/styles.py` |
| Testes (regressão por versão) | `tests/test_vXXX_*.py` |
| Continuidade / backlog | `docs/HANDOFF.md` (seção "STATUS ATUAL" no topo), `docs/prompt.md` |
| Changelog | `changelog/*.md` |

A camada de interface vive em **`ui/`** (regra de dependência: `ui/paginas/*` importa `ui/*` e
`services/*`; `services/*` nunca importa `ui/`). As pastas `controllers/`, `repositories/`,
`models/`, `core/`, `app/`, `pages/`, `dashboards/` são scaffolding **vazio** (só `__init__.py`/
README) — não há lógica ali; serão removidas numa fase posterior (`pages/` é diretório mágico do
Streamlit — evitar).

## Política de economia de contexto

- Ler apenas os módulos relacionados ao pedido; nunca varrer o projeto inteiro sem necessidade.
- Usar `graphify query`/`explain` para localizar impacto **antes** de abrir `app.py` ou
  `db_functions.py` (são grandes).
- Reutilizar funções existentes — nunca duplicar lógica que já existe.
- Preferir extensão incremental a criar arquivo novo; todo arquivo novo precisa de justificativa.
- Não reescrever código estável; não criar abstrações antecipadas (YAGNI).
- Manter o menor número possível de Skills e Subagentes.

## Regras invioláveis

1. Preservar compatibilidade com `mro.db` e com o app atual.
2. Nunca duplicar lógica quando uma função já existe.
3. Nunca alterar regra de negócio/cálculo sem contexto, impacto e testes.
4. Nunca alterar schema sem backup, migração e validação.
5. Labels e mensagens sempre em português, alinhadas à operação real.
6. Commit só após validação no app real **e** OK explícito do usuário.

## Fluxo

Qualquer pedido de evolução ("quero atualizar o Sistema MRO", nova tela, bug, cálculo, KPI,
dashboard) → invoque a Skill `atualizar-sistema-mro` (`.claude/skills/`). Ela organiza requisitos,
mapeia impacto, planeja versão/backlog e só implementa após aprovação.

## Graphify e Vault

- Graphify é navegação; código é a fonte da verdade. Não atualizar automaticamente.
- Vault Obsidian não deve ser modificado, salvo pedido explícito envolvendo apresentação/KPI mensal.
