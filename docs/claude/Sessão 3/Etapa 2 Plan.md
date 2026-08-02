# Etapa 2 — Análise Técnica v6.2.0 (Telas Self-Service)

## Contexto

A Etapa 1 mapeou os pontos de toque (arquivo:linha) para as 3 telas novas (Requisitante,
Gestor, Portaria) descritas em `docs/claude/Sessão 3/PLANO_V620_TELAS_SELF_SERVICE.md`. A
Etapa 2 pediu a análise técnica desse plano **sem alterar código**: confirmar que ele bate com
o estado real do repositório (`c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro`,
branch `feat/v5.0.0`, HEAD em `cded88c` = v6.1.0), levantar riscos e apontar dúvidas antes da
implementação (Etapa 3). Todo o código abaixo foi lido diretamente — nada foi assumido do
plano sem conferência.

**Veredito geral: o plano está tecnicamente correto e consistente com o código real.** Achei
duas imprecisões factuais pequenas (contagem de setores; lista de arquivos de teste afetados)
e um ponto de atenção de implementação (mecanismo de `key`-less widgets em
`_req_bloco_identificacao`) — nenhum bloqueador.

---

## 1. Migração (`database.py`) — validado

- `cols_req` vem de `PRAGMA table_info(requisicoes)` em `database.py:910`.
- O padrão a copiar é `tipo_fluxo` (`database.py:963-971`), e é **literalmente** commit → backup
  → dois `ALTER TABLE ADD COLUMN` — o trecho proposto no plano reproduz essa ordem exata.
- `CREATE TABLE requisicoes` (`database.py:280-297`) tem `CHECK(status IN ('Aberta','Parcial',
  'Entregue','Cancelada'))` na linha 294. `aprovado_por`/`aprovado_em` entram como colunas soltas,
  fora de qualquer CHECK — confirmado, sem risco de violar a constraint de status.
- Armadilha do WAL: `_backup_db` (`database.py:985-1017`) já lê o retorno de
  `PRAGMA wal_checkpoint(TRUNCATE)` (linha 999, `busy, _, _`) e **avisa em vez de abortar**
  (`logger.warning`, 1001-1006) — padrão coberto por
  `tests/test_v550_backup.py:62-83`. O trecho novo reaproveita esse `_backup_db` sem duplicar a
  lógica.
- Idempotência: `_migrar()` roda a cada boot (`database.py:788`, dentro de `criar_banco()`). O
  teste-referência mais próximo é `tests/test_v570_requisicao_padrao.py:333-346`
  (`test_migracao_e_idempotente`), que já testa exatamente esse padrão de `if coluna not in
  cols` rodando `criar_banco()` duas vezes.
- `aprovado_por`/`aprovado_em` não existem hoje em nenhum `CREATE TABLE`/`_migrar` nem são
  referenciados em `services/` ou `ui/` — migração genuinamente nova, sem colisão de nome.

**Conclusão:** nada a corrigir no bloco de migração do plano; é uma cópia fiel e segura do
padrão `tipo_fluxo`.

---

## 2. Domínio (`services/db_functions.py`) — validado, com reuso confirmado

- `listar_requisicoes` (`db_functions.py:1687-1711`) usa:
  ```sql
  SELECT r.*, COUNT(ir.id) total_itens, SUM(ir.quantidade_atendida) total_atendido
  FROM requisicoes r LEFT JOIN itens_requisicao ir ON ir.requisicao_id=r.id
  {filtro} GROUP BY r.id ORDER BY r.data_hora DESC LIMIT ?
  ```
  Reutilizável tal qual para as duas funções novas, só trocando o `WHERE`:
  `buscar_requisicao_por_numero` → `WHERE UPPER(TRIM(r.numero_requisicao)) = UPPER(TRIM(?))`
  (sem `LIMIT`); `listar_requisicoes_por_setor` → `WHERE UPPER(TRIM(r.setor)) = UPPER(TRIM(?))`.
  Itens vêm à parte via `listar_itens_requisicao(req_id, conn=conn)` — mesmo padrão já usado
  dentro de `criar_requisicao_com_baixa` (`db_functions.py:1492`).
- **Separação `autorizador_*` × `aprovado_por` confirmada como genuinamente independente hoje**:
  `autorizador_tipo`/`autorizador_nome` só existem no fluxo de entrega — opcional em
  `criar_requisicao` (1262-1313), obrigatório em `criar_requisicao_com_baixa` (linha 1458) e em
  `entregar_requisicao` (linha 1540), persistidos via UPDATE em `db_functions.py:1572-1573`. Não
  há hoje nenhuma validação cruzada entre esses campos e uma futura `aprovado_por` — a nova
  coluna entra puramente aditiva, sem tocar o fluxo de entrega. Isso confirma a decisão do plano
  ("aprovação não bloqueante").
- Contagem real no `mro.db`: **59 setores distintos** em `requisicoes.setor` (case/trim
  insensível) — o plano cita 57. Departamentos em `usuarios.departamento`: **19** (bate).
  Interseção: **9** (bate). A divergência de 2 no total de setores é pequena e não muda a
  conclusão do plano (o filtro por igualdade simples deixa fora requisições legadas fora da
  interseção), mas vale recontar antes de fechar o número definitivo no `changelog/6.2.0.md`.
- `services/usuarios.py`: `PAPEIS = ("almoxarife","comprador","requisitante","gestor",
  "portaria")` (usuarios.py:33), tabela `usuarios` já tem `departamento` (schema
  `database.py:679-693`), `exigir_login()` (usuarios.py:312-321) trata ausência de config como
  `False` — retrocompatível.
- Arquitetura: `services/db_functions.py` **não importa `ui/`** (confirmado nos imports do topo
  do arquivo) — a regra de dependência do CLAUDE.md segue intacta; as 3 funções novas não a
  quebram.

---

## 3. Camada UI (`ui/auth.py`, `ui/router.py`, `ui/sidebar.py`, `ui/paginas/movimentacao.py`) — validado com 1 ponto de atenção

- `gate()` hoje é literalmente `if exigir_login() and not usuario_logado(): render_login();
  st.stop()` (`ui/auth.py:102-104`). Acrescentar `and not em_modo_publico()` é uma mudança
  mínima, sem outro `st.stop()` concorrente no arquivo.
- `render_login()` já tem precedente de botão fora do `st.form` (o botão "Voltar" em
  `ui/auth.py:92-93`, condicionado a `usuario_logado()`) — um segundo botão "Consulta de saída
  — Portaria" segue o mesmo padrão, sem conflito com o form.
- `ROTAS` tem **7 chaves hoje** (`ui/router.py:38-46`) — o "38" do mapa da Etapa 1 era o número
  da linha, não a contagem. `requisitante`/`gestor`/`portaria` já existem em `ROTAS_POR_PAPEL`
  mas mapeiam para `frozenset()` vazio (`ui/router.py:65-67`) — o comentário no código
  (`ui/router.py:57-59`) já registra que isso é proposital, "próxima fase". `opcoes_menu(None)`
  retorna `list(ROTAS.keys())` (`ui/router.py:78-79`) → hoje 7, vai para 10 quando as 3 rotas
  entrarem em `ROTAS`.
- **Correção ao plano:** a busca por `opcoes_menu(None)` nos testes mostra que só
  **`tests/test_v500_router.py:60`** (`== 7`) e **`tests/test_v610_usuarios.py:343,365`**
  (`== 7`) fixam esse número — `test_v410_ux.py` e `test_v530_dashboard.py` **não** referenciam
  `opcoes_menu`. O plano (§6, §12) cita "v410/v530/v610" para ajustar; o correto é
  **v500 + v610**. Ajustar a lista de arquivos a tocar antes da Etapa 3.
- `ui/sidebar.py`: o bloco de menu vazio já existe (`if not opcoes: st.info(...); st.stop()`,
  `ui/sidebar.py:85-91`) — é exatamente o que os 3 papéis novos recebem hoje. O ponto que
  precisa de cuidado: `papel = usuario["papel"] if usuario else None` (`ui/sidebar.py:68`) —
  **modo público e "deslogado comum" são indistinguíveis por `papel_atual()` (ambos `None`)**.
  O plano já resolve isso corretamente no §6 com um branch explícito
  `if em_modo_publico(): ...` **antes** de cair no `opcoes_menu(papel_atual())` normal — só
  reforço que essa ordem de checagem (modo público checado primeiro, independente de
  `papel_atual()`) é o único jeito de não vazar o menu completo para quem entrou pela Portaria
  pública.
- `ui/paginas/movimentacao.py`: `_req_bloco_identificacao()` já existe (linhas 666-687), **sem
  parâmetros hoje e de propósito sem `key=`** nos widgets — a docstring (669-674) explica que
  isso evita `StreamlitAPIException` ao reaproveitar `session_state` entre os fluxos Padrão e
  Digital (mesmo rótulo → Streamlit reaproveita o estado do widget). Parametrizar com
  `setor_padrao=""`/`emitente_fixo=None` é seguro **desde que**: (a) as duas chamadas existentes
  (Padrão em `movimentacao.py:868`, Digital em `movimentacao.py:936`) continuem passando os
  defaults atuais — o que já é o plano; (b) a versão parametrizada continue sem `key=` explícito
  e o `index=`/`value=` calculado a partir de `setor_padrao`/`emitente_fixo` permaneça estável
  entre reruns da mesma página (departamento do usuário não muda durante a sessão, então não há
  risco de reset). `_opcoes_setor` não existe ainda — é helper novo, sem duplicação (único
  call-site hoje seria a linha 679). `_fila_visao_solicitante` (577-663) confirma o shape citado
  no plano para a aba "Minhas Requisições".

---

## 4. Riscos (os 3 do pedido + 2 adicionais)

1. **`opcoes_menu(None)` 7→10 quebra testes fixos** — confirmado, mas o escopo real é
   `tests/test_v500_router.py` e `tests/test_v610_usuarios.py` (não v410/v530, que não tocam
   nisso). Baixo risco, mudança mecânica (trocar `7` por `10` + adicionar as 3 rotas às
   asserções de `ROTAS_POR_PAPEL`).
2. **Vocabulário divergente `setor`×`departamento`** — confirmado 59×19, interseção 9 (plano
   citava 57 setores; recontar antes do changelog). É uma limitação aceita explicitamente pelo
   Luis no plano — não é bug, é escopo. Sem ação necessária além de registrar o número certo.
3. **AppTest do modo público** — o ponto real de risco não é o AppTest em si (há precedente em
   `tests/test_v500_router.py:13`, `streamlit.testing.v1.AppTest`), é a ordem de checagem
   `em_modo_publico()` vs `papel_atual()` em `ui/sidebar.py` descrita acima — se invertida ou
   esquecida, o modo público vaza o menu completo (10 rotas) em vez de só "Portaria". O teste
   `test_smoke_gate_portaria_publica` (item 11 do plano) precisa setar
   `at.session_state[SESSAO_PUBLICA] = True` **sem** sessão de usuário e conferir que a sidebar
   mostra só "Portaria" — não só que `gate()` não trava.
4. **(Novo) Parametrização de `_req_bloco_identificacao`** — risco baixo, mas é o único lugar do
   plano que toca uma função hoje usada por dois fluxos já em produção (Padrão/Digital). Cuidado
   descrito no item 3 acima; vale um teste específico (além do `test_opcoes_setor_prefill` já
   previsto) que chame a função parametrizada e confirme que os dois fluxos existentes (sem
   argumentos) continuam idênticos — o plano já cobre isso implicitamente ("sem mudar o
   comportamento dos dois fluxos atuais", §7), só reforçando que merece asserção explícita.
5. **(Novo) Números do plano desatualizados** — 57→59 setores e a lista de arquivos de teste
   (v410/v530 → v500/v610) são o tipo de imprecisão que, se copiada sem conferir, produz um
   teste que falha por engano (contagem errada) ou um arquivo que ninguém edita (v410/v530 não
   precisam de mudança nenhuma). Vale atualizar o `PLANO_V620_TELAS_SELF_SERVICE.md` com essas
   duas correções antes da Etapa 3.

---

## 5. Dependências e ordem — confirmadas, sem mudança à ordem já proposta no plano (§14)

A ordem do plano (`database.py` → `db_functions.py` → `auth.py`+`router.py`+`sidebar.py` →
`movimentacao.py` → páginas novas → bump/changelog → `verify.ps1` → validação real → commit) está
correta e é a que a análise acima confirma: cada camada só depende da anterior (schema antes de
domínio, domínio antes de rotas/páginas, `_opcoes_setor`/`_req_bloco_identificacao` antes das
páginas que os chamam). Nenhuma dependência oculta foi encontrada.

Duas correções pontuais a aplicar no plano antes de seguir para Etapa 3:
- Trocar a menção a `tests/test_v410_ux.py`/`tests/test_v530_dashboard.py` por
  `tests/test_v500_router.py` (linha 60) na seção de arquivos de teste a ajustar.
- Recontar setores distintos em `requisicoes.setor` (59, não 57) antes de fechar o texto do
  `changelog/6.2.0.md`.

---

## 6. Dúvidas para o Luis

1. A contagem de 59 setores (vs. 57 no plano) muda alguma decisão de escopo, ou só corrige o
   número no texto? (Minha leitura: só o número — o filtro por igualdade simples já era uma
   limitação aceita independente da contagem exata.)
2. Quer que eu já corrija o `PLANO_V620_TELAS_SELF_SERVICE.md` com as duas imprecisões acima
   (arquivos de teste e contagem de setores) antes da Etapa 3, ou prefere corrigir junto da
   implementação?
3. Confirma que a Etapa 3 é a implementação seguindo a ordem do §14 do plano, sem mudanças de
   escopo — ou há algo que mudou desde 02/08/2026 que eu deva incorporar antes de começar?

---

## Verificação

Nenhuma mudança de código foi feita nesta etapa. Quando a implementação (Etapa 3) começar, o
critério de pronto continua o do `CLAUDE.md` do projeto: `.\verify.ps1` (format + lint + pytest)
com exit 0, validação no app real com o Luis, e OK explícito antes de qualquer commit.
