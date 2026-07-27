"""v5.8.0 — Backup sob demanda do `mro.db`, disparado pela tela (Configurações).

Até aqui os `.bak` só nasciam sozinhos: antes de migração destrutiva (`criar_banco`/
`_migrar`) e uma vez por dia no sync da API (`scm_sync._backup_1x_dia`). Isso cobre
migração, **não** perda de disco — a lacuna que `docs/INSTALACAO_SERVIDOR.md` já admitia
("configure uma cópia de `C:\\MRO\\dados\\` para outro destino") e que ninguém configurou.

Duas metades:

- **Gerar** — `fazer_backup()` NÃO reimplementa a cópia: chama `database._backup_db`, que já
  resolve a armadilha paga do projeto (o `PRAGMA wal_checkpoint` devolve BUSY como valor de
  retorno, não exceção — ver `tests/test_v550_backup.py`). Aqui só se acrescenta a cópia
  para um segundo destino.
- **Destino extra** — um caminho gravado em `configuracoes['backup_destino']`, editável na
  tela. Falha ao copiar para lá **não invalida** o `.bak` principal, que já está em disco:
  perder o backup porque o pendrive não estava plugado seria o pior desfecho possível.

⚠️ O destino mora no `mro.db`, e o banco viaja junto quando o servidor muda de máquina —
um `D:\\Backups` que não existe no destino chega junto. Por isso `validar_destino()` é
pública: a tela revalida a cada render e mostra o aviso, em vez de o backup ir calado
para lugar nenhum.
"""

from __future__ import annotations

import os
import shutil

from database import _backup_db, transaction

CHAVE_DESTINO = "backup_destino"


# ── Destino configurável ──────────────────────────────────────────────────────


def destino_configurado() -> str | None:
    """Caminho gravado em `configuracoes['backup_destino']`, ou None se não houver."""
    with transaction() as conn:
        row = conn.execute("SELECT valor FROM configuracoes WHERE chave=?", (CHAVE_DESTINO,)).fetchone()
    valor = (row["valor"] or "").strip() if row else ""
    return valor or None


def validar_destino(caminho: str) -> tuple[bool, str]:
    """A pasta serve para receber backup **nesta máquina**? (existe, é pasta, é gravável)

    Separada de `definir_destino` porque a tela precisa revalidar a cada render: o caminho
    pode ter sido gravado noutro servidor, ou o disco externo pode não estar montado agora.
    """
    caminho = (caminho or "").strip()
    if not caminho:
        return False, "Informe uma pasta."
    if not os.path.exists(caminho):
        return False, f"A pasta não existe nesta máquina: {caminho}"
    if not os.path.isdir(caminho):
        return False, f"O caminho existe mas não é uma pasta: {caminho}"
    if not os.access(caminho, os.W_OK):
        return False, f"Sem permissão de escrita na pasta: {caminho}"
    return True, "Pasta válida."


def definir_destino(caminho: str) -> tuple[bool, str]:
    """Grava (ou limpa, com string vazia) a pasta de destino extra dos backups."""
    caminho = (caminho or "").strip()

    if not caminho:
        with transaction() as conn:
            conn.execute("DELETE FROM configuracoes WHERE chave=?", (CHAVE_DESTINO,))
        return True, "Pasta de destino removida — os backups ficam só em `backups/`."

    ok, msg = validar_destino(caminho)
    if not ok:
        return False, msg

    with transaction() as conn:
        conn.execute(
            "INSERT INTO configuracoes (chave, valor) VALUES (?,?) "
            "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
            (CHAVE_DESTINO, caminho),
        )
    return True, f"Destino salvo: {caminho}"


# ── Backup ────────────────────────────────────────────────────────────────────


def _mesma_pasta(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def fazer_backup(sufixo: str = "manual") -> dict:
    """Gera um `.bak` em `backups/` e, se houver destino configurado, copia para lá.

    Devolve `{"ok", "caminho", "nome", "tamanho", "destino_extra", "erro_destino"}`.
    `ok` reflete **só** o backup principal: com `erro_destino` preenchido e `ok=True` o
    arquivo existe em `backups/` e apenas a segunda cópia falhou.
    """
    resultado = {
        "ok": False,
        "caminho": None,
        "nome": None,
        "tamanho": 0,
        "destino_extra": None,
        "erro_destino": None,
    }

    caminho = _backup_db(sufixo)
    if not caminho or not os.path.exists(caminho):
        resultado["erro_destino"] = None
        return resultado

    resultado.update(
        ok=True,
        caminho=caminho,
        nome=os.path.basename(caminho),
        tamanho=os.path.getsize(caminho),
    )

    destino = destino_configurado()
    if not destino:
        return resultado

    # A partir daqui o .bak principal já está gravado: nada abaixo pode derrubar `ok`.
    try:
        if _mesma_pasta(destino, os.path.dirname(caminho)):
            resultado["destino_extra"] = caminho
            return resultado
        ok, msg = validar_destino(destino)
        if not ok:
            resultado["erro_destino"] = msg
            return resultado
        copia = os.path.join(destino, os.path.basename(caminho))
        shutil.copy2(caminho, copia)
        resultado["destino_extra"] = copia
    except Exception as e:
        resultado["erro_destino"] = f"Não foi possível copiar para {destino}: {e}"

    return resultado
