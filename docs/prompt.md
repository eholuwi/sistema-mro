# Backlog / prompt de continuidade — Sistema MRO

> Atualizado em 02/08/2026, ao planejar a **v6.2.0** (Telas self-service: Requisitante · Gestor ·
> Portaria). A v6.1.0 (Usuários e Login) saiu desta lista — entregue, validada no app real e
> commitada (`cded88c`).
> As demandas antigas desta lista foram entregues entre a v4.8 e a v5.6 e saíram daqui.
> O estudo das requisições digitais segue em `docs/REQUISICOES_DIGITAIS_ESTUDO.md`, a decisão
> de arquitetura do login em `docs/DECISAO_ENTREGA_FINAL_LOGIN.md` e o plano da fase atual em
> `docs/PLANO_V620_TELAS_SELF_SERVICE.md`.

---

## 🔧 DEMANDA ABERTA — v6.3.0 · Ajustes das telas self-service (feedback do Luis, 02/08/2026)

> **Aberta em 02/08/2026**, ao testar a v6.2.0 no app real. São dois ajustes de **usabilidade
> da tela do Gestor** — nenhum muda regra de negócio. A v6.2.0 fica como está (commitada e
> verde); estes entram na próxima sessão.

### 1. Admin não deveria escolher setor — deveria ver TUDO que há para aprovar (prioridade)

**Como está:** `ui/paginas/gestor.py::_escolher_setor` trata todo usuário logado igual — lê
`usuario["departamento"]` e, se estiver vazio, **para** com um aviso. Para o almoxarife
(admin) isso é duplamente ruim: ele normalmente **não tem departamento** cadastrado, então a
tela não mostra nada; e mesmo cadastrando um, ele veria só um setor por vez.

**Como deve ficar (palavras do Luis):** *"deveria mostrar tudo que tem pra aprovar logo de
todos os setores pra perfil de admin"*. Ou seja: papel `almoxarife` → fila **consolidada**,
de todos os setores, sem seletor obrigatório (o seletor vira filtro opcional, com "Todos"
como padrão). Gestor continua no seu departamento.

**Onde mexer:**
- `services/db_functions.listar_requisicoes_por_setor` — hoje `setor` vazio devolve `[]` de
  propósito (nega por omissão, para gestor sem departamento não virar admin). **Não afrouxar
  essa função**: criar um caminho explícito para "todos os setores" (parâmetro `setor=None`
  com semântica diferente de `""`, ou função irmã `listar_requisicoes_para_aprovacao()`), para
  que a negativa por omissão do gestor continue intacta. Há teste fixando o comportamento
  atual: `test_listar_requisicoes_por_setor_sem_setor_nega`.
- `ui/paginas/gestor.py::_escolher_setor` — ramo por papel: `almoxarife` → consolidado;
  `gestor` → departamento; sem login → simulação (como hoje).
- A fila consolidada precisa mostrar a coluna **Setor** com destaque (hoje ela já vem no
  `_tabela`, mas com um setor só ela é redundante — com todos, é a informação principal).

### 2. Tela do gestor agrupada por solicitante (a confirmar)

*"em perfis de gestor deveria aparecer por solicitante eu acho"* — ideia ainda **não
fechada** (o "eu acho" é do Luis). Confirmar antes de implementar: agrupar a fila por
`emitente` (expander por pessoa, com contagem), em vez da lista plana por data. Decidir se
substitui a ordenação por data (fila do mais antigo) ou se é uma visão alternativa —
**perguntar antes**, porque a ordem por data é o que faz "fila" significar alguma coisa.

---

## 🟡 EM VALIDAÇÃO — v6.2.0 · Telas self-service (Requisitante · Gestor · Portaria)

> **Implementada e COMMITADA em 02/08/2026** com OK explícito do Luis, gate verde (793 testes).
> Os 7 itens do backlog abaixo estão feitos, mais a correção do login por alias (bug da v6.1.0
> achado ao testar). Ver `changelog/6.2.0.md`; plano de referência em
> `docs/claude/Sessão 3/PLANO_V620_TELAS_SELF_SERVICE.md` e análise técnica prévia em
> `Etapa 2 Plan.md`, na mesma pasta.
>
> ⚠️ **A validação no app real ficou INCOMPLETA** (o Luis parou para entender o fluxo). O commit
> saiu com autorização explícita dele mesmo assim. Roteiro passo a passo em
> `docs/ROTEIRO_TESTES_V620.md` — os 4 pontos críticos estão na última seção do roteiro; o mais
> importante é o **6.6** (menu do modo público tem de ter UM item só).
>
> **Decisões travadas em 02/08/2026 (Luis):**
> - **Aprovação do Gestor NÃO bloqueante** — registra a autorização antecipada
>   (`requisicoes.aprovado_por`/`aprovado_em`, migração aditiva com backup); o almoxarife pode
>   separar/entregar antes; **sem novo status** no `CHECK` de `requisicoes.status`.
> - **Portaria = consulta pública por número, sem login** (terminal compartilhado): o `gate()`
>   ganha um "modo público" com botão na tela de login; a página é leitura pura.
> - **Setor na criação do Requisitante**: mantém o `selectbox` de `listar_setores_conhecidos()`,
>   pré-preenchido com o `departamento` do usuário logado e editável.
> - **Filtro do Gestor = igualdade simples de setor** (`requisicoes.setor == departamento`), com
>   seletor de setor editável para testar outros setores. Limitação aceita: vocabulários divergem
>   (**59** setores × 19 departamentos, 9 de interseção — recontado no `mro.db` em 02/08/2026; o
>   plano dizia 57) — o filtro cobre o fluxo novo.
> - **Simulação "Visão do Solicitante"**: mantida com `exigir_login` desligada (modo legado);
>   com login ligado, o requisitante usa a tela própria.
>
> Backlog de implementação — **todos os 7 itens concluídos em 02/08/2026**:
> 1. ✅ `database.py` — migração aditiva `aprovado_por`/`aprovado_em` + `_backup_db`.
> 2. ✅ `services/db_functions.py` — `aprovar_requisicao`, `buscar_requisicao_por_numero`,
>    `listar_requisicoes_por_setor` (todas sobre o `_consultar_requisicoes` extraído).
> 3. ✅ `ui/auth.py` — modo público da Portaria; `ui/router.py` + `ui/sidebar.py` — 3 rotas novas e
>    menu por papel (7 → 10 rotas).
> 4. ✅ `ui/paginas/movimentacao.py` — `_opcoes_setor()` + bloco 1 parametrizado (setor padrão +
>    emitente fixo) + `_req_painel_pedidos` extraído da Visão do Solicitante.
> 5. ✅ Páginas novas `ui/paginas/requisitante.py`, `ui/paginas/gestor.py`, `ui/paginas/portaria.py`.
> 6. ✅ `tests/test_v620_telas_self_service.py` (27 testes) + ajustes em `test_v610_usuarios.py` e
>    `test_v500_router.py` (o menu cresceu — o plano citava v410/v530, que não tocam o menu).
> 7. ✅ `VERSAO = "6.2.0"`, `changelog/6.2.0.md`, `docs/HANDOFF.md`.
>
> **Falta:** validação no app real (roteiro de 7 passos na §13 do plano) → OK do Luis → commit →
> `graphify update .`.

---

## ✅ ENTREGUE — v6.1.0 · Usuários e Login local (FUNDAÇÃO)

> **Entregue em 02/08/2026** — implementada, validada no app real pelo Luis e commitada
> (`cded88c`). Ver `changelog/6.1.0.md`. O item 8 do backlog virou `docs/FUNCIONALIDADES.md` ›
> "Usuários e acesso" e duas linhas no `CLAUDE.md`.
>
> **Resolvido o que estava em aberto:** a aba "Usuários" em Configurações entrou (7ª aba) — sem
> ela ninguém definiria PIN. Duas guardas foram além do plano, ambas para bordas sem volta pela
> UI: não dá para rebaixar/desativar o **último almoxarife ativo**, nem para ligar `exigir_login`
> sem **nenhum** usuário ativo com PIN.

**Decidido em 01/08/2026** (sessão do Luis):

- **Escopo:** só a fundação — tabela `usuarios`, seed, login, papel no `session_state` e filtro
  de rotas. As telas novas (Requisitante/Gestor/Portaria) ficam para a próxima fase.
- **Login:** módulo próprio (`ui/auth.py` + `services/usuarios.py`) — o `st.login` do Streamlit
  1.60 é **OIDC-only** (exige provedor externo em `secrets.toml` + `authlib`, não instalado).
  Não existe "provider local". Mantém o login 100% local, como manda o doc de decisão.
- **Credencial:** nome (ou login `primeiro.sobrenome`) + **PIN de 4 dígitos** (hash pbkdf2,
  stdlib — sem dependência nova). PIN definido pelo admin em Configurações.
- **Ativação:** comutável — flag `exigir_login` em `configuracoes`, **padrão DESLIGADO**.
  O Luis ativa quando validar no app real.
- **Papéis:** `almoxarife` (admin), `comprador`, `requisitante`, `gestor`, `portaria`.
  - almoxarife: **Luis Gabriel Arruda de Oliveira**, **Jasiva Lopes**, **Juan Tarco** (acesso total)
  - comprador: **Miguel Nascimento**, **Adrya Vigil** → veem Dashboard, Saldo em Estoque, Ficha 360,
    Cadastro de Itens e Controle de SC (sem Movimentação nem Configurações)
  - requisitante: demais `solicitantes_mro` (ex.: Sidinei) → nenhuma rota ainda (telas novas na
    próxima fase)
- **Migração:** tabela nova aditiva (CREATE TABLE IF NOT EXISTS + índice) no padrão v5.1.0
  (`itens_sc_externos`); seed idempotente (`INSERT OR IGNORE`). Sem backup necessário — não toca
  dado existente. O que definir que toca dado existente (se mudar a distribuição de papéis) exige
  backup antes.
- **Pergunta em aberto:** a aba "Usuários" em Configurações (listar, papel, PIN, ativo) é parte da
  fundação — sem ela ninguém consegue definir PIN. Fora isso, nada mais entra nesta fase.

Backlog de implementação (após aprovação do plano):

1. `services/usuarios.py` — PAPEIS, hash/validação de PIN, `autenticar`, CRUD de usuários.
2. `database.py` — tabela `usuarios` + `semear_usuarios()` (seed + overrides manuais).
3. `ui/auth.py` — sessão (`st.session_state`), formulário de login, gate.
4. `ui/router.py` + `ui/sidebar.py` — filtro de `ROTAS` por papel; perfil do usuário logado.
5. `ui/paginas/configuracoes.py` — aba "Usuários".
6. `app.py` — gate de login antes do despacho.
7. `tests/test_v610_usuarios.py` — migração/seed/PIN/rotas-por-papel/flag.
8. Changelog `6.1.0` + HANDOFF.

---

## O QUE ESTÁ ABERTO

**O pedido de 26/07/2026 está FECHADO.** Os itens 1–6 saíram na v5.6.0; os itens **7, 8 e 9** —
que dependiam de entrevista — saíram na **v5.7.0**, junto com o achado nº1 daquela versão. Ver
`changelog/5.7.0.md`.

Não há demanda de produto em aberto no momento. O que resta são os **achados 2–7 da v5.6.0**
(abaixo), os **4 achados novos da v5.7.0** e as pendências de infra.

---

## DECISÕES DA ENTREVISTA DE 27/07/2026

Registradas porque **têm autoridade sobre o que estava escrito neste arquivo** — em dois pontos
elas contradizem o plano anterior, e quem ler o histórico precisa saber qual venceu.

1. **Os dois fluxos de requisição convivem.** A **Padrão** é a da operação real (o material sai no
   balcão, a baixa é na criação) e vira o **default**; a **Digital** é protótipo de vitrine do
   self-service e passa a ser assumidamente experimental.
2. ⚠️ **SUBSTITUI a regra antiga deste arquivo** (*"faltando saldo, recusa e avisa qual item"*):
   falta de saldo **não recusa o pedido**. Baixa `min(solicitada, estoque)` e manda o pendente para
   a Fila de Separação — que é o que a operação já faz no papel.
3. **Ajuste não tem Centro de Custo.** É correção do almoxarifado, não consumo de setor: CC vazio é
   a informação **correta**, não dado faltando.
4. **Requisição entregue que recebe item novo reabre como Parcial** e volta à fila (não vira pedido
   novo vinculado).
5. **Visão do Solicitante é simulação**, identificada por nome digitado. O MRO não tem login, e a
   tela precisa dizer isso em destaque.
6. **O relatório serve aos dois usos** — rateio mensal por CC/Setor **e** auditoria/rastreio.
   Daí a exportação larga com colunas explodidas e o filtro de período.
7. **O relatório tem de responder três perguntas:** quanto perdemos no período · quais itens vivem
   divergindo · reconciliação do saldo. É por isso que cada caminho de ajuste ganhou categoria
   própria: sem isso não dá para somar perda sem varrer junto correção de cadastro.
8. **Matrícula e Nome em campos separados** (a `text_area` antiga adivinhava o separador).
9. **Só o MRO escreve `quantidade_recebida`.** Import do Protheus e API do SCM viram leitura; o
   número do ERP vive em coluna própria, visível ao lado.

---

## ARQUIVO — o que estava aqui e foi entregue na v5.7.0

Os itens 7, 8 e 9 tinham páginas de investigação neste arquivo. Foram removidos porque **estão
implementados**; o que sobreviveu deles como conhecimento vivo está no `changelog/5.7.0.md` e no
`docs/HANDOFF.md`. Dois fatos que valem repetir aqui, porque voltam a morder:

- **`movimentacoes.motivo` está 0% preenchido** nas 2.822 linhas do histórico real. Ele só passou a
  ser gravado na v4.3.0. Para classificar movimentação **legada**, a fonte confiável é o
  **`centro_custo`** (`INVENTÁRIO` / `EDIÇÃO`) — os templates de texto da Observação mudaram cinco
  vezes ao longo das versões, o CC nunca mudou.
- **A Observação nunca é digitada** — é string montada por código. Se aparecer um template novo,
  ele nasce em `services/db_functions.py` ou na borda da UI, não no teclado do almoxarife.

---

## ACHADOS DA v5.6.0 — pendentes de decisão

> O **nº1** (segundo caminho de perda do recebimento parcial) foi **resolvido no CP1 da v5.7.0**
> pela decisão nº9: só o MRO escreve `quantidade_recebida`. A numeração dos demais é **preservada
> de propósito** — o `changelog/5.7.0.md` e o `docs/HANDOFF.md` referenciam estes achados pelo
> número, e renumerar quebraria as referências.

2. **`badge_origem` nunca acerta o azul.** Compara `origem == 'excel'`, mas a ingestão grava o **nome
   do arquivo** em `origem_importacao` — as 228 SCs aparecem como "origem não registrada". Os testes
   não pegam porque inserem `'excel'` na mão (`tests/test_v510_scm_sync.py:207`).
3. `registrar_recebimento_sc` recalcula `novo_saldo` a partir da quantidade negociada, mas valida
   contra `saldo_residual` — se divergirem, o pendente salta em vez de descer pela quantidade recebida.
4. `listar_scs` usa fórmula de pendente diferente de `listar_itens_sc` e `buscar_scs_por_item`
   (falta o `COALESCE(quantidade_pedido, …)`) — itens podem sumir/aparecer indevidamente na lista.
5. **Centro de Custo — vocabulários divergentes.** MRO/planilha usa `"21106 - MANUTENÇÃO"` (faixa
   211xx, 56 valores em `listas`); a API do SCM devolve descrição pura (`"DSI"`, faixa 90xxx). Sem
   de-para, agrupar por CC mistura dois universos.
6. **O sync da API varre 0 solicitantes** — nenhum dos marcados como MRO tem `codigo` Protheus
   preenchido (`services/scm_sync.py::_solicitantes_para_sync`). É a razão de o CC nunca ter vindo
   pela API. A v5.6.0 passou a **alertar** isso no painel de saúde; preencher em
   **Configurações › Solicitantes MRO (SCM)** (há botão para resolver pela API).
7. `services/monitor_scm.py` ficou **sem consumidor de UI** (o card "SCs/Itens não atendidos" saiu na
   v5.6.0). Mantido de propósito: lógica pura, testada, barata de manter.

---

## ACHADOS DA v5.7.0 — pendentes de decisão

Todos do Relatório de Movimentações (CP4). Nenhum é bug: são escolhas que ficaram deliberadamente
dentro do escopo aprovado e que o Luis pode querer ampliar.

1. **A categoria `Entrada` ainda mistura duas coisas** — recebimento por SC (139 linhas) e entrada
   avulsa (2). É a mesma doença que os ajustes tinham, mas o plano do CP4 listava só os caminhos de
   *ajuste*. As colunas NF e SC/PO já tornam essas linhas rastreáveis; uma categoria
   `Recebimento SC` fecharia o assunto.
2. **`SC/PO` saiu como coluna única** (`SC 41340 · PO F64923`), seguindo a lista do plano ao pé da
   letra. Duas colunas separadas seriam melhores para pivotar no Excel.
3. **Somar `Qtd` mistura direção** — a coluna é sempre positiva e o sentido está em `Tipo`. Um
   pivot resolve, mas uma coluna `Qtd (sinalizada)` responderia "quanto perdemos" direto, que é a
   primeira das três perguntas da decisão nº7.
4. **⚠️ Cuidado ao agrupar o relatório por Centro de Custo:** `INVENTÁRIO` e `EDIÇÃO` são CCs de
   **sistema**, não centros de custo reais (ver `CC_GENERICOS` em `services/constants.py`), e
   `99000 - ATIVO PASSIVO RES. F` é conta residual. Para rateio, filtrar por
   `Categoria == "Requisição"` primeiro. Isso se soma ao achado **nº5 da v5.6.0** (vocabulários
   divergentes entre MRO e API do SCM) — o relatório usa o CC do **MRO**, coerente consigo mesmo.

---

## PENDÊNCIAS DE INFRA

- **⚠️ Ao subir a v5.7.0:** as migrações do CP1 e do CP3 (`itens_sc.quantidade_recebida_protheus` e
  `requisicoes.tipo_fluxo`) **ainda não rodaram no `mro.db` de produção**. Executam sozinhas no
  primeiro render e gravam o `.bak` em `backups/`. São aditivas, nullable e sem backfill.
- **Validação interativa do CP1 pendente** — depende do Relatório de SCs, que o Luis ainda não tem.
  Falta abrir a tela e conferir o aviso de divergência (Controle de SC, Movimentação) e as colunas
  **Recebido (MRO)** × **Recebido (Protheus)** no SCM Integrado. A regra foi ensaiada contra cópia
  do `mro.db` real (SC 41494 / PN 29TP0086).
- **Após atualizar o app:** reimportar o **Relatório de SCs** para preencher o Centro de Custo das
  228 SCs — a correção da v5.6.0 vale para importações novas, não faz backfill do passado.
- **Validação física da F5:** reboot-test no PC-servidor, acesso de outra máquina, ensaio de
  backup/restore.
- **Promoção para a `main`** quando a v5.x fechar (hoje parada em v4.5.5, 40+ commits atrás).

---

## PROMPT PARA ABRIR A PRÓXIMA SESSÃO

Continuar o Sistema MRO (Inventus Power). Leia @docs/HANDOFF.md — a seção "STATUS ATUAL" no topo é
a autoridade sobre o que já foi feito e o que vem a seguir. Trabalhe na branch `feat/v5.0.0`
(`git fetch --all --prune` e `git checkout feat/v5.0.0` antes de tudo). Siga a skill
`atualizar-sistema-mro`, feche cada etapa com `.\verify.ps1` verde e PARE para aprovação antes de
cada commit.
