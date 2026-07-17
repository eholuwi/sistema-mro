# Estudo — Requisições Digitais (mapeamento + gap analysis)

> **Status:** documento de estudo (v4.10.0). **Nenhum código alterado.** Serve para o Luis
> decidir o próximo passo. Cobre: fluxo real ponta a ponta, modelo de status desejado, a
> regra do dia, e o portal self-service + login. Fecha com fases e esforço.

---

## 1. Ponto de partida — o MVP atual (v4.7.0)

A Requisição já tem **ciclo de vida** e a baixa de estoque só acontece na **entrega** (não na
criação). Hoje é **operada pelo almoxarife** (não há portal do solicitante).

- **Estados atuais:** `Aberta` → `Parcial` → `Entregue`, mais `Cancelada` (só a partir de Aberta).
  Derivação em `services/db_functions.py::_calcular_status_requisicao` (nada atendido → Aberta;
  tudo atendido → Entregue; intermediário → Parcial).
- **Criar** (`criar_requisicao`): abre **Aberta**, `quantidade_atendida=0`, **sem tocar o estoque**.
  Pode-se pedir mais do que o saldo — a fila mostra o que dá para atender.
- **Entregar** (`entregar_requisicao`, aba "Fila / Separação"): baixa por item (movimentação
  `saida` com `requisicao_id`), acumula `quantidade_atendida`, recalcula status. Exige
  **autorizador**; **SESMT** exige responsável (EPI/SSO).
- **Adicionar item ao pedido aberto** (`adicionar_itens_requisicao`): cobre "o solicitante volta e
  escreve no mesmo papel" — enquanto Aberta/Parcial.
- **Cancelar** (`cancelar_requisicao`): só a partir de Aberta.
- **Persistência:** `requisicoes.status` (CHECK Aberta/Parcial/Entregue/Cancelada) +
  `itens_requisicao.quantidade_atendida`.

**Conclusão:** a fundação (ciclo de vida, baixa na entrega, parcial, adicionar item, autorização/
SESMT) **já existe**. O que falta é (a) alinhar a **terminologia e a semântica** ao modelo do Luis,
(b) a **regra do dia**, (c) o caso **"material não pode ser pago"**, e (d) o **portal self-service +
login**.

---

## 2. Fluxo real ponta a ponta (a MAPEAR com o time)

Sequência observada / a confirmar no chão:

1. **Solicitante pede** — hoje muitas vezes verbal/papel; o almoxarife registra.
2. **Almoxarife separa "se tiver"** — atende total ou parcial; às vezes o solicitante volta e pede
   mais no mesmo pedido.
3. **Autorização na saída** — gestor (e **SESMT** para EPI/SSO) é registrado no momento da entrega.
4. **Baixa em lote** — o Juan dá baixa nos horários calmos (o MVP já reflete isso: baixa na entrega).
5. **Fecha o dia** — o que não foi retirado **não transita para amanhã** (ver regra do dia).

> **A confirmar em entrevista/observação:** quem são os solicitantes recorrentes; % de atendimento
> parcial; quanto do pedido é "não cadastrado" (o "caneta" inexistente); com que frequência se
> adiciona item depois; quem autoriza o quê; e como o "não pode ser pago" aparece na prática.

---

## 3. Modelo de status DESEJADO (do Luis) × atual

| Desejado (Luis) | Significado | Equivale hoje | Gap |
|---|---|---|---|
| **Criada** | Ainda não foi atendida. | `Aberta` | Só renomear/rotular. |
| **Atendida parcialmente** | Não deu toda a quantidade **ou** não deu todos os materiais. **Pode acrescentar material** para ser atendido, mesmo que itens já tenham sido atendidos. Inclui o caso **"material não pode ser pago"**. | `Parcial` (+ `adicionar_itens_requisicao`) | Falta o **motivo "não pode ser pago"** por item; hoje "adicionar item" existe mas o rótulo/UX precisa refletir o novo modelo. |
| **Finalizada** | **Não pode mais** ser usada para pegar material; fica no **histórico completo**. | `Entregue` (derivado quando tudo foi atendido) | Hoje "Entregue" é **derivado** (tudo atendido). O Luis quer **finalização explícita** (pode finalizar mesmo com itens não atendidos) **+ finalização automática no fim do dia**. |

**Diferença crítica:** hoje `Entregue` só surge quando **tudo** foi atendido. No modelo do Luis,
**Finalizada** é um estado **terminal por decisão/tempo** (o dia acabou, ou o almoxarife fecha),
independente de ter atendido tudo — o que não foi retirado simplesmente **não vale mais**.

### 3.1. A REGRA DO DIA (nova)
- A requisição é **do dia**: no dia seguinte o solicitante **abre uma nova** se quiser material.
- **Não** dá para usar a requisição de ontem, **nem** criar uma requisição para ser atendida amanhã.
- Implica **finalização automática (expiração) no fim do dia**: toda requisição `Criada`/`Atendida
  parcialmente` vira `Finalizada` na virada (o que sobrou não transita).
- Espelha o reset diário que o Monitor já usa ("Revisado pelo Almox" reseta todo dia) — há padrão
  no projeto para gates por dia (`monitor_sc_sync`).

### 3.2. "Material não pode ser pago"
- Um item pode **não ser atendido** porque **não há como pagar** (sem budget/centro de custo/
  aprovação financeira). É diferente de "não tem em estoque".
- Precisa de um **motivo por item** (ex.: `nao_atendido_motivo ∈ {sem_estoque, nao_pode_pagar,
  cancelado_solicitante, ...}`) para o histórico e para relatórios.

---

## 4. Portal self-service + login (o maior salto — futuro)

Hoje tudo é operado pelo almoxarife. O alvo é o **solicitante pedir sozinho pelo navegador**:

- **Login/usuários** — o MRO ainda **não tem autenticação**. Seria a primeira vez.
  - Opção A (mais simples): login local próprio (tabela de usuários no `mro.db`).
  - Opção B (integrado): reusar o cadastro de usuários do **SCM** (a API tem `/Usuario`,
    `/Usuario/Filter` — read-only) para identificar/validar solicitantes, sem recriar cadastro.
- **Catálogo** — o solicitante escolhe do **catálogo** (o material precisa estar cadastrado; o
  "caneta" inexistente ainda é uma pendência do MVP).
- **Permissões** — quem pode pedir o quê; autorização do gestor (e SESMT) permanece.
- **Fila** — o almoxarife continua vendo a **Fila / Separação** e dá baixa; o portal só muda **quem
  cria** a requisição.

> **Complexidade:** alta (auth + multiusuário + sessão + provavelmente sair do Streamlit puro ou
> adicionar uma camada de login). É a fase que exige decisão de arquitetura.

---

## 5. Gap analysis (resumo)

| Item | Existe hoje? | Esforço |
|---|---|---|
| Ciclo de vida + baixa na entrega + parcial | ✅ (v4.7.0) | — |
| Adicionar item a requisição aberta | ✅ (`adicionar_itens_requisicao`) | — |
| Autorização gestor + SESMT | ✅ | — |
| Renomear estados p/ **Criada / Atendida parcialmente / Finalizada** | ⚠️ rótulos | Baixo |
| **Finalização explícita** (fechar mesmo sem atender tudo) | ❌ | Médio |
| **Regra do dia** (expiração/finalização automática na virada) | ❌ | Médio (há padrão de gate diário) |
| **Motivo "não pode ser pago"** por item | ❌ | Baixo/Médio (coluna + UI + relatório) |
| **Portal self-service** | ❌ | Alto |
| **Login/usuários** | ❌ (MRO nunca teve) | Alto |

---

## 6. Recomendação de fases (para decidir)

- **Fase R1 — Semântica + regra do dia (interno, sem portal):**
  renomear estados (Criada/Atendida parcialmente/Finalizada), adicionar **finalização explícita** e
  a **finalização automática diária**, e o **motivo "não pode ser pago"** por item. Baixo/médio
  risco, alto valor operacional. Migração aditiva (novo enum de status + coluna de motivo), com
  backup. Reusa `entregar_requisicao`/`adicionar_itens_requisicao` e o padrão de gate diário.
- **Fase R2 — Relatórios/histórico:** o histórico "bem completo" da requisição finalizada (o que foi
  pedido × atendido × motivo do não atendido), export e indicadores (nível de atendimento, itens
  "não pode pagar" por período).
- **Fase R3 — Portal self-service + login:** decisão de arquitetura (login local vs. via `/Usuario`
  do SCM; Streamlit vs. camada web). Maior esforço; fazer só depois de R1/R2 validados no chão.

> **Próximo passo sugerido:** uma entrevista/observação curta no almoxarifado para preencher os
> pontos "a confirmar" da seção 2, e então fechar o escopo da **Fase R1** como a primeira entrega de
> requisição digital pós-MVP.
