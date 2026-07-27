# Plano — Grande Evolução Sistema MRO v5.x (SCM Integrado + Refatoração + Distribuição)

> Aprovado pelo usuário em 22/07/2026 ao final da entrevista completa (skill `atualizar-sistema-mro`).
> Pronto para iniciar a execução (F0/F1) em qualquer dispositivo — basta `git pull` e ler este arquivo.

## Contexto

O Sistema MRO (Streamlit + SQLite, Inventus Power) chegou à v4.10/4.11 com integração parcial ao SCM:
a API (não-oficial, anônima, `http://mansrvapp03:5715/api`) alimenta apenas uma tabela efêmera no
Monitor; **toda a persistência depende do upload diário do Excel** ("Relatório de SCs"). O usuário
quer: (1) eliminar o trabalho manual diário, (2) visibilidade completa do ciclo SC→PO, (3) UX/UI
reorganizada, (4) distribuição para os compradores (Miguel/Davi) sem instalar Python nas máquinas
deles. A API **nunca** pode ser dependência exclusiva — todo recurso precisa de fallback por
relatório.

### Decisões da entrevista (fechadas com o usuário)

1. **API vira fonte primária persistindo no `mro.db`** (mesmas tabelas, origem rastreada);
   relatórios Excel viram fallback + conciliação periódica.
2. Sincronização **manual** ("Atualizar agora"), sem job em background.
3. Histórico via API: **~6 meses**, endpoint filtrado `/solicitacaoCompras/ByUser/{usuario}/{ini}/{fim}`
   por solicitante MRO (`solicitantes_mro.incluir_mro=1`). Nunca usar endpoints amplos
   (`/Produto`, `/SolicitacaoCompras` sem filtro — já derrubaram o serviço).
4. Escopo "SC do Almoxarifado" = **por solicitante**.
5. **SCM Integrado** = página nova de CONSULTA, abaixo de Controle de SC no menu, para
   almoxarifado E compradores. 3 abas: Solicitações de Compra / Itens das SCs / Detalhes da SC.
6. **Refatoração completa por fases** do `app.py` (~4.700 linhas), testes verdes a cada fase.
7. Distribuição: **modelo servidor** no PC sempre ligado + navegador para os compradores
   (não dá para instalar Python nas máquinas deles).
8. Requisições Digitais **fora** deste escopo. Sem prazo rígido — ordem técnica ideal.
9. Telas mais usadas (não quebrar nunca): **Movimentação/Requisição** e **Inventário/Ficha 360**.

## Diagnóstico (exploração completa realizada em 22/07/2026)

- `app.py` 272KB/~4.700 linhas: menu (`:165`), router if/elif (`:2748+`), 40+ renderers `_render_*`,
  helpers de gráfico (`_barh:941`, `_donut:964`, `_barv:983`, `_linhas:1528`, `_bloco_top:1567`),
  drill-down (`:1600-1649`). Código morto: `_render_dash_gestao:755` (DEPRECADO).
- **Cache ausente**: 0 `@st.cache_data` em app.py/db_functions.py (só no scm_client).
  `listar_inventario()` roda em TODO rerun via sidebar (`app.py:194`). Principal gargalo.
- `services/db_functions.py` 192KB/117 funções; núcleo modular OK (dashboards/planejamento/ficha/
  tema puros e testados). Importação: `importar_relatorio_scs:3448` (abas SCM header 0 / SC7 header 3 /
  FORNECEDORES / SCM USERS), `ingerir_scm:3490` (upsert por `numero_sc`, COALESCE por campo,
  **descarta** itens com PN fora do inventário — `:3564`), `ingerir_sc7_precos:3709` (lead time),
  legado `importar_solicitacoes_protheus:1367`.
- `scm_client.py` (135 linhas): 7 funções GET, retry 3×/timeout 60s, cache 900s; só 3 usadas hoje
  (`cotacoes_em_andamento`, `sc_timeline`, `esta_disponivel`). API expõe muito mais
  (ByUser, Timelinev2, GetByCodigo→`numeroPedidoCompra` ponte p/ C7, Pedidos, aprovadores).
  Peculiaridades: typo `valorUnitaro`, padding Protheus (trim), datas nulas `0001-01-01`, 2 formatos
  de resposta.
- Pastas `pages/ controllers/ repositories/ models/ core/ app/ dashboards/` **vazias** (scaffolding
  nunca usado). `pages/` é diretório mágico do Streamlit — armadilha.
- Banco: migrações idempotentes em runtime em `criar_banco()` (PRAGMA table_info → ALTER ADD),
  `_backup_db(sufixo)` com wal_checkpoint. `DB_PATH="mro.db"` **relativo** (`database.py:9`) —
  problema para distribuição. `get_connection()` tem WAL, **sem** `busy_timeout` explícito
  (só `timeout=5.0` do connect).
- Testes: 303+ pytest, fixtures `db/make_item/make_sc/xlsx_factory`. EOL: produção CRLF, testes LF.
- Empacotamento: **zero** preparação existente.

## Fases (SemVer) — visão geral

| Fase | Versão | Entrega |
|---|---|---|
| F0 | — | Housekeeping git (branch nova a partir de `feat/v3.10.0-4.0.0-ux-redesign`, validar estado v4.10) |
| F1 | v5.0.0 | Fundação: `ui/` (router dict, sidebar, cache, componentes), extração de Ajuda + Configurações |
| F2 | v5.1.0 | Sincronização SCM persistente (API → mro.db) + fallback Excel intocado |
| F3 | v5.2.0 | Página **SCM Integrado** (3 abas) + componentes filtro/tabela reutilizáveis |
| F4a | v5.3.0 | Migração Saldo em Estoque, Gerenciar Itens, Dashboard, Controle de SC + cache |
| F4b | v5.4.0 | Migração Ficha 360 e Movimentação (críticas, por último) + passada UX/UI global |
| F5 | v5.5.0 | Distribuição no PC-servidor (Python embeddable + launcher, acesso via navegador) |

F2/F3 vêm antes da migração completa de páginas: a única dependência delas é o router+componentes
da F1 — valor (fim do trabalho manual diário) chega em ~metade do caminho.

## F1 — v5.0.0 · Fundação da refatoração

Estrutura alvo (elimina o scaffolding vazio; atualizar mapa do CLAUDE.md):

```
ui/
  router.py        # ROTAS: dict[str, Rota(icone, render)] — fonte única do menu
  sidebar.py       # logo, option_menu, tema (movido de app.py:153-229)
  cache.py         # wrappers @st.cache_data(ttl=120) sobre leituras + invalidar_leituras()
  formatos.py      # fmt, fmt_date_input, R$/datas PT-BR
  componentes/
    graficos.py    # _barh/_donut/_barv/_linhas/_barras_agrupadas/_bloco_top
    selecao.py     # itens_select/sel_material/opcoes_com_atual
    drill_down.py  # UI do drill-down (lógica segue em services/drill_down.py)
  paginas/
    ajuda.py configuracoes.py        # F1
    scm_integrado.py                 # F3
    saldo_estoque.py gerenciar_itens.py dashboard.py controle_sc.py  # F4a
    ficha_360.py movimentacao.py     # F4b
```

- Cada página expõe `def render() -> None`. Regra de dependência: `ui/paginas/*` importa
  `ui/componentes|cache` e `services/*`; nunca `app.py` nem outra página. `services/` nunca importa `ui/`.
- Transição sem big-bang: `app.py` mantém if/elif só para páginas não migradas;
  `if pagina in ROTAS_MIGRADAS: render_pagina(pagina)`.
- Ordem F1: (1) helpers sem estado → `ui/`; (2) router+sidebar; (3) migrar **Ajuda** (`app.py:4341`,
  quase estática); (4) migrar **Configurações** (`app.py:4462`, prova escrita+invalidação de cache);
  (5) cache na sidebar e nos call sites de `listar_inventario()`.
- **Não decorar `db_functions.py`** com cache (fica puro); camada fina em `ui/cache.py`;
  `invalidar_leituras()` (= `st.cache_data.clear()`) após TODA escrita. Converter `sqlite3.Row`→dict
  antes de cachear.
- **Manter `key=` de todos os widgets** (mudar key reseta estado e quebra AppTest).
- Novo `tests/test_v500_router.py`: smoke parametrizado por página —
  `AppTest.from_string` chamando `render_pagina("<página>")` sobre banco isolado (fixture `db`);
  vira a rede de segurança de todas as fases.
- Aproveitar para remover código morto (`_render_dash_gestao`).

## F2 — v5.1.0 · Sincronização SCM persistente

Novos endpoints em `scm_client.py` (aditivo, mesmo padrão `_get`): `sc_por_usuario(usuario, ini, fim)`
[SEM cache — é sync], `sc_timeline_v2(sc_id)`, `cotacao_por_codigo(ct)`, `aprovadores_pedido(...)`.

Novo `services/scm_sync.py` — parsers puros + upserts com `conn` + orquestrador:

- `normalizar_sc_api(payload)` / `normalizar_itens_api(payload)` — trim, datas nulas→None,
  `valorUnitaro`→preco_unitario. Testáveis com fixtures JSON reais (`tests/fixtures/scm/*.json`).
- `sincronizar(periodo_dias=180, progress_cb=None)`:
  1. `esta_disponivel()` — aborta cedo com mensagem amigável;
  2. `_backup_db('sync-api')` 1×/dia;
  3. por solicitante MRO: ByUser(hoje−180, hoje) → normaliza → upsert em **uma transação por
     solicitante** (queda no meio preserva concluídos);
  4. `registrar_log_sync` em `log_importacoes` tipo `'api_scm'` (status ok/parcial/falha);
  5. `invalidar_leituras()`.
- Dedup vs Excel (mesma `numero_sc`): **mais recente vence, por campo, sem apagar** — mesmo padrão
  COALESCE de `ingerir_scm` (`db_functions.py:3612-3625`); API autoritativa em status/datas/PO/centro
  de custo quando responde; campos só-Excel (saving, comprador, previsão NFe) preservados via COALESCE.
  Divergências (banco vs API) acumuladas em `detalhe_json` (cap ~50) → insumo da conciliação.
  Reusar `_status_sc_importado` (nunca duplicar mapeamento).
- **Itens com PN fora do inventário** (hoje descartados): nova tabela aditiva `itens_sc_externos`
  (sc_id FK CASCADE, part_number, descricao, quantidade, unidade, preco_unitario, valor_total,
  numero_po, data_necessidade, origem, data_registro, UNIQUE(sc_id, part_number)).
  `ingerir_scm` também passa a gravar ali (em vez de só ignorar). Backlog: "promover p/ inventário".
- Migração aditiva (padrão `novas_cols_*`, backup automático): `solicitacoes_compra` += `sc_id_scm`
  INTEGER, `centro_custo` TEXT, `data_sync_api` TEXT; `itens_sc` += `origem` TEXT; índices
  `idx_sc_solicitante`, `idx_sc_comprador`.
- UI provisória na aba Monitor: botão "Atualizar agora" + `st.status` com progresso por solicitante +
  "Última sincronização: …" via `ultima_sync()`.

## F3 — v5.2.0 · Página SCM Integrado

Componentes novos (nascem aqui, servem à F4):

- `ui/componentes/filtros.py` → `barra_filtros(df, chave, campos_pesquisa, filtros_rapidos,
  avancados)` — pesquisa case/acento-insensível + `st.pills` (rápidos) + expander avançados
  (período/multiselect/texto); estado em session_state por prefixo.
- `ui/componentes/tabela.py` → `tabela_paginada(df, chave, colunas_config, page_size=50,
  ordenar_padrao, on_select)` — column_config PT-BR, paginação, seleção de linha p/ navegação.
- `ui/componentes/status.py` → `badge_origem(origem, quando)`, `ponto_status_api()`
  (`esta_disponivel()` com cache ttl=60), indicador de última sync.

Novo `services/scm_consulta.py` (puro): `listar_scs_consulta()` (SCs MRO + GROUP_CONCAT de POs de
`itens_sc` ∪ `itens_sc_externos`, DESC por emissão), `listar_itens_consulta()` (UNION com coluna
origem), `detalhes_sc_banco(numero_sc)`, `detalhes_sc_api(sc_id_scm)` (ao vivo: Timeline +
Timelinev2 + GetByCodigo + Pedido C7 + aprovadores — cada bloco em try/except individual, degrada
isoladamente).

`ui/paginas/scm_integrado.py` — cabeçalho (status API + última sync + "Atualizar agora") + 3 abas:
1. **Solicitações de Compra** — colunas SC · Status · Solicitante · Comprador · Centro de Custo ·
   Descrição · Justificativa · Emissão · Aprovação · Necessidade · PO(s); rápidos: Abertas/Com PO/
   Sem PO/Críticas/Últimos 30d; avançados: período, comprador, status, centro de custo. Clique →
   aba Detalhes.
2. **Itens das SCs** — por item (PN, descrição, qtd, preço, PO, status_item, origem) + filtro
   "fora do inventário MRO".
3. **Detalhes da SC** — consolidação total: cabeçalho (banco, badges de origem/frescor), itens
   (incl. externos), preços históricos, expander "Ao vivo da API" (busca só ao abrir; offline →
   aviso "exibindo apenas dados do banco").

## F4a/F4b — v5.3.0/v5.4.0 · Migração das demais páginas + UX global

- F4a: Saldo em Estoque → Gerenciar Itens → Dashboard → Controle de SC; adotar
  `barra_filtros`/`tabela_paginada` onde couber; cache nos assemblers de dashboards.
- F4b (sequencial, 1 commit por página, semana de observação entre elas): **Ficha 360**, estabiliza,
  depois **Movimentação**. Passada global de UX (cabeçalhos, estados vazios, mensagens padronizadas).
  `app.py` final = shell (~150-300 linhas).
- Rollback por página = restaurar o bloco elif do commit anterior.

## F5 — v5.5.0 · Distribuição (recomendação: servidor + Python embeddable)

- `C:\MRO\runtime\` (Python 3.12 embeddable + deps via `pip --target`) · `C:\MRO\app\` (código) ·
  `C:\MRO\dados\mro.db` + `backups\` (fora da pasta do app) · `iniciar_mro.bat`
  (`runtime\python.exe -m streamlit run app\app.py`).
- Código: `DB_PATH = os.environ.get("MRO_DB_PATH", <absoluto ao lado do database.py>)`;
  `_backup_db` grava em `dirname(DB_PATH)/backups/`; adicionar `PRAGMA busy_timeout=5000` em
  `get_connection()`; config produção `.streamlit/config.toml` (headless, 0.0.0.0:8501).
- Auto-start: Agendador de Tarefas ("Ao iniciar o computador", reinício em falha) + firewall TCP 8501.
- Compradores: `http://<pc>:8501` no navegador — zero instalação.
- Atualização: `atualizar_mro.bat` (para tarefa → backup → troca `app\` → religa) +
  `scripts/release.py` (zip da release). Doc `docs/INSTALACAO_SERVIDOR.md`.
- Alternativas descartadas (documentar no plano ao usuário): PyInstaller do app inteiro (frágil a
  cada release — no máximo no launcher), streamlit-desktop-app/pywebview (não atende acesso em rede),
  briefcase (overhead), stlite (sem SQLite), exe por usuário com bancos separados (fragmenta dado).
  TI hospedar = ideal futuro; migração trivial (copiar `C:\MRO\`).
- **v5.8.0 executou a ressalva "no máximo no launcher".** `deploy/launcher.py` → `MRO.exe`
  congela só o launcher (stdlib pura, ~180 linhas); o Streamlit continua sendo executado pelo
  Python do `runtime\`, então o exe **não** precisa ser refeito a cada release — só `app\` muda.
  `scripts/portatil.py` entrega o `C:\MRO\` inteiro montado (~148 MB zipado), o que elimina os 7
  passos manuais sem trocar o modelo de servidor único. As demais alternativas seguem descartadas.

## Riscos e mitigação

1. **API não-oficial quebra/é bloqueada** — importador Excel intocado (fallback permanente);
   padrão "banco primeiro, API enriquece"; gate `esta_disponivel()`; sync por solicitante (endpoints
   filtrados). Nenhuma tela depende de chamada viva.
2. **Regressão Movimentação/Ficha 360** — migram por último, smoke parametrizado por página,
   semana de observação.
3. **EOL** — produção CRLF, testes LF; revisar diffs (nenhuma conversão de arquivo inteiro).
4. **Multiusuário SQLite** — WAL + busy_timeout 5000, escritas curtas via `transaction()`.
5. **Schema** — só mudanças aditivas com `_backup_db`; código antigo roda sobre schema novo
   (rollback de app sem rollback de banco).
6. **Cache velho pós-escrita** — `invalidar_leituras()` em todo caminho de escrita + TTL 120s.
7. **`pages/` mágico do Streamlit** — eliminado na F1.

## Validação (gate de cada fase)

- `pytest` completo verde (303+ + novos por fase) + smoke `test_v500_router.py`.
- Validação manual no app real (foco Movimentação/Ficha 360 mesmo quando não tocadas).
- F2: sync real contra API popula clone do banco de produção; re-import do Excel do dia seguinte
  não duplica nem regride; sync com API desligada falha graciosamente.
- F3: 3 abas operam com API ligada E desligada; volume real com paginação OK.
- F5: reboot-test no PC-servidor; acesso de outra máquina; ensaio de backup/restore e de atualização.
- Commit somente após OK explícito do usuário no app real (regra do projeto). Changelog
  `changelog/5.Y.0.md` + `graphify update .` + HANDOFF "STATUS ATUAL" a cada fase.

## Arquivos críticos

- `sistema-mro/app.py` (encolhe a cada fase)
- `sistema-mro/services/db_functions.py` (`ingerir_scm:3490`, `importar_relatorio_scs:3448`)
- `sistema-mro/database.py` (migrações aditivas, DB_PATH, busy_timeout)
- `sistema-mro/services/scm_client.py` (+4 endpoints)
- novos: `ui/**`, `services/scm_sync.py`, `services/scm_consulta.py`, `tests/test_v5*`

## Próximo passo imediato (para retomar em qualquer PC)

Iniciar **F0** (branch `feat/v5.0.0` a partir de `feat/v3.10.0-4.0.0-ux-redesign`) e **F1**
(criação do pacote `ui/`, router, extração de Ajuda + Configurações). Nenhum código de produto foi
alterado ainda — só planejamento e organização de contexto (este arquivo + `docs/HANDOFF.md`).
