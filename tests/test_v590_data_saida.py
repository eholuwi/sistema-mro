"""v5.9.0 — data REAL da saída do material ("Material saindo agora" desmarcado).

A entrega gravava sempre `datetime.now()`. Material que saiu ontem e foi lançado hoje
caía no dia errado e distorcia consumo médio, ABC, giro e cobertura — todos calculados
sobre `movimentacoes.data_hora`.

O que este arquivo trava:
- retroativo grava a data informada em `movimentacoes.data_hora`;
- o padrão (sem `data_saida`) continua gravando agora — retrocompatível;
- data FUTURA é recusada (envenenaria as janelas `datetime('now','-N days')`);
- `requisicoes.data_hora` NÃO retroage (a numeração REQ-YYYYMMDD-NNN deriva dela);
- a janela de consumo de 30 dias enxerga o movimento na data retroagida.
"""

from datetime import datetime, timedelta

import pytest

import database
from services.db_functions import (
    criar_requisicao_com_baixa,
    entregar_requisicao,
    listar_itens_requisicao,
    validar_data_saida,
)

HOJE = datetime.now()
ONTEM = HOJE - timedelta(days=1)
DEZ_DIAS = HOJE - timedelta(days=10)


def _criar_requisicao_aberta(item_id, qtd=5.0):
    """Requisição SEM baixa (estoque zerado na criação) para entregar depois."""
    with database.transaction() as c:
        cur = c.execute(
            "INSERT INTO requisicoes (numero_requisicao,data_hora,setor,emitente,centro_custo,status) "
            "VALUES (?,?,?,?,?,?)",
            (
                "REQ-TESTE-1",
                HOJE.strftime("%Y-%m-%d %H:%M:%S"),
                "MANUTENÇÃO",
                "Joao",
                "21106 - MANUTENÇÃO",
                "Aberta",
            ),
        )
        req_id = cur.lastrowid
        c.execute(
            "INSERT INTO itens_requisicao (requisicao_id,item_id,quantidade_solicitada,quantidade_atendida) "
            "VALUES (?,?,?,0)",
            (req_id, item_id, qtd),
        )
    return req_id


def _movs(item_id):
    conn = database.get_connection()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT data_hora, quantidade, observacao FROM movimentacoes "
                "WHERE item_id=? AND tipo='saida' ORDER BY id",
                (item_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


# ── validar_data_saida (puro, sem banco) ─────────────────────────────────────


def test_validador_aceita_retroativo_e_recusa_futuro():
    agora = "2026-07-31 12:00:00"
    val, err = validar_data_saida("2026-07-30 08:00:00", agora)
    assert val == "2026-07-30 08:00:00" and err is None

    val, err = validar_data_saida("2026-08-01 08:00:00", agora)
    assert val is None and "futuro" in err

    # None = "saindo agora": passa direto, quem chama usa o próprio `agora`.
    assert validar_data_saida(None, agora) == (None, None)


def test_validador_aceita_datetime_e_data_sem_hora():
    agora = "2026-07-31 12:00:00"
    assert validar_data_saida(datetime(2026, 7, 30, 8, 0, 0), agora)[0] == "2026-07-30 08:00:00"
    assert validar_data_saida("2026-07-30", agora)[0] == "2026-07-30 00:00:00"
    assert validar_data_saida("não é data", agora)[1] is not None


# ── entregar_requisicao ──────────────────────────────────────────────────────


def test_entrega_retroativa_grava_a_data_informada(db, make_item):
    item = make_item("PN-RETRO", estoque=100)
    req_id = _criar_requisicao_aberta(item)
    itens = listar_itens_requisicao(req_id)

    ok, res = entregar_requisicao(
        req_id,
        [{"item_req_id": itens[0]["id"], "quantidade": 3.0}],
        "Gestor",
        "Neidson",
        data_saida=ONTEM,
    )
    assert ok, res

    mov = _movs(item)[-1]
    assert mov["data_hora"][:10] == ONTEM.strftime("%Y-%m-%d")
    # O instante do LANÇAMENTO fica registrado na observação (saldo_apos é do
    # lançamento, não do instante retroagido — quem lê o extrato precisa saber).
    assert "retroativa" in mov["observacao"]


def test_entrega_sem_data_grava_agora(db, make_item):
    """Comportamento padrão intocado — a assinatura é retrocompatível."""
    item = make_item("PN-AGORA", estoque=100)
    req_id = _criar_requisicao_aberta(item)
    itens = listar_itens_requisicao(req_id)

    ok, res = entregar_requisicao(
        req_id, [{"item_req_id": itens[0]["id"], "quantidade": 2.0}], "Gestor", "Neidson"
    )
    assert ok, res

    mov = _movs(item)[-1]
    assert mov["data_hora"][:10] == HOJE.strftime("%Y-%m-%d")
    assert "retroativa" not in mov["observacao"]


def test_data_futura_e_recusada_e_nada_e_gravado(db, make_item):
    item = make_item("PN-FUT", estoque=100)
    req_id = _criar_requisicao_aberta(item)
    itens = listar_itens_requisicao(req_id)

    ok, msg = entregar_requisicao(
        req_id,
        [{"item_req_id": itens[0]["id"], "quantidade": 1.0}],
        "Gestor",
        "Neidson",
        data_saida=HOJE + timedelta(days=1),
    )
    assert not ok and "futuro" in msg

    assert _movs(item) == []  # nenhuma saída gravada
    conn = database.get_connection()
    try:
        est = conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (item,)).fetchone()[0]
    finally:
        conn.close()
    assert est == 100  # estoque intocado


def test_requisicao_nao_retroage_so_a_movimentacao(db, make_item):
    """`_gerar_numero_requisicao` deriva REQ-YYYYMMDD-NNN da data da requisição:
    retroagi-la colidiria a numeração. Só o material carrega a data de saída."""
    item = make_item("PN-NUM", estoque=100)
    req_id = _criar_requisicao_aberta(item)
    itens = listar_itens_requisicao(req_id)

    ok, _ = entregar_requisicao(
        req_id,
        [{"item_req_id": itens[0]["id"], "quantidade": 1.0}],
        "Gestor",
        "Neidson",
        data_saida=DEZ_DIAS,
    )
    assert ok

    conn = database.get_connection()
    try:
        req = conn.execute("SELECT data_hora FROM requisicoes WHERE id=?", (req_id,)).fetchone()
    finally:
        conn.close()
    assert req["data_hora"][:10] == HOJE.strftime("%Y-%m-%d")
    assert _movs(item)[-1]["data_hora"][:10] == DEZ_DIAS.strftime("%Y-%m-%d")


def test_consumo_30d_enxerga_o_movimento_retroagido(db, make_item):
    """O ponto da mudança: o consumo passa a contar o material no dia em que saiu."""
    item = make_item("PN-CONS", estoque=100)
    req_id = _criar_requisicao_aberta(item, qtd=9.0)
    itens = listar_itens_requisicao(req_id)

    ok, _ = entregar_requisicao(
        req_id,
        [{"item_req_id": itens[0]["id"], "quantidade": 9.0}],
        "Gestor",
        "Neidson",
        data_saida=DEZ_DIAS,
    )
    assert ok

    conn = database.get_connection()
    try:
        total = conn.execute(
            "SELECT COALESCE(SUM(quantidade),0) FROM movimentacoes "
            "WHERE item_id=? AND tipo='saida' AND data_hora >= datetime('now','-30 days')",
            (item,),
        ).fetchone()[0]
        # `_recalcular_consumo` roda na baixa e materializa o consumo médio diário.
        cmd = conn.execute("SELECT consumo_medio_diario FROM inventario WHERE id=?", (item,)).fetchone()[0]
    finally:
        conn.close()
    assert total == 9.0
    assert (cmd or 0) > 0


# ── criar_requisicao_com_baixa (Requisição Padrão) ───────────────────────────


@pytest.mark.parametrize("data_saida,esperado", [(None, HOJE), (ONTEM, ONTEM)])
def test_requisicao_padrao_respeita_a_data_de_saida(db, make_item, data_saida, esperado):
    item = make_item("PN-PADRAO", estoque=50)
    ok, res = criar_requisicao_com_baixa(
        "MANUTENÇÃO",
        "Joao",
        "21106 - MANUTENÇÃO",
        "Gestor",
        "Neidson",
        False,
        "",
        False,
        "",
        [{"item_id": item, "quantidade_solicitada": 4.0}],
        data_saida=data_saida,
    )
    assert ok, res
    assert _movs(item)[-1]["data_hora"][:10] == esperado.strftime("%Y-%m-%d")
