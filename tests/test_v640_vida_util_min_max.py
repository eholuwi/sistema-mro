"""v6.4.0 — sugestão automática de Mín/Máx (Épico C).

⚠️ **Os 14 testes do Épico B (consumo por vida útil do lote) saíram na v6.5.0**, junto com
o cálculo que protegiam: a vida útil foi substituída pelo consumo por PEDIDO DE COMPRA
atendido (`tests/test_v650_consumo_sc7.py`). O arquivo mantém o nome porque o Épico C, que
continua aqui inteiro, nasceu nesta mesma versão.

O que estes testes protegem:

- **A base do Sr. Neidson não é tocada pelo cálculo.** `minimo_calculado` existe
  justamente para NÃO ser `estoque_minimo`; a única escrita na base é o botão da tela.
- **A sugestão prefere o lead time CALCULADO ao cadastrado** — inverso proposital do ROP.
- **Consumo persistido sem saída recente não sugere nada** (o caso 34FR0001).
- **Migração aditiva e idempotente**, com as colunas nascendo preenchidas pelo backfill.
"""

import database
import pytest

from services import db_functions as F
from services import planejamento as P
from ui.paginas.gerenciar_itens import _difere, _sugestoes_min_max

CC = "21106 - MANUTENÇÃO"


# ── Apoio ─────────────────────────────────────────────────────────────────────


def _mov(item_id, tipo, qtd, quando, saldo_apos=None, sc_item_id=None):
    """Movimentação crua no ledger — o teste controla data, saldo e se é recebimento.

    Inserção direta (e não `registrar_movimentacao`) porque as saídas precisam cair em
    datas específicas dentro da janela de 30 d, e `saldo_apos=None` exercita de propósito
    o ramo em que a coluna não foi gravada."""
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,"
            "centro_custo,setor,solicitante,emitente,observacao,sc_item_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, tipo, qtd, saldo_apos, quando, CC, "MANUTENÇÃO", "Joao", "Joao", "", sc_item_id),
        )


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
