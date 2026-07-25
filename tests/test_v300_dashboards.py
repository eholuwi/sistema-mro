"""v3.0.0 — Dashboards por público (Comprador / Gestão / KPI Mensal).

v3.3.0: visão "Diretoria" removida; "Mensal" renomeada para "KPI Mensal".

Cobre os assemblers PUROS de `services/dashboards.py` (montam view-models a partir
de funções que já existem) e os casos-limite honestos: nível de serviço com
denominador zero, giro/cobertura sem dado, exclusão da sentinela de cobertura,
aging por faixa e o roteador `montar_dashboard`. Sem tocar o mro.db real (fixtures
de banco temporário isolado).
"""

from datetime import date


import database
from services.constants import PREVISAO_RUPTURA_SEM_RISCO
from services import dashboards as D


def _set_inv(item_id, **campos):
    """Seta campos do inventário direto (determinismo dos cálculos de série/cobertura)."""
    sets = ", ".join(f"{k}=?" for k in campos)
    with database.transaction() as c:
        c.execute(f"UPDATE inventario SET {sets} WHERE id=?", (*campos.values(), item_id))


# ══════════════════════════════════════════════════════════════════════════════
# Helper puro: _dias_desde
# ══════════════════════════════════════════════════════════════════════════════


def test_dias_desde_parseia_data_e_datahora():
    assert D._dias_desde("2026-06-01", hoje=date(2026, 6, 11)) == 10
    assert D._dias_desde("2026-06-01 08:00:00", hoje=date(2026, 6, 1)) == 0


def test_dias_desde_invalido_retorna_none():
    assert D._dias_desde(None) is None
    assert D._dias_desde("") is None
    assert D._dias_desde("não é data") is None


# ══════════════════════════════════════════════════════════════════════════════
# 📊 GESTÃO
# ══════════════════════════════════════════════════════════════════════════════


def test_gestao_distribuicao_e_nivel_servico(db, make_item, registrar_consumo):
    a = make_item(part_number="A", estoque=100, minimo=10)  # OK, com consumo, fora ruptura
    b = make_item(part_number="B", estoque=0, minimo=10)  # COMPRAR, zerado, ruptura
    make_item(part_number="C", estoque=50, minimo=5)  # sem movimentação
    registrar_consumo(a)
    registrar_consumo(b)

    vm = D.montar_visao_gestao()
    d = vm["distribuicao"]
    assert vm["total"] == 3
    assert vm["com_consumo"] == 2  # A e B
    assert d["sem_mov"] == 1  # C
    assert d["zerados"] == 1  # B
    assert d["ok"] == 1  # A
    assert d["comprar"] == 1  # B
    # Saúde física conta TODOS os itens (inclusive Sem Movimentação): A e C físicamente
    # OK (100>10×1,2 e 50>5×1,2), B zerado. C entra em "ok" apesar de Sem Movimentação.
    sf = vm["saude_fisica"]
    assert sf == {"ok": 2, "atencao": 0, "critico": 0, "zerado": 1}
    # Nível de serviço = fora de ruptura / com consumo = 1/2 = 50%.
    assert vm["kpis"]["nivel_servico"] == 50.0
    # Sem preço cadastrado → valor imobilizado zero (mas presente e numérico).
    assert vm["kpis"]["valor_imobilizado"] == 0.0


def test_gestao_nivel_servico_none_quando_ninguem_tem_consumo(db, make_item):
    make_item(part_number="X", estoque=5, minimo=1)  # sem consumo real
    vm = D.montar_visao_gestao()
    assert vm["com_consumo"] == 0
    assert vm["kpis"]["nivel_servico"] is None
    assert vm["kpis"]["cobertura_media"] is None
    assert vm["kpis"]["giro_medio"] is None


def test_gestao_cobertura_media_exclui_sentinela(db, make_item, registrar_consumo):
    a = make_item(part_number="A", estoque=100, minimo=10)
    b = make_item(part_number="B", estoque=50, minimo=5)
    registrar_consumo(a)
    registrar_consumo(b)
    # A: consumo/dia = 10 → cobertura = 100/10 = 10. B: consumo/dia = 0 → sentinela 999.
    _set_inv(a, consumo_medio_diario=10)
    _set_inv(b, consumo_medio_diario=0)

    vm = D.montar_visao_gestao()
    # A sentinela (999) de B é excluída; só A entra na média.
    assert vm["kpis"]["cobertura_media"] == 10.0
    assert PREVISAO_RUPTURA_SEM_RISCO == 999


# ══════════════════════════════════════════════════════════════════════════════
# 👤 COMPRADOR
# ══════════════════════════════════════════════════════════════════════════════


def test_comprador_kpis_fila_e_ruptura(db, make_item, registrar_consumo):
    crit = make_item(part_number="CRIT", estoque=0, minimo=50)
    registrar_consumo(crit)
    _set_inv(crit, consumo_medio_diario=5)  # dá "relógio" de consumo → entra na fila

    vm = D.montar_visao_comprador()
    kpis = vm["kpis"]
    assert set(kpis) == {"criticos", "comprar_atrasados", "scs_abertas", "rupturas"}
    assert kpis["rupturas"] >= 1  # estoque 0 + consumo real
    assert vm["total_fila"] >= 1  # item precisa de reposição
    assert isinstance(vm["fila"], list) and isinstance(vm["scs_sugeridas"], list)


def test_comprador_aging_por_faixa(db, make_item, make_sc):
    # SC muito antiga (2020) cai em "15+"; sem itens abertos recentes.
    make_sc(numero_sc="SC-OLD", data_abertura="2020-01-01", part_number="P1", quantidade_solicitada=10)
    vm = D.montar_visao_comprador()
    ag = vm["aging"]
    assert set(ag) == {"0-7", "8-15", "15+", "sem_data"}
    assert ag["15+"] >= 1
    assert vm["kpis"]["scs_abertas"] >= 1


# ══════════════════════════════════════════════════════════════════════════════
# Roteador + _giro_medio
# ══════════════════════════════════════════════════════════════════════════════


def test_montar_dashboard_roteia_por_publico(db, make_item):
    make_item(part_number="R1", estoque=10, minimo=1)
    assert "fila" in D.montar_dashboard(D.PUBLICO_COMPRADOR)
    assert "distribuicao" in D.montar_dashboard(D.PUBLICO_GESTAO)
    assert "rankings" in D.montar_dashboard(D.PUBLICO_EXECUTIVO)
    # Público desconhecido cai no default (Gestão).
    assert "distribuicao" in D.montar_dashboard("qualquer coisa")


def test_giro_medio_none_sem_itens_com_consumo():
    assert D._giro_medio([]) is None
    assert D._giro_medio([{"id": 1, "sem_movimentacao": True}]) is None
