"""v4.10.0 — Monitor de SC: 'SCs/Itens não atendidos' via API do SCM.

Testa a lógica PURA de `services/monitor_scm.py` (sem rede): filtro de cotações ao escopo
do almoxarifado por nome de solicitante (acento/caixa-insensível + dedup), e a montagem
da tabela por item (só PN do MRO; Status/Esgotado/Faltando do inventário; ordenação por
urgência). Os dados do SCM são injetados — nenhuma chamada de rede aqui.
"""

from datetime import date

from services.constants import PREVISAO_RUPTURA_SEM_RISCO
from services.db_functions import _normalizar_txt
from services.monitor_scm import (
    COLUNAS_SCS_NAO_ATENDIDAS,
    cotacoes_no_escopo,
    montar_scs_nao_atendidas,
)


def _cot(sc_id, nome):
    return {"solicitacaoCompras": {"id": sc_id, "solicitante_Usuario": {"nome": nome}}}


# ── cotacoes_no_escopo ────────────────────────────────────────────────────────


def test_escopo_filtra_por_nome_acento_insensivel_e_dedup():
    solic = {_normalizar_txt("Jasiva Lopes"), _normalizar_txt("Juan Tarco")}
    lic = [
        _cot(1, "Jasiva Lopes"),
        _cot(2, "Fulano Fora do Escopo"),
        _cot(1, "JASIVA LOPES"),  # mesmo sc_id → dedup
        _cot(3, "juan  tarco"),  # caixa/espaço → casa mesmo assim
    ]
    esc = cotacoes_no_escopo(lic, solic)
    assert [c["sc_id"] for c in esc] == [1, 3]


def test_escopo_none_desliga_filtro():
    lic = [_cot(1, "Qualquer"), _cot(2, "Outro")]
    assert [c["sc_id"] for c in cotacoes_no_escopo(lic, None)] == [1, 2]


def test_escopo_ignora_sem_id_ou_sem_sc():
    lic = [
        {"solicitacaoCompras": {"solicitante_Usuario": {"nome": "X"}}},  # sem id
        {"foo": "bar"},
    ]  # sem SC
    assert cotacoes_no_escopo(lic, None) == []


# ── montar_scs_nao_atendidas ──────────────────────────────────────────────────

_INV = {
    "PN-A": {
        "status_material": "🔴 COMPRAR",
        "unidade": "UN",
        "nome_item": "Item A",
        "previsao_ruptura_dias": 3,
    },
    "PN-B": {
        "status_material": "🟢 OK",
        "unidade": "CX",
        "nome_item": "Item B",
        "previsao_ruptura_dias": PREVISAO_RUPTURA_SEM_RISCO + 10,
    },
}


def test_monta_linha_e_ignora_pn_fora_do_mro():
    cot = [{"sc_id": 10, "solicitante": "X"}]
    itens = {
        10: [
            {"produto": "pn-a ", "quantidade": 30, "um": "PT", "descricaoGenerico": "AAA"},
            {"produto": "PN-Z", "quantidade": 5, "um": "UN"},  # não está no inventário MRO
        ]
    }
    rows = montar_scs_nao_atendidas(cot, itens, _INV, hoje=date(2026, 7, 17))
    assert len(rows) == 1
    r = rows[0]
    assert list(r.keys()) == COLUNAS_SCS_NAO_ATENDIDAS
    assert r["SC"] == 10
    assert r["Produto"] == "PN-A"  # trim + upper
    assert r["Descrição"] == "Item A"  # nome do inventário
    assert r["Status"] == "🔴 COMPRAR"
    assert r["UN"] == "PT"  # 'um' do item
    assert r["QTY Solicitada"] == 30
    assert r["Saldo PO"] == 30  # em cotação = qtd solicitada
    assert r["Faltando (d)"] == 3.0
    assert r["Esgotado em"] == "2026-07-20"


def test_sem_risco_esgotado_e_faltando_none():
    cot = [{"sc_id": 20, "solicitante": "X"}]
    itens = {20: [{"produto": "PN-B", "quantidade": 4, "um": ""}]}
    r = montar_scs_nao_atendidas(cot, itens, _INV, hoje=date(2026, 7, 17))[0]
    assert r["Faltando (d)"] is None
    assert r["Esgotado em"] is None
    assert r["UN"] == "CX"  # 'um' vazio → cai na unidade do inventário


def test_ordena_por_faltando_none_por_ultimo():
    cot = [{"sc_id": 1, "solicitante": "X"}]
    itens = {
        1: [
            {"produto": "PN-B", "quantidade": 1, "um": "CX"},  # sem risco → faltando None
            {"produto": "PN-A", "quantidade": 1, "um": "UN"},  # faltando 3
        ]
    }
    rows = montar_scs_nao_atendidas(cot, itens, _INV, hoje=date(2026, 7, 17))
    assert [r["Produto"] for r in rows] == ["PN-A", "PN-B"]  # urgente primeiro, None por último


def test_sc_sem_itens_nao_quebra():
    assert montar_scs_nao_atendidas([{"sc_id": 9}], {}, _INV) == []
