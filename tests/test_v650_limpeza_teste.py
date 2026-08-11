"""v6.5.0 — limpeza de dados de teste/junk do banco (Task 3).

`scripts/limpeza_teste_v650.py` é um script de manutenção ÚNICO, pinado aos ids do relatório
aprovado pelo Luis em 11/08/2026 — não é uma ferramenta genérica que varre qualquer banco.
O que este arquivo trava:
- a igualdade exata (TESTE/TEST) NUNCA pega o falso positivo "ENG TESTE" (Engenharia de
  Teste, setor real) — só `LIKE '%TEST%'` cairia nessa armadilha;
- `_bate_com_aprovado` é o freio de segurança: se os ids encontrados divergirem do
  aprovado, `main()` aborta sem apagar nada, mesmo com `--aplicar`;
- quando os ids batem e roda de verdade: backup criado ANTES do primeiro DELETE, ordem
  movimentações -> requisições (a FK de movimentações não tem CASCADE), `itens_requisicao`
  cai sozinho (CASCADE), guarda-chuva de teste some, lista `setor=TESTE` é DESATIVADA (não
  apagada), e nada fora do critério é tocado (requisição real sobrevive).
"""

import importlib.util
from pathlib import Path

import pytest

import database
from services import db_functions as F

PROJ = Path(__file__).resolve().parents[1]
CC = "21106 - MANUTENÇÃO"


def _carregar_script():
    """Importa scripts/limpeza_teste_v650.py como módulo — não está em services/, então
    não é importável por nome de pacote."""
    caminho = PROJ / "scripts" / "limpeza_teste_v650.py"
    spec = importlib.util.spec_from_file_location("limpeza_teste_v650", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def script(db):
    return _carregar_script()


def _requisicao_com_baixa(item_id, setor, emitente):
    ok, info = F.criar_requisicao_com_baixa(
        setor=setor,
        emitente=emitente,
        centro_custo=CC,
        autorizador_tipo="Gestor",
        autorizador_nome="Chefia",
        entrega_individual=False,
        destinatarios="",
        sesmt=False,
        sesmt_responsavel="",
        itens=[{"item_id": item_id, "quantidade_solicitada": 1}],
    )
    assert ok, info
    conn = database.get_connection()
    req_id = conn.execute(
        "SELECT id FROM requisicoes WHERE numero_requisicao=?", (info["numero"],)
    ).fetchone()["id"]
    conn.close()
    return req_id


def test_auditoria_ignora_eng_teste_por_igualdade_exata(db, make_item, script):
    """'ENG TESTE' não é 'TESTE'/'TEST' — a igualdade exata deve deixá-la passar."""
    item = make_item(part_number="PN-JUNK")
    id_junk = _requisicao_com_baixa(item, "TESTE", "TESTE")
    id_real = _requisicao_com_baixa(item, "ENG TESTE", "JOAO SILVA")

    conn = database.get_connection()
    achado = script._auditar(conn)
    conn.close()

    ids = [r["id"] for r in achado["requisicoes"]]
    assert id_junk in ids
    assert id_real not in ids


def test_auditoria_pega_movimentacao_em_cascata(db, make_item, script):
    item = make_item(part_number="PN-JUNK2")
    id_junk = _requisicao_com_baixa(item, "TESTE", "Luis")

    conn = database.get_connection()
    achado = script._auditar(conn)
    mov = conn.execute("SELECT id FROM movimentacoes WHERE requisicao_id=?", (id_junk,)).fetchone()
    conn.close()

    assert [r["id"] for r in achado["movimentacoes_cascata"]] == [mov["id"]]


def test_guarda_chuva_criterio_exato(db, make_item, script):
    item = make_item(part_number="PN-GC")
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO guarda_chuva (item_id,fornecedor_codigo,fornecedor_nome,qtd_negociada,"
            "qtd_recebida,estagio) VALUES (?,?,?,?,?,?)",
            (item, "F1", "Miguel do papel", 100, 0, "Pedido Colocado"),
        )
        conn.execute(
            "INSERT INTO guarda_chuva (item_id,fornecedor_codigo,fornecedor_nome,qtd_negociada,"
            "qtd_recebida,estagio) VALUES (?,?,?,?,?,?)",
            (item, "F2", "Fornecedor Real", 100, 0, "Pedido Colocado"),
        )

    conn = database.get_connection()
    achado = script._auditar(conn)
    conn.close()

    nomes = [r["fornecedor_nome"] for r in achado["guarda_chuva"]]
    assert nomes == ["Miguel do papel"]


def test_freio_de_seguranca_aborta_sem_apagar(db, make_item, script, capsys):
    """Ids encontrados != APROVADO (hardcoded do relatório real) -> main() aborta, mesmo
    com --aplicar, e nada muda no banco."""
    item = make_item(part_number="PN-FREIO")
    _requisicao_com_baixa(item, "TESTE", "TESTE")

    conn = database.get_connection()
    antes = script._contagens(conn)
    conn.close()

    script.sys.argv = ["limpeza_teste_v650.py", "--aplicar"]
    with pytest.raises(SystemExit):
        script.main()

    conn = database.get_connection()
    depois = script._contagens(conn)
    conn.close()
    assert antes == depois


def test_aplicar_apaga_so_o_aprovado_preserva_o_resto(db, make_item, script, monkeypatch, capsys):
    """Fluxo completo com os ids reais gerados no banco de teste (monkeypatch de APROVADO
    para simular 'a reauditoria bateu'): junk some, real sobrevive, FKs íntegras, lista
    TESTE desativada (não apagada), backup gravado em disco."""
    item = make_item(part_number="PN-FULL")

    id_junk = _requisicao_com_baixa(item, "TESTE", "TESTE")
    id_real = _requisicao_com_baixa(item, "ENG TESTE", "JOAO SILVA")

    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO guarda_chuva (item_id,fornecedor_codigo,fornecedor_nome,qtd_negociada,"
            "qtd_recebida,estagio) VALUES (?,?,?,?,?,?)",
            (item, "F1", "Miguel do papel", 100, 0, "Pedido Colocado"),
        )
        conn.execute("INSERT INTO listas (tipo,valor,ativo) VALUES ('setor','TESTE',1)")

    conn = database.get_connection()
    achado = script._auditar(conn)
    mov_id = achado["movimentacoes_cascata"][0]["id"]
    gc_id = achado["guarda_chuva"][0]["id"]
    conn.close()

    # Simula que a reauditoria bateu com o relatório aprovado (ids reais deste banco de teste).
    monkeypatch.setattr(
        script,
        "APROVADO",
        {"requisicoes": [id_junk], "movimentacoes_cascata": [mov_id], "guarda_chuva": [gc_id]},
    )
    monkeypatch.setattr(script, "MOV_ID_AJUSTE_TESTE_AVULSO", None)  # nenhum ajuste avulso neste teste
    monkeypatch.setattr(script.sys, "argv", ["limpeza_teste_v650.py", "--aplicar"])

    script.main()

    conn = database.get_connection()
    # Junk sumiu (requisição, item e movimentação em cascata) e sem órfã.
    assert conn.execute("SELECT 1 FROM requisicoes WHERE id=?", (id_junk,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM itens_requisicao WHERE requisicao_id=?", (id_junk,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM movimentacoes WHERE id=?", (mov_id,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM guarda_chuva WHERE id=?", (gc_id,)).fetchone() is None

    # Real sobrevive intacto.
    real = conn.execute("SELECT id FROM requisicoes WHERE id=?", (id_real,)).fetchone()
    assert real is not None
    mov_real = conn.execute(
        "SELECT COUNT(*) c FROM movimentacoes WHERE requisicao_id=?", (id_real,)
    ).fetchone()["c"]
    assert mov_real == 1

    # Lista TESTE foi DESATIVADA, não apagada.
    lista = conn.execute("SELECT ativo FROM listas WHERE tipo='setor' AND valor='TESTE'").fetchone()
    assert lista is not None and lista["ativo"] == 0

    # Sem movimentação órfã (FK íntegra) no banco inteiro.
    orfas = conn.execute(
        "SELECT COUNT(*) c FROM movimentacoes m WHERE m.requisicao_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM requisicoes r WHERE r.id = m.requisicao_id)"
    ).fetchone()["c"]
    assert orfas == 0
    conn.close()

    backups_dir = Path(database.diretorio_backups())
    assert any("pre-limpeza-teste-v650" in p.name for p in backups_dir.glob("*.bak-*"))


def test_simulacao_nao_grava(db, make_item, script, monkeypatch):
    item = make_item(part_number="PN-SIM")
    id_junk = _requisicao_com_baixa(item, "TESTE", "TESTE")

    conn = database.get_connection()
    antes = script._contagens(conn)
    achado = script._auditar(conn)
    mov_id = achado["movimentacoes_cascata"][0]["id"]
    conn.close()

    monkeypatch.setattr(
        script,
        "APROVADO",
        {"requisicoes": [id_junk], "movimentacoes_cascata": [mov_id], "guarda_chuva": []},
    )
    monkeypatch.setattr(script, "MOV_ID_AJUSTE_TESTE_AVULSO", None)
    monkeypatch.setattr(script.sys, "argv", ["limpeza_teste_v650.py"])  # sem --aplicar

    script.main()

    conn = database.get_connection()
    depois = script._contagens(conn)
    conn.close()
    assert antes == depois
