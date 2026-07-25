"""v3.11.0 — Monitor de SC (STATUS PO automático + limite de linhas) e Linha do Tempo.

Cobre: derivação automática do STATUS PO no sync (status da SC/PO, chaveado pela linha),
STATUS PO como coluna TÉCNICA (sobrescrita pelo sync, não mais manual), limite de linhas
do Monitor (com prioridade para as manuais) e o enriquecimento da Linha do Tempo.
"""

import database
from services import db_functions as F


def test_sync_deriva_status_po_do_status_da_sc(db, make_item, make_sc):
    item_id = make_item("PN-SPO", estoque=0, minimo=5)
    sc_id = make_sc(numero_sc="SC-SPO", item_id=item_id, quantidade_solicitada=4)
    with database.transaction() as c:
        c.execute("UPDATE solicitacoes_compra SET status='Em Cotação' WHERE id=?", (sc_id,))
    F.sincronizar_monitor_sc(force=True)
    l = F.listar_monitor_sc()[0]
    assert l["status_po"] == "Em Cotação"


def test_status_po_e_tecnica_sobrescrita_pelo_sync(db, make_item, make_sc):
    item_id = make_item("PN-SPO2", estoque=0, minimo=5)
    sc_id = make_sc(numero_sc="SC-SPO2", item_id=item_id, quantidade_solicitada=4)
    with database.transaction() as c:
        c.execute("UPDATE solicitacoes_compra SET status='Pedido Emitido' WHERE id=?", (sc_id,))
    F.sincronizar_monitor_sc(force=True)
    lid = F.listar_monitor_sc()[0]["linha_id"]
    # Simula uma digitação manual antiga → o sync deve SOBRESCREVER (agora é técnica).
    with database.transaction() as c:
        c.execute("UPDATE monitor_sc SET status_po='rabisco manual' WHERE linha_id=?", (lid,))
    F.sincronizar_monitor_sc(force=True)
    assert F.listar_monitor_sc()[0]["status_po"] == "Pedido Emitido"
    assert "status_po" in F.MONITOR_COLS_TECNICAS
    assert "status_po" not in F.MONITOR_COLS_MANUAIS


def test_listar_monitor_limita_linhas(db, make_item, make_sc, monkeypatch):
    monkeypatch.setattr(F, "MONITOR_MAX_LINHAS", 3)
    for i in range(4):
        item = make_item(part_number=f"PN-CAP{i}", estoque=0, minimo=5)
        make_sc(numero_sc=f"SC-CAP{i}", item_id=item, quantidade_solicitada=3)
    F.sincronizar_monitor_sc(force=True)
    assert len(F.listar_monitor_sc()) == 3


def test_cap_mantem_linhas_manuais(db, make_item, make_sc, monkeypatch):
    monkeypatch.setattr(F, "MONITOR_MAX_LINHAS", 3)
    for i in range(2):
        item = make_item(part_number=f"PN-MC{i}", estoque=0, minimo=5)
        make_sc(numero_sc=f"SC-MC{i}", item_id=item, quantidade_solicitada=3)
    F.sincronizar_monitor_sc(force=True)
    orig = F.listar_monitor_sc()
    man = [
        {"numero_sc": "MAN-A", "part_number": "MA", "revisado": False, "linha_id": None},
        {"numero_sc": "MAN-B", "part_number": "MB", "revisado": False, "linha_id": None},
    ]
    F.salvar_monitor_sc(orig + man, [l["linha_id"] for l in orig])
    linhas = F.listar_monitor_sc()
    assert len(linhas) == 3
    scs = {l["numero_sc"] for l in linhas}
    assert "MAN-A" in scs and "MAN-B" in scs  # manuais sempre dentro do limite


def test_linha_do_tempo_recebimentos_enriquecida(db, make_item, make_sc):
    item_id = make_item("PN-RCB", estoque=0, minimo=2, unidade="CX")
    sc_id = make_sc(numero_sc="SC-RCB", item_id=item_id, quantidade_solicitada=10)
    item_sc_id = F.listar_itens_sc(sc_id)[0]["id"]
    ok, _ = F.registrar_recebimento_sc(
        sc_id, item_sc_id, 4, "21194 - ALMOXARIFADO", "Alm", "Alm", "SKF", "2026-02-01", "NF-100"
    )
    assert ok
    recs = F.listar_recebimentos_sc()
    assert recs, "deveria haver ao menos 1 recebimento"
    r = recs[0]
    for k in ("fornecedor", "numero_po", "unidade", "qtd_solicitada", "pendente"):
        assert k in r
    assert r["unidade"] == "CX"
    assert float(r["qtd_solicitada"]) == 10
    assert r["pendente"] is not None and float(r["pendente"]) >= 0
