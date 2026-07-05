"""v2.10.0 — Classificação de Demanda (Syntetos-Boylan), XYZ & Sazonalidade.

Diagnóstico DERIVADO NA LEITURA (sem migração) a partir das SAÍDAS REAIS (por
requisição — `SAIDA_REAL_WHERE`). Esta suíte cobre:
  - núcleo PURO da matemática SBC (as 4 classes) e XYZ (X/Y/Z), sem banco;
  - agregação mensal e o gate de sazonalidade (≥12 meses);
  - integração: consumo_mensal ignora ajustes; campos derivados em listar_inventario.
Princípio do PO: só diagnóstico — não altera status/reposição; base do Neidson intacta.
"""
from datetime import datetime, timedelta

import database
from services import classificacao as C
from services import db_functions as F


# semana de referência (segunda-feira; a data exata é irrelevante — o bucketing é
# relativo à 1ª demanda). Evento k = base + 7*k dias.
_BASE = datetime(2026, 1, 5, 8, 0, 0)


def _ev(semana, qtd):
    return (_BASE + timedelta(days=7 * semana), float(qtd))


# ══════════════════════════════════════════════════════════════════════════════
# NÚCLEO PURO — SBC (as 4 classes) e casos degenerados
# ══════════════════════════════════════════════════════════════════════════════

def test_sbc_suave():
    # demanda TODA semana, tamanhos iguais → ADI≈1, CV²≈0.
    eventos = [_ev(k, 10) for k in range(11)]
    d = C._demanda_from_eventos(eventos)
    assert d["padrao"] == "Suave"
    assert d["adi"] < 1.32 and d["cv2"] < 0.49


def test_sbc_intermitente():
    # demanda a cada 2 semanas, tamanhos iguais → ADI alto, CV² baixo.
    eventos = [_ev(k, 10) for k in range(0, 11, 2)]
    d = C._demanda_from_eventos(eventos)
    assert d["padrao"] == "Intermitente"
    assert d["adi"] >= 1.32 and d["cv2"] < 0.49


def test_sbc_erratico():
    # demanda TODA semana, tamanhos muito diferentes → ADI baixo, CV² alto.
    eventos = [_ev(k, 1 if k % 2 == 0 else 100) for k in range(8)]
    d = C._demanda_from_eventos(eventos)
    assert d["padrao"] == "Errático"
    assert d["adi"] < 1.32 and d["cv2"] >= 0.49


def test_sbc_irregular():
    # demanda esparsa E com tamanhos muito diferentes → ADI alto, CV² alto.
    eventos = [_ev(0, 1), _ev(3, 100), _ev(7, 1), _ev(10, 100)]
    d = C._demanda_from_eventos(eventos)
    assert d["padrao"] == "Irregular"
    assert d["adi"] >= 1.32 and d["cv2"] >= 0.49


def test_sbc_sem_dados_e_poucos_dados():
    assert C._demanda_from_eventos([])["padrao"] == "Sem dados"
    assert C._demanda_from_eventos([])["confianca"] == "sem_dados"
    # 1 semana com consumo → "Poucos dados" (é dado, mas insuficiente p/ classificar).
    um = C._demanda_from_eventos([_ev(0, 5)])
    assert um["padrao"] == "Poucos dados"
    assert um["confianca"] == "muito baixa"


def test_sbc_multiplos_no_mesmo_balde_somam():
    # várias saídas na MESMA semana contam como 1 período, com a qtd somada.
    eventos = [(_BASE, 4.0), (_BASE + timedelta(days=1), 6.0)]
    d = C._demanda_from_eventos(eventos)
    assert d["n_eventos"] == 1  # 1 semana com demanda
    assert d["padrao"] == "Poucos dados"


# ══════════════════════════════════════════════════════════════════════════════
# NÚCLEO PURO — XYZ
# ══════════════════════════════════════════════════════════════════════════════

def test_xyz_estavel_x():
    r = C._xyz_from_meses([100, 100, 100])
    assert r["classe"] == "X" and r["cv"] == 0.0


def test_xyz_variavel_y():
    r = C._xyz_from_meses([30, 100, 170])  # cv ≈ 0.57
    assert r["classe"] == "Y"


def test_xyz_erratico_z():
    r = C._xyz_from_meses([5, 10, 300])    # cv ≈ 1.31
    assert r["classe"] == "Z"


def test_xyz_insuficiente():
    assert C._xyz_from_meses([])["confianca"] == "sem_dados"
    r1 = C._xyz_from_meses([42])           # 1 mês → não dá p/ medir variabilidade
    assert r1["classe"] is None and r1["confianca"] == "insuficiente"


# ══════════════════════════════════════════════════════════════════════════════
# AGREGAÇÃO MENSAL & SAZONALIDADE (gate de maturidade)
# ══════════════════════════════════════════════════════════════════════════════

def test_meses_from_eventos_agrega_por_mes():
    eventos = [(datetime(2026, 4, 10), 5), (datetime(2026, 4, 20), 3),
               (datetime(2026, 6, 1), 7)]
    serie = C._meses_from_eventos(eventos)
    assert serie == [{"mes": "2026-04", "qtd": 8.0}, {"mes": "2026-06", "qtd": 7.0}]


def test_sazonalidade_bloqueada_com_poucos_meses():
    serie = [{"mes": "2026-04", "qtd": 1}, {"mes": "2026-05", "qtd": 2},
             {"mes": "2026-06", "qtd": 3}]
    saz = C._sazonalidade_from_serie(serie)
    assert saz["disponivel"] is False
    assert saz["meses_atuais"] == 3 and saz["meses_necessarios"] == 12


def test_sazonalidade_liberada_com_ciclo_anual():
    serie = [{"mes": f"2025-{m:02d}", "qtd": m} for m in range(1, 13)]  # 12 meses
    saz = C._sazonalidade_from_serie(serie)
    assert saz["disponivel"] is True
    assert len(saz["perfil"]) == 12


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRAÇÃO COM O BANCO
# ══════════════════════════════════════════════════════════════════════════════

def _saida_ajuste(item_id, quantidade, data_hora):
    """Insere uma saída de AJUSTE (requisicao_id NULL) — NÃO é consumo real."""
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,"
            "centro_custo,setor,emitente,observacao,requisicao_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,NULL)",
            (item_id, "saida", quantidade, None, data_hora,
             "INVENTÁRIO", "", "Inventário", "Ajuste"),
        )
        conn.commit()
    finally:
        conn.close()


def test_consumo_mensal_so_conta_saida_real(db, make_item, registrar_consumo):
    item = make_item("PN-CM")
    registrar_consumo(item, 5, "2026-04-10 08:00:00")
    registrar_consumo(item, 3, "2026-06-15 08:00:00")
    _saida_ajuste(item, 999, "2026-05-01 08:00:00")  # ajuste — deve ser ignorado
    serie = C.consumo_mensal(item)
    assert serie == [{"mes": "2026-04", "qtd": 5.0}, {"mes": "2026-06", "qtd": 3.0}]


def test_classificar_demanda_db_suave(db, make_item, registrar_consumo):
    item = make_item("PN-SUA")
    for k in range(6):  # 6 semanas seguidas, qtd igual
        registrar_consumo(item, 10, (_BASE + timedelta(days=7 * k)).strftime("%Y-%m-%d %H:%M:%S"))
    d = C.classificar_demanda(item)
    assert d["padrao"] == "Suave"


def test_listar_inventario_expoe_campos_derivados(db, make_item, registrar_consumo):
    com = make_item("PN-COM")
    for k in range(6):
        registrar_consumo(com, 10, (_BASE + timedelta(days=7 * k)).strftime("%Y-%m-%d %H:%M:%S"))
    sem = make_item("PN-SEM")  # sem consumo real

    inv = {i["part_number"]: i for i in F.listar_inventario()}
    assert "padrao_demanda" in inv["PN-COM"] and "classe_xyz" in inv["PN-COM"]
    assert inv["PN-COM"]["padrao_demanda"] == "Suave"
    # item sem consumo real → sem classificação (None), não quebra.
    assert inv["PN-SEM"]["padrao_demanda"] is None
    assert inv["PN-SEM"]["classe_xyz"] is None


def test_classificar_todos_ignora_item_sem_consumo(db, make_item, registrar_consumo):
    com = make_item("PN-A")
    registrar_consumo(com, 1, "2026-04-01 08:00:00")
    make_item("PN-B")  # sem consumo
    mapa = C.classificar_todos()
    ids = {i["part_number"]: i["id"] for i in F.listar_inventario()}
    assert ids["PN-A"] in mapa
    assert ids["PN-B"] not in mapa
