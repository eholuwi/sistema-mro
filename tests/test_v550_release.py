"""v5.5.0 (F5) — o pacote de release precisa levar tudo que o app importa, e nada
de dado operacional.

O risco dos dois lados e real: faltar um modulo so aparece quando o servidor sobe e
quebra; sobrar `mro.db` ou `vault/` vaza dado da operacao para um zip que circula por
e-mail/pendrive. Este teste fecha os dois.
"""

import ast
import sys
import zipfile
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts"))

release = pytest.importorskip("release")


@pytest.fixture(scope="module")
def pacote(tmp_path_factory):
    destino = release.empacotar("0.0.0-teste", tmp_path_factory.mktemp("dist"))
    with zipfile.ZipFile(destino) as zf:
        nomes = set(zf.namelist())
    return destino, nomes


# ── O que TEM que estar ───────────────────────────────────────────────────────


def test_leva_o_essencial(pacote):
    _, nomes = pacote
    assert {"app.py", "database.py", "inventus_logo.png"} <= nomes


def test_config_de_producao_vira_streamlit_config(pacote):
    """A config do servidor (headless, 0.0.0.0:8501) entra como `.streamlit/config.toml`;
    a do repo e so tema (dev) e nao pode ir."""
    caminho, nomes = pacote
    assert ".streamlit/config.toml" in nomes

    with zipfile.ZipFile(caminho) as zf:
        conteudo = zf.read(".streamlit/config.toml").decode("utf-8")
    assert "headless" in conteudo and "8501" in conteudo


def test_leva_todo_modulo_de_services_e_ui(pacote):
    """Guarda contra 'esqueci de incluir a pasta nova': qualquer .py em services/ ou
    ui/ tem que estar no pacote."""
    _, nomes = pacote
    esperados = {
        str(p.relative_to(PROJ)).replace("\\", "/")
        for pasta in ("services", "ui")
        for p in (PROJ / pasta).rglob("*.py")
        if "__pycache__" not in p.parts
    }
    faltando = esperados - nomes
    assert not faltando, f"modulos de runtime fora do pacote: {sorted(faltando)}"


def test_leva_todo_import_de_primeiro_nivel_do_app(pacote):
    """Lê os imports de app.py e confirma que cada pacote local citado foi empacotado."""
    _, nomes = pacote
    arvore = ast.parse((PROJ / "app.py").read_text(encoding="utf-8"))

    modulos = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module:
            modulos.add(no.module.split(".")[0])
        elif isinstance(no, ast.Import):
            for alias in no.names:
                modulos.add(alias.name.split(".")[0])

    locais = {m for m in modulos if (PROJ / m).is_dir() or (PROJ / f"{m}.py").exists()}
    assert locais, "não consegui identificar nenhum import local em app.py"

    for m in locais:
        assert f"{m}.py" in nomes or any(n.startswith(f"{m}/") for n in nomes), (
            f"app.py importa '{m}', mas ele não está no pacote"
        )


# ── O que NAO pode estar ──────────────────────────────────────────────────────


def test_nao_leva_dado_operacional_nem_vault(pacote):
    _, nomes = pacote
    proibidos = [n for n in nomes if n.endswith(".db") or n.startswith(("vault/", "tests/", "venv/", "docs/"))]
    assert not proibidos, f"o pacote nao pode conter estes itens: {proibidos}"


def test_nao_leva_bytecode(pacote):
    _, nomes = pacote
    assert not [n for n in nomes if n.endswith(".pyc") or "__pycache__" in n]


def test_versao_vem_do_sidebar():
    """`release.py` e `ui/sidebar.py` nao podem divergir no rotulo da versao."""
    from ui import sidebar

    assert release.versao_do_codigo() == sidebar.VERSAO.lstrip("v")
