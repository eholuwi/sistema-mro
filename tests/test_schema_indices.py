"""Fase 3 (DT-9): contrato dos indices de performance criados na migracao.

idx_inv_pn NAO consta do contrato: inventario(part_number) ja e indexado pelo
autoindex do UNIQUE (sqlite_autoindex_inventario_1); criar um indice nomeado
seria redundante. Exigimos apenas os 3 indices que cobrem FKs sem indice."""


def test_indices_essenciais_existem(db):
    conn = db.get_connection()
    nomes = {r["name"] for r in
             conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    # part_number ja possui indice automatico via UNIQUE
    autoidx_pn = {r["name"] for r in conn.execute("PRAGMA index_list(inventario)")}
    conn.close()
    esperados = {"idx_mov_item", "idx_mov_data", "idx_itens_sc_sc"}
    assert esperados.issubset(nomes)
    assert "sqlite_autoindex_inventario_1" in autoidx_pn  # part_number indexado
