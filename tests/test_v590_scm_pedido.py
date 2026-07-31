"""v5.9.0 — parser do Pedido de Compra da API do SCM (`/Pedidos/ByNumero`).

O payload abaixo é o SHAPE REAL capturado da API em produção antes de escrever o parser
(pedido F63955, filial 01) — nomes de campo, padding de espaços do Protheus e tudo. Os
valores foram trocados por dados fictícios: o repositório é público.

Achado que o plano não previa: **o pedido NÃO traz o número da SC**. O vínculo é o
`C7_XPEDSCM` (código da cotação), que casa com `solicitacoes_compra.cotacao_codigo`.
"""

import database
from services.scm_pedido import (
    filtrar_itens_mro,
    normalizar_itens_pedido_api,
    resolver_numero_sc,
)

# Shape real da API: LISTA achatada, cabeçalho repetido em cada linha, campos com padding.
PAYLOAD = [
    {
        "A2_NOME": "FORNECEDOR TESTE LTDA                    ",
        "B1_TIPO": "07",
        "C7_DESCRI": "FITA 72MMX100MT, ROHS          ",
        "C7_EMISSAO": "20260623",
        "C7_FILIAL": "01",
        "C7_FORNECE": "97290 ",
        "C7_ITEM": "0001",
        "C7_LOJA": "01",
        "C7_MOEDA": 1.0,
        "C7_NUM": "F99001",
        "C7_PRECO": 9.75,
        "C7_PRODUTO": "PN-API-1       ",
        "C7_QUANT": 216.0,
        "C7_TOTAL": 2106.0,
        "C7_UM": "PC    ",
        "C7_XPEDSCM": "CT41079             ",
        "USR_NOME": "Comprador Teste                    ",
        "CUSTO": None,
        "Z0G_OBS": None,
    },
    {
        "A2_NOME": "FORNECEDOR TESTE LTDA                    ",
        "C7_DESCRI": "PINCEL MARCADOR AZUL           ",
        "C7_FORNECE": "97290 ",
        "C7_ITEM": "0002",
        "C7_NUM": "F99001",
        "C7_PRECO": 1.30,
        "C7_PRODUTO": "PN-FORA-MRO    ",
        "C7_QUANT": 100.0,
        "C7_TOTAL": 130.0,
        "C7_UM": "UN    ",
        "C7_XPEDSCM": "CT41079             ",
    },
]


def test_parser_le_cabecalho_e_itens_do_payload_real():
    cab, itens = normalizar_itens_pedido_api(PAYLOAD)

    assert cab["numero_pedido"] == "F99001"
    assert cab["fornecedor_codigo"] == "97290"  # padding do Protheus removido
    assert cab["fornecedor_nome"] == "FORNECEDOR TESTE LTDA"
    assert cab["cotacao_codigo"] == "CT41079"
    assert cab["comprador"] == "Comprador Teste"

    assert len(itens) == 2
    assert itens[0]["part_number"] == "PN-API-1"  # sem padding
    assert itens[0]["quantidade"] == 216.0
    assert itens[0]["unidade"] == "PC"
    assert itens[0]["preco_unitario"] == 9.75
    assert itens[0]["valor_total"] == 2106.0


def test_parser_degrada_quando_falta_campo():
    """Campo ausente vira vazio/0 — nunca KeyError. A API pode mudar; a tela não pode cair."""
    cab, itens = normalizar_itens_pedido_api([{"C7_PRODUTO": "PN-X", "C7_NUM": "F1"}])
    assert cab["numero_pedido"] == "F1"
    assert cab["fornecedor_nome"] == ""
    assert itens[0]["quantidade"] == 0.0
    assert itens[0]["unidade"] == ""


def test_parser_ignora_linha_sem_produto():
    _, itens = normalizar_itens_pedido_api([{"C7_NUM": "F1", "C7_PRODUTO": "   "}])
    assert itens == []


def test_parser_aceita_envelope_com_lista_dentro():
    """Robustez: se a API passar a envelopar, o parser continua achando os itens."""
    _, itens = normalizar_itens_pedido_api({"items": PAYLOAD})
    assert len(itens) == 2


def test_parser_com_payload_invalido_nao_quebra():
    assert normalizar_itens_pedido_api(None) == ({}, [])
    assert normalizar_itens_pedido_api("texto") == ({}, [])
    assert normalizar_itens_pedido_api([1, 2, 3]) == ({}, [])


def test_filtro_mro_separa_e_reporta_descartados(db, make_item):
    """Item fora do inventário é LISTADO como descartado, não silenciado."""
    make_item("PN-API-1", nome="Fita adesiva")
    _, itens = normalizar_itens_pedido_api(PAYLOAD)
    mro, descartados = filtrar_itens_mro(itens)

    assert [i["part_number"] for i in mro] == ["PN-API-1"]
    assert mro[0]["nome_item"] == "Fita adesiva"
    assert "item_id" in mro[0]
    assert [i["part_number"] for i in descartados] == ["PN-FORA-MRO"]


def test_resolver_numero_sc_pelo_codigo_da_cotacao(db):
    """O pedido não traz a SC; o elo é o código da cotação (C7_XPEDSCM)."""
    with database.transaction() as c:
        c.execute(
            "INSERT INTO solicitacoes_compra (numero_sc,data_abertura,status,cotacao_codigo) "
            "VALUES ('41079','2026-06-01','Em Cotação','CT41079')"
        )
    assert resolver_numero_sc("CT41079             ") == "41079"
    assert resolver_numero_sc("CT-INEXISTENTE") is None
    assert resolver_numero_sc("") is None
    assert resolver_numero_sc(None) is None
