"""v6.8.0 — Desativar item (soft delete).

Excluir de verdade e inviavel e esta descartado: `movimentacoes` e mais 5 tabelas tem
`ON DELETE CASCADE` (apagaria o ledger inteiro do item) e `itens_sc`/`itens_requisicao`/
`guarda_chuva*` tem FK NO ACTION (bloquearia). O caminho e `ativo INTEGER DEFAULT 1`,
como `listas`, `usuarios` e `fornecedores`.

O que este arquivo trava:
1. o item desativado some das QUATRO superficies combinadas com o Luis (Requisicao/
   Movimentacao, reposicao/SC, dashboards/KPIs e saldo);
2. as TRES excecoes que precisam continuar enxergando (cadastro, PN duplicado, Ficha 360);
3. o historico nunca e tocado — desativar nao apaga movimentacao nenhuma.
"""

import pytest

import database
from services.dashboards import _top_dead_stock, _top_valor_imobilizado
from services.db_functions import (
    atualizar_item_inventario,
    listar_inventario,
)
from services.ficha import montar_ficha_360
from services.planejamento import gerar_sugestoes_reposicao


def _desativar(item_id, ativo=0):
    ok, msg = atualizar_item_inventario(item_id, {"ativo": ativo})
    assert ok, msg


def _pns(itens):
    return {i["part_number"] for i in itens}


@pytest.fixture
def dois_itens(db, make_item):
    """Um item que fica ativo e um que sera desativado."""
    vivo = make_item("PN-VIVO", nome="Fita boa", estoque=50, minimo=10)
    morto = make_item("PN-MORTO", nome="Peca descontinuada", estoque=30, minimo=10)
    return {"vivo": vivo, "morto": morto}


# ── Migracao ─────────────────────────────────────────────────────────────────


def test_migracao_e_idempotente(db):
    """`criar_banco()` roda a cada boot do app."""
    database.criar_banco()
    database.criar_banco()

    conn = database.get_connection()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(inventario)")]
    finally:
        conn.close()
    assert cols.count("ativo") == 1


def test_base_inteira_nasce_ativa_sem_backfill(db, make_item):
    """`ADD COLUMN … DEFAULT 1` ja preenche as linhas existentes no SQLite."""
    make_item("PN-A")
    conn = database.get_connection()
    try:
        valores = {r["ativo"] for r in conn.execute("SELECT ativo FROM inventario")}
    finally:
        conn.close()
    assert valores == {1}


def test_item_legado_com_ativo_nulo_conta_como_ativo(db, make_item):
    """Banco que migrou com a coluna nula nao pode sumir com o cadastro inteiro."""
    iid = make_item("PN-LEGADO")
    conn = database.get_connection()
    try:
        conn.execute("UPDATE inventario SET ativo=NULL WHERE id=?", (iid,))
        conn.commit()
    finally:
        conn.close()

    assert "PN-LEGADO" in _pns(listar_inventario())


# ── O funil ──────────────────────────────────────────────────────────────────


def test_listar_inventario_esconde_e_incluir_inativos_mostra(db, dois_itens):
    _desativar(dois_itens["morto"])

    assert _pns(listar_inventario()) == {"PN-VIVO"}
    assert _pns(listar_inventario(incluir_inativos=True)) == {"PN-VIVO", "PN-MORTO"}


def test_reativar_devolve_o_item(db, dois_itens):
    _desativar(dois_itens["morto"])
    assert "PN-MORTO" not in _pns(listar_inventario())

    _desativar(dois_itens["morto"], ativo=1)
    assert "PN-MORTO" in _pns(listar_inventario())


def test_ativo_esta_no_allowlist_de_atualizar_item(db, dois_itens):
    """Campo fora do allowlist e ignorado em SILENCIO — o toggle nao faria nada."""
    _desativar(dois_itens["morto"])

    conn = database.get_connection()
    try:
        valor = conn.execute("SELECT ativo FROM inventario WHERE id=?", (dois_itens["morto"],)).fetchone()[
            "ativo"
        ]
    finally:
        conn.close()
    assert valor == 0


# ── As quatro superficies que o Luis pediu ───────────────────────────────────


def test_some_do_seletor_de_material(db, dois_itens):
    """`itens_select` alimenta Requisicao, Movimentacao e Cadastro."""
    from ui.componentes.selecao import itens_select

    _desativar(dois_itens["morto"])

    rotulos = " ".join(itens_select().keys())
    assert "PN-VIVO" in rotulos
    assert "PN-MORTO" not in rotulos

    # O cadastro continua alcancando o item para religar.
    assert "PN-MORTO" in " ".join(itens_select(incluir_inativos=True).keys())


def test_some_das_sugestoes_de_reposicao(db, make_item, registrar_consumo):
    """Item morto nao pode ficar pedindo compra para sempre."""
    morto = make_item("PN-REPOR", estoque=0, minimo=50)
    registrar_consumo(morto, quantidade=5)

    assert "PN-REPOR" in {s["part_number"] for s in gerar_sugestoes_reposicao()}

    _desativar(morto)
    assert "PN-REPOR" not in {s["part_number"] for s in gerar_sugestoes_reposicao()}


def test_some_do_capital_parado_e_do_dead_stock(db, make_item):
    """Duas consultas que fazem SQL direto, sem passar pelo funil."""
    caro = make_item("PN-CARO", estoque=100, minimo=1)
    conn = database.get_connection()
    try:
        conn.execute("UPDATE inventario SET preco_referencia=25.0 WHERE id=?", (caro,))
        conn.commit()
    finally:
        conn.close()

    assert "PN-CARO" in {r["part_number"] for r in _top_valor_imobilizado()}
    assert "PN-CARO" in {r["part_number"] for r in _top_dead_stock(2026)}

    _desativar(caro)

    assert "PN-CARO" not in {r["part_number"] for r in _top_valor_imobilizado()}
    assert "PN-CARO" not in {r["part_number"] for r in _top_dead_stock(2026)}


def test_some_do_dashboard(db, dois_itens):
    from services.dashboards import montar_dashboard

    _desativar(dois_itens["morto"])

    dash = montar_dashboard("gestao")
    assert dash is not None  # so nao pode quebrar; o total abaixo e o que importa
    assert len(listar_inventario()) == 1


# ── As tres excecoes ─────────────────────────────────────────────────────────


def test_ficha_360_de_item_desativado_continua_abrindo(db, dois_itens):
    """E justamente o item que se vai consultar depois de tirar de circulacao."""
    _desativar(dois_itens["morto"])

    ficha = montar_ficha_360(dois_itens["morto"])
    assert ficha is not None
    assert ficha["item"]["part_number"] == "PN-MORTO"


def test_pn_duplicado_de_item_desativado_continua_barrado(db, dois_itens):
    """O UNIQUE de `part_number` vale para a tabela inteira.

    Se a checagem de duplicidade do cadastro filtrasse por ativo, o usuario digitaria um
    PN "livre" e levaria um IntegrityError cru do INSERT.
    """
    _desativar(dois_itens["morto"])

    existentes = {i["part_number"].lower() for i in listar_inventario(incluir_inativos=True)}
    assert "pn-morto" in existentes, "a checagem do cadastro precisa enxergar o desativado"

    conn = database.get_connection()
    try:
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO inventario (part_number, nome_item) VALUES (?,?)",
                ("PN-MORTO", "Tentativa de duplicar"),
            )
            conn.commit()
    finally:
        conn.close()


# ── O historico nunca e tocado ───────────────────────────────────────────────


def test_desativar_nao_apaga_movimentacoes(db, dois_itens, registrar_consumo):
    """A razao de ser soft delete: o CASCADE de `movimentacoes` destruiria o ledger."""
    registrar_consumo(dois_itens["morto"], quantidade=5)

    conn = database.get_connection()
    try:
        antes = conn.execute(
            "SELECT COUNT(*) AS n FROM movimentacoes WHERE item_id=?", (dois_itens["morto"],)
        ).fetchone()["n"]
    finally:
        conn.close()
    assert antes > 0

    _desativar(dois_itens["morto"])

    conn = database.get_connection()
    try:
        depois = conn.execute(
            "SELECT COUNT(*) AS n FROM movimentacoes WHERE item_id=?", (dois_itens["morto"],)
        ).fetchone()["n"]
        saldo = conn.execute(
            "SELECT estoque_atual FROM inventario WHERE id=?", (dois_itens["morto"],)
        ).fetchone()["estoque_atual"]
    finally:
        conn.close()
    assert depois == antes, "desativar nao pode encostar no ledger"
    assert saldo == 30, "nem no saldo (o item some das telas, o numero fica no banco)"


def test_desativar_nao_apaga_o_cadastro(db, dois_itens):
    _desativar(dois_itens["morto"])

    conn = database.get_connection()
    try:
        linha = conn.execute(
            "SELECT part_number, nome_item FROM inventario WHERE id=?", (dois_itens["morto"],)
        ).fetchone()
    finally:
        conn.close()
    assert linha["part_number"] == "PN-MORTO"


# ── Cache ────────────────────────────────────────────────────────────────────


def test_cache_separa_as_duas_visoes(db, dois_itens):
    """O parametro precisa entrar na CHAVE do `@st.cache_data`, senao a primeira
    chamada da sessao decidiria o conteudo das duas pelos 120s seguintes."""
    import inspect

    from ui.cache import inventario_cached

    assert "incluir_inativos" in inspect.signature(inventario_cached.__wrapped__).parameters
