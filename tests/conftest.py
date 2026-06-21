"""
Infraestrutura de testes — Fase 0 (rede de seguranca).

Cada teste recebe um banco SQLite TEMPORARIO e ISOLADO, sem tocar o mro.db de
producao. O isolamento usa monkeypatch de `database.DB_PATH`, que `get_connection()`
le em tempo de execucao. Nenhuma fixture abre conexao fora de `get_connection()`.
"""
import io
import sys
from pathlib import Path

import pytest

# Torna 'database' e 'services' importaveis ao rodar pytest de qualquer cwd.
PROJ = Path(__file__).resolve().parents[1]  # .../2.0.2/sistema-mro
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Banco isolado por teste. Retorna o modulo `database` ja inicializado."""
    import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test_mro.db"))
    database.criar_banco()
    return database


@pytest.fixture
def make_item(db):
    """Cria um item no inventario e devolve seu id (consulta via get_connection)."""
    from services import db_functions as F

    def _make(part_number="PN-1", nome="Item", estoque=100, minimo=10,
              unidade="UN", importancia="Importante", tipo="Spare Parts",
              setor="Improdutivo", local="ARM-01", caixa="", lead=7):
        ok, msg = F.salvar_item(part_number, nome, "", unidade, importancia,
                                tipo, setor, local, caixa, estoque, minimo, lead)
        assert ok, msg
        conn = db.get_connection()
        row = conn.execute("SELECT id FROM inventario WHERE part_number=?",
                           (part_number,)).fetchone()
        conn.close()
        return row["id"]

    return _make


@pytest.fixture
def make_sc(make_item):
    """Cria uma SC com itens via criar_sc e devolve o sc_id (Fase 5 / T-01).

    Reutiliza make_item para garantir item valido (FK itens_sc.item_id ->
    inventario.id). Pre-requisito para testar atualizar_sc, que exige uma SC
    existente.
    """
    from services import db_functions as F
    import database

    def _make(numero_sc="SC-100", data_abertura="2026-01-01",
              part_number="PN-SC", quantidade_solicitada=10, item_id=None):
        if item_id is None:
            item_id = make_item(part_number=part_number)
        itens = [{"item_id": item_id, "quantidade_solicitada": quantidade_solicitada}]
        ok, msg = F.criar_sc(numero_sc, data_abertura, itens)
        assert ok, msg
        conn = database.get_connection()
        row = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc=?",
                           (numero_sc,)).fetchone()
        conn.close()
        return row["id"]

    return _make


@pytest.fixture
def xlsx_factory():
    """Gera um buffer .xlsx em memoria para o importador Protheus.

    Correcao A-1: substitui o fragil `from conftest import make_xlsx`.
    Correcao A-3: engine='openpyxl' explicito.
    """
    import pandas as pd

    def _build(rows, columns):
        buf = io.BytesIO()
        pd.DataFrame(rows, columns=columns).to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)
        return buf

    return _build
