# Handoff de Sessão — Sistema MRO (para continuar em outra sessão)

> Cole/`@`-referencie este arquivo no início da próxima sessão — funciona em **qualquer dispositivo**,
> porque viaja com o `git pull` (ao contrário da memória local do Claude, que fica presa à máquina
> onde a sessão rodou).
>
> **Escopo deste arquivo:** estado atual + conhecimento durável que não está no código nem no
> `CLAUDE.md`. **O histórico versão a versão vive em `changelog/`** — não replicar aqui.

---

## STATUS ATUAL — atualizado em 10/08/2026 (v6.5.0 · Task 1 implementada)

- **v6.5.0 EM ANDAMENTO — Task 2 commitada (`183fe6e`), Task 1 IMPLEMENTADA e ⏳ aguardando
  validação no app real. Faltam Task 4 (numeração sequencial) e Task 3 (limpeza do banco).**
  Plano aprovado em `docs/claude/Sessão 4/Plano Gerado Etapa 0.md`; changelog em
  `changelog/6.5.0.md`.

  - **Task 1 — Consumo Mensal por PEDIDO DE COMPRA (SC7) substituiu a vida útil do lote.**
    Tabela nova `consumo_sc7` (aditiva, criada em `criar_banco()`, **sem `_backup_db`** — nova e
    vazia ao migrar), cálculo em `services/consumo_sc7.py`, card "Consumo/Mensal (SC7)" na Ficha
    360 e entrada nova no Mín/Máx sugerido. `_vida_util_from_movimentos`,
    `consumo_por_vida_util` e `_movimentos_item` foram apagados de `services/classificacao.py`
    junto com os 14 testes do Épico B.

  - **⚠️ O FALLBACK POR SAÍDAS REAIS FOI REMOVIDO EM 11/08/2026, por decisão do Luis.** O plano
    da Etapa 0 previa três fontes (`sc7` → `scm` → `saidas`); ficaram **duas**, ambas de pedido
    de compra. Motivo, visto no app: com a `consumo_sc7` ainda vazia, TODO item caía no fallback
    e o card dizia "Fonte: saídas reais · 12 pedido(s)" para o que eram 12 requisições — ou seja,
    media consumo em vez de compra, apagando a diferença entre este card e o "Consumo/Mensal"
    ponderado ao lado. **Sem pedido atendido o card mostra "—"** e o tooltip explica (inclusive
    quantos pedidos estão a caminho). A mesma regra já valia no Mín/Máx sugerido.

  - **⚠️ A tela de import renderiza a chave `SC7_CONSUMO` explicitamente.** O plano supunha que
    `controle_sc.py` iterava as chaves do dict de resultados; ela na verdade renderiza chave a
    chave, então a métrica "Pedidos (consumo)" foi acrescentada à mão.

  - **⚠️ MEDIDO NO ARQUIVO REAL (`Relatório de Compras 10.08.2026.xlsx`), banco temporário:** a
    planilha crua tem **1.048.569 linhas** (limite do Excel) e só 43.971 com conteúdo. **A
    leitura pelo openpyxl leva ~135 s e é o gargalo** — a gravação de 39.966 pedidos leva 11 s.
    A tela avisa no caption e no spinner. Só se resolveria trocando de engine (calamine), que é
    dependência nova e ficou fora. Resultado da carga: 30.921 pedidos atendidos, 9.045 pendentes,
    **zero** sem `DT Emissao`; reimportar deu 0 inseridos / 39.966 atualizados.

  - **`services/constants.py::VERSAO` bumpado para `6.5.0`** (fonte única: rodapé da sidebar,
    `page_title`, log do `criar_banco` e `scripts/release.py`). Havia ficado em 6.4.0 depois da
    Task 2; `test_v600_refatoracao_ux.py` exige `changelog/6.5.0.md`, que existe.

  - **Sem coluna nova em `inventario` e sem nada persistido do cálculo**: o consumo é derivado
    na leitura, em **três consultas** (uma por fonte) para a base inteira — logo não envelhece
    como `consumo_medio_diario` e não tem backfill a refazer quando a fórmula mudar.

- **Branch de trabalho: `feat/v5.0.0`.**
  **Primeiro comando de qualquer sessão:** `git fetch --all --prune` e `git checkout feat/v5.0.0`.
  **Em 31/07/2026 a `main` foi realinhada** (`git branch -f` + force-push): estava 47 commits atrás
  e carregava um commit órfão (`21fc73e`) com uma versão **anterior** do `scm_client.py` e um
  `requirements.txt` **sem pin** — descartado por decisão do Luis, nada a resgatar. As duas branches
  agora apontam para o mesmo commit; quem clonar o repositório cai no estado atual.

- **v6.4.0 IMPLEMENTADA, gate verde (891 testes), ⏳ AGUARDANDO VALIDAÇÃO NO APP REAL E OK PARA
  COMMIT.** Ver `changelog/6.4.0.md`. Os 5 épicos do Luis (05/08/2026) entraram na ordem
  B → C → D → E → F, mais duas correções que ele pediu ao revisar. **Duas migrações aditivas**,
  ambas com `.bak`.

  - **⚠️ O `mro.db` DE PRODUÇÃO JÁ ESTÁ MIGRADO** (05/08/2026 13:39). Aconteceu durante a
    verificação da migração, sem intenção. **Nada foi perdido** — contagens conferidas contra o
    backup imediatamente anterior: 362 itens, 1.132 requisições, 2.973 movimentações, 726 itens de
    SC e estoque total 55.310 **idênticos** nos dois. A rede de segurança funcionou como projetada:
    `backups/mro.db.bak-20260805-133938-inventario-minmax-saldo-v640` e
    `…-requisicoes-rejeicao-v640` são o estado pré-migração, caso se queira voltar.
    Consequência prática: ao subir a v6.4.0 as migrações **não vão rodar de novo** (são
    idempotentes) e o `.bak` do servidor não será gerado — a prova de que migrou passa a ser a
    presença das colunas, não o arquivo.

  - **⚠️ O BACKFILL DO MÍN/MÁX RODA UMA VEZ SÓ NA VIDA DO BANCO** (guardado por
    `minimo_calculado not in cols_inv0`). Quem migrou antes de uma mudança de fórmula fica com os
    números da regra antiga até o item se mexer — foi o que aconteceu aqui: o banco migrou com a
    versão que preferia o lead time **cadastrado**, e a troca para o **calculado** não apareceria
    sozinha. Por isso existe o botão **"Recalcular tudo"** em *Cadastro de Itens › Sugestões de
    Mín/Máx*. **Já foi aplicado ao `mro.db` real**: 362 itens recalculados, 116 com sugestão, dos
    quais **50 usando o lead time calculado**; `estoque_minimo` intacto. **Vale para qualquer
    mudança futura de fórmula: o caminho é o botão, não a migração.**

  - **Decisões que o Luis fechou em 05/08/2026 e o `prompt.md` deixava em aberto:**
    - Épico B — **só recebimento de SC abre lote** (`sc_item_id` preenchido); ajuste de inventário
      e entrada avulsa mexem no saldo mas não abrem lote. Vários lotes → **média simples**.
    - Épico D — rejeitar **não é um "não" final, é um ciclo**: gestor devolve com motivo →
      requisitante ajusta e reenvia → volta para a fila do gestor. Isso puxou uma 4ª coluna
      (`reenviado_em`) e uma função nova (`atualizar_item_requisicao`), porque até aqui o
      requisitante só sabia *remover* item, não corrigir quantidade.

  - **⚠️ COBERTURA REAL DO ÉPICO B: 20 de 362 itens têm número.** *(Foi exatamente este número
    que motivou a troca pelo consumo por pedido na v6.5.0 — o parágrafo abaixo fica como
    registro do diagnóstico; o cálculo que ele descreve não existe mais.)* Não é bug — é o histórico de
    3,5 meses. Dos **94** itens com recebimento de SC: **20** têm lote fechado (viram número),
    **45** têm só lote vivo (o estoque nunca caiu ao mínimo desde que chegou) e **29** não abriram
    lote (chegou já no/abaixo do mínimo, ou fechou em < 1 dia). O número cresce sozinho conforme os
    lotes fecharem. Se o Luis achar vazio demais, **a alavanca é a regra de "que entrada abre
    lote"**, uma linha em `_movimentos_item` — não o resto do cálculo.

  - **⚠️ ACHADO NA BASE REAL, VALE PARA ALÉM DESTA VERSÃO: `consumo_medio_diario` é coluna
    PERSISTIDA e congela.** Ela só é recalculada quando o item se move, então um item parado guarda
    para sempre o consumo do dia em que parou. O **PN 34FR0001** tem uma saída de **99.999
    unidades** em 30/06/2026 (erro de digitação evidente) e está com 3.333/dia no banco, embora
    `consumo_30d` já seja 0. Isso **já distorce hoje** o ROP e a fila de reposição, independente da
    v6.4.0 — vale corrigir a movimentação na operação.
    A v6.4.0 se protegeu: `min_max_amostras` (nº de saídas em 30 d) entra **na fórmula**, não só no
    rótulo, e zero amostras ⇒ sem sugestão. Sem essa guarda a visão em lote proporia **mínimo
    66.666** para um item de mínimo **5**, e um clique reescreveria a base do Neidson. Efeito:
    116 itens com sugestão (todos com lastro) em vez de 228 (112 sem movimento recente).

  - **⚠️ Armadilha de timestamp paga:** o predicado "o pedido voltou?" NÃO compara datas. A primeira
    versão usava `reenviado_em > rejeitado_em` e o teste do ciclo completo reprovou — `data_hora`
    tem resolução de **segundo**, e rejeitar/reenviar no mesmo segundo empata a comparação,
    deixando o pedido preso fora da fila. Como `rejeitar_requisicao` **sempre zera `reenviado_em`**,
    o predicado virou `rejeitado_em IS NOT NULL AND reenviado_em IS NULL`. **Vale para qualquer
    par de colunas de data neste schema.**

  - **DEVOLVIDA NÃO SAI DO ALMOXARIFADO** (decisão do Luis em 05/08/2026, revisando a assunção
    que eu havia deixado em aberto: *"se não foi aprovada pelo gestor então não podemos entregar o
    material"*). A requisição devolvida sai da fila de separação **e** `entregar_requisicao` a
    recusa — a trava vive no serviço, porque sumir da lista é conveniência de tela e qualquer outro
    caminho até a entrega passaria por cima dela. Volta sozinha ao ser reenviada.
    ⚠️ **Isso NÃO tornou a aprovação obrigatória:** só a rejeição **explícita** bloqueia. A
    fronteira está fixada por teste (`test_nao_aprovada_continua_entregavel`) e o motivo é
    concreto — exigir aprovação para toda entrega **pararia a operação**: o `mro.db` tem 1.132
    requisições e **zero** aprovadas.

  - **O lead time da SUGESTÃO é o calculado** (2ª correção do Luis): `lead_time_para_sugestao` é
    deliberadamente o **inverso** de `lead_time_efetivo` — a sugestão prefere o **calculado**, o
    ROP continua preferindo o **cadastrado** (base do Neidson decide compra real). Consequência:
    **o mínimo sugerido não é mais idêntico ao ROP**, e isso é intencional. No `mro.db`, 104 itens
    têm lead time calculado e **103 divergem** do cadastrado (que é quase sempre um `20` genérico;
    o calculado varia de 6 a 100 dias).

  - **Esconder saldo é da TELA, não do item.** `_saldo_visivel` exige **duas** condições: quem está
    olhando (só a tela do Requisitante pede ocultamento) **e** o que o cadastro liberou. O mesmo
    `_req_bloco_materiais` roda na Movimentação do balcão, onde quem monta o pedido é o almoxarife.

  - **SCRIPT DAS FOTOS PRONTO (Épico A) — `scripts/importar_imagens_planilha.py`.**
    Simulação é o padrão; `--aplicar` grava, com `_backup_db` antes da 1ª escrita, e reusa
    `services/ficha.salvar_imagem_item` (mesma validação e mesmo `docs/itens/item_<id>.ext`).
    **Medido:** 351 PNs com foto na planilha, **327 casam** com o inventário (90%), 24 sem
    item (não são criados), 4 já tinham foto (pulados sem `--substituir`). ~90 MB em
    `docs/itens/`, que já está no `.gitignore`.
    - **O vínculo foto→item é EXATO, não por ordem.** As fotos estão *dentro da célula*
      (rich data do Excel 365) e o script segue a cadeia
      `célula vm=N → metadata.xml → rdrichvalue.xml → richValueRel.xml → _rels → xl/media/`.
      O "plano B" do prompt original (extrair na ordem e casar com as linhas) foi
      **descartado**: a cadeia existe e é exata, e foto errada no item errado é pior que
      foto nenhuma.
    - **Conferido visualmente em 3 amostras**, incluindo duas linhas adjacentes que só
      diferem na cor (`17ME0019` CANETA AZUL → BIC azul; `17ME0021` CANETA VERMELHA → BIC
      vermelha) — um deslocamento de uma linha teria aparecido. Repetir esse teste se a
      planilha for trocada.
    - PN sai da **coluna B**; a foto da **coluna E**. GERAL começa na linha 4 (cabeçalho na
      3), ENTRADA na 2. GERAL vence quando o PN aparece nas duas.

  - **⚠️ IMAGEM: a exibição está pronta, o conteúdo não (até rodar o script acima).** O requisitante já vê a foto do material
    (Épico E), mas hoje **0 de 362 itens** renderizariam alguma: são 4 `imagem_path` gravados e
    **nenhum** dos arquivos existe em `docs/itens/` (que tem 1 arquivo órfão, sem referência no
    banco). A guarda de existência (`imagem_existente`) é o que evita a tela estourar nesses 4.
    **Para as fotos aparecerem falta rodar o Épico A** — extrair as 402 fotos de
    `Material MRO 2026.xlsx` e casar por PN; prompt pronto em
    `docs/prompt_importar_planilha_mro.md`, sessão própria. O upload item a item já existe na
    Ficha 360 desde a v2.6.0.

  - **Gate intermitente corrigido (fora do escopo, mas bloqueava):** `test_v500_router.py` reprovou
    uma vez com `AppTest script run timed out after 3(s)` em "Aprovações do Setor". Não é lentidão
    — medido, a página renderiza em **0,17 s**, a mais rápida das dez; ela é só a **primeira em
    ordem alfabética** e paga sozinha o import de toda a árvore `ui/`+`services/`. O `at.run()`
    agora tem `timeout=30` explícito e comentado. **Se outro teste de `AppTest` flakear igual, a
    causa é a mesma** — e o próximo passo seria aquecer os imports uma vez no `conftest.py`.

  - **O que conferir no app** (roteiro completo na seção "Verificação" do plano da v6.4.0): Ficha
    360 de item **com pedido de compra atendido** mostra o card "Consumo/Mensal (SC7)" (o card de
    vida útil saiu na v6.5.0) e os itens sem histórico mostram "—";
    "Usar mínimo/máximo" grava e a aba em lote **não** mexe em quem não foi marcado; o gestor abre
    "Ver requisição completa", devolve com motivo, o pedido some da fila e aparece em "Devolvidas",
    o requisitante ajusta, reenvia e ele **volta**; desmarcar "mostrar saldo" esconde só na tela do
    Requisitante; Portaria acha por nome com caixa/espaço trocados e não lista nada com o campo
    vazio.

  - **Demanda antiga de v6.4.0 (gestor ↔ requisitante) segue ADIADA para v6.5.0** (seção própria no
    `docs/prompt.md`).

- **Planilha MRO encontrada e documentada (05/08/2026).**
  `sistema-mro\Material MRO 2026.xlsx` (118 MB) — controle antigo de entrada/saída com **402
  fotos embutidas em célula** (recurso "rich data" do Excel; `xl/richData/richValueRel.xml` +
  `_rels` mapeiam para as células, NÃO os drawings) + 1 logo (image403, ignorar). Abas `GERAL`
  (1004 itens, estoque diário jan→abr/2026), `ENTRADA` (recebimentos por data). **961 PNs únicos;
  só 330 existem no `inventario`** (362 itens). Prompt de migração pronto:
  `docs/prompt_importar_planilha_mro.md` — extrair fotos → casar por PN → `docs/itens/` +
  `imagem_path`. **Não versionar a planilha** (dado operacional; está untracked — deixar assim).

- **v6.3.0 IMPLEMENTADA, gate verde, ⏳ AGUARDANDO VALIDAÇÃO NO APP REAL E OK PARA COMMIT.**
  Ver `changelog/6.3.0.md`. **Sem migração de schema.** Resolve o item nº1 do feedback da
  v6.2.0: o papel `almoxarife` abre **Aprovações do Setor** com a fila consolidada de TODOS os
  setores (antes caía no ramo do gestor e, sem departamento cadastrado, não via nada).
  - **A negativa por omissão do gestor não foi tocada.** `listar_requisicoes_por_setor` com
    setor vazio continua devolvendo `[]`; o consolidado é a **função irmã**
    `listar_requisicoes_para_aprovacao()`, **sem parâmetro de setor**. A alternativa
    (`setor=None` com semântica diferente de `""`) faria um `departamento` faltando — o caso
    exato que a negativa cobre — entregar a empresa inteira, com a diferença entre negar e
    liberar tudo morando num `None` × `""` no meio da UI. As duas funções compartilham
    `_clausulas_aprovacao`, para as filas não divergirem em silêncio.
  - **Decisões do Luis (03/08/2026):** o filtro de setor lista **só os setores que têm pedido**
    na fila, com contagem (a união Configurações + histórico passa de 60 valores, quase todos
    sem pedido); e com `exigir_login` **desligada** a tela fica **como estava** (ramo simulação)
    — o consolidado é do almoxarife **autenticado**.
  - **⚠️ Armadilha de Streamlit paga:** o `selectbox` do filtro é **sem `key=`**. Aprovar pode
    tirar o último pedido de um setor e mudar as opções; com `key`, a identidade congela
    (`key_as_main_identity`) e um valor guardado que sumiu das opções levanta
    `StreamlitAPIException`. Sem key, o widget é recriado e o filtro volta a "Todos".
  - **Agregação por setor normaliza** (`UPPER(TRIM())`): `'TI'` × `'ti '` × `' Ti'` viram uma
    opção só. É a mesma armadilha que `setor_dominante_por_item` paga desde a v5.9.0 — vale
    para **qualquer** agregação nova por setor.
  - **O que conferir no app:** almoxarife logado SEM departamento vê pedidos de setores
    diferentes e **não** recebe o aviso de cadastro incompleto; a coluna Setor vem em 2º; o
    filtro mostra só setores com pedido e a contagem bate; gestor continua restrito ao seu
    setor. Roteiro completo na seção "Verificação" do plano da v6.3.0.
  - **Feedback do Luis registrado como v6.5.0** (`docs/prompt.md`): o requisitante **seleciona o
    gestor a cada requisição** (`requisicoes.gestor`, TEXT nullable) — decisão do Luis em
    05/08/2026, "é melhor do que vincular". Substitui a ideia antiga de "agrupar a fila por
    solicitante" e de vínculo no cadastro do usuário. Pergunta aberta: guardar nome ou id do
    gestor.

- **v6.2.0 COMMITADA (`e33711a`), gate verde (793 testes), ⏳ VALIDAÇÃO NO APP REAL INCOMPLETA.**
  Ver `changelog/6.2.0.md` e o plano em `docs/claude/Sessão 3/PLANO_V620_TELAS_SELF_SERVICE.md`
  (seguido integralmente; a análise técnica prévia está em `Etapa 2 Plan.md`, na mesma pasta).
  **Telas self-service**: os três papéis órfãos da v6.1.0 ganharam rota — Requisitante ("Minhas
  Requisições"), Gestor ("Aprovações do Setor") e Portaria ("Consulta de Saída"). Menu de 7 → 10.
  - **A aprovação do gestor NÃO bloqueia nada** (decisão do Luis, 02/08/2026): grava
    `aprovado_por`/`aprovado_em` e só. Sem status novo, sem tocar `autorizador_*`, sem impedir a
    entrega. Quem libera o material continua sendo o almoxarife, na entrega. A primeira aprovação
    vale — a segunda chamada avisa e não sobrescreve (duplo-clique não pode reescrever auditoria).
  - **Portaria é pública por decisão.** A guarita é terminal compartilhado; PIN coletivo colado no
    monitor seria pior que login nenhum. `ui/auth.SESSAO_PUBLICA` + botão na tela de login.
    ⚠️ **A ordem da checagem em `render_sidebar()` é o que segura o acesso:** `papel_atual()` é
    `None` tanto no modo público quanto com a flag desligada, e nesse segundo caso
    `opcoes_menu(None)` devolve o menu INTEIRO. `em_modo_publico()` tem de ser perguntado ANTES —
    inverter entrega as 10 rotas a quem entrou sem credencial.
  - **Migração aditiva** `requisicoes.aprovado_por`/`aprovado_em` (padrão `tipo_fluxo` da v5.7.0:
    commit → `_backup_db` → `ALTER`). O guard olha as DUAS colunas e cada `ALTER` tem o seu `if`:
    o `sqlite3` não abre transação para DDL, então um crash entre os dois `ADD COLUMN` deixaria a
    primeira commitada e um guard só na primeira nunca completaria a segunda.
  - **Nada duplicado:** o `SELECT` de requisições virou `_consultar_requisicoes` (usado pelas três
    funções), e as páginas novas importam os blocos de `ui/paginas/movimentacao.py`
    (`_req_bloco_identificacao` agora parametrizado, `_req_bloco_materiais`, `_req_painel_pedidos`
    extraído da Visão do Solicitante, `_opcoes_setor` novo).
  - **Limitação aceita:** o filtro do Gestor é igualdade simples de setor. No `mro.db` de hoje
    `requisicoes.setor` tem **59** valores distintos e `usuarios.departamento` tem **19**, com
    interseção de **9** (o plano dizia 57 — recontado em 02/08/2026). Cobre o fluxo novo, onde o
    setor nasce do departamento; o legado divergente se alcança pelo seletor de setor da tela.
  - **🐛 CORREÇÃO DE BUG DA v6.1.0 QUE ENTROU AQUI — login por alias não autenticava.** Achado em
    02/08/2026 ao ligar o login para os requisitantes: "Usuário ou PIN inválidos" para quase todo
    mundo. `_gerar_login` monta `primeiro.ultimo` e **descarta os nomes do meio**, mas a chave de
    busca (`ident_norm`) é o nome COMPLETO — as duas só coincidem em nome de 2 palavras. **88 dos
    104 usuários** do `mro.db` não entravam pelo login que a tela mostrava. A v6.1.0 passou verde
    porque foi validada com "Jasiva Lopes" (2 palavras).
    Corrigido em `services/usuarios._localizar_por_identificador`: tenta `ident_norm` e, só se não
    achar, o alias. **`login` NÃO é único** (5 aliases compartilhados por duas pessoas): quando
    alguém se chama literalmente como o alias, o match exato vence; empate real (`luis.oliveira`,
    `simone.lima`) é **recusado** em vez de desempatado no chute. Hoje: 104/104 entram pelo nome
    completo, 97 pelo alias.
    ⚠️ **Lição de teste:** o `test_autenticar_normaliza_identificador` da v6.1.0 usava um nome de
    duas palavras e, por construção, não podia pegar isso. Teste de identidade/normalização precisa
    de nome com 3+ palavras.
  - **Débito herdado:** 5 pessoas estão cadastradas em DUPLICIDADE em `usuarios` (mesma identidade,
    duas grafias vindas de `solicitantes_mro`): `luis.oliveira`, `simone.lima`, `luan.perna`,
    `miguel.nascimento`, `daniel.menezes`. Não mexido — é dado operacional e exige decisão caso a
    caso sobre qual linha fica.
  - **⚠️ COMMITADA COM VALIDAÇÃO INCOMPLETA.** O Luis autorizou o commit explicitamente, mas parou
    a validação no meio para entender o fluxo. **Antes de evoluir, rodar `docs/ROTEIRO_TESTES_V620.md`**
    (~20 min, 7 partes). Os 4 pontos que importam estão no fim do roteiro; o crítico é o **6.6** —
    no modo público a sidebar tem de ter UM item só. Se aparecerem 10, é falha de acesso.
  - **Feedback do Luis (02/08/2026) — ambos os itens já encaminhados:** (1) admin ver tudo de
    todos os setores → **entregue na v6.3.0**, acima; (2) fila do gestor agrupada por
    solicitante → **substituída** pela decisão de 05/08/2026: o **requisitante seleciona o
    gestor a cada requisição** (v6.5.0, `docs/prompt.md`), atacando a raiz em vez da aparência.

- **v6.1.0 COMMITADA, gate verde (760 testes), ✅ VALIDADA NO APP REAL PELO LUIS (02/08/2026).**
  Ver `changelog/6.1.0.md` e o plano em `docs/PLANO_V610_USUARIOS_LOGIN.md` (seguido integralmente).
  Fundação de **usuários e login local**: tabela `usuarios`, `services/usuarios.py`, `ui/auth.py`,
  menu filtrado por papel e aba **Usuários** em Configurações.
  - **A flag `exigir_login` nasce DESLIGADA** e é o que garante a compatibilidade: sem ligá-la, o app
    abre idêntico à v6.0.0. `gate()` é no-op, o menu é o completo e o rodapé da barra continua sendo
    o bloco fixo "Luis Oliveira / Inventus Power".
  - **Migração aditiva, sem `_backup_db`** (padrão v5.1.0): a tabela nasce vazia e nenhuma linha
    existente é reescrita. O seed é `INSERT OR IGNORE` — rodar de novo **nunca** sobrescreve papel,
    PIN ou departamento de quem já existe (senão a abertura seguinte do app desfaria toda edição
    feita na tela).
  - **Validação no app real cumprida (02/08/2026):** flag off = app intacto; a lista de usuários já
    vem semeada dos Solicitantes MRO; PIN definido → login → 7 rotas para o almoxarife e 5 para o
    comprador (sem Movimentação e sem Configurações); PIN errado recusa com mensagem genérica;
    desligar a flag devolve a abertura direta.
  - **Em produção, o `mro.db` do servidor só ganha a tabela `usuarios` na primeira vez que alguém
    abrir o app pelo navegador** — subir o serviço não executa `app.py` (armadilha já documentada
    na seção de comandos do `CLAUDE.md`). A prova de que a migração rodou é a aba Usuários listar
    gente, não o serviço responder.
  - **Duas guardas de porta trancada** (irreversíveis pela UI, porque a aba Usuários só existe dentro
    de Configurações): não dá para rebaixar/desativar o **último almoxarife ativo**, e não dá para
    ligar `exigir_login` sem **nenhum** usuário ativo com PIN. A 2ª é adição ao plano — ele previa só
    um aviso; o aviso continua e o bloqueio cobre o caso de prejuízo certo.
  - **Armadilha paga — teste que quebra no dia 1º:** `test_v590_entradas_reais` falhava em 01/08/2026
    **sem relação com esta versão**. O cenário grava a movimentação em `hoje - 1 dia`; no dia 1º ela
    cai no mês anterior e o `historico_mensal` devolve o mês corrente como `0.0`, quebrando uma
    asserção de lista literal. Corrigido para comparar a **soma**. Fixture com data relativa +
    asserção posicional por mês é uma bomba-relógio — vale para os próximos testes de série mensal.
  - **Próxima fase (fora do escopo da v6.1.0):** telas do Requisitante, do Gestor e da Portaria —
    **entregues na v6.2.0**, acima. A partir dela, "Seu perfil ainda não tem telas" só aparece para
    papel desconhecido (banco editado à mão), que continua negando por omissão.

- **v6.0.0 COMMITADA, gate verde (726 testes), ⏳ AGUARDANDO VALIDAÇÃO VISUAL DO LUIS.**
  Ver `changelog/6.0.0.md`. Refatoração de **UX/UI** aprovada de uma vez (11 itens): menu de 9 → 7,
  KPI Mensal e aba Dashboard da Movimentação extintas com o conteúdo redistribuído no Almoxarifado,
  R$ em pt-BR no sistema inteiro e cores alinhadas ao `docs/template_moderno.html`.
  - **SEM migração de schema.** Nenhum cálculo mudou — o teste que prova isso compara os
    indicadores do ano do Almoxarifado com os do extinto `montar_visao_executiva()`.
  - **O que conferir no app:** o Dashboard → Almoxarifado ficou longo (herdou 9 blocos); a primeira
    abertura custa ~1,3 s e depois cai no cache de 120 s. Conferir também Ficha 360 → Evolução de
    preço (item com 1 preço vira métrica, item multi-moeda vira tabela) e o checkbox de conversão
    no Cadastro de Itens **em item já curado** — ele tem de nascer MARCADO.
  - **Três telas saíram sem substituto** (Curva ABC nos dashboards, rascunho de e-mail de cotação,
    cruzamento SCM × SC7 por upload) e o **Volume de Movimentações** foi descontinuado. Os services
    seguem intactos: voltar é religar a chamada. Lista completa na seção "O que SAIU" do changelog.
  - **Preservado de propósito:** o Controle Manual de Críticos (tabela `monitor_livre`) foi para um
    expander do Guarda-Chuva quando a aba Monitor saiu — senão os dados do usuário ficariam no banco
    sem tela para abri-los.
  - **Débito conhecido:** a sidebar cinza `#5B5B5B` do template NÃO foi adotada porque o
    `inventus_logo.png` é opaco com fundo branco (alfa = 255 em toda a imagem) e viraria um
    retângulo branco. Com um PNG transparente é troca de um token em `services/tema.py`.
  - **Armadilha paga — versão em três lugares:** `app.py` e `ui/sidebar.py` diziam 5.8.0 e o log de
    `database.py` dizia 5.7.0, com a v5.9.0 entregue. Agora a fonte é `services.constants.VERSAO` e
    há teste varrendo os três pontos de exibição. **Ao bumpar: mexa só na constante e crie o
    `changelog/<versão>.md`** — o teste exige o arquivo.

- **v5.9.0 COMMITADA (`2393f58`), gate verde (691 testes), ⏳ AGUARDANDO VALIDAÇÃO NO APP REAL.**
  Ver `changelog/5.9.0.md`. Sete entregas: Dashboard do
  Comprador enxuto (4 cards + 5 gráficos), "Cadastro de Itens", bug do SelectBox, card Entradas,
  Guarda-Chuva por Pedido, componente de exportação e data real da saída.
  - **Migração de schema:** 3 tabelas novas e **aditivas** (`guarda_chuva_pedido`,
    `guarda_chuva_item`, `guarda_chuva_recebimento`); a `guarda_chuva` da v4.9.0 fica intacta.
    Provada sobre cópia do `mro.db` real: `.bak` de 4,76 MB, FKs e contagens preservadas.
  - **Três números MUDAM à vista do usuário, de propósito:** card "Entradas" do Almoxarifado cai de
    93 → 33 no mês (428 das 566 entradas do banco eram ajuste de inventário) e os 4 cards do
    Comprador passam a contar ITEM, não SC. É correção — **avisar o almoxarifado**.
  - **O que conferir no app:** trocar de item em Cadastro de Itens atualiza TODOS os campos e salva
    no item certo; Guarda-Chuva adiciona pedido pela API e cai no manual quando ela falha; entrega
    com "Material saindo agora" desmarcado grava a data informada — **e o mesmo na Nova
    Requisição → Padrão**, onde a requisição deve continuar com a data de hoje.
  - **✅ RESOLVIDO (31/07/2026) — "Material saindo agora" agora existe também na Requisição
    Padrão** (retorno do Luis). O bloco do checkbox foi replicado em `_req_nova_padrao`
    (`ui/paginas/movimentacao.py`, seção "4. Autorização da Saída"), com `key=` prefixadas
    (`pad_agora`/`pad_dt_saida`/`pad_hr_saida`) para não colidir com as da Fila — que **ficou como
    estava**. Só UI: o serviço já aceitava `data_saida=None`.
    **Trava nova:** o teste de serviço não pegava a falta de fiação entre tela e serviço, então
    `tests/test_v590_data_saida.py` ganhou dois casos de **AppTest** que percorrem a tela e provam
    que a data informada chega em `movimentacoes.data_hora` (verificado: removendo o
    `data_saida=` da chamada, o teste falha). Falta só conferir no app real.
  - **Achado que mudou o plano (§3):** a correção prevista era *remover* os `key=` dos widgets de
    edição. Medido: isso quebraria a página com `StreamlitDuplicateElementId`, porque as duas abas
    têm widgets de mesmo rótulo/opções e os ids colidem quando o item está no valor padrão
    (`UNIDADES[0]` = "UN"). As keys ficaram; quem devolve a identidade ao item é
    `resetar_campos_ao_trocar`.
  - **Achado que mudou o plano (§5):** o plano supunha um campo `C7_NUMSC` no pedido da API — **não
    existe**. O elo com a SC é o `C7_XPEDSCM` (código da cotação) → `solicitacoes_compra.cotacao_codigo`.
    O payload real foi capturado da API antes de escrever o parser (passo 0 do roadmap, cumprido).
  - **Correção de dado descoberta no caminho:** `setor_dominante_por_item` agora normaliza o setor
    com `UPPER(TRIM(...))`. Havia 68 valores distintos para 59 setores reais (`'ADAPTADOR'` vs
    `'ADAPTADOR '`, `'TI'` vs `'ti'`), o que partia o total do mesmo setor em duas linhas do ranking.

- **v5.8.0 COMMITADA (`015a5cf`), gate verde (641 testes locais), ✅ VALIDADA NO APP REAL
  (31/07/2026) e EM PRODUÇÃO.** Ver `changelog/5.8.0.md`. Duas entregas: backup sob demanda na tela
  (`services/backup.py` + bloco em Configurações) e pacote portátil (`scripts/portatil.py` →
  `MRO.exe`).
  - **O pacote portátil está em uso real: a Jasiva opera pelo `MRO.exe`.** É a prova de campo do
    objetivo da v5.8.0 — os 7 passos manuais do `INSTALACAO_SERVIDOR.md` viraram "extrair e dois
    cliques", e o runtime embeddable roda em máquina que não é a do dev.
  - **Migração de schema:** rodou (tabela `configuracoes (chave, valor)`, `CREATE TABLE IF NOT
    EXISTS` em `criar_banco()`, aditiva pura) — o app abriu em produção, e é o boot que executa a
    migração.
  - **Débito assumido (decisão do Luis):** sem listagem/exclusão de `.bak` na tela e sem retenção
    automática. Nada apaga backup, e o botão manual acelera o acúmulo. **Com o sistema em uso por
    mais de uma pessoa, isso passa a acumular mais rápido** — vale revisitar.

- **v5.7.0 — CP1 segue PENDENTE de validação.** Depende do Relatório de SCs, que o Luis ainda não
  tem; a regra foi ensaiada contra cópia do `mro.db` real (SC 41494 / PN 29TP0086). CP2/CP3/CP4 ✅.

- **Também em aberto, dependendo de estar na empresa:** validar os **códigos de status da API SCM**
  (`01/03/05/09` são **inferidos**, nunca confirmados com dado real — o comprador pode estar vendo
  status errado; o código cru fica em `status_protheus`, ajustar `_STATUS_SC_API` em `scm_sync.py`)
  e a **validação física da F5** (reboot-test, acesso de outra máquina, backup/restore).

- **🎯 PRÓXIMO — passada global de UX** (adiada da F4b, decisão do Luis): adotar
  `barra_filtros`/`tabela_paginada` nas tabelas que a F4a migrou cruas, **página a página com
  validação**, nunca em bloco. `saldo_estoque` e `scm_integrado` já adotaram; `controle_sc`
  (11 tabelas cruas, a maior página) e `dashboard` são os alvos; `movimentacao` fica por último
  (é a que mais escreve estoque). ⚠️ Dois casos são `st.data_editor` e **não** convertem —
  `tabela_paginada` é somente-leitura. O ganho maior não é paginar, é padronizar estado vazio e
  cabeçalhos (`page_size=0` desliga a paginação e mantém o resto).

- **Backlog vivo:** `docs/prompt.md`. Plano da evolução v5.x: `docs/PLANO_V5_EVOLUCAO.md`.

---

## Achados que valem memória (medidos, travados por teste)

Conhecimento que custou caro descobrir e **não** é dedutível do código. As armadilhas de runtime e
de banco estão no `CLAUDE.md`; estas são as de domínio e de Streamlit.

### Streamlit
- **`st.data_editor` com `key` + `num_rows="fixed"`:** o Streamlit 1.60.0 mudou a identidade do
  widget para a **assinatura do schema**, não os valores ("this keeps edits alive across pure value
  changes"). Isso reaplicava a quantidade digitada sobre o pendente já atualizado. Só o parcial
  quebrava — no total o item sai da lista, o nº de linhas muda e a assinatura muda junto. Corrigido
  com chave versionada (`ui/componentes/tabela.chave_editor`). **Se aparecer bug parecido em
  qualquer `data_editor` com `key`, é aqui que se olha primeiro.**
- **Widget com `key=` fixo NÃO se atualiza quando o dado de origem muda** (v5.9.0). Havendo `key`,
  ela vira a **identidade principal** do widget e `options`/`index`/`value` saem do cálculo do id
  (`key_as_main_identity`, `streamlit/elements/lib/utils.py:232-243`). `index=`/`value=` só valem na
  1ª renderização. Em tela do tipo "escolhe item → mostra campos do item" isso faz o formulário
  exibir **e gravar** os dados do item anterior. Remédio: `resetar_campos_ao_trocar`
  (`ui/componentes/selecao.py`). **Sintoma clássico: "troquei o item e a tela não mudou".**
- **Tirar o `key=` não é a saída óbvia:** sem key a identidade passa a incluir todos os kwargs, e
  dois widgets de mesmo rótulo/opções na mesma página (típico de abas espelhadas "Cadastrar" ×
  "Editar") colidem em **`StreamlitDuplicateElementId`** — a página inteira cai. `st.tabs` **não**
  isola ids; só sidebar × main entra no cálculo (`active_dg_root_container`).
- **`st.stop()` NÃO pode ser usado dentro de uma aba** — mata as abas seguintes. Usar guarda
  `if/elif/else`.
- **`st.tabs` é *eager*** — renderiza TODOS os corpos a cada rerun.
- **Escrita em estoque exige `invalidar_leituras()`** (`ui/cache.py`), senão sidebar e Saldo mostram
  cache velho pós-baixa.

### Domínio / dados
- **Estoque de segurança:** `estoque_seguranca` (MANUAL do gestor, inteiro) vs
  `estoque_seguranca_calculado` (SUGESTÃO = `consumo × lead × 1,5`). `estoque_seguranca_efetivo`
  (`planejamento.py`) **prioriza o manual**. `FATOR_ESTOQUE_SEGURANCA=1.5` em `constants.py`.
- **Consumo real** = saída por requisição (`SAIDA_REAL_WHERE` = `tipo='saida' AND requisicao_id IS
  NOT NULL`) — usado por ABC, giro e consumo. **Ajustes físicos NÃO entram.**
- **Recebimento real** = `ENTRADA_REAL_WHERE` = `tipo='entrada' AND sc_item_id IS NOT NULL`
  (v5.9.0, simétrico ao de cima). Não existe `tipo='AJUSTE'` no schema, então contagem física,
  conferência, ajuste por edição e entrada avulsa **são todos gravados como `entrada`**; só
  `registrar_recebimento_sc` preenche `sc_item_id`. Medido: **428 das 566 entradas do banco eram
  ajuste** (418 de `INVENTÁRIO`).
- **A API do SCM não devolve o nº da SC no pedido** (v5.9.0, verificado em produção). O elo é
  `C7_XPEDSCM` (código da cotação, `CTxxxxx`) → `solicitacoes_compra.cotacao_codigo`. O payload de
  `/Pedidos/ByNumero` é uma **lista achatada** de campos `C7_*` com padding de espaços, cabeçalho
  repetido em cada linha. Shape real fixado em `tests/test_v590_scm_pedido.py`.
- **`movimentacoes.setor` tem o mesmo setor grafado de várias formas** — 68 valores distintos para
  59 setores reais (`'ADAPTADOR'` vs `'ADAPTADOR '`, `'TI'` vs `'ti'`). `setor_dominante_por_item`
  normaliza com `UPPER(TRIM(...))` desde a v5.9.0; **qualquer agregação nova por setor precisa
  fazer o mesmo**, senão o total do setor sai partido em duas linhas.
- **Fornecedores MRO** vêm de `itens_sc.fornecedor_item` + `solicitacoes_compra.fornecedor`
  (~34 reais), **NÃO** da tabela `fornecedores` SA1 (~3,6k = empresa toda).
  `precos_historico.fornecedor` tem lixo ("1.0"/"2.0"); `_nome_fornecedor_valido` filtra.
- **Movimentação legada: classifique pelo CENTRO DE CUSTO, não pelo texto.** `motivo` está **0%
  preenchido** nas 2.822 linhas do histórico e os templates de texto da tela de Inventário mudaram
  **cinco vezes**; o CC nunca mudou.
- **Na SC, a FK manda e o texto é fallback do legado** — há linha cuja Observação é `F61846` (o
  **PO**) e cujo `documento_nf` é `169357`.
- **O MRO é a fonte de verdade do recebimento** (v5.7.0/CP1): `itens_sc.quantidade_recebida` não é
  mais sobrescrita pelo Protheus; o número do ERP vai para `quantidade_recebida_protheus`.
- **Falta de saldo NÃO recusa a requisição** (decisão nº2 da v5.7.0, substituiu a regra antiga do
  `prompt.md`): grava o que tem e manda o pendente para a fila.
- **Centro de Custo só passou a ser importado na v5.6.0** — falta **reimportar o Relatório de SCs**
  para preencher o histórico.

### Ambiente
- **EOL: produção = CRLF · testes = LF.** git usa autocrlf (index=LF, worktree=CRLF). Ao editar
  `app.py`, `database.py`, `services/*.py`, preservar CRLF — conferir com `git ls-files --eol`.
- **Nunca rodar smoke contra o `mro.db` real** — copiar para tmp e apontar `database.DB_PATH`.
- **Smoke E2E:** `AppTest.from_file("app.py")` + stub
  `streamlit_option_menu.option_menu = lambda *a, **k: "<Página>"` para navegar.
- **Multi-dispositivo (git):** um clone antigo pode ter `remote.origin.fetch` restrito a um único
  branch — `git fetch`/`pull` nunca trazem branches novos e o `checkout` dá `pathspec did not
  match`. Fix, uma vez por clone:
  ```
  git config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
  git fetch origin
  ```
  Se o `checkout` reclamar de mudanças locais, **não descartar sem olhar**: `git stash -u` antes.
- **Hooks do Claude Code só carregam ao REINICIAR** — `.claude/settings.json` é lido no início da
  sessão.
- **Vault Obsidian (`vault/`)** — protocolo em `vault/CLAUDE.md`. Só para a apresentação de KPI
  mensal. Não é versionado; sincroniza pelo OneDrive.

---

## Setup em OUTRA MÁQUINA (checklist)

O repositório é **público** e não carrega dado operacional — `mro.db`, `backups/`, `vault/`,
`graphify-out/` e o CSV do inventário estão no `.gitignore`. Quem clona pega o **código**, não o
banco.

```powershell
git clone https://github.com/eholuwi/sistema-mro.git
cd sistema-mro
git fetch --all --prune
git checkout feat/v5.0.0          # é a branch de trabalho; a main está parada na v4.5.5
python -m venv venv               # NÃO copiar o venv de outra máquina (caminhos absolutos)
venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\verify.ps1                      # tem de dar exit 0 antes de mexer em qualquer coisa
```

**O `mro.db` não vem pelo git.** Três caminhos, em ordem de preferência:

1. **OneDrive** — a pasta `Documentos\programa\` inteira sincroniza, banco incluído. É como as
   duas máquinas do Luis conversam hoje. ⚠️ Fechar o app antes de trocar de máquina: dois
   Streamlit escrevendo no mesmo `mro.db` pelo OneDrive dá conflito de arquivo, e o `-wal`
   sincroniza separado do `.db`.
2. **Banco novo** — abrir o app sem `mro.db` cria um vazio (`criar_banco()` roda no 1º render).
   Serve para desenvolver e rodar testes; não serve para validar com dado real.
3. **Cópia manual** de um `.bak` de `backups/`.

Depois do clone, para o grafo: `graphify update .` (AST local, sem API, custo 0) — `graphify-out/`
não é versionado.

---

## Prompt pronto para colar na próxima sessão (qualquer dispositivo)

```
Continuar o Sistema MRO (Inventus Power). Leia @docs/HANDOFF.md e @docs/prompt.md (backlog vivo).
Branch feat/v5.0.0 — `git fetch --all --prune && git checkout feat/v5.0.0` antes de qualquer coisa.

Estado: v6.2.0 commitada e pushada (telas self-service: Requisitante, Gestor, Portaria + modo
público da guarita + correção do login por alias da v6.1.0). Gate verde, 793 testes.
A validação no app real ficou INCOMPLETA — roteiro em @docs/ROTEIRO_TESTES_V620.md (~20 min).

Próximo trabalho = v6.3.0, item 1 do topo de docs/prompt.md: o perfil ADMIN (almoxarife) tem de
ver de uma vez tudo o que há para aprovar, de TODOS os setores, sem escolher departamento — hoje
ele cai no mesmo ramo do gestor e, sem departamento cadastrado, não vê nada. Cuidado registrado
no backlog: NÃO afrouxar `listar_requisicoes_por_setor` (setor vazio devolve [] de propósito,
nega por omissão para gestor sem departamento) — criar caminho explícito para "todos os setores".
O item 2 (fila do gestor agrupada por solicitante) é ideia não fechada: PERGUNTAR antes.

Siga a skill atualizar-sistema-mro, use `graphify query` antes de abrir arquivo grande, valide com
`.\verify.ps1` (exit 0) e PARE para aprovação antes de cada commit.
```
