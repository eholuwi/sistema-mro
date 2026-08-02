"""v6.1.0 — Usuários, papéis e login local (fundação).

O que estes testes protegem, além do caminho feliz:

- **PIN nunca em texto no banco.** É a regressão silenciosa mais cara desta versão: um
  `UPDATE` que grave o PIN cru não quebra nada visível, e vaza no primeiro `.bak` que
  circular por e-mail.
- **Compatibilidade.** `exigir_login()` num banco novo tem de ser False e
  `opcoes_menu()` sem argumento tem de devolver o menu inteiro — é o que faz a v6.1.0
  abrir igual à v6.0.0 para quem não ligou nada.
- **Não ficar sem administrador.** Rebaixar/desativar o último almoxarife é irreversível
  pela UI (a aba Usuários só existe dentro de Configurações, que só o almoxarife vê).
- **Seed idempotente e não-destrutivo.** Ele roda a CADA abertura do app: reescrever
  papel de quem já existe desfaria toda edição feita na tela.
"""

import database
import pytest
from streamlit.testing.v1 import AppTest

from services import usuarios as U
from ui.router import ROTAS, ROTAS_POR_PAPEL, icones_menu, opcoes_menu


# ── Apoio ─────────────────────────────────────────────────────────────────────


def _inserir_solicitante(nome, departamento=None, incluir=1):
    """Insere direto em `solicitantes_mro` (é o que a ingestão da aba SCM USERS faz)."""
    with database.transaction() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO solicitantes_mro (nome, nome_norm, departamento, incluir_mro) "
            "VALUES (?,?,?,?)",
            (nome, database._normalizar_nome(nome), departamento, incluir),
        )
        return cur.lastrowid


def _por_nome(nome):
    """Linha CRUA de `usuarios` (com `pin_hash`) — só os testes olham o hash."""
    with database.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM usuarios WHERE nome_norm=?", (database._normalizar_nome(nome),)
        ).fetchone()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════════════════════════
# 1. Schema
# ══════════════════════════════════════════════════════════════════════════════


def test_tabela_usuarios_criada_idempotente(db):
    with db.transaction() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)")}
    assert {
        "id",
        "nome",
        "nome_norm",
        "login",
        "ident_norm",
        "pin_hash",
        "papel",
        "departamento",
        "ativo",
        "solic_mro_id",
        "ultimo_login",
        "data_registro",
    } <= cols

    # A migração é aditiva e roda a cada abertura do app: rodar de novo não pode quebrar.
    db.criar_banco()
    with db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] >= 0
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_usuarios_papel'"
        ).fetchone()


# ══════════════════════════════════════════════════════════════════════════════
# 2. Seed
# ══════════════════════════════════════════════════════════════════════════════


def test_seed_cria_requisitantes_de_solicitantes_mro(db):
    sid = _inserir_solicitante("Fulano de Tal", departamento="ENGENHARIA")
    U.semear_usuarios()

    u = _por_nome("Fulano de Tal")
    assert u is not None
    assert u["papel"] == "requisitante"  # padrão de quem não está no mapa manual
    assert u["departamento"] == "ENGENHARIA"
    assert u["solic_mro_id"] == sid
    assert u["login"] == "fulano.tal"
    assert u["ident_norm"] == "fulanodetal"
    assert u["pin_hash"] is None  # nasce sem PIN: não autentica até o almoxarife definir
    assert u["ativo"] == 1


def test_seed_papeis_manuais(db):
    # Luis/Jasiva/Juan já vêm do seed de `solicitantes_mro` do próprio criar_banco().
    U.semear_usuarios()
    for nome in ("Luis Gabriel Arruda de Oliveira", "Jasiva Lopes", "Juan Tarco Pinheiro de Araujo"):
        assert _por_nome(nome)["papel"] == "almoxarife", nome

    # Miguel e Adrya NÃO são solicitantes MRO (quem compra não abre SC) — o seed
    # precisa criá-los mesmo assim, senão o comprador nunca entra.
    with database.transaction() as conn:
        assert not conn.execute(
            "SELECT 1 FROM solicitantes_mro WHERE nome_norm=?", ("miguel nascimento",)
        ).fetchone()
    for nome in ("Miguel Nascimento", "Adrya Vigil"):
        u = _por_nome(nome)
        assert u is not None and u["papel"] == "comprador", nome
        assert u["solic_mro_id"] is None

    assert _por_nome("Miguel Nascimento")["login"] == "miguel.nascimento"


def test_seed_idempotente_e_respeita_edicao(db):
    _inserir_solicitante("Fulano de Tal")
    criados_1 = U.semear_usuarios()
    assert criados_1 > 0

    total_1 = len(U.listar_usuarios())
    assert U.semear_usuarios() == 0  # nada novo na 2ª passada
    assert len(U.listar_usuarios()) == total_1  # e nenhum duplicado

    # Edição na tela tem de sobreviver ao seed da próxima abertura do app.
    uid = _por_nome("Fulano de Tal")["id"]
    ok, _ = U.definir_papel(uid, "portaria")
    assert ok
    U.semear_usuarios()
    assert _por_nome("Fulano de Tal")["papel"] == "portaria"


def test_seed_nao_duplica_por_acento_nem_caixa(db):
    """`nome_norm` é a identidade: 'JASIVA LOPES' e 'Jasiva Lopes' são a mesma pessoa."""
    U.semear_usuarios()
    _inserir_solicitante("JASIVA LOPES")
    U.semear_usuarios()
    with database.transaction() as conn:
        (n,) = conn.execute("SELECT COUNT(*) FROM usuarios WHERE ident_norm=?", ("jasivalopes",)).fetchone()
    assert n == 1


# ══════════════════════════════════════════════════════════════════════════════
# 3. PIN e autenticação
# ══════════════════════════════════════════════════════════════════════════════


def test_pin_armazenado_com_hash(db):
    U.semear_usuarios()
    uid = _por_nome("Jasiva Lopes")["id"]
    U.definir_pin(uid, "1234")

    pin_hash = _por_nome("Jasiva Lopes")["pin_hash"]
    assert "1234" not in pin_hash  # o PIN em texto NUNCA vai para o banco
    assert pin_hash.startswith(f"pbkdf2:sha256:{U.PBKDF2_ITERACOES}:")
    assert len(pin_hash.split(":")) == 5

    assert U.verificar_pin("1234", pin_hash) is True
    assert U.verificar_pin("4321", pin_hash) is False
    assert U.verificar_pin("1234", None) is False  # sem PIN não entra
    assert U.verificar_pin("1234", "lixo") is False  # hash corrompido recusa, não estoura

    # Salt novo a cada gravação: dois usuários com o mesmo PIN não têm o mesmo hash.
    outro = _por_nome("Juan Tarco Pinheiro de Araujo")["id"]
    U.definir_pin(outro, "1234")
    assert _por_nome("Juan Tarco Pinheiro de Araujo")["pin_hash"] != pin_hash


@pytest.mark.parametrize("pin", ["1234", "0000", "9999"])
def test_definir_pin_aceita_4_digitos(db, pin):
    U.semear_usuarios()
    uid = _por_nome("Jasiva Lopes")["id"]
    ok, _ = U.definir_pin(uid, pin)
    assert ok
    assert U.autenticar("Jasiva Lopes", pin) is not None


@pytest.mark.parametrize("pin", ["123", "12345", "abcd", "12 34", "", "12a4", None])
def test_definir_pin_recusa_invalido(db, pin):
    U.semear_usuarios()
    uid = _por_nome("Jasiva Lopes")["id"]
    ok, msg = U.definir_pin(uid, pin)
    assert not ok
    assert "4 dígitos" in msg
    assert _por_nome("Jasiva Lopes")["pin_hash"] is None


def test_autenticar_pin_correto_e_errado(db):
    U.semear_usuarios()
    uid = _por_nome("Jasiva Lopes")["id"]

    assert U.autenticar("Jasiva Lopes", "1234") is None  # ainda sem PIN definido

    U.definir_pin(uid, "1234")
    usuario = U.autenticar("Jasiva Lopes", "1234")
    assert usuario is not None
    assert usuario["papel"] == "almoxarife"
    assert usuario["ultimo_login"]  # gravado no sucesso
    assert "pin_hash" not in usuario  # o hash não sai do módulo de domínio

    assert U.autenticar("Jasiva Lopes", "0000") is None
    assert U.autenticar("Ninguem Existe", "1234") is None
    assert U.autenticar("", "1234") is None


def test_autenticar_normaliza_identificador(db):
    U.semear_usuarios()
    uid = _por_nome("Jasiva Lopes")["id"]
    U.definir_pin(uid, "1234")

    for forma in ("Jasiva Lopes", "jasiva.lopes", " JASIVA  LOPES ", "JasivaLopes"):
        usuario = U.autenticar(forma, "1234")
        assert usuario is not None, forma
        assert usuario["id"] == uid


def test_autenticar_pelo_alias_com_nomes_do_meio(db):
    """v6.2.0 — regressão do bug de login da v6.1.0.

    `_gerar_login` descarta os nomes do MEIO, então o alias exibido na tela não normaliza
    para o `ident_norm` gravado (nome completo). Quem tem 3+ nomes — a maioria absoluta do
    cadastro real — recebia "Usuário ou PIN inválidos" usando exatamente o login que a
    própria tela anunciava. Este teste usa um nome de QUATRO palavras de propósito: com
    'Jasiva Lopes' (duas) o bug não aparece, que foi o motivo de ele passar despercebido.
    """
    ok, _ = U.salvar_usuario("Ana Clara Pascoal de Carvalho", "requisitante")
    assert ok
    uid = _por_nome("Ana Clara Pascoal de Carvalho")["id"]
    assert _por_nome("Ana Clara Pascoal de Carvalho")["login"] == "ana.carvalho"
    U.definir_pin(uid, "1234")

    for forma in ("Ana Clara Pascoal de Carvalho", "ANA CLARA PASCOAL DE CARVALHO", "ana.carvalho"):
        usuario = U.autenticar(forma, "1234")
        assert usuario is not None, forma
        assert usuario["id"] == uid

    assert U.autenticar("ana.carvalho", "0000") is None  # o alias não afrouxa o PIN


def test_alias_ambiguo_recusa_e_o_nome_completo_resolve(db):
    """`login` NÃO é único: duas grafias da mesma identidade compartilham o alias.

    Par real do `mro.db` ('Luis Gabriel Arruda de Oliveira' × 'Luis Gabriel Oliveira'), em
    que NENHUM dos dois se chama literalmente 'Luis Oliveira' — o alias não tem como ser
    resolvido. Recusar é a escolha certa: os candidatos podem ter papéis diferentes, e
    entrar na conta errada é pior que não entrar.
    """
    assert U.salvar_usuario("Luis Gabriel Arruda de Oliveira", "almoxarife")[0]
    assert U.salvar_usuario("Luis Gabriel Oliveira", "requisitante")[0]
    longo = _por_nome("Luis Gabriel Arruda de Oliveira")
    curto = _por_nome("Luis Gabriel Oliveira")
    assert longo["login"] == curto["login"] == "luis.oliveira"
    U.definir_pin(longo["id"], "1111")
    U.definir_pin(curto["id"], "2222")

    # O alias é ambíguo: não autentica NINGUÉM, com PIN de qualquer um dos dois.
    assert U.autenticar("luis.oliveira", "1111") is None
    assert U.autenticar("luis.oliveira", "2222") is None

    # O nome completo continua único e resolve cada um na sua conta.
    assert U.autenticar("Luis Gabriel Arruda de Oliveira", "1111")["papel"] == "almoxarife"
    assert U.autenticar("Luis Gabriel Oliveira", "2222")["papel"] == "requisitante"


def test_alias_nao_atropela_o_nome_completo_de_outra_pessoa(db):
    """Borda real do `mro.db`: o alias de uma pessoa é o nome completo de outra.

    'Miguel Nascimento' tem `ident_norm='miguelnascimento'`, que é exatamente o alias
    'miguel.nascimento' normalizado. O nome completo tem de vencer — senão digitar o
    próprio nome poderia cair na conta do homônimo."""
    assert U.salvar_usuario("Miguel Nascimento", "comprador")[0]
    assert U.salvar_usuario("Miguel Magalhaes Do Nascimento", "requisitante")[0]
    curto = _por_nome("Miguel Nascimento")
    U.definir_pin(curto["id"], "2222")

    usuario = U.autenticar("Miguel Nascimento", "2222")

    assert usuario is not None and usuario["id"] == curto["id"]
    assert usuario["papel"] == "comprador"


def test_autenticar_nome_de_uma_palavra(db):
    """Nome de uma palavra não tem alias `primeiro.sobrenome` — mas autentica pelo nome."""
    ok, _ = U.salvar_usuario("Portaria", "portaria")
    assert ok
    uid = _por_nome("Portaria")["id"]
    assert _por_nome("Portaria")["login"] is None
    U.definir_pin(uid, "5555")
    assert U.autenticar("portaria", "5555") is not None


def test_usuario_inativo_nao_autentica(db):
    U.semear_usuarios()
    uid = _por_nome("Miguel Nascimento")["id"]
    U.definir_pin(uid, "1234")
    assert U.autenticar("Miguel Nascimento", "1234") is not None

    ok, _ = U.ativar_usuario(uid, False)
    assert ok
    assert U.autenticar("Miguel Nascimento", "1234") is None

    U.ativar_usuario(uid, True)
    assert U.autenticar("Miguel Nascimento", "1234") is not None


def test_remover_pin_tranca_o_usuario(db):
    U.semear_usuarios()
    uid = _por_nome("Miguel Nascimento")["id"]
    U.definir_pin(uid, "1234")
    ok, _ = U.remover_pin(uid)
    assert ok
    assert _por_nome("Miguel Nascimento")["pin_hash"] is None
    assert U.autenticar("Miguel Nascimento", "1234") is None


# ══════════════════════════════════════════════════════════════════════════════
# 4. Papéis, listagem e a guarda do último almoxarife
# ══════════════════════════════════════════════════════════════════════════════


def test_listar_usuarios_nao_expoe_hash(db):
    U.semear_usuarios()
    U.definir_pin(_por_nome("Jasiva Lopes")["id"], "1234")

    lista = U.listar_usuarios()
    assert lista
    for u in lista:
        assert "pin_hash" not in u
        assert isinstance(u["tem_pin"], bool)
        assert isinstance(u["ativo"], bool)
    assert next(u for u in lista if u["nome"] == "Jasiva Lopes")["tem_pin"] is True
    assert next(u for u in lista if u["nome"] == "Miguel Nascimento")["tem_pin"] is False
    # ORDER BY papel, nome
    assert [u["papel"] for u in lista] == sorted(u["papel"] for u in lista)


def test_salvar_usuario_valida_e_nao_duplica(db):
    assert U.salvar_usuario("", "almoxarife")[0] is False
    assert U.salvar_usuario("Novo Usuario", "chefao")[0] is False

    ok, _ = U.salvar_usuario("Novo Usuario", "gestor", "PRODUÇÃO")
    assert ok
    assert _por_nome("Novo Usuario")["papel"] == "gestor"
    assert U.salvar_usuario("novo usuario", "gestor")[0] is False  # mesma pessoa


def test_definir_papel_valida(db):
    U.semear_usuarios()
    uid = _por_nome("Miguel Nascimento")["id"]
    assert U.definir_papel(uid, "inexistente")[0] is False
    assert U.definir_papel(999999, "gestor")[0] is False

    ok, _ = U.definir_papel(uid, "gestor")
    assert ok
    assert _por_nome("Miguel Nascimento")["papel"] == "gestor"


def test_guarda_ultimo_almoxarife(db):
    U.semear_usuarios()
    almox = [u for u in U.listar_usuarios() if u["papel"] == "almoxarife" and u["ativo"]]
    assert len(almox) >= 2  # o seed cria três

    # Com mais de um almoxarife ativo, rebaixar/desativar é permitido...
    for u in almox[1:]:
        assert U.ativar_usuario(u["id"], False)[0] is True

    ultimo = almox[0]["id"]
    # ...mas o ÚLTIMO ativo não pode ser rebaixado nem desativado.
    ok, msg = U.definir_papel(ultimo, "requisitante")
    assert not ok and msg == U.MSG_ULTIMO_ALMOXARIFE
    ok, msg = U.ativar_usuario(ultimo, False)
    assert not ok and msg == U.MSG_ULTIMO_ALMOXARIFE
    assert _por_nome(almox[0]["nome"])["papel"] == "almoxarife"
    assert _por_nome(almox[0]["nome"])["ativo"] == 1

    # Com um segundo administrador de volta, a operação passa a ser permitida.
    assert U.ativar_usuario(almox[1]["id"], True)[0] is True
    assert U.definir_papel(ultimo, "requisitante")[0] is True


# ══════════════════════════════════════════════════════════════════════════════
# 5. Flag `exigir_login` (compatibilidade)
# ══════════════════════════════════════════════════════════════════════════════


def test_exigir_login_default_false(db):
    # Banco novo (e todo `mro.db` anterior à v6.1.0) abre SEM login — é a garantia de
    # que a versão não muda o comportamento de quem não pediu nada.
    assert U.exigir_login() is False

    U.definir_exigir_login(True)
    assert U.exigir_login() is True
    U.definir_exigir_login(False)
    assert U.exigir_login() is False


# ══════════════════════════════════════════════════════════════════════════════
# 6. Rotas por papel (UI)
# ══════════════════════════════════════════════════════════════════════════════


def test_rotas_por_papel():
    assert opcoes_menu("almoxarife") == list(ROTAS.keys())
    assert len(opcoes_menu("almoxarife")) == 10  # v6.2.0: 7 + as 3 telas self-service

    comprador = opcoes_menu("comprador")
    assert comprador == ["Dashboard", "Saldo em Estoque", "Ficha 360", "Cadastro de Itens", "Controle de SC"]
    assert {"Movimentação", "Configurações"}.isdisjoint(comprador)

    # v6.2.0 — os três papéis saíram do "sem rota" da v6.1.0: cada um ganhou a SUA tela
    # (detalhe em tests/test_v620_telas_self_service.py).
    assert opcoes_menu("requisitante") == ["Minhas Requisições"]
    assert opcoes_menu("gestor") == ["Aprovações do Setor"]
    assert opcoes_menu("portaria") == ["Portaria"]

    # Papel desconhecido nega por omissão (não libera o menu inteiro).
    assert opcoes_menu("papel-que-nao-existe") == []

    # Todo papel do domínio tem entrada no mapa da UI.
    assert set(U.PAPEIS) == set(ROTAS_POR_PAPEL)
    for rotas in ROTAS_POR_PAPEL.values():
        assert rotas <= frozenset(ROTAS)


def test_opcoes_menu_sem_papel_mantem_contrato_antigo():
    # Backward-compat: sem login (flag off) o menu é o completo, como antes da v6.1.0.
    assert opcoes_menu() == list(ROTAS.keys())
    assert len(opcoes_menu()) == len(icones_menu()) == len(ROTAS)


def test_icones_acompanham_o_filtro():
    # option_menu recebe options e icons posicionalmente: desalinhar troca os ícones.
    for papel in (None, "almoxarife", "comprador"):
        opcoes, icones = opcoes_menu(papel), icones_menu(papel)
        assert len(opcoes) == len(icones)
        assert icones == [ROTAS[n].icone for n in opcoes]


# ══════════════════════════════════════════════════════════════════════════════
# 7. Gate (AppTest)
# ══════════════════════════════════════════════════════════════════════════════

_SCRIPT_GATE = "import streamlit as st\nfrom ui.auth import gate\ngate()\nst.title('Área interna')\n"


def test_smoke_gate_apptest(db):
    """Flag ligada + sem sessão → o gate para o app antes de qualquer conteúdo."""
    U.definir_exigir_login(True)
    at = AppTest.from_string(_SCRIPT_GATE)
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert len(at.title) == 0, "o gate deixou a página interna renderizar"
    assert len(at.text_input) == 2  # identificador + PIN
    assert any("Acesso ao MRO" in s.value for s in at.subheader)


def test_gate_desligado_e_no_op(db):
    """Padrão (flag off): o app roda igual à v6.0.0 — nenhuma tela de login."""
    at = AppTest.from_string(_SCRIPT_GATE)
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert [t.value for t in at.title] == ["Área interna"]
    assert len(at.text_input) == 0


def test_login_pelo_formulario_libera_o_app(db):
    """Ponta a ponta na UI: PIN errado continua barrado, PIN certo entra e o papel fica
    na sessão (é dele que a sidebar tira o menu filtrado)."""
    U.semear_usuarios()
    U.definir_pin(_por_nome("Miguel Nascimento")["id"], "1234")
    U.definir_exigir_login(True)

    at = AppTest.from_string(_SCRIPT_GATE)
    at.run()

    at.text_input[0].set_value("miguel.nascimento")
    at.text_input[1].set_value("0000")
    at.button[0].click().run()
    assert len(at.title) == 0
    assert at.error[0].value == "Usuário ou PIN inválidos."

    at.text_input[0].set_value("miguel.nascimento")
    at.text_input[1].set_value("1234")
    at.button[0].click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert [t.value for t in at.title] == ["Área interna"]
    assert at.session_state["mro_usuario"]["papel"] == "comprador"
    assert "pin_hash" not in at.session_state["mro_usuario"]  # o hash não vai para a sessão


# ══════════════════════════════════════════════════════════════════════════════
# 8. Telas (sidebar filtrada e aba Usuários)
# ══════════════════════════════════════════════════════════════════════════════

_SCRIPT_SIDEBAR = "from ui.sidebar import render_sidebar\nrender_sidebar()\n"


def _sidebar_como(papel, nome="Fulano de Tal"):
    at = AppTest.from_string(_SCRIPT_SIDEBAR)
    at.session_state["mro_usuario"] = {"id": 1, "nome": nome, "papel": papel}
    at.run()
    return at


def test_sidebar_mostra_quem_entrou(db):
    at = _sidebar_como("comprador", nome="Miguel Nascimento")
    assert not at.exception, [e.value for e in at.exception]
    perfil = " ".join(m.value for m in at.sidebar.markdown)
    assert "Miguel Nascimento" in perfil
    assert U.ROTULO_PAPEL["comprador"] in perfil
    assert [b for b in at.sidebar.button if b.key == "sb_sair"], "logado sem botão Sair"


def test_sidebar_sem_login_mantem_o_rodape_de_sempre(db):
    """Flag off (ninguém logado): a barra é idêntica à v6.0.0 — nada de login na cara."""
    at = AppTest.from_string(_SCRIPT_SIDEBAR)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    perfil = " ".join(m.value for m in at.sidebar.markdown)
    assert "Luis Oliveira" in perfil and "Inventus Power" in perfil
    assert not [b for b in at.sidebar.button if b.key == "sb_sair"]


def test_sidebar_para_quando_o_papel_nao_tem_tela(db):
    """Papel sem rota nenhuma: avisa e para — mas sai com o botão Sair na tela, senão a
    pessoa fica presa sem como trocar de usuário.

    v6.2.0 — o exemplo deixou de ser 'requisitante' (que agora tem a sua tela) e passou a
    ser um papel DESCONHECIDO, que é a borda que sobrou: banco editado à mão ou papel
    removido numa versão futura. A negativa por omissão é o comportamento a proteger."""
    at = _sidebar_como("papel-que-nao-existe")
    assert not at.exception, [e.value for e in at.exception]
    assert any("não tem telas" in i.value for i in at.sidebar.info)
    assert [b for b in at.sidebar.button if b.key == "sb_sair"]


def test_aba_usuarios_renderiza_com_usuarios(db):
    """O smoke do router só cobre a aba VAZIA (banco novo). Aqui a grade, o selectbox e
    os botões de ação existem de verdade — é o caminho que o Luis vai usar."""
    U.semear_usuarios()
    U.definir_pin(_por_nome("Jasiva Lopes")["id"], "1234")

    at = AppTest.from_string("from ui.paginas import configuracoes\nconfiguracoes.render()\n")
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert [t for t in at.toggle if t.key == "usr_exigir_login"]
    assert at.dataframe, "a grade de usuários não renderizou"
    assert [s for s in at.selectbox if s.key == "usr_sel"]
