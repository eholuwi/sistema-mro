"""v6.5.0 — Task 1: o consumo por PEDIDO alimenta o Mín/Máx sugerido.

`calcular_min_max_sugerido` passa a preferir `consumo_sc7_diario` a
`consumo_medio_diario`, exatamente como `lead_time_para_sugestao` prefere o lead time
calculado ao cadastrado — e pela mesma razão: a sugestão se propõe a dizer "o que os dados
mostram", e o consumo por pedido atendido é o dado mais forte que existe.

Os dois invariantes que este arquivo trava:

1. **Com SC7 o número muda e a `origem` diz de onde veio.** O gestor não aceita um Mín/Máx
   sem saber que conta o produziu.
2. **Sem SC7 o comportamento é bit a bit o da v6.4.0** — os 18 testes do Épico C
   (`test_v640_vida_util_min_max.py`) continuam verdes porque a fórmula antiga não mudou.

A terceira regra é de escopo: **só pedido de compra** vira `consumo_sc7_diario`. Saída de
almoxarifado nunca entra — nem aqui, nem no card da Ficha (decisão do Luis, 11/08/2026).
`n_pedidos >= 1` é a guarda equivalente ao `amostras > 0` da janela de 30 d: sem compra no
período, a sugestão continua sendo a da v6.4.0.
"""

from datetime import date, datetime, timedelta

import pandas as pd

import database
from services import db_functions as F
from services import planejamento as P

ROTULO = "SC7 2026 (jan–jul)"


def _pedido_sc7(produto="PN-MM", numero_pc="F900", emissao="2025-06-01", entregue=360):
    return {
        "Numero PC": numero_pc,
        "DT Emissao": emissao,
        "Produto": produto,
        "Descricao": "Item",
        "Unidade": "UN",
        "Quantidade": entregue,
        "Qtd.Entregue": entregue,
        "Saldo": 0,
    }


def _saida_recente(item_id, registrar_consumo, dias=2):
    """Saída real DENTRO da janela de 30 d — é ela que dá lastro ao `consumo_medio_diario`
    e faz `_amostras_consumo_30d` devolver > 0."""
    quando = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    return registrar_consumo(item_id, quantidade=30, data_hora=quando)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Fórmula pura
# ══════════════════════════════════════════════════════════════════════════════


def test_sc7_vence_o_consumo_medio_diario():
    item = {
        "consumo_medio_diario": 2.0,
        "consumo_sc7_diario": 5.0,
        "consumo_sc7_rotulo": ROTULO,
        "lead_time_dias": 10,
    }

    r = P.calcular_min_max_sugerido(item)

    assert r["consumo_diario"] == 5.0
    assert (r["minimo"], r["maximo"]) == (50.0, 300.0)  # 5 × 10 · 5 × 60
    assert r["origem"] == f"consumo {ROTULO} × lead time cadastrado (Compras)"


def test_sem_sc7_reproduz_o_numero_da_v640():
    """Não-regressão do Épico C: a ausência da chave (ou zero) não pode mudar nada."""
    item = {"consumo_medio_diario": 2.0, "lead_time_dias": 15}

    base = P.calcular_min_max_sugerido(item)

    assert base == P.calcular_min_max_sugerido({**item, "consumo_sc7_diario": 0})
    assert base == P.calcular_min_max_sugerido({**item, "consumo_sc7_diario": None})
    assert base["minimo"] == 30.0
    assert base["origem"] == "consumo 30d × lead time cadastrado (Compras)"


def test_guarda_de_amostras_nao_se_aplica_ao_sc7():
    """`amostras=0` suprime a sugestão do consumo PERSISTIDO (o caso 34FR0001, que congela
    no dia em que o item parou). O SC7 é derivado na leitura a cada consulta e não tem esse
    defeito — a guarda dele é `n_pedidos >= 1`, aplicada em `consumo_sc7_por_item`."""
    item = {"consumo_medio_diario": 3333.3, "consumo_sc7_diario": 2.0, "lead_time_dias": 20}

    assert P.calcular_min_max_sugerido(item, amostras=0)["minimo"] == 40.0  # 2 × 20
    # sem SC7, a mesma chamada continua suprimida
    assert P.calcular_min_max_sugerido({**item, "consumo_sc7_diario": 0}, amostras=0)["minimo"] == 0.0


def test_sc7_convive_com_a_preferencia_pelo_lead_time_calculado():
    """As duas preferências são independentes: consumo do pedido × lead time medido."""
    item = {
        "consumo_medio_diario": 2.0,
        "consumo_sc7_diario": 1.0,
        "consumo_sc7_rotulo": ROTULO,
        "lead_time_dias": 20,
        "lead_time_calculado": 7,
        "lead_time_calculado_amostras": 33,
        "lead_time_calculado_origem": "SC7",
    }

    r = P.calcular_min_max_sugerido(item)

    assert (r["minimo"], r["lead_time"]) == (7.0, 7)  # 1 × 7, e não 2 × 20
    assert r["origem"] == f"consumo {ROTULO} × lead time calculado (SC7, 33 amostra(s))"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Persistência — `recalcular_min_max_calculado`
# ══════════════════════════════════════════════════════════════════════════════


def test_recalcular_usa_o_sc7_e_nomeia_a_fonte(db, make_item, registrar_consumo):
    """360 entregues no ano passado ÷ 12 = 30/mês ÷ 30 = 1/dia → mínimo 10 (e não 20, que
    é o que o `consumo_medio_diario` de 2/dia daria)."""
    item_id = make_item("PN-MM", estoque=100, minimo=5, lead=10)
    _saida_recente(item_id, registrar_consumo)
    with database.transaction() as c:
        c.execute("UPDATE inventario SET consumo_medio_diario=2.0 WHERE id=?", (item_id,))
    F.ingerir_sc7_consumo(pd.DataFrame([_pedido_sc7(emissao=f"{date.today().year - 1}-06-01")]), "c.xlsx")

    F.recalcular_min_max_calculado(item_id)

    item = F.buscar_item_por_id(item_id)
    assert (item["minimo_calculado"], item["maximo_calculado"]) == (10.0, 60.0)
    assert item["min_max_origem"].startswith(f"consumo SC7 {date.today().year - 1} ×")
    assert item["estoque_minimo"] == 5  # base do Neidson intacta


def test_recalcular_sem_sc7_mantem_o_numero_da_v640(db, make_item, registrar_consumo):
    item_id = make_item("PN-SEM-SC7", estoque=100, minimo=5, lead=10)
    _saida_recente(item_id, registrar_consumo)
    with database.transaction() as c:
        c.execute("UPDATE inventario SET consumo_medio_diario=2.0 WHERE id=?", (item_id,))

    F.recalcular_min_max_calculado(item_id)

    item = F.buscar_item_por_id(item_id)
    assert (item["minimo_calculado"], item["maximo_calculado"]) == (20.0, 120.0)  # 2 × 10 · 2 × 60
    assert item["min_max_origem"].startswith("consumo 30d ×")


def test_saida_real_nao_entra_no_min_max(db, make_item, registrar_consumo):
    """Item com saída real e SEM pedido de compra: a sugestão continua saindo da janela de
    30 d. Deixar a saída virar `consumo_sc7_diario` mudaria o Mín/Máx da base inteira sem
    nenhuma compra que justificasse — medindo o mesmo dado com outro divisor."""
    item_id = make_item("PN-SAI-MM", estoque=100, minimo=5, lead=10)
    _saida_recente(item_id, registrar_consumo)
    with database.transaction() as c:
        c.execute("UPDATE inventario SET consumo_medio_diario=2.0 WHERE id=?", (item_id,))

    F.recalcular_min_max_calculado(item_id)

    item = F.buscar_item_por_id(item_id)
    assert item["minimo_calculado"] == 20.0
    assert item["min_max_origem"].startswith("consumo 30d ×")


def test_pn_do_sc7_fora_do_inventario_nao_atrapalha_a_base(db, make_item, registrar_consumo):
    """A tabela guarda PN sem item (de propósito); o join por texto simplesmente não casa,
    e o recálculo em lote segue o caminho antigo para todo mundo."""
    item_id = make_item("PN-MM", estoque=100, minimo=5, lead=10)
    _saida_recente(item_id, registrar_consumo)
    with database.transaction() as c:
        c.execute("UPDATE inventario SET consumo_medio_diario=2.0 WHERE id=?", (item_id,))
    F.ingerir_sc7_consumo(pd.DataFrame([_pedido_sc7(produto="PN-DE-OUTRO-MUNDO")]), "c.xlsx")

    assert F.recalcular_min_max_calculado() >= 1

    assert F.buscar_item_por_id(item_id)["minimo_calculado"] == 20.0
