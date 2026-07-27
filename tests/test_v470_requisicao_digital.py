"""v4.7.0 — Requisição Digital: fluxo estendido além do núcleo criação+entrega
(que fica em test_requisicao.py): adicionar item a um pedido aberto (o caso 'escreve
no mesmo papel'), remover item, cancelar, a regra SESMT e a fila de separação.
"""

from services import db_functions as F

CC = "21106 - MANUTENÇÃO"


def _req_id(db, numero):
    conn = db.get_connection()
    row = conn.execute("SELECT id FROM requisicoes WHERE numero_requisicao=?", (numero,)).fetchone()
    conn.close()
    return row["id"]


def _status(db, rid):
    conn = db.get_connection()
    row = conn.execute("SELECT status FROM requisicoes WHERE id=?", (rid,)).fetchone()
    conn.close()
    return row["status"]


def _criar(item_id, qtd=10):
    return F.criar_requisicao(
        "Manut",
        "Joao",
        CC,
        "",
        "",
        False,
        [],
        False,
        "",
        [{"item_id": item_id, "quantidade_solicitada": qtd}],
    )


# ── Adicionar itens ao pedido aberto ('põe no mesmo papel') ──────────────────


def test_adicionar_item_a_requisicao_aberta(db, make_item):
    a = make_item("PN-ADD-A", estoque=50)
    b = make_item("PN-ADD-B", estoque=50)
    ok, num = _criar(a, 5)
    rid = _req_id(db, num)
    ok, msg = F.adicionar_itens_requisicao(rid, [{"item_id": b, "quantidade_solicitada": 3}])
    assert ok, msg
    assert len(F.listar_itens_requisicao(rid)) == 2
    assert _status(db, rid) == "Aberta"


def test_adicionar_item_apos_entrega_parcial(db, make_item):
    a = make_item("PN-ADD-C", estoque=50)
    b = make_item("PN-ADD-D", estoque=50)
    ok, num = _criar(a, 10)
    rid = _req_id(db, num)
    it_id = F.listar_itens_requisicao(rid)[0]["id"]
    F.entregar_requisicao(rid, [{"item_req_id": it_id, "quantidade": 4}], "Gestor", "Chefe")
    assert _status(db, rid) == "Parcial"
    ok, msg = F.adicionar_itens_requisicao(rid, [{"item_id": b, "quantidade_solicitada": 2}])
    assert ok, msg
    assert len(F.listar_itens_requisicao(rid)) == 2


def test_adicionar_item_em_requisicao_entregue_reabre_como_parcial(db, make_item):
    """v5.7.0 (decisão nº4 de 27/07/2026) — REESCRITO: até a v5.6.0 este teste afirmava o
    contrário (`assert ok is False`), travando a guarda que recusava requisição Entregue.

    A operação real é 'escreve no mesmo papel': o solicitante volta com mais um item no
    mesmo pedido. Recusar obrigava a abrir requisição nova e quebrava o vínculo. Agora a
    requisição REABRE como `Parcial` e volta à fila — reabrir sem recalcular o status
    deixaria o item órfão, invisível e não entregável."""
    a = make_item("PN-ADD-E", estoque=50)
    b = make_item("PN-ADD-F", estoque=50)
    ok, num = _criar(a, 5)
    rid = _req_id(db, num)
    it_id = F.listar_itens_requisicao(rid)[0]["id"]
    F.entregar_requisicao(rid, [{"item_req_id": it_id, "quantidade": 5}], "Gestor", "Chefe")
    assert _status(db, rid) == "Entregue"
    assert rid not in [r["id"] for r in F.listar_requisicoes_abertas()]

    ok, msg = F.adicionar_itens_requisicao(rid, [{"item_id": b, "quantidade_solicitada": 2}])
    assert ok, msg
    assert _status(db, rid) == "Parcial", "a requisição precisa reabrir, não continuar Entregue"
    assert len(F.listar_itens_requisicao(rid)) == 2
    # A metade que importa: sem o UPDATE do status ela não reapareceria aqui.
    assert rid in [r["id"] for r in F.listar_requisicoes_abertas()]


def test_requisicao_cancelada_continua_recusando_item(db, make_item):
    """A guarda não foi removida, só estreitada: em Cancelada não há o que reabrir."""
    a = make_item("PN-ADD-G", estoque=50)
    b = make_item("PN-ADD-H", estoque=50)
    ok, num = _criar(a, 5)
    rid = _req_id(db, num)
    F.cancelar_requisicao(rid)
    assert _status(db, rid) == "Cancelada"
    ok, msg = F.adicionar_itens_requisicao(rid, [{"item_id": b, "quantidade_solicitada": 2}])
    assert ok is False
    assert "Cancelada" in msg
    assert _status(db, rid) == "Cancelada"


# ── Remover item ─────────────────────────────────────────────────────────────


def test_remover_item_nao_atendido(db, make_item):
    a = make_item("PN-RM-A", estoque=50)
    b = make_item("PN-RM-B", estoque=50)
    ok, num = F.criar_requisicao(
        "Manut",
        "Joao",
        CC,
        "",
        "",
        False,
        [],
        False,
        "",
        [{"item_id": a, "quantidade_solicitada": 5}, {"item_id": b, "quantidade_solicitada": 3}],
    )
    rid = _req_id(db, num)
    it0 = F.listar_itens_requisicao(rid)[0]["id"]
    ok, msg = F.remover_item_requisicao(it0)
    assert ok, msg
    assert len(F.listar_itens_requisicao(rid)) == 1


def test_nao_remove_item_ja_entregue(db, make_item):
    a = make_item("PN-RM-C", estoque=50)
    ok, num = _criar(a, 10)
    rid = _req_id(db, num)
    it_id = F.listar_itens_requisicao(rid)[0]["id"]
    F.entregar_requisicao(rid, [{"item_req_id": it_id, "quantidade": 4}], "Gestor", "Chefe")
    ok, msg = F.remover_item_requisicao(it_id)
    assert ok is False


# ── Cancelar ─────────────────────────────────────────────────────────────────


def test_cancelar_requisicao_aberta(db, make_item):
    a = make_item("PN-CAN-A", estoque=50)
    ok, num = _criar(a, 5)
    rid = _req_id(db, num)
    ok, msg = F.cancelar_requisicao(rid)
    assert ok, msg
    assert _status(db, rid) == "Cancelada"
    assert F.buscar_item_por_id(a)["estoque_atual"] == 50  # nada baixado


def test_nao_cancela_apos_entrega_parcial(db, make_item):
    a = make_item("PN-CAN-B", estoque=50)
    ok, num = _criar(a, 10)
    rid = _req_id(db, num)
    it_id = F.listar_itens_requisicao(rid)[0]["id"]
    F.entregar_requisicao(rid, [{"item_req_id": it_id, "quantidade": 4}], "Gestor", "Chefe")
    ok, msg = F.cancelar_requisicao(rid)
    assert ok is False
    assert _status(db, rid) == "Parcial"


# ── Regra SESMT ──────────────────────────────────────────────────────────────


def test_sesmt_exige_responsavel_e_grava_autorizacao(db, make_item):
    a = make_item("PN-SES-A", estoque=50)
    ok, num = _criar(a, 5)
    rid = _req_id(db, num)
    it_id = F.listar_itens_requisicao(rid)[0]["id"]

    # SESMT marcado sem responsável -> rejeita, nada baixado
    ok, msg = F.entregar_requisicao(
        rid, [{"item_req_id": it_id, "quantidade": 5}], "Gestor", "Chefe", sesmt=True, sesmt_responsavel=""
    )
    assert ok is False
    assert F.buscar_item_por_id(a)["estoque_atual"] == 50

    # com responsável -> ok e grava autorização na requisição
    ok, status = F.entregar_requisicao(
        rid,
        [{"item_req_id": it_id, "quantidade": 5}],
        "Gestor",
        "Chefe",
        sesmt=True,
        sesmt_responsavel="Tec SESMT",
    )
    assert ok, status
    conn = db.get_connection()
    row = conn.execute(
        "SELECT sesmt, sesmt_responsavel, autorizador_nome FROM requisicoes WHERE id=?", (rid,)
    ).fetchone()
    conn.close()
    assert row["sesmt"] == 1
    assert row["sesmt_responsavel"] == "Tec SESMT"
    assert row["autorizador_nome"] == "Chefe"


# ── Fila de separação ────────────────────────────────────────────────────────


def test_fila_mostra_abertas_e_parciais_esconde_entregue(db, make_item):
    a = make_item("PN-FILA-A", estoque=50)
    b = make_item("PN-FILA-B", estoque=50)
    _, n1 = _criar(a, 5)  # fica Aberta
    _, n2 = _criar(b, 5)
    r2 = _req_id(db, n2)
    it_id = F.listar_itens_requisicao(r2)[0]["id"]
    F.entregar_requisicao(r2, [{"item_req_id": it_id, "quantidade": 5}], "Gestor", "Chefe")  # -> Entregue

    numeros = {r["numero_requisicao"] for r in F.listar_requisicoes_abertas()}
    assert n1 in numeros  # Aberta permanece na fila
    assert n2 not in numeros  # Entregue saiu da fila
