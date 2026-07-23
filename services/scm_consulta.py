"""services/scm_consulta.py — v5.2.0 (F3 · Página SCM Integrado).

Camada de CONSULTA das SCs já persistidas no `mro.db` (pelo Excel e/ou pela API do
SCM, v5.1.0). PURO no que toca ao banco: monta list[dict] prontos para a UI, sem
Streamlit (mesmo espírito de `services/dashboards.py`). A parte "ao vivo da API"
(`detalhes_sc_api`) consulta o SCM em tempo real, mas cada bloco é isolado em
try/except — nunca lança para fora e degrada sozinho quando a rede/serviço falha.

Reusa o que já existe (regra anti-duplicação): `listar_itens_sc` para os itens do
banco na aba Detalhes, `scm_sync.normalizar_itens_api` para os itens vindos da
Timeline, e o cliente `scm_client` para os endpoints de leitura.
"""
from __future__ import annotations

from database import transaction
from services.db_functions import listar_itens_sc
from services import scm_client, scm_sync

# Filial padrão do Protheus para os endpoints de Pedido/aprovadores. A base é
# mono-filial ("01" em todas as amostras); o schema não guarda filial por SC.
_FILIAL_PADRAO = "01"


# ── Aba 1 — Solicitações de Compra ────────────────────────────────────────────

def listar_scs_consulta(conn=None):
    """Uma linha por SC (todas, não só as abertas), com POs consolidados de `itens_sc`
    ∪ `itens_sc_externos` e a próxima data de necessidade. Ordena por emissão desc.

    Devolve list[dict] com as colunas da aba: numero_sc, status, solicitante, comprador,
    centro_custo, descricao_solicitacao, justificativa (=observacoes), data_abertura,
    data_aprovacao, proxima_necessidade, pos, prioridade_critica, origem_importacao,
    data_sync_api, sc_id_scm, cotacao_codigo, numero_po."""
    if conn is None:
        with transaction() as c:
            return listar_scs_consulta(c)
    rows = conn.execute("""
        SELECT sc.id, sc.numero_sc, sc.status, sc.solicitante, sc.comprador,
               sc.centro_custo, sc.descricao_solicitacao,
               sc.observacoes AS justificativa,
               sc.data_abertura, sc.data_aprovacao, sc.numero_po,
               sc.prioridade_critica, sc.origem_importacao, sc.data_sync_api,
               sc.sc_id_scm, sc.cotacao_codigo,
               MIN(pos.data_necessidade) AS proxima_necessidade,
               GROUP_CONCAT(DISTINCT pos.po) AS pos
        FROM solicitacoes_compra sc
        LEFT JOIN (
            SELECT sc_id, numero_po AS po, data_necessidade FROM itens_sc
            UNION ALL
            SELECT sc_id, numero_po AS po, data_necessidade FROM itens_sc_externos
        ) pos ON pos.sc_id = sc.id
        GROUP BY sc.id
        ORDER BY sc.data_abertura DESC, sc.id DESC
    """).fetchall()
    resultado = []
    for r in rows:
        d = dict(r)
        d["prioridade_critica"] = bool(d.get("prioridade_critica"))
        # GROUP_CONCAT pode juntar POs vazios/None; normaliza para lista limpa.
        pos = [p.strip() for p in (d.pop("pos") or "").split(",") if p and p.strip()]
        d["pos"] = ", ".join(sorted(set(pos)))
        resultado.append(d)
    return resultado


# ── Aba 2 — Itens das SCs ─────────────────────────────────────────────────────

def listar_itens_consulta(conn=None):
    """Um registro por item de SC: `itens_sc` (PN no inventário MRO) UNION
    `itens_sc_externos` (PN fora do inventário). Coluna `fora_do_inventario` (bool) e
    `origem` ('excel'|'api_scm') distinguem os dois. Ordena por SC desc, depois PN."""
    if conn is None:
        with transaction() as c:
            return listar_itens_consulta(c)
    rows = conn.execute("""
        SELECT sc.numero_sc, sc.status AS status_sc, sc.solicitante, sc.data_abertura,
               i.part_number, i.nome_item AS descricao,
               isc.quantidade_solicitada AS quantidade, i.unidade,
               isc.preco_unitario, isc.valor_total, isc.numero_po,
               isc.data_necessidade, isc.status_item, isc.origem,
               0 AS fora_do_inventario
        FROM itens_sc isc
        JOIN inventario i ON i.id = isc.item_id
        JOIN solicitacoes_compra sc ON sc.id = isc.sc_id
        UNION ALL
        SELECT sc.numero_sc, sc.status AS status_sc, sc.solicitante, sc.data_abertura,
               ex.part_number, ex.descricao,
               ex.quantidade, ex.unidade,
               ex.preco_unitario, ex.valor_total, ex.numero_po,
               ex.data_necessidade, NULL AS status_item, ex.origem,
               1 AS fora_do_inventario
        FROM itens_sc_externos ex
        JOIN solicitacoes_compra sc ON sc.id = ex.sc_id
        ORDER BY data_abertura DESC, numero_sc DESC, part_number
    """).fetchall()
    resultado = []
    for r in rows:
        d = dict(r)
        d["fora_do_inventario"] = bool(d.get("fora_do_inventario"))
        resultado.append(d)
    return resultado


# ── Aba 3 — Detalhes da SC (banco) ────────────────────────────────────────────

def detalhes_sc_banco(numero_sc, conn=None, precos_por_item=5):
    """Consolidação de uma SC a partir do BANCO: cabeçalho, itens (reusa
    `listar_itens_sc`), itens externos e preços históricos por item. Retorna None se a
    SC não existe. Não toca a rede."""
    if conn is None:
        with transaction() as c:
            return detalhes_sc_banco(numero_sc, c, precos_por_item)
    cab = conn.execute(
        "SELECT * FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)).fetchone()
    if not cab:
        return None
    cab = dict(cab)
    sc_id = cab["id"]
    itens = listar_itens_sc(sc_id)
    externos = [dict(r) for r in conn.execute(
        "SELECT * FROM itens_sc_externos WHERE sc_id=? ORDER BY part_number",
        (sc_id,)).fetchall()]
    # Preços históricos dos itens desta SC (últimos N por item), para leitura rápida.
    item_ids = [it["item_id"] for it in itens if it.get("item_id")]
    precos = []
    if item_ids:
        marcadores = ",".join("?" * len(item_ids))
        precos = [dict(r) for r in conn.execute(f"""
            SELECT ph.item_id, i.part_number, i.nome_item, ph.data, ph.preco_unitario,
                   ph.moeda, ph.fornecedor, ph.numero_sc, ph.numero_po, ph.lead_time_dias
            FROM precos_historico ph
            JOIN inventario i ON i.id = ph.item_id
            WHERE ph.item_id IN ({marcadores})
            ORDER BY ph.item_id, ph.data DESC, ph.id DESC
        """, item_ids).fetchall()]
        # Mantém só os `precos_por_item` mais recentes por item.
        vistos = {}
        filtrados = []
        for p in precos:
            n = vistos.get(p["item_id"], 0)
            if n < precos_por_item:
                filtrados.append(p)
                vistos[p["item_id"]] = n + 1
        precos = filtrados
    return {"cabecalho": cab, "itens": itens, "externos": externos, "precos": precos}


# ── Aba 3 — Detalhes da SC ("ao vivo" da API, sob demanda) ────────────────────

def detalhes_sc_api(sc_id_scm, numero_po=None, cotacao_codigo=None, filial=_FILIAL_PADRAO):
    """Enriquecimento AO VIVO de uma SC pela API do SCM. Cada bloco é independente e
    isolado em try/except: uma falha (rede, serviço reciclando, filial errada) degrada
    só aquele bloco, os demais continuam. NUNCA lança para fora.

    Retorna dict com chaves: `disponivel` (bool, health-check), `itens` (Timeline),
    `eventos` (Timelinev2), `cotacao` (GetByCodigo, só se `cotacao_codigo`),
    `pedido`/`aprovadores` (só se `numero_po`), `erros` (list de avisos por bloco).
    Blocos ausentes/indisponíveis vêm como None."""
    out = {"disponivel": False, "itens": None, "eventos": None, "cotacao": None,
           "pedido": None, "aprovadores": None, "erros": []}
    if not scm_client.esta_disponivel():
        return out
    out["disponivel"] = True

    if sc_id_scm:
        try:
            tl = scm_client.sc_timeline(sc_id_scm)
            out["itens"] = scm_sync.normalizar_itens_api(tl)
        except Exception as e:
            out["erros"].append(f"Itens (Timeline): {e}")
        try:
            out["eventos"] = scm_client.sc_timeline_v2(sc_id_scm)
        except Exception as e:
            out["erros"].append(f"Eventos (Timelinev2): {e}")

    if cotacao_codigo:
        try:
            out["cotacao"] = scm_client.cotacao_por_codigo(cotacao_codigo)
        except Exception as e:
            out["erros"].append(f"Cotação {cotacao_codigo}: {e}")

    if numero_po:
        try:
            out["pedido"] = scm_client.pedido(filial, numero_po)
        except Exception as e:
            out["erros"].append(f"Pedido {numero_po}: {e}")
        try:
            out["aprovadores"] = scm_client.aprovadores_pedido(filial, numero_po)
        except Exception as e:
            out["erros"].append(f"Aprovadores {numero_po}: {e}")

    return out
