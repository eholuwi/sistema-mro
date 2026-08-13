# Backlog / prompt de continuidade — Sistema MRO

> Atualizado em **13/08/2026** — **v6.10.0 (Análise de Consumo em PDF)** planejada e aguardando
> implementação pelo Claude (seção "PRÓXIMA VERSÃO" abaixo). Registro anterior de **10/08/2026**,
> ao implementar a **v6.5.0 / Task 1** (consumo mensal por pedido de compra). O planejamento
> anterior é de **05/08/2026**, da **v6.4.0** (5 demandas do Luis — a
> planilha MRO, consumo por vida útil, sugestão de Min/Max, gestor rejeita + vê a requisição
> completa, requisitante sem saldo/imagem, portaria por nome). **Quem implementa é o Claude** em
> sessão própria; este arquivo + `changelog/6.5.0.md` + `docs/HANDOFF.md` são o handoff.
>
> ⚠️ **O Épico B da v6.4.0 (consumo por vida útil do lote) foi REMOVIDO na v6.5.0** e substituído
> pelo **consumo por pedido de compra atendido** (SC7). O texto do épico continua abaixo como
> registro do que foi decidido em 05/08/2026 — não como descrição do sistema atual.
> A v6.1.0 (Usuários e Login) saiu desta lista — entregue, validada no app real e commitada
> (`cded88c`); a v6.2.0 (Telas self-service) está commitada (`e33711a`) e aguarda a validação
> no app real; a v6.3.0 (Fila de aprovação consolidada) está implementada, gate verde, e
> aguarda validação + OK para commit.
> O estudo das requisições digitais segue em `docs/REQUISICOES_DIGITAIS_ESTUDO.md`, a decisão
> de arquitetura do login em `docs/DECISAO_ENTREGA_FINAL_LOGIN.md`.

---

## 📋 PRÓXIMA VERSÃO — v6.10.0 · Análise de Consumo em PDF (Assistente de Reposição)

> **Planejado em 13/08/2026.** Número **DESLOCADO de v6.9.0**: a v6.9.0 está reservada para a
> **previsão na Requisição** (fila × 5 min + Pronta para retirada), que o Luis vai trabalhar.
> Domínios independentes (v6.9.0 = Requisição; v6.10.0 = SC7/Assistente) — único arquivo em
> comum é `controle_sc.py`, em abas diferentes. **Implementação fica com o Claude** (sessão
> própria, skill `atualizar-sistema-mro`) — aqui está só a base aprovada.
> Changelog esqueleto em `changelog/6.10.0.md`.

**Requisitos (decisões do Luis, 13/08/2026):**

1. Botão **"Gerar Análise de Consumo"** na aba **Assistente de Reposição** (`controle_sc.py`,
   `aba_assist`), agindo sobre os **itens marcados** na tabela de seleção.
2. Saída em **PDF** (formato escolhido na revisão A): 1 PDF por item
   `Consumo <PN>-<Descrição>.pdf` + 1 resumo `Analise Geral.pdf` (convenção de nome já em
   `PROMPT_DOCUMENTO_ALMOXARIFE.md`, raiz do projeto; `/` no nome → `-`).
3. **Revisão A forçada:** revisão por item (campos editáveis: observações, proposta) +
   confirmação "Revisado e de acordo" antes de liberar o download. Nada sai direto.
4. **Fallback claro:** sem pedido de compra ATENDIDO no SC7 → usa consumo por **requisição**
   (saídas reais), com **aviso destacado em linguagem simples**: o documento explica que o SC7
   não encontrou pedido atendido, que por isso o consumo veio das retiradas do almoxarifado e
   **como o cálculo foi feito** (ex.: "somamos as retiradas de jan–jul e dividimos por 7").
   Sempre estampar fonte + período (ex.: "SC7 2026 (jan–jul)").
5. **Aviso de SC7 desatualizado:** `MAX(data_importacao)` da tabela `consumo_sc7`; se > ~1 mês →
   alerta + botão para a aba de importação (padrão já usado em `ficha_360.py:157`).
6. **Auditoria:** tabela nova `analises_geradas` (quem, quando, PNs, versão do SC7 usada,
   modo SC7/requisição).

**Épicos (ordem de implementação):**

- **C — Auditoria (schema).** `database.py`: tabela `analises_geradas` — **aditiva, idempotente,
  sem `_backup_db`** (padrão `consumo_sc7` da v6.5.0). Não toca tabela existente → FKs
  preservadas. Migração roda em runtime no `criar_banco()`.
- **A — Motor.** Novo `services/analise_consumo.py` (puro, sem `ui/`):
  - `montar_dados_analise(item)` — inventário (estoque/mín/máx/un/importância) + **SC7 via
    `consumo_sc7_por_item`** (reuso) + justificativa via `montar_justificativa`
    (`services/planejamento.py`).
  - Fallback por requisição reusando a base `SAIDA_REAL_WHERE`
    (`services/constants.py`) / `classificacao.py` (jan–jul ÷ 7, mesmo janelão do SC7).
  - `gerar_pdf_analise(...)` e `gerar_pdf_analise_geral(...)` via **reportlab** → `BytesIO`;
    `sc7_frescor()` para o aviso de desatualização.
  - **Dependência nova: `reportlab`** pinada em `requirements.txt` (runtime) → entra no pacote
    portátil via `pip --target` (`scripts/portatil.py`). Puro-Python, ok no embeddable; validar
    no app real. Fonte padrão cobre latin-1 (acentos PT).
- **B — UI.** `controle_sc.py`, aba Assistente: aviso SC7 desatualizado, botão Gerar Análise
  sobre a seleção, revisão A (campos editáveis + checkbox por item), `st.download_button`
  (padrão `ui/componentes/exportar.py`).

**Anti-duplicação (regra de ouro):** NÃO criar cálculo de consumo novo — reutilizar
`consumo_sc7_por_item` (SC7) e a leitura de consumo real de `classificacao.py`. **Não alterar** o
card SC7 da Ficha 360 nem a regra de `services/consumo_sc7.py` (o fallback só vale **no
documento**, explicitamente rotulado).

**Testes (gate):** novo `tests/test_v690_analise_consumo.py` — PDF válido (item + geral), fallback
rotulado (item sem SC7 × com SC7), sanitização de nome de arquivo, auditoria gravada,
`sc7_frescor` (bordas: sem import, antigo, recente).

**Gate e entrega:** `.\verify.ps1` verde + validação no app real → OK do Luis → commit →
`graphify update .`. `VERSAO = "6.10.0"` em `services/constants.py` (fonte única do
`scripts/release.py`; a comparação por tupla de inteiros já suporta 6.10.0 —
`services/atualizacao.py:192`).

---

## 🟡 EM VALIDAÇÃO — v6.4.0 · ~~Consumo por vida útil~~ · Min/Max · Gestor · Requisitante · Portaria (Luis, 05/08/2026)

> **Aberta e IMPLEMENTADA em 05/08/2026**, gate verde (886 testes). Ver `changelog/6.4.0.md` e o
> STATUS ATUAL do `docs/HANDOFF.md`. Os 5 épicos entraram na ordem B → C → D → E → F, com duas
> migrações aditivas (`.bak` gravado), provadas contra uma **cópia** do `mro.db` de produção.
> **Falta:** validação no app real → OK do Luis → commit → `graphify update .`.
>
> **Decisões do Luis que fecharam o que esta seção deixava em aberto:**
> - **Épico B — só recebimento de SC abre lote** (`sc_item_id` preenchido). Ajuste de inventário e
>   entrada avulsa mexem no saldo, mas não abrem lote. Vários lotes → **média simples**.
>   ⚠️ **Cobertura real: 20 de 362 itens.** Dos 94 com recebimento de SC, 20 têm lote fechado,
>   45 têm só lote vivo e 29 não abriram lote. É o histórico de 3,5 meses, não bug — cresce
>   sozinho. A alavanca, se ficar vazio demais, é a regra de "que entrada abre lote".
> - **Épico D — rejeitar é um CICLO, não um "não" final:** o gestor devolve com motivo, o
>   requisitante ajusta e reenvia, e o pedido volta para a fila. Puxou a coluna `reenviado_em` e a
>   função `atualizar_item_requisicao` (o requisitante só sabia remover item, não corrigir qtd).
> - **Épico C ganhou uma guarda não prevista:** `consumo_medio_diario` é coluna persistida e
>   congela; zero saídas na janela de 30 d ⇒ **sem sugestão**. Sem ela, o PN 34FR0001 (saída de
>   99.999 un. em 30/06, erro de digitação) proporia mínimo 66.666 para um item de mínimo 5.
>
> **A demanda antiga de v6.4.0 (vínculo gestor ↔ requisitante) segue movida para v6.5.0** (seção
> abaixo).

### Épico B — Consumo mensal por vida útil do lote ~~(entregue na v6.4.0)~~ · **REMOVIDO na v6.5.0**

> Substituído pelo **Consumo Mensal por Pedido de Compra (SC7)** — `services/consumo_sc7.py`,
> tabela `consumo_sc7`, card "Consumo/Mensal (SC7)" na Ficha 360. Motivo: a vida útil media o
> giro pelo saldo do almoxarifado e só produziu número para **20 de 362 itens**; o pedido
> atendido mede pela compra que chegou, que é a pergunta do comprador. Ver `changelog/6.5.0.md`.

**Regra (ajustada pelo Luis):** para cada **entrada** (recebimento) de um item, medir quantos
dias o material durou **desde a data que chegou até a data que bateu o mínimo**
(`estoque_minimo`) — **não** até zerar. `consumo_mensal = qtd recebida ÷ dias de duração × 30`.
Independente de CC/setor.

- **Fonte:** `movimentacoes` atuais (FIFO: entrada abre lote, saídas consomem até o estoque
  atingir o mínimo cadastrado; lote vivo = sem data de fim, não conta ou conta parcial).
- **Onde:** função nova em `services/classificacao.py` (padrão `_eventos_item`) + card na
  Ficha 360 ao lado do "Consumo/Mensal". Sem migração de schema (calculado na leitura).
- **Testes:** sem entrada, lote ainda vivo, múltiplos lotes, mínimo zero (usar zerar como
  fallback), ajustes/entradas avulsas.

### Épico C — Sugestão de Min/Max (padrão do lead time calculado)

**Fórmula (travada pelo Luis):** `min = consumo_diário × lead_time do sistema` (≈1 mês);
`max = consumo_diário × 60d` (≈2 meses). Base = `consumo_medio_diario` (o mesmo do ROP).

- **Schema:** colunas novas `minimo_calculado`, `maximo_calculado`, `min_max_amostras`,
  `min_max_origem` — migração aditiva com `_backup_db` antes (padrão `aprovado_*` da v6.2.0).
  NUNCA tocar `estoque_minimo`/`estoque_maximo` (base do Neidson).
- **UI:** Ficha 360 mostra a sugestão (como o lead time); Gerenciar Itens ganha "Usar
  calculado" para min e max (padrão do bloco de lead time, `gerenciar_itens.py:384`) +
  **visão em lote** para "concordamos e torna real" de uma vez.
- **Testes:** migração idempotente, fórmula, bordas (item sem consumo, mínimo cadastrado maior
  que a sugestão), botão em lote.

### Épico D — Gestor: rejeitar requisição + ver a requisição completa

- **Rejeição:** `rejeitar_requisicao(req_id, gestor_nome, motivo)` — grava
  `rejeitado_por`/`rejeitado_em`/`motivo_rejeicao` (migração aditiva com backup, mesmo padrão
  da aprovação v6.2.0). Não cria status novo (mesma filosofia da aprovação não bloqueante);
  a Portaria passa a exibir a rejeição se houver.
- **Ver completa:** o cartão do gestor (`ui/paginas/gestor.py::_cartoes`) ganha um expander
  "Ver requisição completa" com os **itens** (reutilizar `buscar_requisicao_por_numero`/o
  shape com `itens`), para o gestor saber o que o requisitante está pedindo antes de decidir.
- **UI:** botão **Rejeitar** com campo de justificativa ao lado do Aprovar. Na fila consolidada
  (almoxarife) também vale.
- **Testes:** rejeição (motivo obrigatório, requisição inexistente, já rejeitada), exibição na
  Portaria, tela com os dois botões.

### Épico E — Requisitante: checkbox "mostrar saldo" + imagem do material na requisição

1. **Checkbox "mostrar saldo para requisitante"** em Gerenciar Itens → Editar
   (`ui/paginas/gerenciar_itens.py`). **Default marcada em todos os itens.** Desmarcada → o
   requisitante NÃO vê o saldo atual do material (o almoxarife/comprador continuam vendo
   normal). Schema: `inventario.mostrar_saldo_requisitante INTEGER DEFAULT 1` + backfill 1
   (migração aditiva com backup).
   - Pontos de exibição a respeitar: `ui/paginas/movimentacao.py:771` ("DISPONÍVEL") e o
     `saldo hoje` na lista (`movimentacao.py:804`), e equivalentes na tela do Requisitante
     (reusam os mesmos blocos).
2. **Imagem do material na requisição:** ao selecionar o item (`movimentacao.py:766`) e na
   lista de itens da requisição, mostrar a foto via `imagem_path` → `caminho_absoluto_imagem`
   (`services/ficha.py`) → `st.image`. O requisitante confere que é o material certo antes de
   pedir. Sem imagem → não quebra (só não mostra).

- **Testes:** flag desligada esconde saldo nas duas telas; flag ligada mostra; imagem aparece
  quando há `imagem_path`; smoke das telas.

### Épico F — Portaria: buscar pelo nome do requisitante

- `buscar_requisicoes_por_emitente(nome)` em `services/db_functions.py` (case/trim,
  `UPPER(TRIM())`, padrão `buscar_requisicao_por_numero`), devolvendo lista com `itens`.
- `ui/paginas/portaria.py`: além do número, input por **nome** → lista de requisições do
  requisitante → clica e vê o cartão. **Leitura pura** (a Portaria não escreve).
- **Testes:** case/trim, nome vazio, múltiplos resultados, smoke da tela.

### 📋 Escopo travado para a v6.4.0

- **Vínculo gestor ↔ requisitante fica FORA** (movido para v6.5.0 — seção abaixo).
- **Migração da planilha MRO é Épico A** (documento): `docs/prompt_importar_planilha_mro.md`
  — extrair as 402 fotos de `Material MRO 2026.xlsx` e gravar em `docs/itens/` +
  `imagem_path`, casando por PN (961 únicos; só 330 no inventário). Execução por Claude em
  sessão própria, não é parte do código da v6.4.0.
- **Versionamento:** a versão do código (`services/constants.py:VERSAO`) vai para `6.4.0`.
- **Gate:** `.\verify.ps1` verde + validação no app real com o Luis antes de cada commit.

---

## 🔧 DEMANDA ADIADA — v6.5.0 · Gestor escolhido pelo requisitante na requisição (Luis, 03/08/2026)

> **Aberta em 03/08/2026, ADIADA de v6.4.0 para v6.5.0 em 05/08/2026** — a v6.4.0 foi
> preenchida pelas 5 demandas acima. **Decisão do Luis em 05/08/2026:** o gestor é
> **escolhido pelo requisitante a cada requisição** (atributo da requisição), e NÃO um
> vínculo fixo no cadastro do usuário — "o requisitante vai selecionar o gestor, é melhor
> do que vincular". **Substitui** o item "fila do gestor agrupada por solicitante": em vez
> de agrupar por `emitente` ou casar setor × departamento, o pedido **carrega** o seu gestor.

**O problema de raiz:** a fila do gestor hoje casa `requisicoes.setor` com
`usuarios.departamento`, dois vocabulários diferentes — **59 setores × 19 departamentos, com
9 de interseção** (medido no `mro.db` em 02/08/2026). O fluxo novo casa porque a tela do
Requisitante pré-preenche o setor com o departamento, mas isso é coincidência mantida à mão,
não vínculo.

**Como deve ficar:** ao criar a requisição, o requisitante **seleciona o gestor** (campo
novo no bloco de identificação). A fila do gestor passa a ser "os pedidos **que me marcaram
como gestor**" — exato, independente de como o setor foi grafado.

**Esboço (detalhar em plano próprio, com AskUserQuestion antes):**
- `requisicoes.gestor` — TEXT nullable (nome do gestor, grafia como o `emitente`).
  Migração **aditiva**, com `_backup_db` antes (padrão `aprovado_*` da v6.2.0). Sem backfill:
  `NULL` = "sem gestor marcado" (o legado fica de fora da fila do gestor, alcançável pelo
  filtro de setor — mesma negativa por omissão do setor vazio).
- **Seletor "Gestor" no bloco de identificação da requisição** (`ui/paginas/movimentacao.py`
  `_req_bloco_identificacao`), pré-preenchido e editável, listando usuários ativos com papel
  `gestor` (via `services/usuarios`). O Requisitante (tela própria) também usa o mesmo bloco.
- Fila do gestor = requisições cujo `gestor` == nome do gestor logado (match `UPPER(TRIM())`,
  mesmo padrão de `buscar_requisicao_por_numero`/`listar_requisicoes(emitente=...)`). A tela
  do Requisitante já trava o emitente no nome da sessão; o gestor pode ser gravado no mesmo
  padrão (nome digitado no seletor ou id? decidir no plano — **preferência: guardar o nome**,
  coerente com `emitente`, `aprovado_por`).
- O filtro por **setor** vira **visão alternativa** (não some): serve ao gestor com pedidos
  legados sem gestor marcado e a quem precisa acompanhar outra área.
- A **Portaria** passa a exibir o gestor da requisição.

⚠️ **Pergunta aberta para o plano:** guardar o **nome** do gestor (`requisicoes.gestor` TEXT,
coerente com `emitente`/`aprovado_por`) ou o **id** (`requisicoes.gestor_id` INTEGER, mais
estável a renomeações)? O Luis escolheu o modelo "selecionar a cada pedido"; a coluna em si
ainda decide-se no plano.

---

## 🟡 EM VALIDAÇÃO — v6.3.0 · Fila de aprovação consolidada para o admin

> **Implementada em 03/08/2026**, gate verde. Ver `changelog/6.3.0.md`. Resolve o item nº1 do
> feedback do Luis sobre a v6.2.0: o papel `almoxarife` abre **Aprovações do Setor** com a
> fila de **todos os setores** e um filtro de setor opcional. **Sem migração de schema.**
>
> **Decisões travadas em 03/08/2026 (Luis):**
> - O filtro lista **só os setores que têm pedido na fila**, com contagem — não os ~60
>   setores conhecidos, em que quase toda opção devolveria lista vazia.
> - Com `exigir_login` **desligada** a tela fica **como estava** (ramo simulação, escolher
>   setor): a fila consolidada é do almoxarife **autenticado**.
> - `listar_requisicoes_por_setor` **não foi afrouxada** — o consolidado é a função irmã
>   `listar_requisicoes_para_aprovacao()`, sem parâmetro de setor. A negativa por omissão do
>   gestor segue fixada por teste, agora em dois arquivos.
>
> **Falta:** validação no app real → OK do Luis → commit → `graphify update .`.

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
