# Sistema MRO — Project Instructions

Base operacional do Sistema MRO da Inventus Power (materiais improdutivos, estoque, reposição,
compras, curva ABC, cobertura, lead time, dashboards, KPIs, integração Protheus/SCM). Streamlit +
SQLite. Você sabe ler código — este arquivo só diz **onde está cada coisa** e como não desperdiçar
contexto.

## Onde está cada coisa

| Domínio | Arquivo |
|---|---|
| UI — shell (só setup + sidebar + despacho) | `app.py` (49 linhas; a migração terminou na F4b) |
| UI — router (fonte única do menu) | `ui/router.py` (`ROTAS`, `ROTAS_MIGRADAS`, `render_pagina`) |
| UI — sidebar / tema / formatos / cache | `ui/sidebar.py`, `ui/tema.py`, `ui/formatos.py`, `ui/cache.py` |
| UI — páginas (`render()`) | `ui/paginas/` — as 9 rotas; `ROTAS_MIGRADAS == ROTAS` |
| UI — componentes reusáveis | `ui/componentes/` (`filtros`, `tabela`, `selecao`, `status`, `graficos`) |
| Lógica + acesso a dados | `services/db_functions.py` |
| Banco / schema / migração | `database.py` — `criar_banco()` cria e `_migrar()` migra, em runtime |
| Planejamento (min/máx, cobertura, lead time) | `services/planejamento.py` |
| Curva ABC / classificação de demanda | `services/classificacao.py` |
| Dashboards / KPIs / drill-down | `services/dashboards.py`, `services/drill_down.py` |
| Ficha 360 | `services/ficha.py` |
| SCM / Monitor de SC | `services/monitor_scm.py`, `services/monitor_cruzamento.py`, `services/scm_client.py` |
| SCM Sync (API → mro.db, v5.1.0/F2) | `services/scm_sync.py` (parsers + orquestrador `sincronizar`), tabela `itens_sc_externos` |
| Constantes / tema / estilos | `services/constants.py`, `services/tema.py`, `services/styles.py` |
| Testes (regressão por versão) | `tests/test_vXXX_*.py` |
| **Gate de verificação** | `verify.ps1`, `ruff.toml`, `.github/workflows/verify.yml` |
| Automação do harness | `.claude/hooks/`, `.claude/settings.json`, `.claude/agents/validador-mro.md` |
| Distribuição (servidor) | `deploy/`, `scripts/release.py`, `docs/INSTALACAO_SERVIDOR.md` |
| Continuidade / backlog | `docs/HANDOFF.md` (seção "STATUS ATUAL" no topo), `docs/prompt.md` |
| Changelog | `changelog/*.md` |

A camada de interface vive em **`ui/`** (regra de dependência: `ui/paginas/*` importa `ui/*` e
`services/*`; `services/*` nunca importa `ui/`).

⚠️ **Não recriar `pages/`** — é diretório mágico do Streamlit e conflita com o roteador próprio
(`ui/router.py`). Foi eliminado na F1 de propósito.

## Comandos

```powershell
python -m venv venv                                          # setup, uma vez
venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

.\verify.ps1                                     # GATE: format + lint + testes → exit 0/1
.\verify.ps1 -Rapido                             # pula o format check (loop apertado)
venv\Scripts\python.exe -m pytest -q             # só os testes (~1 min, 491)
venv\Scripts\python.exe -m streamlit run app.py  # sobe o app
python scripts/release.py                        # empacota p/ o servidor → dist/
```

Dependências têm **versão fixada**. Ao mexer em qualquer pin, rode o gate **e** abra o app.

## Critério de parada

**Nada é "pronto" sem `.\verify.ps1` retornando exit 0.** Nunca use critério subjetivo
("parece bom", "deve funcionar"). O gate roda `ruff format --check` + `ruff check` + `pytest`.

Ele **não substitui** a validação no app real (regra inviolável nº6): a suíte cobre `services/`
e `database.py`, mas `ui/` só tem o smoke de render por rota — regressão visual não aparece ali.

Quanto rigor **além** do gate, conforme o que a mudança toca:

| Mudou | Além do gate |
|---|---|
| Tela, texto, refactor local | nada |
| Cálculo, regra de negócio, Protheus/SCM | teste novo obrigatório; conferir bordas (zero, `None`, item sem consumo) e unidades (UN/CX/GL/RL/PCT/LT/RM) |
| `database.py`, migração, schema | + migração idempotente e aditiva, `_backup_db` antes, **rollback testado**, FKs preservadas |

Na dúvida entre dois níveis, use o mais alto e diga qual assumiu.

⚠️ **Armadilha de banco já paga:** `PRAGMA` não levanta exceção — `wal_checkpoint` devolve
`(busy, n, n)`. Nunca abra uma segunda conexão para checkpoint/backup com transação pendente na
primeira, e sempre confira o retorno de PRAGMAs em vez de confiar no `except`.
Ver `tests/test_v550_backup.py`.

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
- Vault Obsidian (`vault/`) **não é versionado** — está no `.gitignore` e sincroniza pelo OneDrive,
  junto com o resto da pasta. Existe no disco; o protocolo de sessão segue em `vault/CLAUDE.md`.
  Não modificar salvo pedido explícito envolvendo a apresentação/KPI mensal.
- **Nunca versionar dado operacional.** O repositório é público: export de inventário, `mro.db`,
  `.bak`, planilhas de SC e o vault ficam fora do git. O que entra no histórico não sai mais.
