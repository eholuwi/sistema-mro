"""v5.8.0 — Pacote portatil: launcher, empacotador e os contratos entre os .bat/.ps1.

O build de verdade NAO roda aqui: precisa de Windows, internet e ~700 MB, e a CI e
ubuntu-latest. O que da para travar sem construir nada e o que de fato quebra calado:

1. **O launcher so pode importar stdlib.** E isso que mantem o freeze trivial e estavel
   entre releases. No dia em que alguem importar `streamlit` ou `database` aqui, o
   PyInstaller passa a arrastar o grafo inteiro e volta a fragilidade que a v5.5.0
   evitou de proposito (`docs/PLANO_V5_EVOLUCAO.md`: "no maximo no launcher").
2. **Uma unica lista de arquivos do app.** `portatil.py` reusa `release.itens_do_pacote()`;
   se alguem duplicar a lista, o portatil sai sem um modulo que o zip de release tem.
3. **O nome da tarefa agendada e um contrato entre tres arquivos.** `instalar_servidor.ps1`
   cria, `atualizar_mro.bat` para e religa. Divergir quebra a atualizacao em silencio.
"""

import ast
import re
import socket
import sys
import time
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts"))
sys.path.insert(0, str(PROJ / "deploy"))

release = pytest.importorskip("release")
launcher = pytest.importorskip("launcher")

LAUNCHER = PROJ / "deploy" / "launcher.py"
INICIAR = PROJ / "deploy" / "iniciar_mro.bat"
ATUALIZAR = PROJ / "deploy" / "atualizar_mro.bat"
INSTALAR = PROJ / "deploy" / "instalar_servidor.ps1"


# ── O launcher ────────────────────────────────────────────────────────────────


def test_launcher_existe_e_compila():
    assert LAUNCHER.exists(), "deploy/launcher.py ausente — e a fonte do MRO.exe"
    ast.parse(LAUNCHER.read_text(encoding="utf-8"))


def test_launcher_so_importa_stdlib():
    """A guarda central do CP2: qualquer import fora da stdlib torna o freeze fragil."""
    arvore = ast.parse(LAUNCHER.read_text(encoding="utf-8"))

    modulos = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            modulos |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            modulos.add(no.module.split(".")[0])

    externos = modulos - sys.stdlib_module_names - {"__future__"}
    assert not externos, (
        f"deploy/launcher.py so pode importar stdlib (o PyInstaller congela ele): {sorted(externos)}"
    )


def test_saida_do_console_e_ascii():
    """A janela do MRO.exe e um console Windows na codepage do sistema, nao UTF-8.

    Medido no CP4: `print(f"Sistema MRO — iniciando...")` saia como `Sistema MRO ? iniciando`
    na tela. Docstrings e comentarios podem ter acento — so o que vai para o console nao pode.
    """
    arvore = ast.parse(LAUNCHER.read_text(encoding="utf-8"))

    ruins = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id in ("print", "input"):
            for parte in ast.walk(no):
                if isinstance(parte, ast.Constant) and isinstance(parte.value, str):
                    if not parte.value.isascii():
                        ruins.append(f"linha {parte.lineno}: {parte.value!r}")

    assert not ruins, "saida de console tem que ser ASCII (codepage do Windows):\n" + "\n".join(ruins)


def test_launcher_nao_toca_no_app():
    """Nem por import indireto: nada de `database`, `services` ou `ui` aqui dentro."""
    arvore = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    modulos = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            modulos |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            modulos.add(no.module.split(".")[0])

    assert not (modulos & {"database", "services", "ui", "streamlit", "pandas"})


def test_launcher_e_o_bat_sobem_na_mesma_porta_e_flags():
    """Os dois caminhos de subida (MRO.exe e tarefa agendada) tem que convergir.

    Divergir daria um sistema que se comporta diferente conforme quem o iniciou — e o
    sintoma apareceria so no servidor.
    """
    argv = launcher.comando(Path("C:/MRO"))
    bat = INICIAR.read_text(encoding="utf-8", errors="ignore")

    assert launcher.PORTA == 8501
    for flag in (
        "--server.headless=true",
        "--server.address=0.0.0.0",
        "--server.port=8501",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ):
        assert flag in argv, f"{flag} faltando no launcher"
        assert flag.split("=")[0] in bat, f"{flag} faltando em iniciar_mro.bat"


def test_sobe_sem_o_site_packages_do_usuario():
    """`-s` nos DOIS caminhos de subida.

    Medido no CP3: o embeddable com `import site` habilitado coloca
    `%APPDATA%\\Python\\PythonXY\\site-packages` no sys.path. Sem `-s`, o pacote portatil
    deixa de ser auto-contido — funciona na maquina do dev (que tem tudo instalado global)
    e quebra na maquina limpa, que e exatamente o cenario que o pacote existe para atender.
    """
    argv = launcher.comando(Path("C:/MRO"))
    assert "-s" in argv, "launcher precisa de -s (ignorar site-packages do usuario)"
    assert argv.index("-s") < argv.index("-m"), "-s tem que vir antes de -m"

    bat = INICIAR.read_text(encoding="utf-8", errors="ignore")
    assert "-s -m streamlit" in bat, "iniciar_mro.bat precisa de -s antes de -m streamlit"


def test_esperar_porta_desiste_quando_o_filho_morre():
    """Sem isto, um Streamlit que aborta na largada faria o launcher esperar os 90s
    inteiros antes de dizer qualquer coisa — e o usuario olhando uma janela parada."""

    class FilhoMorto:
        returncode = 1

        def poll(self):
            return 1

    inicio = time.monotonic()
    assert launcher.esperar_porta(1, 30, FilhoMorto()) is False
    assert time.monotonic() - inicio < 3, "deveria desistir na hora, nao esperar o limite"


def test_porta_em_uso_detecta_instancia_ja_rodando(monkeypatch):
    """Num app de duplo clique a pessoa clica duas vezes. Sem esta deteccao o segundo
    processo anunciava "MRO no ar" apontando para a instancia do PRIMEIRO, enquanto o
    proprio filho morria sem conseguir o bind."""
    fonte = LAUNCHER.read_text(encoding="utf-8")

    # A guarda tem que vir ANTES do Popen, senao o segundo Streamlit ainda e disparado.
    assert fonte.index("if porta_em_uso(PORTA):") < fonte.index("subprocess.Popen(")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        porta = srv.getsockname()[1]
        assert launcher.porta_em_uso(porta) is True

    assert launcher.porta_em_uso(porta) is False


def test_leia_me_e_ascii_puro():
    """O usuario abre o LEIA-ME no Notepad, que no Windows 10 nao detecta UTF-8 sem BOM de
    forma confiavel: um em-dash saia como "â€"" na tela dele (aconteceu no CP3)."""
    portatil = pytest.importorskip("portatil")

    texto = portatil.LEIA_ME.format(versao="9.9.9")
    texto.encode("ascii")  # levanta UnicodeEncodeError se alguem colar acento


def test_launcher_define_o_db_fora_da_pasta_app():
    """`MRO_DB_PATH` -> dados\\mro.db. Sem isso o banco nasceria dentro de app\\, que o
    `atualizar_mro.bat` substitui inteira a cada release."""
    fonte = LAUNCHER.read_text(encoding="utf-8")
    assert "MRO_DB_PATH" in fonte
    assert 'base / "dados" / "mro.db"' in fonte

    # Em dev (sem runtime\ embutido ao lado) nao pode sequestrar o banco do desenvolvedor:
    # so define MRO_DB_PATH quando o layout do pacote portatil esta de fato presente.
    assert launcher.ambiente(Path("C:/MRO")).get("MRO_DB_PATH") is None


def test_launcher_avisa_sobre_pasta_sincronizada():
    assert launcher.em_pasta_sincronizada(Path(r"C:\Users\x\OneDrive\Documentos\MRO"))
    assert launcher.em_pasta_sincronizada(Path(r"C:\Users\x\Dropbox\MRO"))
    assert not launcher.em_pasta_sincronizada(Path(r"C:\MRO"))


# ── O empacotador ─────────────────────────────────────────────────────────────


def test_portatil_reusa_a_lista_do_release():
    """UMA lista de arquivos do app, a do release.py — duas divergem, e a que ninguem
    roda diverge calada."""
    portatil = pytest.importorskip("portatil")

    fonte = (PROJ / "scripts" / "portatil.py").read_text(encoding="utf-8")
    assert "release.itens_do_pacote()" in fonte, "portatil.py precisa reusar release.itens_do_pacote()"
    assert portatil.release is release


def test_portatil_leva_o_essencial_para_a_raiz_do_pacote():
    portatil = pytest.importorskip("portatil")

    for nome in portatil.RAIZ_DO_PACOTE:
        assert (PROJ / "deploy" / nome).exists(), f"deploy/{nome} ausente"
    assert set(portatil.RAIZ_DO_PACOTE) >= {
        "iniciar_mro.bat",
        "atualizar_mro.bat",
        "instalar_servidor.ps1",
    }


def test_portatil_le_a_minor_do_python_do_ci():
    """O runtime embutido tem que ser o minor que a suite valida: `requirements.txt` esta
    com versoes fixadas e nem toda wheel existe para toda minor."""
    portatil = pytest.importorskip("portatil")

    ci = (PROJ / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    minor = re.search(r'python-version:\s*["\']?(\d+\.\d+)', ci).group(1)

    atual = f"{sys.version_info.major}.{sys.version_info.minor}"
    if atual != minor:
        pytest.skip(f"interpretador {atual} != minor do CI {minor}")
    assert portatil.versao_python().startswith(minor + ".")


def test_portatil_usa_icone_com_caminho_absoluto():
    """O PyInstaller resolve `--icon` relativo ao `--specpath`, nao ao cwd: com caminho
    relativo o build morre com FileNotFoundError. Ja aconteceu no CP2."""
    fonte = (PROJ / "scripts" / "portatil.py").read_text(encoding="utf-8")
    assert '(RAIZ / "deploy" / "mro.ico").resolve()' in fonte
    assert (PROJ / "deploy" / "mro.ico").exists(), "deploy/mro.ico ausente"


# ── Contratos entre os scripts de deploy ──────────────────────────────────────


def test_nome_da_tarefa_agendada_bate_nos_dois_scripts():
    """`instalar_servidor.ps1` cria e `atualizar_mro.bat` para/religa pelo nome EXATO."""
    ps = INSTALAR.read_text(encoding="utf-8", errors="ignore")
    bat = ATUALIZAR.read_text(encoding="utf-8", errors="ignore")

    assert "'Sistema MRO'" in ps
    assert 'set "TAREFA=Sistema MRO"' in bat


def test_firewall_nao_libera_o_perfil_public():
    """O MRO nao tem autenticacao — quem alcanca a porta usa o sistema."""
    ps = INSTALAR.read_text(encoding="utf-8", errors="ignore")

    m = re.search(r"-Profile\s+([A-Za-z,]+)", ps)
    assert m, "New-NetFirewallRule sem -Profile explicito"
    assert "Public" not in m.group(1)
    assert set(m.group(1).split(",")) == {"Domain", "Private"}


def test_instalar_servidor_resolve_a_raiz_pelo_proprio_local():
    """Nada de `C:\\MRO` fixo: o pacote portatil pode ser extraido em qualquer lugar."""
    ps = INSTALAR.read_text(encoding="utf-8", errors="ignore")

    assert "$PSScriptRoot" in ps
    assert "-Execute $BAT" in ps


def test_atualizar_aborta_se_nao_conseguir_mover_o_app():
    """Sem esta guarda o Expand-Archive -Force escrevia por cima do app\\ antigo e
    deixava duas versoes misturadas na mesma pasta, sem aviso."""
    bat = ATUALIZAR.read_text(encoding="utf-8", errors="ignore")

    guarda = bat.split("[3/5]", 1)[1].split("[4/5]", 1)[0]
    assert 'if exist "%MRO_RAIZ%app"' in guarda
    assert "exit /b 1" in guarda
    assert "ABORTADA" in guarda


def test_pyinstaller_esta_fixado_so_no_dev():
    """Congelar e passo de build: o runtime do servidor nao muda."""
    dev = (PROJ / "requirements-dev.txt").read_text(encoding="utf-8")
    prod = (PROJ / "requirements.txt").read_text(encoding="utf-8")

    assert re.search(r"^pyinstaller==\d+\.\d+", dev, re.M)
    assert "pyinstaller" not in prod.lower()
