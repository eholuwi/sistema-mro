"""v6.2.0 — Telas self-service (Requisitante · Gestor · Portaria).

O que estes testes protegem, além do caminho feliz:

- **A aprovação do gestor não é uma trava.** A decisão de 02/08/2026 é explícita: o
  gestor registra a autorização antecipada e o almoxarife continua separando e entregando
  como sempre. Um `UPDATE` que mexesse em `status` ou em `autorizador_*` transformaria um
  registro paralelo num bloqueio no meio do expediente — daí as asserções de que esses
  campos NÃO mudam.
- **A primeira aprovação vale.** Duplo-clique/refresh não pode reescrever quem aprovou.
- **Migração aditiva.** Banco da v6.1.0 (sem as colunas) abre na v6.2.0 com `.bak` antes
  do ALTER e sem perder linha; rodar de novo é no-op.
- **Modo público da Portaria não vaza menu.** Entrar sem login pela consulta de saída tem
  de dar acesso a UMA rota; `papel_atual()` é None tanto para o público quanto para o
  "deslogado com a flag desligada", então a ordem da checagem em `ui/sidebar.py` é o que
  separa os dois casos.
"""

import os

import database
from streamlit.testing.v1 import AppTest

from services import db_functions as F
from services import usuarios as U
from ui.auth import SESSAO_PUBLICA, SESSAO_USUARIO
from ui.router import ROTAS, ROTAS_POR_PAPEL, opcoes_menu

CC = "21106 - MANUTENÇÃO"
SETOR = "ENGENHARIA DE TESTES"


# ── Apoio ─────────────────────────────────────────────────────────────────────


def _criar_digital(item_id, setor=SETOR, emitente="Sidinei", qtd=2, **kw):
    """Requisição do fluxo Digital (o do self-service): abre na fila, não baixa estoque."""
    dados = {
        "setor": setor,
        "emitente": emitente,
        "centro_custo": CC,
        "autorizador_tipo": "",
        "autorizador_nome": "",
        "entrega_individual": False,
        "destinatarios": [],
        "sesmt": False,
        "sesmt_responsavel": "",
        "itens": [{"item_id": item_id, "quantidade_solicitada": qtd}],
        "observacoes": "",
    }
    dados.update(kw)
    ok, numero = F.criar_requisicao(**dados)
    assert ok, numero
    return numero


def _req(numero):
    """Linha crua de `requisicoes` pelo número."""
    with database.transaction() as conn:
        row = conn.execute("SELECT * FROM requisicoes WHERE numero_requisicao=?", (numero,)).fetchone()
    return dict(row)


def _id(numero):
    return _req(numero)["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 1. Migração (schema)
# ══════════════════════════════════════════════════════════════════════════════


def test_migracao_aprovacao_gestor(db):
    """Colunas presentes, idempotentes e nascendo NULL (sem backfill)."""
    with db.transaction() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(requisicoes)")]
    assert {"aprovado_por", "aprovado_em"} <= set(cols)

    db.criar_banco()  # roda _migrar de novo: o app migra a cada abertura

    with db.transaction() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(requisicoes)")]
        conn.execute(
            "INSERT INTO requisicoes (numero_requisicao,data_hora,setor,emitente,centro_custo) "
            "VALUES ('REQ-LEGADO','2026-01-01 08:00:00',?,'Joao',?)",
            (SETOR, CC),
        )
    assert cols.count("aprovado_por") == 1 and cols.count("aprovado_em") == 1
    legado = _req("REQ-LEGADO")
    assert legado["aprovado_por"] is None and legado["aprovado_em"] is None


def test_migracao_faz_backup_e_preserva_o_legado(db):
    """Banco no estado da v6.1.0 (sem as colunas) e COM requisição: a migração grava o
    `.bak` antes do ALTER e não perde nem reescreve a linha legada."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO requisicoes (numero_requisicao,data_hora,setor,emitente,centro_custo,status) "
            "VALUES ('REQ-V610','2026-07-01 08:00:00',?,'Joao',?,'Entregue')",
            (SETOR, CC),
        )
        conn.execute("ALTER TABLE requisicoes DROP COLUMN aprovado_por")
        conn.execute("ALTER TABLE requisicoes DROP COLUMN aprovado_em")

    db.criar_banco()

    baks = os.listdir(db.diretorio_backups())
    assert any("aprovacao-gestor-v620" in nome for nome in baks), baks
    legada = _req("REQ-V610")
    assert legada["status"] == "Entregue"  # o CHECK de status não foi tocado
    assert legada["aprovado_por"] is None and legada["aprovado_em"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 2. Aprovação do gestor (domínio)
# ══════════════════════════════════════════════════════════════════════════════


def test_aprovar_requisicao(db, make_item):
    numero = _criar_digital(make_item())
    req_id = _id(numero)
    antes = _req(numero)

    ok, msg = F.aprovar_requisicao(req_id, "Gestor Silva")

    assert ok and numero in msg
    depois = _req(numero)
    assert depois["aprovado_por"] == "Gestor Silva"
    assert depois["aprovado_em"]
    # O registro é PARALELO: nem status nem autorizador (a liberação da entrega) mudam.
    assert depois["status"] == antes["status"] == "Aberta"
    assert depois["autorizador_tipo"] == antes["autorizador_tipo"]
    assert depois["autorizador_nome"] == antes["autorizador_nome"]


def test_aprovar_requisicao_ja_aprovada_nao_sobrescreve(db, make_item):
    numero = _criar_digital(make_item())
    req_id = _id(numero)
    assert F.aprovar_requisicao(req_id, "Gestor Silva")[0] is True
    carimbo = _req(numero)["aprovado_em"]

    ok, msg = F.aprovar_requisicao(req_id, "Outro Gestor")

    assert ok, msg  # não é erro: avisa e segue
    assert "Já aprovada por Gestor Silva" in msg
    assert _req(numero)["aprovado_por"] == "Gestor Silva"
    assert _req(numero)["aprovado_em"] == carimbo


def test_aprovar_requisicao_cancelada_recusa(db, make_item):
    numero = _criar_digital(make_item())
    req_id = _id(numero)
    assert F.cancelar_requisicao(req_id)[0] is True

    ok, msg = F.aprovar_requisicao(req_id, "Gestor Silva")

    assert not ok and "Cancelada" in msg
    assert _req(numero)["aprovado_por"] is None


def test_aprovar_requisicao_bordas(db, make_item):
    numero = _criar_digital(make_item())

    assert F.aprovar_requisicao(99999, "Gestor Silva") == (False, "Requisição não encontrada.")
    ok, msg = F.aprovar_requisicao(_id(numero), "   ")
    assert not ok and "Informe" in msg
    assert _req(numero)["aprovado_por"] is None


def test_aprovacao_nao_bloqueia_a_entrega(db, make_item):
    """A regra que a v6.2.0 mais precisa preservar: o almoxarife entrega uma requisição
    NÃO aprovada exatamente como antes (a aprovação é registro, não trava)."""
    item_id = make_item(estoque=10)
    numero = _criar_digital(item_id, qtd=3)
    req_id = _id(numero)
    itens = F.listar_itens_requisicao(req_id)

    ok, msg = F.entregar_requisicao(
        req_id,
        [{"item_req_id": itens[0]["id"], "item_id": item_id, "quantidade": 3}],
        autorizador_tipo="Gestor",
        autorizador_nome="Chefe",
    )

    assert ok, msg
    entregue = _req(numero)
    assert entregue["status"] == "Entregue"
    assert entregue["aprovado_por"] is None  # entregou sem nenhuma aprovação registrada


# ══════════════════════════════════════════════════════════════════════════════
# 3. Consultas novas (Portaria e Gestor)
# ══════════════════════════════════════════════════════════════════════════════


def test_buscar_requisicao_por_numero(db, make_item):
    item_id = make_item(part_number="PN-PORTARIA")
    numero = _criar_digital(item_id, qtd=4)

    achada = F.buscar_requisicao_por_numero(f"  {numero.lower()}  ")

    assert achada is not None
    assert achada["numero_requisicao"] == numero
    assert achada["setor"] == SETOR and achada["centro_custo"] == CC
    assert achada["total_itens"] == 1  # mesmo shape de listar_requisicoes
    assert [i["part_number"] for i in achada["itens"]] == ["PN-PORTARIA"]
    assert float(achada["itens"][0]["quantidade_solicitada"]) == 4.0


def test_buscar_requisicao_por_numero_sem_resultado(db):
    assert F.buscar_requisicao_por_numero("REQ-QUE-NAO-EXISTE") is None
    assert F.buscar_requisicao_por_numero("") is None
    assert F.buscar_requisicao_por_numero(None) is None
    assert F.buscar_requisicao_por_numero("   ") is None


def test_listar_requisicoes_por_setor(db, make_item):
    item_id = make_item()
    aberta = _criar_digital(item_id, setor=SETOR)
    outro = _criar_digital(item_id, setor="ALMOXARIFADO")
    cancelada = _criar_digital(item_id, setor=SETOR)
    assert F.cancelar_requisicao(_id(cancelada))[0] is True

    fila = F.listar_requisicoes_por_setor(SETOR)

    # Só o setor pedido, só o que ainda pode ser aprovado, e nada já aprovado.
    assert [r["numero_requisicao"] for r in fila] == [aberta]
    assert outro not in [r["numero_requisicao"] for r in fila]
    # Case/trim insensível: o setor vem de `usuarios.departamento`, digitado à mão.
    assert [r["numero_requisicao"] for r in F.listar_requisicoes_por_setor(f"  {SETOR.lower()} ")] == [aberta]
    # A cancelada só aparece quando o chamador pede todos os status.
    todos = [r["numero_requisicao"] for r in F.listar_requisicoes_por_setor(SETOR, so_abertas=False)]
    assert set(todos) == {aberta, cancelada}


def test_listar_requisicoes_por_setor_separa_aprovadas(db, make_item):
    item_id = make_item()
    pendente = _criar_digital(item_id)
    aprovada = _criar_digital(item_id)
    assert F.aprovar_requisicao(_id(aprovada), "Gestor Silva")[0] is True

    aguardando = [r["numero_requisicao"] for r in F.listar_requisicoes_por_setor(SETOR)]
    ja_aprovadas = [
        r["numero_requisicao"]
        for r in F.listar_requisicoes_por_setor(SETOR, so_abertas=False, apenas_aprovadas=True)
    ]

    assert aguardando == [pendente]
    assert ja_aprovadas == [aprovada]


def test_listar_requisicoes_por_setor_sem_setor_nega(db, make_item):
    """Setor vazio devolve [] em vez do setor de todo mundo: gestor sem departamento
    cadastrado não pode virar administrador por acidente."""
    _criar_digital(make_item())

    for vazio in ("", "   ", None):
        assert F.listar_requisicoes_por_setor(vazio) == []
    assert F.listar_requisicoes_por_setor("SETOR-INEXISTENTE") == []


def test_ordem_da_fila_do_gestor_e_da_mais_antiga(db, make_item):
    """Fila se atende pelo começo — a do gestor ordena como a do almoxarife (ASC), ao
    contrário do histórico (`listar_requisicoes`, DESC)."""
    item_id = make_item()
    primeira = _criar_digital(item_id)
    segunda = _criar_digital(item_id)
    with database.transaction() as conn:
        conn.execute(
            "UPDATE requisicoes SET data_hora='2026-01-01 08:00:00' WHERE numero_requisicao=?",
            (primeira,),
        )
        conn.execute(
            "UPDATE requisicoes SET data_hora='2026-08-01 08:00:00' WHERE numero_requisicao=?",
            (segunda,),
        )

    fila = [r["numero_requisicao"] for r in F.listar_requisicoes_por_setor(SETOR)]

    assert fila == [primeira, segunda]


# ══════════════════════════════════════════════════════════════════════════════
# 4. Fluxo self-service ponta a ponta (domínio)
# ══════════════════════════════════════════════════════════════════════════════


def test_contrato_criacao_self_service(db, make_item):
    """O pedido do requisitante nasce como a tela vai criá-lo: Digital, Aberta, sem
    autorizador (isso é da entrega) e sem aprovação (isso é do gestor)."""
    numero = _criar_digital(make_item(estoque=50), qtd=5)

    req = _req(numero)
    assert req["status"] == "Aberta"
    assert req["tipo_fluxo"] == "Digital"
    assert req["aprovado_por"] is None and req["aprovado_em"] is None
    assert not req["autorizador_nome"]
    # A Digital não escreve estoque na criação (contrato desde a v4.7.0).
    with database.transaction() as conn:
        (saldo,) = conn.execute("SELECT estoque_atual FROM inventario LIMIT 1").fetchone()
    assert float(saldo) == 50.0


def test_fluxo_gestor_end_to_end(db, make_item):
    """Requisitante cria com o setor do seu departamento → o pedido aparece na fila do
    gestor daquele setor → aprovado, migra para "já aprovadas" e some da fila."""
    numero = _criar_digital(make_item(), emitente="Sidinei", setor=SETOR)

    aguardando = F.listar_requisicoes_por_setor(SETOR, so_abertas=True, apenas_aprovadas=False)
    assert [r["numero_requisicao"] for r in aguardando] == [numero]

    ok, msg = F.aprovar_requisicao(aguardando[0]["id"], "Gestor Silva")
    assert ok, msg

    assert F.listar_requisicoes_por_setor(SETOR, so_abertas=True, apenas_aprovadas=False) == []
    aprovadas = F.listar_requisicoes_por_setor(SETOR, so_abertas=False, apenas_aprovadas=True)
    assert [r["numero_requisicao"] for r in aprovadas] == [numero]
    assert aprovadas[0]["aprovado_por"] == "Gestor Silva"
    # A Portaria vê o mesmo pedido pelo número, com a aprovação e os itens.
    na_portaria = F.buscar_requisicao_por_numero(numero)
    assert na_portaria["aprovado_por"] == "Gestor Silva"
    assert len(na_portaria["itens"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 5. Rotas e menu (UI)
# ══════════════════════════════════════════════════════════════════════════════


def test_rotas_por_papel_v620():
    assert len(ROTAS) == 10
    assert opcoes_menu("almoxarife") == list(ROTAS.keys())
    assert len(opcoes_menu(None)) == 10  # contrato legado: sem login, menu inteiro

    # Cada papel novo tem UMA rota — a sua.
    assert opcoes_menu("requisitante") == ["Minhas Requisições"]
    assert opcoes_menu("gestor") == ["Aprovações do Setor"]
    assert opcoes_menu("portaria") == ["Portaria"]

    # O comprador NÃO herda as telas novas (self-service é de quem consome material).
    comprador = opcoes_menu("comprador")
    assert comprador == ["Dashboard", "Saldo em Estoque", "Ficha 360", "Cadastro de Itens", "Controle de SC"]
    assert set(U.PAPEIS) == set(ROTAS_POR_PAPEL)
    assert opcoes_menu("papel-que-nao-existe") == []


def test_opcoes_setor_prefill(db, make_item):
    """O departamento do usuário entra no select mesmo fora dos setores conhecidos, e não
    duplica quando já existe (nem em caixa diferente)."""
    from ui.paginas.movimentacao import _opcoes_setor

    F.adicionar_valor_lista("setor", "MANUTENÇÃO")

    com_novo = _opcoes_setor("ENGENHARIA DE TESTES")
    assert com_novo[0] == "ENGENHARIA DE TESTES"
    assert "MANUTENÇÃO" in com_novo

    ja_existe = _opcoes_setor("manutenção")
    assert ja_existe.count("MANUTENÇÃO") == 1
    assert "manutenção" not in ja_existe  # a forma cadastrada vence
    assert _opcoes_setor("") == _opcoes_setor()


# ══════════════════════════════════════════════════════════════════════════════
# 6. Modo público da Portaria e telas novas (AppTest)
# ══════════════════════════════════════════════════════════════════════════════

_SCRIPT_GATE = (
    "import streamlit as st\n"
    "from ui.auth import gate\n"
    "from ui.sidebar import render_sidebar\n"
    "gate()\n"
    "st.title(render_sidebar())\n"
)


def _render_pagina(nome, **estado):
    at = AppTest.from_string(f"from ui.router import render_pagina\nrender_pagina({nome!r})\n")
    for k, v in estado.items():
        at.session_state[k] = v
    at.run()
    return at


def test_smoke_gate_portaria_publica(db):
    """Flag ligada + modo público: o gate deixa passar e a sidebar entrega UMA rota.

    A asserção que importa é a segunda — o gate passar não basta, porque `papel_atual()` é
    None no modo público e `opcoes_menu(None)` devolve o menu inteiro. Se a sidebar
    checasse o papel antes do modo público, este teste veria 10 rotas.
    """
    U.definir_exigir_login(True)
    at = AppTest.from_string(_SCRIPT_GATE)
    at.session_state[SESSAO_PUBLICA] = True
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert [t.value for t in at.title] == ["Portaria"]
    assert len(at.text_input) == 0, "a tela de login apareceu no modo público"
    # O menu público é de UMA rota: nada de Configurações/Movimentação na guarita.
    assert len(at.sidebar.button) == 1  # só "Sair do modo público"


def test_gate_sem_modo_publico_continua_travando(db):
    """A contraprova: sem a sessão pública, a flag ligada continua barrando tudo."""
    U.definir_exigir_login(True)
    at = AppTest.from_string(_SCRIPT_GATE)
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert len(at.title) == 0
    assert len(at.text_input) == 2  # identificador + PIN


def test_login_oferece_a_consulta_publica(db):
    """O botão da Portaria existe na tela de login e liga o modo público."""
    U.definir_exigir_login(True)
    at = AppTest.from_string(_SCRIPT_GATE)
    at.run()

    botoes = [b for b in at.button if "Portaria" in b.label]
    assert botoes, [b.label for b in at.button]

    botoes[0].click().run()
    assert at.session_state[SESSAO_PUBLICA] is True
    assert [t.value for t in at.title] == ["Portaria"]


def test_smoke_rota_requisitante(db):
    """Sessão de requisitante: menu de um item e a tela dele renderiza logada."""
    usuario = {"id": 1, "nome": "Sidinei", "papel": "requisitante", "departamento": SETOR}

    at = _render_pagina("Minhas Requisições", **{SESSAO_USUARIO: usuario})

    assert not at.exception, [e.value for e in at.exception]
    assert opcoes_menu("requisitante") == ["Minhas Requisições"]
    # Entrou no ramo logado (o deslogado pede login em vez de mostrar as abas).
    assert any("Fila de Separação" in c.value for c in at.caption)


def test_requisitante_sem_login_avisa_e_nao_cria(db):
    at = _render_pagina("Minhas Requisições")

    assert not at.exception, [e.value for e in at.exception]
    assert any("PIN" in i.value for i in at.info)
    assert len(at.button) == 0, "sem login não pode haver botão de criar requisição"


def test_gestor_aprova_pela_tela(db, make_item):
    """Ponta a ponta na UI: o gestor logado vê o pedido do seu setor e o botão Aprovar
    grava a aprovação (sem mexer no status)."""
    numero = _criar_digital(make_item(), setor=SETOR)
    usuario = {"id": 1, "nome": "Gestor Silva", "papel": "gestor", "departamento": SETOR}

    at = _render_pagina("Aprovações do Setor", **{SESSAO_USUARIO: usuario})
    assert not at.exception, [e.value for e in at.exception]

    aprovar = [b for b in at.button if "Aprovar" in b.label]
    assert aprovar, [b.label for b in at.button]
    aprovar[0].click().run()

    depois = _req(numero)
    assert depois["aprovado_por"] == "Gestor Silva"
    assert depois["status"] == "Aberta"


def test_gestor_sem_departamento_avisa(db):
    usuario = {"id": 1, "nome": "Gestor Sem Setor", "papel": "gestor", "departamento": ""}

    at = _render_pagina("Aprovações do Setor", **{SESSAO_USUARIO: usuario})

    assert not at.exception, [e.value for e in at.exception]
    assert any("departamento" in w.value for w in at.warning)


def test_portaria_consulta_por_numero(db, make_item):
    """A tela da Portaria acha a requisição pelo número e mostra os itens."""
    numero = _criar_digital(make_item(part_number="PN-GUARITA"), qtd=3)

    at = _render_pagina("Portaria")
    assert not at.exception, [e.value for e in at.exception]

    at.text_input[0].set_value(numero.lower())  # a guarita digita como vier no papel
    at.button[0].click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert any(numero in m.value for m in at.markdown)
    assert len(at.dataframe) == 1  # tabela de itens


def test_portaria_numero_inexistente_avisa(db):
    at = _render_pagina("Portaria")
    at.text_input[0].set_value("REQ-NAO-EXISTE")
    at.button[0].click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("não encontrada" in i.value for i in at.info)


def test_portaria_e_leitura_pura(db, make_item):
    """A guarita não escreve: consultar não pode alterar nenhuma linha de `requisicoes`."""
    numero = _criar_digital(make_item())
    antes = _req(numero)

    at = _render_pagina("Portaria")
    at.text_input[0].set_value(numero)
    at.button[0].click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert _req(numero) == antes
