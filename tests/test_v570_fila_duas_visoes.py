"""v5.7.0 — Fila de Separação: recálculo de status ao adicionar item e as duas visões.

Item 8 do pedido de 26/07/2026 + decisões nº4 e nº5 da entrevista de 27/07/2026.

Contexto do bug: `adicionar_itens_requisicao` nunca recalculou o status da requisição.
Isso ficava mascarado por uma guarda que recusava requisição `Entregue` — ao liberar a
guarda (que é o pedido), o item novo entraria numa requisição ainda marcada `Entregue`,
sumiria da fila (`listar_requisicoes_abertas` filtra Aberta/Parcial) e seria recusado por
`entregar_requisicao`: órfão, invisível e não entregável. Por isso os dois andam juntos.

A Visão do Solicitante é SIMULAÇÃO, sem autenticação — o que se testa aqui é o filtro por
emitente e a fonte do seletor de nomes, não qualquer forma de controle de acesso.
"""

from streamlit.testing.v1 import AppTest

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


def _criar(item_id, qtd=10, emitente="Joao", setor="Manut"):
    return F.criar_requisicao(
        setor,
        emitente,
        CC,
        "",
        "",
        False,
        [],
        False,
        "",
        [{"item_id": item_id, "quantidade_solicitada": qtd}],
    )


def _entregar_tudo(db, rid):
    for it in F.listar_itens_requisicao(rid):
        falta = float(it["quantidade_solicitada"]) - float(it["quantidade_atendida"])
        if falta > 0:
            ok, res = F.entregar_requisicao(
                rid, [{"item_req_id": it["id"], "quantidade": falta}], "Gestor", "Chefe"
            )
            assert ok, res


# ── Reabertura: o ciclo completo que o item 8 pede ───────────────────────────


def test_ciclo_entregue_reaberta_e_entregavel_de_novo(db, make_item):
    """O roteiro de validação do CP2 inteiro, em código: entrega total → adiciona item →
    volta à fila como Parcial → o item novo é entregável → fecha de novo em Entregue."""
    a = make_item("PN-CICLO-A", estoque=50)
    b = make_item("PN-CICLO-B", estoque=50)
    ok, num = _criar(a, 5)
    assert ok, num
    rid = _req_id(db, num)

    _entregar_tudo(db, rid)
    assert _status(db, rid) == "Entregue"

    ok, msg = F.adicionar_itens_requisicao(rid, [{"item_id": b, "quantidade_solicitada": 3}])
    assert ok, msg
    assert _status(db, rid) == "Parcial"
    assert "reaberta" in msg.lower(), "a UI precisa dizer ao almoxarife que a requisição voltou à fila"

    # Entregável de novo — era o que a guarda + status parado impediam.
    item_novo = next(i for i in F.listar_itens_requisicao(rid) if i["item_id"] == b)
    ok, res = F.entregar_requisicao(
        rid, [{"item_req_id": item_novo["id"], "quantidade": 3}], "Gestor", "Chefe"
    )
    assert ok, res
    assert _status(db, rid) == "Entregue"


def test_item_novo_nao_fica_orfao_na_fila(db, make_item):
    """O defeito exato que o recálculo evita: sem o UPDATE do status a requisição some da
    fila e o item novo nunca chega a ser separado."""
    a = make_item("PN-ORF-A", estoque=50)
    b = make_item("PN-ORF-B", estoque=50)
    ok, num = _criar(a, 5)
    rid = _req_id(db, num)
    _entregar_tudo(db, rid)

    F.adicionar_itens_requisicao(rid, [{"item_id": b, "quantidade_solicitada": 3}])
    na_fila = {r["id"]: r for r in F.listar_requisicoes_abertas()}
    assert rid in na_fila, "a requisição reaberta tem de reaparecer na fila padrão"
    assert int(na_fila[rid]["itens_pendentes"]) == 1
    assert int(na_fila[rid]["total_itens"]) == 2


def test_estoque_e_ledger_intactos_ao_adicionar(db, make_item):
    """Adicionar item é escrita de pedido, não de estoque: nada sai do almoxarifado aqui."""
    a = make_item("PN-LEDGER-A", estoque=50)
    b = make_item("PN-LEDGER-B", estoque=40)
    ok, num = _criar(a, 5)
    rid = _req_id(db, num)
    _entregar_tudo(db, rid)

    conn = db.get_connection()
    estoque_b = conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (b,)).fetchone()[0]
    n_mov = conn.execute("SELECT COUNT(*) FROM movimentacoes").fetchone()[0]
    conn.close()

    F.adicionar_itens_requisicao(rid, [{"item_id": b, "quantidade_solicitada": 3}])

    conn = db.get_connection()
    assert conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (b,)).fetchone()[0] == estoque_b
    assert conn.execute("SELECT COUNT(*) FROM movimentacoes").fetchone()[0] == n_mov
    conn.close()


def test_adicionar_em_aberta_nao_promove_o_status(db, make_item):
    """Recalcular não pode inventar progresso: sem nada entregue, continua Aberta."""
    a = make_item("PN-ABE-A", estoque=50)
    b = make_item("PN-ABE-B", estoque=50)
    ok, num = _criar(a, 5)
    rid = _req_id(db, num)
    ok, msg = F.adicionar_itens_requisicao(rid, [{"item_id": b, "quantidade_solicitada": 3}])
    assert ok, msg
    assert _status(db, rid) == "Aberta"
    assert "reaberta" not in msg.lower()


# ── listar_requisicoes_abertas(incluir_entregues) ────────────────────────────


def test_incluir_entregues_e_opt_in_e_nunca_traz_cancelada(db, make_item):
    """O default preserva a fila de trabalho do almoxarife. Cancelada não entra em nenhum
    dos dois modos: não aceita item novo, então não teria o que fazer ali."""
    a = make_item("PN-FILTRO-A", estoque=50)
    b = make_item("PN-FILTRO-B", estoque=50)
    c = make_item("PN-FILTRO-C", estoque=50)

    ok, n_aberta = _criar(a, 5)
    rid_aberta = _req_id(db, n_aberta)
    ok, n_entregue = _criar(b, 5)
    rid_entregue = _req_id(db, n_entregue)
    _entregar_tudo(db, rid_entregue)
    ok, n_cancelada = _criar(c, 5)
    rid_cancelada = _req_id(db, n_cancelada)
    F.cancelar_requisicao(rid_cancelada)

    padrao = [r["id"] for r in F.listar_requisicoes_abertas()]
    assert rid_aberta in padrao
    assert rid_entregue not in padrao
    assert rid_cancelada not in padrao

    ampliada = [r["id"] for r in F.listar_requisicoes_abertas(incluir_entregues=True)]
    assert rid_aberta in ampliada
    assert rid_entregue in ampliada, "sem isto o 'Adicionar item' é inalcançável pela tela"
    assert rid_cancelada not in ampliada


# ── Visão do Solicitante (simulação) ─────────────────────────────────────────


def test_listar_requisicoes_filtra_por_emitente(db, make_item):
    a = make_item("PN-EMI-A", estoque=50)
    _criar(a, 2, emitente="Joao")
    _criar(a, 3, emitente="Maria")
    _criar(a, 4, emitente="Joao")

    do_joao = F.listar_requisicoes(emitente="Joao")
    assert len(do_joao) == 2
    assert {r["emitente"] for r in do_joao} == {"Joao"}
    # Sem filtro, o Histórico continua vendo tudo (contrato preservado).
    assert len(F.listar_requisicoes()) == 3


def test_filtro_por_emitente_ignora_caixa_e_espaco(db, make_item):
    """Nomes são digitados à mão: 'joao' e ' Joao ' são a mesma pessoa."""
    a = make_item("PN-EMI-B", estoque=50)
    _criar(a, 2, emitente="Joao")
    assert len(F.listar_requisicoes(emitente="  joAO ")) == 1


def test_solicitante_ve_os_proprios_pedidos_em_qualquer_status(db, make_item):
    """A fila do almoxarife só mostra o que falta separar; o solicitante quer acompanhar
    também o que já foi entregue e o que foi cancelado."""
    a = make_item("PN-EMI-C", estoque=50)
    ok, n1 = _criar(a, 2, emitente="Ana")
    ok, n2 = _criar(a, 3, emitente="Ana")
    _entregar_tudo(db, _req_id(db, n2))
    ok, n3 = _criar(a, 4, emitente="Ana")
    F.cancelar_requisicao(_req_id(db, n3))

    status = {r["numero_requisicao"]: r["status"] for r in F.listar_requisicoes(emitente="Ana")}
    assert status == {n1: "Aberta", n2: "Entregue", n3: "Cancelada"}


def test_seletor_de_nomes_sai_do_historico_real_e_deduplica(db, make_item):
    a = make_item("PN-EMI-D", estoque=50)
    _criar(a, 1, emitente="Joao")
    _criar(a, 1, emitente="JOAO")  # mesma pessoa, grafia diferente
    _criar(a, 1, emitente="Maria")
    _criar(a, 1, emitente="   ")  # lixo não vira opção

    nomes = F.listar_emitentes_requisicao()
    assert len(nomes) == 2
    assert {n.upper() for n in nomes} == {"JOAO", "MARIA"}


def test_seletor_de_nomes_vazio_quando_nao_ha_requisicao(db):
    assert F.listar_emitentes_requisicao() == []


# ── Smoke de render das duas visões ──────────────────────────────────────────
#
# O smoke do `test_v500_router.py` renderiza a Movimentação com banco VAZIO e na visão
# default, então não passa por nenhum dos dois caminhos novos. Aqui o banco tem dados e
# o `session_state` força cada visão — é o mais perto de "abrir a tela" que a suíte chega
# (a regra do projeto continua valendo: isto não substitui a validação no app real).


def _render_movimentacao(**estado):
    at = AppTest.from_string("from ui.router import render_pagina\nrender_pagina('Movimentação')\n")
    for k, v in estado.items():
        at.session_state[k] = v
    at.run()
    return at


def _cenario_fila(db, make_item):
    """Uma requisição aberta, uma entregue e uma reaberta como Parcial."""
    a = make_item("PN-SMOKE-A", estoque=50)
    b = make_item("PN-SMOKE-B", estoque=50)
    _criar(a, 5, emitente="Joao")
    ok, n2 = _criar(a, 5, emitente="Ana")
    rid2 = _req_id(db, n2)
    _entregar_tudo(db, rid2)
    F.adicionar_itens_requisicao(rid2, [{"item_id": b, "quantidade_solicitada": 2}])
    return rid2


_AVISO_SIMULACAO = "Simulação"


def _textos(at):
    return " ".join(str(e.value) for grupo in (at.warning, at.info, at.caption, at.markdown) for e in grupo)


def test_visao_almoxarife_renderiza_com_entregues_incluidas(db, make_item):
    _cenario_fila(db, make_item)
    at = _render_movimentacao(fila_visao="Almoxarife", fila_incluir_entregues=True)
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    # Prova de que o ramo é o do almoxarife: o aviso de simulação é exclusivo da outra visão.
    assert _AVISO_SIMULACAO not in _textos(at)


def test_visao_solicitante_renderiza_com_nome_escolhido(db, make_item):
    _cenario_fila(db, make_item)
    at = _render_movimentacao(fila_visao="Solicitante", fila_solicitante_nome="Ana")
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    texto = _textos(at)
    # Sem esta asserção o teste passaria mesmo que o session_state fosse ignorado e a tela
    # caísse na visão do almoxarife — verde por engano.
    assert _AVISO_SIMULACAO in texto, "não entrou na Visão do Solicitante"
    assert "não tem login" in texto, "a tela precisa deixar explícito que não há autenticação"


def test_visao_solicitante_renderiza_sem_nome_escolhido(db, make_item):
    """Estado inicial da visão: seletor vazio não pode quebrar a tela."""
    _cenario_fila(db, make_item)
    at = _render_movimentacao(fila_visao="Solicitante")
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    assert _AVISO_SIMULACAO in _textos(at)


def test_visao_solicitante_renderiza_com_banco_vazio(db):
    """Sem nenhuma requisição não há emitente para simular — a tela avisa, não estoura."""
    at = _render_movimentacao(fila_visao="Solicitante")
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    assert _AVISO_SIMULACAO in _textos(at)
