"""v6.3.0 — Fila de aprovação consolidada do almoxarife (admin).

O que estes testes protegem:

- **O admin vê tudo, de todos os setores.** Era o incômodo que abriu a versão: o
  almoxarife não tem departamento cadastrado, caía no ramo do gestor e a tela não lhe
  mostrava nada.
- **A negativa por omissão do gestor continua de pé.** `listar_requisicoes_por_setor` com
  setor vazio devolve `[]` — a fila consolidada é uma função IRMÃ, alcançável só pelo nome,
  justamente para que nenhum valor passado à primeira caia no "todos os setores". Um
  `gestor` com departamento em branco não pode virar administrador por acidente.
- **Agregação por setor normaliza.** `requisicoes.setor` tem a mesma área grafada de
  várias formas ('TI' × 'ti ' × ' Ti'); sem `UPPER(TRIM())` o filtro mostra o mesmo setor
  três vezes, com a contagem partida.
"""

import database
from streamlit.testing.v1 import AppTest

from services import db_functions as F
from tests.test_v620_telas_self_service import CC, SETOR, _criar_digital, _id, _req
from ui.auth import SESSAO_USUARIO

OUTRO_SETOR = "ADAPTADOR"
TERCEIRO_SETOR = "TI"

ADMIN = {"id": 1, "nome": "Luis Gabriel", "papel": "almoxarife", "departamento": ""}


def _render_gestor(**estado):
    at = AppTest.from_string("from ui.router import render_pagina\nrender_pagina('Aprovações do Setor')\n")
    for k, v in estado.items():
        at.session_state[k] = v
    at.run()
    return at


def _texto(at):
    """Tudo que a tela escreveu, para procurar um número de requisição."""
    return " ".join(
        [m.value for m in at.markdown] + [c.value for c in at.caption] + [i.value for i in at.info]
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Serviço — a fila consolidada
# ══════════════════════════════════════════════════════════════════════════════


def test_listar_para_aprovacao_traz_todos_os_setores(db, make_item):
    """O que o gestor só vê um por vez, o admin vê junto — e na ordem da fila (ASC)."""
    item_id = make_item()
    a = _criar_digital(item_id, setor=SETOR)
    b = _criar_digital(item_id, setor=OUTRO_SETOR)
    c = _criar_digital(item_id, setor=TERCEIRO_SETOR)
    with database.transaction() as conn:
        for numero, quando in (
            (a, "2026-03-01 08:00:00"),
            (b, "2026-01-01 08:00:00"),
            (c, "2026-02-01 08:00:00"),
        ):
            conn.execute("UPDATE requisicoes SET data_hora=? WHERE numero_requisicao=?", (quando, numero))

    fila = F.listar_requisicoes_para_aprovacao()

    assert [r["numero_requisicao"] for r in fila] == [b, c, a]  # mais antiga primeiro
    assert {r["setor"] for r in fila} == {SETOR, OUTRO_SETOR, TERCEIRO_SETOR}
    # Mesmo shape da irmã: a tela usa a mesma `_tabela` para as duas.
    assert set(F.listar_requisicoes_por_setor(SETOR)[0]) == set(fila[0])


def test_listar_para_aprovacao_respeita_status_e_aprovadas(db, make_item):
    item_id = make_item(estoque=50)
    aberta = _criar_digital(item_id, setor=SETOR)
    aprovada = _criar_digital(item_id, setor=OUTRO_SETOR)
    cancelada = _criar_digital(item_id, setor=TERCEIRO_SETOR)
    assert F.aprovar_requisicao(_id(aprovada), "Gestor Silva")[0] is True
    assert F.cancelar_requisicao(_id(cancelada))[0] is True

    aguardando = [r["numero_requisicao"] for r in F.listar_requisicoes_para_aprovacao()]
    ja_aprovadas = [
        r["numero_requisicao"]
        for r in F.listar_requisicoes_para_aprovacao(so_abertas=False, apenas_aprovadas=True)
    ]

    assert aguardando == [aberta]  # Cancelada fora, aprovada fora (é a outra metade)
    assert ja_aprovadas == [aprovada]
    # `so_abertas=False` sem `apenas_aprovadas` traz a Cancelada de volta.
    todos = [r["numero_requisicao"] for r in F.listar_requisicoes_para_aprovacao(so_abertas=False)]
    assert set(todos) == {aberta, cancelada}


def test_limite_da_fila_consolidada(db, make_item):
    item_id = make_item()
    for _ in range(4):
        _criar_digital(item_id, setor=SETOR)

    assert len(F.listar_requisicoes_para_aprovacao(limite=2)) == 2
    assert len(F.listar_requisicoes_para_aprovacao()) == 4


def test_por_setor_continua_negando_por_omissao(db, make_item):
    """Regressão da restrição da v6.3.0: existir a fila consolidada não pode ter afrouxado
    a função do gestor. Nenhum valor passado a `listar_requisicoes_por_setor` chega ao
    "todos os setores" — para isso é preciso chamar a irmã pelo nome."""
    item_id = make_item()
    _criar_digital(item_id, setor=SETOR)
    _criar_digital(item_id, setor=OUTRO_SETOR)

    for vazio in ("", "   ", None):
        assert F.listar_requisicoes_por_setor(vazio) == []
    assert len(F.listar_requisicoes_para_aprovacao()) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 2. Tela — ramo do admin
# ══════════════════════════════════════════════════════════════════════════════


def test_admin_ve_fila_de_todos_os_setores(db, make_item):
    """O caso que abriu a versão: almoxarife SEM departamento vê tudo, e o aviso de
    cadastro incompleto (que o barrava na v6.2.0) não aparece mais."""
    item_id = make_item()
    a = _criar_digital(item_id, setor=SETOR)
    b = _criar_digital(item_id, setor=OUTRO_SETOR)

    at = _render_gestor(**{SESSAO_USUARIO: ADMIN})

    assert not at.exception, [e.value for e in at.exception]
    assert not any("departamento" in w.value for w in at.warning), [w.value for w in at.warning]
    texto = _texto(at)
    assert a in texto and b in texto
    # O setor entra no cartão: sem ele o admin não sabe para quem está aprovando.
    assert SETOR in texto and OUTRO_SETOR in texto


def test_admin_aprova_pela_tela(db, make_item):
    numero = _criar_digital(make_item(), setor=SETOR)

    at = _render_gestor(**{SESSAO_USUARIO: ADMIN})
    aprovar = [b for b in at.button if "Aprovar" in b.label]
    assert aprovar, [b.label for b in at.button]
    aprovar[0].click().run()

    depois = _req(numero)
    assert depois["aprovado_por"] == ADMIN["nome"]
    assert depois["status"] == "Aberta"  # aprovar não é status (decisão da v6.2.0)


def test_filtro_do_admin_lista_so_setores_com_pedido_e_normalizados(db, make_item):
    """As opções saem da própria fila, com contagem, e a mesma área grafada de três formas
    é UMA opção — senão o filtro parte o setor e a contagem mente."""
    item_id = make_item()
    for grafia in ("TI", "ti ", " Ti"):
        _criar_digital(item_id, setor=grafia)
    _criar_digital(item_id, setor=SETOR)
    F.adicionar_valor_lista("setor", "SETOR-SEM-PEDIDO")

    at = _render_gestor(**{SESSAO_USUARIO: ADMIN})

    assert not at.exception, [e.value for e in at.exception]
    # `.options` do AppTest já vem pelo `format_func` (é o que a tela mostra); o valor cru
    # continua sendo o setor normalizado, que é o que `set_value` recebe.
    rotulos = at.selectbox[0].options
    assert rotulos[0] == "Todos os setores"
    assert "TI (3)" in rotulos  # as três grafias viraram uma opção
    assert f"{SETOR} (1)" in rotulos
    assert not any("SETOR-SEM-PEDIDO" in r for r in rotulos)  # setor sem pedido fica fora


def test_filtro_do_admin_restringe_a_fila(db, make_item):
    item_id = make_item()
    fica = _criar_digital(item_id, setor=SETOR)
    sai = _criar_digital(item_id, setor=OUTRO_SETOR)

    at = _render_gestor(**{SESSAO_USUARIO: ADMIN})
    at.selectbox[0].set_value(SETOR).run()

    assert not at.exception, [e.value for e in at.exception]
    texto = _texto(at)
    assert fica in texto
    assert sai not in texto


def test_admin_sem_nada_para_aprovar_nao_quebra(db):
    at = _render_gestor(**{SESSAO_USUARIO: ADMIN})

    assert not at.exception, [e.value for e in at.exception]
    assert any("Nenhuma requisição" in i.value for i in at.info)
    assert not any("Aprovar" in b.label for b in at.button)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Tela — o que a v6.3.0 NÃO pode ter mudado
# ══════════════════════════════════════════════════════════════════════════════


def test_gestor_continua_no_seu_setor(db, make_item):
    """O consolidado é do admin: o gestor não pode ter herdado a fila dos outros."""
    item_id = make_item()
    meu = _criar_digital(item_id, setor=SETOR)
    alheio = _criar_digital(item_id, setor=OUTRO_SETOR)
    gestor = {"id": 2, "nome": "Gestor Silva", "papel": "gestor", "departamento": SETOR}

    at = _render_gestor(**{SESSAO_USUARIO: gestor})

    assert not at.exception, [e.value for e in at.exception]
    texto = _texto(at)
    assert meu in texto
    assert alheio not in texto


def test_gestor_sem_departamento_continua_avisando(db, make_item):
    _criar_digital(make_item(), setor=SETOR)
    gestor = {"id": 2, "nome": "Gestor Sem Setor", "papel": "gestor", "departamento": ""}

    at = _render_gestor(**{SESSAO_USUARIO: gestor})

    assert not at.exception, [e.value for e in at.exception]
    assert any("departamento" in w.value for w in at.warning)
    assert not any("Aprovar" in b.label for b in at.button)


def test_sem_login_continua_na_simulacao(db, make_item):
    """Decisão do Luis (03/08/2026): com `exigir_login` desligada a tela fica como estava —
    escolher o setor e dizer quem aprova. O consolidado é do almoxarife AUTENTICADO."""
    _criar_digital(make_item(), setor=SETOR)

    at = _render_gestor()

    assert not at.exception, [e.value for e in at.exception]
    assert any("simulação" in w.value for w in at.warning)
    assert at.selectbox[0].value == ""  # nasce sem setor escolhido
    assert any("Escolha um setor" in i.value for i in at.info)


def test_comprador_nao_alcanca_a_fila_consolidada(db, make_item):
    """Papel sem a rota não pode cair no ramo do admin por engano — o `papel` da sessão é
    o que separa, e só `almoxarife` abre o consolidado."""
    _criar_digital(make_item(), setor=SETOR)
    comprador = {"id": 3, "nome": "Miguel", "papel": "comprador", "departamento": ""}

    at = _render_gestor(**{SESSAO_USUARIO: comprador})

    assert not at.exception, [e.value for e in at.exception]
    assert any("departamento" in w.value for w in at.warning)  # cai no ramo do gestor
    assert not any("Aprovar" in b.label for b in at.button)


def test_fluxo_admin_end_to_end(db, make_item):
    """Requisitante abre em dois setores → admin vê os dois na fila consolidada → aprova um
    → ele migra para "já aprovadas" e a entrega do outro segue livre (não bloqueante)."""
    item_id = make_item(estoque=20)
    a = _criar_digital(item_id, setor=SETOR, emitente="Sidinei", qtd=2)
    b = _criar_digital(item_id, setor=OUTRO_SETOR, emitente="Ana", qtd=3)

    fila = F.listar_requisicoes_para_aprovacao()
    assert {r["numero_requisicao"] for r in fila} == {a, b}

    ok, msg = F.aprovar_requisicao(_id(a), ADMIN["nome"])
    assert ok, msg

    assert [r["numero_requisicao"] for r in F.listar_requisicoes_para_aprovacao()] == [b]
    aprovadas = F.listar_requisicoes_para_aprovacao(so_abertas=False, apenas_aprovadas=True)
    assert [r["numero_requisicao"] for r in aprovadas] == [a]
    assert aprovadas[0]["aprovado_por"] == ADMIN["nome"]

    # O não aprovado entrega normalmente: a aprovação segue sendo registro, não trava.
    itens = F.listar_itens_requisicao(_id(b))
    ok, msg = F.entregar_requisicao(
        _id(b),
        [{"item_req_id": itens[0]["id"], "item_id": item_id, "quantidade": 3}],
        autorizador_tipo="Gestor",
        autorizador_nome="Chefe",
    )
    assert ok, msg
    assert _req(b)["status"] == "Entregue" and _req(b)["aprovado_por"] is None
    assert _req(a)["centro_custo"] == CC
