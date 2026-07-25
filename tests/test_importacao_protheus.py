"""Golden (Fase 0): congela as regras de filtragem do importador Protheus
(o trecho mais complexo do sistema), protegendo todas as fases seguintes.
Usa a fixture xlsx_factory (correcoes A-1 e A-3)."""

from services import db_functions as F


def test_item_existente_cria_sc_e_marca_critico(db, make_item, xlsx_factory):
    make_item("PN-IMP", estoque=0, minimo=5)
    cols = [
        "Numero da Solicitacao",
        "Solicitante",
        "Produto",
        "Quantidade",
        "Status",
        "Justificativa/Projeto",
    ]
    rows = [["SC-IMP-1", "Jasiva Lopes", "PN-IMP", 10, "Pedido", "parada de linha"]]
    ok, stats = F.importar_solicitacoes_protheus(xlsx_factory(rows, cols), "teste.xlsx")
    assert ok, stats
    assert stats["linhas_importadas"] == 1
    assert stats["scs_criadas"] == 1
    assert stats["criticos"] == 1


def test_solicitante_fora_do_escopo_ignora(db, make_item, xlsx_factory):
    make_item("PN-IMP2")
    cols = ["Numero da Solicitacao", "Solicitante", "Produto", "Quantidade"]
    rows = [["SC-IMP-2", "Fulano Aleatorio", "PN-IMP2", 5]]
    ok, stats = F.importar_solicitacoes_protheus(xlsx_factory(rows, cols), "teste.xlsx")
    assert ok, stats
    assert stats["linhas_ignoradas"] == 1
    assert stats["linhas_importadas"] == 0


def test_item_inexistente_ignora(db, xlsx_factory):
    cols = ["Numero da Solicitacao", "Solicitante", "Produto", "Quantidade"]
    rows = [["SC-IMP-3", "Jasiva Lopes", "PN-NAO-EXISTE", 5]]
    ok, stats = F.importar_solicitacoes_protheus(xlsx_factory(rows, cols), "teste.xlsx")
    assert ok, stats
    assert stats["linhas_ignoradas"] == 1
    assert stats["linhas_importadas"] == 0
