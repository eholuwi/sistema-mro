"""services/guarda_chuva.py — Guarda-Chuva POR PEDIDO DE COMPRA (v5.9.0).

Acordo com o fornecedor para **congelar o preço** de um conjunto de materiais e receber
em parcelas mês a mês. A unidade de trabalho é o **pedido** (`guarda_chuva_pedido`), com
N itens (`guarda_chuva_item`) e o recebido de cada item por mês
(`guarda_chuva_recebimento`, 1..12 colunas dinâmicas).

**Invariante inegociável — este módulo é CONTROLE, não ledger.** Registrar recebimento
aqui abate o saldo do ACORDO e **não toca `inventario.estoque_atual` nem
`movimentacoes`**. A entrada física de material continua sendo registrada só pelo
recebimento de SC/PO na Movimentação. Há teste travando isso.

⚠️ "Guarda-chuva" tem TRÊS sentidos no código, não confundir:
1. este (acordo por pedido, v5.9.0) e o antigo por (material × fornecedor) na tabela
   `guarda_chuva` (v4.9.0, preservada mas fora da tela);
2. o pedido sobre `itens_sc` (v4.5.7 — `obter_pedido_sc`/`atualizar_pedido_guarda_chuva`);
3. `estoque_em_transito` em `planejamento.py`.

Arquivo próprio (e não `db_functions.py`) porque o domínio é autocontido e o
`db_functions` já passa de 5.000 linhas — mesmo precedente de `planejamento.py`,
`ficha.py` e `classificacao.py`. Não importa `ui/` (regra de dependência do projeto).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from services.db_functions import GUARDA_CHUVA_ESTAGIOS, _to_float, transaction

MESES_ACORDO_MIN = 1
MESES_ACORDO_MAX = 12

# Campos do CABEÇALHO editáveis pela tela.
_CAMPOS_PEDIDO = (
    "numero_sc",
    "fornecedor_codigo",
    "fornecedor_nome",
    "meses_acordo",
    "estagio",
    "origem",
    "observacao",
)


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalizar_meses(valor, padrao=2):
    """Meses do acordo dentro de 1..12 (as colunas de recebimento da tabela editável)."""
    try:
        n = int(float(valor))
    except (TypeError, ValueError):
        return padrao
    return max(MESES_ACORDO_MIN, min(MESES_ACORDO_MAX, n))


# ── Pedido (cabeçalho) ───────────────────────────────────────────────────────


def criar_pedido_gc(
    numero_pedido,
    *,
    numero_sc=None,
    fornecedor_codigo=None,
    fornecedor_nome=None,
    meses_acordo=2,
    estagio="Pedido Colocado",
    origem="manual",
    observacao=None,
    itens=None,
):
    """Cria o pedido e, opcionalmente, seus itens (`itens`: lista de dicts com `item_id`).

    Tudo numa transação só: um pedido pela API nasce com os itens juntos ou não nasce.
    Retorna `(True, pedido_id)` ou `(False, msg)`.
    """
    numero = str(numero_pedido or "").strip()
    if not numero:
        return False, "Informe o número do pedido."
    if estagio not in GUARDA_CHUVA_ESTAGIOS:
        estagio = GUARDA_CHUVA_ESTAGIOS[0]
    agora = _agora()
    try:
        with transaction() as conn:
            ja = conn.execute(
                "SELECT id FROM guarda_chuva_pedido WHERE numero_pedido=?", (numero,)
            ).fetchone()
            if ja:
                return False, f"O pedido {numero} já está no Guarda-Chuva."
            cur = conn.execute(
                """INSERT INTO guarda_chuva_pedido
                   (numero_pedido, numero_sc, fornecedor_codigo, fornecedor_nome, meses_acordo,
                    estagio, origem, observacao, criado_em, atualizado_em)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    numero,
                    (str(numero_sc).strip() or None) if numero_sc else None,
                    (str(fornecedor_codigo).strip() or None) if fornecedor_codigo else None,
                    (str(fornecedor_nome).strip() or None) if fornecedor_nome else None,
                    normalizar_meses(meses_acordo),
                    estagio,
                    origem or "manual",
                    (observacao or None),
                    agora,
                    agora,
                ),
            )
            pedido_id = cur.lastrowid
            for it in itens or []:
                _inserir_item(conn, pedido_id, it, agora)
            return True, pedido_id
    except Exception as e:
        return False, str(e)


def _inserir_item(conn, pedido_id, it, agora):
    """INSERT de um item do pedido. `UNIQUE(pedido_id,item_id)` → ignora repetido."""
    item_id = it.get("item_id")
    if not item_id:
        return
    conn.execute(
        """INSERT OR IGNORE INTO guarda_chuva_item
           (pedido_id, item_id, qtd_negociada, qtd_prevista_mes, preco_congelado,
            observacao, criado_em, atualizado_em)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            int(pedido_id),
            int(item_id),
            _to_float(it.get("qtd_negociada") or 0),
            (_to_float(it["qtd_prevista_mes"]) if it.get("qtd_prevista_mes") not in (None, "") else None),
            (_to_float(it["preco_congelado"]) if it.get("preco_congelado") not in (None, "") else None),
            (it.get("observacao") or None),
            agora,
            agora,
        ),
    )


def listar_pedidos_gc():
    """Pedidos do Guarda-Chuva com totais derivados (itens, negociado, recebido, saldo).

    `saldo` é derivado na leitura — nunca materializado — como já era na v4.9.0."""
    with transaction() as conn:
        rows = conn.execute("""
            SELECT p.*,
                   COUNT(DISTINCT gi.id) AS n_itens,
                   COALESCE(SUM(gi.qtd_negociada), 0) AS qtd_negociada,
                   COALESCE((
                       SELECT SUM(r.quantidade) FROM guarda_chuva_recebimento r
                       JOIN guarda_chuva_item i2 ON i2.id = r.gc_item_id
                       WHERE i2.pedido_id = p.id
                   ), 0) AS qtd_recebida
            FROM guarda_chuva_pedido p
            LEFT JOIN guarda_chuva_item gi ON gi.pedido_id = p.id
            GROUP BY p.id
            ORDER BY p.atualizado_em DESC, p.id DESC
        """).fetchall()
    pedidos = []
    for r in rows:
        d = dict(r)
        d["saldo_residual"] = round(float(d["qtd_negociada"] or 0) - float(d["qtd_recebida"] or 0), 4)
        pedidos.append(d)
    return pedidos


def obter_pedido_gc(pedido_id):
    """Pedido + itens + recebimentos por mês, fresco do banco (o dialog relê a cada render).

    Cada item traz `recebimentos` como `{mes_seq: quantidade}`, `qtd_recebida` e `saldo`.
    """
    if not pedido_id:
        return None
    with transaction() as conn:
        p = conn.execute("SELECT * FROM guarda_chuva_pedido WHERE id=?", (int(pedido_id),)).fetchone()
        if not p:
            return None
        itens = [
            dict(r)
            for r in conn.execute(
                """SELECT gi.*, i.part_number, i.nome_item, i.unidade
                   FROM guarda_chuva_item gi JOIN inventario i ON i.id = gi.item_id
                   WHERE gi.pedido_id=? ORDER BY i.part_number""",
                (int(pedido_id),),
            ).fetchall()
        ]
        receb = {}
        for r in conn.execute(
            """SELECT r.gc_item_id, r.mes_seq, r.quantidade
               FROM guarda_chuva_recebimento r
               JOIN guarda_chuva_item i2 ON i2.id = r.gc_item_id
               WHERE i2.pedido_id=?""",
            (int(pedido_id),),
        ).fetchall():
            receb.setdefault(r["gc_item_id"], {})[int(r["mes_seq"])] = float(r["quantidade"] or 0)

    pedido = dict(p)
    for it in itens:
        it["recebimentos"] = receb.get(it["id"], {})
        it["qtd_recebida"] = round(sum(it["recebimentos"].values()), 4)
        it["saldo_residual"] = round(float(it["qtd_negociada"] or 0) - it["qtd_recebida"], 4)
    pedido["itens"] = itens
    pedido["meses_acordo"] = normalizar_meses(pedido.get("meses_acordo"))
    return pedido


def atualizar_pedido_gc(pedido_id, campos):
    """Edita o cabeçalho do pedido (chaves em `_CAMPOS_PEDIDO`). Retorna (ok, msg)."""
    if not pedido_id:
        return False, "Pedido inválido."
    sets, params = [], []
    for chave, valor in (campos or {}).items():
        if chave not in _CAMPOS_PEDIDO:
            continue
        if chave == "meses_acordo":
            valor = normalizar_meses(valor)
        elif chave == "estagio" and valor not in GUARDA_CHUVA_ESTAGIOS:
            valor = GUARDA_CHUVA_ESTAGIOS[0]
        elif isinstance(valor, str):
            valor = valor.strip() or None
        sets.append(f"{chave}=?")
        params.append(valor)
    if not sets:
        return False, "Nada a atualizar."
    sets.append("atualizado_em=?")
    params.extend([_agora(), int(pedido_id)])
    try:
        with transaction() as conn:
            conn.execute(f"UPDATE guarda_chuva_pedido SET {', '.join(sets)} WHERE id=?", params)
        return True, "Pedido atualizado."
    except Exception as e:
        return False, str(e)


def remover_pedido_gc(pedido_id):
    """Remove o pedido e, em cascata, seus itens e recebimentos."""
    if not pedido_id:
        return False, "Pedido inválido."
    try:
        with transaction() as conn:
            # ON DELETE CASCADE depende de PRAGMA foreign_keys; apagar na ordem torna a
            # limpeza independente disso (o mesmo banco é aberto por vários pontos).
            conn.execute(
                """DELETE FROM guarda_chuva_recebimento WHERE gc_item_id IN
                   (SELECT id FROM guarda_chuva_item WHERE pedido_id=?)""",
                (int(pedido_id),),
            )
            conn.execute("DELETE FROM guarda_chuva_item WHERE pedido_id=?", (int(pedido_id),))
            conn.execute("DELETE FROM guarda_chuva_pedido WHERE id=?", (int(pedido_id),))
        return True, "Pedido removido do Guarda-Chuva."
    except Exception as e:
        return False, str(e)


# ── Itens e recebimentos ─────────────────────────────────────────────────────


def adicionar_item_gc(pedido_id, item_id, **campos):
    """Acrescenta um material ao pedido (inclusão manual, quando a API não trouxe)."""
    if not pedido_id or not item_id:
        return False, "Selecione o pedido e o material."
    try:
        with transaction() as conn:
            ja = conn.execute(
                "SELECT id FROM guarda_chuva_item WHERE pedido_id=? AND item_id=?",
                (int(pedido_id), int(item_id)),
            ).fetchone()
            if ja:
                return False, "Este material já está no pedido."
            _inserir_item(conn, pedido_id, {"item_id": item_id, **campos}, _agora())
            conn.execute(
                "UPDATE guarda_chuva_pedido SET atualizado_em=? WHERE id=?",
                (_agora(), int(pedido_id)),
            )
        return True, "Material adicionado ao pedido."
    except Exception as e:
        return False, str(e)


def remover_item_gc(gc_item_id):
    """Remove um item do pedido (e seus recebimentos)."""
    if not gc_item_id:
        return False, "Item inválido."
    try:
        with transaction() as conn:
            conn.execute("DELETE FROM guarda_chuva_recebimento WHERE gc_item_id=?", (int(gc_item_id),))
            conn.execute("DELETE FROM guarda_chuva_item WHERE id=?", (int(gc_item_id),))
        return True, "Material removido do pedido."
    except Exception as e:
        return False, str(e)


def atualizar_itens_gc(pedido_id, linhas):
    """Grava a tabela editável INTEIRA (itens + recebimentos do mês) numa transação.

    `linhas`: lista de dicts com `id` (do `guarda_chuva_item`), `qtd_negociada`,
    `qtd_prevista_mes`, `preco_congelado`, `observacao` e `recebimentos`
    (`{mes_seq: quantidade}`). Linhas sem `id` são ignoradas — a inclusão de material
    tem caminho próprio (`adicionar_item_gc`), que valida o item.

    **Não toca estoque nem movimentações** — é controle do acordo.
    """
    if not pedido_id:
        return False, "Pedido inválido."
    agora = _agora()
    try:
        with transaction() as conn:
            validos = {
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM guarda_chuva_item WHERE pedido_id=?", (int(pedido_id),)
                ).fetchall()
            }
            for linha in linhas or []:
                gc_item_id = linha.get("id")
                if gc_item_id not in validos:
                    continue  # linha de outro pedido ou item recém-removido
                conn.execute(
                    """UPDATE guarda_chuva_item
                          SET qtd_negociada=?, qtd_prevista_mes=?, preco_congelado=?,
                              observacao=?, atualizado_em=?
                        WHERE id=?""",
                    (
                        _to_float(linha.get("qtd_negociada") or 0),
                        (
                            _to_float(linha["qtd_prevista_mes"])
                            if linha.get("qtd_prevista_mes") not in (None, "")
                            else None
                        ),
                        (
                            _to_float(linha["preco_congelado"])
                            if linha.get("preco_congelado") not in (None, "")
                            else None
                        ),
                        (linha.get("observacao") or None),
                        agora,
                        int(gc_item_id),
                    ),
                )
                for mes_seq, qtd in (linha.get("recebimentos") or {}).items():
                    conn.execute(
                        """INSERT INTO guarda_chuva_recebimento
                               (gc_item_id, mes_seq, quantidade, atualizado_em)
                           VALUES (?,?,?,?)
                           ON CONFLICT(gc_item_id, mes_seq)
                           DO UPDATE SET quantidade=excluded.quantidade,
                                         atualizado_em=excluded.atualizado_em""",
                        (int(gc_item_id), int(mes_seq), _to_float(qtd or 0), agora),
                    )
            conn.execute("UPDATE guarda_chuva_pedido SET atualizado_em=? WHERE id=?", (agora, int(pedido_id)))
        return True, "Pedido salvo."
    except Exception as e:
        return False, str(e)


# ── Exportação ───────────────────────────────────────────────────────────────


def exportar_guarda_chuva_df():
    """DataFrame ACHATADO do Guarda-Chuva: uma linha por item, colunas por mês.

    O nº de colunas de mês é o MAIOR `meses_acordo` entre os pedidos, para que a planilha
    saia retangular mesmo com pedidos de 2 e de 6 meses convivendo."""
    pedidos = [obter_pedido_gc(p["id"]) for p in listar_pedidos_gc()]
    pedidos = [p for p in pedidos if p]
    if not pedidos:
        return pd.DataFrame()

    max_meses = max(normalizar_meses(p.get("meses_acordo")) for p in pedidos)
    linhas = []
    for p in pedidos:
        for it in p["itens"]:
            linha = {
                "Nº Pedido": p["numero_pedido"],
                "SC": p.get("numero_sc") or "—",
                "Cód. Fornecedor": p.get("fornecedor_codigo") or "—",
                "Fornecedor": p.get("fornecedor_nome") or "—",
                "PN": it["part_number"],
                "Produto": it["nome_item"],
                "Unidade": it.get("unidade") or "",
                "Qtd Negociada": float(it.get("qtd_negociada") or 0),
                "Qtd Prevista/Mês": it.get("qtd_prevista_mes"),
                "Preço Congelado": it.get("preco_congelado"),
            }
            for mes in range(1, max_meses + 1):
                linha[f"{mes}º mês"] = it["recebimentos"].get(mes, 0.0)
            linha["Total Recebido"] = it["qtd_recebida"]
            linha["Saldo"] = it["saldo_residual"]
            linha["Estágio"] = p.get("estagio") or "—"
            linha["Observação"] = it.get("observacao") or p.get("observacao") or ""
            linhas.append(linha)
    return pd.DataFrame(linhas)
