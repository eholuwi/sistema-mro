# Backlog / prompt de continuidade — Sistema MRO

> Atualizado em 01/08/2026, ao planejar a **v6.1.0** (Usuários e Login local — fundação).
> As 4 demandas antigas desta lista foram entregues entre a v4.8 e a v5.6 e saíram daqui.
> O estudo das requisições digitais segue em `docs/REQUISICOES_DIGITAIS_ESTUDO.md` e a decisão
> de arquitetura do login em `docs/DECISAO_ENTREGA_FINAL_LOGIN.md`.

---

## ✅ ENTREGUE — v6.1.0 · Usuários e Login local (FUNDAÇÃO)

> **Implementada em 01/08/2026**, gate verde (756 testes), aguardando validação no app real e o
> OK do Luis para commitar. Ver `changelog/6.1.0.md`; o roteiro de validação está no
> `docs/HANDOFF.md` (STATUS ATUAL). O item 8 do backlog abaixo virou também
> `docs/FUNCIONALIDADES.md` › "Usuários e acesso" e duas linhas no `CLAUDE.md`.
>
> **Resolvido o que estava em aberto:** a aba "Usuários" em Configurações entrou (7ª aba) — sem
> ela ninguém definiria PIN. Duas guardas foram além do plano, ambas para bordas sem volta pela
> UI: não dá para rebaixar/desativar o **último almoxarife ativo**, nem para ligar `exigir_login`
> sem **nenhum** usuário ativo com PIN.
>
> **Próxima fase:** telas do Requisitante ("Minhas Requisições" + criar), do Gestor (fila de
> aprovação) e da Portaria. Os três papéis já existem e autenticam, mas seguem sem rota.

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
