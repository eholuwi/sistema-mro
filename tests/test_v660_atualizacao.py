"""v6.6.0 — Atualizacao do sistema pelo proprio app.

O que da para provar sem Windows (e o que roda na CI ubuntu): a validacao do pacote, a
comparacao de versao, a descoberta da instalacao, a montagem da linha de comando e os
invariantes dos dois .bat. A troca de pasta em si (matar o processo, mover `app\\`,
religar) so se valida a mao, num Windows — esta coberta pelo roteiro do changelog.

O teste mais importante do arquivo e `test_motor_nao_usa_timeout`: `timeout` aborta na
hora quando o stdin esta redirecionado, que e exatamente como `disparar()` lanca o motor.
Com ele, a espera da porta rodaria as 40 voltas em milissegundos e a troca comecaria com
o Streamlit ainda segurando o banco — falha silenciosa, medida em 12/08/2026.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

from services import atualizacao as A  # noqa: E402

MOTOR = PROJ / "deploy" / "aplicar_atualizacao.bat"
BREAK_GLASS = PROJ / "deploy" / "atualizar_mro.bat"


# ══════════════════════════════════════════════════════════════════════════════
# Pacote sintetico
# ══════════════════════════════════════════════════════════════════════════════


def _zip_bytes(arquivos: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, conteudo in arquivos.items():
            zf.writestr(nome, conteudo)
    return buf.getvalue()


def _pacote_valido(versao="6.7.0") -> bytes:
    return _zip_bytes(
        {
            "app.py": "# app\n",
            "database.py": "# db\n",
            "services/constants.py": f'VERSAO = "{versao}"\nVERSAO_ROTULO = f"v{{VERSAO}}"\n',
            "ui/router.py": "# router\n",
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
# ler_versao / comparar_versoes
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ('VERSAO = "6.5.2"', "6.5.2"),
        ("VERSAO = '6.6.0'", "6.6.0"),
        ('VERSAO = "v6.6.0"', "6.6.0"),
        ('X = 1\nVERSAO = "7.0.0"\nY = 2', "7.0.0"),
        ("# VERSAO = nao definida", None),
        ("", None),
    ],
)
def test_ler_versao(texto, esperado):
    assert A.ler_versao(texto) == esperado


def test_release_usa_a_mesma_regex():
    """`scripts/release.py` nao pode ter uma segunda copia da leitura de VERSAO."""
    fonte = (PROJ / "scripts" / "release.py").read_text(encoding="utf-8")
    assert "from services.atualizacao import ler_versao" in fonte
    assert "re.search" not in fonte, "release.py voltou a ter regex propria de VERSAO"


@pytest.mark.parametrize(
    "instalada,pacote,esperado",
    [
        ("6.5.2", "6.6.0", "nova"),
        ("6.5.2", "6.5.2", "mesma"),
        ("6.6.0", "6.5.2", "downgrade"),
        # Ordem alfabetica diria que "6.10.0" < "6.9.0" — o sistema vai chegar la.
        ("6.9.0", "6.10.0", "nova"),
        ("6.10.0", "6.9.0", "downgrade"),
        # Comprimentos diferentes: 6.6 == 6.6.0
        ("6.6", "6.6.0", "mesma"),
        ("6.6", "6.6.1", "nova"),
        ("6.5.2", "abacaxi", "desconhecida"),
        (None, "6.6.0", "desconhecida"),
    ],
)
def test_comparar_versoes(instalada, pacote, esperado):
    assert A.comparar_versoes(instalada, pacote) == esperado


# ══════════════════════════════════════════════════════════════════════════════
# inspecionar_pacote
# ══════════════════════════════════════════════════════════════════════════════


def test_inspecionar_pacote_valido():
    ok, info = A.inspecionar_pacote(_pacote_valido("6.7.0"))
    assert ok
    assert info["versao"] == "6.7.0"
    assert info["arquivos"] == 4


def test_inspecionar_pacote_vazio():
    ok, info = A.inspecionar_pacote(b"")
    assert not ok and "vazio" in info["erro"].lower()


def test_inspecionar_pacote_nao_e_zip():
    ok, info = A.inspecionar_pacote(b"isto nao e um zip, e um texto qualquer")
    assert not ok and ".zip" in info["erro"]


def test_inspecionar_pacote_de_outro_produto():
    """Um zip qualquer nao pode ser aceito: instalar isso destruiria a instalacao."""
    ok, info = A.inspecionar_pacote(_zip_bytes({"planilha.xlsx": "x", "leiame.txt": "y"}))
    assert not ok
    assert "nao e um pacote do Sistema MRO" in info["erro"].replace("ã", "a").replace("é", "e")


def test_inspecionar_pacote_sem_constants():
    ok, info = A.inspecionar_pacote(_zip_bytes({"app.py": "# app"}))
    assert not ok and "services/constants.py" in info["erro"]


def test_inspecionar_pacote_sem_versao():
    ok, info = A.inspecionar_pacote(_zip_bytes({"app.py": "# app", "services/constants.py": "MARGEM = 1.2"}))
    assert not ok and "VERSAO" in info["erro"]


def test_inspecionar_pacote_grande_demais():
    """O pacote PORTATIL (~148 MB) tem outro layout e nao serve para esta troca."""
    ok, info = A.inspecionar_pacote(b"x" * (A.TAMANHO_MAX_PACOTE + 1))
    assert not ok and "grande demais" in info["erro"]


def test_inspecionar_pacote_com_caminho_de_escape():
    """`..` no nome escaparia de app\\ no Expand-Archive."""
    dados = _zip_bytes(
        {
            "app.py": "# app",
            "services/constants.py": 'VERSAO = "6.7.0"',
            "../../fora.txt": "escapei",
        }
    )
    ok, info = A.inspecionar_pacote(dados)
    assert not ok and "caminho" in info["erro"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# Descoberta da instalacao
# ══════════════════════════════════════════════════════════════════════════════


def test_raiz_instalacao_producao(tmp_path):
    """C:\\MRO\\dados\\mro.db -> C:\\MRO"""
    db = tmp_path / "MRO" / "dados" / "mro.db"
    db.parent.mkdir(parents=True)
    assert A.raiz_instalacao(db) == tmp_path / "MRO"


def test_raiz_instalacao_dev(tmp_path):
    """Em dev o banco fica na raiz do repo, sem pasta `dados` — nao pode subir um nivel."""
    db = tmp_path / "sistema-mro" / "mro.db"
    db.parent.mkdir(parents=True)
    assert A.raiz_instalacao(db) == tmp_path / "sistema-mro"


def test_modo_producao_quando_o_codigo_roda_de_dentro_de_app(tmp_path):
    """A pergunta certa: o codigo em execucao esta na pasta que a troca substitui?"""
    raiz = tmp_path / "MRO"
    (raiz / "app" / "services").mkdir(parents=True)
    (raiz / "app" / "app.py").write_text("# app", encoding="utf-8")

    assert A.modo_producao(raiz, origem=raiz / "app")


def test_modo_producao_independe_de_runtime_e_mro_exe(tmp_path):
    """Uma instalacao legitima com outro layout nao pode ser confundida com dev.

    O criterio antigo ("existe `runtime\\` ou `MRO.exe` ao lado?") era um palpite sobre
    COMO a instalacao foi montada: quem instalou de outro jeito veria a aba desabilitada
    em producao, sem nenhuma pista do motivo.
    """
    raiz = tmp_path / "MRO"
    (raiz / "app").mkdir(parents=True)
    (raiz / "app" / "app.py").write_text("# app", encoding="utf-8")
    assert not (raiz / "runtime").exists() and not (raiz / "MRO.exe").exists()

    assert A.modo_producao(raiz, origem=raiz / "app")


def test_modo_producao_falso_no_repo_de_dev(tmp_path):
    """O repositorio do Luis nao tem `app\\` — a tela precisa desabilitar a instalacao."""
    (tmp_path / "app.py").write_text("# app", encoding="utf-8")
    (tmp_path / "services").mkdir()
    assert not A.modo_producao(tmp_path, origem=tmp_path)


def test_modo_producao_falso_se_o_codigo_roda_de_fora_de_app(tmp_path):
    """Existe um `app\\` na raiz, mas quem esta rodando e outro codigo.

    Sem esta guarda, um `streamlit run app.py` no repositorio que por acaso tivesse uma
    subpasta `app\\` autorizaria a troca — e a troca move a pasta errada.
    """
    raiz = tmp_path / "MRO"
    (raiz / "app").mkdir(parents=True)
    (raiz / "app" / "app.py").write_text("# app", encoding="utf-8")
    (raiz / "outro").mkdir()

    assert not A.modo_producao(raiz, origem=raiz / "outro")
    assert not A.modo_producao(raiz, origem=raiz)


def test_modo_producao_em_runtime_usa_a_pasta_do_proprio_modulo(tmp_path):
    """Sem `origem`, a origem e a pasta que contem `services/` — aqui, o repositorio."""
    raiz = tmp_path / "MRO"
    (raiz / "app").mkdir(parents=True)
    (raiz / "app" / "app.py").write_text("# app", encoding="utf-8")
    assert not A.modo_producao(raiz), "o modulo roda do repo de dev, nao de raiz\\app"


# ══════════════════════════════════════════════════════════════════════════════
# Gravacao e comando
# ══════════════════════════════════════════════════════════════════════════════


def test_guardar_pacote_cria_pasta_e_grava(tmp_path):
    dados = _pacote_valido("6.7.0")
    destino = A.guardar_pacote(dados, "6.7.0", tmp_path)
    assert destino == tmp_path / "dados" / "atualizacoes" / "mro-6.7.0.zip"
    assert destino.read_bytes() == dados


def test_guardar_pacote_poda_os_antigos(tmp_path):
    pasta = tmp_path / "dados" / "atualizacoes"
    pasta.mkdir(parents=True)
    for n in range(10):
        (pasta / f"mro-6.0.{n}.zip").write_bytes(b"velho")

    A.guardar_pacote(_pacote_valido(), "6.7.0", tmp_path)

    restantes = sorted(p.name for p in pasta.glob("mro-*.zip"))
    assert len(restantes) == A.PACOTES_MANTIDOS
    assert "mro-6.7.0.zip" in restantes, "o pacote recem-gravado nunca pode ser podado"


def test_preparar_motor_copia_para_fora_de_app(tmp_path):
    """Rodar o bat de dentro de `app\\` seguraria lock na pasta que ele vai mover."""
    copia = A.preparar_motor(tmp_path)
    assert copia == tmp_path / "dados" / "atualizacoes" / A.NOME_MOTOR
    assert copia.read_bytes() == MOTOR.read_bytes()


def test_montar_comando_passa_pelo_comspec(tmp_path):
    """Chamada via `cmd /c`, nao apontando direto para o .bat (BatBadBut/CVE-2024-3566)."""
    cmd = A.montar_comando(tmp_path / "m.bat", tmp_path / "p.zip", tmp_path, 4242)
    assert cmd[1] == "/c"
    assert "cmd" in cmd[0].lower()
    assert cmd[2:] == [str(tmp_path / "m.bat"), str(tmp_path / "p.zip"), "4242", str(tmp_path)]


def test_montar_comando_sobrevive_a_espaco_e_acento(tmp_path):
    """`C:\\Tarefas Diarias\\` e caminho real deste projeto — forma LISTA, sem shell."""
    raiz = tmp_path / "Tarefas Diárias" / "MRO"
    raiz.mkdir(parents=True)
    cmd = A.montar_comando(raiz / "m.bat", raiz / "mro-6.6.0.zip", raiz, 1)
    assert any("Tarefas Diárias" in parte for parte in cmd)
    assert all(isinstance(parte, str) for parte in cmd)


# ══════════════════════════════════════════════════════════════════════════════
# Contratos do pacote e dos .bat
# ══════════════════════════════════════════════════════════════════════════════


def test_motor_viaja_no_pacote_de_release():
    """Sem isso, cada versao nova exigiria copiar o .bat a mao no PC-servidor."""
    import scripts.release as release

    nomes = {nome for _, nome in release.itens_do_pacote()}
    assert "deploy/aplicar_atualizacao.bat" in nomes


def test_atualizacao_e_stdlib_only():
    """`scripts/release.py` roda com o Python do sistema, sem as dependencias do app.

    Um import de pandas/streamlit aqui quebraria o empacotamento — e o modulo tambem e
    lido pela UI, entao a tentacao de importar `st` existe.
    """
    fonte = (PROJ / "services" / "atualizacao.py").read_text(encoding="utf-8")
    proibidos = ("import streamlit", "import pandas", "from services.db_functions", "import openpyxl")
    for termo in proibidos:
        assert termo not in fonte, f"services/atualizacao.py nao pode ter `{termo}`"


def test_motor_e_ascii_puro():
    """A janela do cmd abre em cp850/cp1252 — um acento vira `?` no relatorio."""
    MOTOR.read_bytes().decode("ascii")


def test_motor_nao_usa_timeout():
    """`timeout` aborta com stdin redirecionado — e `disparar()` usa stdin=DEVNULL.

    O efeito seria silencioso: a espera da porta (passo 2) daria as 40 voltas em
    milissegundos e a troca comecaria com o Streamlit ainda segurando o banco.
    """
    fonte = MOTOR.read_text(encoding="ascii")
    # So as linhas EXECUTAVEIS: o cabecalho cita `timeout /t 5` de proposito, para
    # explicar o que mudou em relacao ao bat da raiz.
    codigo = [ln for ln in fonte.splitlines() if not ln.strip().upper().startswith("REM")]
    assert not any("timeout /t" in ln for ln in codigo), "use `call :dormir N` (ping), nunca `timeout`"
    assert ":dormir" in fonte and "ping -n" in fonte


def test_disparar_usa_stdin_devnull_e_flags_de_destacamento():
    """As duas flags sao o coracao do mecanismo: sem elas o motor morre junto com o app."""
    fonte = (PROJ / "services" / "atualizacao.py").read_text(encoding="utf-8")
    assert "DETACHED_PROCESS" in fonte
    assert "CREATE_NEW_PROCESS_GROUP" in fonte
    assert "stdin=subprocess.DEVNULL" in fonte


@pytest.mark.parametrize("bat", [MOTOR, BREAK_GLASS], ids=["motor", "break-glass"])
def test_invariantes_compartilhados_dos_dois_bats(bat):
    """A semelhanca entre os dois e deliberada (ver cabecalho do motor): o da raiz e o
    break-glass e NAO pode depender de nada dentro de `app\\`. O que os dois precisam
    fazer igual fica travado aqui, para nao derivarem em silencio."""
    fonte = bat.read_text(encoding="utf-8")
    assert 'set "TAREFA=Sistema MRO"' in fonte, "nome EXATO da tarefa agendada"
    assert "pre-atualizacao" in fonte, "backup do banco antes de qualquer troca"
    assert "app_anterior" in fonte, "versao anterior preservada"
    # A guarda da v5.8.0: se o `move` falhou, ABORTAR — sem ela o Expand-Archive -Force
    # escreveria por cima da versao antiga e misturaria duas versoes na mesma pasta.
    assert "Expand-Archive" in fonte
    pos_move = fonte.find("app_anterior")
    pos_expand = fonte.find("Expand-Archive")
    assert pos_move < pos_expand, "o move tem que vir ANTES da extracao"


@pytest.mark.parametrize("bat", [MOTOR, BREAK_GLASS], ids=["motor", "break-glass"])
def test_os_dois_bats_religam_por_tres_caminhos(bat):
    """Nem toda instalacao usa tarefa agendada — e a do PC da sala MRO nao usa.

    O `atualizar_mro.bat` chamava SO `schtasks /Run`: numa maquina sem a tarefa (o
    antivirus corporativo tratou a tarefa agendada como ameaca e bloqueou a rede), o
    sistema ficava NO CHAO depois da atualizacao, sem nenhuma mensagem dizendo isso.
    """
    fonte = bat.read_text(encoding="ascii")
    assert "schtasks /Run" in fonte, "tarefa agendada, quando existe"
    assert "MRO.exe" in fonte, "duplo clique no executavel"
    assert "iniciar_mro.bat" in fonte, "ultimo recurso"
    assert "nao achei como religar" in fonte, "e avisar quando nao der para religar"
