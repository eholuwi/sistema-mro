"""v2.2.0 — Ingestão do "Relatório de SCs" (multi-aba): SCM (com preço), SC7
(histórico de preços), FORNECEDORES (e-mails) e SCM USERS (solicitantes)."""
import pandas as pd
from services import db_functions as F
import database


def _linha_scm(solicitante="Luis Gabriel Arruda de Oliveira", produto="PN-ING "):
    # produto com espaço à direita de propósito (testa o .strip() no match do PN)
    return {
        "SC": 5001, "Descrição da Solicitação": "Compra teste", "Status": "Pedido",
        "Solicitante": solicitante, "Produto": produto, "Descrição": "Item ING", "Qty": 10,
        "Justificativa/Projeto": "reposição", "Data Necessidade": "2026-06-01",
        "Emissão": "2026-05-01", "Aprovação": "2026-05-02", "Pedido": "F900",
        "Quantidade": 10, "Qtd.Entregue": 4, "Nome Fantasia": "FORN X",
        "Previsão NFe": "2026-06-10", "Documento": "NF1", "Prc Unitario": 12.5,
        "Vlr.Total": 125.0, "Moeda": 1, "Centro Custo": "21106", "Comprador": "Miguel",
        "Departamento": "ALMOX",
    }


def _build_relatorio(path, scm_rows=None):
    scm = pd.DataFrame(scm_rows if scm_rows is not None else [_linha_scm()])
    sc7 = pd.DataFrame([{
        "Filial": 1, "Tipo": 1, "Item": 1, "Pedido": "F900", "DT Emissao": "2026-05-01",
        "Produto": "PN-ING", "Descricao": "Item ING", "Unidade": "UN", "Moeda": 1,
        "Quantidade": 10, "Prc Unitario": 12.5, "Vlr.Total": 125.0, "Qtd.Entregue": 4,
        "Saldo": 6, "Observacoes": "SC: 5001", "OBS 1": "",
    }])
    forn = pd.DataFrame([{
        "Filial": 1, "Codigo": "F900", "Loja": "1", "Razao Social": "FORN X LTDA",
        "N Fantasia": "FORN X", "CNPJ/CPF": "11.111.111/0001-11",
        "E-Mail": "vendas@fornx.com", "Telefone": "1133", "Contato": "Ana", "Cond. Pagto": "30",
    }])
    users = pd.DataFrame([{
        "SOLICITANTE": "Fulano de Tal", "DEPARTAMENTO": "ENGENHARIA",
        "GERENTE IME": "G", "APROVADOR SCM": "A", "STATUS": "ATIVO",
    }])
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        scm.to_excel(w, sheet_name="SCM", index=False)                # header na linha 0
        sc7.to_excel(w, sheet_name="SC7", index=False, startrow=3)     # header na linha 3
        forn.to_excel(w, sheet_name="FORNECEDORES", index=False)       # header na linha 0
        users.to_excel(w, sheet_name="SCM USERS", index=False, startrow=1)  # header na linha 1
    return path


def test_importar_relatorio_end_to_end(db, make_item, tmp_path):
    item_id = make_item("PN-ING", estoque=5, minimo=10)
    p = _build_relatorio(str(tmp_path / "rel.xlsx"))
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert ok, res
    # SCM: SC importada + preço capturado
    assert res["SCM"]["linhas_importadas"] == 1
    assert res["SCM"]["precos_capturados"] == 1
    it = F.buscar_item_por_id(item_id)
    assert it["preco_referencia"] == 12.5
    # itens_sc guarda preço e moeda decodificada
    with database.transaction() as c:
        isc = c.execute("SELECT preco_unitario, moeda FROM itens_sc WHERE item_id=?", (item_id,)).fetchone()
    assert isc["preco_unitario"] == 12.5
    assert isc["moeda"] == "BRL"
    # SC7: histórico de preço
    assert res["SC7"]["precos_inseridos"] == 1
    # FORNECEDORES: e-mail
    assert res["FORNECEDORES"]["com_email"] == 1
    # SCM USERS: solicitante upsertado (sem marcar incluir_mro)
    assert res["SCM USERS"]["upserted"] == 1
    with database.transaction() as c:
        r = c.execute("SELECT incluir_mro FROM solicitantes_mro WHERE nome_norm=?",
                      ("fulano de tal",)).fetchone()
    assert r["incluir_mro"] == 0
    # snapshot do dia
    assert res["_snapshot_criados"] >= 1


def test_importar_relatorio_idempotente(db, make_item, tmp_path):
    make_item("PN-ING", estoque=5)
    p = _build_relatorio(str(tmp_path / "rel.xlsx"))
    F.importar_relatorio_scs(p, "rel.xlsx")
    with database.transaction() as c:
        n1 = c.execute("SELECT COUNT(*) FROM precos_historico").fetchone()[0]
        s1 = c.execute("SELECT COUNT(*) FROM solicitacoes_compra").fetchone()[0]
        i1 = c.execute("SELECT COUNT(*) FROM itens_sc").fetchone()[0]
    F.importar_relatorio_scs(p, "rel.xlsx")
    with database.transaction() as c:
        n2 = c.execute("SELECT COUNT(*) FROM precos_historico").fetchone()[0]
        s2 = c.execute("SELECT COUNT(*) FROM solicitacoes_compra").fetchone()[0]
        i2 = c.execute("SELECT COUNT(*) FROM itens_sc").fetchone()[0]
    assert (n1, s1, i1) == (n2, s2, i2)


def test_pn_inexistente_e_ignorado(db, tmp_path):
    # Sem cadastrar PN-ING no inventário → linha ignorada (não cria item).
    p = _build_relatorio(str(tmp_path / "rel.xlsx"))
    ok, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert res["SCM"]["linhas_importadas"] == 0
    assert res["SCM"]["linhas_ignoradas"] == 1


def test_solicitante_dinamico_controla_escopo(db, make_item, tmp_path):
    make_item("PN-ING", estoque=5)
    rows = [_linha_scm(solicitante="Pessoa Fora do Escopo")]
    p = _build_relatorio(str(tmp_path / "rel.xlsx"), scm_rows=rows)
    # Fora do escopo → ignorado
    _, res = F.importar_relatorio_scs(p, "rel.xlsx")
    assert res["SCM"]["linhas_importadas"] == 0
    # Ao marcar o solicitante como MRO, passa a ser importado
    with database.transaction() as c:
        c.execute(
            "INSERT INTO solicitantes_mro (nome,nome_norm,incluir_mro) VALUES (?,?,1)",
            ("Pessoa Fora do Escopo", F._normalizar_txt("Pessoa Fora do Escopo")),
        )
    _, res2 = F.importar_relatorio_scs(p, "rel.xlsx")
    assert res2["SCM"]["linhas_importadas"] == 1
