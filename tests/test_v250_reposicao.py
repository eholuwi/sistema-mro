"""v2.5.0 — Assistente de Reposição (Motor de Planejamento).

Cobre: parâmetros efetivos (lead time / estoque de segurança sem sobrescrever a
base do Neidson), ROP, gatilho de reposição com antecedência de 15 d, quantidade
sugerida HÍBRIDA (alvo = max(EstMáx Neidson, consumo×60) − estoque − guarda-chuva),
priorização, justificativa, agrupamento por fornecedor, geração da fila via
listar_inventario, ponte para "Criar SC" (reusa criar_sc) e auditoria de desfecho.
"""
import pytest

import database
from services import db_functions as F
from services import planejamento as P
from services.constants import (
    HORIZONTE_REPOSICAO_DIAS, ANTECEDENCIA_REPOSICAO_DIAS, LEAD_TIME_DEFAULT_DIAS,
)


# ── Fábrica de item sintético (mesmas chaves de listar_inventario) ──────────────

def _item(**over):
    base = dict(
        id=1, part_number="PN-1", nome_item="Item", unidade="UN",
        setor_responsavel="Improdutivo", importancia="Importante",
        estoque_atual=0.0, estoque_em_transito=0.0,
        estoque_minimo=0.0, estoque_maximo=0.0,
        estoque_seguranca=0.0, estoque_seguranca_calculado=0.0,
        consumo_medio_diario=0.0, dias_cobertura=999,
        tendencia_label=None, tendencia_pct=0.0,
        lead_time_dias=0, lead_time_calculado=None,
        lead_time_calculado_amostras=0, lead_time_calculado_origem=None,
    )
    base.update(over)
    return base


def _set_inv(item_id, **campos):
    """Seta campos do inventário direto (determinismo dos cálculos de série)."""
    sets = ", ".join(f"{k}=?" for k in campos)
    with database.transaction() as c:
        c.execute(f"UPDATE inventario SET {sets} WHERE id=?",
                  (*campos.values(), item_id))


# ══════════════════════════════════════════════════════════════════════════════
# PARÂMETROS EFETIVOS (não sobrescrevem a base)
# ══════════════════════════════════════════════════════════════════════════════

def test_lead_time_cadastrado_tem_prioridade():
    lt, origem, mat = P.lead_time_efetivo(_item(lead_time_dias=20, lead_time_calculado=99))
    assert lt == 20
    assert "Neidson" in origem
    assert mat is None


def test_lead_time_fallback_calculado_rotulado():
    lt, origem, mat = P.lead_time_efetivo(
        _item(lead_time_dias=0, lead_time_calculado=13,
              lead_time_calculado_amostras=4, lead_time_calculado_origem="SC7"))
    assert lt == 13
    assert "calculado" in origem and "SC7" in origem
    assert mat == "sugestão"


def test_lead_time_default_quando_desconhecido():
    lt, origem, mat = P.lead_time_efetivo(_item(lead_time_dias=0, lead_time_calculado=None))
    assert lt == LEAD_TIME_DEFAULT_DIAS
    assert mat == "lead time desconhecido"


def test_estoque_seguranca_manual_tem_prioridade():
    ss, origem = P.estoque_seguranca_efetivo(
        _item(estoque_seguranca=25, estoque_seguranca_calculado=99))
    assert ss == 25 and "manual" in origem


def test_estoque_seguranca_fallback_calculado():
    ss, origem = P.estoque_seguranca_efetivo(
        _item(estoque_seguranca=0, estoque_seguranca_calculado=8))
    assert ss == 8 and "calculado" in origem


# ══════════════════════════════════════════════════════════════════════════════
# ROP + GATILHO
# ══════════════════════════════════════════════════════════════════════════════

def test_rop_formula():
    calc = P.calcular_ponto_reposicao(
        _item(consumo_medio_diario=2.0, lead_time_dias=10, estoque_seguranca=5))
    assert calc["rop"] == pytest.approx(2.0 * 10 + 5)  # 25


def test_bem_estocado_nao_repor():
    item = _item(consumo_medio_diario=1.0, lead_time_dias=10, estoque_atual=100,
                 estoque_minimo=10)
    assert P.precisa_repor(item) is False


def test_dentro_da_antecedencia_repor():
    # rop=10, gatilho=10+1*15=25; disp=20 -> antecipar
    item = _item(consumo_medio_diario=1.0, lead_time_dias=10, estoque_atual=20,
                 estoque_minimo=5)
    assert P.precisa_repor(item) is True
    assert P.classificar_prioridade(item)["tier"] == 1  # 🟠


def test_abaixo_do_rop_e_critico():
    item = _item(consumo_medio_diario=1.0, lead_time_dias=10, estoque_atual=8,
                 estoque_minimo=5)
    assert P.precisa_repor(item) is True
    assert P.classificar_prioridade(item)["tier"] == 0  # 🔴


def test_guarda_chuva_conta_como_disponivel():
    # disp = estoque(8) + guarda-chuva(30) = 38 > gatilho(25) -> não repor
    item = _item(consumo_medio_diario=1.0, lead_time_dias=10, estoque_atual=8,
                 estoque_em_transito=30, estoque_minimo=5)
    assert P.precisa_repor(item) is False


def test_consumo_zero_acima_do_minimo_nao_gera_ruido():
    item = _item(consumo_medio_diario=0.0, estoque_atual=50, estoque_minimo=10)
    assert P.precisa_repor(item) is False


def test_consumo_zero_piso_do_neidson_furado_repor():
    item = _item(consumo_medio_diario=0.0, estoque_atual=5, estoque_minimo=10,
                 estoque_maximo=20)
    assert P.precisa_repor(item) is True
    assert P.classificar_prioridade(item)["tier"] == 2  # 🟡


def test_sem_consumo_nunca_e_critico():
    # Estoque 0, Parada de Linha, mas SEM consumo -> não há relógio de ruptura:
    # é 🟡 Atenção (tier 2), não 🔴 Crítico. Criticidade fica só no rótulo.
    item = _item(consumo_medio_diario=0.0, estoque_atual=0, estoque_minimo=5,
                 estoque_maximo=20, importancia="Parada de Linha")
    pr = P.classificar_prioridade(item)
    assert pr["tier"] == 2
    assert "🔴" not in pr["rotulo"]
    assert "Parada de Linha" in pr["rotulo"]


# ══════════════════════════════════════════════════════════════════════════════
# QUANTIDADE SUGERIDA (alvo HÍBRIDO)
# ══════════════════════════════════════════════════════════════════════════════

def test_qtd_horizonte_domina():
    # consumo alto: alvo = consumo*60 = 120 > EstMáx 40
    q = P.calcular_qtd_sugerida(
        _item(consumo_medio_diario=2.0, estoque_maximo=40, estoque_atual=10))
    assert q["alvo"] == pytest.approx(2.0 * HORIZONTE_REPOSICAO_DIAS)  # 120
    assert q["alvo_origem"].startswith("horizonte")
    assert q["qtd"] == 110  # 120 - 10 - 0


def test_qtd_neidson_domina():
    # consumo baixo: EstMáx 100 > consumo*60 = 6
    q = P.calcular_qtd_sugerida(
        _item(consumo_medio_diario=0.1, estoque_maximo=100, estoque_atual=40))
    assert q["alvo"] == 100
    assert q["alvo_origem"] == "máx. Neidson"
    assert q["qtd"] == 60  # 100 - 40


def test_qtd_desconta_guarda_chuva_e_nunca_negativa():
    q = P.calcular_qtd_sugerida(
        _item(consumo_medio_diario=1.0, estoque_maximo=50, estoque_atual=40,
              estoque_em_transito=30))
    # alvo = max(50, 60) = 60; 60 - 40 - 30 = -10 -> 0
    assert q["alvo"] == 60
    assert q["qtd"] == 0


def test_qtd_arredonda_para_cima():
    q = P.calcular_qtd_sugerida(
        _item(consumo_medio_diario=0.5, estoque_maximo=0, estoque_atual=0))
    # alvo = 0.5*60 = 30.0 -> qtd 30 (exato). Testa fração:
    q2 = P.calcular_qtd_sugerida(
        _item(consumo_medio_diario=0.51, estoque_maximo=0, estoque_atual=0))
    assert q2["qtd"] == 31  # ceil(30.6)


# ══════════════════════════════════════════════════════════════════════════════
# PRIORIDADE / JUSTIFICATIVA / AGRUPAMENTO
# ══════════════════════════════════════════════════════════════════════════════

def test_parada_de_linha_eleva_rotulo():
    item = _item(consumo_medio_diario=1.0, lead_time_dias=10, estoque_atual=8,
                 importancia="Parada de Linha")
    pr = P.classificar_prioridade(item)
    assert pr["parada_linha"] is True
    assert "Parada de Linha" in pr["rotulo"]


def test_justificativa_mastigada_contem_numeros():
    item = _item(consumo_medio_diario=3.0, lead_time_dias=20, estoque_atual=24,
                 estoque_maximo=100, dias_cobertura=8, tendencia_label="Alta",
                 tendencia_pct=22.0)
    txt = P.montar_justificativa(item)
    assert "lead time 20 d" in txt
    assert "antecedência" in txt
    assert "tendência Alta" in txt
    assert "sugerido" in txt and "UN" in txt


def test_agrupar_por_fornecedor():
    sugestoes = [
        {"fornecedor_sugerido": "Forn A", "prioridade_tier": 1},
        {"fornecedor_sugerido": "Forn A", "prioridade_tier": 0},
        {"fornecedor_sugerido": None, "prioridade_tier": 2},
    ]
    grupos = P.agrupar_por_fornecedor(sugestoes)
    assert len(grupos["Forn A"]) == 2
    assert "Sem fornecedor sugerido" in grupos
    # Forn A (tier mín 0) vem antes do grupo sem fornecedor (tier 2).
    assert list(grupos.keys())[0] == "Forn A"


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

def test_schema_sugestoes_reposicao(db):
    with database.transaction() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(sugestoes_reposicao)")}
    assert {"item_id", "qtd_sugerida", "desfecho", "sc_id", "justificativa"} <= cols


# ══════════════════════════════════════════════════════════════════════════════
# GERAÇÃO DA FILA (integração via listar_inventario)
# ══════════════════════════════════════════════════════════════════════════════

def test_gerar_fila_filtra_e_prioriza(db, make_item):
    critico = make_item("PN-CRIT", estoque=8, minimo=5, lead=10,
                        importancia="Parada de Linha")
    ok_item = make_item("PN-OK", estoque=200, minimo=10, lead=10)
    _set_inv(critico, consumo_medio_diario=1.0)
    _set_inv(ok_item, consumo_medio_diario=1.0)

    fila = P.gerar_sugestoes_reposicao(incluir_fornecedor=False)
    pns = [s["part_number"] for s in fila]
    assert "PN-CRIT" in pns
    assert "PN-OK" not in pns          # bem estocado -> fora da fila
    assert fila[0]["part_number"] == "PN-CRIT"
    assert fila[0]["qtd_sugerida"] > 0


def test_gerar_fila_desconta_guarda_chuva(db, make_item, make_sc):
    item_id = make_item("PN-GC", estoque=8, minimo=5, lead=10)
    _set_inv(item_id, consumo_medio_diario=1.0, estoque_maximo=60)
    # Sem guarda-chuva: alvo=max(60, 60)=60; qtd = 60-8 = 52
    fila = P.gerar_sugestoes_reposicao(incluir_fornecedor=False)
    assert fila[0]["qtd_sugerida"] == 52

    # Cria SC aberta de 30 -> guarda-chuva 30; disp=8+30=38 <= gatilho(25)? não.
    # 38 > 25 -> sai da fila (já vem material a caminho).
    make_sc(numero_sc="SC-GC", item_id=item_id, quantidade_solicitada=30)
    fila2 = P.gerar_sugestoes_reposicao(incluir_fornecedor=False)
    assert all(s["part_number"] != "PN-GC" for s in fila2)


# ══════════════════════════════════════════════════════════════════════════════
# PONTE PARA "CRIAR SC" (reusa criar_sc)
# ══════════════════════════════════════════════════════════════════════════════

def test_criar_sc_a_partir_da_sugestao(db, make_item):
    item_id = make_item("PN-SC5", estoque=8, minimo=5, lead=10)
    _set_inv(item_id, consumo_medio_diario=1.0, estoque_maximo=60)
    fila = P.gerar_sugestoes_reposicao(incluir_fornecedor=False)
    sug = next(s for s in fila if s["part_number"] == "PN-SC5")

    item_sc = P.sugestao_para_item_sc(sug, data_necessidade="2026-07-20")
    ok, msg = F.criar_sc("SC-REP-1", "2026-07-05", [item_sc], "gerada pelo Assistente")
    assert ok, msg

    with database.transaction() as c:
        row = c.execute(
            """SELECT isc.quantidade_solicitada, isc.observacao_item
               FROM itens_sc isc JOIN solicitacoes_compra s ON s.id = isc.sc_id
               WHERE s.numero_sc='SC-REP-1' AND isc.item_id=?""", (item_id,)
        ).fetchone()
    assert row["quantidade_solicitada"] == sug["qtd_sugerida"]
    assert "sugerido" in (row["observacao_item"] or "")


# ══════════════════════════════════════════════════════════════════════════════
# AUDITORIA DE DESFECHO
# ══════════════════════════════════════════════════════════════════════════════

def test_registrar_e_listar_desfecho(db, make_item):
    item_id = make_item("PN-DES", estoque=8, minimo=5, lead=10)
    _set_inv(item_id, consumo_medio_diario=1.0, estoque_maximo=60)
    sug = P.gerar_sugestoes_reposicao(incluir_fornecedor=False)[0]

    P.registrar_desfecho_sugestao(sug, "adiada", observacao="aguardando orçamento")
    hist = P.listar_sugestoes(item_id=item_id)
    assert len(hist) == 1
    assert hist[0]["desfecho"] == "adiada"
    assert hist[0]["data_desfecho"] is not None


def test_desfecho_invalido_levanta():
    with pytest.raises(ValueError):
        P.registrar_desfecho_sugestao({"item_id": 1}, "qualquer")
