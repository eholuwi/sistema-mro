"""Empacota uma release do Sistema MRO para o PC-servidor (v5.5.0 / F5).

Uso:
    python scripts/release.py                 # versao lida de ui/sidebar.py
    python scripts/release.py --versao 5.6.0
    python scripts/release.py --saida C:\\temp

Gera `dist/mro-<versao>.zip` cujo conteudo, extraido, vira o `C:\\MRO\\app\\` do
servidor (ver docs/INSTALACAO_SERVIDOR.md e deploy/atualizar_mro.bat).

INCLUSAO EXPLICITA, nao exclusao: um pacote de distribuicao que erra para o lado de
"levar demais" pode vazar `mro.db` (dado operacional) ou `vault/`. Se algo novo passar
a ser necessario em runtime, precisa ser adicionado aqui conscientemente — e o teste
`tests/test_v550_release.py` falha se um modulo de runtime ficar de fora.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# Arquivos soltos que o app precisa em runtime.
ARQUIVOS = ["app.py", "database.py", "inventus_logo.png"]

# Pacotes Python + assets. `.streamlit/` entra com a config de PRODUCAO (ver abaixo).
# NAO incluir `migrations/`: o schema e as migracoes vivem dentro de `database.py`
# (`criar_banco()` + `_migrar()`), aplicadas em runtime. Aquele diretorio so tinha um
# README descrevendo migracoes que nunca existiram — empacota-lo levava um arquivo
# morto para o servidor.
PASTAS = ["services", "ui"]

# v6.6.0 — o MOTOR da atualizacao pelo app viaja dentro do proprio pacote, para que a
# instalacao ganhe o mecanismo junto com o codigo que o dispara (sem ele, cada versao
# nova exigiria copiar um .bat a mao no PC-servidor — exatamente o trabalho manual que
# a v6.6.0 elimina). Em runtime ele e copiado de `app\deploy\` para
# `dados\atualizacoes\` antes de rodar: ver services/atualizacao.py:preparar_motor.
MOTOR_ATUALIZACAO = "deploy/aplicar_atualizacao.bat"

# Nunca empacotar, mesmo dentro das pastas acima.
IGNORAR = {"__pycache__", ".pytest_cache", ".ruff_cache"}
IGNORAR_SUFIXOS = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".db-journal"}


def versao_do_codigo() -> str:
    """Le a versao de `services/constants.py` (VERSAO = "6.0.0") — fonte unica.

    v6.0.0: era lida de `ui/sidebar.py`, que agora so re-exporta a constante. Le por
    REGEX, sem importar o modulo: o release roda com o Python do sistema, sem as
    dependencias do app instaladas.

    v6.6.0: a regex saiu daqui e passou a viver em `services/atualizacao.py`, que precisa
    da MESMA leitura para descobrir a versao DE DENTRO de um zip. Duas copias derivariam.
    O import so e seguro porque aquele modulo e stdlib-only por contrato (testado)."""
    from services.atualizacao import ler_versao

    texto = (RAIZ / "services" / "constants.py").read_text(encoding="utf-8")
    versao = ler_versao(texto)
    if not versao:
        raise SystemExit("Nao consegui ler VERSAO de services/constants.py")
    return versao


def _incluir(caminho: Path) -> bool:
    if any(parte in IGNORAR for parte in caminho.parts):
        return False
    return caminho.suffix not in IGNORAR_SUFIXOS


def itens_do_pacote() -> list[tuple[Path, str]]:
    """Devolve [(caminho_absoluto, nome_dentro_do_zip)] do pacote."""
    itens: list[tuple[Path, str]] = []

    for nome in ARQUIVOS:
        origem = RAIZ / nome
        if not origem.exists():
            raise SystemExit(f"Arquivo obrigatorio ausente: {nome}")
        itens.append((origem, nome))

    for pasta in PASTAS:
        base = RAIZ / pasta
        if not base.is_dir():
            raise SystemExit(f"Pasta obrigatoria ausente: {pasta}")
        for caminho in sorted(base.rglob("*")):
            if caminho.is_file() and _incluir(caminho):
                itens.append((caminho, str(caminho.relative_to(RAIZ)).replace("\\", "/")))

    # A config de producao entra como `.streamlit/config.toml` — headless, 0.0.0.0:8501.
    # A `.streamlit/config.toml` do repo e so tema (dev) e NAO vai para o servidor.
    prod = RAIZ / "deploy" / "config-servidor.toml"
    if not prod.exists():
        raise SystemExit("deploy/config-servidor.toml ausente")
    itens.append((prod, ".streamlit/config.toml"))

    # O motor da atualizacao pelo app (v6.6.0). Mesmo nome dentro do zip, para aterrissar
    # em `C:\MRO\app\deploy\aplicar_atualizacao.bat`.
    motor = RAIZ / MOTOR_ATUALIZACAO
    if not motor.exists():
        raise SystemExit(f"{MOTOR_ATUALIZACAO} ausente")
    itens.append((motor, MOTOR_ATUALIZACAO))

    return itens


def empacotar(versao: str, saida: Path) -> Path:
    saida.mkdir(parents=True, exist_ok=True)
    destino = saida / f"mro-{versao}.zip"
    if destino.exists():
        destino.unlink()

    itens = itens_do_pacote()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        for origem, nome in itens:
            zf.write(origem, nome)

    return destino


def main() -> int:
    p = argparse.ArgumentParser(description="Empacota uma release do Sistema MRO.")
    p.add_argument("--versao", help="sobrescreve a versao lida de ui/sidebar.py")
    p.add_argument("--saida", default=str(RAIZ / "dist"), help="pasta do zip (padrao: dist/)")
    args = p.parse_args()

    versao = args.versao or versao_do_codigo()
    destino = empacotar(versao, Path(args.saida))

    tamanho = destino.stat().st_size / 1024
    print(f"Pacote gerado: {destino}  ({tamanho:.0f} KB)")
    print(f"Arquivos: {len(itens_do_pacote())}")
    print()
    print("No servidor:")
    print(f"  atualizar_mro.bat {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
