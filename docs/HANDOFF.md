# Handoff de Sessão — Sistema MRO (para continuar em outra sessão)

> Cole/`@`-referencie este arquivo no início da próxima sessão — funciona em **qualquer dispositivo**,
> porque viaja com o `git pull` (ao contrário da memória local do Claude, que fica presa à máquina
> onde a sessão rodou).

---

## STATUS ATUAL — atualizado em 23/07/2026 (leia isto, não a seção 1-7 abaixo para status)

- **Evolução v5.x — F1 (v5.0.0) IMPLEMENTADA, aguardando OK no app real + commit.** Branch
  `feat/v5.0.0` (criada a partir de `feat/v3.10.0-4.0.0-ux-redesign`). F1 = fundação da
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
  inline — mover antes seria churn sem ganho). **Ainda NÃO commitado** (regra: commit só após OK
  no app real).
- **🎯 PRÓXIMO — plano aprovado:** `docs/PLANO_V5_EVOLUCAO.md`. Depois do commit da F1: **F2
  (v5.1.0)** sincronização SCM persistente API→`mro.db` (Excel vira fallback), **F3 (v5.2.0)**
  página **SCM Integrado** (3 abas), **F4a/F4b** migração das demais páginas (Ficha 360 e
  Movimentação por último) + cache pleno, **F5 (v5.5.0)** distribuição via servidor.
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
API→banco, refatoração faseada do app.py, distribuição via servidor). F1 (v5.0.0) já implementada
na branch feat/v5.0.0 e validada (431 testes + smoke E2E das 8 páginas). Se ainda não commitada,
revise o diff e commite a F1 após meu OK; depois siga para a F2 (sincronização SCM persistente
API→banco). Siga a skill atualizar-sistema-mro, valide cada fase (pytest + smoke + app real) e
PARE para aprovação antes de cada commit.
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
