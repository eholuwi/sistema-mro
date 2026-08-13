"""v6.7.0 — Nota fiscal por recebimento no Guarda-Chuva.

Cada recebimento (item × mes) passa a carregar a NF daquela entrega. A NF fica no NIVEL
DA CELULA, nao do pedido: dois itens do mesmo acordo podem chegar no mesmo mes em notas
diferentes, e guardar uma NF por pedido perderia isso.

A invariante da v5.9.0 continua valendo e esta travada aqui de novo: registrar NF e
recebimento e CONTROLE, nao ledger — nao encosta em `inventario.estoque_atual` nem em
`movimentacoes`.
"""

import pytest

import database
from services.guarda_chuva import (
    atualizar_itens_gc,
    criar_pedido_gc,
    exportar_guarda_chuva_df,
    listar_pedidos_gc,
    obter_pedido_gc,
)


@pytest.fixture
def pedido(db, make_item):
    a = make_item("PN-NF-A", nome="Fita adesiva", estoque=10)
    b = make_item("PN-NF-B", nome="Pincel", estoque=20)
    ok, pid = criar_pedido_gc(
        "PO-NF-1",
        fornecedor_nome="FITAS FLAX",
        meses_acordo=2,
        itens=[
            {"item_id": a, "qtd_negociada": 500},
            {"item_id": b, "qtd_negociada": 100},
        ],
    )
    assert ok, pid
    return {"id": pid, "item_a": a, "item_b": b}


def _linhas(p, **por_pn):
    """Monta o payload de `atualizar_itens_gc` a partir do pedido lido."""
    saida = []
    for it in p["itens"]:
        dados = por_pn.get(it["part_number"].replace("-", "_"), {})
        saida.append(
            {
                "id": it["id"],
                "qtd_negociada": it.get("qtd_negociada") or 0,
                "qtd_prevista_mes": it.get("qtd_prevista_mes"),
                "preco_congelado": it.get("preco_congelado"),
                "recebimentos": dados.get("recebimentos", {}),
                "notas": dados.get("notas", {}),
            }
        )
    return saida


# ── Migracao ─────────────────────────────────────────────────────────────────


def test_migracao_adiciona_a_coluna_e_e_idempotente(db):
    """`criar_banco()` roda a cada boot — a coluna nao pode ser adicionada duas vezes."""
    database.criar_banco()
    database.criar_banco()

    conn = database.get_connection()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(guarda_chuva_recebimento)")]
    finally:
        conn.close()
    assert cols.count("nota_fiscal") == 1


def test_recebimento_legado_sem_nota_le_como_vazio(db, pedido):
    """Linha gravada antes da v6.7.0 tem `nota_fiscal` NULL — a tela nao pode quebrar."""
    conn = database.get_connection()
    try:
        gc_item = conn.execute(
            "SELECT id FROM guarda_chuva_item WHERE pedido_id=?", (pedido["id"],)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO guarda_chuva_recebimento (gc_item_id, mes_seq, quantidade) VALUES (?,?,?)",
            (gc_item, 1, 50.0),
        )
        conn.commit()
    finally:
        conn.close()

    p = obter_pedido_gc(pedido["id"])
    item = next(i for i in p["itens"] if i["id"] == gc_item)
    assert item["recebimentos"][1] == 50.0
    assert item["notas"][1] == ""


# ── Gravacao e leitura ───────────────────────────────────────────────────────


def test_grava_e_le_a_nf_por_celula(db, pedido):
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(
        pedido["id"],
        _linhas(
            p,
            PN_NF_A={"recebimentos": {1: 200, 2: 150}, "notas": {1: "1234", 2: "1250"}},
            PN_NF_B={"recebimentos": {1: 40}, "notas": {1: "1234"}},
        ),
    )

    p = obter_pedido_gc(pedido["id"])
    a = next(i for i in p["itens"] if i["part_number"] == "PN-NF-A")
    b = next(i for i in p["itens"] if i["part_number"] == "PN-NF-B")

    assert a["notas"] == {1: "1234", 2: "1250"}
    assert b["notas"] == {1: "1234"}
    assert a["recebimentos"] == {1: 200.0, 2: 150.0}


def test_dois_itens_no_mesmo_mes_podem_ter_notas_diferentes(db, pedido):
    """A razao de a NF ser por celula e nao por pedido."""
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(
        pedido["id"],
        _linhas(
            p,
            PN_NF_A={"recebimentos": {1: 200}, "notas": {1: "1234"}},
            PN_NF_B={"recebimentos": {1: 40}, "notas": {1: "9999-2"}},
        ),
    )

    p = obter_pedido_gc(pedido["id"])
    notas = {i["part_number"]: i["notas"][1] for i in p["itens"]}
    assert notas == {"PN-NF-A": "1234", "PN-NF-B": "9999-2"}


def test_nf_e_texto_livre(db, pedido):
    """Numero real vem com serie/letra/zeros a esquerda — nunca converter para numero."""
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(pedido["id"], _linhas(p, PN_NF_A={"recebimentos": {1: 10}, "notas": {1: "000123-1"}}))
    p = obter_pedido_gc(pedido["id"])
    a = next(i for i in p["itens"] if i["part_number"] == "PN-NF-A")
    assert a["notas"][1] == "000123-1"


def test_nf_em_branco_vira_nulo_e_nao_string_vazia(db, pedido):
    """Espaco em branco digitado por engano nao pode virar 'NF cadastrada'."""
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(pedido["id"], _linhas(p, PN_NF_A={"recebimentos": {1: 10}, "notas": {1: "   "}}))

    conn = database.get_connection()
    try:
        guardado = conn.execute(
            "SELECT nota_fiscal FROM guarda_chuva_recebimento WHERE mes_seq=1 AND quantidade=10"
        ).fetchone()["nota_fiscal"]
    finally:
        conn.close()
    assert guardado is None


def test_nf_pode_ser_lancada_antes_da_quantidade(db, pedido):
    """A nota chega, a conferencia fisica ainda nao. Iterar so por `recebimentos`
    descartaria a NF solta em silencio."""
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(pedido["id"], _linhas(p, PN_NF_A={"recebimentos": {}, "notas": {2: "5555"}}))

    p = obter_pedido_gc(pedido["id"])
    a = next(i for i in p["itens"] if i["part_number"] == "PN-NF-A")
    assert a["notas"][2] == "5555"
    assert a["recebimentos"][2] == 0.0


def test_editar_a_nf_sobrescreve_sem_duplicar_linha(db, pedido):
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(pedido["id"], _linhas(p, PN_NF_A={"recebimentos": {1: 10}, "notas": {1: "1111"}}))
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(pedido["id"], _linhas(p, PN_NF_A={"recebimentos": {1: 10}, "notas": {1: "2222"}}))

    conn = database.get_connection()
    try:
        linhas = conn.execute(
            "SELECT nota_fiscal FROM guarda_chuva_recebimento WHERE mes_seq=1 AND quantidade=10"
        ).fetchall()
    finally:
        conn.close()
    assert len(linhas) == 1 and linhas[0]["nota_fiscal"] == "2222"


def test_salvar_nao_apaga_nf_de_outro_mes(db, pedido):
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(
        pedido["id"],
        _linhas(p, PN_NF_A={"recebimentos": {1: 10, 2: 20}, "notas": {1: "1111", 2: "2222"}}),
    )
    p = obter_pedido_gc(pedido["id"])
    a = next(i for i in p["itens"] if i["part_number"] == "PN-NF-A")
    assert a["notas"] == {1: "1111", 2: "2222"}


# ── Saldo e invariante de ledger ─────────────────────────────────────────────


def test_nf_nao_altera_saldo_do_acordo(db, pedido):
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(pedido["id"], _linhas(p, PN_NF_A={"recebimentos": {1: 200}, "notas": {1: "1234"}}))

    p = obter_pedido_gc(pedido["id"])
    a = next(i for i in p["itens"] if i["part_number"] == "PN-NF-A")
    assert a["qtd_recebida"] == 200.0
    assert a["saldo_residual"] == 300.0


def test_continua_sendo_controle_e_nao_ledger(db, pedido):
    """Invariante da v5.9.0: nao encosta em estoque nem em movimentacoes."""
    conn = database.get_connection()
    try:
        antes = conn.execute(
            "SELECT estoque_atual FROM inventario WHERE id=?", (pedido["item_a"],)
        ).fetchone()["estoque_atual"]
        movs_antes = conn.execute("SELECT COUNT(*) AS n FROM movimentacoes").fetchone()["n"]
    finally:
        conn.close()

    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(pedido["id"], _linhas(p, PN_NF_A={"recebimentos": {1: 200}, "notas": {1: "1234"}}))

    conn = database.get_connection()
    try:
        depois = conn.execute(
            "SELECT estoque_atual FROM inventario WHERE id=?", (pedido["item_a"],)
        ).fetchone()["estoque_atual"]
        movs_depois = conn.execute("SELECT COUNT(*) AS n FROM movimentacoes").fetchone()["n"]
    finally:
        conn.close()
    assert depois == antes and movs_depois == movs_antes


# ── Kanban e exportacao ──────────────────────────────────────────────────────


def test_cartao_do_kanban_lista_as_nfs_distintas(db, pedido):
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(
        pedido["id"],
        _linhas(
            p,
            PN_NF_A={"recebimentos": {1: 200, 2: 150}, "notas": {1: "1234", 2: "1250"}},
            PN_NF_B={"recebimentos": {1: 40}, "notas": {1: "1234"}},  # repetida de proposito
        ),
    )

    card = next(x for x in listar_pedidos_gc() if x["id"] == pedido["id"])
    assert card["notas_fiscais"] == ["1234", "1250"], "distintas e ordenadas"


def test_cartao_sem_nf_traz_lista_vazia(db, pedido):
    card = next(x for x in listar_pedidos_gc() if x["id"] == pedido["id"])
    assert card["notas_fiscais"] == []


def test_exportacao_traz_a_nf_ao_lado_de_cada_mes(db, pedido):
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(
        pedido["id"],
        _linhas(p, PN_NF_A={"recebimentos": {1: 200, 2: 150}, "notas": {1: "1234", 2: "1250"}}),
    )

    df = exportar_guarda_chuva_df()
    colunas = list(df.columns)
    assert colunas.index("NF 1º mês") == colunas.index("1º mês") + 1, "NF logo apos o mes"
    assert colunas.index("NF 2º mês") == colunas.index("2º mês") + 1

    linha = df[df["PN"] == "PN-NF-A"].iloc[0]
    assert linha["NF 1º mês"] == "1234"
    assert linha["NF 2º mês"] == "1250"


def test_exportacao_sem_nf_traz_coluna_vazia_e_nao_nan(db, pedido):
    """`NaN` numa coluna de texto vira 'nan' no Excel e parece nota fiscal de verdade."""
    df = exportar_guarda_chuva_df()
    assert (df["NF 1º mês"] == "").all()
