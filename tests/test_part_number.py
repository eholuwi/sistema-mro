"""Item 2 (v2.1.0): alteração de Part Number com rastreabilidade.

Verifica que a troca preserva o histórico (ligado por item_id), registra a relação
PN antigo↔novo, rejeita duplicados e mantém o item localizável pelo PN antigo."""
from services import db_functions as F

CC = "21106 - MANUTENÇÃO"


def test_altera_pn_preserva_movimentacoes(db, make_item):
    item_id = make_item("PN-OLD", estoque=100)
    F.registrar_movimentacao(item_id, "saida", 10, CC, "Joao", "Joao")
    antes = len(F.listar_movimentacoes(item_id))
    ok, msg = F.alterar_part_number(item_id, "PN-NEW", motivo="Protheus", usuario="luis")
    assert ok, msg
    assert F.buscar_item_por_id(item_id)["part_number"] == "PN-NEW"
    assert len(F.listar_movimentacoes(item_id)) == antes      # histórico intacto


def test_altera_pn_registra_historico(db, make_item):
    item_id = make_item("PN-H1")
    F.alterar_part_number(item_id, "PN-H2", motivo="ajuste")
    hist = F.listar_historico_part_number(item_id)
    assert len(hist) == 1
    assert hist[0]["pn_antigo"] == "PN-H1"
    assert hist[0]["pn_novo"] == "PN-H2"


def test_rejeita_pn_duplicado(db, make_item):
    make_item("PN-A")
    b = make_item("PN-B")
    ok, msg = F.alterar_part_number(b, "PN-A")
    assert ok is False
    assert F.buscar_item_por_id(b)["part_number"] == "PN-B"   # inalterado


def test_busca_por_pn_antigo(db, make_item):
    item_id = make_item("PN-ANT")
    F.alterar_part_number(item_id, "PN-ATU")
    achado = F.buscar_item_por_pn("PN-ANT")                   # busca pelo PN antigo
    assert achado is not None
    assert achado["id"] == item_id
    assert achado["part_number"] == "PN-ATU"


def test_rejeita_pn_igual_ou_vazio(db, make_item):
    item_id = make_item("PN-EQ")
    assert F.alterar_part_number(item_id, "PN-EQ")[0] is False
    assert F.alterar_part_number(item_id, "   ")[0] is False
