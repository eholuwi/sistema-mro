"""v5.1.0 (F2) — Sincronização SCM persistente (API → mro.db).

A API do SCM (só-leitura, anônima, interna) passa a ser **fonte primária** persistindo no
`mro.db`; o "Relatório de SCs" (Excel) vira **fallback**. Este módulo tem duas metades:

- **Parsers PUROS** (`normalizar_sc_api` / `normalizar_itens_api`) — transformam o JSON cru
  da API em dicts prontos p/ upsert. Testáveis sem rede/banco, com fixtures reais em
  `tests/fixtures/scm/`.
- **Orquestrador** (`sincronizar`) — por solicitante MRO: `ByUser` (cabeçalhos) + `Timeline`
  (itens) → upsert numa transação por solicitante, reusando o padrão COALESCE de `ingerir_scm`
  (a API enriquece, nunca apaga o que só o Excel tem). Dedup por `numero_sc` (= id da API).

Regras herdadas (ver `scm_client`): API só-GET, dois formatos de resposta, padding Protheus,
datas nulas `0001-01-01`, campo de preço com o typo `valorUnitaro`.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import date, datetime, timedelta

import database
from database import transaction, _backup_db
from services import scm_client
from services.scm_client import _num, _trim
from services.db_functions import (
    _status_sc_importado, _log_importacao, _normalizar_txt, _upsert_item_sc_externo,
)


# ── Helpers puros ─────────────────────────────────────────────────────────────

def _data_api(valor):
    """Data ISO da API (`2026-07-16T11:33:17.63`) → `'YYYY-MM-DD'`.
    Nulos (`None`, `''`, sentinela Protheus `0001-01-01…`) → `None`."""
    if not valor:
        return None
    s = str(valor).strip()
    if not s or s.startswith("0001-01-01"):
        return None
    cabeca = s[:10]
    if len(cabeca) == 10 and cabeca[4] == "-" and cabeca[7] == "-":
        return cabeca
    return None


# Código de status da SC na API → (token Protheus p/ `_status_sc_importado`, hint de saldo).
# Reusa a função do importador Excel para produzir EXATAMENTE os mesmos rótulos
# ("Em Cotação", "Pedido Emitido", "Aguardando Aprovação", "Recebido") — nunca duplicar
# esse vocabulário. Códigos observados na doc SCM §7.13 são INFERIDOS: validar na F2 com
# dado real e ajustar este dict (o código cru fica salvo em `status_protheus`, nada se perde).
_STATUS_SC_API = {
    "01": ("aprovacao", 1),  # criada / aguardando aprovação
    "03": ("cotacao", 1),    # aprovada, em cotação
    "05": ("pedido", 1),     # pedido emitido
}


def _mapear_status_api(codigo_sc):
    """Código de status da API (`'03'`) → rótulo canônico do MRO, via `_status_sc_importado`.
    Código desconhecido → 'Aguardando Aprovação' (default seguro; código cru vai p/ status_protheus)."""
    token, saldo = _STATUS_SC_API.get(str(codigo_sc or "").strip(), ("aprovacao", 1))
    return _status_sc_importado(token, saldo)


# Ordem de progresso do ciclo da SC. O sync NUNCA rebaixa (garante "re-sync não regride"):
# o ByUser pode estar defasado vs. o Excel (que enxerga baixa/PO). Rótulos = os de
# `_status_sc_importado`. Cancelado é terminal (rank alto → não é sobrescrito por status vivo).
_RANK_STATUS = {
    "Aguardando Aprovação": 1,
    "Em Cotação": 2,
    "Pedido Emitido": 3,
    "Recebido": 4,
    "Cancelado": 5,
}


# ── Parsers puros ─────────────────────────────────────────────────────────────

def normalizar_sc_api(sc):
    """Cabeçalho de uma SC do `ByUser` → dict de campos do MRO. PURO (sem rede/banco).

    `ByUser` traz só o cabeçalho — os itens vêm de `normalizar_itens_api(Timeline)`.
    `status_code` é o código cru (mapeado p/ rótulo no upsert); `sc_id_scm`/`numero_sc`
    são o id inteiro da API (chave de dedup)."""
    if not isinstance(sc, dict):
        return None
    sc_id = sc.get("id")
    if sc_id in (None, ""):
        return None
    usuario = sc.get("solicitante_Usuario") or {}
    centro = sc.get("centroCusto") or {}
    cotacoes = sc.get("cotacao") or []
    cot_codigo = None
    if isinstance(cotacoes, list) and cotacoes and isinstance(cotacoes[0], dict):
        cot_codigo = _trim(cotacoes[0].get("codigo")) or None
    return {
        "sc_id_scm": int(sc_id),
        "numero_sc": str(sc_id).strip(),
        "solicitante": _trim(usuario.get("nome")),
        "solicitante_codigo": _trim(sc.get("solicitante")),
        "centro_custo": _trim(centro.get("descricao")) or _trim(sc.get("centroCustoCodigo")) or None,
        "descricao_sc": _trim(sc.get("descricao")) or None,
        "status_code": _trim(sc.get("status")),
        "data_abertura": _data_api(sc.get("dtCreated")),
        "data_aprovacao": _data_api(sc.get("dtAproved")),
        "justificativa": _trim(sc.get("justificativa")),
        "prioridade_critica": bool(sc.get("isCritico")),
        "cotacao_codigo": cot_codigo,
    }


def normalizar_itens_api(timeline_result):
    """`result` do `Timeline` → lista de itens (dicts). PURO.

    Lê `items[]`: `produto`→part_number, `produtoData.descricao`→descrição, `quantidade`,
    `um`→unidade, **`valorUnitaro`** (typo da API)→preço, `valorTotal`, `dataNecessidade`.
    Itens sem part_number são ignorados."""
    if not isinstance(timeline_result, dict):
        return []
    itens = []
    for it in (timeline_result.get("items") or []):
        if not isinstance(it, dict):
            continue
        pn = _trim(it.get("produto"))
        if not pn:
            continue
        pdata = it.get("produtoData") or {}
        itens.append({
            "part_number": pn,
            "descricao": _trim(pdata.get("descricao")) or _trim(it.get("descricaoGenerico")) or pn,
            "quantidade": _num(it.get("quantidade")),
            "unidade": _trim(it.get("um")) or None,
            "preco_unitario": _num(it.get("valorUnitaro")),
            "valor_total": _num(it.get("valorTotal")),
            "data_necessidade": _data_api(it.get("dataNecessidade")),
        })
    return itens


# ── Resolução de código do solicitante (nome → código Protheus via /Usuario) ──

def resolver_codigos_solicitantes(conn=None):
    """Preenche `solicitantes_mro.codigo` (faltantes, incluir_mro=1) casando o nome com o
    diretório `/Usuario` da API. Normaliza os DOIS lados com `_normalizar_txt` (não depende
    de como `nome_norm` foi gravado). Retorna quantos foram resolvidos. Falha de rede → 0.
    `conn=None` → abre a própria transação (uso pela UI de Configurações)."""
    if conn is None:
        with transaction() as c:
            return resolver_codigos_solicitantes(c)
    faltantes = conn.execute(
        "SELECT id, nome FROM solicitantes_mro "
        "WHERE incluir_mro=1 AND (codigo IS NULL OR TRIM(codigo)='')"
    ).fetchall()
    if not faltantes:
        return 0
    try:
        usuarios = scm_client.usuarios() or []
    except Exception:
        return 0
    mapa = {}
    for u in usuarios:
        if not isinstance(u, dict):
            continue
        nome = _normalizar_txt(u.get("nome"))
        cod = (u.get("codigo") or "").strip()
        if nome and cod:
            mapa.setdefault(nome, cod)
    resolvidos = 0
    for row in faltantes:
        cod = mapa.get(_normalizar_txt(row["nome"]))
        if cod:
            conn.execute("UPDATE solicitantes_mro SET codigo=? WHERE id=?", (cod, row["id"]))
            resolvidos += 1
    return resolvidos


def _solicitantes_para_sync(conn):
    """Solicitantes MRO (incluir_mro=1) COM código — os únicos sincronizáveis via ByUser."""
    rows = conn.execute(
        "SELECT id, nome, codigo FROM solicitantes_mro "
        "WHERE incluir_mro=1 AND codigo IS NOT NULL AND TRIM(codigo)<>'' ORDER BY nome"
    ).fetchall()
    return [(r["id"], r["nome"], str(r["codigo"]).strip()) for r in rows]


# ── Upserts (mesmo espírito COALESCE de ingerir_scm: API enriquece, não apaga) ─

def _upsert_item_api(conn, sc_id, it, agora, resumo):
    """Item da API: PN no inventário → `itens_sc`; fora do inventário → `itens_sc_externos`."""
    inv = conn.execute("SELECT id FROM inventario WHERE part_number=?", (it["part_number"],)).fetchone()
    preco, vtot = it["preco_unitario"], it["valor_total"]
    if not inv:
        _upsert_externo_api(conn, sc_id, it, resumo)
        return
    item_id = inv["id"]
    ex = conn.execute("SELECT id FROM itens_sc WHERE sc_id=? AND item_id=?", (sc_id, item_id)).fetchone()
    if ex:
        conn.execute("""
            UPDATE itens_sc SET
                quantidade_solicitada=COALESCE(?, quantidade_solicitada),
                descricao_detalhada=COALESCE(?, descricao_detalhada),
                data_necessidade=COALESCE(?, data_necessidade),
                preco_unitario=CASE WHEN ?>0 THEN ? ELSE preco_unitario END,
                valor_total=CASE WHEN ?>0 THEN ? ELSE valor_total END,
                ultima_importacao=?, origem=?
            WHERE id=?
        """, (it["quantidade"], it["descricao"], it["data_necessidade"],
              preco, preco, vtot, vtot, agora, "api_scm", ex["id"]))
    else:
        # Novo item pela API: nada recebido ainda → saldo = qtd solicitada, status 'Aberto'.
        conn.execute("""
            INSERT INTO itens_sc
                (sc_id, item_id, quantidade_solicitada, quantidade_recebida, data_necessidade,
                 descricao_detalhada, saldo_residual, status_item, ultima_importacao,
                 preco_unitario, valor_total, origem)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (sc_id, item_id, it["quantidade"], 0, it["data_necessidade"],
              it["descricao"], it["quantidade"], "Aberto", agora, preco, vtot, "api_scm"))
        conn.execute("UPDATE inventario SET ultima_sc_id=? WHERE id=?", (sc_id, item_id))
    resumo["itens"] += 1


def _upsert_externo_api(conn, sc_id, it, resumo):
    """Item cujo PN não está no inventário MRO → `itens_sc_externos` (reusa o helper do
    importador; a API não fornece PO no item, então `numero_po=None`)."""
    _upsert_item_sc_externo(conn, sc_id, it["part_number"], it["descricao"], it["quantidade"],
                            it["unidade"], it["preco_unitario"], it["valor_total"], None,
                            it["data_necessidade"], "api_scm")
    resumo["externos"] += 1


def _upsert_sc_api(conn, cab, itens, resumo, divergencias):
    """Upsert de uma SC (cabeçalho + itens) vinda da API. Dedup por `sc_id_scm`/`numero_sc`.
    API autoritativa em status/datas/centro de custo; campos só-Excel (numero_po, fornecedor,
    comprador, saving, previsão NFe, departamento) ficam intactos (não entram no SET).
    Nunca rebaixa uma SC já 'Recebido' (estado terminal vindo da baixa registrada no Excel)."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    api_status = _mapear_status_api(cab["status_code"])
    row = conn.execute(
        "SELECT id, status FROM solicitacoes_compra WHERE sc_id_scm=? OR numero_sc=? LIMIT 1",
        (cab["sc_id_scm"], cab["numero_sc"])).fetchone()
    if row:
        sc_id = row["id"]
        atual = row["status"]
        # Nunca rebaixa: se o status do banco (ex.: vindo do Excel) está mais adiante que o
        # da API, mantém o do banco. Só sobe ou fica igual.
        rebaixaria = atual and _RANK_STATUS.get(atual, 0) > _RANK_STATUS.get(api_status, 0)
        status_final = atual if rebaixaria else api_status
        if atual and atual != api_status and len(divergencias) < 50:
            divergencias.append({"numero_sc": cab["numero_sc"], "banco": atual,
                                 "api": api_status, "mantido_banco": bool(rebaixaria)})
        conn.execute("""
            UPDATE solicitacoes_compra SET
                sc_id_scm=COALESCE(?, sc_id_scm), status=?, status_protheus=?,
                data_abertura=COALESCE(?, data_abertura),
                data_aprovacao=COALESCE(?, data_aprovacao),
                centro_custo=COALESCE(?, centro_custo),
                solicitante=COALESCE(?, solicitante),
                descricao_solicitacao=COALESCE(?, descricao_solicitacao),
                observacoes=COALESCE(?, observacoes),
                cotacao_codigo=COALESCE(?, cotacao_codigo),
                prioridade_critica=?, origem_importacao=?, data_importacao=?, data_sync_api=?
            WHERE id=?
        """, (cab["sc_id_scm"], status_final, cab["status_code"], cab["data_abertura"],
              cab["data_aprovacao"], cab["centro_custo"], cab["solicitante"] or None,
              cab["descricao_sc"], cab["justificativa"] or None, cab["cotacao_codigo"],
              1 if cab["prioridade_critica"] else 0, "api_scm", agora, agora, sc_id))
        resumo["scs_atualizadas"] += 1
    else:
        # data_abertura é NOT NULL — fallback p/ hoje se a API não trouxe emissão (idem ingerir_scm).
        data_abertura = cab["data_abertura"] or date.today().strftime("%Y-%m-%d")
        cur = conn.execute("""
            INSERT INTO solicitacoes_compra
                (numero_sc, sc_id_scm, data_abertura, data_aprovacao, centro_custo, status,
                 observacoes, solicitante, descricao_solicitacao, status_protheus,
                 cotacao_codigo, prioridade_critica, origem_importacao, data_importacao, data_sync_api)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (cab["numero_sc"], cab["sc_id_scm"], data_abertura, cab["data_aprovacao"],
              cab["centro_custo"], api_status, cab["justificativa"] or None,
              cab["solicitante"] or None, cab["descricao_sc"], cab["status_code"],
              cab["cotacao_codigo"], 1 if cab["prioridade_critica"] else 0, "api_scm", agora, agora))
        sc_id = cur.lastrowid
        resumo["scs_criadas"] += 1
    for it in itens:
        _upsert_item_api(conn, sc_id, it, agora, resumo)
    resumo["scs"] += 1


# ── Orquestrador ──────────────────────────────────────────────────────────────

def _resumo_zerado():
    return {"solicitantes": 0, "scs": 0, "scs_criadas": 0, "scs_atualizadas": 0,
            "itens": 0, "externos": 0, "divergencias": 0, "erros": []}


def _backup_1x_dia():
    """`_backup_db('sync-api')` no máximo 1×/dia (guarda pela data no nome do .bak).

    v5.5.0/F5: os .bak passaram a ser gravados em `backups/` ao lado do banco, então a
    guarda precisa varrer esse diretório — varrendo o local antigo ela nunca encontraria
    nada e faria backup a cada sync."""
    try:
        hoje_str = date.today().strftime("%Y%m%d")
        alvo = os.path.join(
            database.diretorio_backups(),
            f"{os.path.basename(database.DB_PATH)}.bak-{hoje_str}-*sync-api",
        )
        if not glob.glob(alvo):
            _backup_db("sync-api")
    except Exception:
        pass


def sincronizar(periodo_dias=180, progress_cb=None, hoje=None, backup=True):
    """Sincroniza SCs MRO da API para o `mro.db`. Manual ("Atualizar agora").

    Por solicitante MRO com código: `ByUser(hoje−periodo, hoje)` (cabeçalhos) + `Timeline`
    por SC (itens) → upsert numa transação por solicitante (queda no meio preserva os
    concluídos). Registra `log_importacoes` tipo `api_scm`. **Não** invalida cache (regra
    services↛ui): quem chama (Monitor) faz `invalidar_leituras()` ao terminar.

    `progress_cb(nome, indice, total)` é chamado por solicitante. Retorna o resumo (dict)."""
    resumo = _resumo_zerado()
    if not scm_client.esta_disponivel():
        resumo["ok"] = False
        resumo["erro"] = "API do SCM indisponível — nenhuma alteração feita. Use o Relatório de SCs (Excel)."
        return resumo

    hoje = hoje or date.today()
    fim = hoje.strftime("%Y%m%d")
    ini = (hoje - timedelta(days=periodo_dias)).strftime("%Y%m%d")
    if backup:
        _backup_1x_dia()

    with transaction() as conn:
        resolver_codigos_solicitantes(conn)
        solicitantes = _solicitantes_para_sync(conn)
    resumo["solicitantes"] = len(solicitantes)
    divergencias = []

    for idx, (sid, nome, codigo) in enumerate(solicitantes):
        if progress_cb:
            progress_cb(nome, idx, len(solicitantes))
        try:
            scs = scm_client.sc_por_usuario(codigo, ini, fim) or []
        except Exception as e:
            resumo["erros"].append({"solicitante": nome, "erro": f"ByUser: {e}"})
            continue
        # Rede (Timeline por SC) FORA da transação de escrita.
        preparadas = []
        for sc_raw in scs:
            cab = normalizar_sc_api(sc_raw)
            if not cab:
                continue
            try:
                tl = scm_client.sc_timeline(cab["sc_id_scm"])
                itens = normalizar_itens_api(tl)
            except Exception as e:
                itens = []
                resumo["erros"].append({"sc": cab["numero_sc"], "erro": f"Timeline: {e}"})
            preparadas.append((cab, itens))
        try:
            with transaction() as conn:
                for cab, itens in preparadas:
                    _upsert_sc_api(conn, cab, itens, resumo, divergencias)
        except Exception as e:
            resumo["erros"].append({"solicitante": nome, "erro": f"upsert: {e}"})

    if progress_cb:
        progress_cb(None, len(solicitantes), len(solicitantes))
    resumo["divergencias"] = len(divergencias)
    resumo["ok"] = True
    status_geral = "parcial" if resumo["erros"] else "ok"
    with transaction() as conn:
        _log_importacao(
            conn, "api_scm", "sincronizacao SCM",
            resumo["scs"], resumo["scs_criadas"] + resumo["scs_atualizadas"], resumo["externos"],
            {"status": status_geral, "periodo_dias": periodo_dias, "ini": ini, "fim": fim,
             "resumo": {k: resumo[k] for k in
                        ("solicitantes", "scs", "scs_criadas", "scs_atualizadas", "itens", "externos", "divergencias")},
             "divergencias_amostra": divergencias[:50], "erros": resumo["erros"][:20]})
    return resumo


def ultima_sync(conn=None):
    """Última sincronização via API (linha mais recente de `log_importacoes` tipo `api_scm`).
    Retorna `{'data_hora', 'detalhe'}` ou `None`."""
    q = ("SELECT data_hora, detalhe_json FROM log_importacoes "
         "WHERE tipo='api_scm' ORDER BY id DESC LIMIT 1")
    if conn is not None:
        row = conn.execute(q).fetchone()
    else:
        with transaction() as c:
            row = c.execute(q).fetchone()
    if not row:
        return None
    try:
        detalhe = json.loads(row["detalhe_json"] or "{}")
    except Exception:
        detalhe = {}
    return {"data_hora": row["data_hora"], "detalhe": detalhe}
