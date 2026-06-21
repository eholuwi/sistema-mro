"""Fase 1 (DT-10): garante que as listas de dominio usadas na UI continuam
compativeis com os CHECK do schema. Se a futura extracao para constants.py
divergir do banco, estes testes quebram imediatamente."""
import pytest
from services import db_functions as F

UNIDADES = ["UN", "CX", "GL", "RL", "PCT", "LT", "RM"]
IMPORTANCIAS = ["Parada de Linha", "Importante", "Admin"]
TIPOS = ["Spare Parts", "Consumivel", "Expediente", "Uniforme", "Improdutivo"]


@pytest.mark.parametrize("un", UNIDADES)
def test_unidades_da_ui_aceitas_pelo_schema(db, un):
    ok, msg = F.salvar_item(f"PN-{un}", "x", "", un, "Importante",
                            "Spare Parts", "Improdutivo", "ARM-01", "", 1, 1, 7)
    assert ok, msg


@pytest.mark.parametrize("imp", IMPORTANCIAS)
def test_importancias_da_ui_aceitas(db, imp):
    ok, msg = F.salvar_item(f"PN-{imp}", "x", "", "UN", imp,
                            "Spare Parts", "Improdutivo", "ARM-01", "", 1, 1, 7)
    assert ok, msg


@pytest.mark.parametrize("tp", TIPOS)
def test_tipos_da_ui_aceitos(db, tp):
    ok, msg = F.salvar_item(f"PN-{tp}", "x", "", "UN", "Importante",
                            tp, "Improdutivo", "ARM-01", "", 1, 1, 7)
    assert ok, msg
