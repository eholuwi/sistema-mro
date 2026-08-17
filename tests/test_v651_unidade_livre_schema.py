"""v6.8.1 — `unidade` de inventario livre de CHECK (compativel com as listas
mestras da v6.5.1).

O v6.5.1 tornou Unidades administraveis em Configuracoes, mas o schema antigo
ainda prendia `unidade` a ('GL','UN','CX','RL','PCT','LT','RM'): criar "KG" na
lista e salvar o item caia em `CHECK constraint failed`. A migracao remove o
CHECK com rebuild seguro (SQLite nao remove CHECK via ALTER).

O que estes testes protegem:
  - o bug reproduzido: unidade fora da lista fixa rejeitada pelo schema antigo;
  - a migracao liberar a unidade e preservar dados, UNIQUE de part_number,
    AUTOINCREMENT de id e a FK de ultima_sc_id;
  - a idempotencia (rodar criar_banco de novo nao quebra);
  - o rollback: queda no meio do rebuild nao deixa a tabela pela metade.
"""

import sqlite3

import pytest

import database
from services import db_functions as F


def _tem_check_unidade(db):
    conn = db.get_connection()
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='inventario'").fetchone()[
        "sql"
    ]
    conn.close()
    return "CHECK(unidade" in sql.replace(" ", "").replace("CHECK (", "CHECK(")


def _reinserir_check_unidade(db):
    """Recria `inventario` com o schema antigo (CHECK de unidade) — o cenario do
    bug: lista administravel criada, banco ainda prendendo `unidade`. Espelha o
    rebuild da migracao, so que adicionando o CHECK de volta."""
    conn = db.get_connection()
    try:
        cols = conn.execute("PRAGMA table_info(inventario)").fetchall()
        defs = []
        for c in cols:
            nome, tipo, notnull, dflt, pk = c[1], c[2], c[3], c[4], c[5]
            d = nome
            if tipo:
                d += f" {tipo}"
            if nome == "part_number":
                d += " UNIQUE"
            if nome == "unidade":
                d += " CHECK(unidade IN ('GL','UN','CX','RL','PCT','LT','RM'))"
            if notnull:
                d += " NOT NULL"
            if dflt is not None:
                d += f" DEFAULT {dflt}"
            if pk:
                d += " PRIMARY KEY"
                if nome == "id":
                    d += " AUTOINCREMENT"
            defs.append(d)
        if any(c[1] == "ultima_sc_id" for c in cols):
            defs.append("FOREIGN KEY (ultima_sc_id) REFERENCES solicitacoes_compra(id)")
        iso = conn.isolation_level
        conn.isolation_level = None
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        conn.execute(f"CREATE TABLE inventario_antigo ({', '.join(defs)})")
        copia = ", ".join(c[1] for c in cols)
        conn.execute(f"INSERT INTO inventario_antigo ({copia}) SELECT {copia} FROM inventario")
        conn.execute("DROP TABLE inventario")
        conn.execute("ALTER TABLE inventario_antigo RENAME TO inventario")
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.isolation_level = iso
    finally:
        conn.close()


# ── Bug reproduzido ──────────────────────────────────────────────────────────


def test_schema_novo_aceita_unidade_da_lista(db):
    """Instalacao nova ja nasce com `unidade` livre (CHECK fora do CREATE TABLE)."""
    assert not _tem_check_unidade(db)

    ok, msg = F.salvar_item(
        "PN-KG", "Solvente", "", "KG", "Importante", "Quimico", "Improdutivo", "ARM-01", "", 1, 1, 7
    )

    assert ok, msg


def test_schema_antigo_rejeita_unidade_fora_da_lista(db, make_item):
    make_item(part_number="PN-A", unidade="UN")
    _reinserir_check_unidade(db)
    assert _tem_check_unidade(db)

    # INSERT cru: o CHECK rejeita "KG" com a mensagem real (o `salvar_item` embrulha
    # qualquer IntegrityError como "PN já existe", enganoso nesse caso).
    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError) as exc:
            conn.execute(
                "INSERT INTO inventario (part_number,nome_item,unidade) VALUES (?,?,?)",
                ("PN-KG", "Solvente", "KG"),
            )
    finally:
        conn.close()
    assert "CHECK constraint failed" in str(exc.value)

    # O caminho da tela também falha (não pode salvar).
    ok, msg = F.salvar_item(
        "PN-KG", "Solvente", "", "KG", "Importante", "Quimico", "Improdutivo", "ARM-01", "", 1, 1, 7
    )
    assert not ok


# ── Migracao ─────────────────────────────────────────────────────────────────


def test_migracao_libera_unidade_e_preserva_dados(db, make_item):
    item_id = make_item(part_number="PN-A", nome="Item A", unidade="UN", estoque=42)
    _reinserir_check_unidade(db)

    db.criar_banco()

    assert not _tem_check_unidade(db)
    ok, msg = F.salvar_item(
        "PN-KG", "Solvente", "", "KG", "Importante", "Quimico", "Improdutivo", "ARM-01", "", 1, 1, 7
    )
    assert ok, msg

    conn = db.get_connection()
    row = conn.execute("SELECT * FROM inventario WHERE id=?", (item_id,)).fetchone()
    conn.close()
    assert row["unidade"] == "UN"
    assert row["estoque_atual"] == 42
    assert row["tipo_material"] == "Spare Parts"


def test_migracao_nao_descarta_colunas_futuras(db, make_item):
    item_id = make_item(part_number="PN-A", unidade="UN")
    conn = db.get_connection()
    conn.execute("UPDATE inventario SET fator_conversao=5.0, ativo=0 WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    _reinserir_check_unidade(db)

    db.criar_banco()

    conn = db.get_connection()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(inventario)")}
    row = conn.execute("SELECT fator_conversao, ativo FROM inventario WHERE id=?", (item_id,)).fetchone()
    conn.close()
    assert {"fator_conversao", "ativo", "mostrar_saldo_requisitante", "unidade_compra"}.issubset(cols)
    assert row["fator_conversao"] == 5.0
    assert row["ativo"] == 0


def test_migracao_preserva_unique_de_part_number(db, make_item):
    make_item(part_number="PN-A", unidade="UN")
    _reinserir_check_unidade(db)

    db.criar_banco()

    ok, msg = F.salvar_item(
        "PN-A", "duplicado", "", "UN", "Importante", "Spare Parts", "Improdutivo", "ARM-01", "", 1, 1, 7
    )
    assert not ok
    conn = db.get_connection()
    idxs = {r["name"] for r in conn.execute("PRAGMA index_list(inventario)")}
    conn.close()
    assert "sqlite_autoindex_inventario_1" in idxs


def test_migracao_preserva_fk_de_ultima_sc_id(db, make_sc):
    make_sc(part_number="PN-A", numero_sc="SC-100")
    _reinserir_check_unidade(db)

    db.criar_banco()

    conn = db.get_connection()
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='inventario'").fetchone()[
        "sql"
    ]
    problemas = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    assert "FOREIGN KEY (ultima_sc_id) REFERENCES solicitacoes_compra(id)" in sql
    assert problemas == []


def test_migracao_preserva_autoincrement(db, make_item):
    _reinserir_check_unidade(db)

    db.criar_banco()

    ok, msg = F.salvar_item(
        "PN-A", "x", "", "UN", "Importante", "Spare Parts", "Improdutivo", "ARM-01", "", 1, 1, 7
    )
    assert ok, msg
    conn = db.get_connection()
    row = conn.execute("SELECT MAX(id) AS m FROM inventario").fetchone()
    seq = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='inventario'").fetchone()
    conn.close()
    assert row["m"] == 1
    assert seq is not None and seq["seq"] >= 1


def test_migracao_idempotente(db, make_item):
    make_item(part_number="PN-A", unidade="UN")
    _reinserir_check_unidade(db)

    db.criar_banco()
    db.criar_banco()
    db.criar_banco()

    assert not _tem_check_unidade(db)
    conn = db.get_connection()
    n = conn.execute("SELECT COUNT(*) AS n FROM inventario").fetchone()["n"]
    conn.close()
    assert n == 1


# ── Rollback ─────────────────────────────────────────────────────────────────


class _ConexaoQueFalhaNaRenomeacao:
    """Deixa a migracao correr normalmente e estoura no RENAME do rebuild — queda
    de energia, disco cheio, o que for. Tudo o mais e delegado a conexao real."""

    def __init__(self, conn):
        self._conn = conn

    @property
    def isolation_level(self):
        return self._conn.isolation_level

    @isolation_level.setter
    def isolation_level(self, valor):
        self._conn.isolation_level = valor

    def execute(self, sql, *args, **kwargs):
        if "ALTER TABLE inventario_new RENAME TO inventario" in sql:
            raise sqlite3.OperationalError("disco cheio (simulado)")
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, nome):
        return getattr(self._conn, nome)


def test_rollback_nao_deixa_rebuild_pela_metade(db, make_item):
    make_item(part_number="PN-A", unidade="UN", estoque=7)
    _reinserir_check_unidade(db)

    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.OperationalError):
            database._migrar_inventario_unidade_livre(_ConexaoQueFalhaNaRenomeacao(conn))
    finally:
        conn.close()

    # Conexao nova: o que interessa e o que sobrou COMMITADO no arquivo.
    assert _tem_check_unidade(db)  # o CHECK continua — a migracao nao se aplicou
    conn = db.get_connection()
    row = conn.execute(
        "SELECT part_number, unidade, estoque_atual FROM inventario WHERE part_number='PN-A'"
    ).fetchone()
    conn.close()
    assert row["unidade"] == "UN"
    assert row["estoque_atual"] == 7


def test_migracao_completa_depois_de_um_rollback(db, make_item):
    make_item(part_number="PN-A", unidade="UN")
    _reinserir_check_unidade(db)

    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.OperationalError):
            database._migrar_inventario_unidade_livre(_ConexaoQueFalhaNaRenomeacao(conn))
    finally:
        conn.close()

    db.criar_banco()

    assert not _tem_check_unidade(db)
    ok, msg = F.salvar_item(
        "PN-KG", "x", "", "KG", "Importante", "Quimico", "Improdutivo", "ARM-01", "", 1, 1, 7
    )
    assert ok, msg
