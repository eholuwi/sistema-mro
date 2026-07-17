"""v4.11.0 — Monitor de SC: tabela 'SCs/Itens não atendidos' via API do SCM.

Lógica PURA (sem rede) que monta a tabela a partir de dados JÁ buscados no SCM (cotações
em andamento + itens por SC via Timeline) cruzados com o inventário MRO. O `app.py` faz
as chamadas de rede (via `services.scm_client`) e injeta os dados aqui — mantendo este
módulo determinístico e testável com as amostras de `openapi/samples/`.

Definições (decisões do Luis):
- 'Não atendida' = SC em **FASE DE COTAÇÃO, sem pedido gerado**. A lista de cotações em
  andamento (`/Cotacao/ListInCotacoes`) já é, por definição, o que ainda não virou pedido.
- **Escopo = almoxarifado**: solicitante ∈ `solicitantes_mro` E PN ∈ inventário MRO.
- **Status / Esgotado em / Faltando (d)** vêm do MRO (mesma semântica da aba 'Saldo em
  Estoque'): `status_material` e `previsao_ruptura_dias` do inventário.
"""
from __future__ import annotations

from datetime import date, timedelta

from services.constants import PREVISAO_RUPTURA_SEM_RISCO
from services.db_functions import _normalizar_txt

COLUNAS_SCS_NAO_ATENDIDAS = [
    "SC", "Produto", "Descrição", "Status", "UN",
    "QTY Solicitada", "Saldo PO", "Esgotado em", "Faltando (d)",
]


def cotacoes_no_escopo(list_in_cotacoes, solicitantes_mro):
    """Filtra `ListInCotacoes` ao escopo do almoxarifado pelo NOME do solicitante
    (`solicitacaoCompras.solicitante_Usuario.nome`), casado (acento/caixa-insensível) com
    `solicitantes_mro`. `solicitantes_mro=None` desliga o filtro. Deduplica por `sc_id`.
    Retorna [{'sc_id', 'solicitante'}]."""
    vistos, out = set(), []
    for x in (list_in_cotacoes or []):
        sc = x.get("solicitacaoCompras") or {}
        nome = (sc.get("solicitante_Usuario") or {}).get("nome")
        if solicitantes_mro is not None and _normalizar_txt(nome) not in solicitantes_mro:
            continue
        sc_id = sc.get("id")
        if sc_id is None or sc_id in vistos:
            continue
        vistos.add(sc_id)
        out.append({"sc_id": sc_id, "solicitante": (nome or "").strip()})
    return out


def _esgotado_faltando(prev_ruptura, hoje):
    """(esgotado_em 'YYYY-MM-DD' | None, faltando_dias float | None) a partir da previsão
    de ruptura do MRO — só quando há risco (< PREVISAO_RUPTURA_SEM_RISCO)."""
    if prev_ruptura is None or prev_ruptura >= PREVISAO_RUPTURA_SEM_RISCO:
        return None, None
    faltando = round(float(prev_ruptura), 1)
    esgotado = (hoje + timedelta(days=int(prev_ruptura))).strftime("%Y-%m-%d")
    return esgotado, faltando


def montar_scs_nao_atendidas(cotacoes_escopo, itens_por_sc, inv_por_pn, hoje=None):
    """Monta as linhas (por ITEM) da tabela 'SCs/Itens não atendidos'.

    - `cotacoes_escopo`: saída de `cotacoes_no_escopo`.
    - `itens_por_sc`: {sc_id: [item_timeline, …]} — item tem 'produto', 'quantidade', 'um',
      'descricaoGenerico' (formato do `/SolicitacaoCompras/Timeline`).
    - `inv_por_pn`: {PN_UPPER: {status_material, unidade, nome_item, previsao_ruptura_dias}}.

    Mantém só itens cujo PN ∈ inventário MRO. 'Saldo PO' = QTY Solicitada (em cotação nada
    foi pedido ainda). Ordena por 'Faltando (d)' asc (None por último)."""
    hoje = hoje or date.today()
    linhas = []
    for cot in (cotacoes_escopo or []):
        sc_id = cot.get("sc_id")
        for it in (itens_por_sc.get(sc_id) or []):
            pn = str(it.get("produto") or "").strip().upper()
            inv = inv_por_pn.get(pn)
            if not inv:
                continue
            esgotado, faltando = _esgotado_faltando(inv.get("previsao_ruptura_dias"), hoje)
            qty = float(it.get("quantidade") or 0)
            un = (str(it.get("um") or "").strip() or inv.get("unidade") or "")
            linhas.append({
                "SC": sc_id,
                "Produto": pn,
                "Descrição": inv.get("nome_item") or str(it.get("descricaoGenerico") or "").strip(),
                "Status": inv.get("status_material") or "",
                "UN": un,
                "QTY Solicitada": qty,
                "Saldo PO": qty,   # em cotação: nada pedido ainda → saldo = qtd solicitada
                "Esgotado em": esgotado,
                "Faltando (d)": faltando,
            })
    linhas.sort(key=lambda r: (r["Faltando (d)"] is None,
                               r["Faltando (d)"] if r["Faltando (d)"] is not None else 0.0))
    return linhas
