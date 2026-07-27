"""v5.8.0 — Fonte do `MRO.exe`: sobe o Streamlit do runtime embutido e abre o navegador.

Este arquivo e congelado pelo PyInstaller (`scripts/portatil.py`, etapa 6). O ponto
central e o que ele NAO faz: **nao importa Streamlit, pandas nem nada do app**. So stdlib.
E isso que torna o freeze estavel — o PyInstaller congela ~100 linhas triviais, nao o grafo
de dependencias do Streamlit/pyarrow, que e onde `--onefile` do app inteiro sempre quebrou
(`docs/PLANO_V5_EVOLUCAO.md`: "PyInstaller do app inteiro (fragil a cada release — no maximo
no launcher)"). Consequencia pratica: **o exe nao precisa ser refeito a cada release**; so o
conteudo de `app\\` muda.

Layout esperado ao lado do exe (o mesmo `C:\\MRO\\` de sempre):

    MRO.exe          <- este script congelado
    runtime\\         Python embeddable + dependencias
    app\\             codigo do sistema
    dados\\           mro.db + backups\\   (criado aqui se faltar)

Em desenvolvimento roda direto, sem congelar:  `python deploy/launcher.py`
(usa o `venv` do projeto e a raiz do repositorio).

⚠️ **Tudo que este arquivo IMPRIME tem que ser ASCII.** A janela do MRO.exe e um console
Windows na codepage do sistema (cp850/cp1252), nao UTF-8: um em-dash num `print` sai como
`?` na tela do usuario. Docstrings e comentarios podem ter acento — eles nao vao para o
console. `test_saida_do_console_e_ascii` trava isso.

`tests/test_v580_portatil.py` falha se algum import fora da stdlib aparecer aqui, ou se a
porta/flags divergirem de `deploy/iniciar_mro.bat`.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PORTA = 8501
TIMEOUT_BOOT = 90  # 1o boot roda criar_banco() + _migrar() + snapshot diario


def raiz() -> Path:
    """Pasta que contem `runtime\\`, `app\\` e `dados\\`.

    Congelado: a pasta do proprio MRO.exe. Em dev: a raiz do repositorio, onde `app.py`
    mora ao lado de `deploy/`.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def python_do_runtime(base: Path) -> Path:
    """`runtime\\python.exe` quando congelado; o interpretador atual em dev."""
    embutido = base / "runtime" / "python.exe"
    return embutido if embutido.exists() else Path(sys.executable)


def app_py(base: Path) -> Path:
    """`app\\app.py` no pacote portatil; `app.py` na raiz em dev."""
    empacotado = base / "app" / "app.py"
    return empacotado if empacotado.exists() else base / "app.py"


def em_pasta_sincronizada(base: Path) -> bool:
    """OneDrive/Dropbox/Google Drive seguram lock em `mro.db`/`-wal` e corrompem SQLite.

    Aviso, nao bloqueio: quem insistir que insista sabendo. Mesmo criterio do
    `docs/INSTALACAO_SERVIDOR.md`.
    """
    partes = {p.lower() for p in base.parts}
    if partes & {"onedrive", "dropbox", "google drive", "gdrive"}:
        return True
    return any(p.lower().startswith("onedrive") for p in base.parts)


def ip_da_rede() -> str | None:
    """IP de LAN para os outros usuarios (`http://<ip>:8501`), ou None se so houver loopback."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("10.255.255.255", 1))  # nao envia pacote; so resolve a rota de saida
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def porta_em_uso(porta: int) -> bool:
    """Alguem ja esta escutando nesta porta?"""
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=1):
            return True
    except OSError:
        return False


def esperar_porta(porta: int, limite: int, proc: subprocess.Popen | None = None) -> bool:
    """Poll ate a porta aceitar conexao. True se subiu dentro do limite.

    Desiste na hora se o filho morrer: sem isso, um Streamlit que aborta na largada faria
    o launcher esperar os 90s inteiros antes de dizer qualquer coisa.
    """
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if proc is not None and proc.poll() is not None:
            return False
        if porta_em_uso(porta):
            return True
        time.sleep(0.5)
    return False


def comando(base: Path) -> list[str]:
    """Mesmas flags de `deploy/iniciar_mro.bat` — os dois caminhos de subida convergem.

    Forma de lista, sem shell: caminho com espaco ou acento nao quebra.

    `-s` = nao usar o site-packages do USUARIO. Sem ele, o Python embeddable com `import
    site` habilitado enxerga `%APPDATA%\\Python\\PythonXY\\site-packages` da maquina e o
    pacote deixa de ser auto-contido: na maquina do dev funciona (tem tudo instalado
    global) e na maquina limpa quebra. Medido: sem `-s` aquele caminho entra no sys.path.
    """
    return [
        str(python_do_runtime(base)),
        "-s",
        "-m",
        "streamlit",
        "run",
        str(app_py(base)),
        "--server.headless=true",
        "--server.address=0.0.0.0",
        f"--server.port={PORTA}",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]


def ambiente(base: Path) -> dict[str, str]:
    """`MRO_DB_PATH` e `PYTHONPATH` iguais aos de `iniciar_mro.bat:16-17`.

    Sem `MRO_DB_PATH` o banco nasceria ao lado de `database.py`, isto e, DENTRO de `app\\` —
    a pasta que `atualizar_mro.bat` substitui inteira a cada release.

    Sobre o `PYTHONPATH`: o Python **embeddable IGNORA** essa variavel, porque a presenca
    do `python*._pth` ao lado do python.exe substitui a busca padrao de caminhos (medido).
    Quem coloca `Lib\\site-packages` no sys.path e a linha correspondente do `._pth`, que
    `scripts/portatil.py` grava. Fica aqui porque continua valendo se algum dia o runtime
    for um CPython normal em vez do embeddable — nao e a via principal.
    `MRO_DB_PATH` nao sofre disso: e variavel comum, lida por `os.environ` em database.py.
    """
    env = os.environ.copy()
    site_packages = base / "runtime" / "Lib" / "site-packages"
    if site_packages.is_dir():
        env["MRO_DB_PATH"] = str(base / "dados" / "mro.db")
        env["PYTHONPATH"] = str(site_packages)
    return env


def segurar_janela(mensagem: str = "Pressione Enter para fechar...") -> None:
    """Impede a janela de sumir com o erro dentro dela.

    `input()` levanta EOFError quando nao ha console de verdade (exe chamado por script,
    stdin redirecionado) — ai nao ha janela para segurar e o certo e so seguir.
    """
    try:
        input(mensagem)
    except (EOFError, OSError):
        pass


def main() -> int:
    base = raiz()
    print(f"Sistema MRO - iniciando de {base}")

    alvo = app_py(base)
    if not alvo.exists():
        print(f"ERRO: nao encontrei {alvo}. O MRO.exe precisa ficar ao lado da pasta app\\.")
        segurar_janela()
        return 1

    if em_pasta_sincronizada(base):
        print()
        print("!! AVISO: esta pasta parece estar dentro de OneDrive/Dropbox/Google Drive.")
        print("!! O sincronizador segura lock no mro.db e PODE CORROMPER o banco.")
        print("!! Mova o sistema para um caminho local, por exemplo C:\\MRO.")
        print()

    url = f"http://localhost:{PORTA}"

    # Num app de duplo clique a pessoa clica duas vezes. Sem esta guarda o segundo
    # processo subiria um Streamlit que morre sem conseguir o bind, mas o poll encontraria
    # a porta ocupada pela PRIMEIRA instancia e anunciaria "MRO no ar" — sucesso falso.
    if porta_em_uso(PORTA):
        print()
        print(f"O MRO ja esta rodando nesta maquina (porta {PORTA} em uso).")
        print(f"Abrindo o navegador na instancia existente: {url}")
        print("Para reiniciar, feche a outra janela do MRO primeiro.")
        webbrowser.open(url)
        segurar_janela()
        return 0

    (base / "dados").mkdir(parents=True, exist_ok=True)

    # Filho no MESMO console do pai (sem CREATE_NEW_CONSOLE): fechar a janela dispara
    # CTRL_CLOSE_EVENT para o grupo inteiro e o Streamlit morre junto. Sem isso sobra
    # python.exe orfao segurando a porta 8501 e o banco.
    proc = subprocess.Popen(comando(base), cwd=str(base), env=ambiente(base))

    try:
        print(f"Aguardando o servidor subir (ate {TIMEOUT_BOOT}s no primeiro boot)...")
        if esperar_porta(PORTA, TIMEOUT_BOOT, proc):
            ip = ip_da_rede()
            print()
            print(f"  MRO no ar: {url}")
            if ip:
                print(f"  Na rede:   http://{ip}:{PORTA}   (para os outros usuarios)")
            print()
            print("  FECHE ESTA JANELA para parar o sistema.")
            print()
            webbrowser.open(url)
            return proc.wait()

        # Fracasso. A janela NAO pode sumir: sem a mensagem na tela o usuario nao tem o
        # que reportar, e um exe que abre e fecha num piscar e indepuravel.
        print()
        if proc.poll() is not None:
            print(f"ERRO: o servidor encerrou sozinho (codigo de saida {proc.returncode}).")
            print("A causa esta nas mensagens acima - em geral uma dependencia faltando")
            print("no runtime\\ ou um erro do proprio app.")
        else:
            print(f"ERRO: o servidor nao respondeu na porta {PORTA} em {TIMEOUT_BOOT}s.")
            print("Veja as mensagens acima.")
        segurar_janela()
        return proc.returncode or 1
    except KeyboardInterrupt:
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
