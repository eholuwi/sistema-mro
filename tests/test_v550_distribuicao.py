"""Testes da F5 (v5.5.0) — Distribuição no PC-servidor.

Cobrem as 2 mudanças de código em database.py (DB_PATH sobrescrevível por env +
PRAGMA busy_timeout) e a sanidade do artefato de config de servidor. São puros e
isolados — não sobem o Streamlit nem tocam o mro.db real.
"""
import importlib
import os
import tomllib
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]


def test_mro_db_path_env_override(monkeypatch, tmp_path):
    """MRO_DB_PATH sobrescreve o default; sem env, o default é o mro.db ABSOLUTO ao
    lado de database.py. Recarrega o módulo para reavaliar a expressão de nível de
    módulo e restaura o estado ao final (não vaza p/ outros testes)."""
    import database

    alvo = str(tmp_path / "servidor" / "mro.db")
    monkeypatch.setenv("MRO_DB_PATH", alvo)
    try:
        importlib.reload(database)
        assert database.DB_PATH == alvo
    finally:
        monkeypatch.delenv("MRO_DB_PATH", raising=False)
        importlib.reload(database)

    # Sem env: default absoluto, terminando em mro.db ao lado de database.py.
    esperado = os.path.join(os.path.dirname(os.path.abspath(database.__file__)), "mro.db")
    assert os.path.isabs(database.DB_PATH)
    assert database.DB_PATH == esperado


def test_busy_timeout_aplicado(db):
    """get_connection() aplica PRAGMA busy_timeout=5000 (proteção multiusuário WAL)."""
    conn = db.get_connection()
    try:
        valor = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        conn.close()
    assert valor == 5000


def test_config_servidor_toml_sanidade():
    """deploy/config-servidor.toml: bind de rede + headless + tema preservado."""
    caminho = PROJ / "deploy" / "config-servidor.toml"
    assert caminho.exists(), "deploy/config-servidor.toml ausente"
    cfg = tomllib.loads(caminho.read_text(encoding="utf-8"))
    assert cfg["server"]["address"] == "0.0.0.0"
    assert cfg["server"]["port"] == 8501
    assert cfg["server"]["headless"] is True
    # Superset theme+server: o tema da marca continua presente.
    assert cfg["theme"]["primaryColor"] == "#F36F21"
