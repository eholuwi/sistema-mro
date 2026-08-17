"""v5.8.0 — Pacote portatil: subida, empacotador e os contratos entre os .bat/.ps1.

O build de verdade NAO roda aqui: precisa de Windows, internet e ~700 MB, e a CI e
ubuntu-latest. O que da para travar sem construir nada e o que de fato quebra calado:

1. **O `iniciar_mro.bat` e o UNICO caminho de subida** (v6.8.2). Ele tem que carregar as
   flags do Streamlit, o `-s`, o `MRO_DB_PATH` fora de `app\\` e — desde que o MRO.exe
   saiu — a abertura do navegador e o aviso de pasta sincronizada, que eram do launcher.
2. **Uma unica lista de arquivos do app.** `portatil.py` reusa `release.itens_do_pacote()`;
   se alguem duplicar a lista, o portatil sai sem um modulo que o zip de release tem.
3. **O nome da tarefa agendada e um contrato entre tres arquivos.** `instalar_servidor.ps1`
   cria, `atualizar_mro.bat` para e religa. Divergir quebra a atualizacao em silencio.

⚠️ **v6.8.2 — o `deploy/launcher.py` deixou de existir**, junto com o PyInstaller e o
MRO.exe. Os contratos que os testes do launcher guardavam nao sumiram: eles migraram para
os testes do `.bat` abaixo, porque o comportamento migrou para la.
"""

import re
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts"))
sys.path.insert(0, str(PROJ / "deploy"))

release = pytest.importorskip("release")

INICIAR = PROJ / "deploy" / "iniciar_mro.bat"
ATUALIZAR = PROJ / "deploy" / "atualizar_mro.bat"
INSTALAR = PROJ / "deploy" / "instalar_servidor.ps1"
MOTOR = PROJ / "deploy" / "aplicar_atualizacao.bat"


def _texto(caminho):
    return caminho.read_text(encoding="utf-8", errors="ignore")


# ── A subida (iniciar_mro.bat) ────────────────────────────────────────────────


def test_o_bat_sobe_com_a_porta_e_as_flags_do_servidor():
    """As flags do servidor vivem em UM lugar so desde a v6.8.2 — antes o launcher tinha
    a sua copia e as duas podiam divergir, dando um sistema que se comporta diferente
    conforme quem o iniciou."""
    bat = _texto(INICIAR)
    for flag in (
        "--server.headless=true",
        "--server.address=0.0.0.0",
        "--server.port=8501",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ):
        assert flag in bat, f"{flag} faltando em iniciar_mro.bat"


def test_sobe_sem_o_site_packages_do_usuario():
    """`-s` no caminho de subida.

    Medido no CP3: o embeddable com `import site` habilitado coloca
    `%APPDATA%\\Python\\PythonXY\\site-packages` no sys.path. Sem `-s`, o pacote portatil
    deixa de ser auto-contido — funciona na maquina do dev (que tem tudo instalado global)
    e quebra na maquina limpa, que e exatamente o cenario que o pacote existe para atender.
    """
    assert "-s -m streamlit" in _texto(INICIAR), "iniciar_mro.bat precisa de -s antes de -m streamlit"


def test_o_bat_define_o_db_fora_da_pasta_app():
    """`MRO_DB_PATH` -> dados\\mro.db. Sem isso o banco nasceria dentro de app\\, que o
    `atualizar_mro.bat` substitui inteira a cada release."""
    bat = _texto(INICIAR)
    assert "MRO_DB_PATH" in bat
    assert r"dados\mro.db" in bat


def test_o_bat_abre_o_navegador_e_espera_a_porta():
    """v6.8.2 — quem abria o navegador era o MRO.exe (launcher.py); com ele fora, se o bat
    nao abrir NINGUEM abre, e o duplo clique no atalho vira so uma janela preta — enquanto
    o LEIA-ME continua prometendo que "o navegador abre sozinho".

    A espera pela porta e parte do contrato: abrir antes de o Streamlit atender mostra
    "nao foi possivel conectar" e a pessoa conclui que o sistema nao subiu.
    """
    bat = _texto(INICIAR)
    assert "--abrir-navegador" in bat, "o bat precisa do modo de abertura do navegador"
    assert 'start "" http://localhost:8501' in bat, "falta abrir a URL"
    assert "LISTENING" in bat, "tem que ESPERAR a porta aceitar conexao antes de abrir"


def test_a_espera_da_porta_nao_usa_timeout():
    """Mesma armadilha travada na v6.6.0 (`test_motor_nao_usa_timeout`): com stdin
    redirecionado o `timeout` do cmd aborta na hora, e o laco daria as voltas em
    milissegundos. Este bat e lancado por `start ""` a partir dos dois atualizadores —
    exatamente a condicao do problema. `ping` no loopback nao le stdin."""
    bat = _texto(INICIAR)
    assert "timeout /t" not in bat and "timeout /nobreak" not in bat, (
        "use `ping -n` para esperar; `timeout` aborta com stdin redirecionado"
    )
    assert "ping -n" in bat


def test_o_bat_avisa_sobre_pasta_sincronizada():
    """Era `launcher.em_pasta_sincronizada`. O sincronizador segura lock no `mro.db` e no
    `-wal`; dois processos escrevendo no mesmo arquivo corrompem o banco. Avisa e segue —
    o launcher tambem nao impedia."""
    bat = _texto(INICIAR)
    assert "findstr" in bat and "OneDrive" in bat and "Dropbox" in bat


def test_saida_do_console_e_ascii():
    """A janela preta e um console Windows na codepage do sistema, nao UTF-8.

    Medido no CP4: `Sistema MRO — iniciando...` saia como `Sistema MRO ? iniciando` na
    tela. Vale para os tres .bat de deploy, que so imprimem via `echo`.
    """
    ruins = []
    for arquivo in (INICIAR, ATUALIZAR, MOTOR):
        for n, linha in enumerate(_texto(arquivo).splitlines(), 1):
            if re.match(r"\s*(echo|call :log)\b", linha, re.IGNORECASE) and not linha.isascii():
                ruins.append(f"{arquivo.name}:{n}: {linha.strip()!r}")

    assert not ruins, "saida de console tem que ser ASCII (codepage do Windows):\n" + "\n".join(ruins)


def test_nenhum_bat_de_deploy_religa_pelo_exe():
    """v6.8.2 — o MRO.exe nao existe mais. Um `if exist MRO.exe` sobrevivente seria ramo
    morto nos dois atualizadores: eles cairiam no fallback so depois de testar um arquivo
    que nunca vai estar la, e a mensagem mandaria fechar uma janela que nao existe.

    Olha so o CODIGO: os comentarios continuam podendo citar o exe para explicar por que
    ele saiu — apagar a explicacao junto com o ramo e como o proximo leitor reintroduz o
    problema."""
    for arquivo in (INICIAR, ATUALIZAR, MOTOR, INSTALAR):
        codigo = [
            linha
            for linha in _texto(arquivo).splitlines()
            if not re.match(r"\s*(REM\b|::|#)", linha, re.IGNORECASE)
        ]
        assert "MRO.exe" not in "\n".join(codigo), f"{arquivo.name} ainda EXECUTA o MRO.exe"


def test_leia_me_e_ascii_puro():
    """O usuario abre o LEIA-ME no Notepad, que no Windows 10 nao detecta UTF-8 sem BOM de
    forma confiavel: um em-dash saia como "â€"" na tela dele (aconteceu no CP3)."""
    portatil = pytest.importorskip("portatil")

    texto = portatil.LEIA_ME.format(versao="9.9.9")
    texto.encode("ascii")  # levanta UnicodeEncodeError se alguem colar acento


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
        "criar_atalho.ps1",
        "mro.ico",
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


def test_portatil_nao_empacota_exe_e_sim_atalho():
    """v6.8.2 — sem PyInstaller: o pacote leva o atalho MRO.lnk + o mro.ico.

    O MRO.exe era um binario PyInstaller sem assinatura apontando para o bat — o
    gatilho classico de EDR corporativo, e foi o que a quarentena da maquina real pegou.
    Quem sobe o sistema sempre foi o iniciar_mro.bat; o atalho entrega o mesmo duplo
    clique com menos superficie.
    """
    portatil = pytest.importorskip("portatil")

    assert "mro.ico" in portatil.RAIZ_DO_PACOTE, "o icone tem que viajar no zip"
    assert "criar_atalho.ps1" in portatil.RAIZ_DO_PACOTE
    assert (PROJ / "deploy" / "mro.ico").exists(), "deploy/mro.ico ausente"

    fonte = (PROJ / "scripts" / "portatil.py").read_text(encoding="utf-8")
    assert '"PyInstaller"' not in fonte, "v6.8.2 tirou o PyInstaller do build"
    assert '"--icon"' not in fonte
    assert "construir_exe" not in fonte
    assert "MRO.lnk" in fonte, "o build precisa gerar o atalho"

    ps = (PROJ / "deploy" / "criar_atalho.ps1").read_text(encoding="ascii")
    assert "CreateShortcut" in ps
    assert "GetFolderPath('Desktop')" in ps, "atalho vai para a area de trabalho"
    assert "iniciar_mro.bat" in ps
    assert "mro.ico" in ps


def test_leia_me_ensina_o_atalho_em_vez_do_exe():
    portatil = pytest.importorskip("portatil")

    texto = portatil.LEIA_ME.format(versao="9.9.9")
    assert "MRO.lnk" in texto
    assert "criar_atalho.ps1" in texto
    assert "MRO.exe" not in texto, "o LEIA-ME nao pode mais mandar dar dois cliques no exe"


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
    deixava duas versoes misturadas na mesma pasta, sem aviso.

    v6.6.0: a guarda continua igual, mas o desvio virou `goto fim` em vez de `exit /b 1`
    direto — o bat passou a PAUSAR antes de fechar (janela fechando sozinha era o motivo
    de "rodei e nao deu nada"). O que este teste garante e o COMPORTAMENTO: desviar antes
    do Expand-Archive e sair com codigo 1.
    """
    bat = ATUALIZAR.read_text(encoding="utf-8", errors="ignore")

    guarda = bat.split("[3/5]", 1)[1].split("[4/5]", 1)[0]
    assert 'if exist "%MRO_RAIZ%app"' in guarda
    assert "ABORTADA" in guarda
    assert "exit /b 1" in guarda or ('set "ERRO=1"' in guarda and "goto fim" in guarda)
    # E o desvio precisa mesmo terminar em codigo 1, nao so parecer que termina.
    assert "exit /b %ERRO%" in bat


def test_pyinstaller_saiu_das_duas_listas():
    """v6.8.2 — inverte o contrato da v5.8.0 (`pyinstaller` fixado no dev, ausente no prod).

    O pin so existia para congelar o `deploy/launcher.py` em MRO.exe. Sem o freeze, ele
    passa a ser dependencia de desenvolvimento que ninguem usa: pesada de instalar e
    enganosa para quem le o arquivo e conclui que o build ainda congela algo.
    """
    dev = (PROJ / "requirements-dev.txt").read_text(encoding="utf-8")
    prod = (PROJ / "requirements.txt").read_text(encoding="utf-8")

    assert not re.search(r"^pyinstaller==", dev, re.M), (
        "o pin do pyinstaller saiu na v6.8.2 — o pacote portatil nao congela mais nada"
    )
    assert "pyinstaller" not in prod.lower()
    assert not (PROJ / "deploy" / "launcher.py").exists(), (
        "deploy/launcher.py foi apagado na v6.8.2 (era so a fonte do exe)"
    )
    # Que o BUILD nao invoca mais o freeze ja e travado por
    # `test_portatil_nao_empacota_exe_e_sim_atalho`; aqui e so a lista de dependencias.
