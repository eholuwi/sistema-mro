"""v5.5.0 (F5) — backups em `backups/` e o checkpoint do WAL que falhava calado.

Dois problemas na mesma funcao, corrigidos juntos:

1. `criar_banco()` chamava `_backup_db("pre-monitor-sc-v390")` com a propria transacao
   ainda aberta. `_backup_db` abre uma SEGUNDA conexao e roda
   `PRAGMA wal_checkpoint(TRUNCATE)`, que ficava presa o busy_timeout inteiro (5s) e
   devolvia SQLITE_BUSY. Por ser PRAGMA o BUSY vem como VALOR DE RETORNO, nao excecao —
   entao o `except` nunca via nada e o metodo logava "Backup do banco criado".
   Efeitos: ~5,5s perdidos por banco criado (x503 testes = ~47min) e um .bak gravado SEM
   o conteudo do WAL, logo antes de uma migracao destrutiva.
   O mesmo valia para `_backup_db("req-status-v470")` dentro de `_migrar` — pior ali,
   porque o backup precede um UPDATE que reescreve requisicoes legadas.

2. F5 (distribuicao): os .bak passam a cair em `backups/` ao lado do banco, fora da
   pasta do app — que o `atualizar_mro.bat` substitui inteira.
"""

import logging
import os
import sqlite3
import time

import pytest


@pytest.fixture
def db_zerado(tmp_path, monkeypatch):
    """Banco NAO inicializado (ao contrario do fixture `db`): o teste chama
    `criar_banco()` explicitamente para observar a primeira criacao."""
    import database

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "regressao.db"))
    return database


# ── Checkpoint do WAL ─────────────────────────────────────────────────────────


def test_criar_banco_nao_deixa_checkpoint_busy(db_zerado, caplog):
    """O backup do monitor_sc deve rodar com o lock liberado (checkpoint OK)."""
    with caplog.at_level(logging.WARNING, logger="database"):
        db_zerado.criar_banco()

    busy = [r for r in caplog.records if "BUSY" in r.getMessage()]
    assert not busy, f"checkpoint retornou BUSY durante criar_banco(): {busy}"


def test_criar_banco_nao_gasta_o_busy_timeout(db_zerado):
    """Guarda de performance: a versao com bug gastava ~5,5s (busy_timeout do SQLite)
    so no checkpoint bloqueado. Limite folgado para nao ficar instavel."""
    t0 = time.perf_counter()
    db_zerado.criar_banco()
    decorrido = time.perf_counter() - t0

    assert decorrido < 2.0, (
        f"criar_banco() levou {decorrido:.2f}s — indicio de que o checkpoint voltou a "
        "esperar o busy_timeout inteiro (regressao do lock aberto)"
    )


def test_backup_db_avisa_quando_checkpoint_fica_busy(db_zerado, caplog):
    """BUSY nao pode voltar a ser falso sucesso silencioso.

    Segura uma transacao de escrita aberta numa conexao paralela para forcar o
    SQLITE_BUSY e confirma que agora sai um WARNING explicito.
    """
    db_zerado.criar_banco()

    bloqueador = sqlite3.connect(db_zerado.DB_PATH, timeout=5.0)
    try:
        bloqueador.execute("BEGIN IMMEDIATE")
        bloqueador.execute("INSERT INTO listas (tipo, valor, ativo) VALUES ('teste','lock',1)")

        with caplog.at_level(logging.WARNING, logger="database"):
            db_zerado._backup_db("teste-busy")
    finally:
        bloqueador.rollback()
        bloqueador.close()

    assert any("BUSY" in r.getMessage() for r in caplog.records), (
        "checkpoint bloqueado deveria emitir WARNING, nao passar como sucesso"
    )


# ── Destino dos backups (F5) ──────────────────────────────────────────────────


def test_backup_vai_para_subpasta_backups(db_zerado, tmp_path):
    db_zerado.criar_banco()

    destino = db_zerado._backup_db("teste-destino")

    assert destino is not None
    assert os.path.dirname(destino) == str(tmp_path / "backups")
    assert os.path.exists(destino)
    assert os.path.basename(destino).startswith("regressao.db.bak-")


def test_diretorio_backups_fica_ao_lado_do_banco(db_zerado, tmp_path):
    assert db_zerado.diretorio_backups() == str(tmp_path / "backups")


def test_backup_e_um_sqlite_integro(db_zerado):
    """O ponto do backup e poder restaurar: o .bak precisa abrir e ter o schema."""
    db_zerado.criar_banco()

    destino = db_zerado._backup_db("teste-integridade")

    conn = sqlite3.connect(destino)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"inventario", "movimentacoes", "listas"} <= tabelas


def test_backup_sem_banco_nao_quebra(db_zerado):
    """Banco inexistente devolve None em vez de estourar (migracao nao pode falhar)."""
    assert db_zerado._backup_db("sem-banco") is None
