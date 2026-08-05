"""v6.4.0 — Rejeição com ciclo de volta (D) · saldo/imagem do requisitante (E) · Portaria por nome (F).

O que estes testes protegem:

- **A rejeição é um CICLO, não um "não".** Decisão do Luis (05/08/2026): o gestor devolve
  com motivo, o requisitante ajusta e reenvia, o pedido volta para a fila. É por isso que
  existe `reenviado_em` — e é por isso que o par rejeitado/reenviado tem de ser testado
  nas DUAS filas (setor e consolidada), que compartilham `_clausulas_aprovacao`.
- **Motivo obrigatório.** Uma devolução sem motivo faz o requisitante reenviar o mesmo
  pedido; é o único canal entre as duas pontas.
- **Aprovado e rejeitado nunca coexistem.** As duas guardas são simétricas, senão a
  Portaria mostraria dois carimbos contraditórios e ninguém saberia qual vale.
- **Esconder saldo é da tela do Requisitante, não do item em si.** Almoxarife e comprador
  continuam vendo tudo — `_saldo_visivel` só oculta quando as DUAS condições batem.
- **A Portaria por nome nega por omissão.** `listar_requisicoes(emitente="")` devolve a
  base inteira; sem a guarda, apertar Consultar em branco despejaria as requisições de
  todos os funcionários no terminal da guarita.
"""

import pytest
from streamlit.testing.v1 import AppTest

from services import db_functions as F
from services import ficha
from tests.test_v620_telas_self_service import CC, SETOR, _criar_digital, _id, _req
from ui.auth import SESSAO_USUARIO
from ui.paginas.movimentacao import _saldo_visivel

GESTOR = "Gestor Silva"
MOTIVO = "Quantidade acima do necessário; peça 2 em vez de 10."

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64  # bytes quaisquer com extensão válida


# ══════════════════════════════════════════════════════════════════════════════
# 1. Épico D — migração
# ══════════════════════════════════════════════════════════════════════════════


def test_migracao_rejeicao(db):
    """Quatro colunas, idempotentes e nascendo NULL (sem backfill: o legado nunca foi
    rejeitado, e é isso que NULL diz)."""
    with db.transaction() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(requisicoes)")]
    assert {"rejeitado_por", "rejeitado_em", "motivo_rejeicao", "reenviado_em"} <= set(cols)

    db.criar_banco()  # o app migra a cada abertura
    with db.transaction() as conn:
        assert [r[1] for r in conn.execute("PRAGMA table_info(requisicoes)")] == cols


def test_rejeicao_nao_criou_status_novo(db, make_item):
    """Mesma filosofia da aprovação: nenhum status novo no CHECK de `requisicoes.status`."""
    numero = _criar_digital(make_item())
    assert F.rejeitar_requisicao(_id(numero), GESTOR, MOTIVO)[0] is True

    assert _req(numero)["status"] == "Aberta"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Épico D — rejeitar
# ══════════════════════════════════════════════════════════════════════════════


def test_rejeitar_grava_quem_quando_e_por_que(db, make_item):
    numero = _criar_digital(make_item())

    ok, msg = F.rejeitar_requisicao(_id(numero), GESTOR, MOTIVO)

    assert ok, msg
    linha = _req(numero)
    assert linha["rejeitado_por"] == GESTOR
    assert linha["motivo_rejeicao"] == MOTIVO
    assert linha["rejeitado_em"] and linha["reenviado_em"] is None


@pytest.mark.parametrize("motivo", ["", "   ", None])
def test_rejeitar_exige_motivo(db, make_item, motivo):
    """Sem motivo, o requisitante reenviaria exatamente o mesmo pedido."""
    numero = _criar_digital(make_item())

    ok, msg = F.rejeitar_requisicao(_id(numero), GESTOR, motivo)

    assert ok is False and "motivo" in msg.lower()
    assert _req(numero)["rejeitado_em"] is None


def test_rejeitar_exige_quem(db, make_item):
    numero = _criar_digital(make_item())
    ok, _ = F.rejeitar_requisicao(_id(numero), "  ", MOTIVO)
    assert ok is False


def test_rejeitar_requisicao_inexistente(db):
    ok, msg = F.rejeitar_requisicao(99999, GESTOR, MOTIVO)
    assert ok is False and "não encontrada" in msg


def test_rejeitar_recusa_cancelada_e_aprovada(db, make_item):
    item_id = make_item(estoque=50)
    cancelada = _criar_digital(item_id)
    aprovada = _criar_digital(item_id)
    assert F.cancelar_requisicao(_id(cancelada))[0] is True
    assert F.aprovar_requisicao(_id(aprovada), GESTOR)[0] is True

    assert F.rejeitar_requisicao(_id(cancelada), GESTOR, MOTIVO)[0] is False
    ok, msg = F.rejeitar_requisicao(_id(aprovada), GESTOR, MOTIVO)
    assert ok is False and "já aprovada" in msg


def test_rejeitar_de_novo_sobrescreve(db, make_item):
    """Ao contrário da aprovação (primeira vence), o motivo que vale é sempre o último —
    o requisitante precisa ver o que AINDA está errado, não o que já corrigiu."""
    numero = _criar_digital(make_item())
    req_id = _id(numero)
    F.rejeitar_requisicao(req_id, GESTOR, "primeiro motivo")
    F.reenviar_requisicao(req_id)

    assert F.rejeitar_requisicao(req_id, "Outra Gestora", "segundo motivo")[0] is True

    linha = _req(numero)
    assert linha["motivo_rejeicao"] == "segundo motivo"
    assert linha["rejeitado_por"] == "Outra Gestora"
    assert linha["reenviado_em"] is None  # o ciclo recomeça


def test_aprovar_recusa_devolvida_nao_reenviada(db, make_item):
    """Guarda simétrica: enquanto está com o requisitante, o pedido não pode ser aprovado.

    Não é beco sem saída — reenviar (mesmo sem mudar nada) devolve o pedido à fila."""
    numero = _criar_digital(make_item())
    req_id = _id(numero)
    F.rejeitar_requisicao(req_id, GESTOR, MOTIVO)

    ok, msg = F.aprovar_requisicao(req_id, GESTOR)
    assert ok is False and "devolvida" in msg

    assert F.reenviar_requisicao(req_id)[0] is True
    assert F.aprovar_requisicao(req_id, GESTOR)[0] is True


# ══════════════════════════════════════════════════════════════════════════════
# 3. Épico D — o pedido sai da fila e volta
# ══════════════════════════════════════════════════════════════════════════════


def _fila_setor(numero_esperado=None, **kw):
    return [r["numero_requisicao"] for r in F.listar_requisicoes_por_setor(SETOR, **kw)]


def _fila_admin(**kw):
    return [r["numero_requisicao"] for r in F.listar_requisicoes_para_aprovacao(**kw)]


def test_devolvida_sai_das_duas_filas_e_volta_ao_reenviar(db, make_item):
    """O ciclo inteiro, nas DUAS filas — elas compartilham `_clausulas_aprovacao`, e uma
    divergência aqui faria o pedido sumir de uma e continuar na outra."""
    numero = _criar_digital(make_item())
    req_id = _id(numero)
    assert numero in _fila_setor() and numero in _fila_admin()

    F.rejeitar_requisicao(req_id, GESTOR, MOTIVO)
    assert numero not in _fila_setor()
    assert numero not in _fila_admin()
    assert numero in _fila_setor(apenas_rejeitadas=True)
    assert numero in _fila_admin(apenas_rejeitadas=True)

    F.reenviar_requisicao(req_id)
    assert numero in _fila_setor()
    assert numero in _fila_admin()
    assert numero not in _fila_setor(apenas_rejeitadas=True)
    assert numero not in _fila_admin(apenas_rejeitadas=True)


def test_nunca_rejeitada_permanece_na_fila(db, make_item):
    """O `NOT (...)` do filtro não pode derrubar quem nunca foi rejeitado (NULL no SQL)."""
    numero = _criar_digital(make_item())

    assert numero in _fila_admin()
    assert numero not in _fila_admin(apenas_rejeitadas=True)


def test_devolvida_sai_da_fila_de_separacao(db, make_item):
    """Decisão do Luis (05/08/2026): "se não foi aprovada pelo gestor, não podemos entregar
    o material". A requisição devolvida some da fila do almoxarife e volta ao ser reenviada.

    ⚠️ Só a rejeição EXPLÍCITA bloqueia — ver
    `test_nao_aprovada_continua_entregavel`."""
    numero = _criar_digital(make_item())
    req_id = _id(numero)
    assert numero in [r["numero_requisicao"] for r in F.listar_requisicoes_abertas()]

    F.rejeitar_requisicao(req_id, GESTOR, MOTIVO)
    assert numero not in [r["numero_requisicao"] for r in F.listar_requisicoes_abertas()]
    # some também do ramo que reabre requisição Entregue para receber item novo
    assert numero not in [
        r["numero_requisicao"] for r in F.listar_requisicoes_abertas(incluir_entregues=True)
    ]

    F.reenviar_requisicao(req_id)
    assert numero in [r["numero_requisicao"] for r in F.listar_requisicoes_abertas()]


def test_entregar_recusa_requisicao_devolvida(db, make_item):
    """A trava vive no SERVIÇO, não só no filtro da fila: sumir da lista é conveniência de
    tela, e qualquer outro caminho até a entrega passaria por cima dela."""
    numero = _criar_digital(make_item(estoque=50), qtd=5)
    req_id = _id(numero)
    item_req = F.listar_itens_requisicao(req_id)[0]
    F.rejeitar_requisicao(req_id, GESTOR, MOTIVO)

    ok, msg = F.entregar_requisicao(
        req_id, [{"item_req_id": item_req["id"], "quantidade": 2}], "Luis", "Almoxarife"
    )

    assert ok is False and "devolvida" in msg.lower()
    assert F.listar_itens_requisicao(req_id)[0]["quantidade_atendida"] == 0  # nada baixado

    # reenviada, a entrega volta a ser possível
    assert F.reenviar_requisicao(req_id)[0] is True
    ok, msg = F.entregar_requisicao(
        req_id, [{"item_req_id": item_req["id"], "quantidade": 2}], "Luis", "Almoxarife"
    )
    assert ok, msg


def test_nao_aprovada_continua_entregavel(db, make_item):
    """A aprovação NÃO virou obrigatória — só a rejeição explícita bloqueia.

    Exigir aprovação para toda entrega pararia a operação: em 05/08/2026 o `mro.db` tem
    1.132 requisições e ZERO aprovadas. Este teste é a fronteira entre as duas leituras."""
    numero = _criar_digital(make_item(estoque=50), qtd=5)
    req_id = _id(numero)
    item_req = F.listar_itens_requisicao(req_id)[0]

    assert _req(numero)["aprovado_por"] is None  # ninguém aprovou
    assert numero in [r["numero_requisicao"] for r in F.listar_requisicoes_abertas()]
    ok, msg = F.entregar_requisicao(
        req_id, [{"item_req_id": item_req["id"], "quantidade": 2}], "Luis", "Almoxarife"
    )
    assert ok, msg


# ══════════════════════════════════════════════════════════════════════════════
# 4. Épico D — reenviar e ajustar
# ══════════════════════════════════════════════════════════════════════════════


def test_reenviar_sem_rejeicao_e_recusado(db, make_item):
    numero = _criar_digital(make_item())
    ok, msg = F.reenviar_requisicao(_id(numero))
    assert ok is False and "não foi rejeitada" in msg


def test_reenviar_duas_vezes_e_no_op(db, make_item):
    """Duplo-clique não pode reescrever a data do reenvio."""
    numero = _criar_digital(make_item())
    req_id = _id(numero)
    F.rejeitar_requisicao(req_id, GESTOR, MOTIVO)
    assert F.reenviar_requisicao(req_id)[0] is True
    primeiro = _req(numero)["reenviado_em"]

    ok, msg = F.reenviar_requisicao(req_id)

    assert ok is True and "Já reenviada" in msg
    assert _req(numero)["reenviado_em"] == primeiro


def test_ajustar_quantidade_do_item(db, make_item):
    numero = _criar_digital(make_item(estoque=50), qtd=10)
    item_req = F.listar_itens_requisicao(_id(numero))[0]

    ok, msg = F.atualizar_item_requisicao(item_req["id"], 2)

    assert ok, msg
    assert F.listar_itens_requisicao(_id(numero))[0]["quantidade_solicitada"] == 2


@pytest.mark.parametrize("qtd", [0, -3, "abc", None])
def test_ajustar_quantidade_invalida(db, make_item, qtd):
    """Zerar seria remover pela porta dos fundos, sem passar pela checagem de item
    já atendido."""
    numero = _criar_digital(make_item(estoque=50), qtd=10)
    item_req = F.listar_itens_requisicao(_id(numero))[0]

    assert F.atualizar_item_requisicao(item_req["id"], qtd)[0] is False
    assert F.listar_itens_requisicao(_id(numero))[0]["quantidade_solicitada"] == 10


def test_ajustar_item_ja_entregue_e_recusado(db, make_item):
    """A quantidade solicitada é a referência contra a qual a baixa foi conferida."""
    numero = _criar_digital(make_item(estoque=50), qtd=10)
    req_id = _id(numero)
    item_req = F.listar_itens_requisicao(req_id)[0]
    ok, msg = F.entregar_requisicao(
        req_id, [{"item_req_id": item_req["id"], "quantidade": 4}], "Luis", "Almoxarife"
    )
    assert ok, msg

    ok, msg = F.atualizar_item_requisicao(item_req["id"], 2)

    assert ok is False and "entregue" in msg.lower()


def test_ajustar_item_de_requisicao_cancelada_e_recusado(db, make_item):
    numero = _criar_digital(make_item(estoque=50), qtd=10)
    item_req = F.listar_itens_requisicao(_id(numero))[0]
    assert F.cancelar_requisicao(_id(numero))[0] is True

    assert F.atualizar_item_requisicao(item_req["id"], 2)[0] is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. Épico E — saldo do requisitante e imagem
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "flag_item,ocultar,visivel",
    [
        (1, False, True),  # almoxarife no balcão: vê sempre
        (0, False, True),  # idem, mesmo com a flag desligada no item
        (1, True, True),  # requisitante, item liberado
        (0, True, False),  # requisitante, item bloqueado — o único caso que esconde
        (None, True, True),  # legado sem a coluna: visível por omissão
    ],
)
def test_saldo_visivel(flag_item, ocultar, visivel):
    assert _saldo_visivel({"mostrar_saldo_requisitante": flag_item}, ocultar) is visivel


def test_flag_de_saldo_persiste_pelo_cadastro(db, make_item):
    item_id = make_item()

    ok, msg = F.atualizar_item_inventario(item_id, {"mostrar_saldo_requisitante": 0})

    assert ok, msg
    assert F.buscar_item_por_id(item_id)["mostrar_saldo_requisitante"] == 0
    item = next(i for i in F.listar_inventario() if i["id"] == item_id)
    assert item["mostrar_saldo_requisitante"] == 0  # chega à tela pelo inventário


def test_imagem_existente(db, make_item):
    item_id = make_item()
    assert ficha.imagem_existente(F.buscar_item_por_id(item_id)) is None

    ok, rel = ficha.salvar_imagem_item(item_id, "foto.png", _PNG)
    assert ok, rel
    caminho = ficha.imagem_existente(F.buscar_item_por_id(item_id))
    assert caminho and caminho.endswith(".png")


def test_imagem_existente_com_arquivo_sumido(db, make_item):
    """`imagem_path` aponta para arquivo fora do SQLite: ele pode não ter descido do
    OneDrive. Sem a checagem, o `st.image` derruba a página inteira por causa de uma foto."""
    import os

    item_id = make_item()
    ficha.salvar_imagem_item(item_id, "foto.png", _PNG)
    item = F.buscar_item_por_id(item_id)
    os.remove(ficha.imagem_existente(item))

    assert ficha.imagem_existente(item) is None


# ══════════════════════════════════════════════════════════════════════════════
# 6. Épico F — Portaria por nome
# ══════════════════════════════════════════════════════════════════════════════


def test_busca_por_emitente_traz_itens(db, make_item):
    numero = _criar_digital(make_item(), emitente="Sidinei Barbosa")

    reqs = F.buscar_requisicoes_por_emitente("Sidinei Barbosa")

    assert [r["numero_requisicao"] for r in reqs] == [numero]
    assert reqs[0]["itens"] and "part_number" in reqs[0]["itens"][0]


def test_busca_por_emitente_ignora_caixa_e_espacos(db, make_item):
    """Quem digita é o porteiro num terminal compartilhado, lendo um crachá."""
    _criar_digital(make_item(), emitente="Sidinei Barbosa")

    assert len(F.buscar_requisicoes_por_emitente("  sidinei barbosa ")) == 1
    assert len(F.buscar_requisicoes_por_emitente("SIDINEI BARBOSA")) == 1


@pytest.mark.parametrize("termo", ["", "   ", None])
def test_busca_por_emitente_vazio_nao_lista_ninguem(db, make_item, termo):
    """A guarda que impede a guarita de ver a base inteira ao apertar Consultar em branco."""
    _criar_digital(make_item(), emitente="Sidinei Barbosa")
    _criar_digital(make_item(part_number="PN-2"), emitente="Outro")

    assert F.buscar_requisicoes_por_emitente(termo) == []


def test_busca_por_emitente_multiplos_resultados(db, make_item):
    item_id = make_item(estoque=99)
    a = _criar_digital(item_id, emitente="Sidinei Barbosa")
    b = _criar_digital(item_id, emitente="Sidinei Barbosa")

    reqs = F.buscar_requisicoes_por_emitente("Sidinei Barbosa")

    assert {r["numero_requisicao"] for r in reqs} == {a, b}


def test_busca_por_emitente_desconhecido(db, make_item):
    _criar_digital(make_item(), emitente="Sidinei Barbosa")
    assert F.buscar_requisicoes_por_emitente("Ninguém") == []


# ══════════════════════════════════════════════════════════════════════════════
# 7. Smoke das telas (o gate não cobre `ui/` além disto)
# ══════════════════════════════════════════════════════════════════════════════


def _render(rota, **estado):
    at = AppTest.from_string(f"from ui.router import render_pagina\nrender_pagina({rota!r})\n")
    for k, v in estado.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, at.exception
    return at


def test_smoke_gestor_com_devolvida(db, make_item):
    numero = _criar_digital(make_item())
    F.rejeitar_requisicao(_id(numero), GESTOR, MOTIVO)

    at = _render(
        "Aprovações do Setor",
        **{SESSAO_USUARIO: {"id": 1, "nome": "Luis", "papel": "almoxarife", "departamento": ""}},
    )

    texto = " ".join([m.value for m in at.markdown] + [c.value for c in at.caption])
    assert "Devolvidas para ajuste" in texto


def test_smoke_portaria_por_nome(db, make_item):
    _criar_digital(make_item(), emitente="Sidinei Barbosa")
    at = _render("Portaria")
    assert at.radio[0].options == ["Número da requisição", "Nome do requisitante"]


def test_smoke_requisitante_esconde_saldo(db, make_item):
    """A tela do requisitante renderiza com a flag ligada — o smoke garante que o
    parâmetro novo de `_req_bloco_materiais` não quebrou a montagem do pedido."""
    make_item()
    _render(
        "Minhas Requisições",
        **{SESSAO_USUARIO: {"id": 2, "nome": "Sidinei", "papel": "requisitante", "departamento": SETOR}},
    )


def test_smoke_cadastro_itens_com_aba_minmax(db, make_item):
    item_id = make_item(estoque=100, minimo=10, lead=10)
    ok, msg = F.registrar_movimentacao(item_id, "saida", 5, CC, "Joao", "Joao")
    assert ok, msg  # saída de hoje: dá lastro ao consumo, senão não há sugestão
    F.recalcular_min_max_calculado(item_id)

    at = _render("Cadastro de Itens")

    assert len(at.tabs) >= 3  # Editar · Novo · Sugestões de Mín/Máx


def test_smoke_ficha_360_com_vida_util(db, make_item):
    """A Ficha ganhou uma 6ª métrica na linha; o smoke pega quebra de layout/atributo."""
    make_item(estoque=100, minimo=10)
    _render("Ficha 360")


def test_cc_do_teste_permanece_valido(db):
    """Sentinela do import compartilhado: se o CC do v6.2.0 mudar, estes testes mudam junto."""
    assert CC
