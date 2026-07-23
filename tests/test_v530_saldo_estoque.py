"""Testes focados da migração Saldo em Estoque (v5.3.0 / F4a).

Cobre a lógica pura extraída do bloco inline: `acaba_em` (data estimada de ruptura)
e os predicados dos filtros rápidos. O render da página é coberto pelo smoke
parametrizado `test_v500_router` (Saldo em Estoque entrou em ROTAS_MIGRADAS)."""
from datetime import date

import pandas as pd

from services.constants import PREVISAO_RUPTURA_SEM_RISCO
from ui.paginas.saldo_estoque import (
    acaba_em, _pill_status_contem, _pill_nao_inventariado,
)


class TestAcabaEm:
    def test_dias_positivos_somam_a_data(self):
        assert acaba_em(5, hoje=date(2026, 1, 1)) == "06/01/2026"
        assert acaba_em(30, hoje=date(2026, 1, 1)) == "31/01/2026"

    def test_sem_consumo_e_sentinela_viram_travessao(self):
        assert acaba_em(0) == "—"
        assert acaba_em(-3) == "—"
        assert acaba_em(PREVISAO_RUPTURA_SEM_RISCO) == "—"
        assert acaba_em(PREVISAO_RUPTURA_SEM_RISCO + 10) == "—"

    def test_nao_numerico_vira_travessao(self):
        assert acaba_em(None) == "—"
        assert acaba_em("x") == "—"
        assert acaba_em("") == "—"

    def test_string_numerica_e_float_aceitos(self):
        assert acaba_em("5", hoje=date(2026, 1, 1)) == "06/01/2026"
        assert acaba_em(5.9, hoje=date(2026, 1, 1)) == "06/01/2026"  # int() trunca p/ 5


def _df():
    return pd.DataFrame([
        {"part_number": "A", "status_material": "🔴 COMPRAR", "data_inventario": ""},
        {"part_number": "B", "status_material": "🟢 OK", "data_inventario": "2026-01-10"},
        {"part_number": "C", "status_material": "🟡 ATENÇÃO", "data_inventario": None},
    ])


class TestPredicadosFiltros:
    def test_status_contem_comprar(self):
        df = _df()
        mask = _pill_status_contem("COMPRAR")(df)
        assert list(df[mask]["part_number"]) == ["A"]

    def test_status_contem_atencao(self):
        df = _df()
        mask = _pill_status_contem("ATENÇÃO")(df)
        assert list(df[mask]["part_number"]) == ["C"]

    def test_nao_inventariado_pega_vazio_e_none(self):
        df = _df()
        mask = _pill_nao_inventariado(df)
        assert set(df[mask]["part_number"]) == {"A", "C"}

    def test_predicados_robustos_a_coluna_ausente(self):
        df = pd.DataFrame([{"part_number": "X"}])
        # Sem status_material/data_inventario o predicado não pode quebrar (mantém tudo).
        assert _pill_status_contem("COMPRAR")(df).all()
        assert _pill_nao_inventariado(df).all()
