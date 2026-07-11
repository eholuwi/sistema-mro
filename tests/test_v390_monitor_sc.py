"""v3.9.0 — Monitor de SC editável e persistente (C1/C2/C3).

Cobre: tabela/migração, sync diário (upsert técnico por linha_id estável, reset do
'Revisado', gate por dia, desativação de itens não-pendentes), preservação das colunas
manuais no re-sync, e persistência das edições (update / insert manual / delete →
tombstone de sistema e delete de manual).
"""
import database
from services import db_functions as F


def _mon(item_sc_linha=None, conn=None):
    """Linhas atuais do Monitor (dict por linha_id)."""
    return {l["linha_id"]: l for l in F.listar_monitor_sc()}


def _raw(linha_id):
    conn = database.get_connection()
    try:
        r = conn.execute("SELECT * FROM monitor_sc WHERE linha_id=?", (linha_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


# ── C1: tabela ─────────────────────────────────────────────────────────────────

def test_tabela_monitor_existe_com_colunas(db):
    conn = db.get_connection()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(monitor_sc)")}
    conn.close()
    assert {"linha_id", "numero_sc", "part_number", "status_calc", "tam_po", "saldo_po",
            "faltando_dias", "po", "status_po", "fornecedor", "comentario", "responsavel",
            "revisado", "revisado_data", "origem", "ativo", "removido"} <= cols


# ── C2: sync ───────────────────────────────────────────────────────────────────

def test_sync_cria_linha_de_sistema(db, make_item, make_sc):
    item_id = make_item("PN-MON", estoque=0, minimo=5)   # estoque 0 → STATUS "ESTOQUE Ø"
    make_sc(numero_sc="SC-MON", item_id=item_id, quantidade_solicitada=8)
    n = F.sincronizar_monitor_sc(force=True)
    assert n == 1
    linhas = F.listar_monitor_sc()
    assert len(linhas) == 1
    l = linhas[0]
    assert l["linha_id"].startswith("sys:")
    assert l["numero_sc"] == "SC-MON"
    assert l["part_number"] == "PN-MON"
    assert l["saldo_po"] == 8
    assert l["origem"] == "sistema" and l["ativo"] == 1 and l["removido"] == 0
    assert "ESTOQUE" in (l["status_calc"] or "")   # estoque 0


def test_status_critico_quando_abaixo_do_minimo(db, make_item, make_sc):
    item_id = make_item("PN-CRT", estoque=3, minimo=10)   # 0 < 3 ≤ 10 → CRÍTICO
    make_sc(numero_sc="SC-CRT", item_id=item_id, quantidade_solicitada=5)
    F.sincronizar_monitor_sc(force=True)
    l = F.listar_monitor_sc()[0]
    assert "CRÍTICO" in (l["status_calc"] or "")


def test_sync_gate_diario(db, make_item, make_sc):
    make_sc(numero_sc="SC-G", item_id=make_item("PN-G"), quantidade_solicitada=2)
    assert F.sincronizar_monitor_sc() >= 1       # 1ª vez no dia: roda
    assert F.sincronizar_monitor_sc() == -1      # 2ª vez no mesmo dia: gate (no-op)
    assert F.sincronizar_monitor_sc(force=True) >= 1  # force ignora o gate


def test_reset_revisado_no_virar_do_dia(db, make_item, make_sc):
    make_sc(numero_sc="SC-R", item_id=make_item("PN-R"), quantidade_solicitada=2)
    F.sincronizar_monitor_sc(force=True)
    lid = F.listar_monitor_sc()[0]["linha_id"]
    with database.transaction() as c:
        c.execute("UPDATE monitor_sc SET revisado=1, revisado_data='2020-01-01' WHERE linha_id=?", (lid,))
    F.sincronizar_monitor_sc(force=True)     # sync do "novo dia"
    assert _raw(lid)["revisado"] == 0        # revisado antigo foi resetado


def test_revisado_de_hoje_nao_reseta(db, make_item, make_sc):
    from datetime import date
    make_sc(numero_sc="SC-RH", item_id=make_item("PN-RH"), quantidade_solicitada=2)
    F.sincronizar_monitor_sc(force=True)
    lid = F.listar_monitor_sc()[0]["linha_id"]
    with database.transaction() as c:
        c.execute("UPDATE monitor_sc SET revisado=1, revisado_data=? WHERE linha_id=?",
                  (date.today().strftime("%Y-%m-%d"), lid))
    F.sincronizar_monitor_sc(force=True)
    assert _raw(lid)["revisado"] == 1        # marcado hoje: permanece


# ── C3: persistência das edições ───────────────────────────────────────────────

def test_salvar_preserva_manual_e_reflete_edicao(db, make_item, make_sc):
    make_sc(numero_sc="SC-E", item_id=make_item("PN-E"), quantidade_solicitada=4)
    F.sincronizar_monitor_sc(force=True)
    linha = F.listar_monitor_sc()[0]
    linha["fornecedor"] = "SKF"
    linha["comentario"] = "cotando"
    linha["responsavel"] = "Miguel"
    upd, ins, rem = F.salvar_monitor_sc([linha], [linha["linha_id"]])
    assert (upd, ins, rem) == (1, 0, 0)
    r = _raw(linha["linha_id"])
    assert r["fornecedor"] == "SKF" and r["comentario"] == "cotando" and r["responsavel"] == "Miguel"
    # Re-sync preserva as manuais e recalcula as técnicas.
    F.sincronizar_monitor_sc(force=True)
    r2 = _raw(linha["linha_id"])
    assert r2["fornecedor"] == "SKF" and r2["responsavel"] == "Miguel"


def test_salvar_insere_linha_manual(db, make_item, make_sc):
    make_sc(numero_sc="SC-M", item_id=make_item("PN-M"), quantidade_solicitada=1)
    F.sincronizar_monitor_sc(force=True)
    orig = F.listar_monitor_sc()
    nova = {"numero_sc": "MANUAL-1", "part_number": "ZZZ", "nome_item": "Item avulso",
            "fornecedor": "Fornecedor X", "revisado": False, "linha_id": None}
    upd, ins, rem = F.salvar_monitor_sc(orig + [nova], [l["linha_id"] for l in orig])
    assert ins == 1 and rem == 0
    linhas = F.listar_monitor_sc()
    manuais = [l for l in linhas if l["origem"] == "manual"]
    assert len(manuais) == 1 and manuais[0]["numero_sc"] == "MANUAL-1"
    assert manuais[0]["linha_id"].startswith("man:")


def test_salvar_remove_linha_de_sistema_vira_tombstone(db, make_item, make_sc):
    make_sc(numero_sc="SC-T", item_id=make_item("PN-T"), quantidade_solicitada=3)
    F.sincronizar_monitor_sc(force=True)
    orig = F.listar_monitor_sc()
    lid = orig[0]["linha_id"]
    # Salva SEM a linha de sistema → deve virar tombstone (removido=1), não sumir do banco.
    upd, ins, rem = F.salvar_monitor_sc([], [lid])
    assert rem == 1
    assert _raw(lid)["removido"] == 1
    assert F.listar_monitor_sc() == []           # não aparece mais na grade


def test_salvar_remove_linha_manual_deleta(db, make_item, make_sc):
    make_sc(numero_sc="SC-DM", item_id=make_item("PN-DM"), quantidade_solicitada=1)
    F.sincronizar_monitor_sc(force=True)
    orig = F.listar_monitor_sc()
    nova = {"numero_sc": "MAN-DEL", "part_number": "AAA", "revisado": False, "linha_id": None}
    F.salvar_monitor_sc(orig + [nova], [l["linha_id"] for l in orig])
    manual_lid = next(l["linha_id"] for l in F.listar_monitor_sc() if l["origem"] == "manual")
    # Remove a manual → DELETE de verdade (sem tombstone).
    restantes = [l for l in F.listar_monitor_sc() if l["linha_id"] != manual_lid]
    todos_ids = [l["linha_id"] for l in F.listar_monitor_sc()]
    F.salvar_monitor_sc(restantes, todos_ids)
    assert _raw(manual_lid) is None


def test_item_recebido_fica_inativo_e_some_da_grade(db, make_item, make_sc):
    item_id = make_item("PN-REC", estoque=0, minimo=2)
    sc_id = make_sc(numero_sc="SC-REC", item_id=item_id, quantidade_solicitada=5)
    F.sincronizar_monitor_sc(force=True)
    assert len(F.listar_monitor_sc()) == 1
    # Recebe tudo → item deixa de estar pendente.
    item_sc_id = F.listar_itens_sc(sc_id)[0]["id"]
    ok, _ = F.registrar_recebimento_sc(sc_id, item_sc_id, 5, "21194 - ALMOXARIFADO",
                                       "Alm", "Alm", "Forn", "2026-02-01", "NF-9")
    assert ok
    F.sincronizar_monitor_sc(force=True)
    assert F.listar_monitor_sc() == []           # ativo=0 → escondido
