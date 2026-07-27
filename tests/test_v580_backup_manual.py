"""v5.8.0 — Backup sob demanda (`services/backup.py`) e a tabela `configuracoes`.

O teste que mais importa aqui e o do destino extra que falha: o `.bak` principal ja esta
gravado quando a copia e tentada, entao um pendrive desconectado ou uma pasta de rede fora
do ar NAO pode derrubar o backup. Perder o backup por causa da copia seria pior que nao ter
copia nenhuma.

O resto cobre o contrato de `configuracoes['backup_destino']` — inclusive a regravacao
repetida, que e exatamente onde reusar a tabela `listas` teria batido em IntegrityError
(soft-delete `ativo=0` contra `UNIQUE(tipo,valor)`).
"""

import os
import sqlite3

import pytest


@pytest.fixture
def bkp(db):
    """`services.backup` com o banco isolado do fixture `db` ja criado."""
    from services import backup

    return backup


# ── Tabela `configuracoes` ────────────────────────────────────────────────────


def test_tabela_configuracoes_existe(db):
    conn = db.get_connection()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(configuracoes)")}
    finally:
        conn.close()
    assert cols == {"chave", "valor"}


def test_criar_banco_e_idempotente_na_tabela_nova(db):
    """CREATE TABLE IF NOT EXISTS: rodar `criar_banco()` de novo nao pode quebrar."""
    db.criar_banco()
    db.criar_banco()

    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM configuracoes").fetchone()[0] == 0
    finally:
        conn.close()


# ── Destino configuravel ──────────────────────────────────────────────────────


def test_destino_ida_e_volta(bkp, tmp_path):
    pasta = tmp_path / "extra"
    pasta.mkdir()

    ok, msg = bkp.definir_destino(str(pasta))

    assert ok, msg
    assert bkp.destino_configurado() == str(pasta)


def test_sem_destino_configurado_devolve_none(bkp):
    assert bkp.destino_configurado() is None


def test_string_vazia_limpa_o_destino(bkp, tmp_path):
    pasta = tmp_path / "extra"
    pasta.mkdir()
    bkp.definir_destino(str(pasta))

    ok, _ = bkp.definir_destino("")

    assert ok
    assert bkp.destino_configurado() is None


def test_regravar_o_mesmo_destino_varias_vezes(bkp, tmp_path):
    """O upsert por `chave` tem que aguentar trocar e voltar para o mesmo valor.

    E o cenario que reusar `listas` quebraria: `remover_valor_lista` so marca `ativo=0`
    e o `UNIQUE(tipo,valor)` faria o reinsert estourar IntegrityError.
    """
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()

    for alvo in (a, b, a, b, a):
        ok, msg = bkp.definir_destino(str(alvo))
        assert ok, msg

    assert bkp.destino_configurado() == str(a)

    import database

    conn = database.get_connection()
    try:
        linhas = conn.execute(
            "SELECT COUNT(*) FROM configuracoes WHERE chave=?", ("backup_destino",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert linhas == 1, "upsert deveria manter UMA linha por chave, nao acumular"


def test_destino_inexistente_e_recusado(bkp, tmp_path):
    ok, msg = bkp.definir_destino(str(tmp_path / "nao-existe"))

    assert not ok
    assert "não existe" in msg
    assert bkp.destino_configurado() is None


def test_destino_que_e_arquivo_e_recusado(bkp, tmp_path):
    arquivo = tmp_path / "isto-e-um-arquivo.txt"
    arquivo.write_text("x", encoding="utf-8")

    ok, msg = bkp.definir_destino(str(arquivo))

    assert not ok
    assert "não é uma pasta" in msg


# ── Backup ────────────────────────────────────────────────────────────────────


def test_backup_gera_sqlite_integro(bkp, tmp_path):
    res = bkp.fazer_backup("manual")

    assert res["ok"]
    assert os.path.dirname(res["caminho"]) == str(tmp_path / "backups")
    assert res["nome"].startswith("test_mro.db.bak-")
    assert res["nome"].endswith("-manual")
    assert res["tamanho"] > 0

    conn = sqlite3.connect(res["caminho"])
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"inventario", "movimentacoes", "configuracoes"} <= tabelas


def test_backup_sem_destino_nao_reclama(bkp):
    res = bkp.fazer_backup("manual")

    assert res["ok"]
    assert res["destino_extra"] is None
    assert res["erro_destino"] is None


def test_backup_copia_para_o_destino_configurado(bkp, tmp_path):
    pasta = tmp_path / "extra"
    pasta.mkdir()
    bkp.definir_destino(str(pasta))

    res = bkp.fazer_backup("manual")

    assert res["ok"]
    assert res["erro_destino"] is None
    assert res["destino_extra"] == str(pasta / res["nome"])
    assert os.path.exists(res["destino_extra"])
    assert os.path.getsize(res["destino_extra"]) == res["tamanho"]


def test_destino_sumido_nao_derruba_o_backup_principal(bkp, tmp_path):
    """O caso do pendrive desconectado / servidor trocado de maquina.

    O destino foi gravado quando existia; some depois. O `.bak` em `backups/` ja esta em
    disco quando a copia e tentada e TEM que sobreviver ao erro.
    """
    pasta = tmp_path / "extra"
    pasta.mkdir()
    bkp.definir_destino(str(pasta))
    pasta.rmdir()

    res = bkp.fazer_backup("manual")

    assert res["ok"], "a falha da copia extra nao pode invalidar o backup principal"
    assert os.path.exists(res["caminho"])
    assert res["destino_extra"] is None
    assert res["erro_destino"] and "não existe" in res["erro_destino"]


def test_destino_igual_a_pasta_de_backups_nao_duplica(bkp, db):
    """Apontar o destino para a propria `backups/` nao pode estourar SameFileError."""
    pasta = db.diretorio_backups()
    os.makedirs(pasta, exist_ok=True)
    bkp.definir_destino(pasta)

    res = bkp.fazer_backup("manual")

    assert res["ok"]
    assert res["erro_destino"] is None
    assert res["destino_extra"] == res["caminho"]


def test_backup_sem_banco_devolve_nao_ok(tmp_path, monkeypatch):
    """Banco inexistente: `_backup_db` devolve None e o resultado sai `ok=False`,
    sem exception — a tela mostra erro em vez de quebrar."""
    import database

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "nunca-criado.db"))
    from services import backup

    res = backup.fazer_backup("manual")

    assert res["ok"] is False
    assert res["caminho"] is None
    assert res["tamanho"] == 0


# ── Contrato com a tela ───────────────────────────────────────────────────────


def test_resultado_tem_as_chaves_que_a_tela_le(bkp):
    """`ui/paginas/configuracoes.py` indexa direto — chave faltando vira KeyError na tela,
    que o smoke de render nao pega (o bloco so aparece depois de clicar no botao)."""
    res = bkp.fazer_backup("manual")

    assert set(res) == {"ok", "caminho", "nome", "tamanho", "destino_extra", "erro_destino"}
