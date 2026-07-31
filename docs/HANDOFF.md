# Handoff de Sessão — Sistema MRO (para continuar em outra sessão)

> Cole/`@`-referencie este arquivo no início da próxima sessão — funciona em **qualquer dispositivo**,
> porque viaja com o `git pull` (ao contrário da memória local do Claude, que fica presa à máquina
> onde a sessão rodou).
>
> **Escopo deste arquivo:** estado atual + conhecimento durável que não está no código nem no
> `CLAUDE.md`. **O histórico versão a versão vive em `changelog/`** — não replicar aqui.

---

## STATUS ATUAL — atualizado em 31/07/2026

- **Branch de trabalho: `feat/v5.0.0`.** Não é a `main`.
  **Primeiro comando de qualquer sessão:** `git fetch --all --prune` e `git checkout feat/v5.0.0`.
  A `main` está 47 commits atrás e contém um commit órfão (`21fc73e`) com uma versão **anterior**
  do `scm_client.py` e um `requirements.txt` **sem pin** — não há nada a resgatar nele. A promoção
  da `feat/v5.0.0` para a `main` segue pendente de decisão.

- **v5.8.0 COMMITADA (`015a5cf`), gate verde (641 testes locais), PENDENTE de validação no app real.**
  Ver `changelog/5.8.0.md`. Duas entregas: backup sob demanda na tela (`services/backup.py` +
  bloco em Configurações) e pacote portátil (`scripts/portatil.py` → `MRO.exe`).
  - ⚠️ **Migração de schema ainda NÃO rodou no `mro.db` de produção:** tabela
    `configuracoes (chave, valor)`, `CREATE TABLE IF NOT EXISTS` em `criar_banco()` — aditiva pura.
  - **Roteiro de validação pendente:** (a) botão de backup com destino válido, destino apagado e
    download pelo navegador; (b) `MRO.exe` na 8501 em **máquina limpa**, incluindo fechar a janela e
    conferir que nenhum `python.exe` sobrou; (c) `atualizar_mro.bat` com o exe aberto tem que
    **abortar**; (d) reboot-test depois do `instalar_servidor.ps1`.
  - **Débito assumido (decisão do Luis):** sem listagem/exclusão de `.bak` na tela e sem retenção
    automática. Nada apaga backup, e o botão manual acelera o acúmulo.

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
