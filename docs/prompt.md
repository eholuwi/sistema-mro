# Backlog / prompt de continuidade — Sistema MRO

> Atualizado em 26/07/2026, ao fechar a **v5.6.0**. As 4 demandas antigas desta lista
> (Consumo/Mensal, Guarda-Chuva, Monitor de SC, integração com a API do SCM) foram entregues
> entre a v4.8 e a v5.6 e saíram daqui. O estudo das requisições digitais segue em
> `docs/REQUISICOES_DIGITAIS_ESTUDO.md`.

---

## O QUE ESTÁ ABERTO

O pedido de 26/07/2026 tinha 9 itens. **Os itens 1–6 foram entregues na v5.6.0.** Ficaram de fora,
por decisão do Luis, os três que dependem de **entrevista de alinhamento**:

### Item 7 — Requisição de Material: Padrão × Digital

Radio button na aba "Nova Requisição" com **Requisição Padrão** (default) e **Requisição Digital**.

Fatos já levantados (não repetir a investigação):

- O fluxo Padrão **não foi desativado, foi removido** — commit `84c654b` (17/07/2026), o mesmo que
  introduziu a Digital. O pai é `4d25e2c`. O código antigo está recuperável quase 1:1 em
  `git show 4d25e2c:app.py`, função `_render_requisicao()`, **linhas 1196-1348** — inclusive os dois
  checkboxes pedidos (Entrega Individual e Aprovação SESMT).
- **As colunas já existem** em `requisicoes` (`database.py:263-281`): `entrega_individual`,
  `destinatarios` (JSON), `sesmt`, `sesmt_responsavel`, `autorizador_tipo/nome`. **Sem migração**
  para elas. Falta só um campo para distinguir Padrão de Digital.
- **Matrícula nunca teve coluna própria** — era parseada de um `text_area` livre no formato
  `MATRÍCULA — NOME` e serializada em JSON. Campos separados de Matrícula e Nome são pedido **novo**,
  não restauração.
- ⚠️ **Conflito de regra:** a Padrão baixa estoque **na criação**; a v4.7.0 mudou isso de propósito
  (baixa na entrega) e `tests/test_requisicao.py::test_criacao_nao_baixa_estoque` trava o contrato.
  Usar **função separada** (ex.: `criar_requisicao_com_baixa`) ou flag — **não** alterar
  `criar_requisicao`.
- Hoje SESMT só existe na **entrega** (`ui/paginas/movimentacao.py:601-606`); "Entrega Individual"
  não existe em lugar nenhum da UI.
- **Decisão já tomada pelo Luis:** na Padrão vai **só "Qtd Solicitada"**, com baixa integral (o fluxo
  antigo tinha Qtd Solicitada + Qtd Atendida). Faltando saldo, recusa e avisa qual item.

### Item 8 — Fila de Separação: visões Almoxarife × Solicitante + "Adicionar Item" sempre

- "Adicionar Item" **não tem condição na UI** — o expander é sempre renderizado
  (`ui/paginas/movimentacao.py:627-647`). A restrição vem de dois pontos indiretos:
  `services/db_functions.py:1356` (a fila só lista `Aberta`/`Parcial`) e `:1298` (o serviço recusa
  os demais status).
- ⚠️ **Armadilha:** `adicionar_itens_requisicao` **não recalcula o status**. Liberar a guarda sem
  recalcular deixa a requisição `Entregue` com item pendente — e ela **não reaparece na fila**, então
  o item novo fica **órfão e invisível**, e a entrega passa a recusá-lo. Correção mínima: chamar
  `_calcular_status_requisicao` + `UPDATE` ao final, reabrindo para `Parcial`. Isso faz
  `tests/test_v470_requisicao_digital.py:67-76` falhar — precisa ser reescrito.
- **Não existe autenticação no MRO** (`tests/test_v330_seguranca.py` é sobre *estoque* de segurança,
  não acesso). A "visão do Solicitante" depende dessa decisão de arquitetura — ver
  `docs/REQUISICOES_DIGITAIS_ESTUDO.md`, seção 4 (login local × reusar `/Usuario` do SCM) e as fases
  R1/R2/R3.

### Item 9 — Relatório de Movimentações (exportação)

Análise do `movimentacoes_26-07-2026.xlsx` (2.815 linhas, 16/04 a 21/07 — arquivo **fora do git**,
mantido só para análise).

A coluna **Observação nunca é digitada** — é sempre string montada por código, em 8 templates, e
empilha 4 semânticas diferentes:

| Padrão | Ocorrências | O que está escondido no texto |
|---|---|---|
| `Req REQ-…` | 1.545 | nº da requisição |
| `Requisição REQ-…` | 336 | **o mesmo, em formato histórico diferente** |
| `Ajuste …` / `AJUSTE: …` | 517 | motivo do ajuste (dois formatos) |
| `Conferência …` | 136 | mudança de local (`Local: X → Y`) |
| `NF: …` | 108 | número da nota fiscal |

Dado que **já existe no banco e não é exportado**: `centro_custo` (99% preenchido), `setor` (66%),
`solicitante` (100%), `requisicao_id` (66%), `sc_item_id` (4%). As FKs para puxar SC/PO/NF/
fornecedor/autorizador/SESMT já existem. **`motivo` está 0% preenchido** — não serve de fonte.

Proposta a validar: explodir a Observação em colunas próprias (Nº Requisição, NF, SC/PO, Centro de
Custo, Setor, Motivo, Categoria), manter Observação como texto residual, e trocar o `Tipo` cru
(`saida`/`entrada`) pela categoria amigável que a tela já calcula.

⚠️ Dois defeitos a corrigir junto, independentemente do desenho: **teto rígido de 5.000 linhas**
(`services/db_functions.py:3049`) com `ORDER BY data_hora DESC` — as mais antigas somem
**silenciosamente**, e no ritmo atual o corte começa em ~6 meses — e **ausência de filtro por período**.

### Pauta da entrevista (itens 7-9)

1. Requisição Padrão × Digital: quem usa cada uma, e a Digital é criada pelo solicitante ou pelo almoxarife?
2. Baixa imediata na Padrão: quando falta saldo — recusa tudo, ou baixa o que tem?
3. Matrícula/Nome: um colaborador por requisição ou vários (a lista antiga aceitava vários)?
4. "Adicionar Item" em requisição entregue: ela volta para a fila como Parcial, ou vira pedido novo vinculado?
5. Visão do Solicitante: consulta só, ou também cria? Identifica por nome digitado ou precisa de login?
6. Relatório: quem consome, com que frequência, e para responder qual pergunta?

---

## ACHADOS DA v5.6.0 — pendentes de decisão

1. **⚠️ Segundo caminho de perda do recebimento parcial.** `ingerir_scm` grava
   `quantidade_recebida = qtd_entregue` (do Protheus) direto no UPDATE de `itens_sc` (via
   `dados_item`); `importar_solicitacoes_protheus` faz o mesmo. Mas o `changelog/4.5.7.md:27`
   declara: *"`quantidade_recebida` NUNCA é escrita fora de `registrar_recebimento_sc`"*.
   **Efeito real:** o parcial registrado hoje é sobrescrito no próximo import do Relatório de SCs,
   porque o Protheus só enxerga a NF — mesmo com a UI já corrigida na v5.6.0. Corrigir é **decidir
   quem é a fonte de verdade**: (a) `MAX(quantidade_recebida, qtd_entregue)`; (b) o import nunca
   reduz o valor; (c) manter como está, Protheus manda.
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

## PENDÊNCIAS DE INFRA

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
