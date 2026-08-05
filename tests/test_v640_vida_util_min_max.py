"""v6.4.0 — Consumo por vida útil do lote (Épico B) + sugestão de Mín/Máx (Épico C).

O que estes testes protegem:

- **Só recebimento de SC abre lote.** Decisão do Luis em 05/08/2026, medida contra o
  `mro.db` real: das 579 entradas, 145 têm `sc_item_id`. Se um ajuste de inventário
  passasse a abrir lote, o número mudaria para ~270 itens sem ninguém perceber — e a
  carga inicial de 16/04 viraria "um recebimento" que nunca aconteceu.
- **Lote vivo não conta e lote de menos de 1 dia é descartado.** Os dois protegem o mesmo:
  inventar duração produz consumo mensal absurdo (dividir por zero, ou por "hoje").
- **Média simples entre lotes** — a escolha do Luis entre média, mediana e ponderada.
- **A base do Sr. Neidson não é tocada pelo cálculo.** `minimo_calculado` existe
  justamente para NÃO ser `estoque_minimo`; a única escrita na base é o botão da tela.
- **Migração aditiva e idempotente**, com as colunas nascendo preenchidas pelo backfill.
"""

import database
import pytest

from services import classificacao as C
from services import db_functions as F
from services import planejamento as P
from ui.paginas.gerenciar_itens import _difere, _sugestoes_min_max

CC = "21106 - MANUTENÇÃO"


# ── Apoio ─────────────────────────────────────────────────────────────────────


def _mov(item_id, tipo, qtd, quando, saldo_apos=None, sc_item_id=None):
    """Movimentação crua no ledger — o teste controla data, saldo e se é recebimento.

    Inserção direta (e não `registrar_movimentacao`) porque a vida útil do lote depende de
    datas espalhadas por meses e de `sc_item_id`, que a função pública só grava vindo do
    recebimento de SC. `saldo_apos=None` exercita de propósito o ramo do saldo acumulado."""
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,"
            "centro_custo,setor,solicitante,emitente,observacao,sc_item_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, tipo, qtd, saldo_apos, quando, CC, "MANUTENÇÃO", "Joao", "Joao", "", sc_item_id),
        )


def _item_sc_id(numero_sc):
    with database.transaction() as conn:
        row = conn.execute(
            "SELECT isc.id FROM itens_sc isc JOIN solicitacoes_compra s ON s.id=isc.sc_id "
            "WHERE s.numero_sc=?",
            (numero_sc,),
        ).fetchone()
    return row["id"]


def _recebimento(item_id, sc_item_id, qtd, quando, saldo_apos=None):
    """Entrada COM `sc_item_id` — a única que abre lote (decisão do Luis).

    `movimentacoes.sc_item_id` tem FK para `itens_sc`, então o teste precisa de uma linha
    de SC de verdade: inventar o id 1 passa no cálculo e explode no banco."""
    return _mov(item_id, "entrada", qtd, quando, saldo_apos, sc_item_id=sc_item_id)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Épico B — núcleo puro da vida útil
# ══════════════════════════════════════════════════════════════════════════════


def _dt(dia):
    """Dia N a partir de 01/01/2026 (via timedelta — `datetime(2026, 1, 41)` não existe)."""
    from datetime import datetime, timedelta

    return datetime(2026, 1, 1, 8, 0, 0) + timedelta(days=dia - 1)


def test_vida_util_lote_simples():
    """Chegaram 60 em 01/01, bateu o mínimo em 31/01 → 60 ÷ 30 d × 30 = 60/mês."""
    movimentos = [
        (_dt(1), "entrada", 60, 60, True),
        (_dt(31), "saida", 50, 10, False),
    ]
    r = C._vida_util_from_movimentos(movimentos, minimo=10)

    assert r["consumo_mensal"] == 60.0
    assert r["n_lotes"] == 1 and r["n_lotes_vivos"] == 0
    assert r["dias_medio"] == 30.0


def test_vida_util_ignora_entrada_sem_sc():
    """Ajuste de inventário mexe no saldo mas NÃO abre lote (`abre_lote=False`).

    É a decisão do Luis de 05/08/2026 em forma de teste: sem esta linha, a carga inicial do
    inventário viraria "recebimento" e o número passaria a existir para 3× mais itens."""
    movimentos = [
        (_dt(1), "entrada", 60, 60, False),  # ajuste/contagem física
        (_dt(31), "saida", 50, 10, False),
    ]
    r = C._vida_util_from_movimentos(movimentos, minimo=10)

    assert r["consumo_mensal"] is None
    assert r["n_lotes"] == 0 and r["n_lotes_vivos"] == 0


def test_vida_util_lote_vivo_nao_conta():
    """Estoque nunca chegou ao mínimo: o lote não tem fim, então não entra na média."""
    movimentos = [
        (_dt(1), "entrada", 60, 60, True),
        (_dt(20), "saida", 10, 50, False),
    ]
    r = C._vida_util_from_movimentos(movimentos, minimo=10)

    assert r["consumo_mensal"] is None
    assert r["n_lotes"] == 0
    assert r["n_lotes_vivos"] == 1  # continua visível para a UI explicar o "—"


def test_vida_util_media_simples_entre_lotes():
    """Dois lotes (60 em 30 d = 60/mês · 30 em 10 d = 90/mês) → média simples 75/mês.

    Fixa a escolha do Luis: mediana daria 75 também com dois pontos, mas a ponderada por
    quantidade daria 67,5 — por isso o terceiro lote no meio, que separa os três critérios."""
    movimentos = [
        (_dt(1), "entrada", 60, 60, True),
        (_dt(31), "saida", 50, 10, False),  # fecha o 1º: 30 d
        (_dt(1 + 40), "entrada", 30, 40, True),
        (_dt(11 + 40), "saida", 30, 10, False),  # fecha o 2º: 10 d
    ]
    r = C._vida_util_from_movimentos(movimentos, minimo=10)

    assert [x["consumo_mensal"] for x in r["lotes"]] == [60.0, 90.0]
    assert r["consumo_mensal"] == 75.0
    assert r["n_lotes"] == 2


def test_vida_util_lotes_sobrepostos_fecham_juntos():
    """Dois recebimentos antes de o saldo cair: cada lote conta da SUA chegada."""
    movimentos = [
        (_dt(1), "entrada", 50, 50, True),
        (_dt(11), "entrada", 50, 100, True),
        (_dt(21), "saida", 95, 5, False),
    ]
    r = C._vida_util_from_movimentos(movimentos, minimo=10)

    assert [x["dias"] for x in r["lotes"]] == [20, 10]
    assert r["consumo_mensal"] == round((50 / 20 * 30 + 50 / 10 * 30) / 2, 2)


def test_vida_util_minimo_zero_usa_zerar_como_piso():
    """Item sem mínimo cadastrado: o lote dura até ZERAR (fallback do backlog)."""
    movimentos = [
        (_dt(1), "entrada", 30, 30, True),
        (_dt(16), "saida", 25, 5, False),  # 5 > 0: com mínimo 10 fecharia aqui
        (_dt(31), "saida", 5, 0, False),
    ]
    com_piso_zero = C._vida_util_from_movimentos(movimentos, minimo=0)
    com_piso_dez = C._vida_util_from_movimentos(movimentos, minimo=10)

    assert com_piso_zero["lotes"][0]["dias"] == 30
    assert com_piso_dez["lotes"][0]["dias"] == 15  # o mínimo antecipa o fim do lote


def test_vida_util_descarta_lote_de_menos_de_um_dia():
    """Chegou e bateu o mínimo no mesmo dia: sem duração medível (e sem divisão por zero)."""
    from datetime import datetime

    movimentos = [
        (datetime(2026, 1, 1, 8, 0), "entrada", 30, 30, True),
        (datetime(2026, 1, 1, 17, 0), "saida", 25, 5, False),
    ]
    r = C._vida_util_from_movimentos(movimentos, minimo=10)

    assert r["consumo_mensal"] is None
    assert r["n_lotes"] == 0 and r["n_lotes_vivos"] == 0  # fechou, só não é medível


def test_vida_util_recebimento_abaixo_do_minimo_nao_abre_lote():
    """Chegou pouco e o estoque continuou no piso: não há vida útil a medir.

    Sem esta guarda, o item cronicamente em falta — justamente o que mais aparece na fila
    de reposição — teria "lote de 1 dia" e um consumo mensal 30× a quantidade recebida."""
    movimentos = [
        (_dt(1), "entrada", 5, 5, True),  # mínimo é 10: chegou e já está no piso
        (_dt(2), "saida", 1, 4, False),
    ]
    r = C._vida_util_from_movimentos(movimentos, minimo=10)

    assert r["consumo_mensal"] is None
    assert r["n_lotes"] == 0 and r["n_lotes_vivos"] == 0


def test_vida_util_sem_saldo_apos_acumula():
    """`saldo_apos` NULL (movimentação inserida direto no banco) cai no acumulado."""
    movimentos = [
        (_dt(1), "entrada", 60, None, True),
        (_dt(31), "saida", 50, None, False),
    ]
    r = C._vida_util_from_movimentos(movimentos, minimo=10)

    assert r["consumo_mensal"] == 60.0  # 0 + 60 − 50 = 10 → bateu o mínimo


def test_vida_util_sem_movimento_nenhum():
    r = C._vida_util_from_movimentos([], minimo=10)
    assert r == {
        "consumo_mensal": None,
        "n_lotes": 0,
        "n_lotes_vivos": 0,
        "dias_medio": None,
        "lotes": [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. Épico B — leitura do banco
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def lote_no_banco(db, make_item, make_sc):
    """Item com um lote fechado no ledger: chegou 60 em 01/01, bateu o mínimo em 31/01."""

    def _montar(minimo=10):
        item_id = make_item(estoque=0, minimo=minimo)
        make_sc(numero_sc="SC-VIDA", item_id=item_id, quantidade_solicitada=60)
        _recebimento(item_id, _item_sc_id("SC-VIDA"), 60, "2026-01-01 08:00:00", saldo_apos=60)
        _mov(item_id, "saida", 50, "2026-01-31 08:00:00", saldo_apos=minimo)
        return item_id

    return _montar


def test_consumo_por_vida_util_le_o_ledger(lote_no_banco):
    r = C.consumo_por_vida_util(lote_no_banco())

    assert r["n_lotes"] == 1
    assert r["consumo_mensal"] == 60.0


def test_consumo_por_vida_util_entra_na_ficha(lote_no_banco):
    """A Ficha 360 recebe `vida_util` pelo dict que já existia — sem query nova nela."""
    cls = C.classificar_item(lote_no_banco())

    assert cls["vida_util"]["consumo_mensal"] == 60.0
    # e continua trazendo tudo o que a v2.10.0 já trazia
    assert {"demanda", "xyz", "consumo_mensal", "sazonalidade"} <= set(cls)


def test_classificar_todos_nao_carrega_vida_util(lote_no_banco):
    """A vida útil fica FORA da varredura da base inteira, de propósito: `classificar_todos`
    roda dentro de `listar_inventario` e ler o ledger completo por item seria o N+1 que
    aquela função existe para evitar."""
    lote_no_banco()

    mapa = C.classificar_todos()

    assert all("vida_util" not in v for v in mapa.values())


def test_movimentos_item_marca_so_recebimento(db, make_item, make_sc):
    """`abre_lote` só é True para entrada com `sc_item_id` — o predicado de ENTRADA_REAL."""
    item_id = make_item(estoque=0, minimo=10)
    make_sc(numero_sc="SC-VIDA", item_id=item_id, quantidade_solicitada=10)
    _recebimento(item_id, _item_sc_id("SC-VIDA"), 10, "2026-02-01 08:00:00", saldo_apos=10)
    _mov(item_id, "entrada", 5, "2026-02-02 08:00:00", saldo_apos=15)  # ajuste avulso

    with database.transaction() as conn:
        movimentos = C._movimentos_item(conn, item_id)

    assert [m[4] for m in movimentos if m[1] == "entrada"] == [True, False]  # SC, ajuste


# ══════════════════════════════════════════════════════════════════════════════
# 3. Épico C — fórmula do Mín/Máx
# ══════════════════════════════════════════════════════════════════════════════


def test_min_max_sugerido_usa_lead_time_e_60_dias():
    """min = consumo × lead time · max = consumo × 60 d (fórmulas travadas)."""
    item = {"consumo_medio_diario": 2.0, "lead_time_dias": 15}

    r = P.calcular_min_max_sugerido(item)

    assert r["minimo"] == 30.0  # 2 × 15
    assert r["maximo"] == 120.0  # 2 × 60
    assert r["lead_time"] == 15
    assert "cadastrado" in r["origem"]


def test_min_max_prefere_o_lead_time_calculado():
    """Pedido do Luis (05/08/2026): a sugestão automática usa o lead time AUTOMÁTICO.

    Inverso proposital de `lead_time_efetivo` (que o ROP usa): lá a base do Neidson tem
    prioridade porque decide compra real; aqui o número se propõe a dizer "o que os dados
    mostram", e usar o lead time digitado à mão o tornaria metade empírico, metade cadastral."""
    item = {
        "consumo_medio_diario": 2.0,
        "lead_time_dias": 20,  # cadastrado (genérico)
        "lead_time_calculado": 7,  # medido em recebimentos reais
        "lead_time_calculado_amostras": 33,
        "lead_time_calculado_origem": "SC7",
    }

    r = P.calcular_min_max_sugerido(item)

    assert r["lead_time"] == 7  # o calculado venceu
    assert r["minimo"] == 14.0  # 2 × 7, e não 2 × 20
    assert "calculado (SC7, 33 amostra(s))" in r["origem"]


def test_min_max_diverge_do_rop_de_proposito():
    """Os dois são `consumo × lead time`, mas escolhem lead times diferentes.

    Em 103 dos 104 itens com lead time calculado no `mro.db` real os números divergem — se
    algum dia voltarem a bater por acidente, este teste avisa que uma das duas preferências
    mudou sem intenção."""
    item = {"consumo_medio_diario": 2.0, "lead_time_dias": 20, "lead_time_calculado": 7}

    assert P.calcular_min_max_sugerido(item)["minimo"] == 14.0
    assert P.calcular_ponto_reposicao(item)["rop"] == 40.0  # ROP segue no cadastrado


def test_min_max_cai_no_cadastrado_sem_calculado():
    """Sem lead time calculado, a sugestão usa o cadastrado — a maioria da base."""
    item = {"consumo_medio_diario": 2.0, "lead_time_dias": 15}

    r = P.calcular_min_max_sugerido(item)

    assert r["lead_time"] == 15 and r["minimo"] == 30.0
    assert "cadastrado" in r["origem"]


def test_min_max_sugerido_sem_consumo():
    """Sem consumo não há sugestão: zeros com origem explícita, para a UI mostrar '—'
    em vez de propor mínimo zero (que mandaria o item para a fila de reposição)."""
    r = P.calcular_min_max_sugerido({"consumo_medio_diario": 0, "lead_time_dias": 20})

    assert (r["minimo"], r["maximo"]) == (0.0, 0.0)
    assert r["origem"] == "sem consumo registrado"


def test_min_max_sugerido_cai_no_lead_time_default():
    """Item sem lead time nenhum usa o default de 30 d, rotulado como tal."""
    r = P.calcular_min_max_sugerido({"consumo_medio_diario": 1.0})

    assert r["minimo"] == 30.0
    assert "default" in r["origem"]


def test_min_max_sugerido_sem_amostras_nao_sugere():
    """Guarda paga em dado real: `consumo_medio_diario` é coluna PERSISTIDA e congela no
    valor do dia em que o item parou de se mover.

    No `mro.db` de 05/08/2026, o PN 34FR0001 tem uma saída de 99.999 unidades em 30/06
    (erro de digitação) e ficou com 3.333/dia, com `consumo_30d` já em 0. Sem esta guarda,
    a visão em lote proporia mínimo 66.666 para um item de mínimo 5 — e um clique
    reescreveria a base do Sr. Neidson."""
    item = {"consumo_medio_diario": 3333.3, "lead_time_dias": 20}

    assert P.calcular_min_max_sugerido(item, amostras=0)["minimo"] == 0.0
    assert "desatualizado" in P.calcular_min_max_sugerido(item, amostras=0)["origem"]
    # com lastro, a fórmula volta a valer
    assert P.calcular_min_max_sugerido(item, amostras=3)["minimo"] == 66666.0
    # amostras=None = uso puro da fórmula (sem a checagem)
    assert P.calcular_min_max_sugerido(item)["minimo"] == 66666.0


# ══════════════════════════════════════════════════════════════════════════════
# 4. Épico C — persistência e migração
# ══════════════════════════════════════════════════════════════════════════════


def test_migracao_min_max_e_saldo(db):
    """Colunas presentes e idempotentes — o app roda `criar_banco` a cada abertura."""
    with db.transaction() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(inventario)")]
    esperadas = {
        "minimo_calculado",
        "maximo_calculado",
        "min_max_amostras",
        "min_max_origem",
        "mostrar_saldo_requisitante",
    }
    assert esperadas <= set(cols)

    db.criar_banco()
    with db.transaction() as conn:
        cols2 = [r[1] for r in conn.execute("PRAGMA table_info(inventario)")]
    assert cols == cols2


def test_mostrar_saldo_nasce_ligado(db, make_item):
    """Default 1: a base inteira abre visível, como o Luis pediu."""
    item_id = make_item()
    assert F.buscar_item_por_id(item_id)["mostrar_saldo_requisitante"] == 1


def _com_consumo_recente(item_id, consumo=2.0, saidas=3):
    """Consumo persistido + saídas DENTRO da janela de 30 d.

    As saídas são o que dá lastro ao número: sem nenhuma, a sugestão é suprimida de
    propósito (ver `test_min_max_sugerido_sem_amostras_nao_sugere`), então um teste que
    só escrevesse `consumo_medio_diario` estaria medindo o caminho errado."""
    from datetime import datetime, timedelta

    with database.transaction() as conn:
        conn.execute("UPDATE inventario SET consumo_medio_diario=? WHERE id=?", (consumo, item_id))
    for n in range(saidas):
        quando = (datetime.now() - timedelta(days=n + 1)).strftime("%Y-%m-%d %H:%M:%S")
        _mov(item_id, "saida", 1, quando, saldo_apos=None)


def test_recalcular_min_max_grava_sem_tocar_a_base(db, make_item):
    """A escrita automática vai só para as colunas `*_calculado`.

    É a regra inviolável nº1 do Mín/Máx: `estoque_minimo`/`estoque_maximo` são do Sr.
    Neidson e só mudam por clique explícito."""
    item_id = make_item(estoque=100, minimo=10, lead=15)
    _com_consumo_recente(item_id)

    F.recalcular_min_max_calculado(item_id)

    item = F.buscar_item_por_id(item_id)
    assert item["minimo_calculado"] == 30.0 and item["maximo_calculado"] == 120.0
    assert item["estoque_minimo"] == 10  # base intacta
    assert item["min_max_amostras"] == 3
    assert item["min_max_origem"] and "lead time" in item["min_max_origem"]


def test_recalcular_min_max_suprime_consumo_sem_lastro(db, make_item):
    """Consumo persistido alto e NENHUMA saída na janela → sem sugestão, base intacta."""
    item_id = make_item(estoque=100, minimo=5, lead=20)
    with database.transaction() as conn:
        conn.execute("UPDATE inventario SET consumo_medio_diario=3333.3 WHERE id=?", (item_id,))

    F.recalcular_min_max_calculado(item_id)

    item = F.buscar_item_por_id(item_id)
    assert item["minimo_calculado"] == 0.0 and item["min_max_amostras"] == 0
    assert "desatualizado" in item["min_max_origem"]
    assert item["estoque_minimo"] == 5


def test_min_max_acompanha_o_consumo(db, make_item, registrar_consumo):
    """Saída nova → `_recalcular_consumo` → sugestão atualizada na mesma transação."""
    item_id = make_item(estoque=100, minimo=10, lead=10)
    registrar_consumo(item_id, quantidade=30, data_hora="2026-06-01 08:00:00")

    ok, msg = F.registrar_movimentacao(item_id, "saida", 30, CC, "Joao", "Joao")
    assert ok, msg

    item = F.buscar_item_por_id(item_id)
    assert item["minimo_calculado"] > 0
    assert item["min_max_amostras"] >= 1


def test_min_max_acompanha_o_lead_time(db, make_item):
    """Trocar o lead time no cadastro recalcula a sugestão junto — a outra metade da conta."""
    item_id = make_item(estoque=100, minimo=10, lead=10)
    _com_consumo_recente(item_id)
    F.recalcular_min_max_calculado(item_id)
    antes = F.buscar_item_por_id(item_id)["minimo_calculado"]

    ok, msg = F.atualizar_item_inventario(item_id, {"lead_time_dias": 40})
    assert ok, msg

    assert F.buscar_item_por_id(item_id)["minimo_calculado"] == 80.0  # 2 × 40
    assert antes == 20.0  # 2 × 10


def test_min_max_calculado_nao_e_editavel_pela_tela(db, make_item):
    """`minimo_calculado` fora do `allowed_fields`: é derivado, não campo de formulário."""
    item_id = make_item()

    ok, _ = F.atualizar_item_inventario(item_id, {"minimo_calculado": 999})

    assert ok is False  # nenhum campo válido no payload
    assert (F.buscar_item_por_id(item_id)["minimo_calculado"] or 0) != 999


# ══════════════════════════════════════════════════════════════════════════════
# 5. Épico C — visão em lote (funções puras da tela)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "calc,cad,esperado",
    [(30, 10, True), (10, 10, False), (10.4, 10, False), (11, 10, True), (0, 0, False)],
)
def test_difere_tem_tolerancia_de_uma_unidade(calc, cad, esperado):
    """Sem tolerância, 10 × 10,4 apareceria como divergente e a lista viraria ruído."""
    assert _difere(calc, cad) is esperado


def test_sugestoes_em_lote_filtra_o_que_importa():
    itens = [
        {
            "id": 1,
            "part_number": "B",
            "nome_item": "x",
            "minimo_calculado": 30,
            "maximo_calculado": 120,
            "estoque_minimo": 10,
            "estoque_maximo": 20,
            "min_max_amostras": 3,
            "min_max_origem": "o",
        },
        {
            "id": 2,
            "part_number": "A",
            "nome_item": "y",
            "minimo_calculado": 0,
            "maximo_calculado": 0,
            "estoque_minimo": 5,
            "estoque_maximo": 10,
        },  # sem consumo: não entra
        {
            "id": 3,
            "part_number": "C",
            "nome_item": "z",
            "minimo_calculado": 10,
            "maximo_calculado": 20,
            "estoque_minimo": 10,
            "estoque_maximo": 20,
        },  # já alinhado: não entra
    ]

    linhas = _sugestoes_min_max(itens)

    assert [linha["id"] for linha in linhas] == [1]
    assert linhas[0]["Aplicar"] is False  # nada nasce marcado


def test_recalcular_em_massa_atualiza_formula_antiga(db, make_item):
    """O botão "Recalcular tudo" da aba em lote — a saída para banco já migrado.

    O backfill da migração roda UMA VEZ só (guardado por `minimo_calculado not in
    cols_inv0`), então quem migrou antes de uma mudança de fórmula fica com o número da
    regra antiga até o item se mexer. Aconteceu de verdade: o `mro.db` do Luis migrou com a
    versão que preferia o lead time CADASTRADO, e a troca para o CALCULADO não apareceria
    sozinha. Simulado aqui gravando um valor obsoleto direto na coluna."""
    item_id = make_item(estoque=100, minimo=10, lead=20)
    _com_consumo_recente(item_id)
    with database.transaction() as conn:
        conn.execute(
            """UPDATE inventario
               SET lead_time_calculado=7, lead_time_calculado_amostras=33,
                   lead_time_calculado_origem='SC7',
                   minimo_calculado=40.0, min_max_origem='formula antiga'
               WHERE id=?""",
            (item_id,),
        )

    n = F.recalcular_min_max_calculado()

    item = F.buscar_item_por_id(item_id)
    assert n >= 1
    assert item["minimo_calculado"] == 14.0  # 2 × 7 (calculado), não 2 × 20 (cadastrado)
    assert "calculado (SC7" in item["min_max_origem"]


def test_aplicar_em_lote_grava_a_base(db, make_item):
    """O caminho que a aba em lote usa: `atualizar_item_inventario` com mín E máx."""
    item_id = make_item(estoque=100, minimo=10)

    ok, msg = F.atualizar_item_inventario(item_id, {"estoque_minimo": 30.0, "estoque_maximo": 120.0})
    assert ok, msg

    item = F.buscar_item_por_id(item_id)
    assert (item["estoque_minimo"], item["estoque_maximo"]) == (30.0, 120.0)
