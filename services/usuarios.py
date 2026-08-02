"""v6.1.0 — Usuários, papéis e autenticação local (fundação).

Domínio NOVO, em módulo próprio: `services/db_functions.py` já passa de 5.000 linhas e
autenticação não é acesso a inventário. Aqui vive tudo que o banco sabe sobre gente —
quem existe, que papel tem, se pode entrar — e **nada** de interface: a sessão, o
formulário e o gate ficam em `ui/auth.py` (regra de dependência: `services/*` nunca
importa `ui/`). Por isso o mapa rota→papel NÃO mora aqui, e sim em `ui/router.py`:
nome de rota é conceito de UI; este módulo conhece só `PAPEIS`.

**Login 100% local.** O `st.login` do Streamlit 1.60 é OIDC-only (exige provedor externo
em `.streamlit/secrets.toml` + `authlib`) — usá-lo criaria a dependência externa vetada
em `docs/DECISAO_ENTREGA_FINAL_LOGIN.md` §7. A credencial é **nome + PIN de 4 dígitos**,
guardado como hash pbkdf2-sha256 da stdlib (nunca em texto).

⚠️ Não é controle de acesso à prova de adversário: um PIN de 4 dígitos tem 10 mil
combinações e o banco é um arquivo na rede interna. O objetivo declarado é **separar
papéis** (o comprador não vê Movimentação nem Configurações) e dar nome a quem age, não
resistir a ataque. Não usar para proteger dado sensível.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import unicodedata

from database import _normalizar_nome, transaction

# ── Constantes de domínio ─────────────────────────────────────────────────────

PAPEIS = ("almoxarife", "comprador", "requisitante", "gestor", "portaria")
PAPEL_PADRAO = "requisitante"

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

# Papéis definidos à mão pelo Luis (01/08/2026). Só valem no INSERT do seed: usuário que
# já existe NUNCA é reescrito, senão o seed desfaria toda edição feita em Configurações.
# Miguel e Adrya são compradores e podem não ter linha em `solicitantes_mro` (o escopo MRO
# é de quem ABRE SC, não de quem compra) — por isso o seed os cria mesmo assim.
USUARIOS_MANUAIS: tuple[tuple[str, str], ...] = (
    ("Luis Gabriel Arruda de Oliveira", "almoxarife"),
    ("Jasiva Lopes", "almoxarife"),
    ("Juan Tarco Pinheiro de Araujo", "almoxarife"),
    ("Miguel Nascimento", "comprador"),
    ("Adrya Vigil", "comprador"),
)
PAPEIS_MANUAIS: dict[str, str] = {_normalizar_nome(nome): papel for nome, papel in USUARIOS_MANUAIS}

MSG_ULTIMO_ALMOXARIFE = "Não é possível remover o último almoxarife ativo."


# ── Identidade (normalização de nome) ─────────────────────────────────────────


def _sem_acento(valor: str) -> str:
    """NFKD sem combinantes, minúsculo, sem colapsar espaços (isso é do chamador)."""
    texto = unicodedata.normalize("NFKD", str(valor or "").strip())
    return "".join(ch for ch in texto if not unicodedata.combining(ch)).lower()


def _gerar_login(nome: str) -> str | None:
    """Alias de exibição `primeiro.sobrenome` (é assim que o Luis pensa nas pessoas:
    `miguel.nascimento`). Nome de uma palavra só não tem alias → None.

    'Juan Tarco Pinheiro de Araujo' → 'juan.araujo'.
    """
    partes = _sem_acento(nome).split()
    if len(partes) < 2:
        return None
    return f"{partes[0]}.{partes[-1]}"


def _gerar_ident_norm(nome: str) -> str:
    """Chave ÚNICA de busca do login: sem acento, minúscula, sem ponto e sem espaço.

    Aplicada ao NOME COMPLETO, é o que faz 'Jasiva Lopes', ' JASIVA  LOPES ' e
    'JasivaLopes' caírem na mesma conta sem três colunas no banco.

    ⚠️ Aplicada ao ALIAS `primeiro.sobrenome`, só coincide com o `ident_norm` gravado
    quando o nome tem exatamente duas palavras — 'jasiva.lopes' → 'jasivalopes' bate, mas
    'ana.carvalho' → 'anacarvalho' não bate com 'anaclarapascoaldecarvalho'. Foi o bug de
    login da v6.1.0; quem resolve o alias hoje é `_localizar_por_identificador`, não esta
    função.
    """
    return re.sub(r"[\s.]+", "", _sem_acento(nome))


# ── PIN ───────────────────────────────────────────────────────────────────────


def _hash_pin(pin: str) -> str:
    """`pbkdf2:sha256:<iteracoes>:<salt_hex>:<hash_hex>` — salt novo a cada chamada.

    Formato autodescritivo de propósito: subir as iterações no futuro não invalida os
    PINs já gravados, porque `verificar_pin` lê o custo de dentro do próprio hash.
    """
    salt = os.urandom(16)
    derivado = hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), salt, PBKDF2_ITERACOES)
    return f"pbkdf2:sha256:{PBKDF2_ITERACOES}:{salt.hex()}:{derivado.hex()}"


def verificar_pin(pin: str, pin_hash: str | None) -> bool:
    """Confere o PIN contra o hash gravado. `pin_hash` vazio/None → False (sem PIN
    ninguém entra). Comparação em tempo constante (`hmac.compare_digest`)."""
    if not pin_hash:
        return False
    partes = str(pin_hash).split(":")
    if len(partes) != 5:
        return False
    algo, digest, iteracoes, salt_hex, esperado_hex = partes
    if algo != "pbkdf2":
        return False
    try:
        derivado = hashlib.pbkdf2_hmac(
            digest, str(pin).encode("utf-8"), bytes.fromhex(salt_hex), int(iteracoes)
        )
    except (ValueError, TypeError):
        # hash corrompido/formato desconhecido: recusa em vez de estourar na tela de login.
        return False
    return hmac.compare_digest(derivado.hex(), esperado_hex)


def _pin_valido(pin: str) -> bool:
    """Exatamente 4 dígitos ASCII. `isascii()` porque `'١٢٣٤'.isdigit()` é True e um PIN
    em algarismo arábico-índico seria impossível de redigitar no teclado do almoxarifado."""
    pin = str(pin or "")
    return len(pin) == PIN_DIGITS and pin.isdigit() and pin.isascii()


# ── Seed ──────────────────────────────────────────────────────────────────────


def _inserir_usuario(conn, nome, papel, departamento=None, solic_mro_id=None) -> bool:
    """INSERT OR IGNORE por `nome_norm`/`ident_norm`. Devolve True se CRIOU a linha.

    O OR IGNORE é o que torna o seed idempotente e não-destrutivo: rodar de novo não
    reescreve papel, PIN nem departamento de quem já existe.
    """
    nome = (nome or "").strip()
    if not nome:
        return False
    cur = conn.execute(
        "INSERT OR IGNORE INTO usuarios (nome, nome_norm, login, ident_norm, papel, "
        "departamento, solic_mro_id) VALUES (?,?,?,?,?,?,?)",
        (
            nome,
            _normalizar_nome(nome),
            _gerar_login(nome),
            _gerar_ident_norm(nome),
            papel,
            departamento,
            solic_mro_id,
        ),
    )
    return cur.rowcount > 0


def semear_usuarios() -> int:
    """Popula `usuarios` a partir de `solicitantes_mro` + os papéis manuais. Idempotente.

    Devolve quantos usuários foram CRIADOS nesta execução (0 quando não há nada novo —
    o caso normal, já que roda a cada abertura do app).

    Todo mundo nasce SEM PIN: usuário sem PIN não autentica, então ligar a flag
    `exigir_login` antes de distribuir os PINs tranca o sistema. É o motivo de a aba
    Usuários avisar isso antes de ligar o interruptor.
    """
    criados = 0
    with transaction() as conn:
        solicitantes = conn.execute("SELECT id, nome, departamento FROM solicitantes_mro").fetchall()
        for s in solicitantes:
            papel = PAPEIS_MANUAIS.get(_normalizar_nome(s["nome"]), PAPEL_PADRAO)
            if _inserir_usuario(conn, s["nome"], papel, s["departamento"], s["id"]):
                criados += 1

        # Quem tem papel manual mas não é solicitante MRO (compradores) entra aqui.
        for nome, papel in USUARIOS_MANUAIS:
            if _inserir_usuario(conn, nome, papel):
                criados += 1
    return criados


# ── Autenticação ──────────────────────────────────────────────────────────────


def _sem_segredo(row) -> dict:
    """dict da linha SEM `pin_hash` — o hash nunca sai deste módulo (nem para a sessão
    do Streamlit, que é o `st.session_state` de um navegador)."""
    usuario = {k: row[k] for k in row.keys() if k != "pin_hash"}
    usuario["tem_pin"] = bool(row["pin_hash"])
    return usuario


def _localizar_por_identificador(conn, identificador: str):
    """Linha de `usuarios` para o que a pessoa digitou. None se não achar ou se for ambíguo.

    Duas chaves, nesta ordem:

    1. `ident_norm` — o NOME COMPLETO normalizado. Sempre funciona, para todo mundo.
    2. o alias `primeiro.sobrenome` da coluna `login`.

    O passo 2 é a correção de um bug da v6.1.0 (achado em 02/08/2026, ao ligar o login para
    os requisitantes): `_gerar_login` descarta os nomes do MEIO, então o alias exibido na
    tela — 'ana.carvalho' para 'ANA CLARA PASCOAL DE CARVALHO' — não normalizava para o
    `ident_norm` gravado. A busca só por `ident_norm` recusava o login que a própria tela
    anunciava, e a mensagem genérica ("Usuário ou PIN inválidos") escondia o motivo. Num
    cadastro real de 104 pessoas, 88 caíam nisso; só quem tem nome de duas palavras entrava.

    **`login` NÃO é único** (o `UNIQUE` do schema está em `nome_norm`/`ident_norm`): duas
    pessoas cadastradas com grafias diferentes da mesma identidade — 'Miguel Magalhaes Do
    Nascimento' e 'Miguel Nascimento' — compartilham 'miguel.nascimento'. A ordem acima já
    resolve a maioria desses casos: quando alguém se chama LITERALMENTE como o alias, o
    passo 1 casa e essa pessoa vence, deterministicamente. Sobra o empate real (dois nomes
    longos, nenhum igual ao alias, como 'Luis Gabriel Arruda de Oliveira' × 'Luis Gabriel
    Oliveira'), e aí o alias é RECUSADO em vez de desempatado no chute: os candidatos podem
    ter papéis diferentes, e entrar na conta errada é pior que não entrar. Quem cair nesse
    caso usa o nome completo, que é sempre único.
    """
    ident = _gerar_ident_norm(identificador)
    if not ident:
        return None
    row = conn.execute("SELECT * FROM usuarios WHERE ident_norm=?", (ident,)).fetchone()
    if row is not None:
        return row
    # `login` já nasce sem acento e minúsculo; tirar o ponto o põe na mesma forma do
    # `ident_norm`. NULL (nome de uma palavra) nunca casa — REPLACE(NULL) é NULL.
    candidatos = conn.execute("SELECT * FROM usuarios WHERE REPLACE(login,'.','')=?", (ident,)).fetchall()
    return candidatos[0] if len(candidatos) == 1 else None


def autenticar(identificador: str, pin: str) -> dict | None:
    """Valida nome/login + PIN. Sucesso → dict do usuário (sem `pin_hash`) e `ultimo_login`
    atualizado. Falha → None, sem distinguir o motivo.

    O None único é intencional: a tela mostra uma mensagem genérica, então descobrir se
    o nome existe, se está inativo ou se só o PIN está errado exige tentativa e erro.
    """
    with transaction() as conn:
        row = _localizar_por_identificador(conn, identificador)
        if row is None or not row["ativo"] or not verificar_pin(pin, row["pin_hash"]):
            return None
        conn.execute("UPDATE usuarios SET ultimo_login=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        atual = conn.execute("SELECT * FROM usuarios WHERE id=?", (row["id"],)).fetchone()
    return _sem_segredo(atual)


# ── CRUD / administração ──────────────────────────────────────────────────────


def listar_usuarios() -> list[dict]:
    """Todos os usuários, ordenados por papel e nome. `tem_pin` no lugar do hash."""
    with transaction() as conn:
        rows = conn.execute(
            "SELECT id, nome, login, papel, departamento, ativo, "
            "       (pin_hash IS NOT NULL) AS tem_pin, data_registro, ultimo_login "
            "FROM usuarios ORDER BY papel, nome"
        ).fetchall()
    return [dict(r) | {"tem_pin": bool(r["tem_pin"]), "ativo": bool(r["ativo"])} for r in rows]


def salvar_usuario(nome: str, papel: str, departamento: str = "") -> tuple[bool, str]:
    """Cria um usuário à mão (quem não veio do seed). Retorna (ok, msg)."""
    nome = (nome or "").strip()
    if not nome:
        return False, "Informe o nome do usuário."
    if papel not in PAPEIS:
        return False, f"Papel inválido: {papel!r}."
    with transaction() as conn:
        criado = _inserir_usuario(conn, nome, papel, (departamento or "").strip() or None)
    if not criado:
        return False, f"Já existe um usuário com o nome {nome!r}."
    return True, f"Usuário {nome!r} criado como {ROTULO_PAPEL[papel]}."


def _e_ultimo_almoxarife(conn, usuario_id: int) -> bool:
    """O alvo é o ÚNICO almoxarife ativo? Guarda contra o sistema ficar sem administrador —
    ninguém poderia reverter, porque a aba Usuários só existe para o almoxarife."""
    row = conn.execute("SELECT papel, ativo FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    if row is None or row["papel"] != "almoxarife" or not row["ativo"]:
        return False
    (n,) = conn.execute("SELECT COUNT(*) FROM usuarios WHERE papel='almoxarife' AND ativo=1").fetchone()
    return n <= 1


def definir_papel(usuario_id: int, papel: str) -> tuple[bool, str]:
    """Troca o papel. Recusa se isso removeria o último almoxarife ativo."""
    if papel not in PAPEIS:
        return False, f"Papel inválido: {papel!r}."
    with transaction() as conn:
        row = conn.execute("SELECT nome, papel FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
        if row is None:
            return False, "Usuário não encontrado."
        if row["papel"] == papel:
            return True, f"{row['nome']} já é {ROTULO_PAPEL[papel]}."
        if papel != "almoxarife" and _e_ultimo_almoxarife(conn, usuario_id):
            return False, MSG_ULTIMO_ALMOXARIFE
        conn.execute("UPDATE usuarios SET papel=? WHERE id=?", (papel, usuario_id))
    return True, f"{row['nome']} agora é {ROTULO_PAPEL[papel]}."


def definir_pin(usuario_id: int, pin: str) -> tuple[bool, str]:
    """Grava o hash do PIN (4 dígitos). O PIN em texto não é persistido em lugar nenhum."""
    if not _pin_valido(pin):
        return False, f"O PIN precisa ter exatamente {PIN_DIGITS} dígitos (só números)."
    with transaction() as conn:
        row = conn.execute("SELECT nome FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
        if row is None:
            return False, "Usuário não encontrado."
        conn.execute("UPDATE usuarios SET pin_hash=? WHERE id=?", (_hash_pin(pin), usuario_id))
    return True, f"PIN definido para {row['nome']}."


def remover_pin(usuario_id: int) -> tuple[bool, str]:
    """Apaga o PIN — o usuário deixa de conseguir entrar (não é o mesmo que desativar)."""
    with transaction() as conn:
        row = conn.execute("SELECT nome FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
        if row is None:
            return False, "Usuário não encontrado."
        conn.execute("UPDATE usuarios SET pin_hash=NULL WHERE id=?", (usuario_id,))
    return True, f"PIN removido — {row['nome']} não consegue mais entrar até definir outro."


def ativar_usuario(usuario_id: int, ativo: bool) -> tuple[bool, str]:
    """Liga/desliga o acesso preservando o cadastro. Mesma guarda do último almoxarife."""
    with transaction() as conn:
        row = conn.execute("SELECT nome FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
        if row is None:
            return False, "Usuário não encontrado."
        if not ativo and _e_ultimo_almoxarife(conn, usuario_id):
            return False, MSG_ULTIMO_ALMOXARIFE
        conn.execute("UPDATE usuarios SET ativo=? WHERE id=?", (1 if ativo else 0, usuario_id))
    return True, f"{row['nome']} {'ativado' if ativo else 'desativado'}."


# ── Flag `exigir_login` (chave/valor em `configuracoes`) ───────────────────────


def exigir_login() -> bool:
    """O app exige login? Chave ausente ou vazia → **False** (padrão desligado).

    É o que garante a compatibilidade da v6.1.0: um `mro.db` que nunca viu esta versão
    abre exatamente como antes, sem tela de login.
    """
    with transaction() as conn:
        row = conn.execute("SELECT valor FROM configuracoes WHERE chave=?", (CHAVE_EXIGIR_LOGIN,)).fetchone()
    valor = (row["valor"] or "").strip().lower() if row else ""
    return valor in ("1", "true", "sim")


def definir_exigir_login(valor: bool) -> None:
    """Liga/desliga a exigência de login (mesmo upsert de `services/backup.py`)."""
    with transaction() as conn:
        conn.execute(
            "INSERT INTO configuracoes (chave, valor) VALUES (?,?) "
            "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
            (CHAVE_EXIGIR_LOGIN, "1" if valor else "0"),
        )
