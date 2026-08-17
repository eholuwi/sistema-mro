"""Monta o pacote PORTATIL do Sistema MRO — extrair, arrastar o atalho e clicar (v6.8.2).

    python scripts/portatil.py            # -> dist/mro-portatil-<versao>.zip

Diferenca para `scripts/release.py`: o zip de release leva so o codigo e pressupoe um
`C:\\MRO\\runtime\\` ja montado a mao (7 passos em `docs/INSTALACAO_SERVIDOR.md`: baixar o
embeddable, editar o `._pth`, get-pip, pip --target...). Este leva **tudo pronto** —
Python embeddable com as dependencias ja instaladas — para que trocar o PC-servidor seja
extrair um zip.

    C:\\MRO\\
    ├── MRO.lnk                  atalho p/ iniciar_mro.bat (so arrastar p/ Desktop)
    ├── mro.ico                  icone do atalho
    ├── runtime\\                Python embeddable + deps
    ├── app\\                    identico ao payload de release.py
    ├── dados\\                  vazio; o banco nasce no primeiro boot
    ├── iniciar_mro.bat · atualizar_mro.bat · instalar_servidor.ps1 · criar_atalho.ps1
    └── LEIA-ME.txt

**Nao ha MRO.exe desde a v6.8.2.** Quem sobe o sistema e `iniciar_mro.bat`; o exe
congelado so existia para dar icone clicavel, e um binario PyInstaller sem assinatura e o
gatilho classico de EDR corporativo (na maquina real foi o que a quarentena pegou). No
lugar dele o build gera `MRO.lnk` apontando para o bat, com o `mro.ico` da propria raiz —
menos superficie, mesmo resultado. `deploy/criar_atalho.ps1` recria o atalho na area de
trabalho se o pacote foi extraido em outro caminho.

**O conteudo de `app\\` vem de `release.itens_do_pacote()`, nao de uma segunda lista.**
Duas listas de arquivos divergem — e a que ninguem roda diverge calada. Assim o
`tests/test_v550_release.py` (que falha se um modulo de runtime ficar de fora) protege os
dois formatos, e `tests/test_v580_portatil.py` trava o reuso.

O build precisa de Windows + internet na primeira vez (baixa o embeddable, cacheado em
`build/cache/`). A CI e ubuntu-latest e NAO roda isto — os testes exercitam so o manifesto.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import release  # noqa: E402  (mesmo padrao de tests/test_v550_release.py)

CACHE = RAIZ / "build" / "cache"
MONTAGEM = RAIZ / "build" / "portatil"

# Arquivos da raiz do pacote (fora de `app\`), copiados de deploy/.
RAIZ_DO_PACOTE = [
    "iniciar_mro.bat",
    "atualizar_mro.bat",
    "instalar_servidor.ps1",
    "criar_atalho.ps1",
    "mro.ico",
]

# Caminho que o MRO.lnk do zip aponta. O LEIA-ME manda extrair em C:\MRO; quem extrair
# em outro lugar roda `criar_atalho.ps1`, que resolve a raiz pelo proprio local.
PASTA_ALVO = Path("C:/MRO")

URL_EMBED = "https://www.python.org/ftp/python/{versao}/python-{versao}-embed-amd64.zip"
URL_GETPIP = "https://bootstrap.pypa.io/get-pip.py"

# ASCII puro de proposito: o usuario abre isto no Notepad, que em Windows 10 nao detecta
# UTF-8 sem BOM de forma confiavel — um em-dash aqui virava "â€"" na tela dele.
# `gravar_leia_me` re-encoda em ASCII e falha o build se alguem colar um acento.
LEIA_ME = """Sistema MRO {versao} - pacote portatil
=========================================

1. Extraia esta pasta em C:\\MRO  (ou outro caminho LOCAL e curto).

   NAO extraia dentro do OneDrive / Dropbox / Google Drive. O sincronizador
   segura lock no banco e pode corrompe-lo.

2. Arrume o atalho na area de trabalho:
   - Copie o arquivo MRO.lnk (desta pasta) para a area de trabalho; ou
   - Clique com o botao direito em criar_atalho.ps1 > "Executar com o
     PowerShell" (cria o atalho MRO sozinho - util se extraiu em outro lugar).

3. De dois cliques no atalho MRO.

   O navegador abre sozinho. Os outros usuarios acessam pelo endereco de rede
   que aparece na janela preta (http://<ip>:8501).

   Feche a janela preta para parar o sistema.

4. (Opcional) Para o sistema subir sozinho quando o PC liga, clique com o botao
   direito em instalar_servidor.ps1 > "Executar com o PowerShell". Ele cria a
   tarefa agendada e libera a porta 8501 no firewall. Pede admin.

O banco fica em dados\\mro.db e os backups em dados\\backups\\ - essa pasta
sobrevive as atualizacoes. Backup sob demanda: aba Configuracoes no sistema.

Atualizar: feche o atalho MRO (ou pare a tarefa) e rode
  atualizar_mro.bat C:\\caminho\\mro-<nova-versao>.zip
"""


# ── Runtime embeddable ────────────────────────────────────────────────────────


def versao_python() -> str:
    """Minor validada no CI (`.github/workflows/verify.yml`) + o patch do interpretador atual.

    Fonte unica pelo mesmo motivo que `release.versao_do_codigo()` le `ui/sidebar.py`: a
    minor tem que bater com a que a suite valida, porque `requirements.txt` esta com
    versoes fixadas e nem toda wheel existe para toda minor.
    """
    texto = (RAIZ / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    m = re.search(r'python-version:\s*["\']?(\d+\.\d+)', texto)
    if not m:
        raise SystemExit("Nao consegui ler python-version de .github/workflows/verify.yml")
    minor = m.group(1)

    atual = f"{sys.version_info.major}.{sys.version_info.minor}"
    if atual != minor:
        raise SystemExit(
            f"O CI valida Python {minor} mas este interpretador e {atual}. Rode o build com "
            f"o mesmo minor, senao o pip resolve wheels que a suite nunca viu."
        )
    return f"{minor}.{sys.version_info.micro}"


def baixar(url: str, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        print(f"  (cache) {destino.name}")
        return destino
    print(f"  baixando {url}")
    with urllib.request.urlopen(url) as r, open(destino, "wb") as f:
        shutil.copyfileobj(r, f)
    return destino


def montar_runtime(destino: Path) -> None:
    """Extrai o embeddable e habilita `site` — o passo manual do INSTALACAO_SERVIDOR.md §1."""
    versao = versao_python()
    zip_embed = baixar(URL_EMBED.format(versao=versao), CACHE / f"python-{versao}-embed-amd64.zip")

    destino.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_embed) as zf:
        zf.extractall(destino)

    # O embeddable vem com imports isolados: descomentar `import site` e acrescentar
    # `Lib\site-packages`, senao o pip --target instala num lugar que ninguem importa.
    pths = list(destino.glob("python*._pth"))
    if not pths:
        raise SystemExit(f"python*._pth nao encontrado em {destino}")
    pth = pths[0]
    linhas = pth.read_text(encoding="utf-8").splitlines()
    linhas = [ln[1:] if ln.strip() == "#import site" else ln for ln in linhas]
    if "Lib\\site-packages" not in linhas:
        linhas.append("Lib\\site-packages")
    pth.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"  runtime: Python {versao} + site habilitado")


def instalar_deps(runtime: Path) -> None:
    """`pip install --target` com os pins do requirements.txt. E o passo lento do build."""
    py = runtime / "python.exe"
    get_pip = baixar(URL_GETPIP, CACHE / "get-pip.py")

    print("  instalando pip no runtime...")
    subprocess.run([str(py), str(get_pip), "--no-warn-script-location"], check=True, cwd=str(runtime))

    print("  instalando dependencias (demora alguns minutos)...")
    subprocess.run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--target",
            str(runtime / "Lib" / "site-packages"),
            "--no-warn-script-location",
            "-r",
            str(RAIZ / "requirements.txt"),
        ],
        check=True,
    )


# ── Aplicacao e atalho ────────────────────────────────────────────────────────


def montar_app(destino: Path) -> int:
    """Copia o payload de release para `app\\`. Uma lista so, a do release.py."""
    itens = release.itens_do_pacote()
    for origem, nome in itens:
        alvo = destino / nome
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, alvo)
    return len(itens)


def criar_atalho_lnk(raiz_instalacao: Path, destino: Path) -> Path:
    """Gera `MRO.lnk` apontando para `raiz_instalacao\\iniciar_mro.bat`.

    Substitui o MRO.exe da v5.8.0 (v6.8.2): binario PyInstaller sem assinatura e o
    gatilho classico de EDR corporativo, e quem sobe o sistema de verdade sempre foi o
    bat. O atalho ja vai pronto no zip — na maquina destino e so arrastar para a area
    de trabalho.

    Aponta para PASTA_ALVO (C:\\MRO), o caminho fixo que o LEIA-ME manda extrair.
    Quem extrair em outro lugar roda `criar_atalho.ps1`, que resolve a raiz pelo
    proprio local.

    Caminhos vao por variaveis de ambiente, nao interpolados no -Command: o caminho do
    build tem espaco e acento, e embutir isso no texto quebra. Ambiente no Windows e
    UTF-16 — o acento sobrevive sem problema.
    """
    atalho = destino / "MRO.lnk"
    env = os.environ.copy()
    env["MRO_ATALHO"] = str(atalho)
    env["MRO_BAT"] = str(raiz_instalacao / "iniciar_mro.bat")
    env["MRO_RAIZ"] = str(raiz_instalacao)
    env["MRO_ICO"] = str(raiz_instalacao / "mro.ico")
    cmd = (
        "$w = New-Object -ComObject WScript.Shell; "
        "$s = $w.CreateShortcut($env:MRO_ATALHO); "
        "$s.TargetPath = $env:MRO_BAT; "
        "$s.WorkingDirectory = $env:MRO_RAIZ; "
        "$s.IconLocation = $env:MRO_ICO + ',0'; "
        "$s.Description = 'Sistema MRO'; "
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=True, env=env)
    return atalho


# ── Orquestracao ──────────────────────────────────────────────────────────────


def gravar_leia_me(destino: Path, versao: str) -> None:
    """Grava o LEIA-ME em ASCII: o usuario abre no Notepad, que no Windows 10 nao detecta
    UTF-8 sem BOM de forma confiavel. `encode("ascii")` falha o build se entrar acento."""
    texto = LEIA_ME.format(versao=versao)
    destino.write_bytes(texto.encode("ascii").replace(b"\n", b"\r\n"))


def zipar(origem: Path, alvo: Path) -> Path:
    alvo.parent.mkdir(parents=True, exist_ok=True)
    if alvo.exists():
        alvo.unlink()
    with zipfile.ZipFile(alvo, "w", zipfile.ZIP_DEFLATED) as zf:
        for caminho in sorted(origem.rglob("*")):
            rel = str(caminho.relative_to(origem)).replace("\\", "/")
            if caminho.is_file():
                zf.write(caminho, rel)
            elif not any(caminho.iterdir()):
                # Pasta vazia (`dados\`): sem uma entrada de diretorio explicita ela
                # simplesmente nao existe no zip extraido. O iniciar_mro.bat a recria,
                # mas o layout tem que estar visivel para quem abre o pacote.
                zf.writestr(rel + "/", "")
    return alvo


def main() -> int:
    p = argparse.ArgumentParser(description="Monta o pacote portatil do Sistema MRO.")
    p.add_argument("--versao", help="sobrescreve a versao lida de ui/sidebar.py")
    p.add_argument("--saida", default=str(RAIZ / "dist"), help="pasta do zip (padrao: dist/)")
    p.add_argument(
        "--pular-deps",
        action="store_true",
        help="reaproveita o runtime\\ ja montado (o pip e o passo lento)",
    )
    args = p.parse_args()

    if os.name != "nt":
        raise SystemExit("O pacote portatil e para Windows — rode o build numa maquina Windows.")

    versao = args.versao or release.versao_do_codigo()
    runtime = MONTAGEM / "runtime"

    print(f"Sistema MRO {versao} — pacote portatil")

    print("[1/5] Runtime...")
    if args.pular_deps and runtime.is_dir():
        print("  (reaproveitando runtime\\ existente)")
    else:
        if runtime.exists():
            shutil.rmtree(runtime)
        montar_runtime(runtime)
        instalar_deps(runtime)

    print("[2/5] Aplicacao...")
    app = MONTAGEM / "app"
    if app.exists():
        shutil.rmtree(app)
    n = montar_app(app)
    print(f"  {n} arquivos em app\\ (mesmo payload de release.py)")

    print("[3/5] Raiz do pacote...")
    for nome in RAIZ_DO_PACOTE:
        origem = RAIZ / "deploy" / nome
        if not origem.exists():
            raise SystemExit(f"deploy/{nome} ausente")
        shutil.copy2(origem, MONTAGEM / nome)
    (MONTAGEM / "dados").mkdir(exist_ok=True)
    gravar_leia_me(MONTAGEM / "LEIA-ME.txt", versao)

    print("[4/5] Atalho MRO...")
    criar_atalho_lnk(PASTA_ALVO, MONTAGEM)

    print("[5/5] Compactando...")
    destino = zipar(MONTAGEM, Path(args.saida) / f"mro-portatil-{versao}.zip")

    mb = destino.stat().st_size / (1024 * 1024)
    print()
    print(f"Pacote gerado: {destino}  ({mb:.0f} MB)")
    print()
    print("Na maquina destino: extrair em C:\\MRO, arrastar MRO.lnk para a area")
    print("de trabalho e dar dois cliques nele.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
