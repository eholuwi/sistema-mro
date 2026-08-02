# Plano de Implementação — v6.2.0 · Telas Self-Service (Requisitante · Gestor · Portaria)

> Documento de referência para a implementação. Quem implementar (Claude/Claude Code) segue
> este arquivo passo a passo. A fundação de usuários/login é a v6.1.0 (`cded88c`); o backlog
> vive em `docs/prompt.md` (seção "DEMANDA ABERTA — v6.2.0").
>
> **Decisões travadas em 02/08/2026 (Luis):**
> - Escopo: **3 telas novas** — Requisitante ("Minhas Requisições"), Gestor ("Aprovações do
>   Setor") e Portaria (consulta de saída). Reutilizar funções de `services/db_functions.py` e
>   blocos de `ui/paginas/movimentacao.py`; **nenhuma lógica duplicada**.
> - **Aprovação do Gestor é NÃO bloqueante**: registrar a autorização antecipada; o almoxarife
>   pode separar/entregar antes; **sem novo status**. O Luis quer testar as aprovações por setor.
> - **Portaria = consulta pública por número, sem login** (terminal compartilhado) — precisa de
>   caminho para escapar do `gate()` quando `exigir_login` estiver ligada.
> - **Setor na criação do Requisitante**: manter o `selectbox` de `listar_setores_conhecidos()`,
>   mas **pré-preenchido com o `departamento` do usuário logado** e editável.
> - **Filtro do Gestor = igualdade simples de setor** (`requisicoes.setor == usuarios.departamento`
>   do gestor), com seletor de setor para testar. Limitação aceita: o vocabulário diverge
>   (`requisicoes.setor` tem 57 valores; `usuarios.departamento` tem 19; interseção = 9) — o filtro
>   cobre o fluxo novo (setor pré-preenchido) e deixa de fora requisições legadas de setor distinto.
> - **Simulação "Visão do Solicitante"**: mantida com `exigir_login` desligada (modo legado).
>   Com login ligado, o requisitante usa a tela própria.

---

## 1. Escopo

### Dentro
1. Migração aditiva `requisicoes.aprovado_por` + `aprovado_em` (registro da aprovação do gestor).
2. `services/db_functions.py`: `aprovar_requisicao`, `buscar_requisicao_por_numero`,
   `listar_requisicoes_por_setor`.
3. `ui/auth.py`: **modo público da Portaria** (sessão `mro_portaria_publica` + botão na
   `render_login`) e `gate()` atualizado.
4. `ui/router.py`: +3 rotas; `ROTAS_POR_PAPEL` dá rota a requisitante/gestor/portaria.
5. `ui/sidebar.py`: menu do modo público (só "Portaria").
6. `ui/paginas/movimentacao.py`: `_opcoes_setor()` + `_req_bloco_identificacao(setor_padrao,
   emitente_fixo)` (refactor pequeno, retrocompatível).
7. Páginas novas `ui/paginas/requisitante.py`, `ui/paginas/gestor.py`, `ui/paginas/portaria.py`.
8. `tests/test_v620_telas_self_service.py` + ajustes no `test_v610_usuarios.py`.
9. `VERSAO = "6.2.0"`, `changelog/6.2.0.md`, `docs/HANDOFF.md` (STATUS ATUAL), `docs/prompt.md`.

### Fora
- Alterar o `CHECK` de `requisicoes.status` (nenhum status novo — decisão).
- Mexer em `entregar_requisicao`/`criar_requisicao_com_baixa`/`autorizador_*` (o fluxo de entrega
  do almoxarife não muda).
- Vincular aprovação a email/notificação/Workflow do SCM.
- Tela do Requisitante para o fluxo **Padrão** (o self-service nasce Digital: abre o pedido e o
  almoxarife dá baixa na entrega — modelo do `docs/REQUISICOES_DIGITAIS_ESTUDO.md`).

---

## 2. Arquivos tocados

| Arquivo | Ação |
|---|---|
| `database.py` | migração aditiva `aprovado_por`/`aprovado_em` em `requisicoes` + `_backup_db` (padrão v5.7.0 `tipo_fluxo`) |
| `services/db_functions.py` | +`aprovar_requisicao`, +`buscar_requisicao_por_numero`, +`listar_requisicoes_por_setor` |
| `ui/auth.py` | modo público: `SESSAO_PUBLICA`, `em_modo_publico()`, `entrar/sair_modo_publico()`, `gate()` + botão na `render_login()` |
| `ui/router.py` | +3 rotas; `ROTAS_POR_PAPEL` (requisitante/gestor/portaria ganham rota); atualizar comentário do menu |
| `ui/sidebar.py` | menu do modo público (só "Portaria") |
| `ui/paginas/movimentacao.py` | `_opcoes_setor()` novo; `_req_bloco_identificacao(setor_padrao="", emitente_fixo=None)` |
| `ui/paginas/requisitante.py` | **novo** — Minhas Requisições |
| `ui/paginas/gestor.py` | **novo** — Aprovações do Setor |
| `ui/paginas/portaria.py` | **novo** — Consulta de Saída |
| `services/constants.py` | `VERSAO = "6.2.0"` |
| `tests/test_v620_telas_self_service.py` | **novo** |
| `tests/test_v610_usuarios.py` | atualizar `test_rotas_por_papel` (almoxarife 7→10; requisitante/gestor/portaria ganham rota) |
| `changelog/6.2.0.md` | **novo** (esqueleto; preencher ao concluir) |
| `docs/HANDOFF.md` | seção STATUS ATUAL (ao concluir) |
| `docs/prompt.md` | seção "DEMANDA ABERTA — v6.2.0" (na abertura do plano) |

**Regra de dependência preservada:** `services/*` não importa `ui/`. As páginas novas importam
apenas `ui/*`, `ui/paginas/movimentacao` (blocos reutilizáveis) e `services/*`.

---

## 3. Schema — `database.py`

Migração **aditiva** no bloco de `_migrar()` (mesmo padrão da v5.7.0 `tipo_fluxo`,
`database.py:963–971` — checar `PRAGMA table_info`, backup **só** se a tabela tiver linha):

```python
# v6.2.0 — Aprovação do gestor (tela "Aprovações do Setor"). Quem e quando aprovou a
# requisição. NÃO é status (não entra no CHECK) e NÃO bloqueia separação/entrega: registra
# a autorização antecipada do fluxo self-service. NULL = ainda não aprovada.
if "aprovado_por" not in cols_req or "aprovado_em" not in cols_req:
    if conn.execute("SELECT 1 FROM requisicoes LIMIT 1").fetchone():
        conn.commit()  # ALTERs anteriores deixam transação aberta; sem commit o
        _backup_db("requisicoes-aprovacao-gestor-v620")  # wal_checkpoint devolve BUSY.
    if "aprovado_por" not in cols_req:
        conn.execute("ALTER TABLE requisicoes ADD COLUMN aprovado_por TEXT")
    if "aprovado_em" not in cols_req:
        conn.execute("ALTER TABLE requisicoes ADD COLUMN aprovado_em TEXT")
    logger.info("  ↳ Migração v6.2.0: aprovado_por/aprovado_em em requisicoes adicionadas.")
```

Notas:
- `cols_req` já existe no `_migrar()` (usado pelo `tipo_fluxo`). O guard olha as DUAS colunas e cada
  `ALTER` tem o seu `if`: o `sqlite3` não abre transação para DDL, então um crash entre os dois
  `ADD COLUMN` deixaria a primeira já commitada, e um guard só em `aprovado_por` nunca completaria
  a segunda (correção feita na implementação — a versão original deste bloco tinha `if` único).
- Aditiva, nullable, **sem backfill**: `NULL` = "gestor ainda não aprovou", que é a verdade — as
  requisições legadas não foram aprovadas por ninguém.
- Backup apenas quando há linha, idêntico ao `tipo_fluxo`; a ordem (commit → backup → ALTER) é a
  que evita o `.bak` incompleto.

---

## 4. Domínio — `services/db_functions.py`

Três funções novas, no mesmo bloco das funções de requisição (~linha 1660). Usam
`transaction()` e os mesmos formatos de retorno `(bool, ...)`/listas de dict do módulo.

```python
def aprovar_requisicao(req_id, gestor_nome) -> tuple[bool, str]
# v6.2.0 — Registra a aprovação do gestor (NÃO bloqueante). Grava aprovado_por/aprovado_em
# (aprovado_em = CURRENT_TIMESTAMP). NÃO mexe em status nem em autorizador_*: a liberação
# na entrega continua sendo do almoxarife (entregar_requisicao exige autorizador).
# - Requisição não encontrada → (False, "Requisição não encontrada.")
# - status == 'Cancelada' → (False, "Requisição Cancelada: não pode ser aprovada.")
# - já aprovada (aprovado_por NOT NULL) → (True, "Já aprovada por <quem> em <quando>.")
#   SEM sobrescrever (a 1ª aprovação vale).
# - sucesso → (True, "Requisição <numero> aprovada.")

def buscar_requisicao_por_numero(numero) -> dict | None
# v6.2.0 — Consulta da Portaria. Busca case-insensitive e TRIM no número completo
# (ex.: 'REQ-20260802-001' — aceita 'req-20260802-001' e espaços nas pontas).
# Devolve o dict da requisição com os itens anexados (via listar_itens_requisicao) e
# COUNTs (total_itens/total_atendido), no shape de listar_requisicoes. None se não achar.

def listar_requisicoes_por_setor(setor, so_abertas=True, apenas_aprovadas=False, limite=100) -> list[dict]
# v6.2.0 — Requisições de um setor para a tela do Gestor (filtro = igualdade simples,
# decisão de 02/08/2026). WHERE UPPER(TRIM(setor)) = UPPER(TRIM(?)).
# - so_abertas=True  → status IN ('Aberta','Parcial')   (fila de aprovação)
# - so_abertas=False → todos os status, exceto nada (o chamador filtra se quiser)
# - apenas_aprovadas=True → aprovado_por IS NOT NULL  |  False → IS NULL
# ORDER BY data_hora ASC (a fila do gestor, como a do almoxarife, é do mais antigo).
# Mesmo SELECT (com total_itens/total_atendido) de listar_requisicoes.
```

Contratos de borda: `aprovar_requisicao` nunca falha por setor (a guarda de setor é da tela,
não do serviço); `buscar_requisicao_por_numero` com `""`/`None` → None; `listar_requisicoes_por_setor`
com `setor` vazio → lista vazia (nega por omissão).

---

## 5. Auth — `ui/auth.py` (modo público da Portaria)

```python
SESSAO_PUBLICA = "mro_portaria_publica"

def em_modo_publico() -> bool
# st.session_state.get(SESSAO_PUBLICA) is True

def entrar_modo_publico() -> None
# st.session_state[SESSAO_PUBLICA] = True; st.rerun()

def sair_modo_publico() -> None
# st.session_state.pop(SESSAO_PUBLICA, None); st.rerun()

def gate() -> None
# if exigir_login() and not usuario_logado() and not em_modo_publico():
#     render_login(); st.stop()
```

Em `render_login()` (a tela só aparece com `exigir_login` ligada e sem sessão), adicionar um
segundo botão sob o formulário:

```
"Consulta de saída — Portaria (sem login)"  → entrar_modo_publico()
```

com `st.caption` "Consulta pública de requisições. Não é necessário login — funciona num
terminal compartilhado."

Semântica: com a flag **desligada** (padrão) `gate()` continua no-op e o modo público nem
existe na prática. Com a flag ligada, o público entra só pela Portaria e não vê menu (a sidebar
do modo público renderiza só "Portaria", ver §6). `app.py` **não muda** — `gate()` já roda antes
da sidebar.

---

## 6. Rotas e menu — `ui/router.py` + `ui/sidebar.py`

### `ui/router.py`
```python
ROTAS: dict[str, Rota] = {
    ...  # as 7 atuais, NA MESMA ORDEM (não reordenar)
    # v6.2.0 — telas self-service. Ordem = fim do menu: preserva a ordem existente
    # (o comentário "NÃO reordenar sem intenção" vale) e os 3 papéis novos têm menu de 1 item.
    "Minhas Requisições":    Rota("inbox",          requisitante.render),
    "Aprovações do Setor":   Rota("clipboard-check", gestor.render),
    "Portaria":              Rota("pass",            portaria.render),
}

ROTAS_POR_PAPEL: dict[str, frozenset[str]] = {
    "almoxarife": frozenset(ROTAS.keys()),        # admin vê tudo → agora 10 rotas
    "comprador":  frozenset({...5 atuais...}),     # inalterado
    "requisitante": frozenset({"Minhas Requisições"}),
    "gestor":       frozenset({"Aprovações do Setor"}),
    "portaria":     frozenset({"Portaria"}),
}
```

`opcoes_menu(None)` continua devolvendo **todas** as rotas (10) — contrato legado de quando a
flag está desligada; os testes que fixam a lista completa (v410/v530/v610) são atualizados para
10. Papel desconhecido continua devolvendo lista vazia (nega por omissão).

### `ui/sidebar.py`
- Se `em_modo_publico()`: menu = `["Portaria"]` (ícone de `ROTAS["Portaria"]`); bloco de perfil =
  "Portaria · consulta pública" + botão "Sair do modo público" (`sair_modo_publico`). Retorna
  `"Portaria"` como página selecionada.
- Senão: comportamento atual (`opcoes_menu(papel_atual())`), perfil com usuário logado + Sair.

---

## 7. Refactor — `ui/paginas/movimentacao.py`

Extrair a construção de opções e parametrizar o bloco 1, **sem mudar o comportamento dos dois
fluxos atuais** (a Digital/Padrão continuam passando os defaults):

```python
def _opcoes_setor(setor_padrao="") -> list[str]
# listar_setores_conhecidos(); se setor_padrao não estiver na lista, entra como PRIMEIRA
# opção (sem duplicar quando já existe). Função pura — testável. O departamento do usuário
# normalmente NÃO está nos 57 setores conhecidos (ex.: 'ENGENHARIA DE TESTES'), então ele
# aparece por cima e o usuário pode trocar (accept_new_options continua valendo).

def _req_bloco_identificacao(setor_padrao="", emitente_fixo=None)
# setor_padrao → index do selectbox cai em setor_padrao (index 0 = vazio quando vazio).
# emitente_fixo → st.text_input(value=emitente_fixo, disabled=True) (Requisitante é quem é);
# None → text_input livre como hoje.
# Devolve (req_setor, req_emit, req_cc) — mesma assinatura de retorno de sempre.
```

---

## 8. Página Requisitante — `ui/paginas/requisitante.py` (novo)

`render()` (despachada pelo router; rota só existe para `requisitante`):

1. **Sem usuário logado** (caso flag off / acesso direto): `st.info("Faça login com seu nome +
   PIN para abrir e acompanhar as suas requisições.")` e para. A simulação da Visão do Solicitante
   continua em Movimentação — não duplicar.
2. **Com usuário**: cabeçalho "Minhas Requisições" + `st.caption` explicando o fluxo Digital
   (abre o pedido → Fila → almoxarife dá baixa na entrega).
3. Abas `aba_nova, aba_minhas`:
   - **aba_nova** — criar pedido no fluxo **Digital** (reuso, sem duplicar):
     - `_req_bloco_identificacao(setor_padrao=usuario["departamento"], emitente_fixo=usuario["nome"])`;
     - `_req_bloco_materiais(PAL, ajuda_qtd)` com a ajuda da Digital;
     - sem autorizador/SESMT na criação (fica para a entrega) — igual a `_req_nova_digital`;
     - botão "CRIAR REQUISIÇÃO" → `criar_requisicao(...)` com `autorizador_tipo=""`,
       `autorizador_nome=""`, `entrega_individual=False`, `destinatarios=[]`, `sesmt=False`;
     - sucesso → `_req_tela_confirmacao(st.session_state.req_confirmada)` (mesmo recibo);
     - `invalidar_leituras()` no sucesso (a Digital não escreve estoque, mas o padrão da UI é
       invalidar após escrita).
   - **aba_minhas** — acompanhamento (todos os status, como a simulação):
     - `listar_requisicoes(limit=500, emitente=usuario["nome"])`; métricas (meus pedidos /
       aguardando separação / entregues) + `st.dataframe` no shape da `_fila_visao_solicitante`;
     - detalhe por requisição (`listar_itens_requisicao`) com o "pedido × recebido" por item;
     - quando `status == 'Aberta'`: botão "Cancelar requisição" → `cancelar_requisicao` (já existe).

Estado de sessão: `st.session_state.itens_req` / `req_destinatarios` / `req_confirmada` são os
mesmos de `movimentacao.py` — como só uma página renderiza por execução, não há colisão.

---

## 9. Página Gestor — `ui/paginas/gestor.py` (novo)

`render()`:

1. **Sem usuário logado**: seletor de setor (`[""] + _opcoes_setor()`) com
   `st.warning("Sem login — simulação: escolha o setor. Com login, o setor é o departamento do
   seu cadastro.")` e segue abaixo.
2. **Com usuário** (`papel == gestor`): `setor = usuario["departamento"]`; se vazio →
   `st.warning("Seu cadastro não tem departamento — fale com o almoxarife.")` e para.
   `st.selectbox("Setor", ["", ...], index=do departamento)` **editável** — permite ao Luis
   testar aprovações de outros setores (pedido explícito). `st.caption` documentando o filtro:
   "Mostra requisições em que o Setor é igual ao departamento (a criação do Requisitante já
   pré-preenche)."
3. **Fila de aprovação** — `listar_requisicoes_por_setor(setor, so_abertas=True,
   apenas_aprovadas=False)`: tabela com Nº, aberta em, emitente, itens, itens pendentes;
   botão ":material/how_to_reg: Aprovar" por linha → `aprovar_requisicao(req_id, usuario["nome"])`
   → `invalidar_leituras()` + `st.rerun()`. Vazio → `st.info("Nenhuma requisição do setor
   aguardando aprovação.")`.
4. **Já aprovadas** — `listar_requisicoes_por_setor(setor, so_abertas=False,
   apenas_aprovadas=True)` (limitada às últimas ~20 na tela), somente leitura, com "Aprovado por
   X em Y".

**Não bloqueia:** a tela não recusa separação/entrega nem altera status — a fila do almoxarife
(`_fila_visao_almoxarife`) continua mandando. A aprovação é um registro paralelo.

---

## 10. Página Portaria — `ui/paginas/portaria.py` (novo)

`render()` (funciona logada, como `portaria`, e no modo público):

1. Cabeçalho "Consulta de Saída — Portaria" + `st.caption` "Informe o número da requisição para
   conferir o pedido e a baixa. Consulta pública — não requer login."
2. `st.form`: `st.text_input("Número da requisição", placeholder="ex.: REQ-20260802-001")` +
   botão "Consultar".
3. Resultado (`buscar_requisicao_por_numero`):
   - não encontrada → `st.info("Requisição não encontrada.")`;
   - encontrada → card: **status** (com a cor/marcação por status), emitente, setor, centro de
     custo, aberta em, autorizador (se houver), **aprovado por/em** (se houver, "Aprovado por X
     em Y"), observações, destinatários (se `entrega_individual`), e a tabela de itens
     `solicitado × atendido` (PN, nome, unidade).
4. Sem interações de escrita — leitura pura.

---

## 11. Testes — `tests/test_v620_telas_self_service.py` (novo)

Usa fixtures `db`, `make_item` do `conftest.py`. Importa `services.db_functions` e
`services.usuarios`.

| # | Teste | O que afirma |
|---|---|---|
| 1 | `test_migracao_aprovacao_gestor` | após `criar_banco()`, `requisicoes` tem `aprovado_por`/`aprovado_em`; 2º `criar_banco()` idempotente; com tabela não vazia, `.bak` gravado em `backups/` |
| 2 | `test_aprovar_requisicao` | requis. Aberta → `(True, msg)`; `aprovado_por`/`aprovado_em` preenchidos; **status e autorizador_* inalterados** |
| 3 | `test_aprovar_requisicao_ja_aprovada` | 2ª chamada avisa e **não sobrescreve** `aprovado_por` |
| 4 | `test_aprovar_requisicao_cancelada_recusa` | `Cancelada` → `(False, msg)`; `aprovado_por` continua NULL |
| 5 | `test_buscar_requisicao_por_numero` | encontra por número (case/trim insensível), traz itens; `""`/ausente → None |
| 6 | `test_listar_requisicoes_por_setor` | filtra por setor (case/trim insensível); `so_abertas` exclui Entregue/Cancelada; `apenas_aprovadas` separa; setor vazio → [] |
| 7 | `test_rotas_por_papel_v620` | almoxarife=10; comprador=5 inalterado; requisitante=["Minhas Requisições"]; gestor=["Aprovações do Setor"]; portaria=["Portaria"]; `opcoes_menu(None)`=10 |
| 8 | `test_contrato_criacao_self_service` | `criar_requisicao` com emitente=nome do usuário e setor=departamento nasce Aberta com `aprovado_por` NULL e fluxo Digital |
| 9 | `test_fluxo_gestor_end_to_end` | requisitante cria (setor=departamento) → `listar_requisicoes_por_setor` (abertas, não aprovadas) contém → gestor aprova → entra em "aprovadas" |
| 10 | `test_opcoes_setor_prefill` | `_opcoes_setor('X')` com X inexistente → X como 1ª opção; com X existente → sem duplicar |
| 11 | `test_smoke_gate_portaria_publica` | AppTest: `exigir_login` ligada, sem sessão, `em_modo_publico()` → `gate()` não para e "Portaria" renderiza |
| 12 | `test_smoke_rota_requisitante` | AppTest: sessão com papel requisitante → `opcoes_menu` = só "Minhas Requisições"; render sem exceção |

Ajuste em `tests/test_v610_usuarios.py`: `test_rotas_por_papel` passa a esperar almoxarife=10 e
os 3 papéis com a própria rota (não mais lista vazia).

Bordas cobertas: aprovação não sobrescreve nem muda status; cancelada recusa; portaria não acha →
mensagem amigável; filtro de setor sem linha → lista vazia.

---

## 12. Migração / backup / compatibilidade

- Migração **aditiva e nullable**: `aprovado_por`/`aprovado_em` entram como `NULL`; sem backfill.
- **Backup** `requisicoes-aprovacao-gestor-v620` antes do ALTER (mesmo motivo/padrão do
  `tipo_fluxo`); confere o retorno do `wal_checkpoint` (armadilha já paga na v5.8.0).
- Compatibilidade: banco antigo (v6.1.0) abre na v6.2.0 — as colunas nascem NULL e nada muda
  para o almoxarife; flag `exigir_login` desligada → menu com 10 rotas e as 3 páginas degradam
  (Requisitante/Gestor sem login mostram aviso/seletor; Portaria consulta sem login).
- `opcoes_menu(None)` mantém o contrato "todas as rotas"; os testes v410/v530/v610 que fixam a
  lista completa do menu são atualizados para 10.
- `ui/paginas/movimentacao.py` continua importável e os blocos mantêm defaults — nenhum teste de
  movimentação existente muda de comportamento.

---

## 13. Definição de Pronto

- [ ] Migração `aprovado_por`/`aprovado_em` aditiva + backup testados (teste 1)
- [ ] `services/db_functions.py` com as 3 funções novas e testes verdes (2–6, 8–9)
- [ ] Modo público da Portaria: `gate()` + botão na `render_login` + menu de 1 item (7, 11–12)
- [ ] Páginas Requisitante/Gestor/Portaria renderizando sem exceção (AppTest)
- [ ] `tests/test_v620_telas_self_service.py` verde isolado e na suíte; `test_v610` ajustado
- [ ] `.\verify.ps1` retorna exit 0 (ruff format + lint + pytest completo)
- [ ] Bump `VERSAO = "6.2.0"` em `services/constants.py`
- [ ] `changelog/6.2.0.md` preenchido; `docs/HANDOFF.md` STATUS ATUAL atualizado
- [ ] **Validação no app real (regra nº6):** com o Luis —
  1. flag off → app abre como sempre; menu com as 3 telas novas; "Minhas Requisições"/"Aprovações
     do Setor" sem login mostram o aviso; Portaria consulta sem login;
  2. ligar `exigir_login` → tela de login com o botão "Consulta de saída — Portaria (sem login)";
  3. definir PIN do requisitante (ex.: Sidinei) → logar → menu só "Minhas Requisições"; criar um
     pedido com o setor já pré-preenchido (editável) → aparece em "Minhas requisições" como Aberta;
  4. na Configurações, marcar um usuário como **gestor** com departamento e PIN → logar → 
     "Aprovações do Setor" mostra o pedido do passo 3; aprovar → "Aprovado por ..." registrado;
     almoxarife ainda separa/entrega (não bloqueia);
  5. Portaria (modo público e logado) → consultar pelo número → dados corretos;
  6. Visão do Solicitante (simulação) continua funcionando com flag off;
  7. desligar a flag → volta ao comportamento anterior.
- [ ] **OK explícito do Luis** antes de qualquer commit (regra nº6)
- [ ] `graphify update .` ao final (grafo)

## 14. Ordem de implementação

1. `database.py` (migração) + teste 1 → 2. `services/db_functions.py` (3 funções) + testes 2–6
   → 3. `ui/auth.py` (modo público) + `ui/router.py` + `ui/sidebar.py` + testes 7/11/12 →
   4. `ui/paginas/movimentacao.py` (`_opcoes_setor` + bloco parametrizado) + teste 10 →
   5. `ui/paginas/requisitante.py` → 6. `ui/paginas/gestor.py` → 7. `ui/paginas/portaria.py`
   (testes 8–9 com as páginas) → 8. bump `VERSAO` + `changelog/6.2.0.md` + `docs/HANDOFF.md` →
   9. `.\verify.ps1` → 10. validação no app real com o Luis → 11. commit (só com OK) + `graphify`.
