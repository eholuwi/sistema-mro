"""v6.5.0 — Consumo mensal do item medido pelo PEDIDO DE COMPRA (Protheus SC7).

Substitui a "vida útil do lote" da v6.4.0 como terceira leitura do consumo, ao lado do
mensal por mês-calendário e do ponderado. A pergunta que ele responde é a do comprador,
não a do almoxarife: **quanto deste item foi de fato comprado e entregue por mês**.

Regra travada pelo Luis (10/08/2026):

- Conta **só pedido ATENDIDO** (`saldo = 0`): soma da `Qtd.Entregue` do período ÷ meses.
- O mês do pedido é a **DT Emissao** — não a data de entrega. É a data em que a compra
  foi decidida, e é a que existe em toda linha do SC7.
- **Ano anterior:** total ÷ 12. **Ano atual:** total de janeiro até o mês ANTERIOR ÷ meses
  decorridos (com `hoje = 10/08/2026` → jan–jul ÷ 7). O mês corrente nunca entra — mesmo
  princípio de `_ultimos_n_meses_completos` (`classificacao.py`): mês em andamento
  dividido por um mês inteiro produz um consumo artificialmente baixo todo dia 1º.
- **Referência** = ano atual quando tem pedido atendido; senão o ano anterior. Os dois
  voltam no dict, porque o card mostra os dois quando existirem.
- **Pendente (`saldo > 0`) nunca soma.** Vai para `pendentes` e vira nota no card: o
  material ainda não chegou, então não é consumo — mas o comprador precisa saber que
  existe, ou vai ler o número como "compramos pouco".
- **Linha sem `dt_emissao` ou sem entrega (`qtd_entregue <= 0`) é ignorada**, não zerada:
  pedido cancelado/zerado não é evidência de consumo zero, é ausência de evidência.

**Só PEDIDO DE COMPRA alimenta este número** — decisão do Luis em 11/08/2026, ao ver o card
pela primeira vez. Duas fontes, na ordem; a primeira que produzir número vence:

| origem | de onde | por quê |
|---|---|---|
| `sc7` | tabela `consumo_sc7` (planilha "Relatório de Compras") | tem Entregue **e** Saldo por linha de PO |
| `scm` | `itens_sc` + `solicitacoes_compra` (Relatório de SCs) | o MESMO pedido visto pela outra planilha, para o item que não veio no SC7 |

⚠️ **Não existe fallback por saídas do almoxarifado.** A versão de 10/08/2026 tinha um, e ele
foi removido no dia seguinte: com a tabela `consumo_sc7` ainda vazia, TODO item caía nele e o
card dizia "12 pedido(s)" para o que eram 12 requisições — medindo consumo em vez de compra,
que é justamente a diferença entre este card e o "Consumo/Mensal" ponderado ao lado dele. Sem
pedido atendido o card mostra "—", e o tooltip diz por quê (inclusive quantos pedidos estão a
caminho). Ausência de compra é uma informação; um número tirado de outra fonte, não.

`_consumo_from_linhas` é **PURA** (lista de dicts → dict), como as `_*_from_*` de
`classificacao.py`; as funções de leitura só buscam as linhas e delegam. A conversão de
unidade usa a fórmula do recebimento (`qtd / fator_conversao`, fator `<= 0`/`None` ⇒ 1):
`qtd_entregue` vem na UM de COMPRA e o estoque vive na UM de ESTOQUE.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

MESES_ABREV = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
# Por extenso para o tooltip da Ficha ("janeiro a julho"); abreviado para a `origem` do
# Mín/Máx, que divide espaço com o lead time e precisa de "2026 (jan–jul)".
MESES_EXTENSO = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)

# As duas fontes são pedido de compra; muda só a planilha que trouxe a linha. Dois rótulos
# porque os dois lugares têm espaços diferentes: a `origem` do Mín/Máx divide a célula com o
# lead time e precisa do curto; o tooltip da Ficha tem espaço e ganha em dizer qual planilha.
ROTULO_ORIGEM = {"sc7": "SC7", "scm": "SCM"}
ROTULO_FONTE = {"sc7": "SC7 (Relatório de Compras)", "scm": "SCM (Relatório de SCs)"}


# ══════════════════════════════════════════════════════════════════════════════
# NÚCLEO PURO — soma por ano sobre listas de linhas (sem banco)
# ══════════════════════════════════════════════════════════════════════════════


def _fator_valido(fator):
    """Fator de conversão utilizável: `<= 0`, `None` ou lixo ⇒ 1 (a UM é a mesma)."""
    try:
        f = float(fator)
    except (TypeError, ValueError):
        return 1.0
    return f if f > 0 else 1.0


def _num(valor):
    """Número tolerante — `None`/texto vazio/lixo viram 0.0 (a planilha traz os três)."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def _ano_mes(valor):
    """`'YYYY-MM-DD'` (ou com hora) → `(ano, mês)`; `None` quando não parseia."""
    if not valor:
        return None
    try:
        d = date.fromisoformat(str(valor).strip()[:10])
    except ValueError:
        return None
    return d.year, d.month


def _bloco(ano, meses):
    return {"ano": ano, "meses": meses, "total_entregue": 0.0, "n_pedidos": 0, "consumo_mensal": None}


def _consumo_from_linhas(linhas, hoje, fator=1.0):
    """Consumo mensal a partir de `linhas` = `[{dt_emissao, qtd_entregue, saldo}]`.

    PURA — é aqui que a regra do Luis vive inteira; ver o cabeçalho do módulo. `fator` é o
    `fator_conversao` do item (UM de compra → UM de estoque); as saídas reais já estão na
    UM de estoque e entram com `fator=1`.
    """
    f = _fator_valido(fator)
    ano_atual, ano_anterior = hoje.year, hoje.year - 1
    # jan..mês-1 do ano corrente. Em janeiro dá 0 meses decorridos: não há período
    # fechado no ano, e a referência cai sozinha para o ano anterior.
    meses_atual = hoje.month - 1
    blocos = {ano_anterior: _bloco(ano_anterior, 12), ano_atual: _bloco(ano_atual, meses_atual)}
    pendentes = {"n": 0, "qtd": 0.0}
    ignorados = 0
    fora_janela = 0

    for linha in linhas:
        ano_mes = _ano_mes(linha.get("dt_emissao"))
        if ano_mes is None:
            ignorados += 1
            continue
        saldo = _num(linha.get("saldo"))
        if saldo > 0:
            pendentes["n"] += 1
            pendentes["qtd"] += saldo / f
            continue
        entregue = _num(linha.get("qtd_entregue")) / f
        if entregue <= 0:
            ignorados += 1
            continue
        ano, mes = ano_mes
        if ano == ano_atual and mes <= meses_atual:
            bloco = blocos[ano_atual]
        elif ano == ano_anterior:
            bloco = blocos[ano_anterior]
        else:
            fora_janela += 1
            continue
        bloco["total_entregue"] += entregue
        bloco["n_pedidos"] += 1

    pendentes["qtd"] = round(pendentes["qtd"], 2)
    for bloco in blocos.values():
        bloco["total_entregue"] = round(bloco["total_entregue"], 2)
        if bloco["n_pedidos"] and bloco["meses"] > 0:
            bloco["consumo_mensal"] = round(bloco["total_entregue"] / bloco["meses"], 2)

    ref = blocos[ano_atual] if blocos[ano_atual]["consumo_mensal"] is not None else blocos[ano_anterior]
    tem = ref["consumo_mensal"] is not None
    return {
        "consumo_mensal": ref["consumo_mensal"],
        "ano_ref": ref["ano"] if tem else None,
        "meses": ref["meses"] if tem else None,
        "total_entregue": ref["total_entregue"] if tem else 0.0,
        "n_pedidos": ref["n_pedidos"] if tem else 0,
        "origem": None,  # preenchida por quem leu o banco (sc7 | scm | saidas)
        "ano_anterior": blocos[ano_anterior],
        "ano_atual": blocos[ano_atual],
        "pendentes": pendentes,
        "ignorados": ignorados,
        "fora_janela": fora_janela,
    }


def rotulo_periodo(ano, meses):
    """`2025` → `'2025'` · `2026` com 7 meses → `'2026 (jan–jul)'`."""
    if not ano:
        return "—"
    if not meses or meses >= 12:
        return str(ano)
    if meses == 1:
        return f"{ano} (jan)"
    return f"{ano} (jan–{MESES_ABREV[meses - 1]})"


def rotulo_consumo(info):
    """`'SC7 2026 (jan–jul)'` — a fonte e o período que produziram o número.

    É o rótulo que a `origem` do Mín/Máx sugerido mostra ao gestor: sem ele a tela diria
    só "consumo", e duas fontes muito diferentes (pedido atendido × saída de almoxarifado)
    ficariam indistinguíveis na hora de decidir se aceita a sugestão."""
    if not info or info.get("consumo_mensal") is None:
        return None
    origem = info.get("origem")
    return f"{ROTULO_ORIGEM.get(origem, origem or 'SC7')} {rotulo_periodo(info.get('ano_ref'), info.get('meses'))}"


# ══════════════════════════════════════════════════════════════════════════════
# LEITURA DO BANCO — uma consulta por fonte para a base INTEIRA (sem N+1)
# ══════════════════════════════════════════════════════════════════════════════


def _fatores(c, item_id=None):
    """{item_id: fator_conversao válido} — a conversão UM de compra → UM de estoque."""
    where, params = (" WHERE id=?", (item_id,)) if item_id else ("", ())
    rows = c.execute(f"SELECT id, fator_conversao FROM inventario{where}", params).fetchall()
    return {r["id"]: _fator_valido(r["fator_conversao"]) for r in rows}


def _agrupar(rows):
    por_item = defaultdict(list)
    for r in rows:
        por_item[r["item_id"]].append(
            {"dt_emissao": r["dt_emissao"], "qtd_entregue": r["qtd_entregue"], "saldo": r["saldo"]}
        )
    return por_item


def _linhas_sc7(c, item_id=None):
    """Linhas de `consumo_sc7` casadas ao inventário pelo PN (join por TEXTO, sem FK: o
    SC7 traz PNs que não existem no MRO e eles ficam gravados, só não pertencem a item)."""
    where, params = ("AND i.id=?", (item_id,)) if item_id else ("", ())
    rows = c.execute(
        f"""SELECT i.id AS item_id, cs.dt_emissao, cs.qtd_entregue, cs.saldo
            FROM consumo_sc7 cs
            JOIN inventario i ON UPPER(TRIM(i.part_number)) = UPPER(TRIM(cs.produto))
            WHERE 1=1 {where}""",
        params,
    ).fetchall()
    return _agrupar(rows)


def _linhas_scm(c, item_id=None):
    """Fallback 1 — o pedido visto pelo Relatório de SCs (`itens_sc`).

    O saldo sai das MESMAS colunas do Protheus (`quantidade_pedido` − `Qtd.Entregue`) e
    **não** de `saldo_residual`: aquele mede o recebimento conferido na doca pelo MRO
    (`_saldo_status_item_sc`) e responde outra pergunta — um PO totalmente entregue pelo
    fornecedor pode ter saldo residual porque o almoxarifado ainda não deu entrada."""
    where, params = ("AND isc.item_id=?", (item_id,)) if item_id else ("", ())
    rows = c.execute(
        f"""SELECT isc.item_id AS item_id,
                   COALESCE(sc.data_po, sc.data_abertura) AS dt_emissao,
                   COALESCE(isc.quantidade_recebida_protheus, 0) AS qtd_entregue,
                   MAX(COALESCE(isc.quantidade_pedido, 0)
                       - COALESCE(isc.quantidade_recebida_protheus, 0), 0) AS saldo
            FROM itens_sc isc
            JOIN solicitacoes_compra sc ON sc.id = isc.sc_id
            WHERE COALESCE(TRIM(isc.numero_po), '') <> '' {where}""",
        params,
    ).fetchall()
    return _agrupar(rows)


def consumo_sc7_por_item(c, item_id=None, hoje=None):
    """{item_id: dict de `_consumo_from_linhas` + `origem`} — `item_id=None` → base inteira.

    Duas consultas no total (uma por fonte), no molde de `_amostras_consumo_30d`: a
    alternativa seria uma consulta por item dentro do laço da base, exatamente o N+1 que
    `classificar_todos` existe para evitar. Nada é persistido — o número é derivado na
    leitura, então não envelhece como `consumo_medio_diario`.

    Com `item_id` a chave SEMPRE volta (dict vazio com `consumo_mensal=None` quando não há
    pedido em fonte alguma), para a Ficha ter o que mostrar como "—". Sem `item_id` só
    aparecem os itens com dado — quem não está no mapa não tem consumo por pedido.

    Quando a fonte de maior prioridade não produz número mas viu pedidos PENDENTES, eles
    viajam para o resultado final: é a informação que explica o "—" da tela.
    """
    hoje = hoje or date.today()
    fatores = _fatores(c, item_id)
    resultado = {}

    def _aplicar(linhas_por_item, origem):
        for iid, linhas in linhas_por_item.items():
            anterior = resultado.get(iid)
            if anterior is not None and anterior["consumo_mensal"] is not None:
                continue  # fonte de maior prioridade já respondeu
            info = _consumo_from_linhas(linhas, hoje, fatores.get(iid, 1.0))
            if info["consumo_mensal"] is not None:
                info["origem"] = origem
            elif anterior is not None:
                continue  # não troca um "sem número" por outro (perderia os pendentes)
            if anterior and anterior["pendentes"]["n"]:
                info["pendentes"] = anterior["pendentes"]
            resultado[iid] = info

    _aplicar(_linhas_sc7(c, item_id), "sc7")
    _aplicar(_linhas_scm(c, item_id), "scm")

    if item_id is not None and item_id not in resultado:
        resultado[item_id] = _consumo_from_linhas([], hoje)
    return resultado
