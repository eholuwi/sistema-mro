"""v4.4.0 — Fase 3 parte 2: Guarda-Chuva (Ficha 360) + Monitor de SC livre.

A UI (aba Guarda-Chuva/kanban e grade livre "colar do Excel") é coberta pelo smoke
E2E. Aqui ficam as funções de serviço testáveis: persistência JSON da grade livre.
"""

from services import db_functions as F


def test_monitor_livre_migracao(db):
    conn = db.get_connection()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(monitor_livre)")}
    conn.close()
    assert {"id", "dados_json", "data_atualizacao"} <= cols


def test_monitor_livre_vazio(db):
    assert F.carregar_monitor_livre() == []


def test_monitor_livre_roundtrip(db):
    regs = [{"A": "PN", "B": "Nome", "C": "Qtd"}, {"A": "X1", "B": "Item 1", "C": "10"}]
    n = F.salvar_monitor_livre(regs)
    assert n == 2
    assert F.carregar_monitor_livre() == regs


def test_monitor_livre_overwrite(db):
    # Documento único (id=1): salvar de novo substitui o anterior, não acumula.
    F.salvar_monitor_livre([{"A": "antigo"}])
    F.salvar_monitor_livre([{"A": "novo", "B": "b"}])
    assert F.carregar_monitor_livre() == [{"A": "novo", "B": "b"}]


def test_monitor_livre_preserva_acentos(db):
    regs = [{"A": "Descrição", "B": "Válvula 1/2"}]
    F.salvar_monitor_livre(regs)
    assert F.carregar_monitor_livre() == regs
