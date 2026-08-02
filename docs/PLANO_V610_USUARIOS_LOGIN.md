# Plano de Implementação — v6.1.0 · Usuários e Login local (FUNDAÇÃO)

> Documento de referência para a implementação. Quem implementar (Claude/Claude Code) segue
> este arquivo passo a passo. Decisões de produto em `docs/DECISAO_ENTREGA_FINAL_LOGIN.md`;
> o backlog vive em `docs/prompt.md` (seção "DEMANDA ABERTA — v6.1.0").
>
> **Decisões travadas em 01/08/2026 (Luis):**
> - Escopo: **só a fundação**. Telas novas (Requisitante/Gestor/Portaria) = próxima fase.
> - Login próprio (`ui/auth.py` + `services/usuarios.py`). `st.login` do Streamlit 1.60 é
>   **OIDC-only** (exige provedor externo em `.streamlit/secrets.toml` + `authlib`, que não está
>   no venv) — não existe "provider local". Usar `st.login` criaria dependência externa, vetada
>   pelo §7 do doc de decisão.
> - Credencial: **nome** (ou `primeiro.sobrenome`) + **PIN de 4 dígitos**, hash pbkdf2 (stdlib).
> - Ativação: flag `exigir_login` em `configuracoes`, **padrão DESLIGADO**.
> - Papéis manuais: **almoxarife** = Luis, Jasiva, Juan · **comprador** = Miguel, Adrya.
> - "O que o comprador vê" (definido por Luis): Dashboard, Saldo em Estoque, Ficha 360, Cadastro
>   de Itens, Controle de SC. **Sem** Movimentação nem Configurações.

---

## 1. Escopo

### Dentro
1. Tabela `usuarios` (migração aditiva) + seed idempotente a partir de `solicitantes_mro`.
2. Módulo de domínio `services/usuarios.py` (papéis, CRUD, PIN, autenticação).
3. Módulo de UI `ui/auth.py` (sessão no `st.session_state`, formulário, gate).
4. Filtro de `ROTAS` por papel no `ui/router.py` + menu filtrado no `ui/sidebar.py`.
5. Aba **Usuários** em `ui/paginas/configuracoes.py` (listar, papel, PIN, ativo) + flag
   `exigir_login` (padrão desligado).
6. Gate no `app.py` (só trava quando a flag estiver ligada).
7. `tests/test_v610_usuarios.py`.
8. Changelog `changelog/6.1.0.md` + `docs/HANDOFF.md` (STATUS ATUAL) + bump `VERSAO`.

### Fora (próxima fase)
- Telas do Requisitante ("Minhas Requisições" + criar), do Gestor (fila de aprovação) e da
  Portaria. Requisitante/gestor/portaria ficam **sem rota** nesta fase.

---

## 2. Arquivos tocados

| Arquivo | Ação |
|---|---|
| `database.py` | `CREATE TABLE IF NOT EXISTS usuarios` + índice (bloco `criar_banco`) |
| `services/usuarios.py` | **novo** — domínio de usuários/auth |
| `ui/auth.py` | **novo** — sessão + formulário + gate |
| `ui/router.py` | `ROTAS_POR_PAPEL` + `opcoes_menu(papel)`/`icones_menu(papel)` |
| `ui/sidebar.py` | menu filtrado + perfil do usuário logado |
| `ui/paginas/configuracoes.py` | aba **Usuários** (7ª aba) |
| `app.py` | `semear_usuarios()` + `gate()` antes do despacho |
| `services/constants.py` | `VERSAO = "6.1.0"` |
| `tests/test_v610_usuarios.py` | **novo** |
| `changelog/6.1.0.md` | preencher ao concluir |
| `docs/HANDOFF.md` | seção STATUS ATUAL |

**Regra de dependência preservada:** `services/*` não importa `ui/`. O mapa rota→papel vive em
`ui/router.py` (nome de rota é conceito de UI); `services/usuarios.py` conhece só `PAPEIS`.

---

## 3. Schema — `database.py`

Adicionar no bloco de `criar_banco()` (mesmo padrão do `solicitantes_mro`, v5.1.0
`itens_sc_externos` — `CREATE TABLE IF NOT EXISTS`, aditiva, sem backup):

```sql
-- v6.1.0 — Usuários e login local (100% local, sem dependência externa).
-- pin_hash = 'pbkdf2:sha256:200000:<salt_hex>:<hash_hex>' | NULL = sem PIN (não autentica).
-- ident_norm = chave única de busca: NFKD sem acento, sem ponto, sem espaço, minúsculo
--              (permite logar por "Jasiva Lopes", "jasiva.lopes" ou " JASIVA  LOPES ").
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nome          TEXT NOT NULL,
    nome_norm     TEXT NOT NULL UNIQUE,
    login         TEXT,
    ident_norm    TEXT NOT NULL UNIQUE,
    pin_hash      TEXT,
    papel         TEXT NOT NULL DEFAULT 'requisitante',
    departamento  TEXT,
    ativo         INTEGER DEFAULT 1,
    solic_mro_id  INTEGER REFERENCES solicitantes_mro(id) ON DELETE SET NULL,
    ultimo_login  TEXT,
    data_registro TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_usuarios_papel ON usuarios(papel);
```

Notas:
- `nome_norm` usa o `_normalizar_nome` já existente em `database.py` (NFKD, sem acento,
  minúsculo, espaços colapsados) — mesma regra do `solicitantes_mro`.
- `login` é alias de exibição `primeiro.sobrenome` (o Luis pensa nos usuários assim:
  `miguel.nascimento`). Pode ser NULL (nome em 1 palavra).
- `solic_mro_id` liga o usuário ao solicitante de origem (ON DELETE SET NULL para nunca
  apagar um usuário quando o solicitante sair do escopo).
- A tabela é **nova e vazia** ao migrar: não toca dado existente → segue o padrão v5.1.0,
  **sem `_backup_db`**. Se no futuro o seed passar a reescrever papel de linhas existentes,
  exige backup antes (regra inviolável nº4).

---

## 4. Domínio — `services/usuarios.py` (novo)

Módulo novo **justificado**: autenticação é domínio novo; `services/db_functions.py` já tem
~5.400 linhas. Usa `database.transaction()`/`get_connection()` (importar de `database`).

### Constantes
```python
PAPEIS = ("almoxarife", "comprador", "requisitante", "gestor", "portaria")
ROTULO_PAPEL = {
    "almoxarife": "Almoxarife",
    "comprador": "Comprador",
    "requisitante": "Requisitante",
    "gestor": "Gestor de setor",
    "portaria": "Portaria",
}
CHAVE_EXIGIR_LOGIN = "exigir_login"
PIN_DIGITS = 4
PBKDF2_ITERACOES = 200_000
```

### Funções (assinaturas e contratos)

```python
def _gerar_login(nome: str) -> str | None
# 'primeiro.sobrenome' sem acento (NFKD), minúsculo. 1 palavra → None.
# 'Juan Tarco Pinheiro de Araujo' → 'juan.araujo'.

def _gerar_ident_norm(nome: str) -> str
# NFKD sem acento, minúsculo, remove '.' e espaços → 'jasivalopes'.

def _hash_pin(pin: str) -> str
# 'pbkdf2:sha256:200000:<salt_hex>:<hash_hex>'; salt = os.urandom(16).

def verificar_pin(pin: str, pin_hash: str | None) -> bool
# False se pin_hash None. Comparação em tempo constante (hmac.compare_digest).

def semear_usuarios() -> int
# Idempotente. Devolve nº de usuários CRIADOS nesta execução (0 se nada novo).
# 1) solic_mro = SELECT id, nome, departamento FROM solicitantes_mro
#    → INSERT OR IGNORE (por nome_norm) papel='requisitante', departamento copiado,
#      solic_mro_id preenchido.
# 2) PAPEIS_MANUAIS (mapa nome→papel, nomes normalizados) — aplica SÓ no INSERT:
#    usuário que já existe NUNCA é reescrito (respeita edição feita na Configurações).
# 3) Miguel Nascimento e Adrya Vigil podem não existir em solicitantes_mro → cria mesmo assim.
# PAPEIS_MANUAIS = {
#   "luis gabriel arruda de oliveira": "almoxarife",
#   "jasiva lopes":                    "almoxarife",
#   "juan tarco pinheiro de araujo":   "almoxarife",
#   "miguel nascimento":               "comprador",
#   "adrya vigil":                     "comprador",
# }

def autenticar(identificador: str, pin: str) -> dict | None
# Normaliza identificador via _gerar_ident_norm e busca por ident_norm.
# Exige: usuário existe, ativo=1, pin_hash definido e verificar_pin ok.
# Sucesso: grava ultimo_login (CURRENT_TIMESTAMP) e devolve dict do usuário SEM pin_hash.
# Falha: None (mensagem genérica na UI — não revelar o que falhou).

def listar_usuarios() -> list[dict]
# ORDER BY papel, nome. Devolve nome, login, papel, departamento, ativo, tem_pin (bool),
# data_registro, ultimo_login.

def salvar_usuario(nome: str, papel: str, departamento: str = "") -> tuple[bool, str]
# Valida nome e papel ∈ PAPEIS. INSERT OR IGNORE por nome_norm. (Uso futuro/Configurações.)

def definir_papel(usuario_id: int, papel: str) -> tuple[bool, str]
# Valida papel. Nunca permite desativar o ÚLTIMO almoxarife ativo (guarda: ao menos 1 admin).

def definir_pin(usuario_id: int, pin: str) -> tuple[bool, str]
# Valida: str(pin).isdigit() e len == 4. Grava _hash_pin(pin). Mensagem em pt-BR.

def remover_pin(usuario_id: int) -> tuple[bool, str]
# pin_hash = NULL (usuário deixa de autenticar).

def ativar_usuario(usuario_id: int, ativo: bool) -> tuple[bool, str]
# Mesma guarda do último almoxarife ao desativar.

def exigir_login() -> bool
# SELECT valor FROM configuracoes WHERE chave='exigir_login'; ausente/'' → False.

def definir_exigir_login(valor: bool) -> None
# INSERT ... ON CONFLICT(chave) DO UPDATE (mesmo padrão de services/backup.py).
```

### Guarda "último almoxarife" (borda obrigatória)
`definir_papel` e `ativar_usuario` recusam a operação se o alvo é o **único** `usuarios`
com `papel='almoxarife' AND ativo=1`. Mensagem: "Não é possível remover o último almoxarife
ativo."

---

## 5. UI — `ui/auth.py` (novo)

```python
SESSAO_USUARIO = "mro_usuario"

def usuario_logado() -> dict | None          # st.session_state.get(SESSAO_USUARIO)
def fazer_login(identificador, pin) -> tuple[bool, str]
# chama services.usuarios.autenticar; sucesso grava SESSAO_USUARIO e st.rerun().
def fazer_logout() -> None                    # limpa a chave e st.rerun()
def render_login() -> None
# Card central: título "Acesso ao MRO", st.text_input (nome ou login), st.text_input
# (PIN, type="password", max_chars=4, help "PIN de 4 dígitos"). Botão "Entrar".
# Mensagem de erro genérica ("Usuário ou PIN inválidos."). Botão "Voltar" só se já houve
# sessão (reusa st.session_state anterior — evita prender o almoxarife que errou o PIN).
def gate() -> None
# if services.usuarios.exigir_login() and not usuario_logado(): render_login(); st.stop()
```

Regra de UX: com a flag **desligada** (padrão), `gate()` não faz nada — o app roda exatamente
como hoje. `render_login()` nunca aparece em produção sem o Luis ligar a flag.

---

## 6. Rotas e menu — `ui/router.py` + `ui/sidebar.py`

### `ui/router.py`
```python
ROTAS_POR_PAPEL: dict[str, frozenset[str]] = {
    "almoxarife": frozenset(ROTAS.keys()),                       # 7 rotas
    "comprador":  frozenset({"Dashboard", "Saldo em Estoque",
                             "Ficha 360", "Cadastro de Itens", "Controle de SC"}),  # 5
    "requisitante": frozenset(),                                 # telas novas → próxima fase
    "gestor":       frozenset(),
    "portaria":     frozenset(),
}

def opcoes_menu(papel: str | None = None) -> list[str]
# papel None → todas (comportamento atual, backward-compat: testes v410/v530).
# Caso contrário → ROTAS_POR_PAPEL[papel] na ordem de ROTAS.
def icones_menu(papel: str | None = None) -> list[str]  # espelho de opcoes_menu
```

### `ui/sidebar.py`
- `render_sidebar()` lê `ui.auth.usuario_logado()`.
- Menu: `opcoes_menu(papel)` / `icones_menu(papel)` onde `papel = usuario["papel"]` se logado,
  senão `None`.
- Rodapé do perfil:
  - sem login (flag off): mantém o bloco hardcoded "Luis Oliveira / Inventus Power"
    (comportamento atual, inalterado).
  - logado: nome real + rótulo do papel (`ROTULO_PAPEL`) + botão "Sair" (`fazer_logout`).
  - logado e flag off é possível (gate não ativo): idem logado.
- Se `opcoes_menu(papel)` devolver lista vazia (ex.: requisitante), mostra
  `st.info("Seu perfil ainda não tem telas. Fale com o almoxarife.")` e `st.stop()`.

---

## 7. Aba Usuários — `ui/paginas/configuracoes.py`

Nova aba (vira a 7ª; a página usa `st.tabs`). Importa de `services.usuarios`.

Conteúdo:
1. **Flag `exigir_login`** — `st.toggle("Exigir login para acessar o sistema", value=exigir_login())`.
   Ao ligar, `st.warning` explicando: "Ao ligar, todo acesso passa a exigir nome + PIN. Você
   precisa definir o PIN dos usuários antes — senão ninguém entra." Persiste na hora.
2. **Lista de usuários** — `st.dataframe` com nome, login, papel, departamento, ativo,
   "PIN definido" (sim/não). Formatação pt-BR.
3. **Ações por usuário** — para cada linha (ou via `st.selectbox` + formulário abaixo):
   - alterar papel (`st.selectbox` com `PAPEIS`);
   - definir/alterar PIN (`st.text_input` senha, valida 4 dígitos);
   - remover PIN (botão);
   - ativar/desativar (`st.checkbox` "Ativo").
   Toda ação chama a função de `services.usuarios` e mostra o retorno `(ok, msg)`.
4. Aviso fixo no topo: "Login 100% local — os usuários vivem no mro.db. Não depende da API
   do SCM nem de Kódigos/TI."

O componente de ações pode usar o padrão de formulário por usuário com chave única
(`key=f"usr_{id}_pin"`), evitando colisão de widget (lição do v5.9.0).

---

## 8. Gate — `app.py`

```
import ... de services.usuarios: semear_usuarios, exigir_login (via ui.auth.gate)
...
criar_banco()
semear_usuarios()                     # idempotente; corre no 1º render, barato
...
from ui.auth import gate
gate()                                # trava SÓ se exigir_login ligado e sem sessão
pagina = render_sidebar()
render_pagina(pagina)
```

`gate()` roda **antes** de `render_sidebar()` (menu não aparece deslogado).

---

## 9. Testes — `tests/test_v610_usuarios.py` (novo)

Usa fixtures `db`, `make_item` do `conftest.py` (banco isolado). Importar `services.usuarios as U`.

| # | Teste | O que afirma |
|---|---|---|
| 1 | `test_tabela_usuarios_criada_idempotente` | banco vazio → tabela existe com colunas esperadas; 2º `criar_banco()` não quebra |
| 2 | `test_seed_cria_requisitantes_de_solicitantes_mro` | insere 1 solicitante (INSERT em `solicitantes_mro`) → `semear_usuarios()` cria requisitante com departamento copiado |
| 3 | `test_seed_papeis_manuais` | Luis/Jasiva/Juan = almoxarife; Miguel/Adrya = comprador, criados mesmo sem linha em solicitantes_mro |
| 4 | `test_seed_idempotente_e_respeita_edicao` | 2º seed não cria duplicado; `definir_papel` manual → seed não reverte |
| 5 | `test_autenticar_pin_correto_e_errado` | PIN "1234" → dict; "0000" → None; sem PIN (pin_hash None) → None |
| 6 | `test_autenticar_normaliza_identificador` | "Jasiva Lopes", "jasiva.lopes", " JASIVA  LOPES " → mesma conta |
| 7 | `test_pin_armazenado_com_hash` | `pin_hash` ≠ PIN em texto; `verificar_pin` roundtrip; formato `pbkdf2:sha256:...` |
| 8 | `test_definir_pin_valida_4_digitos` | aceita "1234"; recusa "123", "abcd", "12 34", "" |
| 9 | `test_guarda_ultimo_almoxarife` | tenta desativar/trocar papel do último almoxarife → recusa; com 2 admins, permite |
| 10 | `test_exigir_login_default_false` | banco novo → `exigir_login()` é False; `definir_exigir_login(True)` → True |
| 11 | `test_rotas_por_papel` | almoxarife = 7; comprador = 5 e sem Movimentação/Configurações; requisitante = vazio; `opcoes_menu(None)` = todas |
| 12 | `test_smoke_gate_apptest` | AppTest: flag ligada + sem sessão → `gate()` para o app (não renderiza menu) |

Bordas cobertas além do feliz: PIN em texto nunca no banco, usuário inativo não autentica,
login de 1 palavra (login alias None, autentica por nome), nomes com acento/caixa.

---

## 10. Migração / backup / compatibilidade

- Migração: **aditiva** (CREATE TABLE IF NOT EXISTS + índice). Sem backfill de dado existente.
- Backup: **não necessário** nesta fase (padrão v5.1.0). Se algo do seed vier a escrever em
  linha existente, exigir `_backup_db` antes (regra inviolável nº4).
- Compatibilidade: flag `exigir_login` ausente → False → app roda idêntico ao atual.
  `opcoes_menu()`/`icones_menu()` sem argumento mantêm o contrato antigo (testes v410/v530
  não quebram).
- `services/usuarios.py` entra sozinho no pacote de release (o `test_v550_release.py` lê
  `services/` dinamicamente — verificar no gate).

---

## 11. Definição de Pronto

- [ ] `services/usuarios.py` + `ui/auth.py` implementados e testados
- [ ] `tests/test_v610_usuarios.py` verde (rodar isolado e na suíte)
- [ ] `.\verify.ps1` retorna exit 0 (ruff format + lint + pytest completo)
- [ ] Bump `VERSAO = "6.1.0"` em `services/constants.py`
- [ ] Changelog `changelog/6.1.0.md` preenchido (o esqueleto já existe)
- [ ] `docs/HANDOFF.md` seção STATUS ATUAL atualizada
- [ ] **Validação no app real (regra nº6):** com o Luis —
  1. subir o app com flag off → comportamento atual intacto;
  2. ligar `exigir_login` na Configurações → desloga, tela de login aparece;
  3. definir PIN de Luis → logar como almoxarife → menu com 7 rotas;
  4. logar como Miguel/Adrya → menu com 5 rotas (sem Movimentação/Configurações);
  5. PIN errado → recusa sem mensagem específica;
  6. desligar a flag → app volta a abrir direto.
- [ ] **OK explícito do Luis** antes de qualquer commit (regra nº6)
- [ ] `graphify update .` ao final (grafo)

## 12. Ordem de implementação

1. `database.py` (tabela) → 2. `services/usuarios.py` → 3. `tests/test_v610_usuarios.py`
   (domínio testado antes da UI) → 4. `ui/auth.py` → 5. `ui/router.py` + `ui/sidebar.py` →
   6. `ui/paginas/configuracoes.py` → 7. `app.py` → 8. bump versão + changelog + HANDOFF →
   9. `.\verify.ps1` → 10. validação no app real com o Luis → 11. commit (só com OK).
