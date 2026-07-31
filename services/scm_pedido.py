"""services/scm_pedido.py — leitura do Pedido de Compra na API do SCM (v5.9.0).

Traduz o payload de `GET /Pedidos/ByNumero/{filial}/{numero}` (Protheus SC7, campos
`C7_*`) para os itens do Guarda-Chuva, cruzando o PN com o inventário MRO.

**Contrato verificado em produção** (payload real capturado antes de escrever o parser,
pedido F63955 / F62421): a resposta é uma LISTA achatada — uma linha por item, com os
dados do cabeçalho repetidos em cada linha. Campos observados:

    C7_NUM      nº do pedido          C7_FORNECE  código do fornecedor
    C7_ITEM     sequência do item     C7_LOJA     loja do fornecedor
    C7_PRODUTO  part number           A2_NOME     nome do fornecedor
    C7_DESCRI   descrição             C7_EMISSAO  emissão (yyyyMMdd)
    C7_QUANT    quantidade            C7_XPEDSCM  código da COTAÇÃO no SCM (CTxxxxx)
    C7_UM       unidade               USR_NOME    comprador
    C7_PRECO    preço unitário        C7_TOTAL    valor total da linha

⚠️ **Não existe campo de nº da SC no pedido.** O vínculo é o `C7_XPEDSCM` (código da
cotação), que casa com `solicitacoes_compra.cotacao_codigo` — é assim que
`resolver_numero_sc` acha a SC. O plano supunha um `C7_NUMSC`, que a API não devolve.

Todos os campos passam por um mapa de ALIASES: se o Protheus for reconfigurado ou a API
mudar o envelope, o parser degrada (campo vazio) em vez de quebrar. Só GET, como manda
`scm_client`; erro de rede nunca escapa — vira `(ok=False, mensagem)`.
"""

from __future__ import annotations

from services import scm_client
from services.db_functions import buscar_item_por_pn, transaction
from services.scm_client import _num, _trim

FILIAL_PADRAO = "01"

# Nome canônico → nomes aceitos no payload, em ordem de preferência. O 1º é o que a API
# realmente devolve hoje; os demais são degradação defensiva.
_ALIASES = {
    "numero_pedido": ("C7_NUM", "numero", "pedido"),
    "item_seq": ("C7_ITEM", "item"),
    "part_number": ("C7_PRODUTO", "produto", "partNumber"),
    "descricao": ("C7_DESCRI", "descricao", "descricaoProduto"),
    "quantidade": ("C7_QUANT", "quantidade", "qtd"),
    "unidade": ("C7_UM", "um", "unidade"),
    "preco_unitario": ("C7_PRECO", "preco", "valorUnitario"),
    "valor_total": ("C7_TOTAL", "total", "valorTotal"),
    "fornecedor_codigo": ("C7_FORNECE", "fornecedor", "codigoFornecedor"),
    "fornecedor_loja": ("C7_LOJA", "loja"),
    "fornecedor_nome": ("A2_NOME", "nomeFornecedor", "razaoSocial"),
    "emissao": ("C7_EMISSAO", "emissao", "dataEmissao"),
    "cotacao_codigo": ("C7_XPEDSCM", "cotacao", "codigoCotacao"),
    "comprador": ("USR_NOME", "comprador"),
}


def _campo(linha, canonico, *, numerico=False):
    """Lê um campo pelo mapa de aliases, já sem o padding de espaços do Protheus."""
    for chave in _ALIASES.get(canonico, ()):
        if chave in linha and linha[chave] is not None:
            return _num(linha[chave]) if numerico else _trim(linha[chave])
    return 0.0 if numerico else ""


def normalizar_itens_pedido_api(payload):
    """`payload` da API → `(cabecalho, itens)`. PURO — testável sem rede.

    `cabecalho`: numero_pedido, fornecedor_codigo/nome, cotacao_codigo, emissao, comprador.
    `itens`: um dict por linha do pedido (ainda SEM cruzar com o inventário).
    Aceita a lista achatada (formato real) e, por robustez, um dict com a lista dentro.
    """
    linhas = payload
    if isinstance(payload, dict):
        for chave in ("items", "itens", "result", "data"):
            if isinstance(payload.get(chave), list):
                linhas = payload[chave]
                break
        else:
            linhas = [payload]  # objeto único
    if not isinstance(linhas, list):
        return {}, []

    itens, cabecalho = [], {}
    for linha in linhas:
        if not isinstance(linha, dict):
            continue
        pn = _campo(linha, "part_number")
        if not cabecalho:
            cabecalho = {
                "numero_pedido": _campo(linha, "numero_pedido"),
                "fornecedor_codigo": _campo(linha, "fornecedor_codigo"),
                "fornecedor_loja": _campo(linha, "fornecedor_loja"),
                "fornecedor_nome": _campo(linha, "fornecedor_nome"),
                "cotacao_codigo": _campo(linha, "cotacao_codigo"),
                "emissao": _campo(linha, "emissao"),
                "comprador": _campo(linha, "comprador"),
            }
        if not pn:
            continue  # linha sem produto não vira item
        itens.append(
            {
                "item_seq": _campo(linha, "item_seq"),
                "part_number": pn,
                "descricao": _campo(linha, "descricao"),
                "quantidade": _campo(linha, "quantidade", numerico=True),
                "unidade": _campo(linha, "unidade"),
                "preco_unitario": _campo(linha, "preco_unitario", numerico=True),
                "valor_total": _campo(linha, "valor_total", numerico=True),
            }
        )
    return cabecalho, itens


def filtrar_itens_mro(itens):
    """Separa `(mro, descartados)` cruzando o PN com `inventario.part_number`.

    Itens fora do inventário MRO são REPORTADOS, não silenciados — a tela mostra o que
    foi descartado para o comprador saber que o pedido tinha mais linhas."""
    mro, descartados = [], []
    for it in itens or []:
        item = buscar_item_por_pn(it["part_number"])
        if item:
            mro.append({**it, "item_id": item["id"], "nome_item": item["nome_item"]})
        else:
            descartados.append(it)
    return mro, descartados


def resolver_numero_sc(cotacao_codigo):
    """Nº da SC a partir do código da cotação (`C7_XPEDSCM` → `cotacao_codigo`).

    O pedido não traz o número da SC; o que ele traz é o código da cotação do SCM, que
    já está gravado em `solicitacoes_compra.cotacao_codigo` pelo importador. Sem match
    devolve None — a tela deixa o campo em branco para preenchimento manual."""
    codigo = _trim(cotacao_codigo)
    if not codigo:
        return None
    try:
        with transaction() as conn:
            r = conn.execute(
                "SELECT numero_sc FROM solicitacoes_compra WHERE TRIM(cotacao_codigo)=? LIMIT 1",
                (codigo,),
            ).fetchone()
        return r["numero_sc"] if r else None
    except Exception:
        return None


def buscar_pedido(numero_pedido, filial=FILIAL_PADRAO):
    """Busca o pedido na API e devolve `(ok, dados_ou_msg)`.

    `dados`: `{cabecalho, itens_mro, descartados}`. Toda falha de rede/HTTP/parse vira
    `(False, mensagem)` — a tela cai no cadastro manual, nunca quebra."""
    numero = str(numero_pedido or "").strip()
    if not numero:
        return False, "Informe o número do pedido."
    try:
        payload = scm_client.pedido(filial, numero)
    except Exception as e:
        return False, f"Não foi possível consultar a API do SCM ({type(e).__name__}). Cadastre manualmente."
    if not payload:
        return False, f"Pedido {numero} não encontrado na API do SCM."

    cabecalho, itens = normalizar_itens_pedido_api(payload)
    if not itens:
        return False, f"A API respondeu, mas o pedido {numero} não trouxe itens legíveis."

    cabecalho.setdefault("numero_pedido", numero)
    cabecalho["numero_pedido"] = cabecalho.get("numero_pedido") or numero
    cabecalho["numero_sc"] = resolver_numero_sc(cabecalho.get("cotacao_codigo"))
    mro, descartados = filtrar_itens_mro(itens)
    return True, {"cabecalho": cabecalho, "itens_mro": mro, "descartados": descartados}
