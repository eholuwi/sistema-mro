# Handoff de Sessão — Sistema MRO (para continuar em outra sessão)

> Cole/`@`-referencie este arquivo no início da próxima sessão — funciona em **qualquer dispositivo**,
> porque viaja com o `git pull` (ao contrário da memória local do Claude, que fica presa à máquina
> onde a sessão rodou).
>
> **Escopo deste arquivo:** estado atual + conhecimento durável que não está no código nem no
> `CLAUDE.md`. **O histórico versão a versão vive em `changelog/`** — não replicar aqui.

---

## STATUS ATUAL — atualizado em 31/07/2026

- **Branch de trabalho: `feat/v5.0.0`.**
  **Primeiro comando de qualquer sessão:** `git fetch --all --prune` e `git checkout feat/v5.0.0`.
  **Em 31/07/2026 a `main` foi realinhada** (`git branch -f` + force-push): estava 47 commits atrás
  e carregava um commit órfão (`21fc73e`) com uma versão **anterior** do `scm_client.py` e um
  `requirements.txt` **sem pin** — descartado por decisão do Luis, nada a resgatar. As duas branches
  agora apontam para o mesmo commit; quem clonar o repositório cai no estado atual.

- **v5.9.0 IMPLEMENTADA, gate verde (688 testes), ⏳ AGUARDANDO VALIDAÇÃO NO APP REAL E OK DO
  LUIS PARA COMMIT** (regra inviolável nº6). Ver `changelog/5.9.0.md`. Sete entregas: Dashboard do
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
    com "Material saindo agora" desmarcado grava a data informada.
  - **🔴 PENDENTE — "Material saindo agora" falta na Requisição Padrão** (retorno do Luis,
    31/07/2026). Hoje o checkbox existe só na **fila do almoxarife**
    (`ui/paginas/movimentacao.py:510`, `_fila_visao_almoxarife`) — que **fica como está**. Falta o
    mesmo checkbox na tela de **Nova Requisição → Requisição Padrão**, que é onde o material sai na
    hora e, portanto, onde a data retroativa mais importa.
    **O serviço já está pronto e testado:** `criar_requisicao_com_baixa` já aceita `data_saida=None`
    e `tests/test_v590_data_saida.py::test_requisicao_padrao_respeita_a_data_de_saida` já cobre os
    dois caminhos. **É só UI** — replicar o bloco do checkbox e passar `data_saida=` na chamada.
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

## Prompt pronto para colar na próxima sessão (qualquer dispositivo)

```
Continuar o Sistema MRO (Inventus Power). Leia @docs/HANDOFF.md e @docs/prompt.md (backlog vivo).
Trabalhe na branch feat/v5.0.0 — `git fetch --all --prune && git checkout feat/v5.0.0` antes de
qualquer coisa. Estado: v5.8.0 commitada (015a5cf), 641 testes verdes, validação no app real
PENDENTE (roteiro no HANDOFF). Próximo passo do plano: passada global de UX (barra_filtros /
tabela_paginada nas tabelas cruas da F4a), página a página com validação — nunca em bloco.
Siga a skill atualizar-sistema-mro, use `graphify query` antes de abrir arquivo grande, valide com
`.\verify.ps1` (exit 0) e PARE para aprovação antes de cada commit.
```
