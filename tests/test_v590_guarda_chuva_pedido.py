"""v5.9.0 — Guarda-Chuva por PEDIDO DE COMPRA: modelo, serviço e migração.

O modelo antigo (v4.9.0) tratava o acordo como (material × fornecedor) e `numero_po` era
texto que nada lia. Aqui o pedido é a entidade, com N itens e recebimento mês a mês.

A invariante que este arquivo existe para travar: **é controle, não ledger** — registrar
recebimento abate o saldo do ACORDO e não encosta em `inventario.estoque_atual` nem em
`movimentacoes`. O caption da tela promete isso ao usuário; o teste garante.
"""

import pytest

import database
from services.guarda_chuva import (
    adicionar_item_gc,
    atualizar_itens_gc,
    atualizar_pedido_gc,
    criar_pedido_gc,
    exportar_guarda_chuva_df,
    listar_pedidos_gc,
    normalizar_meses,
    obter_pedido_gc,
    remover_item_gc,
    remover_pedido_gc,
)


@pytest.fixture
def pedido(db, make_item):
    """Pedido com 2 itens, como viria da API."""
    a = make_item("PN-GC-A", nome="Fita adesiva", estoque=10)
    b = make_item("PN-GC-B", nome="Pincel", estoque=20)
    ok, pid = criar_pedido_gc(
        "F63955",
        numero_sc="41079",
        fornecedor_codigo="97290",
        fornecedor_nome="FITAS FLAX",
        meses_acordo=2,
        origem="api",
        itens=[
            {"item_id": a, "qtd_negociada": 216, "preco_congelado": 9.75},
            {"item_id": b, "qtd_negociada": 100, "preco_congelado": 5.30},
        ],
    )
    assert ok, pid
    return {"id": pid, "item_a": a, "item_b": b}


# ── Migração / schema ────────────────────────────────────────────────────────


def test_migracao_cria_as_tres_tabelas_e_e_idempotente(db):
    """`criar_banco()` 2× não pode duplicar nem perder dado (roda a cada boot do app)."""
    ok, pid = criar_pedido_gc("PO-IDEM", meses_acordo=3)
    assert ok

    database.criar_banco()  # 2ª execução — idempotente

    conn = database.get_connection()
    try:
        tabelas = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'guarda_chuva%'"
            )
        }
        n = conn.execute("SELECT COUNT(*) FROM guarda_chuva_pedido").fetchone()[0]
    finally:
        conn.close()
    assert tabelas >= {
        "guarda_chuva",  # a tabela ANTIGA continua existindo (aditiva, nada migrou)
        "guarda_chuva_pedido",
        "guarda_chuva_item",
        "guarda_chuva_recebimento",
    }
    assert n == 1
    assert obter_pedido_gc(pid)["numero_pedido"] == "PO-IDEM"


def _dropar_tabelas_novas(conn):
    """Volta o banco ao estado pré-v5.9.0 (só as tabelas novas somem)."""
    for t in ("guarda_chuva_recebimento", "guarda_chuva_item", "guarda_chuva_pedido"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.commit()


def test_migracao_faz_backup_antes_de_criar_em_banco_com_dados(db, make_item):
    """Regra do projeto: nenhuma alteração de schema sem backup.

    O backup sai UMA vez — na criação real das tabelas, num banco que já tem dados.
    Nos boots seguintes as tabelas já existem e nada é copiado (senão cada abertura do
    app geraria um .bak)."""
    import os

    make_item("PN-BK")
    conn = database.get_connection()
    try:
        _dropar_tabelas_novas(conn)
    finally:
        conn.close()

    dir_bk = database.diretorio_backups()
    antes = len(os.listdir(dir_bk)) if os.path.isdir(dir_bk) else 0

    database.criar_banco()  # aqui a migração de fato cria as tabelas
    depois = os.listdir(dir_bk) if os.path.isdir(dir_bk) else []
    assert len(depois) == antes + 1
    assert any("guarda-chuva-pedido-v590" in n for n in depois)

    database.criar_banco()  # 2ª vez: tabelas já existem → nenhum backup novo
    assert len(os.listdir(dir_bk)) == antes + 1


def test_rollback_da_migracao_preserva_o_banco(db, make_item):
    """Rollback testado: derrubar as tabelas novas devolve o banco ao estado anterior,
    com os dados operacionais e o Guarda-Chuva ANTIGO intactos."""
    from services.db_functions import criar_guarda_chuva, listar_guarda_chuva

    item = make_item("PN-RB", estoque=42)
    criar_guarda_chuva(item, "FORN-RB", qtd_negociada=7)
    criar_pedido_gc("PO-RB", itens=[{"item_id": item, "qtd_negociada": 5}])

    conn = database.get_connection()
    try:
        _dropar_tabelas_novas(conn)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (item,)).fetchone()[0] == 42
    finally:
        conn.close()
    assert len(listar_guarda_chuva()) == 1  # acordo antigo sobreviveu

    database.criar_banco()  # e a migração roda de novo, limpa
    assert listar_pedidos_gc() == []


def test_tabela_antiga_preservada(db, make_item):
    """A `guarda_chuva` da v4.9.0 não é tocada — só deixa de ser exibida."""
    from services.db_functions import criar_guarda_chuva, listar_guarda_chuva

    item = make_item("PN-VELHO")
    ok, _ = criar_guarda_chuva(item, "FORN-1", qtd_negociada=50)
    assert ok
    criar_pedido_gc("PO-NOVO")
    assert len(listar_guarda_chuva()) == 1  # o acordo antigo segue lá


# ── CRUD do pedido ───────────────────────────────────────────────────────────


def test_criar_pedido_com_itens_e_ler_de_volta(pedido):
    p = obter_pedido_gc(pedido["id"])
    assert p["numero_pedido"] == "F63955"
    assert p["numero_sc"] == "41079"
    assert p["fornecedor_nome"] == "FITAS FLAX"
    assert p["origem"] == "api"
    assert len(p["itens"]) == 2
    assert {i["part_number"] for i in p["itens"]} == {"PN-GC-A", "PN-GC-B"}


def test_numero_de_pedido_e_unico(pedido):
    ok, msg = criar_pedido_gc("F63955")
    assert not ok and "já está" in msg


def test_pedido_sem_numero_e_recusado(db):
    ok, msg = criar_pedido_gc("   ")
    assert not ok and "número" in msg


def test_atualizar_cabecalho(pedido):
    ok, _ = atualizar_pedido_gc(
        pedido["id"], {"estagio": "NF Emitida", "fornecedor_nome": "OUTRO", "meses_acordo": 6}
    )
    assert ok
    p = obter_pedido_gc(pedido["id"])
    assert p["estagio"] == "NF Emitida"
    assert p["fornecedor_nome"] == "OUTRO"
    assert p["meses_acordo"] == 6


def test_remover_pedido_leva_itens_e_recebimentos(pedido):
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(
        pedido["id"],
        [{"id": p["itens"][0]["id"], "qtd_negociada": 216, "recebimentos": {1: 10}}],
    )
    ok, _ = remover_pedido_gc(pedido["id"])
    assert ok
    assert obter_pedido_gc(pedido["id"]) is None

    conn = database.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM guarda_chuva_item").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM guarda_chuva_recebimento").fetchone()[0] == 0
    finally:
        conn.close()


# ── Itens, recebimento por mês e saldo derivado ──────────────────────────────


def test_recebimento_por_mes_e_saldo_derivado(pedido):
    p = obter_pedido_gc(pedido["id"])
    it_a = next(i for i in p["itens"] if i["part_number"] == "PN-GC-A")

    ok, _ = atualizar_itens_gc(
        pedido["id"],
        [
            {
                "id": it_a["id"],
                "qtd_negociada": 216,
                "qtd_prevista_mes": 108,
                "preco_congelado": 9.75,
                "recebimentos": {1: 100, 2: 50},
            }
        ],
    )
    assert ok

    p = obter_pedido_gc(pedido["id"])
    it_a = next(i for i in p["itens"] if i["part_number"] == "PN-GC-A")
    assert it_a["recebimentos"] == {1: 100.0, 2: 50.0}
    assert it_a["qtd_recebida"] == 150.0
    assert it_a["saldo_residual"] == 66.0  # 216 − 150, derivado na leitura


def test_regravar_o_mesmo_mes_substitui_nao_soma(pedido):
    """O editor manda a tabela inteira a cada salvamento — o mês tem que ser upsert."""
    p = obter_pedido_gc(pedido["id"])
    gid = p["itens"][0]["id"]
    for qtd in (30, 45):
        atualizar_itens_gc(pedido["id"], [{"id": gid, "qtd_negociada": 216, "recebimentos": {1: qtd}}])
    p = obter_pedido_gc(pedido["id"])
    assert next(i for i in p["itens"] if i["id"] == gid)["recebimentos"] == {1: 45.0}


def test_atualizar_itens_ignora_linha_de_outro_pedido(pedido, db):
    """Guarda contra id forjado/estale: só grava itens que são DESTE pedido."""
    ok, outro = criar_pedido_gc("PO-OUTRO")
    assert ok
    p = obter_pedido_gc(pedido["id"])
    alheio = p["itens"][0]["id"]

    atualizar_itens_gc(outro, [{"id": alheio, "qtd_negociada": 999, "recebimentos": {1: 999}}])

    p = obter_pedido_gc(pedido["id"])
    assert next(i for i in p["itens"] if i["id"] == alheio)["qtd_negociada"] == 216
    assert next(i for i in p["itens"] if i["id"] == alheio)["qtd_recebida"] == 0


def test_adicionar_e_remover_item_manualmente(pedido, make_item):
    novo = make_item("PN-GC-C", nome="Caneta")
    ok, _ = adicionar_item_gc(pedido["id"], novo, qtd_negociada=12)
    assert ok
    assert len(obter_pedido_gc(pedido["id"])["itens"]) == 3

    ok, msg = adicionar_item_gc(pedido["id"], novo)  # repetido
    assert not ok and "já está" in msg

    gid = next(i["id"] for i in obter_pedido_gc(pedido["id"])["itens"] if i["item_id"] == novo)
    ok, _ = remover_item_gc(gid)
    assert ok
    assert len(obter_pedido_gc(pedido["id"])["itens"]) == 2


def test_totais_do_pedido_na_listagem(pedido):
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(
        pedido["id"],
        [{"id": i["id"], "qtd_negociada": i["qtd_negociada"], "recebimentos": {1: 10}} for i in p["itens"]],
    )
    lista = listar_pedidos_gc()
    linha = next(x for x in lista if x["numero_pedido"] == "F63955")
    assert linha["n_itens"] == 2
    assert linha["qtd_negociada"] == 316.0  # 216 + 100
    assert linha["qtd_recebida"] == 20.0  # 10 + 10
    assert linha["saldo_residual"] == 296.0


@pytest.mark.parametrize(
    "entrada,esperado", [(0, 1), (1, 1), (2, 2), (12, 12), (99, 12), ("x", 2), (None, 2)]
)
def test_meses_do_acordo_ficam_entre_1_e_12(entrada, esperado):
    assert normalizar_meses(entrada) == esperado


# ── A invariante: controle, NÃO ledger ───────────────────────────────────────


def test_recebimento_nao_toca_estoque_nem_movimentacoes(pedido):
    """A regra que a tela promete em letras maiúsculas — travada aqui."""
    conn = database.get_connection()
    try:
        estoque_antes = dict(conn.execute("SELECT id, estoque_atual FROM inventario").fetchall())
        movs_antes = conn.execute("SELECT COUNT(*) FROM movimentacoes").fetchone()[0]
    finally:
        conn.close()

    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(
        pedido["id"],
        [
            {"id": i["id"], "qtd_negociada": i["qtd_negociada"], "recebimentos": {1: 50, 2: 25}}
            for i in p["itens"]
        ],
    )

    conn = database.get_connection()
    try:
        estoque_depois = dict(conn.execute("SELECT id, estoque_atual FROM inventario").fetchall())
        movs_depois = conn.execute("SELECT COUNT(*) FROM movimentacoes").fetchone()[0]
    finally:
        conn.close()
    assert estoque_depois == estoque_antes
    assert movs_depois == movs_antes


# ── Exportação ───────────────────────────────────────────────────────────────


def test_exportacao_achata_itens_com_uma_coluna_por_mes(pedido):
    p = obter_pedido_gc(pedido["id"])
    atualizar_itens_gc(
        pedido["id"],
        [{"id": p["itens"][0]["id"], "qtd_negociada": 216, "recebimentos": {1: 100, 2: 16}}],
    )
    df = exportar_guarda_chuva_df()
    assert len(df) == 2  # uma linha por item
    assert {"Nº Pedido", "SC", "Cód. Fornecedor", "Fornecedor", "PN", "Produto"} <= set(df.columns)
    assert {"1º mês", "2º mês", "Total Recebido", "Saldo", "Estágio"} <= set(df.columns)
    linha = df[df["PN"] == "PN-GC-A"].iloc[0]
    assert linha["1º mês"] == 100.0 and linha["2º mês"] == 16.0
    assert linha["Total Recebido"] == 116.0 and linha["Saldo"] == 100.0


def test_exportacao_usa_o_maior_numero_de_meses(pedido):
    """Pedidos de 2 e de 6 meses convivendo → planilha retangular de 6 colunas."""
    criar_pedido_gc("PO-6M", meses_acordo=6)
    df = exportar_guarda_chuva_df()
    assert "6º mês" in df.columns


def test_exportacao_sem_dados_devolve_df_vazio(db):
    assert exportar_guarda_chuva_df().empty


# ── Smoke da UI (o dialog só renderiza com o estado ligado) ──────────────────


def test_tela_e_dialog_do_pedido_renderizam(pedido):
    """O smoke por rota do router roda com banco vazio e nunca entra no dialog.

    Aqui a tela renderiza COM pedido cadastrado e com o dialog aberto — que é onde vive
    o `data_editor` de colunas dinâmicas, o ponto mais frágil da tela."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string("from ui.router import render_pagina\nrender_pagina('Controle de SC')\n")
    at.session_state["_gc_pedido_edit"] = pedido["id"]
    at.run(timeout=60)
    assert not at.exception, [e.value for e in at.exception]
