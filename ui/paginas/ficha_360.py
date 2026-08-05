"""Página Ficha 360 do Material (v6.0.0) — a vida útil do item em uma tela.

Migrada do bloco inline do `app.py` (migração FIEL). Read-only: a única escrita é a
imagem do produto (`salvar_imagem_item`/`remover_imagem_item`), que não entra nas
leituras cacheadas (inventário/dashboards) — logo NÃO chama `invalidar_leituras()`.
Todo o conteúdo é montado por `services.ficha.montar_ficha_360`.

v6.0.0 — duas mudanças de UX, ambas sem tocar em cálculo: (1) a **recomendação
automática de reposição** saiu da tela (a decisão de compra vive no Assistente de
Reposição, mesmo motor); (2) a **Evolução de preço** deixou o `st.line_chart` cru e
passou a usar o dado que a query já trazia (moeda, fornecedor, PO, SC).

Removido na migração o `_render_ficha_guarda_chuva` (código morto desde a v4.9.0 — a
sub-aba Guarda-Chuva virou controle próprio em "Controle de SC → ☂️ Guarda-Chuva").
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from services.constants import PREVISAO_RUPTURA_SEM_RISCO
from services.ficha import (
    montar_ficha_360,
    salvar_imagem_item,
    remover_imagem_item,
)
from ui.tema import paleta_atual
from ui.formatos import fmt, fmt_brl, fmt_moeda
from ui.componentes.graficos import _barv, _linha_valor, _mes_label
from ui.componentes.selecao import sel_material


def _hover_preco(linha):
    """Linhas extras do tooltip de um ponto da evolução de preço: fornecedor, PO e SC.

    Devolve string pronta (já com as quebras do Plotly) — vazia quando o histórico não
    trouxe nenhum dos três, para o tooltip não ficar com rótulos órfãos."""
    partes = [
        (rot, str(linha.get(campo) or "").strip())
        for rot, campo in (("Fornecedor", "fornecedor"), ("PO", "numero_po"), ("SC", "numero_sc"))
    ]
    return "".join(f"<br>{rot}: {val}" for rot, val in partes if val)


def _render_evolucao_preco(ep):
    """Evolução de preço (v6.0.0) — antes um `st.line_chart` cru que só usava a coluna
    `preco_unitario` e descartava moeda/fornecedor/PO/SC que a query já trazia.

    Mesma query (`obter_evolucao_preco`), mesmo dado: só o desenho mudou. Com um único
    ponto o gráfico de linha não diz nada, então vira métrica. Quando o histórico mistura
    moedas, o eixo não pode somar tudo em R$ — a tabela substitui o gráfico."""
    if not ep:
        return

    st.markdown("##### :material/trending_up: Evolução de preço")
    df_ep = pd.DataFrame(ep)
    df_ep["data"] = pd.to_datetime(df_ep["data"], errors="coerce")
    df_ep = df_ep.dropna(subset=["data"]).sort_values("data")
    if df_ep.empty:
        st.caption("Histórico de preços sem data utilizável.")
        return

    moedas = {str(m).strip().upper() for m in df_ep["moeda"].dropna() if str(m).strip()}
    if len(moedas) > 1:
        st.caption(
            f":material/language: Histórico em mais de uma moeda ({', '.join(sorted(moedas))}) — "
            "sem conversão cambial, os preços vão em tabela para não somar moedas diferentes."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Data": fmt(str(r["data"].date())),
                        "Preço": fmt_moeda(r["preco_unitario"], r.get("moeda") or "R$"),
                        "Fornecedor": r.get("fornecedor") or "—",
                        "PO": r.get("numero_po") or "—",
                        "SC": r.get("numero_sc") or "—",
                        "Origem": r.get("origem") or "—",
                    }
                    for _, r in df_ep.iterrows()
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        return

    _moeda = next(iter(moedas), "R$")
    _prefixo = "R$ " if _moeda in ("", "R$", "BRL") else f"{_moeda} "
    primeiro = float(df_ep["preco_unitario"].iloc[0])
    ultimo = float(df_ep["preco_unitario"].iloc[-1])

    m1, m2, m3 = st.columns(3)
    _var = ((ultimo - primeiro) / primeiro * 100) if primeiro else None
    m1.metric(
        "Último preço",
        fmt_moeda(ultimo, _prefixo.strip()),
        delta=(f"{_var:+.1f}% vs. o 1º registro".replace(".", ",") if _var is not None else None),
        delta_color="inverse",  # preço subindo é ruim para o comprador
        help=f"Registro mais recente ({fmt(str(df_ep['data'].iloc[-1].date()))}).",
    )
    m2.metric("Menor preço", fmt_moeda(df_ep["preco_unitario"].min(), _prefixo.strip()))
    m3.metric(
        "Registros",
        len(df_ep),
        help="Preços vindos do Relatório de SCs (SCM/SC7) — um por compra conhecida.",
    )

    if len(df_ep) < 2:
        st.caption(
            ":material/info: Um único preço no histórico — a curva aparece quando houver "
            "uma segunda compra registrada."
        )
        return

    st.plotly_chart(
        _linha_valor(
            list(df_ep["data"]),
            [float(v) for v in df_ep["preco_unitario"]],
            hover=[_hover_preco(r) for _, r in df_ep.iterrows()],
            prefixo=_prefixo,
        ),
        width="stretch",
        config={"displayModeBar": False},
    )
    st.caption("Passe o mouse em cada ponto para ver fornecedor, PO e SC daquela compra.")


def _render_ficha_visao_geral(ficha):
    """Corpo original da Ficha 360 (v4.4.0: extraido para a 1a aba \"Visao Geral\")."""
    PAL = paleta_atual()
    it = ficha["item"]
    mat = ficha["maturidade"]

    def _g(v):  # número curto e seguro (None -> 0)
        return f"{(v or 0):g}"

    def _g1(v):  # arredonda a 1 casa (4.46667 -> 4.5); inteiros ficam sem ".0"
        return f"{round(v or 0, 1):g}"

    # ── Cabeçalho: imagem + cadastro ──────────────────────────────────
    col_img, col_cad = st.columns([1, 2])
    with col_img:
        if ficha["imagem_abs"]:
            st.image(ficha["imagem_abs"], use_container_width=True)
        else:
            st.markdown(
                f"<div style='border:1px dashed {PAL['painel_borda']};border-radius:8px;"
                f"padding:32px;text-align:center;color:{PAL['texto_suave']};'>Sem imagem</div>",
                unsafe_allow_html=True,
            )
        with st.expander(":material/image: Imagem do produto"):
            up = st.file_uploader(
                "Enviar/atualizar (png/jpg/webp, até 5 MB)",
                type=["png", "jpg", "jpeg", "webp", "gif"],
                key="ficha_img_up",
            )
            cb1, cb2 = st.columns(2)
            if cb1.button(
                ":material/save: Salvar", key="ficha_img_save", disabled=up is None, width="stretch"
            ):
                ok, msg = salvar_imagem_item(it["id"], up.name, up.getvalue())
                if ok:
                    st.success("Imagem salva.")
                    st.rerun()
                else:
                    st.error(msg)
            if ficha["imagem_abs"] and cb2.button(
                ":material/delete: Remover", key="ficha_img_del", width="stretch"
            ):
                remover_imagem_item(it["id"])
                st.rerun()
    with col_cad:
        st.subheader(f"{it['part_number']} — {it['nome_item']}")
        # v4.1.0: "Setor que mais consome" (top do consumo real por setor) no lugar do
        # antigo "Setor responsável" (campo estático, ~98% "Improdutivo"); Local mostra
        # as 2 locações quando houver.
        _top_setor = (
            ficha["departamentos"]["por_setor"][0]["chave"] if ficha["departamentos"]["por_setor"] else "—"
        )
        _locais = (
            " · ".join(x for x in [it.get("local_armazenagem"), it.get("local_armazenagem_2")] if x) or "—"
        )
        st.markdown(
            f"**Categoria/Tipo:** {it.get('tipo_material') or '—'}  \n"
            f"**Unidade:** {it.get('unidade') or '—'} · "
            f"**Criticidade:** {it.get('importancia') or '—'}  \n"
            f"**Setor que mais consome:** {_top_setor}  \n"
            f"**Local:** {_locais}"
            + (f" · Caixa {it.get('caixa_identificacao')}" if it.get("caixa_identificacao") else "")
        )
        if it.get("descricao"):
            st.caption(it["descricao"])

        # v2.7.0 — Situação de consumo (real = saída por requisição)
        if it.get("sem_movimentacao"):
            st.caption(
                "⚪ **Situação de consumo:** Sem movimentação "
                "(nunca teve saída por requisição) — fora da lista de compra."
            )
        else:
            _ult = it.get("ultima_requisicao_data")
            _ult_txt = f" · última em {fmt(_ult)}" if _ult else ""
            st.caption(
                f"🟢 **Situação de consumo:** {it.get('qtd_requisicoes', 0)} requisição(ões){_ult_txt}."
            )

    # ── Conversão de unidades (v2.9.0) ────────────────────────────────
    _fat_f = float(it.get("fator_conversao") or 1.0) or 1.0
    _uc_f = it.get("unidade_compra")
    if abs(_fat_f - 1.0) > 1e-9 and _uc_f:
        st.caption(
            f":material/sync: **Conversão:** compra em **{_uc_f}** · **1 {it.get('unidade') or 'UN'}** "
            f"de estoque = **{_fat_f:g} {_uc_f}** (fator {_fat_f:g})."
        )

    # v6.0.0 — a RECOMENDAÇÃO AUTOMÁTICA de reposição saiu desta tela (pedido do
    # usuário): a decisão de comprar se dá no **Controle de SC › Assistente de
    # Reposição**, que usa o MESMO motor (`services/planejamento.py`). A chave
    # `reposicao` segue no view-model de `montar_ficha_360` — nada de cálculo mudou,
    # só deixou de ser desenhada aqui.
    un = it.get("unidade") or "UN"

    # ── Estoque / cobertura / giro ────────────────────────────────────
    st.divider()
    e1, e2, e3, e4 = st.columns(4)
    # v6.4.0 — a sugestão calculada aparece no help, como já acontece com o lead time
    # (g5): mostra o número sem tocar no cadastrado. Quem transforma sugestão em base é o
    # botão "Usar calculado" do Cadastro de Itens.
    _mm_amostras = int(it.get("min_max_amostras") or 0)
    _mm_origem = it.get("min_max_origem") or "—"

    def _ajuda_mm(calculado):
        if not calculado:
            return (
                "Baseado no reajuste de compras. Sem sugestão calculada (item sem consumo na janela de 30 d)."
            )
        return (
            f"Baseado no reajuste de compras. Sugestão calculada: **{_g1(calculado)}** "
            f"({_mm_origem}, {_mm_amostras} saída(s) na janela). O cadastrado não é alterado "
            "automaticamente — use *Cadastro de Itens › Editar* para adotar."
        )

    e1.metric("Estoque atual", _g(it.get("estoque_atual")))
    e2.metric("Quantidade Mínima", _g(it.get("estoque_minimo")), help=_ajuda_mm(it.get("minimo_calculado")))
    e3.metric("Quantidade Máxima", _g(it.get("estoque_maximo")), help=_ajuda_mm(it.get("maximo_calculado")))
    e4.metric(
        "Saldo Item (PO)",
        _g(it.get("estoque_em_transito")),
        help="Qtd já negociada em pedidos (PO/SC) aprovados que ainda falta chegar.",
    )

    cob = it.get("dias_cobertura")
    giro = ficha["giro"]
    g1, g2, g3, g6, g4, g5 = st.columns(6)
    g1.metric(
        "Dias até acabar",
        f"{cob:.0f} d" if cob is not None and cob < PREVISAO_RUPTURA_SEM_RISCO else "—",
        help="Quantos dias o estoque atual ainda dura no ritmo de consumo atual "
        "(estoque atual ÷ consumo médio diário). '—' = sem consumo registrado, "
        "logo não há previsão de término.",
    )
    tend = it.get("tendencia_label")
    tend_txt = (
        (f"{tend} {'+' if (it.get('tendencia_pct') or 0) >= 0 else ''}{_g(it.get('tendencia_pct'))}%")
        if tend
        else None
    )
    g2.metric(
        "Consumo/dia",
        f"{_g1(it.get('consumo_medio_diario'))} {un}/dia",
        delta=tend_txt,
        delta_color="inverse",
        help="Média de quanto sai por dia deste item, pelas saídas reais por requisição "
        "na janela de 30 dias. A seta indica a tendência vs. os 30 dias anteriores.",
    )
    _cons_mes = (ficha.get("classificacao") or {}).get("consumo_mensal_ponderado")
    g3.metric(
        "Consumo/Mensal",
        f"{_g1(_cons_mes)} {un}/mês" if _cons_mes is not None else "—",
        delta=tend_txt,
        delta_color="inverse",
        help="Consumo médio por mês: média PONDERADA dos últimos 3 meses completos, com o "
        "mês mais recente pesando mais (3/2/1). Usa as saídas reais por mês (dias úteis "
        "já embutidos); meses sem saída contam 0 e a média decai se o item parar. A "
        "seta é a mesma tendência do Consumo/dia.",
    )
    # v6.4.0 — o consumo pela VIDA ÚTIL do lote, ao lado do ponderado: os dois medem
    # consumo mensal por caminhos diferentes (mês-calendário × duração do recebimento),
    # e ver os dois juntos é o ponto — quando divergem muito, o item tem compra
    # descolada do giro.
    _vida = (ficha.get("classificacao") or {}).get("vida_util") or {}
    _cons_lote = _vida.get("consumo_mensal")
    _min_piso = float(it.get("estoque_minimo") or 0)
    g6.metric(
        "Consumo/Mensal (lote)",
        f"{_g1(_cons_lote)} {un}/mês" if _cons_lote is not None else "—",
        help=(
            f"Média de {_vida.get('n_lotes', 0)} lote(s) recebido(s), que duraram "
            f"{_g1(_vida.get('dias_medio'))} d em média: quantidade recebida ÷ dias até o "
            f"estoque bater o mínimo ({_g(_min_piso) if _min_piso > 0 else 'zerar — item sem mínimo cadastrado'}) × 30. "
            f"{_vida.get('n_lotes_vivos', 0)} lote(s) ainda em uso não entram na conta."
            if _cons_lote is not None
            else "Sem lote fechado para medir: só recebimento por SC abre lote, e ele precisa "
            "ter durado ao menos 1 dia acima do mínimo. Ajuste de inventário e entrada "
            "avulsa não contam."
        ),
    )
    g4.metric(
        "Giro anual",
        _g(giro["giro_anual"]),
        help='Quantas vezes o estoque "vira" no ano: '
        "(saídas dos últimos 90 d ÷ estoque médio das fotos diárias) × (365 ÷ 90). "
        "Base: estoque_snapshots (fotos diárias do saldo) + saídas de movimentações. "
        "Maior = gira mais rápido; menor = parado. "
        f"Tempo médio em estoque: "
        f"{giro['tempo_medio_dias'] if giro['tempo_medio_dias'] else '—'} d · "
        f"baseado em {giro['n_snapshots']} fotos.",
    )
    lt_calc = it.get("lead_time_calculado")
    g5.metric(
        "Lead time (Compras)",
        f"{int(it.get('lead_time_dias') or 0)} d",
        help=(
            f"Calculado (sugestão): {int(lt_calc)} d "
            f"({it.get('lead_time_calculado_amostras') or 0} amostras, "
            f"{it.get('lead_time_calculado_origem') or '—'})"
            if lt_calc
            else "Sem lead time calculado ainda."
        ),
    )

    # ── Consumo (30/60/90) + Valor ────────────────────────────────────
    cc1, cc2 = st.columns(2)
    with cc1:
        with st.container(border=True):
            st.markdown("##### :material/trending_down: Consumo médio/dia por janela")
            st.caption(
                "Média de saída por dia em 3 janelas (30/60/90 dias). Comparar as três "
                "mostra se o consumo está **acelerando** (30d > 90d) ou **desacelerando**."
            )
            _cons_j = [
                round(it.get("consumo_30d") or 0, 1),
                round(it.get("consumo_60d") or 0, 1),
                round(it.get("consumo_90d") or 0, 1),
            ]
            st.plotly_chart(
                _barv(["30 dias", "60 dias", "90 dias"], _cons_j, textos=[f"{v:g}" for v in _cons_j]),
                width="stretch",
                config={"displayModeBar": False},
            )
    with cc2:
        with st.container(border=True):
            st.markdown("##### :material/payments: Valor")
            st.caption(
                "Quanto este item representa em dinheiro: **parado em estoque** hoje e "
                "**consumido no ano** (estimado pelo último preço de compra)."
            )
            vc = ficha["valor"]["valor_consumido"]
            st.metric("Valor em estoque", fmt_brl(ficha["valor"]["valor_estoque"]))
            # v2.7.1: valor unitário (preço de referência) logo abaixo
            _preco_un = vc.get("preco") or 0
            st.caption(
                f"Valor unitário: **{fmt_moeda(_preco_un, vc['moeda'])}** / {un} · origem {vc['origem']}"
            )
            st.metric(
                f"Valor consumido (YTD {date.today().year})",
                fmt_moeda(vc["valor"], vc["moeda"]),
                help=f"Estimativa (último preço, origem {vc['origem']}). "
                f"Acumulado de 01/01/{date.today().year} até hoje.",
            )
            if ficha["abc"]:
                st.caption(
                    f"Curva ABC (valor): classe **{ficha['abc']['classe']}** "
                    f"· {ficha['abc']['pct_acumulado']}% acumulado."
                )

    # ── Evolução de preço ─────────────────────────────────────────────
    _render_evolucao_preco(ficha["evolucao_preco"])

    # ── Quem consome (departamentos / centros de custo) ───────────────
    st.markdown("##### :material/group: Quem consome (últimos 180 dias)")
    dep = ficha["departamentos"]
    if dep["total"] <= 0:
        st.caption("Sem saídas registradas no período.")
    else:
        d1, d2 = st.columns(2)
        d1.caption("Por centro de custo")
        d1.dataframe(
            pd.DataFrame(
                [
                    {"Centro de custo": r["chave"], "Qtd": r["qtd"], "%": r["pct"]}
                    for r in dep["por_centro_custo"]
                ],
            ),
            hide_index=True,
            width="stretch",
        )
        d2.caption("Por setor")
        d2.dataframe(
            pd.DataFrame([{"Setor": r["chave"], "Qtd": r["qtd"], "%": r["pct"]} for r in dep["por_setor"]]),
            hide_index=True,
            width="stretch",
        )

    # ── Fornecedores ──────────────────────────────────────────────────
    with st.expander(f":material/apartment: Fornecedores ({len(ficha['fornecedores'])})"):
        fs = ficha["fornecedores"]
        if not fs:
            st.caption("Sem fornecedores vinculados (vêm dos pedidos do Relatório de SCs).")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Fornecedor": f["fornecedor"],
                            "Último Preço": f["ultimo_preco"],
                            "Moeda": f["moeda"],
                            "Nº Compras": f["n_compras"],
                            "Lead Time (d)": f["lead_time_fornecedor"],
                            "E-mail": f["email"] or "—",
                            "Melhor preço": "⭐" if f.get("melhor") else "",
                        }
                        for f in fs
                    ]
                ),
                hide_index=True,
                width="stretch",
            )

    # ── Histórico de SCs / POs ────────────────────────────────────────
    with st.expander(f":material/receipt_long: Histórico de SCs / POs ({len(ficha['scs_pos'])})"):
        sp = ficha["scs_pos"]
        if not sp:
            st.caption("Nenhuma SC registrada para este item.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "SC": s["numero_sc"],
                            "PO": s.get("po_item") or s.get("numero_po") or "—",
                            "Fornecedor": s.get("fornecedor_item") or "—",
                            "Status": s.get("status"),
                            "Abertura": fmt(s.get("data_abertura")),
                            "Solic.": s.get("quantidade_solicitada"),
                            "Receb.": s.get("quantidade_recebida"),
                            "Pendente": s.get("pendente"),
                        }
                        for s in sp
                    ]
                ),
                hide_index=True,
                width="stretch",
            )

    # ── Histórico de movimentações ────────────────────────────────────
    with st.expander(f":material/sync: Movimentações recentes ({len(ficha['movimentacoes'])})"):
        mv = ficha["movimentacoes"]
        if not mv:
            st.caption("Sem movimentações.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Data": fmt(m.get("data_hora")),
                            "Tipo": m.get("tipo"),
                            "Qtd": m.get("quantidade"),
                            "Saldo": m.get("saldo_apos"),
                            "Centro de custo": m.get("centro_custo") or "—",
                            "Setor": m.get("setor") or "—",
                            "Obs": m.get("observacao") or "",
                        }
                        for m in mv
                    ]
                ),
                hide_index=True,
                width="stretch",
            )

    # ── Histórico de Part Number ──────────────────────────────────────
    if ficha["historico_pn"]:
        with st.expander(f":material/bookmark: Histórico de Part Number ({len(ficha['historico_pn'])})"):
            st.dataframe(pd.DataFrame(ficha["historico_pn"]), hide_index=True, width="stretch")

    # ── Classificação de demanda / XYZ / Sazonalidade (v2.10.0) ───────
    st.divider()
    st.markdown("##### :material/science: Padrão de demanda & variabilidade")
    cls = ficha.get("classificacao") or {}
    dem = cls.get("demanda") or {}
    xyz = cls.get("xyz") or {}
    saz = cls.get("sazonalidade") or {}
    cm = cls.get("consumo_mensal") or []

    xd1, xd2 = st.columns(2)
    with xd1:
        _emoji = dem.get("emoji") or "⚪"
        _pad = dem.get("padrao") or "Sem dados"
        st.markdown(f"**Demanda:** {_emoji} **{_pad}**")
        st.caption(dem.get("explicacao") or "")
        if dem.get("adi") is not None:
            st.caption(
                f"ADI {dem['adi']} · CV² {dem['cv2']} · "
                f"{dem['n_eventos']} semana(s) com consumo · "
                f"confiança {dem.get('confianca', '—')}."
            )
    with xd2:
        _cx = xyz.get("classe")
        if _cx:
            _rot = {"X": "estável", "Y": "variável", "Z": "errático"}.get(_cx, "")
            st.markdown(f"**XYZ:** **{_cx}** ({_rot})")
            st.caption(
                f"Coef. de variação mensal {xyz.get('cv')} · "
                f"{xyz.get('n_meses')} mês(es) · confiança {xyz.get('confianca', '—')}."
            )
        else:
            st.markdown("**XYZ:** —")
            st.caption("Precisa de ≥2 meses de consumo para medir a variabilidade.")

    if cm:
        st.markdown("###### :material/calendar_month: Consumo real por mês")
        st.plotly_chart(
            _barv(
                [_mes_label(x["mes"]) for x in cm],
                [round(x["qtd"], 1) for x in cm],
                textos=[f"{round(x['qtd'], 1):g}" for x in cm],
            ),
            width="stretch",
            config={"displayModeBar": False},
        )

    if not saz.get("disponivel"):
        st.caption(
            f":material/eco: **Sazonalidade:** amadurecendo — "
            f"{saz.get('meses_atuais', 0)}/{saz.get('meses_necessarios', 12)} "
            "meses (precisa de 1 ciclo anual completo para um perfil confiável)."
        )
    st.caption(
        f":material/calendar_month: Indicadores de série baseados em ~{mat['dias']} dias de histórico — "
        "diagnóstico que amadurece conforme os dados acumulam. A base do "
        "Compras (mín/máx/lead time/categoria) permanece intocada."
    )


def render() -> None:
    """Ficha 360 do Material (v2.6.0) — vida útil do item em uma tela (read-only,
    exceto a imagem do produto). Montagem de dados já existentes (v2.2-v2.5)."""
    st.title(":material/badge: Ficha 360 do Material")
    st.caption(
        "Toda a vida útil do material em uma tela — cadastro, estoque, consumo, "
        "compras, utilização, indicadores e recomendação. Somente leitura "
        "(a única escrita é a imagem do produto)."
    )

    _, item_f, _ = sel_material("Selecione o material (PN ou nome)", "ficha_item")
    if not item_f:
        st.info("Selecione um material para ver a ficha completa.")
        return

    ficha = montar_ficha_360(item_f["id"])
    if not ficha:
        st.error("Material não encontrado.")
        return

    # v4.9.0 — a sub-aba Guarda-Chuva saiu da Ficha 360 e virou um controle próprio e
    # manual em "Controle de SC → ☂️ Guarda-Chuva" (tabela guarda_chuva). A Ficha 360
    # volta a ser só a Visão Geral (read-only).
    _render_ficha_visao_geral(ficha)
