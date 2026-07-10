"""v3.4.0 — Assistente de Reposição: a justificativa das SCs sugeridas deixa explícito
o horizonte de ~2 meses e a base do cálculo (giro + mín/máx), conforme o §3 do backlog.
"""
from services.planejamento import resumir_grupo_sc


def test_justificativa_menciona_2_meses_e_base():
    sugs = [{
        "part_number": "PN-1", "nome_item": "Item", "prioridade_tier": 0,
        "prioridade": "🔴 Crítico", "consumo_diario": 1.0, "qtd_sugerida": 10,
        "cc_sugerido": "CC-1", "comprar_ate": "2026-07-15",
    }]
    r = resumir_grupo_sc("Consumível", sugs, criterio="tipo de material")
    just = r["justificativa"].lower()
    assert "2 meses" in just
    assert "giro" in just
    assert "mín" in just or "min" in just
