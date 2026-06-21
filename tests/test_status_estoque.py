"""Fase 2 (DT-4): fixa a regra OFICIAL de status de estoque (faixa com margem
de 20%) e documenta o alvo de unificacao do dashboard."""
import pytest
from services.db_functions import calcular_status_inventario as status


class TestRegraOficialFaixa20:
    def test_abaixo_do_minimo(self):      assert "COMPRAR" in status(5, 10, 0)
    def test_igual_ao_minimo(self):       assert "COMPRAR" in status(10, 10, 0)
    def test_zona_atencao_inferior(self): assert "ATENÇÃO" in status(11, 10, 0)
    def test_zona_atencao_limite(self):   assert "ATENÇÃO" in status(12, 10, 0)  # 10 * 1.2
    def test_acima_da_faixa(self):        assert "OK" in status(13, 10, 0)
    def test_minimo_zero_com_saldo(self): assert "OK" in status(5, 0, 0)
    def test_minimo_zero_sem_saldo(self): assert "COMPRAR" in status(0, 0, 0)
    def test_none_nao_quebra(self):       assert "COMPRAR" in status(None, None, 0)


def test_dashboard_concorda_com_regra_oficial(db, make_item):
    from services import db_functions as F
    make_item("PN-AT", estoque=11, minimo=10)   # zona de ATENCAO pela regra oficial
    kpis = F.obter_dados_dashboard()["kpis"]
    assert kpis["atencao"] == 1 and kpis["ok"] == 0
