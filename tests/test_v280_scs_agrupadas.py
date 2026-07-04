"""v2.8.0 — Assistente de Reposição "de mão beijada".

Cobre: data-limite "Comprar até" derivada da COBERTURA (não do ROP); mapeamento
item→NATUREZA da SC (do histórico) e item→CENTRO DE CUSTO (do consumo real, sem os
CCs genéricos); agrupamento das SCs por natureza; título + justificativa + CC
automáticos por grupo; e a criação de uma SC agrupada multi-item (reusa criar_sc,
sem migração — observações na própria SC).
"""
from datetime import date, timedelta

import database
from services import db_functions as F
from services import planejamento as P
from services.constants import CATEGORIA_SC_PADRAO, CC_SUGERIDO_PADRAO


# ── Fábrica de item sintético (mesmas chaves de listar_inventario) ──────────────

def _item(**over):
    base = dict(
        id=1, part_number="PN-1", nome_item="Item", descricao="Descrição",
        unidade="UN", tipo_material="Consumivel", setor_responsavel="MANUTENÇÃO",
        importancia="Importante", sem_movimentacao=0,
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
    sets = ", ".join(f"{k}=?" for k in campos)
    with database.transaction() as c:
        c.execute(f"UPDATE inventario SET {sets} WHERE id=?",
                  (*campos.values(), item_id))


def _sc_historica(item_ids, natureza, numero, data="2026-05-01"):
    """SC RECEBIDA (não vira guarda-chuva) com uma natureza, ligada a itens — para
    exercitar a derivação item→natureza do histórico."""
    with database.transaction() as c:
        cur = c.execute(
            "INSERT INTO solicitacoes_compra (numero_sc, data_abertura, status, descricao_solicitacao) "
            "VALUES (?,?,?,?)", (numero, data, "Recebido", natureza))
        sc_id = cur.lastrowid
        for iid in item_ids:
            c.execute(
                "INSERT INTO itens_sc (sc_id, item_id, quantidade_solicitada, "
                "quantidade_recebida, saldo_residual, status_item) VALUES (?,?,?,?,?,?)",
                (sc_id, iid, 10, 10, 0, "Recebido"))
    return sc_id


def _saida_real(item_id, cc, data="2026-06-02 08:00:00"):
    """Saída por requisição (consumo real) com um centro de custo — para exercitar a
    derivação item→CC."""
    with database.transaction() as c:
        cur = c.execute(
            "INSERT INTO requisicoes (numero_requisicao, data_hora, setor, emitente, centro_custo) "
            "VALUES (?,?,?,?,?)",
            (f"REQ-CC-{item_id}-{cc[:3]}", data, "MANUTENÇÃO", "Joao", cc))
        req_id = cur.lastrowid
        c.execute(
            "INSERT INTO movimentacoes (item_id,tipo,quantidade,data_hora,centro_custo,"
            "setor,emitente,observacao,requisicao_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (item_id, "saida", 1.0, data, cc, "MANUTENÇÃO", "Joao", f"Req {req_id}", req_id))
    return req_id


# ══════════════════════════════════════════════════════════════════════════════
# "COMPRAR ATÉ" (data-limite derivada da cobertura, com folga de 15 d)
# ══════════════════════════════════════════════════════════════════════════════

def test_comprar_ate_deriva_da_cobertura():
    hoje = date(2026, 7, 4)
    comprar_ate, dias, atrasado = P.calcular_comprar_ate(40, 10, hoje=hoje)  # 40−10−15
    assert dias == 15
    assert atrasado is False
    assert comprar_ate == (hoje + timedelta(days=15)).isoformat()


def test_comprar_ate_atrasado_vira_hoje():
    hoje = date(2026, 7, 4)
    comprar_ate, dias, atrasado = P.calcular_comprar_ate(5, 10, hoje=hoje)  # 5−10−15=−20
    assert dias == -20
    assert atrasado is True
    assert comprar_ate == hoje.isoformat()


def test_comprar_ate_sem_consumo_e_none():
    comprar_ate, dias, atrasado = P.calcular_comprar_ate(
        P.PREVISAO_RUPTURA_SEM_RISCO, 10, hoje=date(2026, 7, 4))
    assert comprar_ate is None
    assert dias is None
    assert atrasado is False


def test_montar_sugestao_expoe_comprar_ate_e_categoria():
    item = _item(id=7, part_number="PN-CAT", dias_cobertura=40, lead_time_dias=10,
                 consumo_medio_diario=2.0, estoque_atual=80, estoque_maximo=200,
                 tipo_material="Consumivel", setor_responsavel="MANUTENÇÃO",
                 descricao="Cotonete industrial")
    sug = P.montar_sugestao(item, incluir_fornecedor=False)
    assert sug["tipo_material"] == "Consumivel"
    assert sug["descricao"] == "Cotonete industrial"
    assert sug["dias_para_comprar"] == 15          # 40 − 10 − 15
    assert sug["comprar_atrasado"] is False
    assert sug["comprar_ate"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# NATUREZA (do histórico de SCs) + CENTRO DE CUSTO (do consumo real)
# ══════════════════════════════════════════════════════════════════════════════

NAT_A = "SOLICITAÇÃO DE COMPRA - CONSUMÍVEIS PRODUÇÃO"
NAT_B = "SOLICITAÇÃO DE COMPRA - MATERIAL DE EXPEDIENTE"


def test_mapear_categoria_sc_mais_frequente(db, make_item):
    x = make_item("PN-NAT-X")
    _sc_historica([x], NAT_A, "SC-NX-1", data="2026-01-01")
    _sc_historica([x], NAT_A, "SC-NX-2", data="2026-02-01")
    _sc_historica([x], NAT_B, "SC-NX-3", data="2026-03-01")
    mapa = P.mapear_categoria_sc_por_item([x])
    assert mapa[x] == NAT_A          # 2× A vence 1× B


def test_mapear_categoria_sc_desempate_pela_mais_recente(db, make_item):
    y = make_item("PN-NAT-Y")
    _sc_historica([y], NAT_A, "SC-NY-1", data="2026-01-01")
    _sc_historica([y], NAT_B, "SC-NY-2", data="2026-02-01")   # empate 1-1
    mapa = P.mapear_categoria_sc_por_item([y])
    assert mapa[y] == NAT_B          # desempate: SC mais recente


def test_mapear_cc_ignora_genericos(db, make_item):
    bom = make_item("PN-CC-BOM")
    generico = make_item("PN-CC-GEN")
    _saida_real(bom, "21106 - MANUTENÇÃO")
    _saida_real(generico, "99000 - ATIVO PASSIVO RES. F")   # genérico → ignorado
    mapa = P.mapear_cc_por_item([bom, generico])
    assert mapa[bom] == "21106 - MANUTENÇÃO"
    assert generico not in mapa                              # só tinha CC genérico


# ══════════════════════════════════════════════════════════════════════════════
# AGRUPAMENTO POR NATUREZA
# ══════════════════════════════════════════════════════════════════════════════

def test_agrupar_por_natureza():
    sugs = [
        {"categoria_sc": NAT_A, "prioridade_tier": 1},
        {"categoria_sc": NAT_A, "prioridade_tier": 2},
        {"categoria_sc": NAT_B, "prioridade_tier": 0},
    ]
    grupos = P.agrupar_por_natureza(sugs)
    assert len(grupos[NAT_A]) == 2
    assert NAT_B in grupos
    assert list(grupos.keys())[0] == NAT_B          # tier mín 0 vem primeiro


def test_agrupar_por_natureza_sem_categoria_usa_padrao():
    grupos = P.agrupar_por_natureza([{"prioridade_tier": 2}])
    assert CATEGORIA_SC_PADRAO in grupos


# ══════════════════════════════════════════════════════════════════════════════
# RESUMO DA SC SUGERIDA (título = natureza; justificativa + CC automáticos)
# ══════════════════════════════════════════════════════════════════════════════

def test_resumir_grupo_sc():
    sugs = [
        {"categoria_sc": NAT_A, "prioridade_tier": 0, "prioridade": "🔴 Crítico",
         "qtd_sugerida": 50, "consumo_diario": 2.0, "comprar_ate": "2026-07-25",
         "part_number": "PN-A", "fornecedor_ultimo_preco": 3.0, "cc_sugerido": "21106 - MANUTENÇÃO"},
        {"categoria_sc": NAT_A, "prioridade_tier": 1, "prioridade": "🟠 Antecipar",
         "qtd_sugerida": 30, "consumo_diario": 1.0, "comprar_ate": "2026-07-19",
         "part_number": "PN-B", "fornecedor_ultimo_preco": None, "cc_sugerido": "21106 - MANUTENÇÃO"},
    ]
    r = P.resumir_grupo_sc(NAT_A, sugs)
    assert r["titulo"] == NAT_A                       # a natureza É o título
    assert r["n_itens"] == 2
    assert r["qtd_total"] == 80
    assert r["prioridade_tier"] == 0
    assert r["comprar_ate_min"] == "2026-07-19"       # mais urgente
    assert r["valor_estimado"] == 150.0               # 50×3 (o outro sem preço)
    assert r["cc_sugerido"] == "21106 - MANUTENÇÃO"
    assert "Agrupa 2 itens da natureza CONSUMÍVEIS PRODUÇÃO" in r["justificativa"]
    assert "1 crítico" in r["justificativa"]
    assert "Comprar até 19/07/2026" in r["justificativa"]
    assert "Centro de custo sugerido: 21106 - MANUTENÇÃO" in r["justificativa"]


def test_resumir_grupo_sc_sem_cc_significativo():
    sugs = [{"categoria_sc": NAT_A, "prioridade_tier": 2, "prioridade": "🟡 Atenção",
             "qtd_sugerida": 10, "consumo_diario": 0.0, "comprar_ate": None,
             "part_number": "PN-Z", "fornecedor_ultimo_preco": None, "cc_sugerido": None}]
    r = P.resumir_grupo_sc(NAT_A, sugs)
    assert r["cc_sugerido"] == CC_SUGERIDO_PADRAO


def test_resumir_grupo_sc_vazio_nao_quebra():
    r = P.resumir_grupo_sc(NAT_A, [])
    assert r["n_itens"] == 0
    assert r["comprar_ate_min"] is None
    assert r["cc_sugerido"] == CC_SUGERIDO_PADRAO


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRAÇÃO — SC AGRUPADA MULTI-ITEM POR NATUREZA (reusa criar_sc, sem migração)
# ══════════════════════════════════════════════════════════════════════════════

def test_gerar_scs_sugeridas_agrupa_por_natureza(db, make_item, registrar_consumo):
    a = make_item("PN-G1", estoque=8, minimo=5, lead=10)
    b = make_item("PN-G2", estoque=8, minimo=5, lead=10)
    for i in (a, b):
        _set_inv(i, consumo_medio_diario=1.0, estoque_maximo=60)
        registrar_consumo(i)                       # consumo real (CC 21106 - MANUTENÇÃO)
    _sc_historica([a, b], NAT_A, "SC-HIST-A")      # natureza vinda do histórico

    scs = P.gerar_scs_sugeridas(incluir_fornecedor=False)
    grupo = next(s for s in scs if s["label"] == NAT_A)
    assert grupo["n_itens"] == 2
    assert {s["part_number"] for s in grupo["itens"]} == {"PN-G1", "PN-G2"}
    assert grupo["cc_sugerido"] == "21106 - MANUTENÇÃO"   # do consumo real


def test_item_sem_historico_cai_no_padrao(db, make_item, registrar_consumo):
    x = make_item("PN-SEMHIST", estoque=8, minimo=5, lead=10)
    _set_inv(x, consumo_medio_diario=1.0, estoque_maximo=60)
    registrar_consumo(x)
    sugs = P.gerar_sugestoes_reposicao(incluir_fornecedor=False)
    s = next(s for s in sugs if s["part_number"] == "PN-SEMHIST")
    assert s["categoria_sc"] == CATEGORIA_SC_PADRAO


def test_criar_sc_agrupada_multi_item(db, make_item, registrar_consumo):
    a = make_item("PN-SC-A", estoque=8, minimo=5, lead=10)
    b = make_item("PN-SC-B", estoque=8, minimo=5, lead=10)
    for i in (a, b):
        _set_inv(i, consumo_medio_diario=1.0, estoque_maximo=60)
        registrar_consumo(i)
    _sc_historica([a, b], NAT_A, "SC-HIST-B")

    grupo = next(g for g in P.gerar_scs_sugeridas(incluir_fornecedor=False)
                 if g["label"] == NAT_A)
    itens = [P.sugestao_para_item_sc(s) for s in grupo["itens"]]
    obs = f"{grupo['titulo']}\nCentro de custo sugerido: {grupo['cc_sugerido']}\n\n{grupo['justificativa']}"
    ok, msg = F.criar_sc("SC-AGRUP-1", "2026-07-04", itens, observacoes=obs)
    assert ok, msg

    sc_id = P.buscar_sc_id_por_numero("SC-AGRUP-1")
    assert sc_id is not None
    assert len(F.listar_itens_sc(sc_id)) == 2      # SC multi-item de mão beijada

    with database.transaction() as c:
        row = c.execute(
            "SELECT observacoes FROM solicitacoes_compra WHERE id=?", (sc_id,)
        ).fetchone()
    assert NAT_A in row["observacoes"]
    assert "Centro de custo sugerido: 21106 - MANUTENÇÃO" in row["observacoes"]

    for s in grupo["itens"]:
        P.registrar_desfecho_sugestao(s, "criou_sc", sc_id=sc_id)
    assert len(P.listar_sugestoes(desfecho="criou_sc")) == 2
