"""v4.6.0 — Monitor de SC 2.0: cruzamento SCM × SC7 a partir dos dois exports CRUS.

Reproduz automaticamente o PROCV que os compradores fazem à mão (a aba "SCM" do
"Relatório de SCs"): a **demanda** (SCM / ``Solicitações.xlsx``) casada com a
**compra** (SC7 / ``Relatório de Compras.xlsx``) pela chave do PO
(``SCM.Pedido`` = ``SC7.Numero PC``), refinada por Produto (PN).

Funções **puras** sobre DataFrames — sem I/O de banco. O escopo MRO (solicitantes
+ PNs do inventário) e o mapa ``solicitante → departamento`` são **injetados** pelo
chamador (o ``app.py`` os lê do cadastro), mantendo o módulo testável e o
cruzamento efêmero (nada é gravado).

Achados que guiam o design (verificados nos arquivos reais):
- No SC7 cru o campo ``Numero da SC`` vem vazio; ``Numero PC`` (PO) está sempre
  preenchido → a chave é o **PO**, nunca o número da SC.
- SC7 não tem Status (dado puro de PO); o Status vem do SCM.
- Um PO tem várias linhas/itens no SC7 → agrega por ``(PO, PN)``.
"""

from __future__ import annotations

import pandas as pd

from services.db_functions import (
    _coluna,
    _valor,
    _to_float,
    _to_date_str,
    _normalizar_txt,
)

# ── Mapas de nomes de coluna aceitos (tolerantes a acento/pontuação via _coluna) ──
_SCM_COLS = {
    "sc": ["Numero da Solicitacao", "Número da Solicitação", "SC"],
    "solicitante": ["Solicitante"],
    "status": ["Status"],
    "produto": ["Produto", "Partnumber", "Part Number"],
    "descricao": ["Descricao Detalhada", "Descrição Detalhada", "Descrição", "Descricao", "Nome do item"],
    "quantidade": ["Quantidade", "Qty"],
    "data_necessidade": ["Data Necessidade"],
    "justificativa": ["Justificativa/Projeto", "Justificativa", "Projeto"],
    "pedido": ["Pedido", "Numero PC", "Número PC"],
    "documento": ["Documento"],
}
_SC7_COLS = {
    "pedido": ["Numero PC", "Pedido"],
    "produto": ["Produto"],
    "descricao": ["Descricao", "Descrição"],
    "qtd_entregue": ["Qtd.Entregue", "Qtd Entregue"],
    "saldo": ["Saldo"],
    "dt_entrega": ["Dt. Entrega", "Dt Entrega", "Data Entrega", "Entrega"],
    "fornecedor": ["Nome Fantasia", "Razão Social", "Razao Social", "Fornecedor"],
    "comprador": ["Comprador"],
}

# Colunas mínimas para o cruzamento fazer sentido.
_SCM_OBRIGATORIAS = ("sc", "produto", "pedido")
_SC7_OBRIGATORIAS = ("pedido", "produto", "saldo")

# Ordem das colunas de saída (espelha a aba "SCM" manual dos compradores).
COLUNAS_SAIDA = [
    "SC",
    "Solicitante",
    "Departamento",
    "Status",
    "Produto",
    "Descrição",
    "Qty (SC)",
    "Data Necessidade",
    "Justificativa",
    "PO",
    "Fornecedor",
    "Comprador",
    "Qtd Entregue",
    "Saldo",
    "Dt. Entrega",
    "Situação",
]


def _txt(valor) -> str:
    """Texto limpo (nunca None)."""
    return "" if valor is None else str(valor).strip()


def _key(valor) -> str:
    """Chave normalizada para join/escopo (trim + upper)."""
    return _txt(valor).upper()


def _mapear(df, mapa):
    """{chave_lógica: nome_real_da_coluna_ou_None} para um DataFrame."""
    return {k: _coluna(df, nomes) for k, nomes in mapa.items()}


def _faltantes(colmap, obrigatorias, mapa):
    """Nomes 'humanos' das colunas obrigatórias não encontradas."""
    return [mapa[k][0] for k in obrigatorias if not colmap.get(k)]


def detectar_header(xls, aba_preferida, chaves, mapa, max_linhas=6):
    """Escolhe a aba e a linha de cabeçalho onde as ``chaves`` obrigatórias resolvem.

    Robustez p/ SC7 cru (header 0) e SC7 dentro do "Relatório de SCs" (header 3),
    e p/ SCM (header 0). Retorna ``(df, aba, header)`` ou ``(None, aba, None)``.
    """
    abas = [aba_preferida] if aba_preferida in xls.sheet_names else []
    abas += [s for s in xls.sheet_names if s not in abas]
    for aba in abas:
        for h in range(max_linhas):
            try:  # probe leve (só o cabeçalho) — evita reler planilhas grandes 6×.
                probe = pd.read_excel(xls, aba, header=h, nrows=1)
            except Exception:
                continue
            if probe is None or probe.shape[1] == 0:
                continue
            colmap = _mapear(probe, mapa)
            if all(colmap.get(k) for k in chaves):
                return pd.read_excel(xls, aba, header=h), aba, h
    return None, (abas[0] if abas else None), None


def preparar_df(arquivo, tipo):
    """Lê um upload cru (``tipo`` = "SCM" ou "SC7"), detectando aba + linha de
    cabeçalho. Retorna ``(df, {"aba", "header"})`` ou ``(None, {"erro"})``."""
    mapa = _SCM_COLS if tipo == "SCM" else _SC7_COLS
    chaves = _SCM_OBRIGATORIAS if tipo == "SCM" else _SC7_OBRIGATORIAS
    aba_pref = "SCM" if tipo == "SCM" else "SC7"
    try:
        xls = pd.ExcelFile(arquivo)
    except Exception as e:  # pragma: no cover - erro de arquivo
        return None, {"erro": f"Não foi possível abrir o arquivo: {e}"}
    df, aba, _h = detectar_header(xls, aba_pref, chaves, mapa)
    if df is None:
        alvo = ", ".join(mapa[k][0] for k in chaves)
        return None, {
            "erro": f"Não encontrei as colunas-chave ({alvo}) em nenhuma aba/linha do arquivo {tipo}."
        }
    return df, {"aba": aba, "header": _h}


def _agregar_sc7(df_sc7, cols, pns_set):
    """Agrega o SC7 por ``(PO, PN)`` (soma Entregue/Saldo, última Dt.Entrega),
    restrito ao escopo de PN do MRO. Retorna ``(grupos, pos_presentes)``."""
    grupos = {}
    pos = set()
    for _, row in df_sc7.iterrows():
        pn_raw = _txt(_valor(row, cols["produto"], ""))
        if not pn_raw:
            continue
        if pns_set is not None and _key(pn_raw) not in pns_set:
            continue
        po_raw = _txt(_valor(row, cols["pedido"], ""))
        chave = (_key(po_raw), _key(pn_raw))
        g = grupos.get(chave)
        if g is None:
            g = {
                "po": po_raw,
                "pn": pn_raw,
                "descricao": _txt(_valor(row, cols["descricao"], "")),
                "qtd_entregue": 0.0,
                "saldo": 0.0,
                "dt_entrega": None,
                "fornecedor": "",
                "comprador": "",
            }
            grupos[chave] = g
        g["qtd_entregue"] += _to_float(_valor(row, cols["qtd_entregue"], 0))
        g["saldo"] += _to_float(_valor(row, cols["saldo"], 0))
        d = _to_date_str(_valor(row, cols["dt_entrega"], None))
        if d and (g["dt_entrega"] is None or d > g["dt_entrega"]):
            g["dt_entrega"] = d
        if not g["fornecedor"]:
            g["fornecedor"] = _txt(_valor(row, cols["fornecedor"], ""))
        if not g["comprador"]:
            g["comprador"] = _txt(_valor(row, cols["comprador"], ""))
        if po_raw:
            pos.add(_key(po_raw))
    return grupos, pos


def cruzar_scm_sc7(df_scm, df_sc7, *, solicitantes_mro=None, pns_mro=None, dep_por_solic=None):
    """Cruza os dois exports crus e devolve a tabela do Monitor 2.0.

    - **SCM dirige** (demanda); o SC7 anexa entrega/saldo por ``(PO, PN)``.
    - **Filtro MRO** (igual aos importadores; ``None`` desliga): no SCM mantém só
      ``solicitante ∈ solicitantes_mro`` **e** ``PN ∈ pns_mro``; no SC7 mantém só
      ``PN ∈ pns_mro`` (restringe os órfãos).
    - **Departamento** derivado do solicitante via ``dep_por_solic`` ("—" se não
      mapeado).

    Retorna ``{"linhas", "orfaos", "departamentos", "stats", "colunas"}`` ou
    ``{"erro": "..."}`` se faltar planilha/coluna-chave.
    """
    dep_por_solic = dep_por_solic or {}
    scm_cols = _mapear(df_scm, _SCM_COLS) if df_scm is not None else {}
    sc7_cols = _mapear(df_sc7, _SC7_COLS) if df_sc7 is not None else {}

    falt = []
    if df_scm is None or df_scm.empty:
        falt.append("SCM (Solicitações) vazia/ausente")
    else:
        falt += [f"SCM: {n}" for n in _faltantes(scm_cols, _SCM_OBRIGATORIAS, _SCM_COLS)]
    if df_sc7 is None or df_sc7.empty:
        falt.append("SC7 (Relatório de Compras) vazia/ausente")
    else:
        falt += [f"SC7: {n}" for n in _faltantes(sc7_cols, _SC7_OBRIGATORIAS, _SC7_COLS)]
    if falt:
        return {"erro": "Colunas/planilhas ausentes → " + "; ".join(falt)}

    pns_set = None if pns_mro is None else {_key(p) for p in pns_mro}

    def _scope_solic(sol):
        return solicitantes_mro is None or _normalizar_txt(sol) in solicitantes_mro

    def _scope_pn(pn):
        return pns_set is None or _key(pn) in pns_set

    # 1) SC7 agregado por (PO, PN), restrito ao escopo de PN do MRO.
    sc7_grupos, _sc7_pos = _agregar_sc7(df_sc7, sc7_cols, pns_set)

    # POs referenciados por QUALQUER linha do SCM (p/ decidir órfão = compra sem SC).
    scm_pos = {_key(_valor(row, scm_cols["pedido"], "")) for _, row in df_scm.iterrows()}
    scm_pos.discard("")

    # 2) SCM dirige a tabela.
    linhas = []
    deptos = set()
    stats = {
        "n_scm": int(len(df_scm)),
        "n_sc7": int(len(df_sc7)),
        "casadas": 0,
        "sem_pedido": 0,
        "po_sem_sc7": 0,
        "orfaos": 0,
        "fora_escopo": 0,
        "saldo_pendente_total": 0.0,
    }

    for _, row in df_scm.iterrows():
        pn_raw = _txt(_valor(row, scm_cols["produto"], ""))
        if not pn_raw:
            continue
        solic = _txt(_valor(row, scm_cols["solicitante"], ""))
        # Filtro MRO (igual aos importadores): solicitante MRO E PN no inventário.
        if not _scope_solic(solic) or not _scope_pn(pn_raw):
            stats["fora_escopo"] += 1
            continue
        po_raw = _txt(_valor(row, scm_cols["pedido"], ""))
        dep = dep_por_solic.get(_normalizar_txt(solic), "—") or "—"
        deptos.add(dep)
        linha = {
            "SC": _txt(_valor(row, scm_cols["sc"], "")),
            "Solicitante": solic,
            "Departamento": dep,
            "Status": _txt(_valor(row, scm_cols["status"], "")),
            "Produto": pn_raw,
            "Descrição": _txt(_valor(row, scm_cols["descricao"], "")),
            "Qty (SC)": _to_float(_valor(row, scm_cols["quantidade"], 0)),
            "Data Necessidade": _to_date_str(_valor(row, scm_cols["data_necessidade"], None)),
            "Justificativa": _txt(_valor(row, scm_cols["justificativa"], "")),
            "PO": po_raw,
            "Fornecedor": "",
            "Comprador": "",
            "Qtd Entregue": None,
            "Saldo": None,
            "Dt. Entrega": None,
            "Situação": "",
        }
        if not po_raw:
            linha["Situação"] = "🟡 Sem pedido"
            stats["sem_pedido"] += 1
        else:
            g = sc7_grupos.get((_key(po_raw), _key(pn_raw)))
            if g is not None:
                linha.update(
                    {
                        "Fornecedor": g["fornecedor"],
                        "Comprador": g["comprador"],
                        "Qtd Entregue": g["qtd_entregue"],
                        "Saldo": g["saldo"],
                        "Dt. Entrega": g["dt_entrega"],
                        "Situação": "✅ Casada",
                    }
                )
                stats["casadas"] += 1
                stats["saldo_pendente_total"] += g["saldo"]
            else:
                linha["Situação"] = "⚠️ PO sem linha no SC7"
                stats["po_sem_sc7"] += 1
        linhas.append(linha)

    # 3) Órfãos: grupos SC7 (já restritos a PN do MRO) cujo PO não aparece no SCM.
    orfaos = []
    for (po_key, _pn_key), g in sc7_grupos.items():
        if po_key and po_key in scm_pos:
            continue
        orfaos.append(
            {
                "PO": g["po"],
                "Produto": g["pn"],
                "Descrição": g["descricao"],
                "Fornecedor": g["fornecedor"],
                "Comprador": g["comprador"],
                "Qtd Entregue": g["qtd_entregue"],
                "Saldo": g["saldo"],
                "Dt. Entrega": g["dt_entrega"],
            }
        )
    orfaos.sort(key=lambda o: o["Saldo"] or 0, reverse=True)
    stats["orfaos"] = len(orfaos)

    return {
        "linhas": linhas,
        "orfaos": orfaos,
        "departamentos": sorted(deptos),
        "stats": stats,
        "colunas": COLUNAS_SAIDA,
    }
