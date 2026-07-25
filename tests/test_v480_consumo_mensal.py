"""v4.8.0 — Card "Consumo/Mensal" na Ficha 360.

Cobre a matemática PURA do consumo mensal ponderado (`_ponderado_from_serie` e
`_ultimos_n_meses_completos`): média dos últimos 3 meses COMPLETOS com peso 3/2/1
(recente pesa mais), meses sem saída contando 0, exclusão do mês corrente, virada de
ano e decaimento quando o item para de sair. Sem banco — funções determinísticas.
"""

from datetime import date

from services.classificacao import (
    _ponderado_from_serie,
    _ultimos_n_meses_completos,
)


def _serie(**meses):
    """Helper: {'2026-01': 50, ...} → [{mes, qtd}] no formato de consumo_mensal."""
    return [{"mes": m, "qtd": q} for m, q in sorted(meses.items())]


# ── Janela: últimos N meses completos (exclui o mês corrente) ──────────────────


def test_ultimos_3_meses_completos_exclui_mes_corrente():
    # Em 15/abr, os 3 meses completos são jan, fev, mar (abr está em andamento).
    assert _ultimos_n_meses_completos(date(2026, 4, 15)) == ["2026-01", "2026-02", "2026-03"]


def test_ultimos_meses_viram_o_ano():
    # Em fev/2026, os 3 completos anteriores cruzam a virada de ano.
    assert _ultimos_n_meses_completos(date(2026, 2, 10)) == ["2025-11", "2025-12", "2026-01"]


# ── Ponderação 3/2/1 ──────────────────────────────────────────────────────────


def test_exemplo_do_luis_jan50_fev20_mar40():
    # (mar×3 + fev×2 + jan×1) / 6 = (120 + 40 + 50) / 6 = 35.
    serie = _serie(**{"2026-01": 50, "2026-02": 20, "2026-03": 40})
    assert _ponderado_from_serie(serie, date(2026, 4, 15)) == 35.0


def test_mes_corrente_e_ignorado():
    # abr (mês corrente) não pode entrar na conta; o resultado é o mesmo do exemplo.
    serie = _serie(**{"2026-01": 50, "2026-02": 20, "2026-03": 40, "2026-04": 999})
    assert _ponderado_from_serie(serie, date(2026, 4, 15)) == 35.0


def test_mes_sem_saida_conta_como_zero():
    # fev ausente na série → conta 0: (mar30×3 + 0×2 + jan60×1)/6 = (90 + 60)/6 = 25.
    serie = _serie(**{"2026-01": 60, "2026-03": 30})
    assert _ponderado_from_serie(serie, date(2026, 4, 15)) == 25.0


def test_dois_meses_de_dados_no_periodo():
    # Só fev e mar têm dados; jan = 0: (mar40×3 + fev20×2 + 0×1)/6 = 160/6 ≈ 26.67.
    serie = _serie(**{"2026-02": 20, "2026-03": 40})
    assert _ponderado_from_serie(serie, date(2026, 4, 15)) == round(160 / 6, 2)


# ── Decaimento / sem dados → None (UI mostra "—") ─────────────────────────────


def test_item_que_parou_de_sair_decai_para_none():
    # Só teve saída em jan; em mai os 3 meses-alvo (fev/mar/abr) estão zerados → None.
    serie = _serie(**{"2026-01": 50})
    assert _ponderado_from_serie(serie, date(2026, 5, 15)) is None


def test_serie_vazia_retorna_none():
    assert _ponderado_from_serie([], date(2026, 4, 15)) is None
    assert _ponderado_from_serie(None, date(2026, 4, 15)) is None
