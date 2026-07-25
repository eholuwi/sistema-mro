"""v4.1.0 — Quick Wins de UX/clareza (Fase 1).

A maior parte das mudanças da Fase 1 é de interface (rótulos, help, abas, selects
com default vazio, reorganização de dashboards) e é coberta pelo smoke E2E
(AppTest sobre uma cópia do mro.db). Aqui ficam as mudanças testáveis na camada de
serviço.
"""

from services import db_functions as F


def test_export_inventario_sem_coluna_seguranca(db, make_item):
    # v4.1.0 — a coluna "Segurança" (estoque_seguranca) saiu do Excel de inventário.
    make_item("PN-410")
    df = F.exportar_inventario_df()
    assert not df.empty
    assert "Segurança" not in df.columns
    # Continua trazendo as colunas essenciais — incluindo "UN", usada na tabela
    # "Top capital parado" do Dashboard de movimentações.
    assert "UN" in df.columns
    assert "PN" in df.columns
    assert "Estoque Atual" in df.columns
