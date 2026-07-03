"""Ficha 360 do Material (v2.6.0).

Consolida, EM UMA TELA e SOMENTE LEITURA, toda a "vida útil" de um item — cadastro,
estoque, consumo, compras, utilização, indicadores e a recomendação de reposição.
A ficha é majoritariamente MONTAGEM de funções já existentes (v2.2→v2.5): este
módulo apenas (a) agrega o consumo por departamento/centro de custo, (b) cuida da
imagem do produto (arquivo em docs/itens/, fora do SQLite) e (c) reúne tudo num
único dict via `montar_ficha_360`. A única escrita da ficha é o upload/remoção da
imagem; nada aqui altera a base do Sr. Neidson.
"""
from __future__ import annotations

import os
from datetime import datetime

import database
from database import transaction
from services.db_functions import (
    listar_inventario,
    listar_movimentacoes,
    buscar_scs_por_item,
    obter_evolucao_preco,
    obter_fornecedores_por_item,
    calcular_giro,
    calcular_valor_consumido,
    obter_abc_valor,
    listar_historico_part_number,
    obter_maturidade_dados,
)
from services import planejamento as P


# ══════════════════════════════════════════════════════════════════════════════
# IMAGEM DO PRODUTO (arquivo em docs/itens/, referenciado por inventario.imagem_path)
# ══════════════════════════════════════════════════════════════════════════════

IMAGEM_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
IMAGEM_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def _base_dir():
    """Diretório do banco (raiz das pastas de dados). Lido em tempo de execução
    para respeitar o monkeypatch de `database.DB_PATH` nos testes (isolamento)."""
    return os.path.dirname(os.path.abspath(database.DB_PATH))


def _itens_dir():
    return os.path.join(_base_dir(), "docs", "itens")


def caminho_absoluto_imagem(rel):
    """Resolve o `imagem_path` (relativo, ex.: 'docs/itens/item_5.png') para caminho
    absoluto a partir do diretório do banco. Retorna None se vazio."""
    if not rel:
        return None
    return os.path.join(_base_dir(), rel.replace("/", os.sep))


def _remover_arquivos_item(item_id):
    """Remove qualquer arquivo item_<id>.<ext> (evita órfãos ao trocar de formato).
    O ponto após o id evita casar item_1 com item_10."""
    d = _itens_dir()
    if not os.path.isdir(d):
        return
    prefixo = f"item_{item_id}."
    for nome in os.listdir(d):
        if nome.startswith(prefixo):
            try:
                os.remove(os.path.join(d, nome))
            except OSError:
                pass


def salvar_imagem_item(item_id, nome_arquivo, conteudo, conn=None):
    """Salva a imagem do produto e grava `imagem_path`. Valida formato e tamanho.

    `conteudo` = bytes (na UI: `uploaded_file.getvalue()`). Retorna (ok, msg/rel).
    Não usa Pillow: apenas persiste os bytes; o Streamlit renderiza."""
    ext = (os.path.splitext(nome_arquivo or "")[1] or "").lower().lstrip(".")
    if ext == "jpe":
        ext = "jpg"
    if ext not in IMAGEM_EXTS:
        return False, (f"Formato não suportado ({ext or 'desconhecido'}). "
                       f"Use: {', '.join(sorted(IMAGEM_EXTS))}.")
    if not conteudo:
        return False, "Arquivo vazio."
    if len(conteudo) > IMAGEM_MAX_BYTES:
        return False, f"Imagem acima do limite de {IMAGEM_MAX_BYTES // (1024 * 1024)} MB."

    os.makedirs(_itens_dir(), exist_ok=True)
    _remover_arquivos_item(item_id)  # troca de formato não deixa órfão
    nome = f"item_{item_id}.{ext}"
    with open(os.path.join(_itens_dir(), nome), "wb") as f:
        f.write(conteudo)

    rel = f"docs/itens/{nome}"
    with transaction(conn) as c:
        c.execute(
            "UPDATE inventario SET imagem_path=?, data_atualizacao=? WHERE id=?",
            (rel, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), item_id),
        )
    return True, rel


def remover_imagem_item(item_id, conn=None):
    """Remove o arquivo de imagem e limpa `imagem_path`."""
    _remover_arquivos_item(item_id)
    with transaction(conn) as c:
        c.execute(
            "UPDATE inventario SET imagem_path=NULL, data_atualizacao=? WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), item_id),
        )
    return True, "Imagem removida."


# ══════════════════════════════════════════════════════════════════════════════
# DEPARTAMENTOS / CENTROS DE CUSTO CONSUMIDORES (agregação nova)
# ══════════════════════════════════════════════════════════════════════════════

def obter_consumo_por_departamento(item_id, dias=180, conn=None):
    """Quem consome o item: agrega as SAÍDAS por centro de custo e por setor na
    janela (qtd + % do total), ordenado do maior para o menor. Vazios viram
    '(não informado)' para transparência."""
    def _agg(campo, c):
        rows = c.execute(
            f"""SELECT COALESCE(NULLIF(TRIM({campo}), ''), '(não informado)') AS chave,
                       COALESCE(SUM(quantidade), 0) AS qtd
                FROM movimentacoes
                WHERE item_id=? AND tipo='saida'
                      AND data_hora >= datetime('now', ?)
                GROUP BY chave HAVING qtd > 0
                ORDER BY qtd DESC""",
            (item_id, f"-{dias} days"),
        ).fetchall()
        return [dict(r) for r in rows]

    with transaction(conn) as c:
        por_cc = _agg("centro_custo", c)
        por_setor = _agg("setor", c)

    total = sum(r["qtd"] for r in por_cc)
    total_setor = sum(r["qtd"] for r in por_setor)
    for r in por_cc:
        r["pct"] = round(r["qtd"] / total * 100, 1) if total else 0.0
    for r in por_setor:
        r["pct"] = round(r["qtd"] / total_setor * 100, 1) if total_setor else 0.0
    return {
        "por_centro_custo": por_cc,
        "por_setor": por_setor,
        "total": round(total, 2),
        "janela_dias": dias,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ASSEMBLER — reúne todas as seções (read-only) num único dict
# ══════════════════════════════════════════════════════════════════════════════

def montar_ficha_360(item_id, conn=None):
    """Reúne toda a Ficha 360 de um item reusando as funções já existentes.
    Retorna None se o item não existe. Casos edge (sem histórico/preço/imagem/
    consumo) devolvem estruturas vazias — a UI mostra placeholders."""
    item = next((i for i in listar_inventario() if i["id"] == item_id), None)
    if not item:
        return None

    # Recomendação de reposição (reusa o motor da v2.5 — sem novo cálculo de base).
    calc = P.calcular_ponto_reposicao(item)
    qtd = P.calcular_qtd_sugerida(item)
    precisa = P.precisa_repor(item)
    prioridade = P.classificar_prioridade(item)

    fornecedores = obter_fornecedores_por_item(item_id)
    melhor = next((f for f in fornecedores if f.get("melhor")),
                  fornecedores[0] if fornecedores else None)
    justificativa = P.montar_justificativa(item, calc, qtd, melhor)

    giro = calcular_giro(item_id)
    vc = calcular_valor_consumido(item_id)
    valor_estoque = round(float(item.get("estoque_atual") or 0) * (vc["preco"] or 0), 2)
    abc = next((x for x in obter_abc_valor() if x["item_id"] == item_id), None)

    imagem_rel = item.get("imagem_path")
    imagem_abs = caminho_absoluto_imagem(imagem_rel)
    if imagem_abs and not os.path.exists(imagem_abs):
        imagem_abs = None  # arquivo sumiu; UI mostra placeholder

    return {
        "item": item,
        "imagem_path": imagem_rel,
        "imagem_abs": imagem_abs,
        "reposicao": {
            "precisa": precisa,
            "prioridade": prioridade["rotulo"],
            "prioridade_tier": prioridade["tier"],
            "rop": calc["rop"],
            "lead_time": calc["lead_time"],
            "lead_time_origem": calc["lead_time_origem"],
            "lead_time_maturidade": calc["lead_time_maturidade"],
            "estoque_seguranca": calc["estoque_seguranca"],
            "estoque_seguranca_origem": calc["estoque_seguranca_origem"],
            "consumo_diario": calc["consumo_diario"],
            "alvo": qtd["alvo"],
            "alvo_origem": qtd["alvo_origem"],
            "qtd_sugerida": qtd["qtd"],
            "justificativa": justificativa,
        },
        "giro": giro,
        "valor": {"valor_estoque": valor_estoque, "valor_consumido": vc},
        "abc": abc,
        "fornecedores": fornecedores,
        "melhor_fornecedor": melhor,
        "departamentos": obter_consumo_por_departamento(item_id),
        "movimentacoes": listar_movimentacoes(item_id, limit=100),
        "scs_pos": buscar_scs_por_item(item_id, apenas_abertas=False),
        "evolucao_preco": obter_evolucao_preco(item_id),
        "historico_pn": listar_historico_part_number(item_id),
        "maturidade": obter_maturidade_dados(),
    }
