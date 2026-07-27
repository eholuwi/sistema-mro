"""v5.6.0 — Recebimento parcial por SC/PO: a chave do `data_editor` precisa ser versionada.

Contexto do bug (não era do MRO): no Streamlit 1.60.0 um `data_editor` com `key` e
`num_rows="fixed"` passou a ter identidade baseada na ASSINATURA DO SCHEMA (colunas,
tipos, nº de linhas) e não nos valores — "This keeps edits alive across pure value
changes". Com a `key` fixa que existia em `_receber_por_sc`, a quantidade digitada pelo
usuário sobrevivia ao rerun e era reaplicada sobre o pendente já atualizado: receber 4 de
10 mostrava 4 de novo em vez de 6, e um segundo clique recebia 4 outra vez. O recebimento
TOTAL escapava porque o item sai da lista e o nº de linhas muda.

A regressão é de UI, não de serviço — `registrar_recebimento_sc` está coberto por
`tests/test_recebimento_sc.py`. Aqui travamos o contrato da chave (puro, determinístico)
e o comportamento de estado que dependia dela.
"""

import pytest
from services import db_functions as F

from ui.componentes.tabela import chave_editor
from ui.paginas.movimentacao import chave_editor_recebimento

CC = "21194 - ALMOXARIFADO"


# ── Contrato da chave (puro) ──────────────────────────────────────────────────


def test_chave_muda_com_a_geracao():
    # O ponto do bug: após um recebimento a geração avança e o editor renasce limpo,
    # em vez de reaplicar a quantidade digitada no ciclo anterior.
    assert chave_editor_recebimento(7, 0) != chave_editor_recebimento(7, 1)


def test_chave_muda_entre_scs():
    # Sem isso, duas SCs com o mesmo nº de linhas e mesmo schema compartilham a
    # identidade do widget e as edições vazam de uma para a outra.
    assert chave_editor_recebimento(7, 0) != chave_editor_recebimento(8, 0)


def test_chave_estavel_para_a_mesma_sc_e_geracao():
    # Estabilidade importa: sem ela o editor seria recriado a cada rerun e o usuário
    # perderia o que digitou antes de confirmar.
    assert chave_editor_recebimento(7, 3) == chave_editor_recebimento(7, 3)


def test_chave_editor_reage_ao_conteudo_e_resume_listas_longas():
    # Usado pela sugestão de reposição: conjuntos filtrados diferentes → chaves diferentes.
    a = chave_editor("rep_sel_editor", ["PN-1", "PN-2"])
    b = chave_editor("rep_sel_editor", ["PN-1", "PN-3"])
    assert a != b
    assert chave_editor("rep_sel_editor", ["PN-1", "PN-2"]) == a
    # Lista longa vira hash curto — a chave não cresce sem limite.
    longa = chave_editor("rep_sel_editor", [f"PN-{i}" for i in range(200)])
    assert len(longa) < 60
    assert longa != chave_editor("rep_sel_editor", [f"PN-{i}" for i in range(199)])


def test_prefixo_preservado_para_a_limpeza_de_estado():
    # `_limpar_editores_recebimento` varre o session_state por este prefixo; se ele
    # mudar, o estado antigo deixa de ser descartado e cresce a cada SC visitada.
    assert chave_editor_recebimento(7, 0).startswith("rec_sc_editor__")


# ── Comportamento de ponta a ponta do parcial (serviço + releitura) ───────────


@pytest.fixture
def sc_com_item(db, make_item):
    """SC aberta com um item de 10 unidades pendentes."""
    item_id = make_item("PN-PARCIAL", estoque=0, minimo=5)
    ok, msg = F.criar_sc(
        "SC-PARCIAL-1",
        "2026-01-01",
        [
            {
                "item_id": item_id,
                "part_number": "PN-PARCIAL",
                "nome_item": "Item",
                "quantidade_solicitada": 10,
                "quantidade_pedido": 10,
            }
        ],
        "",
    )
    assert ok, msg
    conn = db.get_connection()
    sc_id = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc='SC-PARCIAL-1'").fetchone()["id"]
    conn.close()
    return sc_id, F.listar_itens_sc(sc_id)[0]["id"]


def test_parcial_sucessivo_consome_o_saldo_ate_fechar(db, sc_com_item):
    """O cenário exato relatado: 10 pendentes, recebe 4, depois os 6 restantes.

    Com o bug da chave fixa a UI reenviava 4 na segunda vez; aqui garantimos que a
    releitura entre recebimentos devolve o pendente ATUALIZADO, que é o valor que o
    editor passa a exibir quando renasce."""
    sc_id, item_sc_id = sc_com_item
    assert F.listar_itens_sc(sc_id)[0]["pendente"] == 10

    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 4, CC, "Alm", "Alm", "Forn X", "2026-01-10")
    assert ok, msg

    # É esta releitura que alimenta o `base` do data_editor no rerun seguinte.
    apos_parcial = F.listar_itens_sc(sc_id)[0]
    assert apos_parcial["pendente"] == 6, "o pendente precisa cair para 6 — o editor mostra este valor"
    assert apos_parcial["quantidade_recebida"] == 4

    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 6, CC, "Alm", "Alm", "Forn X", "2026-01-11")
    assert ok, msg
    final = F.listar_itens_sc(sc_id)[0]
    assert final["pendente"] == 0
    assert final["quantidade_recebida"] == 10


def test_reenviar_a_quantidade_antiga_excede_o_pendente_e_e_recusado(db, sc_com_item):
    """Prova de que o bug tinha consequência real: reenviar a quantidade do ciclo
    anterior quando ela passa do pendente é recusado pelo serviço — mas enquanto ela
    coubesse, a UI recebia a mais silenciosamente."""
    sc_id, item_sc_id = sc_com_item
    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 7, CC, "Alm", "Alm", "Forn X", "2026-01-10")
    assert ok, msg
    ok, msg = F.registrar_recebimento_sc(sc_id, item_sc_id, 7, CC, "Alm", "Alm", "Forn X", "2026-01-10")
    assert not ok, "receber 7 duas vezes (14 > 10) tem de ser recusado"
    assert F.listar_itens_sc(sc_id)[0]["quantidade_recebida"] == 7
