"""v5.7.0 — Requisição Padrão × Digital (item 7 do pedido de 26/07/2026).

Decisões nº1, nº2 e nº3 da entrevista de 27/07/2026:

- nº1: o **Padrão** é o fluxo real (baixa na criação) e a **Digital** é protótipo de
  vitrine (baixa só na entrega). O Padrão foi removido — não desativado — na v4.7.0, e
  volta aqui ao lado da Digital, que fica intacta.
- nº2: falta de saldo **grava só o que tem** e manda o pendente para a Fila de Separação.
  Isto SUBSTITUI a regra anterior ("recusa e avisa qual item", `docs/prompt.md:38`), então
  o que se testa aqui é o oposto do que o sistema fazia antes da v4.7.0.
- nº3: Entrega Individual aceita vários destinatários, com Matrícula e Nome separados —
  serializados na MESMA forma que o parser antigo produzia, para não quebrar o histórico.

O contrato da Digital (`criar_requisicao` não baixa estoque) é deliberado desde a v4.7.0 e
está fixado em `tests/test_requisicao.py::test_criacao_nao_baixa_estoque`. Aqui ele é
reafirmado do outro lado: as duas funções convivem sem uma contaminar a outra.
"""

import json

from streamlit.testing.v1 import AppTest

from services import db_functions as F

CC = "21106 - MANUTENÇÃO"


def _req(db, numero):
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM requisicoes WHERE numero_requisicao=?", (numero,)).fetchone()
    conn.close()
    return dict(row)


def _estoque(db, item_id):
    conn = db.get_connection()
    v = conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (item_id,)).fetchone()[0]
    conn.close()
    return float(v)


def _movs(db, item_id):
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM movimentacoes WHERE item_id=? ORDER BY id", (item_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _criar_padrao(itens, **kw):
    """Requisição Padrão com o mínimo obrigatório: autorizador é exigido na criação."""
    dados = {
        "setor": "Manut",
        "emitente": "Joao",
        "centro_custo": CC,
        "autorizador_tipo": "Gestor",
        "autorizador_nome": "Chefe",
        "entrega_individual": False,
        "destinatarios": [],
        "sesmt": False,
        "sesmt_responsavel": "",
        "itens": itens,
        "observacoes": "",
    }
    dados.update(kw)
    return F.criar_requisicao_com_baixa(**dados)


# ── Saldo suficiente: nasce Entregue e o estoque sai na hora ─────────────────


def test_saldo_suficiente_baixa_tudo_e_nasce_entregue(db, make_item):
    a = make_item("PN-PAD-A", estoque=50)
    ok, res = _criar_padrao([{"item_id": a, "quantidade_solicitada": 12}])
    assert ok, res
    assert res["status"] == "Entregue"
    assert res["faltas"] == []
    assert _estoque(db, a) == 38

    req = _req(db, res["numero"])
    assert req["status"] == "Entregue"
    assert req["tipo_fluxo"] == F.FLUXO_PADRAO


def test_baixa_da_padrao_usa_o_mesmo_ledger_da_entrega(db, make_item):
    """A baixa passa por `_baixar_item_requisicao`, o mesmo caminho da entrega: a
    movimentação nasce amarrada à requisição e com o saldo pós correto. Sem isso o
    relatório do CP4 veria duas formas diferentes de saída por requisição."""
    a = make_item("PN-PAD-LEDGER", estoque=30)
    ok, res = _criar_padrao([{"item_id": a, "quantidade_solicitada": 10}])
    assert ok, res
    req = _req(db, res["numero"])

    saidas = [m for m in _movs(db, a) if m["tipo"] == "saida"]
    assert len(saidas) == 1
    mov = saidas[0]
    assert mov["quantidade"] == 10
    assert mov["saldo_apos"] == 20
    assert mov["requisicao_id"] == req["id"], "a saída precisa apontar para a requisição"
    assert mov["centro_custo"] == CC
    assert mov["setor"] == "Manut"
    assert mov["emitente"] == "Joao"
    assert res["numero"] in str(mov["observacao"])


# ── Saldo parcial: grava o que tem, o resto vai para a Fila (decisão nº2) ────


def test_saldo_parcial_baixa_o_disponivel_e_nasce_parcial(db, make_item):
    a = make_item("PN-PAD-PARC", estoque=4)
    ok, res = _criar_padrao([{"item_id": a, "quantidade_solicitada": 10}])
    assert ok, res
    assert res["status"] == "Parcial"
    assert _estoque(db, a) == 0, "baixa o disponível inteiro, não a quantidade pedida"

    assert len(res["faltas"]) == 1
    falta = res["faltas"][0]
    assert falta["part_number"] == "PN-PAD-PARC"
    assert falta["solicitada"] == 10
    assert falta["atendida"] == 4
    assert falta["falta"] == 6


def test_pendente_da_padrao_entra_na_fila_de_separacao(db, make_item):
    """A metade que importa da decisão nº2: o que faltou não se perde — vira trabalho na
    fila do almoxarife, entregável quando o material chegar."""
    a = make_item("PN-PAD-FILA", estoque=4)
    ok, res = _criar_padrao([{"item_id": a, "quantidade_solicitada": 10}])
    req = _req(db, res["numero"])

    na_fila = {r["id"]: r for r in F.listar_requisicoes_abertas()}
    assert req["id"] in na_fila
    assert int(na_fila[req["id"]]["itens_pendentes"]) == 1

    # E é entregável pelo caminho normal assim que houver saldo.
    conn = db.get_connection()
    conn.execute("UPDATE inventario SET estoque_atual=6 WHERE id=?", (a,))
    conn.commit()
    conn.close()
    it = F.listar_itens_requisicao(req["id"])[0]
    ok, novo_status = F.entregar_requisicao(
        req["id"], [{"item_req_id": it["id"], "quantidade": 6}], "Gestor", "Chefe"
    )
    assert ok, novo_status
    assert novo_status == "Entregue"
    assert _estoque(db, a) == 0


def test_item_sem_estoque_nao_gera_movimentacao_e_pedido_nasce_aberta(db, make_item):
    """Borda: saldo zero. Nada é baixado (movimentação de quantidade 0 seria lixo no
    ledger) e, sem nenhum atendimento, o pedido nasce `Aberta` — inteiro na fila."""
    a = make_item("PN-PAD-ZERO", estoque=0)
    ok, res = _criar_padrao([{"item_id": a, "quantidade_solicitada": 5}])
    assert ok, res
    assert res["status"] == "Aberta"
    assert res["faltas"][0]["atendida"] == 0
    assert [m for m in _movs(db, a) if m["tipo"] == "saida"] == []
    assert _estoque(db, a) == 0

    req = _req(db, res["numero"])
    assert req["id"] in [r["id"] for r in F.listar_requisicoes_abertas()]


def test_pedido_com_itens_mistos_baixa_so_o_que_tem(db, make_item):
    """O caso real: um pedido com três materiais, um sobrando, um curto e um zerado."""
    cheio = make_item("PN-MIX-CHEIO", estoque=50)
    curto = make_item("PN-MIX-CURTO", estoque=3)
    zero = make_item("PN-MIX-ZERO", estoque=0)
    ok, res = _criar_padrao(
        [
            {"item_id": cheio, "quantidade_solicitada": 5},
            {"item_id": curto, "quantidade_solicitada": 8},
            {"item_id": zero, "quantidade_solicitada": 2},
        ]
    )
    assert ok, res
    assert res["status"] == "Parcial"
    assert _estoque(db, cheio) == 45
    assert _estoque(db, curto) == 0
    assert _estoque(db, zero) == 0

    faltas = {f["part_number"]: f for f in res["faltas"]}
    assert set(faltas) == {"PN-MIX-CURTO", "PN-MIX-ZERO"}, "item atendido por completo não é falta"
    assert faltas["PN-MIX-CURTO"]["falta"] == 5
    assert faltas["PN-MIX-ZERO"]["falta"] == 2


# ── Autorização e SESMT: exigidos na criação, porque é nela que o material sai ─


def test_padrao_exige_autorizador_e_nao_escreve_nada_ao_recusar(db, make_item):
    a = make_item("PN-PAD-AUT", estoque=50)
    ok, msg = _criar_padrao([{"item_id": a, "quantidade_solicitada": 5}], autorizador_nome="  ")
    assert not ok
    assert "autorizador" in msg.lower()
    assert _estoque(db, a) == 50
    assert F.listar_requisicoes() == [], "pedido recusado não pode deixar requisição órfã"


def test_padrao_exige_responsavel_quando_sesmt(db, make_item):
    a = make_item("PN-PAD-SESMT", estoque=50)
    ok, msg = _criar_padrao([{"item_id": a, "quantidade_solicitada": 5}], sesmt=True)
    assert not ok
    assert "sesmt" in msg.lower()
    assert _estoque(db, a) == 50


def test_padrao_recusa_pedido_sem_item(db):
    ok, msg = _criar_padrao([])
    assert not ok
    ok, msg = _criar_padrao([{"item_id": 1, "quantidade_solicitada": 0}])
    assert not ok
    assert "quantidade" in msg.lower()


def test_falha_no_meio_do_pedido_nao_deixa_baixa_pela_metade(db, make_item):
    """Atomicidade: o pedido inteiro é uma transação. Um item_id inexistente derruba tudo,
    inclusive a baixa do item válido que veio antes."""
    a = make_item("PN-PAD-ATOM", estoque=50)
    ok, msg = _criar_padrao(
        [
            {"item_id": a, "quantidade_solicitada": 5},
            {"item_id": 999999, "quantidade_solicitada": 1},
        ]
    )
    assert not ok, msg
    assert _estoque(db, a) == 50, "a baixa do primeiro item tinha de ser revertida"
    assert F.listar_requisicoes() == []
    assert [m for m in _movs(db, a) if m["tipo"] == "saida"] == []


# ── Entrega Individual: vários destinatários (decisão nº3) ───────────────────


def test_destinatarios_sao_gravados_na_forma_antiga(db, make_item):
    """A UI mudou (Matrícula e Nome em campos separados, um por vez); o formato gravado
    NÃO mudou — continua `[{"matricula":…, "nome":…}]`, como o parser de texto livre
    produzia. É o que mantém `requisicoes.destinatarios` legível junto com o histórico."""
    a = make_item("PN-PAD-EPI", estoque=50)
    destinatarios = [
        {"matricula": "12345", "nome": "Maria Silva"},
        {"matricula": "67890", "nome": "Jose Souza"},
    ]
    ok, res = _criar_padrao(
        [{"item_id": a, "quantidade_solicitada": 2}],
        entrega_individual=True,
        destinatarios=destinatarios,
    )
    assert ok, res
    req = _req(db, res["numero"])
    assert req["entrega_individual"] == 1
    assert json.loads(req["destinatarios"]) == destinatarios


def test_sesmt_com_responsavel_e_gravado(db, make_item):
    a = make_item("PN-PAD-SESMT-OK", estoque=50)
    ok, res = _criar_padrao(
        [{"item_id": a, "quantidade_solicitada": 2}], sesmt=True, sesmt_responsavel="Tecnico SESMT"
    )
    assert ok, res
    req = _req(db, res["numero"])
    assert req["sesmt"] == 1
    assert req["sesmt_responsavel"] == "Tecnico SESMT"
    assert req["autorizador_nome"] == "Chefe"


# ── A Digital fica exatamente como está ──────────────────────────────────────


def test_digital_continua_sem_baixar_estoque_e_marcada_como_digital(db, make_item):
    """O contrato da v4.7.0 preservado — e agora identificável no histórico."""
    a = make_item("PN-DIG-A", estoque=50)
    ok, num = F.criar_requisicao(
        "Manut", "Joao", CC, "", "", False, [], False, "", [{"item_id": a, "quantidade_solicitada": 10}]
    )
    assert ok, num
    assert _estoque(db, a) == 50, "criar_requisicao NÃO baixa estoque — contrato da Digital"
    assert [m for m in _movs(db, a) if m["tipo"] == "saida"] == []

    req = _req(db, num)
    assert req["status"] == "Aberta"
    assert req["tipo_fluxo"] == F.FLUXO_DIGITAL


def test_os_dois_fluxos_convivem_no_mesmo_banco(db, make_item):
    a = make_item("PN-CONVIVE", estoque=50)
    ok, num_dig = F.criar_requisicao(
        "Manut", "Joao", CC, "", "", False, [], False, "", [{"item_id": a, "quantidade_solicitada": 4}]
    )
    ok, res_pad = _criar_padrao([{"item_id": a, "quantidade_solicitada": 6}])
    assert ok, res_pad

    fluxos = {r["numero_requisicao"]: r["tipo_fluxo"] for r in F.listar_requisicoes()}
    assert fluxos[num_dig] == F.FLUXO_DIGITAL
    assert fluxos[res_pad["numero"]] == F.FLUXO_PADRAO
    # Só a Padrão tocou o estoque.
    assert _estoque(db, a) == 44


def test_numeracao_nao_colide_entre_os_fluxos(db, make_item):
    a = make_item("PN-NUM", estoque=90)
    numeros = []
    for _ in range(2):
        ok, num = F.criar_requisicao(
            "Manut", "Joao", CC, "", "", False, [], False, "", [{"item_id": a, "quantidade_solicitada": 1}]
        )
        numeros.append(num)
        ok, res = _criar_padrao([{"item_id": a, "quantidade_solicitada": 1}])
        assert ok, res
        numeros.append(res["numero"])
    assert len(set(numeros)) == 4, f"números repetidos entre os fluxos: {numeros}"


# ── Migração: aditiva e sem backfill ─────────────────────────────────────────


def test_migracao_tipo_fluxo_e_aditiva_e_nao_chuta_o_legado(db):
    """A coluna existe, aceita NULL e requisição legada (gravada sem passar pelas funções
    novas) permanece NULL — "—" na tela. Inferir o fluxo pela data seria chute."""
    conn = db.get_connection()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(requisicoes)")}
    assert "tipo_fluxo" in cols
    conn.execute(
        "INSERT INTO requisicoes (numero_requisicao,data_hora,setor,emitente,centro_custo) "
        "VALUES ('REQ-LEGADO','2026-01-01 08:00:00','Manut','Joao',?)",
        (CC,),
    )
    conn.commit()
    row = conn.execute("SELECT tipo_fluxo FROM requisicoes WHERE numero_requisicao='REQ-LEGADO'").fetchone()
    conn.close()
    assert row["tipo_fluxo"] is None


def test_migracao_e_idempotente(db):
    """Rodar `_migrar` de novo não pode falhar nem reescrever nada (o app migra a cada
    primeiro render)."""
    conn = db.get_connection()
    conn.execute("UPDATE requisicoes SET tipo_fluxo='Padrão'")
    conn.commit()
    conn.close()

    db.criar_banco()  # roda _migrar novamente

    conn = db.get_connection()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(requisicoes)")]
    conn.close()
    assert cols.count("tipo_fluxo") == 1


# ── Smoke de render da aba Nova, nos dois ramos ──────────────────────────────
#
# Mesma abordagem do CP2 (`test_v570_fila_duas_visoes.py`): o smoke do router renderiza a
# Movimentação com banco vazio e no default, então não passa pelo ramo Digital. Aqui o
# `session_state` força cada ramo e a asserção usa um texto EXCLUSIVO daquele ramo — sem
# isso o teste passaria verde mesmo que o seletor fosse ignorado. Continua valendo a regra
# do projeto: isto não substitui abrir o app.


def _render_movimentacao(**estado):
    at = AppTest.from_string("from ui.router import render_pagina\nrender_pagina('Movimentação')\n")
    for k, v in estado.items():
        at.session_state[k] = v
    at.run()
    return at


def _textos(at):
    return " ".join(str(e.value) for grupo in (at.warning, at.info, at.caption, at.markdown) for e in grupo)


_EXCLUSIVO_PADRAO = "O material sai agora"
_EXCLUSIVO_DIGITAL = "Fluxo experimental"


def test_aba_nova_renderiza_o_fluxo_padrao_por_default(db, make_item):
    make_item("PN-SMOKE-PAD", estoque=10)
    at = _render_movimentacao()
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    texto = _textos(at)
    assert _EXCLUSIVO_PADRAO in texto, "a Padrão precisa ser o fluxo default"
    assert _EXCLUSIVO_DIGITAL not in texto


def test_aba_nova_renderiza_o_fluxo_digital_quando_escolhido(db, make_item):
    make_item("PN-SMOKE-DIG", estoque=10)
    at = _render_movimentacao(req_fluxo="Digital (experimental)")
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    texto = _textos(at)
    assert _EXCLUSIVO_DIGITAL in texto, "não entrou no ramo Digital"
    assert _EXCLUSIVO_PADRAO not in texto


def test_tela_de_confirmacao_da_padrao_lista_o_que_ficou_pendente(db, make_item):
    """O desfecho `Parcial` só é útil se a tela disser o que faltou — senão o almoxarife
    acha que entregou tudo."""
    at = _render_movimentacao(
        req_confirmada={
            "fluxo": "Padrão",
            "numero": "REQ-20260727-001",
            "status": "Parcial",
            "faltas": [
                {
                    "part_number": "PN-PEND",
                    "nome_item": "Luva",
                    "unidade": "PAR",
                    "solicitada": 10,
                    "atendida": 4,
                    "falta": 6,
                }
            ],
        }
    )
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    texto = _textos(at) + " ".join(str(e.value) for e in at.success)
    assert "REQ-20260727-001" in texto
    assert "PN-PEND" in texto, "a tela precisa nomear o item que ficou pendente"
    assert "Fila" in texto


def test_tela_de_confirmacao_da_digital_mantem_a_mensagem_de_fila(db):
    at = _render_movimentacao(req_confirmada={"fluxo": "Digital", "numero": "REQ-20260727-009"})
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    texto = _textos(at) + " ".join(str(e.value) for e in at.success)
    assert "REQ-20260727-009" in texto
    assert "Fila" in texto
