"""v6.10.0 — Análise de Consumo em PDF (Assistente de Reposição).

O documento que o almoxarife anexa no e-mail para justificar a compra de um material.
Antes era feito **à mão**, item a item, fora do sistema; aqui ele nasce dos mesmos números
que a tela já mostra.

**Regra de ouro deste módulo: ele NÃO calcula consumo.** Todo número vem de função que já
existia e que outra tela já usa:

| número | de onde |
|---|---|
| consumo por PEDIDO DE COMPRA | `consumo_sc7.consumo_sc7_por_item` (o card da Ficha 360) |
| consumo por REQUISIÇÃO (fallback) | `classificacao.consumo_mensal` (`SAIDA_REAL_WHERE`) |
| ROP, lead time, consumo/dia | `planejamento.calcular_ponto_reposicao` |
| setor que consome | `db_functions.setor_dominante_por_item` |
| padrão de demanda (SBC) | `classificacao.classificar_demanda` |

O que este módulo acrescenta é **redação**: escolher a fonte, rotulá-la, explicar a conta em
português e montar o PDF. Se um número aqui divergir do que a Ficha 360 mostra, é bug —
não há segunda fórmula para culpar.

⚠️ **O FALLBACK POR SAÍDAS VALE SÓ DENTRO DO DOCUMENTO.** A v6.5.0 removeu de propósito o
fallback por saídas do card SC7 da Ficha 360: com a `consumo_sc7` vazia, TODO item caía nele
e o card media consumo de almoxarifado enquanto dizia "pedido de compra". Aqui ele volta —
mas com duas condições que lá não existiam: o documento **diz em letras claras** que o SC7
não achou pedido atendido, e **explica a conta feita** ("somamos as retiradas de jan–jul e
dividimos por 7"). Fonte rotulada é informação; fonte trocada em silêncio é mentira. Nada
neste arquivo altera `services/consumo_sc7.py` nem o card.

**A janela é a mesma do SC7** (`consumo_sc7._consumo_from_linhas`): ano anterior ÷ 12; ano
corrente de janeiro até o mês ANTERIOR ÷ meses decorridos. O mês em andamento nunca entra —
dividir um mês pela metade por um mês inteiro produz um consumo artificialmente baixo todo
dia 1º. Usar janelas diferentes por fonte tornaria os dois números incomparáveis dentro do
mesmo documento.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime

from database import transaction
from services import consumo_sc7 as C7
from services.classificacao import classificar_demanda, consumo_mensal
from services.db_functions import buscar_item_por_id, setor_dominante_por_item
from services.planejamento import calcular_ponto_reposicao
from services.tema import ACCENT

# Dias sem reimportar o SC7 até a tela avisar. Um mês é o ritmo real da planilha
# "Relatório de Compras" — abaixo disso o alerta viraria ruído permanente.
SC7_DIAS_PARA_ALERTA = 30

# Padrões de demanda (SBC) que justificam o risco de "consumo não linear". `Suave` não
# entra: consumo regular não é argumento para risco de queda acelerada de estoque.
PADROES_NAO_LINEARES = ("Intermitente", "Irregular")

MODO_SC7 = "sc7"
MODO_REQUISICAO = "requisicao"
MODO_SEM_HISTORICO = "sem_historico"

# Caracteres proibidos em nome de arquivo no Windows. O `/` da descrição ("P/LIMPEZA")
# é o caso real e frequente — vira `-`, como no lote gerado à mão.
_INVALIDOS_NO_NOME = r'[<>:"/\\|?*\x00-\x1f]'


def _num(valor):
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _fmt(valor, casas=1):
    """Número em pt-BR, sem casa decimal inútil: 86.0 → '86', 86.35 → '86,4'."""
    n = round(_num(valor), casas)
    texto = f"{n:,.{casas}f}".replace(",", "·").replace(".", ",").replace("·", ".")
    return texto.rstrip("0").rstrip(",") if "," in texto else texto


def _data_br(iso):
    """'2026-07-03' (ou com hora) → '03/07/2026'; entrada ruim volta como veio."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).strip()[:19]).strftime("%d/%m/%Y")
    except ValueError:
        try:
            return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return str(iso)


# ══════════════════════════════════════════════════════════════════════════════
# FRESCOR DO SC7 — a planilha que sustenta o número principal
# ══════════════════════════════════════════════════════════════════════════════


def sc7_frescor(conn=None, hoje=None):
    """`MAX(data_importacao)` de `consumo_sc7` → há quantos dias a planilha foi importada.

    O documento afirma "consumo por pedido de compra atendido". Se a planilha é de três
    meses atrás, a afirmação continua verdadeira e o número continua velho — e quem lê o
    PDF não tem como saber. Daí o aviso na tela ANTES de gerar.

    `sem_import=True` (tabela vazia) é diferente de `desatualizado`: um é "nunca houve",
    o outro é "houve e envelheceu". A tela diz coisas diferentes para cada um.
    """
    hoje = hoje or date.today()
    with transaction(conn) as c:
        row = c.execute("SELECT MAX(data_importacao) AS ultima FROM consumo_sc7").fetchone()
    ultima = row["ultima"] if row else None
    if not ultima:
        return {"data": None, "dias": None, "desatualizado": False, "sem_import": True}

    try:
        dia = datetime.fromisoformat(str(ultima).strip()[:19]).date()
    except ValueError:
        return {"data": str(ultima), "dias": None, "desatualizado": False, "sem_import": False}

    dias = (hoje - dia).days
    return {
        "data": dia.isoformat(),
        "dias": dias,
        "desatualizado": dias > SC7_DIAS_PARA_ALERTA,
        "sem_import": False,
    }


# ══════════════════════════════════════════════════════════════════════════════
# FALLBACK — consumo por REQUISIÇÃO, na mesma janela do SC7
# ══════════════════════════════════════════════════════════════════════════════


def consumo_por_requisicao(item_id, conn=None, hoje=None):
    """Consumo mensal pelas saídas por requisição, recortado na janela do SC7.

    NÃO é cálculo novo: a série mensal vem inteira de `classificacao.consumo_mensal`
    (que já filtra por `SAIDA_REAL_WHERE` — ajuste de inventário e entrada avulsa ficam de
    fora). Aqui só se somam os meses da janela e se divide pelo nº de meses, para o número
    ser comparável ao do SC7 dentro do mesmo documento.
    """
    hoje = hoje or date.today()
    serie = consumo_mensal(item_id, conn)
    ano_atual, ano_anterior = hoje.year, hoje.year - 1
    meses_atual = hoje.month - 1  # jan..mês-1; em janeiro dá 0 e a referência cai p/ o ano anterior

    blocos = {
        ano_anterior: {"ano": ano_anterior, "meses": 12, "total": 0.0, "meses_com_saida": 0},
        ano_atual: {"ano": ano_atual, "meses": meses_atual, "total": 0.0, "meses_com_saida": 0},
    }
    for linha in serie:
        try:
            ano, mes = (int(p) for p in str(linha["mes"]).split("-")[:2])
        except (ValueError, KeyError):
            continue
        qtd = _num(linha.get("qtd"))
        if qtd <= 0:
            continue
        if ano == ano_atual and mes <= meses_atual:
            bloco = blocos[ano_atual]
        elif ano == ano_anterior:
            bloco = blocos[ano_anterior]
        else:
            continue
        bloco["total"] += qtd
        bloco["meses_com_saida"] += 1

    for bloco in blocos.values():
        bloco["total"] = round(bloco["total"], 2)
        bloco["consumo_mensal"] = (
            round(bloco["total"] / bloco["meses"], 2) if bloco["meses"] > 0 and bloco["total"] > 0 else None
        )

    ref = blocos[ano_atual] if blocos[ano_atual]["consumo_mensal"] is not None else blocos[ano_anterior]
    tem = ref["consumo_mensal"] is not None
    return {
        "consumo_mensal": ref["consumo_mensal"],
        "ano_ref": ref["ano"] if tem else None,
        "meses": ref["meses"] if tem else None,
        "total": ref["total"] if tem else 0.0,
        "meses_com_saida": ref["meses_com_saida"] if tem else 0,
        "ano_anterior": blocos[ano_anterior],
        "ano_atual": blocos[ano_atual],
    }


def _explicacao_fallback(info, unidade):
    """A frase que o documento estampa quando o número veio das retiradas.

    Escrita para o gestor que vai LER o PDF, não para quem conhece o sistema: diz o que
    faltou, de onde o número veio no lugar e QUAL foi a conta — com os valores da conta,
    não a fórmula genérica."""
    meses = info.get("meses") or 0
    ano = info.get("ano_ref")
    if not meses or ano is None:
        return (
            "Não foi encontrado pedido de compra atendido para este material no Relatório de "
            "Compras (SC7), e também não há retiradas registradas no período — por isso não "
            "há consumo mensal para informar."
        )
    if meses >= 12:
        periodo = f"de janeiro a dezembro de {ano}"
    else:
        fim = C7.MESES_EXTENSO[meses - 1]
        periodo = f"de janeiro a {fim} de {ano}"
    return (
        "Não foi encontrado pedido de compra atendido para este material no Relatório de "
        "Compras (SC7). Por isso o consumo abaixo foi calculado pelas RETIRADAS do "
        f"almoxarifado (requisições): somamos as retiradas {periodo} — "
        f"{_fmt(info.get('total'))} {unidade} no total — e dividimos por {meses} "
        f"{'mês' if meses == 1 else 'meses'}, chegando a "
        f"{_fmt(info.get('consumo_mensal'))} {unidade} por mês."
    )


# ══════════════════════════════════════════════════════════════════════════════
# DADOS DA ANÁLISE — um dict por item, pronto para virar PDF
# ══════════════════════════════════════════════════════════════════════════════


def _riscos(item, dados):
    """Bullets "Risco de …" — só os aplicáveis ao item.

    Conforme `PROMPT_DOCUMENTO_ALMOXARIFE.md`, ficam **de fora** o "risco de ruptura em
    X–Y dias" e o "risco de impacto no atendimento da produção": o primeiro projeta uma
    data que o consumo intermitente do MRO não sustenta, e o segundo é genérico a ponto de
    caber em qualquer item — dizer isso de todo material é não dizer nada.
    """
    riscos = []
    estoque = _num(item.get("estoque_atual"))
    minimo = _num(item.get("estoque_minimo"))
    unidade = dados["unidade"]

    if dados["modo"] == MODO_SEM_HISTORICO:
        riscos.append(
            "Risco de dimensionamento: o material não tem histórico de consumo (item novo "
            "ou parado), então não há base para calcular a necessidade — a reposição deve "
            f"seguir o mínimo cadastrado de {_fmt(minimo)} {unidade}."
        )

    if estoque <= 0:
        riscos.append(
            "Risco de RUPTURA IMINENTE: o estoque está zerado — qualquer solicitação deste "
            "material depende do recebimento da compra."
        )

    if (item.get("importancia") or "") == "Parada de Linha":
        riscos.append(
            "Risco de parada de linha, devido à utilização do material diretamente no "
            f"processo produtivo{' de ' + dados['setor_dominante'] if dados['setor_dominante'] else ''}."
        )

    if minimo > 0 and 0 < estoque < minimo:
        pct = (minimo - estoque) / minimo * 100
        riscos.append(
            "Risco de indisponibilidade por reposição tardia, uma vez que o estoque já se "
            f"encontra {_fmt(pct)}% abaixo do estoque mínimo estabelecido "
            f"({_fmt(estoque)} {unidade} contra {_fmt(minimo)} {unidade})."
        )

    if dados["padrao_demanda"] in PADROES_NAO_LINEARES:
        riscos.append(
            "Risco de consumo não linear, pois as saídas ocorrem de forma intermitente, "
            "porém em quantidades relevantes, podendo gerar redução acelerada do estoque "
            "entre os períodos de consumo."
        )

    return riscos


def _por_que(item, dados):
    """Seção 3 — parágrafo curto: o que o item faz e por que repor agora."""
    unidade = dados["unidade"]
    estoque = _num(item.get("estoque_atual"))
    minimo = _num(item.get("estoque_minimo"))
    nome = (item.get("nome_item") or "").strip() or item.get("part_number")

    partes = [f"{nome}"]
    if dados["setor_dominante"]:
        partes.append(f"utilizado principalmente por {dados['setor_dominante']}")
    if item.get("importancia"):
        partes.append(f"classificado como {item['importancia']}")
    frase = ", ".join(partes) + "."

    if minimo > 0 and estoque < minimo:
        situacao = (
            f" O estoque atual ({_fmt(estoque)} {unidade}) está abaixo do mínimo ({_fmt(minimo)} {unidade})"
        )
    else:
        situacao = f" O estoque atual é de {_fmt(estoque)} {unidade}"

    if dados["consumo_mensal"] is not None:
        situacao += f", com consumo mensal de aproximadamente {_fmt(dados['consumo_mensal'])} {unidade}"
        situacao += f" ({dados['fonte_rotulo']})."
    else:
        situacao += ", e não há consumo mensal apurado no período analisado."

    return frase + situacao


def montar_dados_analise(item_id, conn=None, hoje=None, observacoes=None):
    """Tudo o que o PDF de UM item precisa, já decidido e redigido.

    A escolha da fonte acontece aqui e em nenhum outro lugar: SC7 com pedido atendido
    vence; sem ele, requisição; sem as duas, `sem_historico` — e o documento diz isso em
    vez de estampar zero. Zero e "não sabemos" são coisas diferentes, e confundi-las na
    justificativa de uma compra é o erro caro.
    """
    hoje = hoje or date.today()
    item = buscar_item_por_id(item_id)
    if not item:
        raise ValueError(f"item {item_id} não encontrado")

    unidade = (item.get("unidade") or "UN").strip() or "UN"

    with transaction(conn) as c:
        sc7 = C7.consumo_sc7_por_item(c, item_id=item_id, hoje=hoje).get(item_id) or {}
    setores = setor_dominante_por_item([item_id], conn)
    demanda = classificar_demanda(item_id, conn)
    calc = calcular_ponto_reposicao(item)
    frescor = sc7_frescor(conn, hoje)

    dados = {
        "item_id": item_id,
        "part_number": item.get("part_number"),
        "nome_item": item.get("nome_item"),
        "descricao": item.get("descricao"),
        "unidade": unidade,
        "importancia": item.get("importancia"),
        "estoque_atual": _num(item.get("estoque_atual")),
        "estoque_minimo": _num(item.get("estoque_minimo")),
        "estoque_maximo": _num(item.get("estoque_maximo")),
        "data_inventario": _data_br(item.get("data_inventario")),
        "setor_dominante": setores.get(item_id),
        "padrao_demanda": demanda.get("padrao"),
        "lead_time": calc.get("lead_time"),
        "rop": calc.get("rop"),
        "sc7": sc7,
        "requisicao": None,
        # A data da planilha vai IMPRESSA no rodapé do PDF: o documento sai do sistema e
        # vive sozinho num e-mail, então tem de carregar a idade da sua própria fonte.
        "sc7_importado_em": frescor.get("data"),
        "observacoes": (observacoes or "").strip(),
        "gerado_em": hoje,
    }

    if sc7.get("consumo_mensal") is not None:
        dados["modo"] = MODO_SC7
        dados["consumo_mensal"] = sc7["consumo_mensal"]
        dados["fonte_rotulo"] = C7.rotulo_consumo(sc7) or "SC7"
        dados["explicacao_fallback"] = None
    else:
        req = consumo_por_requisicao(item_id, conn, hoje)
        dados["requisicao"] = req
        dados["consumo_mensal"] = req["consumo_mensal"]
        dados["modo"] = MODO_REQUISICAO if req["consumo_mensal"] is not None else MODO_SEM_HISTORICO
        dados["fonte_rotulo"] = (
            f"retiradas do almoxarifado {C7.rotulo_periodo(req['ano_ref'], req['meses'])}"
            if req["consumo_mensal"] is not None
            else "sem histórico"
        )
        dados["explicacao_fallback"] = _explicacao_fallback(req, unidade)

    dados["consumo_diario"] = (
        round(dados["consumo_mensal"] / 30, 2) if dados["consumo_mensal"] is not None else None
    )
    dados["por_que"] = _por_que(item, dados)
    dados["riscos"] = _riscos(item, dados)
    return dados


# ══════════════════════════════════════════════════════════════════════════════
# NOME DO ARQUIVO
# ══════════════════════════════════════════════════════════════════════════════


def nome_arquivo_analise(part_number, descricao, extensao="pdf"):
    """`Consumo <PN>-<Descrição>.pdf` — a convenção do lote que o Luis já gerou à mão.

    `/` e os demais proibidos do Windows viram `-`. O nome é cortado porque
    `part_number + descrição` passa de 200 caracteres em vários itens e o caminho completo
    (área de trabalho + pasta + nome) estoura o limite do Explorer."""
    pn = re.sub(_INVALIDOS_NO_NOME, "-", str(part_number or "SEM-PN")).strip()
    desc = re.sub(_INVALIDOS_NO_NOME, "-", str(descricao or "").strip())
    desc = re.sub(r"\s+", " ", desc).strip(" .-")
    base = f"Consumo {pn}-{desc}".strip(" -") if desc else f"Consumo {pn}"
    return f"{base[:120].strip(' .-')}.{extensao}"


# ══════════════════════════════════════════════════════════════════════════════
# PDF — reportlab, em memória
# ══════════════════════════════════════════════════════════════════════════════

CINZA_FONTE = "#7A7F87"
FUNDO_CABECALHO = "#F2F4F8"
BORDA = "#D8DDE3"


def _texto_pdf(valor, markup=True):
    """Sanitiza texto vindo do usuário/cadastro antes de entrar no PDF.

    `markup=True` (padrão) é para `Paragraph`, que interpreta mini-HTML; `markup=False`
    é para célula de `Table`, que **não** interpreta — escapar ali imprimiria `&amp;` na
    cara do leitor.

    Duas armadilhas, as duas com dado real:

    1. **`Paragraph` interpreta mini-HTML.** Uma descrição "PORCA & PARAFUSO" ou uma
       observação "trocar por <modelo novo>" levanta erro de parse e o PDF não sai — em
       cima de um campo que o almoxarife digita à mão na tela de revisão. Os 363 itens de
       hoje estão limpos; a próxima observação digitada não tem como estar garantida.
    2. **A fonte padrão (Helvetica/WinAnsi) não tem tudo.** Medido: os acentos do
       português, `—`, `–`, `·`, `•`, `º`, `ª` e as aspas curvas passam; `▪` e `→` não têm
       mapeamento e derrubariam a geração. Quem não mapeia vira `?` em vez de quebrar o
       documento inteiro — perder um caractere é melhor que perder o PDF.

    ⚠️ Aplique em TODO texto de origem externa (nome, descrição, setor, observações). O
    texto que este módulo escreve é conhecido e já está dentro do conjunto seguro.
    """
    texto = str(valor if valor is not None else "")
    seguro = []
    for ch in texto:
        try:
            ch.encode("cp1252")
        except UnicodeEncodeError:
            seguro.append("?")
        else:
            seguro.append(ch)
    texto = "".join(seguro)
    if not markup:
        return texto
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _estilos():
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "MroTitulo", parent=base["Title"], fontSize=15, textColor=ACCENT, alignment=0, spaceAfter=2
        ),
        "cabecalho": ParagraphStyle(
            "MroCabecalho", parent=base["Normal"], fontSize=9, textColor=CINZA_FONTE, spaceAfter=10
        ),
        "secao": ParagraphStyle(
            "MroSecao",
            parent=base["Heading2"],
            fontSize=12,
            textColor=ACCENT,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "texto": ParagraphStyle(
            "MroTexto", parent=base["Normal"], fontSize=10, leading=14, alignment=TA_JUSTIFY
        ),
        "aviso": ParagraphStyle(
            "MroAviso",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            alignment=TA_JUSTIFY,
            backColor=FUNDO_CABECALHO,
            borderColor=ACCENT,
            borderWidth=1,
            borderPadding=6,
            spaceAfter=8,
        ),
        "bullet": ParagraphStyle(
            "MroBullet", parent=base["Normal"], fontSize=10, leading=14, leftIndent=12, spaceAfter=4
        ),
        "fonte": ParagraphStyle(
            "MroFonte",
            parent=base["Italic"],
            fontSize=8,
            textColor=CINZA_FONTE,
            spaceBefore=14,
        ),
        "celula": ParagraphStyle("MroCelula", parent=base["Normal"], fontSize=9, leading=12),
    }


def _tabela(linhas, larguras, estilos_extra=None):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    tabela = Table(linhas, colWidths=larguras, hAlign="LEFT")
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDA)),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor(FUNDO_CABECALHO)),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    tabela.setStyle(TableStyle(estilo + (estilos_extra or [])))
    return tabela


def _bloco_consumo(dados, est):
    """Seção 2 — a tabela por período + a frase de origem da demanda.

    As duas fontes usam a MESMA moldura de período, para o leitor não precisar aprender
    dois formatos: `<período> | <o que foi somado> | <total> | <consumo mensal>`.
    """
    from reportlab.platypus import Paragraph

    unidade = _texto_pdf(dados["unidade"], markup=False)
    fluxo = []

    if dados["explicacao_fallback"]:
        fluxo.append(Paragraph(f"<b>Atenção:</b> {_texto_pdf(dados['explicacao_fallback'])}", est["aviso"]))

    linhas = [["Período", "O que foi somado", "Total", "Consumo mensal"]]
    if dados["modo"] == MODO_SC7:
        sc7 = dados["sc7"]
        for bloco in (sc7.get("ano_anterior"), sc7.get("ano_atual")):
            if not bloco or bloco.get("consumo_mensal") is None:
                continue
            linhas.append(
                [
                    C7.rotulo_periodo(bloco["ano"], bloco["meses"]),
                    f"{bloco['n_pedidos']} pedido(s) atendido(s)",
                    f"{_fmt(bloco['total_entregue'])} {unidade}",
                    f"{_fmt(bloco['consumo_mensal'])} {unidade}/mês",
                ]
            )
    elif dados["modo"] == MODO_REQUISICAO:
        req = dados["requisicao"]
        for bloco in (req.get("ano_anterior"), req.get("ano_atual")):
            if not bloco or bloco.get("consumo_mensal") is None:
                continue
            linhas.append(
                [
                    C7.rotulo_periodo(bloco["ano"], bloco["meses"]),
                    f"retiradas em {bloco['meses_com_saida']} mês(es)",
                    f"{_fmt(bloco['total'])} {unidade}",
                    f"{_fmt(bloco['consumo_mensal'])} {unidade}/mês",
                ]
            )

    if len(linhas) > 1:
        fluxo.append(_tabela(linhas, [90, 150, 90, 110]))
    else:
        fluxo.append(
            Paragraph(
                "Não há consumo apurado para este material no ano corrente nem no anterior.",
                est["texto"],
            )
        )

    # Pedido pendente não some: explica o "—" e evita que o gestor leia pouco consumo
    # como pouca necessidade quando o material só não chegou ainda.
    pendentes = (dados.get("sc7") or {}).get("pendentes") or {}
    if pendentes.get("n"):
        fluxo.append(
            Paragraph(
                f"Há {pendentes['n']} pedido(s) de compra com saldo a receber "
                f"({_fmt(pendentes.get('qtd'))} {unidade}) — ainda não entregues, portanto "
                "fora da conta de consumo.",
                est["texto"],
            )
        )

    if dados["setor_dominante"]:
        origem = f"Consumo concentrado em <b>{_texto_pdf(dados['setor_dominante'])}</b>."
    else:
        origem = "Uso administrativo, distribuído por vários setores."
    fluxo.append(Paragraph(origem, est["texto"]))
    return fluxo


def gerar_pdf_analise(dados):
    """PDF de UM material → `bytes`. Seções 1–4; encerra em Riscos.

    **Não existe seção de "Proposta de reposição"** — decisão de 17/08/2026, coerente com
    o lote de documentos já entregue. O documento apresenta o quadro; a quantidade a
    comprar é decisão de quem lê, e escrevê-la aqui daria ao PDF um ar de pedido aprovado.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    est = _estilos()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Análise de Consumo — {dados['part_number']}",
        author="Sistema MRO",
    )
    unidade = _texto_pdf(dados["unidade"], markup=False)
    fluxo = [
        Paragraph("Análise de Consumo", est["titulo"]),
        Paragraph(
            f"PN: {_texto_pdf(dados['part_number'])} · {_texto_pdf(dados['nome_item'])} · "
            f"Unidade: {unidade} · "
            f"Data da análise: {dados['gerado_em'].strftime('%d/%m/%Y')}",
            est["cabecalho"],
        ),
        Paragraph("1. Identificação", est["secao"]),
    ]

    estoque_txt = f"{_fmt(dados['estoque_atual'])} {unidade}"
    if dados["data_inventario"]:
        estoque_txt += f" (inventário {dados['data_inventario']})"
    identificacao = [
        ["Campo", "Valor"],
        ["Part number", _texto_pdf(dados["part_number"] or "—", markup=False)],
        # Célula longa vira Paragraph para QUEBRAR linha: descrição de 80 caracteres numa
        # célula de 320pt sai cortada em texto puro, sem aviso nenhum.
        ["Descrição", Paragraph(_texto_pdf(dados["nome_item"] or "—"), est["celula"])],
        ["Unidade", unidade],
        ["Estoque atual", estoque_txt],
        ["Estoque mínimo", f"{_fmt(dados['estoque_minimo'])} {unidade}"],
        ["Estoque máximo", f"{_fmt(dados['estoque_maximo'])} {unidade}"],
    ]
    if dados["importancia"]:
        identificacao.append(["Importância", _texto_pdf(dados["importancia"], markup=False)])
    fluxo.append(_tabela(identificacao, [120, 320]))

    fluxo.append(Paragraph("2. Análise de consumo", est["secao"]))
    fluxo.extend(_bloco_consumo(dados, est))

    fluxo.append(Paragraph("3. Por que o material é necessário", est["secao"]))
    fluxo.append(Paragraph(_texto_pdf(dados["por_que"]), est["texto"]))
    if dados.get("observacoes"):
        fluxo.append(Spacer(1, 6))
        fluxo.append(Paragraph(_texto_pdf(dados["observacoes"]), est["texto"]))

    fluxo.append(Paragraph("4. Riscos", est["secao"]))
    if dados["riscos"]:
        for risco in dados["riscos"]:
            fluxo.append(Paragraph(f"• {_texto_pdf(risco)}", est["bullet"]))
    else:
        fluxo.append(
            Paragraph(
                "Não foram identificados riscos relevantes para este material no momento: o "
                "estoque está dentro dos parâmetros cadastrados.",
                est["texto"],
            )
        )

    fonte = "Análise gerada a partir dos dados do Sistema MRO" + (
        f" e do Relatório de Compras (SC7) de {_data_br(dados.get('sc7_importado_em'))}."
        if dados.get("sc7_importado_em")
        else "."
    )
    fluxo.append(Paragraph(fonte, est["fonte"]))

    doc.build(fluxo)
    return buffer.getvalue()


def gerar_pdf_analise_geral(lista_dados, hoje=None):
    """`Analise Geral.pdf` — a tabela resumo do lote, para anexar no e-mail.

    Colunas fixadas em `PROMPT_DOCUMENTO_ALMOXARIFE.md`; o consumo diário é o mensal ÷ 30
    (não é média independente — se fosse, as duas colunas poderiam se contradizer na mesma
    linha). Sai em paisagem porque sete colunas com descrição legível não cabem em A4
    retrato sem quebrar a descrição em quatro linhas.
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    hoje = hoje or date.today()
    est = _estilos()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="Análise Geral",
        author="Sistema MRO",
    )
    fluxo = [
        Paragraph("Análise Geral", est["titulo"]),
        Paragraph(f"Data da análise: {hoje.strftime('%d/%m/%Y')}", est["cabecalho"]),
    ]

    linhas = [["PN", "Descrição", "Estoque Atual", "MIN", "MAX", "Consumo Diário", "Consumo Mensal"]]
    for d in lista_dados:
        un = _texto_pdf(d["unidade"], markup=False)
        linhas.append(
            [
                _texto_pdf(d["part_number"] or "—", markup=False),
                Paragraph(_texto_pdf(d["nome_item"] or "—"), est["celula"]),
                f"{_fmt(d['estoque_atual'])} {un}",
                f"{_fmt(d['estoque_minimo'])} {un}",
                f"{_fmt(d['estoque_maximo'])} {un}",
                f"{_fmt(d['consumo_diario'], 2)} {un}" if d["consumo_diario"] is not None else "—",
                f"{_fmt(d['consumo_mensal'])} {un}" if d["consumo_mensal"] is not None else "—",
            ]
        )

    from reportlab.lib import colors

    tabela = _tabela(
        linhas,
        [70, 250, 85, 65, 65, 85, 85],
        estilos_extra=[
            # Nesta tabela o cabeçalho é a 1ª LINHA, não a 1ª coluna (o `_tabela` pinta a
            # coluna porque as fichas são Campo/Valor). Repinta as duas faixas certas.
            ("BACKGROUND", (0, 1), (0, -1), colors.white),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(FUNDO_CABECALHO)),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ],
    )
    fluxo.append(tabela)
    doc.build(fluxo)
    return buffer.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# AUDITORIA
# ══════════════════════════════════════════════════════════════════════════════


def registrar_analise(lista_dados, usuario=None, conn=None, hoje=None):
    """Grava UMA linha em `analises_geradas` por lote gerado. Devolve o id.

    Guarda a versão do SC7 usada e o modo do lote (`sc7`, `requisicao` ou `misto`): sem
    esses dois, dois PDFs do mesmo item em datas diferentes seriam indistinguíveis no
    registro, e a pergunta "de onde veio este número" ficaria sem resposta.
    """
    if not lista_dados:
        return None
    modos = {d["modo"] for d in lista_dados}
    modo = modos.pop() if len(modos) == 1 else "misto"
    pns = ", ".join(str(d.get("part_number") or "—") for d in lista_dados)
    frescor = sc7_frescor(conn, hoje)

    with transaction(conn) as c:
        cur = c.execute(
            """INSERT INTO analises_geradas
                   (usuario, part_numbers, n_itens, sc7_data_importacao, modo)
               VALUES (?,?,?,?,?)""",
            (usuario, pns, len(lista_dados), frescor.get("data"), modo),
        )
        return cur.lastrowid


def listar_analises(limite=50, conn=None):
    """Últimas análises geradas (mais recentes primeiro) — leitura para a tela/auditoria."""
    with transaction(conn) as c:
        rows = c.execute("SELECT * FROM analises_geradas ORDER BY id DESC LIMIT ?", (int(limite),)).fetchall()
    return [dict(r) for r in rows]
