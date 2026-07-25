"""Fase 1 (DT-1): caracteriza os helpers vigentes para garantir que a remocao
da copia duplicada (db_functions.py:18-94) nao altere comportamento."""

from services import db_functions as F


class TestToFloat:
    def test_inteiro(self):
        assert F._to_float(5) == 5.0

    def test_none(self):
        assert F._to_float(None) == 0.0

    def test_decimal_br(self):
        assert F._to_float("1,5") == 1.5

    def test_milhar_br(self):
        assert F._to_float("1.234,56") == 1234.56

    def test_vazio(self):
        assert F._to_float("") == 0.0

    def test_invalido(self):
        assert F._to_float("abc") == 0.0


class TestNormalizarTxt:
    def test_remove_acentos(self):
        assert F._normalizar_txt("Solicitacao") == "solicitacao"

    def test_acento_real(self):
        assert F._normalizar_txt("Solicitação") == "solicitacao"

    def test_colapsa_espacos(self):
        assert F._normalizar_txt("  a   b ") == "a b"

    def test_none(self):
        assert F._normalizar_txt(None) == ""


class TestToDateStr:
    def test_formato_br(self):
        assert F._to_date_str("31/12/2026") == "2026-12-31"

    def test_none(self):
        assert F._to_date_str(None) is None


class TestStatusScImportado:
    def test_rejeitado(self):
        assert F._status_sc_importado("Rejeitado", 5) == "Cancelado"

    def test_saldo_zero(self):
        assert F._status_sc_importado("Pedido", 0) == "Recebido"

    def test_pedido(self):
        assert F._status_sc_importado("Pedido Emitido", 5) == "Pedido Emitido"


class TestPrioridadeCritica:
    def test_parada(self):
        assert F._tem_prioridade_critica("parada de linha") is True

    def test_normal(self):
        assert F._tem_prioridade_critica("compra de rotina") is False
