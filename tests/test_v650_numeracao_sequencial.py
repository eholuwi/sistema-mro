"""v6.5.0 — numeração sequencial simples das requisições: `REQ-AAAAMMDD-NNN` → `1..N`.

A operação pediu o número curto que se lê em voz alta na guarita. A data que o formato
antigo carregava não some do sistema: ela sempre esteve em `requisicoes.data_hora`, que é
o que a Portaria e o cartão exibem — o número apenas para de duplicá-la.

O que este arquivo trava:
- a renumeração ordena por `data_hora` (desempate por `id`) e cobre a base inteira;
- as FKs (`itens_requisicao`, `movimentacoes`) continuam ligadas — elas apontam para
  `requisicoes.id`, e nenhum `id` muda;
- a migração é idempotente e faz backup ANTES de reescrever;
- **rollback**: erro no meio do UPDATE não pode deixar renumeração pela metade;
- o próximo número é `MAX + 1` e ignora número não-numérico (legado e fixture de teste);
- colisão de número vira nova tentativa, não erro na tela;
- o regex do Relatório de Movimentações aceita OS DOIS formatos (as 2.320 observações
  antigas não foram reescritas — a FK é a fonte da verdade, o texto é fallback);
- a busca da Portaria normaliza zero à esquerda e ainda aceita `REQ-…` dos cartões
  impressos.
"""

import os
import sqlite3

import pytest

import database
from services import db_functions as F

CC = "21106 - MANUTENÇÃO"


def _req_legada(conn, numero, data_hora, setor="MANUTENÇÃO", emitente="Joao"):
    """Uma requisição no formato ANTIGO, gravada por INSERT direto — é assim que o banco
    de produção chega na migração."""
    cur = conn.execute(
        "INSERT INTO requisicoes (numero_requisicao,data_hora,setor,emitente,centro_custo) VALUES (?,?,?,?,?)",
        (numero, data_hora, setor, emitente, CC),
    )
    return cur.lastrowid


def _numeros_por_id(conn=None):
    """`{id: numero}` — a única leitura que interessa aqui, sempre por `id`, que é o que
    as FKs enxergam."""
    fechar = conn is None
    conn = conn or database.get_connection()
    try:
        return {
            r["id"]: r["numero_requisicao"]
            for r in conn.execute("SELECT id, numero_requisicao FROM requisicoes")
        }
    finally:
        if fechar:
            conn.close()


@pytest.fixture
def base_legada(db):
    """Três requisições no formato antigo, inseridas FORA da ordem cronológica: se a
    renumeração usasse a ordem de inserção (ou o `id`), o teste passaria por acidente."""
    conn = db.get_connection()
    try:
        meio = _req_legada(conn, "REQ-20260502-001", "2026-05-02 09:00:00")
        antiga = _req_legada(conn, "REQ-20260416-007", "2026-04-16 14:08:00")
        nova = _req_legada(conn, "REQ-20260807-003", "2026-08-07 16:10:00")
        conn.commit()
    finally:
        conn.close()
    return {"antiga": antiga, "meio": meio, "nova": nova}


# ── Renumeração ───────────────────────────────────────────────────────────────


def test_renumeracao_ordena_por_data_hora(db, base_legada):
    """1 é o pedido mais antigo, N o mais recente — a ordem que o número passa a contar."""
    with database.transaction() as c:
        database._migrar(c)

    numeros = _numeros_por_id()
    assert numeros[base_legada["antiga"]] == "1"
    assert numeros[base_legada["meio"]] == "2"
    assert numeros[base_legada["nova"]] == "3"


def test_renumeracao_desempata_por_id(db):
    """`data_hora` tem resolução de SEGUNDO: dois pedidos do mesmo segundo empatam, e sem
    desempate a ordem seria a que o SQLite quisesse. O `id` é o critério estável."""
    conn = db.get_connection()
    try:
        primeiro = _req_legada(conn, "REQ-20260601-001", "2026-06-01 10:00:00")
        segundo = _req_legada(conn, "REQ-20260601-002", "2026-06-01 10:00:00")
        conn.commit()
    finally:
        conn.close()

    with database.transaction() as c:
        database._migrar(c)

    numeros = _numeros_por_id()
    assert (numeros[primeiro], numeros[segundo]) == ("1", "2")


def test_renumeracao_nao_deixa_duplicata_nem_buraco(db, base_legada):
    """O `UNIQUE` da coluna é a rede, mas o invariante é mais forte: 1..N sem repetir."""
    with database.transaction() as c:
        database._migrar(c)

    numeros = sorted(int(n) for n in _numeros_por_id().values())
    assert numeros == [1, 2, 3]


def test_fks_sobrevivem_a_renumeracao(db, make_item):
    """O ponto que justificava o backup: renumerar não pode desligar o histórico. As FKs
    apontam para `requisicoes.id` — nenhum `id` muda — mas quem confia em teste, e não em
    argumento, precisa ver o item e a saída continuarem ligados ao pedido certo."""
    item = make_item("PN-FK", estoque=50)
    conn = db.get_connection()
    try:
        req_id = _req_legada(conn, "REQ-20260504-006", "2026-05-04 08:00:00")
        conn.execute(
            "INSERT INTO itens_requisicao (requisicao_id,item_id,quantidade_solicitada,quantidade_atendida) "
            "VALUES (?,?,?,?)",
            (req_id, item, 4.0, 4.0),
        )
        conn.execute(
            "INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,centro_custo,setor,"
            "emitente,observacao,requisicao_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                item,
                "saida",
                4.0,
                46.0,
                "2026-05-04 08:05:00",
                CC,
                "MANUTENÇÃO",
                "Joao",
                "Req REQ-20260504-006",
                req_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    with database.transaction() as c:
        database._migrar(c)

    itens = F.listar_itens_requisicao(req_id)
    assert [i["quantidade_solicitada"] for i in itens] == [4.0]

    conn = db.get_connection()
    try:
        mov = conn.execute("SELECT requisicao_id FROM movimentacoes WHERE tipo='saida'").fetchone()
        numero = conn.execute("SELECT numero_requisicao FROM requisicoes WHERE id=?", (req_id,)).fetchone()
    finally:
        conn.close()
    assert mov["requisicao_id"] == req_id
    assert numero["numero_requisicao"] == "1"


def test_migracao_e_idempotente(db, base_legada):
    """O app migra a cada boot: a segunda passada não pode encontrar trabalho nem
    reembaralhar o que já está numerado."""
    with database.transaction() as c:
        database._migrar(c)
    antes = _numeros_por_id()

    with database.transaction() as c:
        database._migrar(c)
    assert _numeros_por_id() == antes

    db.criar_banco()  # o caminho real: boot completo do app
    assert _numeros_por_id() == antes


def test_migracao_faz_backup_antes_de_reescrever(db, base_legada):
    """Regra inviolável nº4: dado histórico só é reescrito com `.bak` no disco. E o backup
    é do estado ANTERIOR — é o que o torna útil."""
    with database.transaction() as c:
        database._migrar(c)

    baks = [b for b in os.listdir(database.diretorio_backups()) if "numero-sequencial-v650" in b]
    assert len(baks) == 1, f"esperava 1 backup da renumeração, achei {baks}"

    velho = sqlite3.connect(os.path.join(database.diretorio_backups(), baks[0]))
    try:
        numeros = {r[0] for r in velho.execute("SELECT numero_requisicao FROM requisicoes")}
    finally:
        velho.close()
    assert numeros == {"REQ-20260416-007", "REQ-20260502-001", "REQ-20260807-003"}


def test_banco_ja_numerico_nao_gera_backup_novo(db, base_legada):
    """O guard tem de ser barato e silencioso: sem trabalho a fazer, nem `.bak` nem log."""
    with database.transaction() as c:
        database._migrar(c)
    antes = len(os.listdir(database.diretorio_backups()))

    with database.transaction() as c:
        database._migrar(c)
    assert len(os.listdir(database.diretorio_backups())) == antes


# ── Rollback ──────────────────────────────────────────────────────────────────


class _ConexaoQueFalhaNoMeio:
    """Deixa `_migrar` correr normalmente e estoura no N-ésimo UPDATE de número — queda de
    energia, disco cheio, o que for. Tudo o mais é delegado à conexão real."""

    def __init__(self, conn, falhar_no=2):
        self._conn = conn
        self._falhar_no = falhar_no
        self.updates = 0

    def execute(self, sql, *args, **kwargs):
        if "SET numero_requisicao" in sql:
            self.updates += 1
            if self.updates == self._falhar_no:
                raise sqlite3.OperationalError("disco cheio (simulado)")
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, nome):
        return getattr(self._conn, nome)


def test_rollback_nao_deixa_renumeracao_pela_metade(db, base_legada):
    """Tudo ou nada. Uma renumeração parcial deixaria os dois formatos convivendo e o
    `MAX + 1` da geração apontando para um número já em uso — pior que não migrar."""
    conn = db.get_connection()
    espia = _ConexaoQueFalhaNoMeio(conn, falhar_no=2)
    try:
        with pytest.raises(sqlite3.OperationalError):
            database._migrar(espia)
    finally:
        conn.close()

    assert espia.updates == 2, "o erro precisa cair NO MEIO, com a primeira linha já reescrita"
    # Conexão nova: o que interessa é o que sobrou COMMITADO no arquivo.
    assert set(_numeros_por_id().values()) == {
        "REQ-20260416-007",
        "REQ-20260502-001",
        "REQ-20260807-003",
    }


def test_renumeracao_completa_depois_de_um_rollback(db, base_legada):
    """A falha não pode envenenar a próxima tentativa: o guard continua vendo trabalho."""
    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.OperationalError):
            database._migrar(_ConexaoQueFalhaNoMeio(conn, falhar_no=2))
    finally:
        conn.close()

    with database.transaction() as c:
        database._migrar(c)
    assert sorted(int(n) for n in _numeros_por_id().values()) == [1, 2, 3]


# ── Geração do próximo número ─────────────────────────────────────────────────


def _criar(item, emitente="Ana"):
    ok, num = F.criar_requisicao(
        "MANUTENÇÃO",
        emitente,
        CC,
        "",
        "",
        False,
        [],
        False,
        "",
        [{"item_id": item, "quantidade_solicitada": 1}],
    )
    assert ok, num
    return num


def test_primeira_requisicao_de_um_banco_vazio_e_1(db, make_item):
    item = make_item("PN-PRIMEIRA", estoque=10)
    assert _criar(item) == "1"


def test_numeros_seguem_a_sequencia(db, make_item):
    item = make_item("PN-SEQ", estoque=10)
    assert [_criar(item) for _ in range(3)] == ["1", "2", "3"]


def test_proximo_numero_continua_do_maior_existente(db, base_legada, make_item):
    """Depois da migração o contador é global e retoma em N+1 — não recomeça do 1 a cada
    dia, como fazia o `COUNT` do formato antigo."""
    item = make_item("PN-CONT", estoque=10)
    with database.transaction() as c:
        database._migrar(c)
    assert _criar(item) == "4"


def test_numero_nao_numerico_nao_envenena_o_contador(db, make_item, registrar_consumo):
    """A fixture `registrar_consumo` grava 'REQ-TEST-3-1' por INSERT direto. `CAST` de
    texto com dígito no meio devolveria número ('12A' → 12) e um valor inventado por
    fixture passaria a ditar a sequência real — por isso o filtro é GLOB, não CAST."""
    item = make_item("PN-VENENO", estoque=10)
    registrar_consumo(item)
    assert _criar(item) == "1"


def test_colisao_de_numero_dispara_nova_tentativa(db, make_item, monkeypatch):
    """Contador global = dois almoxarifes podem ler o mesmo `MAX`. O `UNIQUE` sempre
    barrou a colisão; a v6.5.0 passa a reagir a ela em vez de jogar o erro na tela."""
    item = make_item("PN-RETRY", estoque=10)
    primeiro = _criar(item)

    original = F._gerar_numero_requisicao
    chamadas = {"n": 0}

    def _colide_uma_vez(conn):
        chamadas["n"] += 1
        return primeiro if chamadas["n"] == 1 else original(conn)

    monkeypatch.setattr(F, "_gerar_numero_requisicao", _colide_uma_vez)
    segundo = _criar(item)

    assert chamadas["n"] == 2, "a colisão tinha de custar exatamente uma reemissão"
    assert segundo != primeiro
    assert sorted(int(n) for n in _numeros_por_id().values()) == [1, 2]


def test_erro_de_integridade_que_nao_e_o_numero_sobe_na_hora(db, monkeypatch):
    """Repetir três vezes uma FK inválida só esconderia o defeito: o retry é do número, e
    de mais nada."""
    chamadas = {"n": 0}
    original = F._gerar_numero_requisicao

    def _contar(conn):
        chamadas["n"] += 1
        return original(conn)

    monkeypatch.setattr(F, "_gerar_numero_requisicao", _contar)
    ok, msg = F.criar_requisicao(
        "MANUTENÇÃO",
        "Ana",
        CC,
        "",
        "",
        False,
        [],
        False,
        "",
        [{"item_id": 999999, "quantidade_solicitada": 1}],
    )
    assert not ok
    assert chamadas["n"] == 1, "FK inválida não é motivo para reemitir número"


# ── Texto da observação e busca da Portaria ───────────────────────────────────


def test_regex_da_observacao_aceita_os_dois_formatos(db):
    """As 2.320 observações antigas NÃO foram reescritas (a FK é a fonte da verdade). Se o
    regex perdesse o formato velho, o texto voltaria a sujar a coluna Observação."""
    velho = F._RX_OBS_REQ.search("Req REQ-20260504-006")
    novo = F._RX_OBS_REQ.search("Req 123")
    longo = F._RX_OBS_REQ.search("Requisição 1237 · saída retroativa (lançada em 2026-08-07 09:00:00)")

    assert velho.group(1) == "REQ-20260504-006"
    assert novo.group(1) == "123"
    assert longo.group(1) == "1237"


def test_saida_por_requisicao_grava_o_numero_novo_na_observacao(db, make_item):
    """Fecha o ciclo: o texto que a entrega escreve hoje é o que o regex lê amanhã. Também
    é aqui que morre o `REQ-REQ-…` que a UI montava sobre um número já prefixado."""
    item = make_item("PN-OBS", estoque=10)
    numero = _criar(item)
    req_id = F.listar_requisicoes()[0]["id"]
    ok, msg = F.entregar_requisicao(
        req_id,
        [{"item_req_id": F.listar_itens_requisicao(req_id)[0]["id"], "quantidade": 1}],
        "Gestor",
        "Neidson",
    )
    assert ok, msg

    mov = next(m for m in F.listar_movimentacoes(item_id=item, limit=None) if m["tipo"] == "saida")
    assert mov["observacao"] == f"Req {numero}"
    assert "REQ-REQ" not in mov["observacao"]
    assert F._explodir_linha_movimentacao(mov)["Nº Requisição"] == numero


def test_busca_da_portaria_normaliza_zero_a_esquerda(db, make_item):
    """Quem copia de um papel escrito à mão não sabe quantos zeros o sistema guardou."""
    item = make_item("PN-BUSCA", estoque=10)
    numero = _criar(item)

    assert F.buscar_requisicao_por_numero(numero)["numero_requisicao"] == numero
    assert F.buscar_requisicao_por_numero(f"000{numero}")["numero_requisicao"] == numero
    assert F.buscar_requisicao_por_numero(f"  {numero} ")["numero_requisicao"] == numero
    assert F.buscar_requisicao_por_numero("0") is None  # não existe requisição 0


def test_busca_da_portaria_ainda_aceita_cartao_antigo(db, base_legada):
    """Cartões `REQ-…` já impressos continuam circulando pela fábrica DEPOIS da migração —
    e é justamente esse papel que chega na guarita. Ele não acha mais nada (o número foi
    reescrito), mas a busca não pode explodir: devolve "não encontrada", que é a resposta
    honesta, e o porteiro consulta pelo nome."""
    with database.transaction() as c:
        database._migrar(c)

    assert F.buscar_requisicao_por_numero("REQ-20260502-001") is None
    assert F.buscar_requisicao_por_numero("1")["data_hora"].startswith("2026-04-16")
