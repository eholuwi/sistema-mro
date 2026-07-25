"""v4.3.0 — Ajuste Rápido (4 tipos) + busca por PN no Histórico de Requisições.

Camada de serviço (a UI é coberta pelo smoke E2E):
- Migração idempotente da coluna `motivo` em movimentacoes.
- registrar_movimentacao persiste `motivo` e mantém a direção do saldo por `tipo`.
- categoria_movimentacao deriva o rótulo do Histórico (4 tipos + Requisição/Conferência).
- mapa_pn_por_requisicao indexa PN/nome por requisição para a busca textual.
"""

from services import db_functions as F


def test_migracao_motivo_presente_e_idempotente(db):
    # Coluna criada no CREATE/migração; rodar criar_banco de novo não duplica nada.
    conn = db.get_connection()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(movimentacoes)")}
    conn.close()
    assert "motivo" in cols
    db.criar_banco()  # idempotente
    conn = db.get_connection()
    cols2 = {r[1] for r in conn.execute("PRAGMA table_info(movimentacoes)")}
    conn.close()
    assert "motivo" in cols2


def test_registrar_movimentacao_grava_motivo(db, make_item):
    item_id = make_item("PN-MOT", estoque=100, minimo=10)
    ok, _ = F.registrar_movimentacao(
        item_id=item_id,
        tipo="saida",
        quantidade=3,
        centro_custo=None,
        solicitante="ana",
        emitente="ana",
        observacao="AJUSTE: perda",
        motivo="Perda de Material",
    )
    assert ok
    conn = db.get_connection()
    row = conn.execute(
        "SELECT tipo, motivo, quantidade FROM movimentacoes WHERE item_id=? AND motivo IS NOT NULL",
        (item_id,),
    ).fetchone()
    conn.close()
    assert row["motivo"] == "Perda de Material"
    assert row["tipo"] == "saida"


def test_registrar_movimentacao_sem_motivo_continua_valido(db, make_item):
    # Retrocompatibilidade: chamadas antigas (sem motivo) seguem funcionando.
    item_id = make_item("PN-OLD", estoque=50, minimo=5)
    ok, _ = F.registrar_movimentacao(
        item_id=item_id,
        tipo="entrada",
        quantidade=10,
        centro_custo=None,
        solicitante="x",
        emitente="x",
    )
    assert ok


def test_categoria_movimentacao_rotulos():
    # motivo tem precedência (4 tipos do Ajuste Rápido).
    assert (
        F.categoria_movimentacao({"motivo": "Perda de Material", "tipo": "saida", "quantidade": 2})
        == "Perda de Material"
    )
    # saída com requisição = Requisição.
    assert F.categoria_movimentacao({"tipo": "saida", "quantidade": 5, "requisicao_id": 9}) == "Requisição"
    # quantidade zero = Conferência.
    assert F.categoria_movimentacao({"tipo": "saida", "quantidade": 0}) == "Conferência"
    # entrada sem vínculo = Entrada.
    assert F.categoria_movimentacao({"tipo": "entrada", "quantidade": 7}) == "Entrada"


def test_mapa_pn_por_requisicao_indexa_pn(db, make_item):
    item_id = make_item("PN-BUSCA", nome="Filtro de Ar", estoque=100, minimo=10)
    ok, _ = F.criar_requisicao(
        setor="MANUTENÇÃO",
        emitente="joao",
        centro_custo="21106 - MANUTENÇÃO",
        autorizador_tipo="Gestor",
        autorizador_nome="maria",
        entrega_individual=False,
        destinatarios=[],
        sesmt=False,
        sesmt_responsavel="",
        itens=[{"item_id": item_id, "quantidade_solicitada": 2}],
    )
    assert ok
    mapa = F.mapa_pn_por_requisicao()
    assert any("pn-busca" in v for v in mapa.values())
    assert any("filtro de ar" in v for v in mapa.values())
