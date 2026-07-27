# Handoff de Sessão — Sistema MRO (para continuar em outra sessão)

> Cole/`@`-referencie este arquivo no início da próxima sessão — funciona em **qualquer dispositivo**,
> porque viaja com o `git pull` (ao contrário da memória local do Claude, que fica presa à máquina
> onde a sessão rodou).

---

## STATUS ATUAL — atualizado em 27/07/2026 (leia isto, não a seção 1-7 abaixo para status)

- **v5.8.0 IMPLEMENTADA, gate verde (638 testes, 604 → +34), PENDENTE de validação no app
  real.** Duas entregas independentes, ambas atacando "coisa que só o autor consegue fazer".
  Ver `changelog/5.8.0.md`. **4 checkpoints, ainda NÃO commitados.**
  - **CP1 — Backup sob demanda.** `services/backup.py` (novo) + bloco *Backup do Banco* em
    Configurações: botão, **pasta de destino configurável** e **download pelo navegador** (o
    único jeito de quem usa pela rede tirar cópia do servidor). Não reimplementa nada:
    chama `database._backup_db`, que já trata a armadilha do `wal_checkpoint`.
    **Regra de projeto:** falha no destino extra **não** invalida o `.bak` principal — ele já
    está em disco quando a cópia é tentada. Pendrive desconectado → `erro_destino` com
    `ok=True`.
  - **CP2/CP3 — Pacote portátil.** `scripts/portatil.py` → `dist/mro-portatil-5.8.0.zip`
    (**148 MB** zipado / 440 MB extraído). Extrair e dar dois cliques no `MRO.exe`; os 7
    passos manuais do `INSTALACAO_SERVIDOR.md` viraram um comando na máquina de dev.
    `deploy/launcher.py` **só importa stdlib** — o PyInstaller congela ~180 linhas triviais,
    não o grafo do Streamlit, então **o exe não é refeito a cada release**. O `app\` do
    portátil vem de `release.itens_do_pacote()`, não de uma segunda lista.
  - **CP4** — `deploy/instalar_servidor.ps1` (tarefa agendada + firewall, idempotente,
    auto-eleva) + guarda no `atualizar_mro.bat` + docs.
  - ⚠️ **Migração de SCHEMA:** tabela `configuracoes (chave, valor)`, `CREATE TABLE IF NOT
    EXISTS` em `criar_banco()` — aditiva pura, mesmo padrão das outras 21, sem `_migrar()` e
    sem `_backup_db`. **Ainda não rodou no `mro.db` de produção.**
  - **Três achados que valem memória** (todos medidos, todos travados por teste):
    1. **O Python embeddable IGNORA `PYTHONPATH`** — o `python*._pth` substitui a busca de
       caminhos. O `set "PYTHONPATH=..."` do `iniciar_mro.bat` **sempre foi inócuo**;
       funcionava porque `Lib\site-packages` está no `._pth` e porque o `streamlit run`
       insere sozinho a pasta do script. Se `import streamlit` falhar no servidor, **é no
       `._pth` que se olha**, não na variável.
    2. **O runtime embutido enxergava os pacotes GLOBAIS da máquina** —
       `%APPDATA%\Python\Python314\site-packages` entrava no `sys.path` com `import site`
       habilitado. O pacote deixava de ser auto-contido: funciona na máquina do dev, quebra
       na limpa. Corrigido com **`-s`** no launcher e no `.bat`.
    3. **Subir o servidor NÃO cria o banco** — o Streamlit só executa `app.py` quando uma
       sessão de navegador conecta. `/_stcore/health` responde 200 com `dados\` vazio. Em
       qualquer roteiro de validação, **a prova é o `.bak` em `backups\`, não o HTTP 200.**
  - **Débito assumido por decisão do Luis:** sem listagem/exclusão de `.bak` na tela e sem
    retenção automática. Nada apaga backup, e o botão manual acelera o acúmulo.
  - **Validação no app real: PENDENTE.** Roteiro: (a) botão de backup com destino válido,
    destino apagado e download; (b) `MRO.exe` na 8501 em máquina limpa, incluindo fechar a
    janela e conferir que nenhum `python.exe` sobrou; (c) `atualizar_mro.bat` com o exe
    aberto tem que **abortar**; (d) reboot-test depois do `instalar_servidor.ps1`.
- **v5.7.0 CONCLUÍDA** — os itens **7, 8 e 9** do pedido de 26/07/2026 (os três que a v5.6.0
  deixou para a entrevista) **mais o achado nº1** daquela versão. Gate verde: **604 testes**
  (532 → +72). Ver `changelog/5.7.0.md`. **4 checkpoints, 1 commit cada:**
  - **CP1 `ca0b997`** — o MRO passa a ser a **fonte de verdade do recebimento**. `itens_sc.
    quantidade_recebida` era sobrescrita pela "Qtd.Entregue" do Protheus a cada import **e** a
    cada edição manual: um parcial de 4 conferido na doca era apagado na reimportação e o pendente
    saltava de volta. Import e API viram leitura; o número do ERP vai para
    `quantidade_recebida_protheus`, exibido lado a lado.
  - **CP2 `9927938`** — `adicionar_itens_requisicao` **nunca recalculou o status**. O bug e o
    pedido foram no mesmo commit porque um sem o outro é o defeito: liberar a guarda sem recalcular
    deixaria o item novo órfão numa requisição `Entregue`, fora da fila e não entregável. Requisição
    entregue agora **reabre como Parcial**. + as visões Almoxarife × Solicitante (⚠️ a do
    Solicitante é **simulação**, não controle de acesso — o MRO não tem login).
  - **CP3 `3626713`** — **Requisição Padrão volta a existir** ao lado da Digital, como default.
    ⚠️ A **decisão nº2 substituiu** a regra antiga do `prompt.md` (*"recusa e avisa qual item"*):
    falta de saldo **não recusa** o pedido, grava o que tem e manda o pendente para a fila.
    `_inserir_requisicao` e `_baixar_item_requisicao` foram **extraídos antes de criar** — os dois
    fluxos gravam o **mesmo ledger**, senão o relatório do CP4 veria duas formas de saída.
  - **CP4 `8f95b12`** — **Relatório de Movimentações**. Teto de 5.000 linhas removido (cortava as
    **mais antigas** em silêncio, porque o ledger vem em ordem descendente; ~6 meses até começar a
    apagar histórico), filtro de período e a Observação explodida em colunas: **8 → 17**. A
    Observação virou o **resíduo** e caiu de ~100% para **29,3%** de preenchimento no banco real.
    **Regra: a FK manda, o texto é fallback do legado** — há linha cuja Observação é `F61846` (o
    **PO**) e cujo `documento_nf` é `169357`.
  - **Os três caminhos de ajuste deixaram de se confundir** (decisão nº7): `Ajuste de Inventário`
    (569 linhas), `Ajuste por Edição`, `Ajuste Manual` (30) — antes tudo caía em "Entrada"/"Saída".
    Como **`motivo` está 0% preenchido** nas 2.822 linhas do histórico, a derivação do legado se
    apoia no **centro de custo**: os templates de texto da tela de Inventário mudaram **cinco
    vezes**, o CC nunca mudou. **Se precisar classificar movimentação legada, é no CC que se olha.**
  - **Validação no app real:** CP2, CP3 e CP4 ✅ (Luis). **CP1 segue PENDENTE** — depende do
    Relatório de SCs, que o Luis ainda não tem; a regra foi ensaiada contra cópia do `mro.db` real
    (SC 41494 / PN 29TP0086). Refazer o roteiro do CP1 quando o arquivo chegar.
  - ⚠️ **Migração de SCHEMA:** duas colunas aditivas e nullable, sem backfill
    (`itens_sc.quantidade_recebida_protheus` e `requisicoes.tipo_fluxo`). **Ainda não rodaram no
    `mro.db` de produção** — executam sozinhas no primeiro render e gravam o `.bak` em `backups/`.
- **v5.6.0 CONCLUÍDA e validada pelo Luis no app real** — 6 ajustes pontuais pedidos pela operação.
  Gate verde: **532 testes** (491 → +41). Ver `changelog/5.6.0.md`. Três diagnósticos valem memória:
  - **O recebimento parcial por SC/PO não quebrou por código do MRO.** O Streamlit 1.60.0 mudou a
    identidade do `data_editor` com `key` + `num_rows="fixed"` para a **assinatura do schema**, não
    os valores ("This keeps edits alive across pure value changes"). A quantidade digitada era
    reaplicada sobre o pendente já atualizado. Só o parcial quebrou porque no total o item sai da
    lista, o nº de linhas muda e a assinatura muda junto. Corrigido com chave versionada
    (`ui/componentes/tabela.chave_editor`). **Se aparecer bug parecido em qualquer `data_editor` com
    `key`, é aqui que se olha primeiro.**
  - **Centro de Custo nunca foi importado:** a planilha sempre teve a coluna, `ingerir_scm` nunca a
    mapeou (228 SCs, 0 com CC). Corrigido; falta **reimportar o Relatório de SCs** para preencher.
  - **O indicador da API era incapaz de ficar vermelho** — estava depois do `return` do caso offline.
  - **Migração de dados** (backfill `itens_sc.origem` → `'excel'`): ensaiada numa cópia do banco real
    (658 itens, 0,13s, integridade/FK ok, backup íntegro) e **rollback testado** nos dois caminhos.
    Roda sozinha no próximo boot do app.
- **⚠️ A BRANCH DE TRABALHO É `feat/v5.0.0`, NÃO a `main`.** Decisão do Luis em 26/07/2026:
  seguir na feature branch, **sem** abrir PR para a `main` por enquanto. A `main` está parada em
  **v4.5.5** (`21fc73e`, 16/07) e já são 40+ commits de diferença — quem clonar o repositório cai
  nela e vê um sistema três versões atrás (foi exatamente o que aconteceu com o outro PC do Luis).
  **Primeiro comando de qualquer sessão: `git fetch --all --prune` e `git checkout feat/v5.0.0`.**
  A promoção para a `main` fica pendente, para quando a v5.x fechar.
- **Auditoria do repositório (v5.5.1) CONCLUÍDA, PUSHADA e com CI verde** (`a383c1c`). 7 commits,
  **219 → 178 arquivos rastreados**, −2.121 linhas líquidas, **sem mudança de comportamento** (491
  testes do início ao fim). Saíram: 9 diretórios de scaffolding vazio, 8 docs de governança
  obsoletos, `LEIA-ME.md`, o Blueprint rev.1 corrompido e o `.claudeignore`; o export de inventário
  e o `vault/` foram destrackeados (`--cached`, seguem no disco). README reescrito 474 → 76 linhas
  e `docs/FUNCIONALIDADES.md` criado com o conteúdo de produto que valia. Corrigido de quebra o
  `scripts/release.py`, que empacotava `migrations/` para o servidor. Ver `changelog/5.5.1.md`.
- **Branches locais sobrando** (nenhuma apagada sem ordem): `chore/harness-v5` está **inteiramente
  contida** na `feat/v5.0.0` (segura de apagar, local e remota); `chore/harness-engineering` (7
  commits) e `fix/backup-wal-checkpoint` (2 commits) são o harness e o fix do WAL construídos sobre
  a `main` obsoleta — **o conteúdo das duas já foi refeito na v5.x**, só existem localmente.
- **Evolução v5.x — F4b (v5.4.0) CONCLUÍDA, COMMITADA e PUSHADA na `feat/v5.0.0`.**
  Migração das 2 páginas críticas (as últimas inline) para `ui/paginas/`, **1 commit por página**, cada
  um validado no app real (Luis): **CP1 Ficha 360** (`56a2c80` — read-only; removido o morto
  `_render_ficha_guarda_chuva`) e **CP2 Movimentação** (`de92388` — a que mais escreve estoque; extraída
  byte-a-byte + **`invalidar_leituras()` nas 8 escritas**, corrigindo o cache velho do saldo pós-baixa —
  agora sidebar/Saldo refrescam na hora). O **CP3 (fechamento)** faz o bump de rótulos 5.3.0 → 5.4.0
  (page_config/sidebar/log do banco) + `changelog/5.4.0.md` + este HANDOFF + `graphify update .`. Com
  isso `app.py` vira **SHELL de 44 linhas** (só setup + sidebar + `render_pagina`): **`ROTAS_MIGRADAS ==
  ROTAS`**, fim do if/elif, **9/9 rotas em `ui/paginas/`**. **app.py: 1.383 → 44 (−97%); ao longo de toda
  a v5.x: 4.588 → 44.** **Sem migração de schema.** Testes: **500 verdes** + smoke AppTest das páginas +
  pyflakes limpo. Monitor já estava padronizado (aviso "SCM Integrado" no lugar desde a F3/F4a). **Passada
  global de UX ADIADA** (decisão Luis): adotar `barra_filtros`/`tabela_paginada` nas tabelas de migração
  pura da F4a vira fase própria, página a página com validação — não re-tocar telas estáveis no
  fechamento. Ver `changelog/5.4.0.md`. Os **3 commits da F4b** (CP1 `56a2c80` / CP2 `de92388` +
  fechamento) estão no `origin/feat/v5.0.0`.
- **Evolução v5.x — F4a (v5.3.0) CONCLUÍDA e no remoto.** Migração das 4 páginas grandes ainda
  inline para `ui/paginas/`, em 4 checkpoints na branch `feat/v5.0.0` (todos pushados):
  **CP1 Saldo em Estoque** (`fc0d314`), **CP2 Gerenciar Itens** (`528b60d`), **CP3 Dashboard**
  (`753bf14`, + extrai `ui/componentes/graficos.py`) com **fix do import `fmt`** (`bbf3190` — o
  Dashboard referenciava `fmt` sem importar; só estourava com Relatório de SCs importado) e a nova
  **guarda estática `tests/test_v530_lint_imports.py`** (pyflakes sobre `app.py` + `ui/**`, falha só
  em `UndefinedName`; `pyflakes` em `requirements-dev.txt`) — *aposentada em 25/07 pelo `ruff check`
  com `F`, que cobre o mesmo `F821` no repo inteiro; cumpriu o papel: as ~4.500 linhas migradas
  chegaram ao primeiro lint com zero nomes indefinidos*, **CP4 Controle de SC** (`db765cb` — a
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
- **F5 (v5.5.0) — distribuição.** Parte 1/3 no commit `0e510bb` (`DB_PATH` por env/absoluto,
  `busy_timeout=5000`, `deploy/config-servidor.toml`, rótulos 5.5.0). Partes 2/3 e 3/3 fecham a fase:
  `_backup_db` grava em `backups/` ao lado do banco (via `database.diretorio_backups()`), com
  `services/scm_sync.py::_backup_1x_dia` ajustado para varrer o diretório novo; `ui/sidebar.py` passa a
  resolver o logo por caminho **absoluto** (com cwd do servidor o relativo quebrava);
  `deploy/iniciar_mro.bat` + `deploy/atualizar_mro.bat`; `scripts/release.py` (inclusão explícita —
  nunca empacota `.db`/`vault/`); `docs/INSTALACAO_SERVIDOR.md`; `changelog/5.5.0.md`.
  **🐛 Defeito corrigido no caminho:** o backup pré-migração rodava `wal_checkpoint(TRUNCATE)` numa
  segunda conexão com a transação da primeira **ainda aberta** → esperava o busy_timeout inteiro e
  devolvia `SQLITE_BUSY`. Como `PRAGMA` **não levanta exceção**, o BUSY vinha como valor de retorno,
  o `except` nunca via nada e o `.bak` era gravado **sem o WAL**, logo antes de migração destrutiva
  (idem `req-status-v470`, que precede o UPDATE das requisições legadas). Corrigido com `conn.commit()`
  antes dos dois backups + checagem do retorno do checkpoint. **Suíte: ~47 min → ~58 s.**
  Testes: `tests/test_v550_backup.py` e `tests/test_v550_release.py` (7 cada); **515 verdes, 2 skipped**.
  ⚠️ **Validação física pendente (Luis):** reboot-test no PC-servidor, acesso de outra máquina, ensaio
  de backup/restore e de atualização. `drill_down.py` **não** foi extraído (F4b): a UI do drill-down tem
  1 só consumidor (Dashboard) — YAGNI; reabrir se surgir 2º.
  **Backlog paralelo (ADIADO da F4b, decisão Luis):** passada global de UX — adotar
  `barra_filtros`/`tabela_paginada` nas tabelas de migração pura da F4a + estados vazios/cabeçalhos
  padronizados, **página a página com validação** (nunca em bloco).
- **v5.5.1 — auditoria e limpeza do repositório. CONCLUÍDA.** 219 → 178 arquivos rastreados,
  −2.121 linhas, **sem mudança de comportamento** (491 testes do início ao fim). Saíram: 9 pastas
  de scaffolding vazio, 8 docs de governança que contradiziam o estado atual, o Blueprint rev.1
  corrompido, o `LEIA-ME.md` (duplicata do README) e o `.claudeignore` (nome legado).
  **Dado operacional destrackeado** (segue no disco): export do inventário e `vault/` — este
  havia sido escrito sob a premissa documentada de ser gitignored, premissa revertida depois sem
  reauditar o conteúdo (colegas nomeados com cargo, valores em R$ reais, material de outro setor);
  o repo é público. ⚠️ O histórico antigo **não** foi reescrito — decisão consciente para não
  quebrar o clone da outra máquina. README reescrito (474 → 76 linhas; o antigo nunca mencionava
  `ui/`) e `docs/FUNCIONALIDADES.md` criado com o conteúdo que valia. Corrigido de quebra um
  defeito do `scripts/release.py`, que empacotava `migrations/` para o servidor.
  Ver `changelog/5.5.1.md`.
- **Harness de verificação — CONCLUÍDO e MESCLADO na `feat/v5.0.0`.** O projeto não tinha lint,
  formatador nem CI, e o `.claude/settings.json` usava chaves inventadas que o Claude Code ignora
  (nenhuma instrução de sessão jamais chegou ao modelo). Entregue: `ruff` (ruleset em rampa
  `E9`,`F`), **`.\verify.ps1` como critério de parada objetivo**, hooks reais (formata o `.py`
  editado; bloqueia o fim do turno com a suíte quebrada), CI em `.github/workflows/verify.yml`
  rodando em toda branch, e o subagente `validador-mro` usando o **exit code** do gate como
  veredito. Removida a governança legada das 9 personas, que contradizia o `CLAUDE.md`, junto com
  os dois guardas que exigiam aquelas pastas. Primeiro CI verde em 25/07.
  **⚠️ Os hooks só carregam ao reiniciar o Claude Code** — `settings.json` é lido no início da sessão.

- **🎯 PRÓXIMO — passada global de UX** (adiada da F4b, decisão do Luis): adotar
  `barra_filtros`/`tabela_paginada` nas tabelas que a F4a migrou cruas, **página a página com
  validação**, nunca em bloco. Levantamento feito: `saldo_estoque` e `scm_integrado` já adotaram;
  `controle_sc` (11 tabelas cruas, a maior página) e `dashboard` são os alvos da F4a;
  `movimentacao` fica por último (é a que mais escreve estoque). Atenção: dois casos são
  `st.data_editor` (grade editável) e **não** convertem — `tabela_paginada` é somente-leitura.
  O ganho maior não é paginar, é padronizar estado vazio e cabeçalhos (`page_size=0` desliga a
  paginação e mantém o resto).

  Também em aberto, dependendo de estar na empresa: validar os **códigos de status da API SCM**
  (`01/03/05/09` são inferidos, nunca confirmados com dado real — o comprador pode estar vendo
  status errado) e a **validação física da F5** (reboot-test, acesso de outra máquina,
  backup/restore).
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
API→banco, refatoração faseada do app.py, distribuição via servidor). F1 (v5.0.0) a F4b (v5.4.0)
estão COMMITADAS e PUSHADAS na branch feat/v5.0.0 (Ficha 360 56a2c80, Movimentação de92388 e o
commit de fechamento). A refatoração de
páginas ACABOU: app.py é um SHELL de 44 linhas, 9/9 páginas vivem em ui/paginas/ (ROTAS_MIGRADAS ==
ROTAS), 500 testes verdes. Trabalhe na branch feat/v5.0.0 (git pull antes). Próximo passo do plano:
F5 (v5.5.0) — distribuição no PC-servidor (Python embeddable + launcher .bat, navegador para
Miguel/Davi, DB_PATH absoluto/env, busy_timeout, config headless, Agendador+firewall, doc
INSTALACAO_SERVIDOR.md). Backlog paralelo adiado da F4b (decisão Luis): passada global de UX
(barra_filtros/tabela_paginada nas tabelas de migração pura da F4a), página a página com validação.
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

### 0.2 Critério de parada — `.\verify.ps1`
**Nada é "pronto" sem `.\verify.ps1` retornando exit 0** (`ruff format --check` + `ruff check` + `pytest`, ~1 min). Nunca usar critério subjetivo. O gate **não** substitui a validação no app real (regra inviolável nº6): a suíte cobre `services/` e `database.py`, mas `ui/` só tem o smoke de render por rota. Fluxo de mudança: Skill `atualizar-sistema-mro` → subagente `validador-mro` (roda o gate) → OK do Luis no app real → commit. Ver `CLAUDE.md`.

> O antigo "fluxo das 9 skills" (PO, Supply Chain, DB, Backend, Data, UX/UI, QA, Arquitetura, DevOps) foi **descontinuado** — apontava para uma memory `project_mro_skills_framework.md` que nunca existiu e já contradizia o `CLAUDE.md` desde a reescrita dele. Os arquivos que ainda o pregavam (`MRO_QUICKSTART.md`, `.claude/pre-session.md`, `skills/`, `prompts/`, `templates/`, `config/`, `hooks/`) foram removidos.

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
- **Docs de contexto** (na raiz `docs/`, adicionados pelo usuário): `Contexto do Sistema MRO e Principal Problemática.md`, `METODOLOGIA_SCs_Explicada.md`, `Blueprint - Plataforma de Inteligencia de Materiais.md` (rev. 3). O backlog vivo é **`docs/prompt.md`**. — *Nota (25/07): a rev. 1 do Blueprint (`Blueprint Inteligência de Materiais.md`) foi removida — era um despejo truncado, sem a primeira letra do arquivo e com as tabelas achatadas em prosa, integralmente contido na rev. 3. O `Relatório de SCs 30.06.xlsx` nunca esteve no repositório.*

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
> "Continuando o Sistema MRO. Leia `@HANDOFF.md` e `@prompt.md`. Use **graphify** para navegar o código (rode `graphify update .` se estiver em outra máquina). Fluxo: Skill `atualizar-sistema-mro` + `.\verify.ps1` verde antes de qualquer commit. [Escolha: commitar a v3.3.0 / ir para o 2º lote do §3 / começar o §1 Dashboard de Comprador — e neste caso responda antes as 3 lacunas de dado da seção 4.2]."
