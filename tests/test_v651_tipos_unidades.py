"""v6.5.1 — Tipos de Material e Unidades administraveis (tabela `listas`).

Os dois campos eram constantes hardcoded em `constants.py` e passaram a ser listas
mestras editaveis em Configuracoes. Nao ha schema novo: sao linhas em `listas`,
semeadas na primeira leitura com o que JA esta em uso no `inventario`.

O que estes testes protegem:
  - o caso do valor ("Spare Parts" nao pode virar "SPARE PARTS");
  - a armadilha soft-delete + UNIQUE(tipo,valor): remover e re-adicionar o mesmo
    valor precisa REATIVAR, nao estourar IntegrityError;
  - o seed rodar uma vez so (nao ressuscita o que o admin removeu);
  - a nao-regressao de `adicionar_valor_lista`, que segue em maiusculas para as
    outras cinco listas.
"""

import pytest

from services import db_functions as F
from services.constants import TIPOS, UNIDADES


def _valores(db, tipo, ativos_apenas=True):
    """Le a tabela `listas` crua, sem passar pelos helpers sob teste."""
    conn = db.get_connection()
    sql = "SELECT valor FROM listas WHERE tipo=?" + (" AND ativo=1" if ativos_apenas else "")
    rows = conn.execute(sql, (tipo,)).fetchall()
    conn.close()
    return [r["valor"] for r in rows]


# ── Seed lazy ─────────────────────────────────────────────────────────────────


def test_seed_nasce_com_o_que_esta_no_inventario_preservando_o_caso(db, make_item):
    make_item(part_number="PN-A", tipo="Spare Parts", unidade="UN")
    make_item(part_number="PN-B", tipo="Limpeza Stencil", unidade="GL")

    tipos = F.listar_valores_material("tipo_material")
    unidades = F.listar_valores_material("unidade")

    assert tipos == ["Limpeza Stencil", "Spare Parts"]  # ORDER BY valor
    assert unidades == ["GL", "UN"]
    # O seed nao pode passar por `adicionar_valor_lista` (que faz .upper()).
    assert "SPARE PARTS" not in tipos


def test_seed_e_idempotente_rodar_duas_vezes_nao_duplica(db, make_item):
    make_item(part_number="PN-A", tipo="Spare Parts", unidade="UN")

    F.listar_valores_material("tipo_material")
    F.listar_valores_material("tipo_material")
    F.listar_valores_material("tipo_material")

    assert _valores(db, "tipo_material") == ["Spare Parts"]


def test_seed_nao_ressuscita_valor_removido_pelo_admin(db, make_item):
    """O item continua com o tipo gravado; a lista, nao. Semear de novo a cada
    leitura desfaria a decisao do admin — por isso o seed roda uma vez so."""
    make_item(part_number="PN-A", tipo="Spare Parts", unidade="UN")
    F.listar_valores_material("tipo_material")

    F.remover_valor_lista("tipo_material", "Spare Parts")

    assert F.listar_valores_material("tipo_material", fallback=False) == []
    assert _valores(db, "tipo_material", ativos_apenas=False) == ["Spare Parts"]


def test_banco_sem_inventario_semeia_com_as_constantes(db):
    assert F.listar_valores_material("tipo_material") == sorted(TIPOS)
    assert F.listar_valores_material("unidade") == sorted(UNIDADES)


def test_lista_vazia_cai_no_fallback_das_constantes(db, make_item):
    """Admin removeu tudo: o Cadastro de Itens nao pode ficar sem opcao (fallback),
    mas Configuracoes precisa mostrar a lista como ela esta (sem fallback)."""
    make_item(part_number="PN-A", tipo="Spare Parts", unidade="UN")
    F.listar_valores_material("unidade")
    F.remover_valor_lista("unidade", "UN")

    assert F.listar_valores_material("unidade", fallback=False) == []
    # Fallback sai na ordem das constantes (UN primeiro, o default do cadastro);
    # o que vem do banco sai alfabetico (ORDER BY valor).
    assert F.listar_valores_material("unidade") == list(UNIDADES)


def test_lista_desconhecida_e_erro(db):
    with pytest.raises(ValueError):
        F.listar_valores_material("centro_custo")


# ── adicionar_valor_lista_txt ─────────────────────────────────────────────────


def test_adicionar_preserva_o_caso_digitado(db):
    ok, _ = F.adicionar_valor_lista_txt("tipo_material", "  Vestimenta ESD  ")

    assert ok
    assert "Vestimenta ESD" in _valores(db, "tipo_material")


def test_readicionar_valor_removido_reativa_sem_integrity_error(db):
    """UNIQUE(tipo,valor) + soft-delete: o INSERT cru estouraria IntegrityError."""
    F.adicionar_valor_lista_txt("unidade", "BB")
    F.remover_valor_lista("unidade", "BB")
    assert "BB" not in F.listar_valores_material("unidade", fallback=False)

    ok, msg = F.adicionar_valor_lista_txt("unidade", "BB")

    assert ok, msg
    assert "reativado" in msg
    assert _valores(db, "unidade", ativos_apenas=False).count("BB") == 1
    assert "BB" in F.listar_valores_material("unidade", fallback=False)


def test_adicionar_duplicado_ativo_nao_duplica(db):
    F.adicionar_valor_lista_txt("tipo_material", "Consumivel")

    ok, msg = F.adicionar_valor_lista_txt("tipo_material", "Consumivel")

    assert not ok
    assert "já existe" in msg
    assert _valores(db, "tipo_material").count("Consumivel") == 1


def test_adicionar_ignora_diferenca_de_caixa(db):
    """ "Un" e "UN" como opcoes distintas seria ruido puro no selectbox."""
    F.adicionar_valor_lista_txt("unidade", "UN")

    ok, _ = F.adicionar_valor_lista_txt("unidade", "un")

    assert not ok
    assert _valores(db, "unidade") == ["UN"]


def test_adicionar_vazio_e_recusado(db):
    ok, msg = F.adicionar_valor_lista_txt("unidade", "   ")

    assert not ok
    assert "vazio" in msg.lower()
    assert _valores(db, "unidade") == []


# ── Guarda de remocao ─────────────────────────────────────────────────────────


def test_contagem_de_itens_em_uso_orienta_a_remocao(db, make_item):
    make_item(part_number="PN-A", tipo="Spare Parts", unidade="UN")
    make_item(part_number="PN-B", tipo="Spare Parts", unidade="CX")

    assert F.contar_itens_com_valor("tipo_material", "Spare Parts") == 2
    assert F.contar_itens_com_valor("unidade", "un") == 1  # case-insensitive
    assert F.contar_itens_com_valor("unidade", "RL") == 0


def test_remocao_e_soft_delete_o_item_nao_perde_o_valor(db, make_item):
    """Remover da lista tira a opcao do menu, nao mexe no inventario."""
    item_id = make_item(part_number="PN-A", tipo="Spare Parts", unidade="UN")
    F.listar_valores_material("tipo_material")

    F.remover_valor_lista("tipo_material", "Spare Parts")

    conn = db.get_connection()
    row = conn.execute("SELECT tipo_material FROM inventario WHERE id=?", (item_id,)).fetchone()
    conn.close()
    assert row["tipo_material"] == "Spare Parts"


def test_contagem_de_lista_desconhecida_e_erro(db):
    with pytest.raises(ValueError):
        F.contar_itens_com_valor("fornecedor", "ACME")


# ── Item fora da lista continua editavel ──────────────────────────────────────


def test_valor_fora_da_lista_sobrevive_no_selectbox(db, make_item):
    """Item legado com tipo que ninguem cadastrou: `opcoes_com_atual` o mantem
    visivel, para o selectbox nao trocar o valor em silencio ao salvar."""
    from ui.componentes.selecao import opcoes_com_atual

    make_item(part_number="PN-A", tipo="Spare Parts", unidade="UN")
    F.listar_valores_material("tipo_material")
    F.remover_valor_lista("tipo_material", "Spare Parts")

    opcoes = opcoes_com_atual(F.listar_valores_material("tipo_material"), "Spare Parts")

    assert opcoes[0] == "Spare Parts"


# ── Nao-regressao das outras cinco listas ─────────────────────────────────────


def test_adicionar_valor_lista_original_segue_em_maiusculas(db):
    """As listas de codigo (centro de custo, local, fornecedor...) nao mudaram."""
    ok, msg = F.adicionar_valor_lista("local", "arm-99")

    assert ok
    assert "ARM-99" in msg
    assert "ARM-99" in F.listar_valores("local")
