# Roteiro de testes — v6.2.0 (Telas self-service)

> Para validar no app real (regra inviolável nº6). Tempo: ~20 min. Nenhum passo aqui
> apaga dado; o que grava é requisição de teste, que fica no histórico como qualquer outra.
>
> Subir o app: `venv\Scripts\python.exe -m streamlit run app.py`

---

## Antes de começar — como o fluxo funciona

Três papéis, três telas, e uma regra que amarra tudo: **a aprovação do gestor não bloqueia
nada**. Ela é um carimbo paralelo, não uma etapa obrigatória.

```
REQUISITANTE                GESTOR                    ALMOXARIFE              PORTARIA
"Minhas Requisições"        "Aprovações do Setor"     Movimentação › Fila     "Consulta de Saída"
      |                            |                        |                      |
  abre o pedido  ─────────────►  vê o pedido do          separa e ENTREGA      confere pelo
  (fluxo Digital,                seu setor e            (aqui sai o estoque,   número o que
  NÃO baixa estoque)             registra "aprovado"    com autorizador)       está saindo
      |                            |                        |                      |
      └──────── acompanha "pedido × recebido" ◄─────────────┘                      |
                                                                                   |
                     a aprovação aparece no cartão da Portaria ────────────────────┘
```

**O que confunde e é de propósito:**

- **Dois "autorizadores" diferentes.** `aprovado_por` (gestor, antecipado, opcional) e
  `autorizador_nome` (quem liberou a saída, exigido do almoxarife na entrega). A entrega
  funciona com ou sem aprovação do gestor.
- **Dois fluxos de requisição.** O **Padrão** (Movimentação) baixa estoque na criação — é
  o balcão. O **Digital** abre o pedido e só baixa na entrega — é o que o Requisitante usa.
- **A tela "Minhas Requisições" só mostra os pedidos em que `emitente` = seu nome.** Se
  você criar o pedido pela Movimentação com outro nome, ele não aparece lá.

---

## Parte 1 — Com `exigir_login` DESLIGADA (5 min)

O objetivo é provar que **nada quebrou** para quem não ligou o login.

| # | Passo | O que tem de acontecer |
|---|---|---|
| 1.1 | Abrir o app | Abre direto, sem tela de login |
| 1.2 | Olhar o menu lateral | **10 itens** — os 7 de sempre + Minhas Requisições, Aprovações do Setor, Portaria |
| 1.3 | Movimentação › Requisição › Nova | Padrão e Digital funcionam como antes; setor **vazio** no topo (não pré-preenchido) |
| 1.4 | Movimentação › Requisição › Fila › Solicitante | A simulação antiga continua lá, com o aviso de "não tem login" |
| 1.5 | Abrir "Minhas Requisições" | Avisa "Faça login com seu nome + PIN…" e **não** mostra formulário |
| 1.6 | Abrir "Aprovações do Setor" | Modo simulação: seletor de setor + campo "Aprovando como" |
| 1.7 | Abrir "Portaria" | Funciona sem login (é público por natureza) |

---

## Parte 2 — Ligar o login (2 min)

| # | Passo | O que tem de acontecer |
|---|---|---|
| 2.1 | Configurações › Usuários | A lista vem semeada dos Solicitantes MRO |
| 2.2 | Definir PIN para **um requisitante** (ex.: `ANA CLARA PASCOAL DE CARVALHO` → `1111`) | "PIN definido para…" |
| 2.3 | Definir PIN para **um gestor**: escolher alguém, mudar o papel para **Gestor**, preencher o **departamento** e dar PIN (ex.: `2222`) | ⚠️ **Sem departamento a tela do gestor não funciona** — é o campo que casa com o setor da requisição |
| 2.4 | Confirmar que o **seu** usuário (almoxarife) tem PIN | Você vai precisar dele para voltar |
| 2.5 | Ligar `exigir_login` | Recarrega e cai na tela de login |

**⚠️ Anote o departamento que você deu ao gestor** — ele tem de ser o mesmo setor que o
requisitante vai usar no pedido. É a limitação conhecida (setor × departamento são
vocabulários diferentes).

---

## Parte 3 — Requisitante (5 min)

| # | Passo | O que tem de acontecer |
|---|---|---|
| 3.1 | Logar como o requisitante do passo 2.2 — **nome completo** ou `ana.carvalho` | Entra |
| 3.2 | Olhar o menu | **Um item só**: "Minhas Requisições" |
| 3.3 | Aba "Nova Requisição" | **Setor já vem preenchido** com o departamento do cadastro (e dá para trocar); **Emitente travado** no nome dele |
| 3.4 | Adicionar 1 material e clicar CRIAR REQUISIÇÃO | Recibo "Requisição … criada!" com o número sequencial (v6.5.0: `1`, `2`, `3`…) — **estoque NÃO baixa** (é o fluxo Digital) |
| 3.5 | Aba "Meus Pedidos" | O pedido aparece como **Aberta**, com "pedido × recebido" por item |
| 3.6 | Selecionar o pedido e cancelar | Botão "Cancelar requisição" só aparece em pedido **Aberta** |

> Se o cadastro do requisitante **não tiver departamento**, o setor abre vazio e a tela
> avisa. Não é erro — é o aviso para pedir o cadastro ao almoxarife.

Crie **dois pedidos** aqui (um para aprovar, outro para entregar sem aprovação, no passo 5).

---

## Parte 4 — Gestor (5 min)

| # | Passo | O que tem de acontecer |
|---|---|---|
| 4.1 | Sair e logar como o gestor do passo 2.3 | Menu com **um item**: "Aprovações do Setor" |
| 4.2 | Olhar o topo | Setor já vem do **departamento** dele (editável, para acompanhar outra área) |
| 4.3 | "Aguardando aprovação" | Os pedidos do passo 3 aparecem, do mais antigo para o mais novo |
| 4.4 | Clicar **Aprovar** em UM deles | Mensagem de sucesso; ele **some** da fila e migra para "Já aprovadas" com "Aprovado por / em" |
| 4.5 | Conferir o status do pedido aprovado | Continua **Aberta** — aprovar **não** muda status |

> ✅ **RESOLVIDO na v6.3.0** (03/08/2026): o **almoxarife** não cai mais no seletor de setor —
> ele abre a tela já com a fila consolidada de **todos os setores**, e o seletor virou filtro
> opcional ("Todos os setores" por padrão, listando só os setores que têm pedido). O passo 4.1
> continua valendo para o papel **gestor**; para conferir o ramo do admin, use o roteiro da
> v6.3.0 (seção "Verificação" do plano) ou simplesmente abra a tela logado como você.

---

## Parte 5 — A prova de que a aprovação NÃO bloqueia (3 min)

Este é o passo mais importante da versão. Faça com o **pedido que você NÃO aprovou**.

| # | Passo | O que tem de acontecer |
|---|---|---|
| 5.1 | Sair e logar como **você (almoxarife)** | Menu completo, 10 itens |
| 5.2 | Movimentação › Requisição › Fila › Almoxarife | Os dois pedidos estão lá — aprovado e não aprovado, sem distinção |
| 5.3 | Entregar o pedido **não aprovado** (informando o autorizador) | **Entrega normalmente** — o estoque baixa e o status vai para Entregue/Parcial |
| 5.4 | Conferir o estoque do item | Baixou agora, na entrega (não na criação) |

Se a entrega tivesse sido recusada por falta de aprovação, a decisão teria sido violada.

---

## Parte 6 — Portaria (3 min)

| # | Passo | O que tem de acontecer |
|---|---|---|
| 6.1 | Ainda logado, abrir "Portaria" e consultar o número do pedido **aprovado** | Cartão com status, emitente, setor, CC e **"Aprovado por … em …"** |
| 6.2 | Consultar o pedido **entregue** | Tabela `Solicitado × Entregue` batendo com o que saiu |
| 6.3 | Digitar o número **em minúsculas** e com espaço na ponta | Acha do mesmo jeito |
| 6.4 | Digitar um número inexistente | "Requisição não encontrada", sem erro na tela |
| 6.5 | **Sair** (logout) → na tela de login, clicar **"Consulta de saída — Portaria (sem login)"** | Entra sem PIN |
| 6.6 | ⚠️ **Olhar o menu lateral no modo público** | **UM item só** ("Portaria"). Se aparecerem 10, é falha de segurança — pare e me avise |
| 6.7 | Consultar um número no modo público | Funciona; não há nenhum botão que grave |
| 6.8 | "Sair do modo público" | Volta para a tela de login |

---

## Parte 7 — Voltar ao normal (1 min)

| # | Passo | O que tem de acontecer |
|---|---|---|
| 7.1 | Logar como almoxarife → Configurações › Usuários → **desligar** `exigir_login` | App volta a abrir direto, sem login |
| 7.2 | Conferir o menu | 10 itens, tudo acessível como antes |

---

## Se algo falhar

Anote **em qual passo** e o que apareceu na tela. Os pontos que mais importam, em ordem:

1. **6.6** (menu do modo público com mais de 1 item) — é o único risco de acesso.
2. **5.3** (entrega recusada por falta de aprovação) — violaria a decisão de não bloquear.
3. **3.4** (estoque baixando na criação) — o Digital não pode baixar nada.
4. **4.5** (status mudando ao aprovar) — aprovar não é status.
