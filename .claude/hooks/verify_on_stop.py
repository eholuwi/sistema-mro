"""Stop: nao deixa o turno encerrar com a suite quebrada.

Implementa o "gerar -> verificar -> corrigir -> verificar": se algum .py foi mexido e
o pytest falha, devolve o erro para correcao em vez de encerrar em silencio.

Roda so `pytest` (nao o verify.ps1 inteiro) porque `format_py.py` ja formatou e
auto-corrigiu no PostToolUse — repetir ruff aqui seria redundante. O gate completo
continua sendo `.\\verify.ps1`, antes de commitar.
"""

import json
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]


def _python():
    venv = PROJ / "venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


def _ler_payload():
    """Tolera BOM (utf-8-sig) — ver nota em format_py.py."""
    bruto = sys.stdin.buffer.read()
    if not bruto:
        return {}
    return json.loads(bruto.decode("utf-8-sig"))


def _py_modificados():
    """.py alterados/nao rastreados na arvore de trabalho.

    Limitacao consciente: se o trabalho ja foi commitado, a arvore esta limpa e o hook
    pula. Aceitavel — o commit deve ter sido precedido de `.\\verify.ps1`.
    """
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJ,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return True  # sem git nao da pra decidir: melhor rodar os testes

    if r.returncode != 0:
        return True

    for linha in r.stdout.splitlines():
        if linha[3:].strip().strip('"').endswith(".py"):
            return True
    return False


def main():
    try:
        payload = _ler_payload()
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        payload = {}

    # CRITICO: sem isto o bloqueio se re-dispara em loop infinito.
    if payload.get("stop_hook_active"):
        return

    if not _py_modificados():
        return

    try:
        r = subprocess.run(
            [_python(), "-m", "pytest", "-q", "-x", "--no-header"],
            cwd=PROJ,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return  # nao trava o usuario por timeout de ferramenta
    except (subprocess.SubprocessError, OSError):
        return  # pytest indisponivel: nao e motivo pra bloquear

    if r.returncode == 0:
        return

    saida = (r.stdout or "") + (r.stderr or "")
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": (
                    "A suite de testes esta quebrada — corrija antes de encerrar.\n"
                    "Rode `.\\verify.ps1` para o gate completo.\n\n" + saida[-4000:]
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
    sys.exit(0)
