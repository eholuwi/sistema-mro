"""v3.7.0 — Estoque de Segurança removido: reflexos no ROP e no gatilho de reposição.

Antes, itens sem consumo recebiam um "piso pelo mínimo" na segurança e o ROP somava a
segurança. Agora o buffer é o próprio Mínimo do Neidson: o ROP = consumo × lead, e a
proteção de itens sem consumo vem do gatilho de piso (estoque ≤ mínimo) em
`precisa_repor` — não mais de um estoque de segurança efetivo.
"""

from services.planejamento import (
    estoque_seguranca_efetivo,
    calcular_ponto_reposicao,
    precisa_repor,
)


def _item(**over):
    base = dict(
        estoque_atual=0.0,
        estoque_em_transito=0.0,
        estoque_minimo=0.0,
        estoque_seguranca=0.0,
        estoque_seguranca_calculado=0.0,
        consumo_medio_diario=0.0,
        lead_time_dias=0,
        lead_time_calculado=None,
    )
    base.update(over)
    return base


# ── estoque_seguranca_efetivo: no-op (sempre 0) ────────────────────────────────


def test_seguranca_efetiva_sempre_zero_mesmo_com_manual():
    val, origem = estoque_seguranca_efetivo(
        _item(estoque_seguranca=10, estoque_seguranca_calculado=20, estoque_minimo=8)
    )
    assert val == 0
    assert origem == "não utilizado"


# ── ROP = consumo × lead (sem segurança) ───────────────────────────────────────


def test_rop_nao_soma_seguranca():
    calc = calcular_ponto_reposicao(_item(consumo_medio_diario=2.0, lead_time_dias=10))
    assert calc["rop"] == 20
    assert "estoque_seguranca" not in calc


# ── Proteção de itens sem consumo: gatilho de PISO (estoque ≤ mínimo) ───────────


def test_piso_do_minimo_ainda_dispara_reposicao_sem_consumo():
    # Sem consumo, mas abaixo do mínimo → ainda entra na fila (gatilho de piso).
    item = _item(consumo_medio_diario=0.0, estoque_atual=3, estoque_minimo=8)
    assert precisa_repor(item) is True


def test_item_sem_consumo_acima_do_minimo_nao_repor():
    item = _item(consumo_medio_diario=0.0, estoque_atual=20, estoque_minimo=8)
    assert precisa_repor(item) is False
