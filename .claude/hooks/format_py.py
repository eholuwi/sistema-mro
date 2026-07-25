"""PostToolUse: formata e auto-corrige o .py que acabou de ser editado.

Chamado pelo Claude Code apos Edit/Write, com o payload do hook em JSON no stdin.
Escrito em Python (nao .ps1/.sh) porque Python ja e requisito do projeto e o mesmo
arquivo serve Windows e CI.

Sai SEMPRE com codigo 0: formatacao nunca deve travar o fluxo de trabalho. Quem barra
erro real e o hook de Stop (verify_on_stop.py) e o `.\\verify.ps1`.
"""

import json
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]


def _python():
    """Prefere o venv do projeto: garante a MESMA versao de ruff que o gate usa."""
    venv = PROJ / "venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


def _ler_payload():
    """Le o JSON do stdin tolerando BOM (utf-8-sig): no Windows e comum o
    redirecionamento injetar BOM, e `json.load` estoura nele."""
    bruto = sys.stdin.buffer.read()
    if not bruto:
        return {}
    return json.loads(bruto.decode("utf-8-sig"))


def main():
    try:
        payload = _ler_payload()
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return

    caminho = (payload.get("tool_input") or {}).get("file_path")
    if not caminho:
        return

    arquivo = Path(caminho)
    if arquivo.suffix != ".py" or not arquivo.exists():
        return

    # Fora do repo (ex.: script em scratchpad) nao e problema nosso.
    try:
        arquivo.relative_to(PROJ)
    except ValueError:
        return

    py = _python()
    for args in (["format", str(arquivo)], ["check", "--fix", str(arquivo)]):
        try:
            subprocess.run([py, "-m", "ruff", *args], cwd=PROJ, capture_output=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            # ruff ausente ou lento: segue o jogo, o gate pega depois.
            return


if __name__ == "__main__":
    main()
    sys.exit(0)
