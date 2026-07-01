# Blueprint — Sistema MRO como Plataforma de Inteligência de Materiais (rev. 3)

> **Natureza deste documento:** visão/arquitetura (blueprint). Não contém código. Cada pilar será planejado e aprovado separadamente, conforme o fluxo das 9 skills.
>
> **Rev. 2** incorporou o feedback do PO e a análise da planilha **Relatório de SCs 30.06.xlsx** (fonte muito mais rica que o export cru do SCM). **Rev. 3** revê a decisão de snapshots de estoque: após verificação empírica no `mro.db` real, **adotamos `estoque_snapshots`** e corrigimos a raiz das "quebras" do ledger (ver seções 1.5, 1.8 e 6).
>
> Referência interna do planejamento: `~/.claude/plans/velvet-swinging-duckling.md`.

---

## Contexto

A falta de material MRO **não** decorre de deixar de solicitar, e sim do gargalo entre a abertura da SC e a compra efetiva: 2 compradores indiretos (Davi — Manutenção/Engenharias ~300 itens/SC; Miguel — Almoxarifado/SSO/Qualidade ~83 itens/SC) + estagiária (Adrya). Cada item MRO exige tratativa específica. O comprador perde tempo procurando dados dispersos e retornando dúvidas ao Almoxarifado.

**Objetivo:** evoluir o Sistema MRO para uma **plataforma de planejamento e inteligência de materiais** que (a) entregue tudo "mastigado" por SC/item; (b) atue como **assistente** que *recomenda* o que/quando/quanto comprar, com justificativa, fornecedor e agrupamento sugeridos — mantendo a decisão final com o comprador; (c) garanta o lema: **nunca deixar faltar material**, sem excesso de estoque.

---

## Princípios norteadores (definidos pelo PO)

1. **Assistente, não piloto automático.** O sistema *recomenda*; o comprador decide e cria a SC.
2. **Transparência total dos cálculos.** Todo indicador calculado deve ser **explicável em uma frase**. Sempre exibir: origem do dado, como foi calculado e o nível de precisão esperado.
3. **Base do Neidson é a referência inicial.** Mín/Máx/Categoria/Lead Time revisados pelo Sr. Neidson são a verdade de partida. Cálculos automáticos **nunca sobrescrevem** essa base — eles **sugerem** (ex.: *"Lead Time calculado: 18d · cadastrado: 30d · Atualizar?"*) e o humano valida.
4. **Simplicidade primeiro, sofisticação depois.** Começar simples (ex.: estoque de segurança manual) e evoluir para cálculo automático só quando os dados se mostrarem confiáveis.
5. **Vocabulário da operação.** Usar os termos que a equipe já usa (ex.: **"Guarda-Chuva"** em vez de "estoque em trânsito").
6. **Fundação de dados antes de automação.** Dados corretos → cálculos confiáveis → regras bem definidas → só então automatizar decisões.

---

## Ajustes de conceito solicitados pelo PO

### Estoque de Segurança → parâmetro operacional manual (inicialmente)
Hoje o código calcula `consumo × lead_time × 1,5`. **Mudança:** passa a ser um **valor manual sugerido pelo gestor (Sullyvan)**, situado **entre o Mínimo e o Máximo**. O cálculo automático fica como **sugestão futura**, quando validado. (Impacto: `estoque_seguranca` vira campo editável de negócio; a fórmula atual deixa de ser a fonte primária.)

### Estoque em Trânsito → "Guarda-Chuva"
Renomear o conceito para o termo do Miguel. Definição: **quantidade que ainda falta ser entregue de um material já negociado**. Isso mapeia exatamente para `Saldo PO` (aba FUP) e `Saldo` (abas SCM/SC7) = `Qtd Pedido − Qtd Entregue`. (Hoje o sistema calcula algo equivalente via Σ `saldo_residual` de `itens_sc`; vamos alinhar o cálculo e o rótulo a este conceito.)

### Cálculos como apoio à decisão (padrão "calculado vs cadastrado")
Aplicar a Lead Time, Mínimo, Máximo, Estoque de Segurança e Ponto de Pedido: o sistema mostra lado a lado o valor **cadastrado (Neidson)** e o **calculado**, e oferece atualização opcional. Nada é alterado sem confirmação.

---

## Fonte de dados central: **Relatório de SCs** (planilha diária dos compradores)

A planilha é atualizada **diariamente** e concentra muito mais inteligência que o export cru do SCM. Proposta: tratá-la como **fonte primária de ingestão**, com um pipeline por aba. Mapa das abas:

| Aba | Linhas × Col | Papel | Uso no Sistema MRO |
|---|---|---|---|
| **SCM** | 15.381 × 49 | Base das SCs (SC-nível) — **inclui preço** | Fonte de SCs; **captura `Prc Unitario`, `Vlr.Total`, `Moeda`, `Saldo`, `Qtd.Entregue`**; comprador, departamento, justificativa, datas NFe. **Fonte-verdade de SC.** |
| **FUP 2026** | 5.149 × 42 | Follow-up diário dos compradores | Enriquecer com **`Saldo PO` (Guarda-Chuva)**, **`Dias LT`**, `Aging`, `Criticidade`, **`E-Mail` fornecedor**, `Status PO`, `ETD/ETAF`, `VALOR NEGOCIADO/COTADO`, `SAVING`. |
| **CRÍTICOS** | 37 × 20 | Lista crítica **manual** (Juan) | **Referência para auto-gerar** a lista: usa `Esgotado em:` (data ruptura) e `Faltando a (Dias)` (cobertura). Validar nosso cálculo contra a lista do Juan. |
| **SC7** | 40.838 × 37 | **Pedidos de Compra (POs)** — Protheus SC7 | **Histórico de POs e de preços por produto** (cabeçalho na linha 3; `Observacoes` liga "SC: xxxxx"). Base do histórico de preço/lead time. **Cuidar de duplicação com SCM (ver regra abaixo).** |
| **SCM USERS** | 98 × 12 | Solicitante → Depto → Gerente → Aprovador → Status | **Filtro dinâmico de solicitantes MRO** (substitui a lista fixa no código) + enriquecimento de departamento/aprovador. |
| **FORNECEDORES** | 3.614 × 276 | Cadastro de fornecedores (Protheus SA1) | **Fornecedor mestre**: Código, Loja, Razão Social, N Fantasia, CNPJ, Cond. Pagto e **e-mails** (`E-Mail`, `E-Mail Repr.`, `Forn.Mailing`, `Email Addres`). Habilita cotação. |
| **Data Base** | 35 × 11 | Painel/pivot manual do Miguel (Status PO × Comprador + tarefas) | **Derivar**, não importar (o próprio sistema produzirá esse painel). |
| **Spot Saving** | 37 × 23 | Savings negociados (R$ 4,7M em 2025) | KPI para dashboards de Gestão/Diretoria. |
| Planilha1 / Planilha2 / AÇÃO-CC / NRE | pequenas | Rascunhos/notas de trabalho | Ignorar na ingestão. |

**Regra anti-duplicação (Data Engineer):** `SCM` = verdade de SC (uma SC/item). `SC7` = histórico de POs (vários POs por produto ao longo do tempo) — usar **apenas** para `precos_historico` e histórico de POs, deduplicando por `Pedido + Item`. `FUP` = camada de *enriquecimento* (Guarda-Chuva, Dias LT, e-mail, saving), casada por número da SC. Nunca criar SC a partir de SC7/FUP.

**A confirmar (planejamento da v2.2):** modelo de upload — recomendado **um único upload diário do .xlsx**, com o sistema roteando cada aba para seu pipeline (idempotente, com auditoria em `log_importacoes` e backup automático). Manter o import atual do SCM como fallback.

---

## Estado atual (v2.1.0) — o que já existe e é confiável

Stack: **Streamlit + SQLite (WAL, FKs) + Plotly**, monolítico (`app.py` ~1775 linhas; `db_functions.py` ~1733). Migrações não-destrutivas padronizadas.

- **Cálculos existentes:** consumo médio diário (30d), previsão de ruptura (`estoque/consumo`), estoque de segurança (fórmula — **será substituída por campo manual**), estoque máximo (default mín×2), "em trânsito" (Σ saldo_residual — **vira Guarda-Chuva**), status 🔴/🟡/🟢, ABC top 10, aging de SC, consumo por CC/emitente/setor/período.
- **Compras:** 6 abas (Monitor, Nova SC, Receber, Atualizar Status, Histórico, Importar Protheus). Monitor já prioriza por ruptura→criticidade→aging.
- **Importação Protheus** funcional, mas **baseada no export cru** (sem preço; solicitantes fixos).
- **Rastreabilidade:** movimentações completas; alteração de PN com histórico (`part_numbers_historico`).
- **Código morto a ativar:** `_recalcular_lead_time_real()` (db_functions.py:1384) existe e **nunca é chamado**.

---

## 1. Modelo de Dados Alvo (evolução aditiva, não-destrutiva)

### 1.1 Guarda-Chuva & Estoque de Segurança
- `inventario.estoque_seguranca` passa a ser **campo manual de negócio** (valor do gestor, entre mín e máx). Guardar `estoque_seguranca_calculado` separado (sugestão, não aplicado).
- Padronizar cálculo do **Guarda-Chuva** = Σ (`quantidade_pedido − quantidade_recebida`) dos itens de SC abertos, exibido com esse rótulo.

### 1.2 Pilar Financeiro (do SCM/SC7)
- `itens_sc`: `preco_unitario REAL`, `valor_total REAL`, `moeda TEXT DEFAULT 'BRL'`.
- **`precos_historico`** `(id, item_id, data, preco_unitario, moeda, fornecedor, numero_sc, numero_po, origem)` — alimentado por SCM/SC7 → histórico e evolução de preço.
- `inventario`: `preco_referencia REAL`, `data_preco_ref` (cache p/ valoração).
- **Transparência:** toda tela de valor exibe origem (SCM/SC7), método (último/médio) e ressalva de precisão ("estimativa baseada em SCM").

### 1.3 Fornecedor mestre (da aba FORNECEDORES)
- **`fornecedores`** `(id, codigo, loja, razao_social, nome_fantasia, cnpj, email, email_repr, telefone, contato, cond_pagto, ativo)`. Chave `codigo+loja`.
- **`fornecedor_item`** (relação material↔fornecedor, com último preço e lead time observados) para "melhor fornecedor".

### 1.4 Solicitantes dinâmicos (da aba SCM USERS)
- **`solicitantes_mro`** `(nome, departamento, gerente, aprovador, status, incluir_mro)` — substitui a constante fixa `SOLICITANTES_MRO`; manutenível pela tela.

### 1.5 Indicadores históricos (giro / tempo em estoque) → **`estoque_snapshots`** (decisão revista)
Verificação empírica no `mro.db` real mostrou que **reconstruir pelo `saldo_apos` é frágil** (ver seção 6). Portanto:
- **Nova tabela `estoque_snapshots`** `(item_id, data, estoque_atual, valor_estoque)` — uma "foto" diária do saldo por item (idempotente por dia). Cobre 100% dos itens, é imune à semântica de movimentos e permite explicar **estoque médio = média das fotos do período**. Também habilita a **evolução do valor imobilizado** ao longo do tempo (ótimo p/ Diretoria).
- **Gatilho sem scheduler externo:** tirar a foto **junto do import diário do Relatório de SCs** (que já é hábito) e/ou na 1ª abertura do app no dia — grava só se ainda não houver foto de hoje.
- Retenção configurável (ex.: 24 meses). ~360 itens/dia ≈ 130k linhas/ano — trivial para SQLite.

### 1.6 Suporte à recomendação
- `inventario`: `embalagem_multiplo REAL`, `horizonte_cobertura_dias INTEGER DEFAULT 60` (regra operacional dos ~2 meses), `ponto_pedido REAL` (cache).
- **`sugestoes_reposicao`** `(id, item_id, data_geracao, qtd_sugerida, cobertura_dias, ponto_pedido, fornecedor_sugerido, agrupamento, prioridade, justificativa, status['Pendente'|'SC criada'|'Ignorada'], sc_id?)`.
- **Ficha 360:** `inventario.imagem_path TEXT` (imagem do produto até ~3 MB, armazenada em pasta `docs/itens/` referenciada por caminho — evita inchar o SQLite).

### 1.7 Índices faltantes
`itens_sc(item_id)`, `solicitacoes_compra(status)`, `precos_historico(item_id)`, `fornecedores(codigo,loja)`, `estoque_snapshots(item_id, data)`.

### 1.8 Integridade do ledger (corrigir a raiz das "quebras")
Hoje `salvar_item` altera `estoque_atual` **direto, sem gerar movimento** — origem das quebras de continuidade observadas. **Correção:** toda mudança de saldo deve passar por `registrar_movimentacao` (com `saldo_apos` correto); o formulário de edição deixa de escrever `estoque_atual` diretamente. Isso mantém o histórico limpo daqui para frente (independente dos snapshots).

---

## 2. Catálogo de Cálculos e Indicadores (com explicação "de uma frase")

Legenda: ✅ existe · 🔁 ativar/ajustar · 🆕 novo. Cada indicador terá tooltip explicando fonte + fórmula + precisão.

| Indicador | Fórmula / definição | "Explique em 1 frase" | Status |
|---|---|---|---|
| Consumo médio diário | Σ saídas(janela)/dias; janela **30/60/90** | "Média do que saiu por dia nos últimos N dias." | 🔁 |
| Dias de cobertura | `(estoque + guarda_chuva) / consumo_diário` | "Quantos dias o estoque dura no ritmo atual." | 🆕 |
| Previsão de ruptura | `estoque / consumo_diário` | "Em quantos dias zera se nada chegar." | ✅ |
| Guarda-Chuva | Σ(qtd_pedido − qtd_entregue) em SCs abertas | "O que já foi comprado e ainda vai chegar." | 🔁 |
| Ponto de Pedido | `consumo_diário × lead_time + seg.` | "Nível em que já se deve comprar." | 🆕 |
| Lead Time Real | média(recebimento − abertura SC) | "Quanto o fornecedor realmente demorou." | 🔁 (ativar como sugestão) |
| Lead Time por fornecedor | idem, agrupado | "Quem entrega mais rápido." | 🆕 |
| Tendência de consumo | consumo(30d) vs 30d anteriores → ↑/→/↓ % | "Se o consumo está subindo ou caindo." | 🆕 |
| Classificação XYZ | coef. de variação do consumo mensal | "Se a demanda é estável ou errática." | 🆕 |
| Curva ABC | ranking por **valor consumido** (qtd×preço) | "Os poucos itens que somam a maior parte do gasto." | 🔁 |
| Giro de estoque | consumo_período / estoque médio (via snapshots) | "Quantas vezes o estoque se renova." | 🆕 |
| Tempo médio em estoque | `365 / giro` | "Quanto tempo, em média, o item fica parado." | 🆕 |
| Valor em estoque | `estoque × preço_ref` (rótulo: estimativa SCM) | "Quanto dinheiro está parado nesse item." | 🆕 |
| Valor consumido | Σ(saídas × preço vigente) | "Quanto se gastou consumindo o item." | 🆕 |
| Evolução de preço | série de `precos_historico` | "Como o preço variou ao longo do tempo." | 🆕 |
| Qtd sugerida de compra | ver Regra 3.2 | "Quanto comprar para cobrir ~2 meses." | 🆕 |

---

## 3. Regras de Negócio (Supply Chain)

### 3.1 Quando recomendar SC
`posição = estoque + guarda_chuva + já_solicitado(SC aberta)`; recomendar quando `posição ≤ ponto_pedido`. Priorizar itens com `cobertura ≤ lead_time + 15 dias` (garante os **15 dias de antecedência**).

### 3.2 Quanto comprar
`qtd_alvo = consumo_diário × horizonte(60d) − (estoque + guarda_chuva + já_solicitado)`; arredondar a `embalagem_multiplo`; respeitar `estoque_maximo`; críticos podem usar colchão maior. **60 dias = regra operacional dos ~2 meses.**

### 3.3 Justificativa automática ("mastigada")
Template com: criticidade, consumo médio, cobertura atual, ruptura prevista, lead time, departamentos/CCs consumidores, última compra (data/fornecedor/preço), motivo ("reposição planejada").

### 3.4 Fornecedor sugerido & agrupamento
Sugerir fornecedor a partir de `fornecedor_item` (último preço + lead time + melhor histórico) com **e-mail** pronto para cotação; **agrupar** recomendações por fornecedor/categoria para reduzir nº de SCs.

### 3.5 Críticos automáticos (substituir a lista manual do Juan)
Gerar candidatos por: dias de cobertura baixos, ruptura prevista, criticidade (Parada de Linha), lead time longo e consumo. **Validar** contra a aba CRÍTICOS antes de confiar.

### 3.6 Excesso de estoque
Sinalizar cobertura muito acima do horizonte + baixo giro → evitar compra e reduzir capital imobilizado.

---

## 4. Funcionalidades / Módulos

- **Assistente de Reposição (recomendar):** lista priorizada com o que/quando/quanto/justificativa/fornecedor/agrupamento/prioridade; botão **"Criar SC"** reaproveita o fluxo Nova SC. Registra desfecho em `sugestoes_reposicao`.
- **Ficha 360 do Material** (somente leitura): **imagem do produto (~3 MB)**, cadastro, estoque/mín/máx/segurança, cobertura, consumo (gráficos) + tendência, lead time real vs cadastrado, histórico de movimentações/SCs/POs/preços, últimos fornecedores, ABC/XYZ, CCs/departamentos consumidores, histórico de PN.
- **Busca de Fornecedores por Material:** dados cadastrais, e-mails, histórico de compras, último preço, lead time, melhor fornecedor — para acelerar cotação.
- **Pilar Financeiro:** valor em estoque/consumido (com rótulos de origem/precisão), evolução de preço, ABC por valor, savings.
- **Dashboards por público:** Comprador (fila + sugestões + aging + rupturas), Gestão (nível de serviço, cobertura, valor, giro, savings), Diretoria (valor imobilizado, evolução, economia).

---

## 5. Roadmap Faseado (proposto)

| Versão | Pilar | Entrega |
|---|---|---|
| **v2.2.0 — Fundação de Precisão & Ingestão Rica** | Dados/Cálculos | Ingestão do **Relatório de SCs** (SCM c/ preço, FUP p/ Guarda-Chuva + Dias LT, SCM USERS dinâmico); **Guarda-Chuva** (rótulo+cálculo); **Estoque de Segurança manual**; ativar **Lead Time Real como sugestão**; consumo 30/60/90 + tendência; **dias de cobertura**; **`estoque_snapshots`** (giro/tempo em estoque) + correção da integridade do ledger; padrão "calculado vs cadastrado" + tooltips de transparência (com rótulo de maturidade de histórico) |
| **v2.3.0 — Pilar Financeiro** | Custo | `precos_historico` (SCM/SC7); valor em estoque/consumido (rotulado); evolução de preço; ABC por valor; savings (Spot Saving) |
| **v2.4.0 — Fornecedores & Cotação** | Compras | `fornecedores` mestre (e-mails); busca material→fornecedores/último preço/lead time/melhor fornecedor |
| **v2.5.0 — Assistente de Reposição** | Planejamento | ROP, qtd sugerida, justificativa, fornecedor/agrupamento/prioridade, "Criar SC" |
| **v2.6.0 — Ficha 360 do Material** | Rastreabilidade | Página consolidada por item (com imagem) |
| **v2.7.0 — Críticos automáticos, XYZ & Sazonalidade** | Inteligência | Auto-gerar lista de críticos (validar vs Juan); XYZ; sazonalidade |
| **v3.0.0 — Dashboards por público** | Decisão | Comprador / Gestão / Diretoria |

**Ordem confirmada pelo PO:** iniciar pela **v2.2 (fundação)** — nenhuma inteligência é confiável sem dados/cálculos sólidos.

---

## 6. Estoque Snapshots — decisão revista com base em dados reais

**O que é e por que importa:** uma "fotografia" diária do saldo de cada item, para calcular médias ao longo do tempo. **Giro** e **tempo médio em estoque** precisam do *estoque médio do período*, que o saldo atual sozinho não fornece.

**Antes** havia a proposta de *não* criar a tabela e reconstruir o histórico pelo `saldo_apos` das movimentações. **A verificação no `mro.db` real (30/06/2026) mostrou que isso é frágil:**

| Evidência | Impacto na reconstrução por `saldo_apos` |
|---|---|
| **16% dos itens (57/360) sem nenhuma movimentação** | Sem série histórica para esses itens |
| **Quebras de continuidade** (ex.: `30UC0048`=6, `30UC0010`=3) | O `saldo_apos` "pula" sem delta → série intermediária não confiável |
| `salvar_item` altera estoque **sem gerar movimento** | Raiz das quebras; edições diretas ficam invisíveis no ledger |
| Histórico de apenas **~2,5 meses** (16/04→30/06) | Base curta; qualquer método ainda é aproximado por ora |

**Decisão:** **adotar `estoque_snapshots`** (foto diária idempotente). Vantagens: cobre 100% dos itens, é imune à semântica de movimentos (ajuste físico, conferência qtd 0, recebimento, requisição) e é **fácil de explicar** — "estoque médio = média das fotos do período" — atendendo ao princípio de transparência. Sem scheduler externo: a foto é tirada junto do import diário (que já é rotina) ou na 1ª abertura do dia. Em paralelo, corrigimos a raiz (seção 1.8) para o ledger não gerar mais quebras.

### Nota de maturidade de histórico (transparência)
Como só há **~2,5 meses** de dados, **giro, tempo em estoque, tendência, sazonalidade, XYZ e lead time real** começarão **rotulados** ("baseado em N dias de histórico") e ganharão confiança conforme os dados acumulam. Isso reforça os princípios do PO: cálculos como **apoio à decisão** que **evoluem com o tempo**, sempre com validação humana e sem sobrescrever a base do Neidson.

---

## 7. Riscos & Impactos (multidisciplinar)

- **Database Engineer:** mudanças aditivas, idempotentes, com backup automático. `estoque_seguranca` muda de semântica (calc→manual) — migrar preservando valores atuais como ponto de partida. Adicionar índices antes das telas pesadas.
- **Data Engineer:** confirmar nomes/posições exatas das colunas por aba (nomes com acento/mojibake); dedupe SCM×SC7; normalizar fornecedores (código+loja) e e-mails; tratar valores do SCM como **estimativa rotulada**.
- **Backend:** ativar `_recalcular_lead_time_real` (como sugestão); **fechar o gap do `salvar_item`** (toda mudança de saldo via `registrar_movimentacao`); **modularizar** `db_functions.py` (ex.: `services/ingestao.py`, `calculos.py`, `planejamento.py`, `compras.py`).
- **Maturidade de dados:** ~2,5 meses de histórico hoje → indicadores dependentes de série (giro, tendência, sazonalidade, XYZ, lead time real) começam rotulados e amadurecem; 16% dos itens sem movimento passam a ter série via `estoque_snapshots`.
- **Software Architect:** `app.py`/`db_functions.py` grandes → modularização transversal para manutenção de longo prazo.
- **UX/UI:** transparência (tooltips origem+fórmula+precisão); menos cliques (selecionar→"Criar SC"); imagem na Ficha 360; visões por público.
- **QA:** ampliar a suíte (hoje 96) com ROP, qtd sugerida, lead time real, histórico de preço, tendência, ingestão por aba, dedupe; regressão dos cálculos atuais; validar críticos automáticos contra a lista do Juan.
- **DevOps:** ingestão diária idempotente + auditoria + backup; bump de versão + changelog por release; armazenamento de imagens em pasta (fora do .db).
- **Product Owner:** manter **recomendar, não criar sozinho** e a **não-sobrescrita da base do Neidson**.

---

## 8. Próximos passos

A implementação começa, recomendadamente, pela **v2.2 — Fundação de Precisão & Ingestão Rica**, planejada e aprovada à parte (com User Stories, critérios de aceite e testes definidos antes de qualquer código), conforme o fluxo das 9 skills.
