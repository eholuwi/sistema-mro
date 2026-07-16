lueprint — Sistema MRO como Plataforma de Inteligência de Materiais
Natureza desta entrega: documento de visão/arquitetura (blueprint). Nenhum código será escrito nesta etapa. Após aprovação, a única ação é persistir este blueprint como documento oficial no repositório (sistema-mro/docs/) e registrar a referência na memória do projeto. A implementação de cada pilar virá em releases futuras, cada uma passando pelo fluxo de aprovação das 9 skills.

Contexto
A falta de material no Almoxarifado MRO não decorre de deixar de solicitar, e sim do gargalo entre a abertura da SC e a compra efetiva: 2 compradores indiretos (Davi e Miguel) + estagiária (Adrya) atendem carteiras gigantes (Manutenção ~300 itens/SC; Almoxarifado ~83 itens/SC), e cada item MRO exige tratativa específica (rateio entre departamentos, fornecedores, lead times e criticidades distintos). O comprador perde tempo procurando informação em planilhas e retornando dúvidas ao Almoxarifado.

Objetivo: evoluir o Sistema MRO de um controle de estoque para uma plataforma de planejamento e inteligência de materiais que (a) entregue ao comprador tudo "mastigado" por SC/item, (b) preveja necessidades e recomende a abertura de SCs com ~15 dias de antecedência e cobertura de ~2 meses, e (c) garanta o lema operacional: nunca deixar faltar material, sem gerar excesso de estoque.

Resultado pretendido: redução de rupturas e de compras emergenciais, maior previsibilidade e rastreabilidade por item (visão de "vida útil" do material), e decisões de compra baseadas em dados confiáveis.

Estado Atual (v2.1.0) — o que já existe e é confiável
Stack: Streamlit + SQLite (WAL, FKs on) + Plotly, monolítico (app.py ~1775 linhas, services/db_functions.py ~1733 linhas). Migrações não-destrutivas já padronizadas (_migrar, rebuild seguro, _backup_db).

Já implementado e em uso:

Cálculos: consumo médio diário (janela 30d — _recalcular_consumo, db_functions.py:298), previsão de ruptura (estoque_atual / consumo_diário, db_functions.py:237), estoque de segurança (consumo × lead_time × 1,5), estoque máximo (default mín × 2), estoque em trânsito (Σ saldo_residual de itens de SC), status material 🔴/🟡/🟢 (calcular_status_inventario, db_functions.py:30).
Analytics: Curva ABC (top 10), aging de SC (7/15 dias), ruptura histórica (90d), consumo por centro de custo / emitente (colaborador) / setor / período (já disponível em movimentacoes).
Compras (SC): 6 abas (Monitor, Nova SC, Receber, Atualizar Status, Histórico, Importar Protheus). O Monitor já mostra muito do "mastigado" (importância, ruptura, aging, fornecedor, PO, prev. NF, justificativa), priorizado por ruptura→criticidade→aging.
Importação Protheus/SCM robusta (importar_solicitacoes_protheus, db_functions.py:657): normaliza colunas, filtra por solicitantes MRO, status e palavras críticas; faz upsert em solicitacoes_compra/itens_sc; marca ruptura/divergência/prioridade crítica; auditoria em log_importacoes.
Rastreabilidade: histórico de movimentações completo; alteração de Part Number com histórico (part_numbers_historico) ligando tudo por item_id (PN antigo continua pesquisável).
Lacunas confirmadas (vs. a visão):

Sugestão automática de reposição / quantidade de compra — não existe (peça central).
Ficha 360 do material (página única consolidando histórico + indicadores de um item) — não existe; os dados existem, porém dispersos.
Lead Time Real — _recalcular_lead_time_real() (db_functions.py:1384) existe mas nunca é chamado (código morto a ativar).
Tendência de consumo, sazonalidade, classificação XYZ, giro de estoque, tempo médio em estoque, dias de cobertura explícito — não existem.
Preço/custo/valor — não há modelo de dados (valor em estoque/consumido, histórico de preço, melhor fornecedor bloqueados).
Fornecedor mestre — apenas texto livre em fornecedor/fornecedor_item.
Decisões desta rodada (Product Owner)
Tema	Decisão
Entregável agora	Somente o blueprint (sem código)
Dados de custo	Preço unitário vem no relatório SCM/Protheus → pilar financeiro é viável (basta capturar a coluna)
Confiabilidade do consumo	Toda saída é registrada → podemos confiar no consumo e automatizar previsões
Comportamento da sugestão	Recomendar — lista priorizada com qtd/justificativa; humano decide e cria a SC
1. Modelo de Dados Alvo (evolução incremental, não-destrutiva)
Todas as mudanças seguem o padrão atual (ALTER TABLE ADD COLUMN / novas tabelas / _migrar idempotente + _backup_db). Nada de DROP/rename de colunas em produção.

1.1 Pilar Financeiro (custo/preço) — habilitado pelo Protheus
itens_sc: adicionar preco_unitario REAL DEFAULT 0, valor_total REAL DEFAULT 0, moeda TEXT DEFAULT 'BRL' — preenchidos na importação Protheus/recebimento.
Nova tabela precos_historico (id, item_id FK, data, preco_unitario, fornecedor, numero_sc, numero_po, origem) — 1 linha por preço observado (importação/recebimento) → histórico e evolução de preço.
inventario: cache preco_referencia REAL, data_preco_ref TEXT (último/médio preço) para valoração rápida.
⚠️ A confirmar (Data Engineer): o nome exato da coluna de preço no export SCM (ex.: "Valor Unitário", "Preço Unitário", "Vlr. Unit", "Total do Item"). O importador atual não mapeia preço hoje — será adicionado ao _coluna().
1.2 Fornecedor mestre
Nova tabela fornecedores (id, nome, nome_fantasia, cnpj?, lead_time_medio_dias, ativo) populada a partir das importações; futuramente itens_sc.fornecedor_id (FK) sem remover o texto livre atual (compatibilidade). Habilita "melhor fornecedor" e "lead time por fornecedor".
1.3 Histórico para giro/tendência/tempo em estoque
Nova tabela estoque_snapshots (item_id, data, estoque_atual, valor_estoque) — fotografia periódica (1×/dia, idempotente por dia) para calcular estoque médio, giro e tempo médio em estoque. Retenção configurável (ex.: 24 meses).
Agregado mensal de consumo (tabela ou view materializada) para tendência, sazonalidade e XYZ sem varrer todo o histórico a cada tela.
1.4 Suporte à recomendação
inventario: embalagem_multiplo REAL (lote de compra), horizonte_cobertura_dias INTEGER DEFAULT 60 (override por item; default global = 60), ponto_pedido REAL (cache do ROP).
Nova tabela sugestoes_reposicao (id, item_id, data_geracao, qtd_sugerida, cobertura_dias, ponto_pedido, justificativa, status['Pendente'|'SC criada'|'Ignorada'], sc_id?) — registra cada recomendação e seu desfecho (auditoria + aprendizado).
1.5 Índices faltantes (performance — Database Engineer)
itens_sc(item_id) (achar todas as SCs de um item — ficha 360), solicitacoes_compra(status), precos_historico(item_id), estoque_snapshots(item_id, data).
2. Catálogo de Cálculos e Indicadores (definição alvo)
Legenda: ✅ existe · 🔁 existe mas precisa ativar/ajustar · 🆕 novo.

Indicador	Fórmula alvo	Status
Consumo médio diário	Σ saídas(janela) / dias da janela; janela configurável 30/60/90	🔁 (hoje fixo 30)
Tendência de consumo	consumo(30d atuais) vs consumo(30d anteriores) → Alta/Estável/Queda + %	🆕
Sazonalidade	perfil de consumo por mês (requer ≥12–18 meses)	🆕 (depende de histórico)
Classificação XYZ	coef. de variação do consumo mensal → X/Y/Z (estável→errático)	🆕
Curva ABC	ranking por valor consumido (qtd × preço) — hoje por qtd	🔁 (melhorar com preço)
Dias de cobertura	(estoque_atual + em_trânsito) / consumo_diário (explícito)	🆕
Previsão de ruptura	estoque_atual / consumo_diário	✅
Estoque mínimo/máximo/segurança	min (apurado Neidson) · máx · consumo×LT×1,5	✅ (revisar)
Ponto de pedido (ROP)	consumo_diário × lead_time + estoque_segurança	🆕
Lead time real	média (recebimento − abertura da SC) por item	🔁 (ativar função existente)
Lead time por fornecedor	idem agrupado por fornecedor	🆕
Tempo médio em estoque	365 / giro (aprox.)	🆕
Giro de estoque	consumo_período / estoque_médio (via snapshots)	🆕
Valor em estoque	estoque_atual × preço_referência	🆕 (custo)
Valor consumido	Σ(saídas × preço vigente) por período	🆕 (custo)
Evolução de preço	série temporal de precos_historico	🆕 (custo)
Qtd sugerida de compra	ver Regra 3.2	🆕
3. Regras de Negócio (Supply Chain Specialist)
3.1 Quando recomendar uma SC
Disparar recomendação quando a posição de estoque projetada cair no/abaixo do ponto de pedido considerando 15 dias de antecedência:

posição = estoque_atual + em_trânsito + já_solicitado(SC aberta) Recomendar quando posição ≤ ponto_pedido, onde ponto_pedido = consumo_diário × lead_time + estoque_segurança. A antecedência de 15 dias é garantida porque o ROP embute o lead time; itens com dias_de_cobertura ≤ lead_time + 15 entram como prioridade.

3.2 Quanto comprar (quantidade sugerida)
qtd_alvo = consumo_diário × horizonte_cobertura(60d) − (estoque_atual + em_trânsito + já_solicitado) Ajustes: arredondar para embalagem_multiplo; respeitar estoque_maximo (não ultrapassar); nunca negativo; itens críticos (Parada de Linha) podem usar horizonte/colchão maior.

3.3 Justificativa automática (template "mastigado")
Gerar texto padrão por item: criticidade, consumo médio, dias de cobertura atuais, ruptura prevista, lead time, departamentos/CCs consumidores (top N), última compra (data/fornecedor/preço) e motivo ("reposição planejada — cobertura abaixo do ponto de pedido").

3.4 Agrupamento / racionalização (reduzir nº de SCs)
Agrupar recomendações por fornecedor e/ou categoria para sugerir SCs consolidadas — endereça diretamente o gargalo de "muitos itens por SC" e a pergunta "dá para agrupar com outra categoria?".

3.5 Excesso de estoque
Sinalizar itens com dias_de_cobertura muito acima do horizonte (ex.: > 2× máximo) e baixo giro → evitar novas compras e reduzir capital imobilizado.

4. Funcionalidades / Módulos
4.1 Planejamento de Reposição (motor de recomendação) — modo recomendar
Nova página: lista priorizada (ruptura asc → criticidade → valor) de "itens a comprar", cada linha com qtd sugerida + cobertura + justificativa + última compra. Ações: selecionar itens → "Criar SC" (reaproveita criar_sc/aba Nova SC, pré-preenchendo qtd e justificativa). Cada recomendação é registrada em sugestoes_reposicao com desfecho. Humano sempre decide.

4.2 Ficha 360 do Material (visão de "vida útil")
Nova página acessível pelo PN (Inventário/busca), somente leitura, consolidando: cadastro + estoque/cobertura; indicadores (giro, tempo em estoque, ABC/XYZ, lead time real vs planejado); gráfico de consumo mensal + tendência; histórico de movimentações; SCs/POs/recebimentos do item; histórico de preços; consumo por CC/colaborador/setor; histórico de Part Number. Reusa funções existentes + novos agregadores (obter_ficha_item, listar_scs_por_item).

4.3 Pilar Financeiro
Captura de preço na importação Protheus → precos_historico + valoração (valor em estoque/consumido, evolução de preço, ABC por valor, melhor fornecedor por preço×lead time).

4.4 Dashboards por público (Item 7 do roadmap)
Comprador: fila priorizada + sugestões de SC + aging + divergências + rupturas.
Gestão: nível de serviço, rupturas evitadas, cobertura média, valor em estoque, giro.
Diretoria: valor imobilizado, evolução, top ofensores, economia/risco.
5. Roadmap Faseado (proposto)
Versão	Pilar	Entrega
v2.2.0 — Fundação de Precisão	Cálculos	Ativar lead time real; consumo configurável (30/60/90) + tendência; dias de cobertura explícito; giro + estoque_snapshots; revisão mín/máx/segurança com base Neidson
v2.3.0 — Pilar Financeiro	Custo	Capturar preço do Protheus; precos_historico; valor em estoque/consumido; evolução de preço; ABC por valor
v2.4.0 — Motor de Reposição	Planejamento	Página de recomendação, ROP, qtd sugerida, justificativa automática, "Criar SC", sugestoes_reposicao
v2.5.0 — Ficha 360 do Material	Rastreabilidade	Página consolidada por item
v2.6.0 — Fornecedores & Classificação	Supply Chain	fornecedores mestre, melhor/mais rápido fornecedor, XYZ, sazonalidade
v3.0.0 — Dashboards por público	Decisão	Comprador / Gestão / Diretoria + consolidação
Recomendação de ordem (Software Architect + Supply Chain): começar pela v2.2 (fundação de precisão) — o motor de reposição e a ficha 360 só são confiáveis sobre cálculos sólidos (lead time real, cobertura, tendência). Em paralelo, v2.3 (custo) é de baixo risco pois reaproveita a importação existente.

6. Riscos & Impactos (análise multidisciplinar)
Database Engineer: todas as mudanças são aditivas (ADD COLUMN / novas tabelas), idempotentes, com backup automático — risco baixo. estoque_snapshots cresce: definir retenção. Adicionar índices faltantes antes das telas de agregação.
Data Engineer: confirmar a coluna de preço no SCM (nome/posição), moeda e tratamento de ausências/zeros; deduplicação de precos_historico; normalizar nomes de fornecedor para o mestre.
Backend (Python): lógica nova concentrada em db_functions.py já está grande → modularizar (services/calculos.py, services/planejamento.py, services/compras.py). Ativar _recalcular_lead_time_real no recebimento.
Software Architect: app.py (1775 linhas) e db_functions.py (1733) próximos do limite de manutenção — modularização entra como tarefa transversal do roadmap para "seguir funcionando daqui a 2 anos".
UX/UI: ficha 360 e lista de recomendação devem priorizar menos cliques (selecionar → "Criar SC" direto). Evitar sobrecarga de informação; públicos distintos veem visões distintas.
QA: suíte atual (96 testes) deve crescer com casos de ROP, qtd sugerida, lead time real, histórico de preço, tendência, e regressão dos cálculos existentes. Validar com itens reais antes de confiar nas recomendações.
DevOps: backups e migração idempotente já existem; cada release com bump de versão + changelog; snapshots diários precisam de gatilho (executar no carregamento do app, idempotente por dia, já que não há scheduler).
Product Owner: manter o princípio recomendar, não criar sozinho — governança e confiança da equipe de Compras.
7. Critérios de Aceite (desta entrega — o blueprint)
 Documento cobre: modelo de dados alvo, catálogo de cálculos/indicadores, regras de negócio, funcionalidades, roadmap faseado, riscos/impactos.
 Cada item da "visão" do usuário está mapeado para um pilar/fase (ou marcado como dependente de dado a confirmar).
 Aprovado pelo usuário e persistido em sistema-mro/docs/ como documento oficial versionado.
 Referência registrada na memória do projeto.
(Critérios de aceite específicos por release serão definidos no plano de cada fase, antes de qualquer código.)

8. Próxima ação após aprovação (sem código)
Salvar este blueprint em sistema-mro/docs/Blueprint - Plataforma de Inteligencia de Materiais.md.
Atualizar a memória do projeto com o roadmap (v2.2 → v3.0) e as decisões do PO.
(Opcional) Registrar no canal de Feedback/backlog os itens do roadmap como entradas rastreáveis.
A implementação de qualquer pilar (a começar, recomendadamente, pela v2.2 — Fundação de Precisão) será planejada e aprovada separadamente, conforme o fluxo das 9 skills.