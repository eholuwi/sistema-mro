# Handoff de Sessão — Sistema MRO (para continuar em outra sessão)

> Cole/`@`-referencie este arquivo no início da próxima sessão — funciona em **qualquer dispositivo**,
> porque viaja com o `git pull` (ao contrário da memória local do Claude, que fica presa à máquina
> onde a sessão rodou).

---

## STATUS ATUAL — atualizado em 24/07/2026 (leia isto, não a seção 1-7 abaixo para status)

- **Evolução v5.x — F4a (v5.3.0) CONCLUÍDA e no remoto.** Migração das 4 páginas grandes ainda
  inline para `ui/paginas/`, em 4 checkpoints na branch `feat/v5.0.0` (todos pushados):
  **CP1 Saldo em Estoque** (`fc0d314`), **CP2 Gerenciar Itens** (`528b60d`), **CP3 Dashboard**
  (`753bf14`, + extrai `ui/componentes/graficos.py`) com **fix do import `fmt`** (`bbf3190` — o
  Dashboard referenciava `fmt` sem importar; só estourava com Relatório de SCs importado) e a nova
  **guarda estática `tests/test_v530_lint_imports.py`** (pyflakes sobre `app.py` + `ui/**`, falha só
  em `UndefinedName`; `pyflakes` em `requirements-dev.txt`), **CP4 Controle de SC** (`db765cb` — a
  maior página, 8 abas + 6 helpers, migração FIEL; aba Monitor mantém o aviso p/ SCM Integrado; 9
  escritas chamam `invalidar_leituras()`; morto `_dialog_pedido_guarda_chuva`/`_clear_gc_edit`
  removido). No **fechamento** (commit de refactor): limpeza dos **83 imports órfãos** do `app.py`
  (44 só do bloco `db_functions`) + `graphify update .` + esta atualização do HANDOFF. **`app.py`:
  4.063 → 1.383 linhas (−66%) ao longo da F4a**; **7/7 páginas de produto agora em `ROTAS_MIGRADAS`**
  — só **Movimentação** e **Ficha 360** seguem inline (F4b). `_render_ficha_guarda_chuva` fica no
  `app.py` (é da Ficha 360). Rótulos 5.2.0 → 5.3.0 (page_config, sidebar, log do banco). **Sem
  migração de schema.** Testes: **496 verdes** (475 + a guarda pyflakes parametrizada por módulo) +
  smoke AppTest das páginas. **Validação no app real: Dashboard ✅ (Luis) e Controle de SC ✅ (Luis,
  nesta sessão).** Ver `changelog/5.3.0.md`.
- **Evolução v5.x — F3 (v5.2.0) COMMITADA e no remoto.** Commit `3721a57` na branch `feat/v5.0.0`
  (já pushado — F1/F2/F3 todas no `origin/feat/v5.0.0`). **Validação no app real ainda pendente** (o
  Luis autorizou o commit/push com base na suíte + smoke render semeado; ainda não abriu o Streamlit
  rodando). **Página SCM Integrado** (menu, abaixo de
  Controle de SC): consulta unificada das SCs do banco (Excel E/OU API), 3 abas — **Solicitações de
  Compra** / **Itens das SCs** / **Detalhes da SC**. O botão **"Atualizar agora"** (sync API→banco)
  saiu da aba Monitor (onde era provisório na F2) e virou o **cabeçalho** desta página; a aba Monitor
  agora só tem um aviso apontando para cá. Novos: `ui/paginas/scm_integrado.py`, **pacote
  `ui/componentes/`** (`filtros.py::barra_filtros` com pesquisa acento-insensível + `st.pills` +
  avançados; `tabela.py::tabela_paginada` com seleção de linha→Detalhes; `status.py::badge_origem`/
  `ponto_status_api`), `services/scm_consulta.py` (puro: `listar_scs_consulta`/`listar_itens_consulta`/
  `detalhes_sc_banco`/`detalhes_sc_api`). `scm_client.py` **+3 endpoints** (`sc_timeline_v2`,
  `cotacao_por_codigo`, `aprovadores_pedido`) para o "ao vivo da API" da aba Detalhes (busca **sob
  demanda**, botão — `render()` é livre de rede). Migração **aditiva** (backup): `solicitacoes_compra`
  += `cotacao_codigo` (TEXT), agora persistido por `_upsert_sc_api` (já vinha de `normalizar_sc_api`).
  Testes: **novo `tests/test_v520_scm_integrado.py`** (consulta pura + `detalhes_sc_api` off/online/
  bloco-falho com cliente FALSO + funções puras de filtros/tabela + 3 endpoints; `test_v500_router`
  cobre o smoke da página nova sobre banco vazio). Ver `changelog/5.2.0.md`. ⚠️ **Códigos de status da
  API e a filial `"01"`** (usada em Pedido/aprovadores) seguem as premissas da F2 — validar no app real.
  **Recomenda-se validar no app real** (API ligada na rede Inventus, cópia do `mro.db`): 3 abas com API
  on/off, clique linha→Detalhes, "Buscar dados ao vivo", "Atualizar agora" ainda grava, Monitor sem a
  UI antiga, Movimentação/Ficha 360 intactas.
- **Evolução v5.x — F2 (v5.1.0) COMMITADA e no remoto.** Commit `c85390d` na branch `feat/v5.0.0`
  (pushado junto com a F3). Sincronização SCM persistente **API → `mro.db`**:
  botão **"Atualizar agora"** (era na aba Monitor; na F3 migrou p/ o cabeçalho da página SCM
  Integrado) puxa as SCs dos solicitantes MRO (cabeçalho via `ByUser` +
  itens via `Timeline`) e grava no banco (status/datas/centro de custo/itens/preços); **Excel vira
  fallback**, a API nunca é dependência exclusiva. Novos: `services/scm_sync.py` (parsers puros +
  orquestrador `sincronizar`, dedup COALESCE vs Excel, **nunca rebaixa status** via rank, log
  `api_scm`), endpoints `sc_por_usuario`/`usuarios` em `scm_client.py`. Migração **aditiva** (backup):
  `solicitacoes_compra` += `sc_id_scm`/`centro_custo`/`data_sync_api`; `itens_sc` += `origem`;
  `solicitantes_mro` += `codigo`; **nova `itens_sc_externos`** (itens com PN fora do inventário — antes
  descartados; agora capturados no Excel E na API). **Configurações › Solicitantes MRO (SCM)**: gerir o
  escopo (incluir/remover, código Protheus, "Resolver códigos via API"). Testes: **444 verdes**
  (baseline 431 + `tests/test_v510_scm_sync.py` + 2 no `test_scm_client.py`; `test_pn_inexistente`
  virou captura em externos) + smoke `test_v500_router.py`; smoke E2E manual (Controle de SC +
  Configurações) OK. Ver `changelog/5.1.0.md`. **Recomenda-se ainda validar no app real** (com a API
  acessível na rede Inventus): sync contra **cópia** do `mro.db` (SCs/itens populam), re-import do
  Excel do dia seguinte (não duplica/regride), sync com API off (falha graciosa), Movimentação/Ficha
  360 intactas — nenhum bloqueador identificado até aqui, mas ainda não testado fora de fixtures/mocks.
  ⚠️ **Códigos de status da API (`01/03/05/09`) são inferidos** (§7.13 da doc SCM) — o código cru fica
  em `status_protheus`; ajustar `_STATUS_SC_API` em `scm_sync.py` se o dado real divergir. Códigos dos
  solicitantes atuais (Luis/Jasiva/Sidinei/Juan) são resolvidos por nome via `/Usuario` no 1º sync (ou
  à mão em Configurações).
- **Evolução v5.x — F1 (v5.0.0) COMMITADA e no remoto.** Commit `ba01f61` na branch
  `feat/v5.0.0` (de `feat/v3.10.0-4.0.0-ux-redesign`; já com `git push -u origin feat/v5.0.0`). F1 = fundação da
  refatoração: novo pacote **`ui/`** — `router.py` (fonte única do menu: `ROTAS`,
  `ROTAS_MIGRADAS`, `render_pagina`), `sidebar.py`, `tema.py`, `formatos.py`, `cache.py` — e as
  páginas **Ajuda** e **Configurações** migradas para `ui/paginas/` com `render()`. O `app.py`
  vira shell + páginas ainda inline: `if pagina in ROTAS_MIGRADAS: render_pagina(pagina)`; o
  resto segue no if/elif (transição sem big-bang). `app.py`: **4.588 → 4.058 linhas** (removidos
  blocos inline migrados, `def tema_atual`/`fmt`/`fmt_date_input`, consts de feedback e o morto
  `_render_dash_gestao`). **Sem migração de schema; comportamento idêntico** ao da v4.10.0.
  Testes: **431 verdes** (426 baseline + `tests/test_v500_router.py`, smoke parametrizado por
  `ROTAS_MIGRADAS` via AppTest); smoke E2E do app inteiro (cópia do `mro.db`, `option_menu`/rede
  SCM stubados) **OK nas 8 páginas**. Ver `changelog/5.0.0.md`. Decisões de fundação:
  cache criado como infraestrutura com **ativação progressiva** (só as escritas de Configurações
  chamam `invalidar_leituras()`; a sidebar segue leitura direta p/ não arriscar métrica velha);
  `ui/componentes/` (graficos/selecao/drill_down) **adiados p/ F4** (usados só pelos `_render_*`
  inline — mover antes seria churn sem ganho). Validação manual no app real recomendada antes de seguir p/ a F2.
- **🎯 PRÓXIMO — F4b (v5.4.0):** `docs/PLANO_V5_EVOLUCAO.md`. Migrar **Movimentação** e **Ficha 360**
  (as duas críticas, por último, **1 commit por página**) para `ui/paginas/`, extrair
  `ui/componentes/drill_down.py` e **padronizar o Monitor** (o aviso "SCM Integrado" fica) + passada
  global de UX — adotar `barra_filtros`/`tabela_paginada` nas tabelas que ficaram como migração pura
  na F4a. Depois **F5 (v5.5.0)** distribuição no PC-servidor (Python embeddable + navegador).
- **Versão anterior: v4.7.0 — Requisição Digital (MVP).** Implementada e testada em
  `feat/v3.10.0-4.0.0-ux-redesign`; **aguardando commit** (o commit é feito só após o OK do Luis +
  validação no app real, regra do projeto). A **Requisição** ganhou **ciclo de vida**:
  `Aberta → Parcial → Entregue` (+ `Cancelada`). A **criação NÃO baixa estoque** — o pedido vai para
  uma **Fila / Separação** (nova aba em Movimentação → Requisição) e a **baixa acontece só na
  ENTREGA**, item a item, permitindo **parcial e em lote** (o jeito do Juan). Autorização (gestor;
  +**checkbox "Material SESMT?"** → responsável do SESMT) é registrada **na entrega**. Dá para
  **adicionar itens** a um pedido aberto (o caso "escreve no mesmo papel") e **cancelar** (só Aberta).
  Migração **aditiva** `requisicoes.status` (backfill legado → `Entregue`, com backup). Serviços novos
  em `db_functions.py`: `entregar_requisicao`, `adicionar_itens_requisicao`, `remover_item_requisicao`,
  `cancelar_requisicao`, `listar_requisicoes_abertas`. Testes: `test_requisicao.py` reescrito + novo
  `test_v470_requisicao_digital.py`.
- **Base (v4.6.0, já commitada `d7a49e1`):** Monitor de SC 2.0 — cruzamento SCM×SC7 crus + Planilha
  livre "criar coluna".
- **Pendente da v4.6.0 (não bloqueia a v4.7.0):** validar no app real o join SCM×SC7 com um
  `Solicitações.xlsx` real do mesmo período do `Relatório de Compras.xlsx`. Só depois a v4.6.0 é 100%.
- **Próximo (após a v4.7.0):** evoluir a Requisição Digital para **website self-service + login**
  (hoje só o almoxarife opera); aprovação assíncrona real do gestor; tratar **material não cadastrado**.
- **Backlog vivo:** `docs/prompt.md` (o antigo `prompt.md` da raiz foi movido para cá).
- **⚠️ Lição multi-dispositivo (git):** um clone antigo (notebook do trabalho) tinha
  `remote.origin.fetch` restrito (fetch de um único branch) — `git fetch`/`git pull` nunca traziam
  branches novos, mesmo com o remote certo. Sintoma: `git checkout <branch>` dá
  `pathspec did not match any file(s)` mesmo após `git fetch origin`. Fix permanente (uma vez, por
  clone/máquina):
  ```
  git config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
  git fetch origin
  ```
  Se o `checkout` reclamar de mudanças locais não commitadas, **não descartar sem olhar**:
  `git stash -u` (reversível) antes de trocar de branch.
- **Config recomendada para retomar** (heurística do projeto: feature grande/nova com
  plano+aprovação → Opus, sem fast, Plan mode): **Opus 4.8** (`claude-opus-4-8`) · **fast DESLIGADO**
  · **Plan mode**.

**Prompt pronto para colar na próxima sessão (qualquer dispositivo):**
```
Continuar o Sistema MRO (Inventus Power). Leia @docs/HANDOFF.md (seção "STATUS ATUAL" no topo) e
@docs/PLANO_V5_EVOLUCAO.md — plano da grande evolução v5.x já aprovado (SCM Integrado com sync
API→banco, refatoração faseada do app.py, distribuição via servidor). F1 (v5.0.0) a F4a (v5.3.0)
estão COMMITADAS e PUSHADAS na branch feat/v5.0.0 — 7/7 páginas de produto já vivem em ui/paginas/;
só Movimentação e Ficha 360 seguem inline no app.py (1.383 linhas, 496 testes verdes). Trabalhe na
branch feat/v5.0.0 (git pull antes). Validação no app real: Dashboard e Controle de SC OK (Luis);
F1/F2/F3 (SCM Integrado, sync API→banco) foram commitadas com base em suíte + smoke — se ainda não
abriu o Streamlit, vale confirmar a página SCM Integrado (3 abas com API on/off, clique
linha→Detalhes, "Atualizar agora" grava) e as suspeitas herdadas da F2 (códigos de status da API e a
filial "01"). Próximo passo do plano: F4b (v5.4.0) — migrar Movimentação e Ficha 360 (as duas
críticas, 1 commit por página), extrair drill_down.py e padronizar o Monitor + passada global de UX.
Siga a skill atualizar-sistema-mro, valide cada fase (pytest + smoke + app real) e PARE para
aprovação antes de cada commit.
```

---

> ℹ️ **A partir daqui (seções 0-7), o conteúdo é um SNAPSHOT HISTÓRICO gerado em 10/07/2026, ao
> final da v3.3.0.** Útil para arquitetura, convenções e "lições aprendidas" que ainda valem — mas
> o backlog/status descrito nele está **desatualizado** (muita coisa das seções 3/4 já foi entregue
> em versões posteriores). Para o estado real, use a seção **STATUS ATUAL** acima e `changelog/`.

## 0. ⚠️ LEIA PRIMEIRO — Ferramentas e regras obrigatórias

### 0.1 graphify (OBRIGATÓRIO para qualquer pergunta sobre o código)
O projeto tem um **grafo de conhecimento** em `graphify-out/` (verificado funcionando nesta sessão — 1127 nós, atualizado após a v3.3.0). **Antes de grepar/ler código à toa, use:**
```
graphify query "<pergunta>"          # subgrafo escopado (ex.: "onde é calculado o estoque de segurança")
graphify path "<A>" "<B>"            # relação entre dois símbolos
graphify explain "<conceito>"        # foco num conceito
graphify update .                    # re-indexa (AST-only, sem custo de API) — rode APÓS editar código
```
Também há tools MCP: `mcp__graphify__query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `god_nodes`, etc.
**Atenção:** `graphify-out/` é **git-ignored** (vive local, por máquina). Se abrir a próxima sessão **em outra máquina**, rode **`graphify update .`** antes de consultar. Se `graphify-out/wiki/index.md` existir, use-o para navegação ampla; leia `graphify-out/GRAPH_REPORT.md` só para arquitetura geral.

### 0.2 Fluxo das 9 Skills (CLAUDE.md) — para TODA solicitação
Entender problema → impactos/riscos → **análise das 9 skills** (PO, Supply Chain, DB, Backend, Data, UX/UI, QA, Arquitetura, DevOps) → plano → **aprovação** → implementar → validar. Detalhes na memory `project_mro_skills_framework.md`.

### 0.3 Convenção de EOL (memory `eol-convention`)
**Produção = CRLF · Testes = LF.** git usa autocrlf (index=LF, worktree=CRLF). Ao editar arquivos de produção (`app.py`, `services/*.py`, `database.py`), preservar CRLF — checar com `git ls-files --eol` / `grep -c $'\r$'` (0 linhas lone-LF = ok). `Write` gera LF (bom para testes; converter em produção se necessário).

### 0.4 Vault Obsidian (`vault/`) — só para a apresentação de KPI
`vault/CLAUDE.md` tem o protocolo. Para tarefas da apresentação mensal: ler `vault/Projects/Apresentação Inventus Power - KPI Mensal.md` + Daily Note + Session Log mais recentes; ao terminar, gerar Session Log + atualizar Daily Note. **`git pull` antes / `git push` depois** (vault sincroniza entre máquinas).

---

## 1. O projeto em 1 minuto
- **Sistema MRO** da **Inventus Power**, integrado ao **Protheus (TOTVS)**. Domínio: Almoxarifado MRO, Compras indiretas, Supply Chain. Lema: **"nunca deixar faltar material"** sem excesso.
- **Gargalo real** (docs/Contexto): a falta não vem de não solicitar, e sim do tempo entre **abrir a SC** e a **compra efetiva**. 2 compradores (**Davi** = Manutenção+Engenharias; **Miguel** = Almoxarifado/SSO/Qualidade) + estagiária (Adrya). Objetivo: entregar tudo "mastigado" ao comprador.
- **Stack:** Streamlit + SQLite (WAL, FKs on) + Plotly. Roda com `streamlit run app.py`. **Sem ORM** (sqlite3 cru + `transaction()`).
- **Arquivos-chave:**
  - `app.py` (~3,3k linhas) — router `if pagina == "..."` + toda a UI. Navegação lateral via `streamlit-option-menu`.
  - `services/db_functions.py` (~3,1k) — núcleo: inventário, SC, requisições, preços, importação, analytics.
  - `services/dashboards.py` — **assemblers PUROS** por público (padrão DT-3: monta view-model, sem Streamlit).
  - `services/planejamento.py` — reposição: ROP, `estoque_seguranca_efetivo`, prioridade, `gerar_scs_sugeridas`, `agrupar_por_tipo_material`, `resumir_grupo_sc`.
  - `services/ficha.py` — `montar_ficha_360(item_id)`. `services/classificacao.py` — SBC/XYZ. `services/constants.py` — todos os fatores/limiares.
  - `database.py` — schema + migrações **idempotentes em runtime** (`criar_banco()`; sem pasta de migrations); backup `_backup_db(sufixo)`.
  - `tests/` — **303 testes** (pytest). Fixtures em `conftest.py`: `db`, `make_item`, `registrar_consumo`, `make_sc`, `xlsx_factory`.
- **Dados:** `mro.db` (produção real, ~360 itens). **Nunca rodar smoke contra o mro.db real** — copiar para tmp e apontar `database.DB_PATH`.
- **Versionamento:** semver por branch `feat/vX.Y.Z` + `changelog/X.Y.Z.md`. Rótulo em `app.py` (page_config + sidebar) e log em `database.py`. **Agora: v3.3.0.**
- **Docs de contexto** (na raiz `docs/`, adicionados pelo usuário): `Contexto do Sistema MRO e Principal Problemática.md`, `METODOLOGIA_SCs_Explicada.md`, `Blueprint Inteligência de Materiais.md`, `Relatório de SCs 30.06.xlsx`. O backlog vivo é **`prompt.md`** (na raiz).

---

## 2. O backlog (`prompt.md`) e a estratégia acordada
- **§1 Dashboard de Comprador** (novo, *flagship*) — Painel de Prioridades é "a parte MAIS importante".
- **§2 Dashboard do Almoxarifado** — *conceito de referência* (inclui **Mapa do Almoxarifado**, que exige um modelo de localização/prateleira inexistente).
- **§3 Ajustes em telas existentes**.
- **§4 Requisições digitais** — usuário pediu para ser **entrevistado** antes.

**Decisão do usuário (perguntada e respondida):** começar por **§3 Quick Wins**, no formato **enxuto** (rápidos primeiro; médios depois). Estratégia "estabilizar, depois construir".

---

## 3. ✅ FEITO nesta sessão — v3.3.0 (Quick Wins enxuto)
Branch **`feat/v3.3.0`** — **ainda NÃO commitado** (aguardando OK do usuário).

| Item | Onde | Estado |
|---|---|---|
| **Bug estoque de segurança** ("números quebrados") | `db_functions.py` (`_recalcular_ruptura_by_pn` usa `math.ceil`; recebimento delega a `_recalcular_ruptura_by_id`, não grava mais na coluna manual) + `database.py` (limpeza idempotente + `_backup_db`) | ✅ |
| Remover Dashboard **Diretoria** | `dashboards.py` (constante, `montar_visao_diretoria`, roteador), `app.py` (`_render_dash_diretoria`), `ajuda_conteudo.py`, testes | ✅ |
| Renomear "Mensal" → **"KPI Mensal"** | `dashboards.py:PUBLICO_EXECUTIVO` | ✅ |
| "Bolinhas" (radio) → **abas** (`st.tabs`) no Dashboard | `app.py` (bloco `if pagina=="Dashboard"`) | ✅ |
| Ficha 360: **"Saldo Residual"** (sem "Guarda-Chuva") | `app.py` métrica `e5` | ✅ |
| Ficha 360: gráficos Plotly (novo helper **`_barv`**) | `app.py` (Consumo médio/dia + Consumo real/mês) | ✅ |
| Movimentações: abas **Analytics · Ajuste · Histórico**; remover "Evolução de preço" | `app.py` (Movimentações) | ✅ |
| Controle de SC → Atualizar Status: seletor **vazio** (guarda if/elif/else, **sem `st.stop()`**) | `app.py` (aba `aba_ed`) | ✅ |
| Fornecedores & Cotação: busca única por **PN/nome/descrição** | `app.py` (aba `aba_forn`) | ✅ |
| Configurações: botão **"Sincronizar do Relatório de SCs"** (nova `sincronizar_fornecedores_lista`) | `app.py` (LISTAS_CONFIG) + `db_functions.py` | ✅ |

**Verificação:** 303 testes verdes (+ novo `tests/test_v330_seguranca.py`); smoke E2E headless (AppTest sobre cópia do `mro.db`) — Dashboard com 3 abas e todas as telas renderizam sem exceção; migração confirmada em dados reais (havia valores contaminados → resetados com backup `.bak-…-fix-seguranca-v330`); EOL CRLF preservado; `graphify update .` rodado. Changelog: `changelog/3.3.0.md`.

**Arquivos tocados:** `app.py`, `database.py`, `services/db_functions.py`, `services/dashboards.py`, `services/ajuda_conteudo.py`, `tests/test_v300_dashboards.py`, `README.md`, `LEIA-ME.md` + novos `changelog/3.3.0.md`, `tests/test_v330_seguranca.py`.

---

## 4. ⏭️ PRÓXIMOS PASSOS (roadmap)

### 4.1 — 2º lote do §3 (médios) — provável v3.4.0
> Localizar os pontos exatos via `graphify query` (os nºs de linha abaixo são de ANTES da v3.3.0 e já mudaram).
- **Receber por SC** — hoje só recebe começando pelo material (`registrar_recebimento_sc`); criar fluxo que começa pela SC/PO e recebe todos os itens. (aba `aba_rec` em Controle de SC.)
- **2ª locação** na Contagem Física do Inventário — hoje só a 1ª locação (`Local (1ª Locação)`); a "2ª locação" virou o Ajuste Rápido de Movimentações. Adicionar campo de 2º local mantendo o ajuste.
- **Rework do Assistente de Reposição** — simplificar fluxo: mostrar críticos/atenção → selecionar → "Criar SC" agrupada por **Tipo do material**; tabela com estoque/mín/máx/segurança/cobertura/consumo-dia+unidade/setores; anexar print na SC; **remover "Detalhe e ação por item"**. Reusar `gerar_scs_sugeridas`/`agrupar_por_tipo_material`/`resumir_grupo_sc` (`planejamento.py`). Formato "SCs sugeridas" foi **validado** pelo usuário.
- **Requisição de Material** — deixar "mais bonita e detalhada", incl. o Histórico (já existe, mas plano/simples).

### 4.2 — §1 Dashboard de Comprador (flagship) — provável v3.5.0
Revamp do `montar_visao_comprador` + `_render_dash_comprador`. **Antes de codar, FECHAR 3 lacunas de dado (perguntar ao usuário):**
1. **Aging "Emissão → Atendimento":** hoje aging = `data_abertura → hoje`; **não há data de "atendimento" armazenada**. Definir o que é "atendimento" (PO emitido? recebido?) e capturar/derivar essa data.
2. **"Comparativo por Comprador" (Miguel/Davi):** a importação captura **Solicitante**, não o **comprador**. Verificar se o Relatório de SCs tem coluna de comprador; se sim, ingerir; se não, derivar (ex.: por departamento).
3. **"Saving":** não implementado (`savings=None`, placeholder honesto). Precisa de **fórmula/definição** de negócio.

Demais itens do §1 (ver `prompt.md`): header com **última atualização** (de `log_importacoes`) + indicador **WK** (usar **ISO week** `date.isocalendar()`, NÃO `%W` — hoje 10/07/2026 ≈ WK 28); KPIs linhas 1-2; **Painel de Prioridades** (fila por aging); distribuição de aging (5 faixas 0-7/8-15/16-30/31-60/60+); departamentos; solicitantes; fornecedores Top 10; **histograma SC→PO**; **lead time por fornecedor**; valor comprado; comparativo por comprador; saving. Novos assemblers em `dashboards.py` sobre os dados do import de SCs. Provável subdivisão.

### 4.3 — Futuro
- **§2 Dashboard do Almoxarifado** (conceito) — o **Mapa do Almoxarifado** exige modelo de localização/prateleira (não existe).
- **§4 Requisições digitais** — **entrevistar o usuário** primeiro.

---

## 5. Aprendizados técnicos (para não redescobrir)
- **Segurança:** `estoque_seguranca` (MANUAL do gestor, inteiro) vs `estoque_seguranca_calculado` (SUGESTÃO = `consumo×lead×1,5`). `estoque_seguranca_efetivo` (`planejamento.py`) **prioriza o manual**. `FATOR_ESTOQUE_SEGURANCA=1.5` (`constants.py`). O bug antigo: o recebimento gravava a sugestão fracionária **na coluna manual** → corrigido na v3.3.0 (ceil + delega a `_recalcular_ruptura_by_id`).
- **Dashboards DT-3:** assemblers puros em `dashboards.py` (`montar_visao_comprador/gestao/executiva`, `montar_dashboard`); render `_render_dash_*` em `app.py`. Helpers de gráfico em `app.py`: `_barh` (ranking horizontal), `_donut`, **`_barv`** (vertical, novo), `_bloco_top`, `_brl_compact`, `_mes_label` — todos usando `PAL` (tema) de `services/tema.py`/`styles.py`.
- **`st.tabs` é *eager*:** renderiza TODOS os corpos a cada rerun. O Dashboard agora computa os 3 view-models por load (ok p/ ferramenta interna; se pesar, cachear com `@st.cache_data`).
- **`st.stop()` NÃO pode ser usado dentro de uma aba** — mata as abas seguintes. Usar guarda `if/elif/else` (foi assim no seletor de SC).
- **Fornecedores MRO** vêm de `itens_sc.fornecedor_item` + `solicitacoes_compra.fornecedor` (34 reais), **NÃO** do `fornecedores` SA1 (~3,6k = empresa toda). `precos_historico.fornecedor` tem lixo ("1.0"/"2.0"). `_nome_fornecedor_valido` filtra (exige letra).
- **Import "Relatório de SCs":** `importar_relatorio_scs` (`db_functions.py`), abas `SCM/SC7/FORNECEDORES/SCM USERS` (header rows em `constants.py:RELATORIO_SCS_ABAS`). Captura Status, Pedido(PO), Emissão, Aprovação, Nome Fantasia, Prc Unitário, Vlr.Total.
- **Consumo real** = saída por requisição (`SAIDA_REAL_WHERE` = `tipo='saida' AND requisicao_id IS NOT NULL`) — usado por ABC, giro, consumo. Ajustes físicos NÃO entram.
- **Cálculos:** cobertura `calcular_cobertura`; consumo `_recalcular_consumo` (janelas 30/60/90); giro `calcular_giro` (via `estoque_snapshots`); ABC `obter_abc_valor`; ROP/prioridade `planejamento.py` (`calcular_ponto_reposicao`, `precisa_repor`, `classificar_prioridade`, `calcular_qtd_sugerida` alvo híbrido). Status físico Mín×1,2 (`MARGEM_ATENCAO`).
- **Smoke E2E** (padrão útil): `AppTest.from_file("app.py")` + stub `streamlit_option_menu.option_menu = lambda *a,**k: "<Página>"` para navegar + `database.DB_PATH` apontando p/ **cópia** do `mro.db`. Ver scripts (foram temporários) — recriar se precisar.
- **Recebimento (assinatura):** `F.registrar_recebimento_sc(sc_id, item_sc_id, qtd, centro_custo, solicitante, emitente, fornecedor, data, nf)`.

---

## 6. Estado do git
- Branch **`feat/v3.3.0`** (criada a partir de `main`). **Não commitado.**
- Modificados: `app.py`, `database.py`, `services/{db_functions,dashboards,ajuda_conteudo}.py`, `tests/test_v300_dashboards.py`, `README.md`, `LEIA-ME.md`. Novos: `changelog/3.3.0.md`, `tests/test_v330_seguranca.py`.
- **Untracked do usuário** (NÃO commitar sem pedir): `docs/*` (Blueprint, Contexto, METODOLOGIA, Relatório xlsx), `prompt.md`, este `HANDOFF.md`.
- Ação pendente combinada: **commitar a v3.3.0** quando o usuário autorizar (e, se for da apresentação, Session Log no vault com pull/push).

---

## 7. Prompt sugerido para abrir a próxima sessão
> "Continuando o Sistema MRO. Leia `@HANDOFF.md` e `@prompt.md`. Use **graphify** para navegar o código (rode `graphify update .` se estiver em outra máquina). Seguimos o fluxo das 9 skills. [Escolha: commitar a v3.3.0 / ir para o 2º lote do §3 / começar o §1 Dashboard de Comprador — e neste caso responda antes as 3 lacunas de dado da seção 4.2]."
