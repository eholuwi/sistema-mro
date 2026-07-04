"""v2.7.0 — Status "⚪ Sem Movimentação" (higiene da lista de compra).

Regra: item que NUNCA teve consumo real (saída por requisição, `requisicao_id`
preenchido) sai da lista de compra e ganha status próprio, sobrepondo 🔴/🟡/🟢.
Decisão do PO: vale p/ TODO item sem consumo (inclusive "Parada de Linha"), que
segue visível no Assistente de Reposição via toggle. Nada altera a base do Neidson.
"""
from services import db_functions as F
from services import planejamento as P
from services.constants import STATUS_SEM_MOVIMENTACAO


def _item(itens, pn):
    return next(i for i in itens if i["part_number"] == pn)


# ── Definição de "sem movimentação" ──────────────────────────────────────────

def test_item_novo_sem_requisicao_e_sem_movimentacao(db, make_item):
    make_item("PN-SM", estoque=0, minimo=10)
    item = _item(F.listar_inventario(), "PN-SM")
    assert item["sem_movimentacao"] is True
    assert item["qtd_requisicoes"] == 0
    assert item["status_material"] == STATUS_SEM_MOVIMENTACAO


def test_saldo_inicial_e_ajuste_nao_contam_como_movimentacao(db, make_item):
    # make_item(estoque>0) gera "Saldo inicial" (entrada) — NÃO é consumo real.
    iid = make_item("PN-AJU", estoque=50, minimo=10)
    # ajuste manual (saída sem requisicao_id) também não conta
    F.registrar_movimentacao(iid, "saida", 5, "21106 - MANUTENÇÃO", "Joao", "Joao",
                             observacao="Ajuste - retirado sem requisição")
    item = _item(F.listar_inventario(), "PN-AJU")
    assert item["sem_movimentacao"] is True
    assert item["status_material"] == STATUS_SEM_MOVIMENTACAO


def test_requisicao_real_tira_do_sem_movimentacao(db, make_item, registrar_consumo):
    iid = make_item("PN-COM", estoque=5, minimo=10)
    registrar_consumo(iid, quantidade=2)
    item = _item(F.listar_inventario(), "PN-COM")
    assert item["sem_movimentacao"] is False
    assert item["qtd_requisicoes"] == 1
    # com consumo real, volta a valer o status físico (estoque 5 <= min 10)
    assert "COMPRAR" in item["status_material"]
    assert item["status_estoque_fisico"] == item["status_material"]


# ── Sobreposição do status preserva o físico ─────────────────────────────────

def test_status_fisico_preservado_mesmo_sem_movimentacao(db, make_item):
    make_item("PN-OKSM", estoque=100, minimo=10)  # fisicamente OK, mas sem consumo
    item = _item(F.listar_inventario(), "PN-OKSM")
    assert item["status_material"] == STATUS_SEM_MOVIMENTACAO
    assert "OK" in item["status_estoque_fisico"]   # físico preservado p/ revisão


# ── Dashboard: balde próprio, não conta como crítico ─────────────────────────

def test_dashboard_separa_sem_movimentacao_dos_criticos(db, make_item, registrar_consumo):
    # 1 crítico real (com consumo) + 2 sem movimentação (fantasmas na lista antiga)
    iid = make_item("PN-CRIT", estoque=2, minimo=10)
    registrar_consumo(iid)
    make_item("PN-F1", estoque=0, minimo=10)
    make_item("PN-F2", estoque=0, minimo=0)
    kpis = F.obter_dados_dashboard()["kpis"]
    assert kpis["comprar"] == 1               # só o que tem consumo real
    assert kpis["sem_movimentacao"] == 2      # os dois fantasmas separados


# ── Export: coluna "Movimentação" + status na coluna filtrável ───────────────

def test_export_tem_coluna_movimentacao_e_status(db, make_item, registrar_consumo):
    make_item("PN-SMX", estoque=0, minimo=10)          # sem movimentação
    iid = make_item("PN-CMX", estoque=5, minimo=10)    # com consumo
    registrar_consumo(iid)
    df = F.exportar_inventario_df()
    assert "Movimentação" in df.columns
    linha_sm = df[df["PN"] == "PN-SMX"].iloc[0]
    linha_cm = df[df["PN"] == "PN-CMX"].iloc[0]
    assert linha_sm["Movimentação"] == "Sem movimentação"
    assert linha_sm["Status Material"] == STATUS_SEM_MOVIMENTACAO
    assert "req" in linha_cm["Movimentação"]
    assert "COMPRAR" in linha_cm["Status Material"]


# ── Assistente de Reposição: exclui por padrão, inclui via toggle ────────────

def test_reposicao_exclui_sem_movimentacao_por_padrao(db, make_item):
    # item sem consumo, estoque abaixo do mínimo (dispara piso do Neidson)
    make_item("PN-REPSM", estoque=1, minimo=10)
    fila_default = P.gerar_sugestoes_reposicao(incluir_fornecedor=False)
    assert all(not s["sem_movimentacao"] for s in fila_default)
    assert not any(s["part_number"] == "PN-REPSM" for s in fila_default)


def test_reposicao_inclui_sem_movimentacao_com_toggle(db, make_item):
    make_item("PN-REPSM2", estoque=1, minimo=10)
    fila = P.gerar_sugestoes_reposicao(incluir_fornecedor=False,
                                       incluir_sem_movimentacao=True)
    alvo = next((s for s in fila if s["part_number"] == "PN-REPSM2"), None)
    assert alvo is not None
    assert alvo["sem_movimentacao"] is True


def test_parada_de_linha_sem_giro_sai_do_comprar_mas_revisavel(db, make_item):
    make_item("PN-PL", estoque=0, minimo=5, importancia="Parada de Linha")
    item = _item(F.listar_inventario(), "PN-PL")
    # decisão do PO "tratar igual": mesmo crítico, vira Sem Movimentação
    assert item["status_material"] == STATUS_SEM_MOVIMENTACAO
    # fora da fila por padrão…
    assert not any(s["part_number"] == "PN-PL"
                   for s in P.gerar_sugestoes_reposicao(incluir_fornecedor=False))
    # …mas revisável com o toggle
    fila = P.gerar_sugestoes_reposicao(incluir_fornecedor=False,
                                       incluir_sem_movimentacao=True)
    assert any(s["part_number"] == "PN-PL" for s in fila)


# ── Ficha 360: expõe a situação de consumo ───────────────────────────────────

def test_ficha_expoe_sem_movimentacao(db, make_item):
    from services.ficha import montar_ficha_360
    iid = make_item("PN-FICHA", estoque=0, minimo=10)
    ficha = montar_ficha_360(iid)
    assert ficha["item"]["sem_movimentacao"] is True
