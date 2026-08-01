"""Página Dashboard (v6.0.0) — 2 abas por público (Comprador / Almoxarifado).

Migrada do bloco inline do `app.py`. Os assemblers seguem puros em
`services/dashboards.py`; aqui é só o desenho. Os construtores de gráfico foram para
`ui/componentes/graficos.py` (compartilhados com Ficha 360/Movimentação na F4b).

v6.0.0 — a aba **KPI Mensal** foi extinta (pedido do usuário: menos dashboards). O que
sobreviveu dela migrou para o Almoxarifado: Consumido no Ano, Requisições Atendidas no
Ano, Itens Movimentados no Ano e Consumo por Tipo de Material. O assembler
`montar_visao_executiva()` PERMANECE em services/ (coberto por test_v320) — só perdeu o
consumidor de UI. O Almoxarifado também herdou 5 blocos da aba Dashboard da Movimentação
(tendência, capital parado, maior valor em estoque, divergências e ruptura).

O cluster de DRILL-DOWN (modal + cards/seletores clicáveis) permanece nesta página:
hoje o Dashboard é seu único consumidor — extrair p/ ui/componentes/ seria abstração
antecipada.

Cache: os assemblers (caros) passam por `ui/cache.py`; toda escrita do app chama
`invalidar_leituras()`, então o TTL de 120s é só rede de segurança.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from services.constants import PADROES_DEMANDA
from services.dashboards import PUBLICO_COMPRADOR, PUBLICO_GESTAO
from services.db_functions import listar_requisicoes
from ui.formatos import fmt, fmt_brl, fmt_num, colunas_brl
from ui.tema import paleta_atual
from ui.cache import (
    inventario_cached,
    dashboard_cached,
    visao_compras_cached,
    visao_almoxarifado_cached,
    dados_dashboard_cached,
    inventario_indicadores_cached,
    divergencias_cached,
    rupturas_cached,
)
from ui.componentes.graficos import (
    _donut,
    _barv,
    _barras_agrupadas,
    _bloco_top,
    _mes_label,
    _brl_compact,
    _MESES_PT,
)


def render() -> None:
    st.title(":material/bar_chart: Dashboard — MRO Inventus Power")
    if not inventario_cached():
        st.info("Nenhum item cadastrado. Vá em **:material/add: Cadastro de Itens** para começar.")
        return

    # v4.1.0 — a aba "Gestão" foi extinta; seu conteúdo (2 linhas de distribuição, Top 10
    # consumo, padrões de demanda, requisições por setor/emitente) migrou para o Almoxarifado.
    # v6.0.0 — a aba "KPI Mensal" também foi extinta (ver docstring do módulo).
    tab_comp, tab_almox = st.tabs(
        [
            f":material/person: {PUBLICO_COMPRADOR}",
            ":material/warehouse: Almoxarifado",
        ]
    )
    with tab_comp:
        _render_dash_compras_mro(visao_compras_cached())
    with tab_almox:
        _render_dash_almoxarifado(visao_almoxarifado_cached(), dashboard_cached(PUBLICO_GESTAO))

    # v4.5.0 — modal de drill-down: abre quando um card/gráfico clicável marca o estado.
    if st.session_state.get("_drill_on"):
        _drill_modal()


def _render_dash_almoxarifado(vm, vm_gestao):
    """:material/warehouse: Dashboard do Almoxarifado (§2) — saúde do estoque, prioridades
    do dia, entradas/saídas por período, materiais mais movimentados, setores e histórico.
    v4.1.0: incorpora o conteúdo da antiga aba Gestão (2 linhas de distribuição, Top 10 de
    consumo, padrões de demanda e requisições por setor/emitente).

    v6.0.0 — vira o painel operacional único. SAÍRAM (pedido do usuário): Cobertura Média,
    Distribuição de Itens por Status (donut), Cobertura em Dias e Curva ABC. ENTRARAM: os
    indicadores do ano (KPI Mensal extinto) e 5 blocos da aba Dashboard da Movimentação."""
    from services.drill_down import (
        rows_inventario_filtro,
        rows_mov_periodo,
        rows_requisicoes_dia,
        rows_padrao_demanda,
        rows_mov_mes,
        rows_saidas_item,
        rows_consumo_ytd,
        rows_requisicoes_ano,
        rows_consumo_ytd_tipo,
    )

    PAL = paleta_atual()
    k = vm["kpis"]
    # DF largo (giro, valoração, tendência) — UMA leitura cacheada serve os 3 blocos
    # herdados da Movimentação (tendência, capital parado, maior valor em estoque).
    df_ind = _indicadores_df()
    st.markdown("### :material/warehouse: Dashboard do Almoxarifado · Inventus Power")
    st.caption(
        ":material/ads_click: Clique no 🔍 de qualquer card — ou use o seletor **🔍 Ver itens de:** abaixo de cada gráfico — para abrir a tabela que compõe o número."
    )
    r1 = st.columns(3)
    _card_drill(
        r1[0],
        "📦 Itens cadastrados",
        k["itens_cadastrados"],
        "alm_cad",
        lambda: rows_inventario_filtro("todos"),
    )
    _card_drill(
        r1[1],
        "📥 Entradas hoje",
        k["entradas_hoje"],
        "alm_ent_hoje",
        lambda: rows_mov_periodo("entrada", "hoje"),
    )
    _card_drill(
        r1[2], "📤 Requisições hoje", k["requisicoes_hoje"], "alm_req_hoje", lambda: rows_requisicoes_dia()
    )
    r2 = st.columns(3)
    _card_drill(
        r2[0],
        "🔴 Compra urgente",
        k["compra_urgente"],
        "alm_urg",
        lambda: rows_inventario_filtro("compra_urgente"),
        delta_color="inverse",
    )
    _card_drill(r2[1], "⚠️ Sem giro", k["sem_giro"], "alm_semgiro", lambda: rows_inventario_filtro("sem_mov"))
    _card_drill(
        r2[2],
        "💰 Valor estoque",
        _brl_compact(k["valor_estoque"]),
        "alm_valor",
        lambda: rows_inventario_filtro("com_valor"),
    )

    # ── Ano corrente (YTD) — herdado do extinto KPI Mensal (v6.0.0) ──────────────
    y = vm["ytd"]
    st.divider()
    st.markdown(f"#### :material/calendar_month: Ano corrente ({y['ano']})")
    st.caption(
        f"De 1º de janeiro de {y['ano']} até hoje. Consumo = **saídas reais por requisição** "
        "(ajuste de inventário não entra), valorado pelo preço de referência."
    )
    a1, a2, a3 = st.columns(3)
    _card_drill(
        a1,
        ":material/shopping_cart: Consumido no Ano",
        fmt_brl(y["valor_consumido"]),
        "alm_ytd_valor",
        lambda: rows_consumo_ytd(),
        help="Valor total consumido no ano (saídas reais × preço de referência).",
    )
    _card_drill(
        a2,
        ":material/assignment: Requisições Atendidas no Ano",
        fmt_num(y["n_requisicoes"], casas=0),
        "alm_ytd_req",
        lambda: rows_requisicoes_ano(),
        help="Nº de requisições com consumo real atendidas no ano corrente.",
    )
    _card_drill(
        a3,
        ":material/inventory_2: Itens Movimentados no Ano",
        y["itens_movimentados"],
        "alm_ytd_itens",
        lambda: rows_consumo_ytd(),
        help="Quantos itens diferentes tiveram consumo real no ano.",
    )

    # ── Status dos itens (2 linhas migradas da antiga aba Gestão) ────────────────
    st.divider()
    dg = vm_gestao["distribuicao"]
    total_g = vm_gestao["total"]

    def _pctg(n):
        return f"{round(n / total_g * 100)}%" if total_g else "0%"

    st.markdown("#### :material/inventory_2: Status dos itens (base de compra — só itens com consumo)")
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    _card_drill(
        s1,
        ":material/check_circle: OK",
        dg["ok"],
        "alm_d_ok",
        lambda: rows_inventario_filtro("ok"),
        delta=_pctg(dg["ok"]),
    )
    _card_drill(
        s2,
        "🟡 Atenção",
        dg["atencao"],
        "alm_d_at",
        lambda: rows_inventario_filtro("atencao"),
        delta=_pctg(dg["atencao"]),
        delta_color="off",
    )
    _card_drill(
        s3,
        ":material/warning: Críticos",
        dg["comprar"],
        "alm_d_cr",
        lambda: rows_inventario_filtro("comprar"),
        delta=_pctg(dg["comprar"]),
        delta_color="inverse",
    )
    _card_drill(
        s4,
        "⚪ Sem movimentação",
        dg["sem_mov"],
        "alm_d_sm",
        lambda: rows_inventario_filtro("sem_mov"),
        delta=_pctg(dg["sem_mov"]),
        delta_color="off",
        help="Nunca tiveram saída por requisição — ficam fora da lista de compra.",
    )
    _card_drill(
        s5,
        "🔴 Zerados",
        dg["zerados"],
        "alm_d_ze",
        lambda: rows_inventario_filtro("zerados"),
        delta=_pctg(dg["zerados"]),
        delta_color="inverse",
    )
    _card_drill(
        s6,
        ":material/search: Inventariado",
        f"{dg['inventariado']}/{total_g}",
        "alm_d_inv",
        lambda: rows_inventario_filtro("inventariado"),
        delta=_pctg(dg["inventariado"]),
    )

    sf = vm_gestao["saude_fisica"]
    st.markdown("#### :material/monitor_heart: Status de TODO o material (mesmo sem movimentação)")
    st.caption(
        "Nível físico de **todos** os itens vs. estoque mínimo — inclui os que nunca "
        "tiveram consumo (por isso o total difere da linha acima, que os separa da compra)."
    )
    h1, h2, h3, h4 = st.columns(4)
    _card_drill(
        h1,
        "🟢 OK",
        sf["ok"],
        "alm_f_ok",
        lambda: rows_inventario_filtro("fis_ok"),
        delta=_pctg(sf["ok"]),
        help="Acima do nível confortável (mínimo × 1,2).",
    )
    _card_drill(
        h2,
        "🟡 Atenção",
        sf["atencao"],
        "alm_f_at",
        lambda: rows_inventario_filtro("fis_atencao"),
        delta=_pctg(sf["atencao"]),
        delta_color="off",
        help="Entre o mínimo e mínimo × 1,2.",
    )
    _card_drill(
        h3,
        "🔴 Críticos",
        sf["critico"],
        "alm_f_cr",
        lambda: rows_inventario_filtro("fis_critico"),
        delta=_pctg(sf["critico"]),
        delta_color="inverse",
        help="No/abaixo do mínimo, mas ainda com saldo (> 0).",
    )
    _card_drill(
        h4,
        "⚫ Zerados",
        sf["zerado"],
        "alm_f_ze",
        lambda: rows_inventario_filtro("fis_zerado"),
        delta=_pctg(sf["zerado"]),
        delta_color="inverse",
        help="Estoque atual = 0.",
    )

    # ── Consumo por tipo (do KPI Mensal) + Tendência (da Movimentação) — v6.0.0 ──
    # Colunas iguais e gráficos da MESMA altura: são duas leituras do consumo lado a lado.
    st.divider()
    s1c, s2c = st.columns(2)
    with s1c:
        with st.container(border=True):
            st.markdown("##### :material/donut_large: Consumo por Tipo de Material")
            st.caption(f"Valor consumido em {y['ano']}, agregado por tipo/categoria do material.")
            comp = y["composicao_tipo"]
            if comp:
                st.plotly_chart(
                    _donut(
                        [x["tipo"] for x in comp], [x["valor"] for x in comp], height=300, fmt=_brl_compact
                    ),
                    width="stretch",
                    config={"displayModeBar": False},
                )
                _drill_select(
                    "alm_ch_comp",
                    [x["tipo"] for x in comp if x["tipo"] != "Outros"],
                    lambda l: f"Consumo YTD · {l}",
                    lambda l: rows_consumo_ytd_tipo(l),
                )
            else:
                st.caption("Sem consumo valorado no ano.")
    with s2c:
        with st.container(border=True):
            _bloco_tendencia_consumo(df_ind)

    # ── Entradas / Saídas com o período explícito (hoje/semana/mês) ──────────────
    _hoje = date.today()
    _seg = _hoje - timedelta(days=_hoje.weekday())  # segunda-feira da semana atual
    _dom = _seg + timedelta(days=6)  # domingo
    _wk = _hoje.isocalendar().week
    _hoje_str = _hoje.strftime("%d/%m/%Y")
    _sem_str = f"WK {_wk} ({_seg.strftime('%d/%m')}–{_dom.strftime('%d/%m')})"
    _mes_str = f"{_MESES_PT[_hoje.month].capitalize()}/{_hoje.year}"
    st.divider()
    ea, sa = st.columns(2)
    with ea:
        with st.container(border=True):
            st.markdown("#### 📥 Entradas")
            st.caption(f"Hoje **{_hoje_str}** · Semana **{_sem_str}** · Mês **{_mes_str}**")
            en = vm["entradas"]
            e1, e2, e3 = st.columns(3)
            _card_drill(
                e1,
                "Hoje",
                en["hoje"]["n"],
                "alm_e_h",
                lambda: rows_mov_periodo("entrada", "hoje"),
                help=f"Recebimentos de hoje ({_hoje_str}).",
            )
            _card_drill(
                e2,
                "Semana",
                en["semana"]["n"],
                "alm_e_s",
                lambda: rows_mov_periodo("entrada", "semana"),
                help=f"Recebimentos da semana atual — {_sem_str}.",
            )
            _card_drill(
                e3,
                "Mês",
                en["mes"]["n"],
                "alm_e_m",
                lambda: rows_mov_periodo("entrada", "mes"),
                help=f"Recebimentos do mês atual — {_mes_str}.",
            )
    with sa:
        with st.container(border=True):
            st.markdown("#### 📤 Saídas (requisições)")
            st.caption(f"Hoje **{_hoje_str}** · Semana **{_sem_str}** · Mês **{_mes_str}**")
            sd = vm["saidas"]
            x1, x2, x3 = st.columns(3)
            _card_drill(
                x1,
                "Hoje",
                sd["hoje"]["n"],
                "alm_x_h",
                lambda: rows_mov_periodo("saida", "hoje"),
                help=f"Saídas por requisição de hoje ({_hoje_str}).",
            )
            _card_drill(
                x2,
                "Semana",
                sd["semana"]["n"],
                "alm_x_s",
                lambda: rows_mov_periodo("saida", "semana"),
                help=f"Saídas da semana atual — {_sem_str}.",
            )
            _card_drill(
                x3,
                "Mês",
                sd["mes"]["n"],
                "alm_x_m",
                lambda: rows_mov_periodo("saida", "mes"),
                help=f"Saídas do mês atual — {_mes_str}.",
            )

    tc1, tc2 = st.columns(2)
    with tc1:
        _bloco_top(
            "📥 Top materiais recebidos (mês)",
            vm["top_recebidos"],
            lambda x: f"{x['pn']} — {(x['item'] or '')[:26]}",
            "q",
            lambda v: f"{v:g}",
        )
    with tc2:
        _bloco_top(
            "📤 Materiais mais consumidos (mês)",
            vm["mais_consumidos"],
            lambda x: f"{x['pn']} — {(x['item'] or '')[:26]}",
            "q",
            lambda v: f"{v:g}",
        )
    _bloco_top("🏭 Setores que mais retiram", vm["setores"], lambda x: x["setor"], "n", lambda v: f"{int(v)}")

    # ── Top 10 de consumo + Padrões de demanda (migrado da antiga aba Gestão) ────
    st.divider()
    colA, colB = st.columns(2)
    with colA:
        with st.container(border=True):
            st.markdown("#### :material/trending_down: Top 10 Itens com mais consumo no mês anterior")
            dados = dados_dashboard_cached()
            st.caption(f"Referência: consumo real de {dados['kpis'].get('periodo_abc', '—')}.")
            df_abc = pd.DataFrame(dados["abc"])
            if not df_abc.empty:
                import plotly.graph_objects as go

                df_abc = df_abc.sort_values("total_saida", ascending=True)
                df_abc["lbl"] = df_abc.apply(
                    lambda x: f"{x['part_number']} • {str(x['nome_item'])[:15]}", axis=1
                )  # top10-almox
                fig = go.Figure(
                    data=[
                        go.Bar(
                            y=df_abc["lbl"],
                            x=df_abc["total_saida"],
                            orientation="h",
                            marker=dict(color=PAL["accent"], line=dict(width=1, color=PAL["accent_borda"])),
                            text=df_abc["total_saida"].apply(lambda x: f"{int(x)}"),
                            textposition="outside",
                            textfont=dict(size=11, color=PAL["texto_suave"]),
                        )
                    ]
                )
                fig.update_layout(
                    template=PAL["plotly_template"],
                    height=320,
                    margin=dict(l=0, r=20, t=10, b=0),
                    paper_bgcolor=PAL["paper_bg"],
                    plot_bgcolor=PAL["plot_bg"],
                    showlegend=False,
                    font=dict(family="Inter", color=PAL["texto"]),
                    xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(color=PAL["texto_suave"])),
                    yaxis=dict(showgrid=False, tickfont=dict(size=11, color=PAL["texto"])),
                )
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                _drill_select(
                    "alm_ch_top10",
                    list(df_abc["part_number"]),
                    lambda l: f"Saídas recentes (30d) · {l}",
                    lambda l: rows_saidas_item(l),
                    display=list(df_abc["lbl"]),
                )
            else:
                st.info("Sem consumo registrado no período.")
    with colB:
        with st.container(border=True):
            st.markdown("#### :material/science: Padrões de demanda")
            st.caption(
                "Cada item é lido por duas coisas: **com que regularidade** ele sai e "
                "**o quanto o tamanho de cada saída varia**. Juntas, indicam o quão "
                "previsível é repor cada material. O número na coluna = quantos itens."
            )
            ordem = ["Suave", "Intermitente", "Errático", "Irregular", "Poucos dados"]
            dem = vm_gestao["demanda"]
            dados_dem = [(p, dem.get(p, 0)) for p in ordem if dem.get(p, 0)]
            if dados_dem:
                _plabels = [p for p, _ in dados_dem]
                st.plotly_chart(
                    _barv(
                        _plabels, [n for _, n in dados_dem], textos=[f"{n}" for _, n in dados_dem], height=220
                    ),
                    width="stretch",
                    config={"displayModeBar": False},
                )
                _drill_select(
                    "alm_ch_dem",
                    _plabels,
                    lambda l: f"Padrão de demanda · {l}",
                    lambda l: rows_padrao_demanda(l),
                )
            else:
                st.caption("Ainda sem consumo real suficiente para classificar.")

            _expl = {v["label"]: (v["emoji"], v["explicacao"]) for v in PADROES_DEMANDA.values()}
            st.markdown("**O que cada padrão significa:**")
            for p in ["Suave", "Intermitente", "Errático", "Irregular"]:
                emoji, exp = _expl[p]
                n = dem.get(p, 0)
                st.markdown(
                    f"{emoji} **{p}** — {exp} "
                    f"<span style='opacity:.65'>· {n} {'item' if n == 1 else 'itens'}</span>",
                    unsafe_allow_html=True,
                )

            xyz = vm_gestao["xyz"]
            if xyz:
                st.caption(
                    "**XYZ** mede o quanto o consumo varia de mês a mês "
                    "(X estável · Y variável · Z errático — baixa confiança com poucos meses): "
                    f"X {xyz.get('X', 0)} · Y {xyz.get('Y', 0)} · Z {xyz.get('Z', 0)}."
                )

    with st.container(border=True):
        st.markdown("#### :material/factory: Requisições por Setor & :material/person: Top Emitentes")
        reqs = listar_requisicoes(limit=500)
        if reqs:
            df_r = pd.DataFrame(reqs)
            colS, colE = st.columns(2)
            with colS:
                if "setor" in df_r.columns and not df_r["setor"].isna().all():
                    dc = df_r["setor"].value_counts().head(7).reset_index()
                    dc.columns = ["Setor", "Qtd"]
                    st.bar_chart(dc.set_index("Setor"), color=PAL["accent"], height=250)
                else:
                    st.caption("Sem dados de setor preenchidos.")
            with colE:
                if "emitente" in df_r.columns and not df_r["emitente"].isna().all():
                    dc = df_r["emitente"].value_counts().head(10).reset_index()
                    dc.columns = ["Emitente", "Qtd"]
                    st.dataframe(
                        dc,
                        width="stretch",
                        hide_index=True,
                        height=250,
                        column_config={
                            "Qtd": st.column_config.ProgressColumn(
                                "Qtd",
                                format="%d",
                                min_value=0,
                                max_value=int(dc["Qtd"].max()) if not dc.empty else 100,
                                color=PAL["accent"],
                            )
                        },
                    )
                else:
                    st.caption("Sem dados de emitente preenchidos.")
        else:
            st.caption("Aguardando histórico de requisições.")

    st.divider()
    with st.container(border=True):
        st.markdown("#### 📈 Histórico mensal — Entradas × Saídas")
        h = vm["historico_mensal"]
        if h["meses"]:
            st.plotly_chart(
                _barras_agrupadas(
                    [_mes_label(m) for m in h["meses"]],
                    [("Entradas", h["entradas"], PAL["positivo"]), ("Saídas", h["saidas"], PAL["negativo"])],
                    mostrar_valores=True,
                ),
                width="stretch",
                config={"displayModeBar": False},
            )
            _drill_select(
                "alm_ch_hist",
                h["meses"],
                lambda l: f"Movimentações de {_mes_label(l)}",
                lambda l: rows_mov_mes(l),
                display=[_mes_label(m) for m in h["meses"]],
            )
        else:
            st.caption("Sem movimentações registradas.")

    # ── Blocos herdados da aba Dashboard da Movimentação (v6.0.0) ───────────────
    st.divider()
    st.markdown("### :material/payments: Capital parado & falhas de abastecimento")
    st.caption(
        "Valores são **estimativas** pelo **último preço** conhecido (SCM; na falta, "
        "último preço de PO/SC7) — não substituem o custo contábil."
    )
    cp1, cp2 = st.columns(2)
    with cp1:
        with st.container(border=True):
            _bloco_capital_parado(df_ind)
    with cp2:
        with st.container(border=True):
            _bloco_maior_valor_estoque(df_ind)

    with st.container(border=True):
        _bloco_divergencias()

    with st.container(border=True):
        _bloco_ruptura()

    st.caption(
        ":material/map: **Mapa do Almoxarifado** (prateleiras por status de cor) fica "
        "para quando houver um modelo de localização/posição — hoje o local é texto livre."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Blocos herdados da aba Dashboard da Movimentação (v6.0.0)
# ══════════════════════════════════════════════════════════════════════════════
#
# Migração FIEL: mesmas fontes de dado (`exportar_inventario_df`,
# `obter_analitico_divergencias`, `obter_analitico_rupturas`), mesmos textos e mesmos
# recortes (90 d, giro 0, top 8). Só mudou o container que os hospeda e o cache —
# como o Almoxarifado é a página mais visitada, as leituras passam por `ui/cache.py`.
# São funções module-level para manter `_render_dash_almoxarifado` legível.

_COLS_CAPITAL = ["PN", "Nome", "UN", "Estoque Atual", "Valor em Estoque"]


def _indicadores_df():
    """DF de indicadores do inventário (cacheado). DF vazio se o cálculo falhar —
    um bloco financeiro não pode derrubar o dashboard inteiro."""
    try:
        return inventario_indicadores_cached()
    except Exception as e:  # noqa: BLE001 — a falha é exibida, não engolida
        st.error(f"Erro ao calcular indicadores do inventário: {e}")
        return pd.DataFrame()


def _tabela_valor(df, colunas):
    """Tabela de ranking por valor, com o R$ já no padrão pt-BR (v6.0.0). A ordem vem
    pronta do `nlargest`, então virar texto não custa ordenação útil."""
    st.dataframe(
        colunas_brl(df[colunas].copy(), "Valor em Estoque"),
        hide_index=True,
        width="stretch",
        column_config={"Valor em Estoque": st.column_config.TextColumn("Valor em Estoque")},
    )


def _bloco_tendencia_consumo(df_ind, height=300):
    """Tendência de consumo: 30 d vs. os 30 d anteriores, item a item (v4.1.0).

    v6.0.0 — vira UM gráfico, com a mesma altura do donut de Consumo por Tipo ao lado.
    Antes eram três `st.metric` soltos: ocupavam meia coluna e deixavam o resto vazio,
    além de dar contagem sem proporção. Três barras coloridas resolvem as duas coisas —
    e sem componente novo, é o `_barv` de sempre. Cálculo inalterado: a coluna
    `Tendência` de `exportar_inventario_df()` (janelas de 30 d, faixa de ±15%)."""
    PAL = paleta_atual()
    st.markdown("##### :material/psychology: Tendência de Consumo")
    st.caption("Consumo dos últimos 30 dias vs. os 30 anteriores, item a item (faixa de ±15%).")
    if df_ind.empty or "Tendência" not in df_ind.columns:
        st.caption("Sem dados suficientes.")
        return

    vc = df_ind["Tendência"].value_counts()
    alta, estavel, queda = (int(vc.get(k, 0)) for k in ("Alta", "Estável", "Queda"))
    total = alta + estavel + queda
    if not total:
        st.caption("Nenhum item com consumo nas duas janelas de 30 dias — sem tendência a comparar.")
        return

    valores = [alta, estavel, queda]
    st.plotly_chart(
        _barv(
            ["Em alta", "Estável", "Em queda"],
            valores,
            textos=[f"{n} · {n / total * 100:.0f}%" for n in valores],
            # Alta em vermelho: demanda subindo é o que pressiona a reposição.
            cor=[PAL["negativo"], PAL["neutro"], PAL["positivo"]],
            height=height,
        ),
        width="stretch",
        config={"displayModeBar": False},
    )
    st.caption(f"{fmt_num(total, casas=0)} itens com consumo comparável nas duas janelas.")


def _bloco_capital_parado(df_ind):
    """Top capital parado: maior valor em estoque COM giro 0 — dinheiro sem saída."""
    st.markdown("##### :material/ac_unit: Top Capital Parado")
    st.caption("Maior valor em estoque **com giro 0** — dinheiro parado, candidato a reduzir/realocar.")
    if df_ind.empty or not {"Valor em Estoque", "Giro(anual)"} <= set(df_ind.columns):
        st.caption("Sem dados de valoração no período.")
        return
    cols = [c for c in _COLS_CAPITAL if c in df_ind.columns]
    parado = df_ind[(df_ind["Giro(anual)"] == 0) & (df_ind["Valor em Estoque"] > 0)].nlargest(
        8, "Valor em Estoque"
    )
    if parado.empty:
        st.success(":material/check_circle: Nenhum item de valor relevante totalmente parado.")
        return
    _tabela_valor(parado, cols)


def _bloco_maior_valor_estoque(df_ind):
    """Maior valor em estoque: os itens que mais imobilizam capital hoje (com ou sem giro)."""
    st.markdown("##### :material/savings: Maior Valor em Estoque")
    st.caption("Itens que mais imobilizam capital hoje (estoque atual × preço de referência).")
    if df_ind.empty or "Valor em Estoque" not in df_ind.columns:
        st.caption("Sem dados de valoração no período.")
        return
    cols = [c for c in _COLS_CAPITAL if c in df_ind.columns]
    top = df_ind[df_ind["Valor em Estoque"] > 0].nlargest(8, "Valor em Estoque")
    if top.empty:
        st.caption("Nenhum item com valor de estoque conhecido.")
        return
    _tabela_valor(top, cols)


def _bloco_divergencias():
    """Top itens com divergências: ajustes manuais frequentes (últimos 90 d)."""
    PAL = paleta_atual()
    st.markdown("#### :material/balance: Top Itens com Divergências")
    st.caption("Ajustes manuais frequentes (sem Req/SC) indicam erro de processo. Últimos 90 dias.")
    df_div = divergencias_cached(days=90)
    if df_div.empty:
        st.success(":material/check_circle: Nenhuma divergência significativa.")
        return
    vis = df_div.copy()
    vis.columns = ["PN", "Item", "Nº Ajustes", "Vol. Ajustado"]
    st.dataframe(
        vis,
        width="stretch",
        hide_index=True,
        height=320,
        column_config={
            "Nº Ajustes": st.column_config.ProgressColumn(
                "Freq.", format="%d", min_value=0, max_value=int(vis["Nº Ajustes"].max()), color=PAL["accent"]
            ),
            "Vol. Ajustado": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def _bloco_ruptura():
    """Ruptura de estoque: itens que zeraram durante uma requisição (últimos 90 d)."""
    PAL = paleta_atual()
    st.markdown("#### :material/emergency: Ruptura de Estoque (Impacto na Operação)")
    st.caption(
        "Itens que zeraram o estoque durante uma requisição nos últimos 90 dias. "
        "Indica falha de abastecimento."
    )
    df_rup = rupturas_cached(days=90)
    if df_rup.empty:
        st.success(
            ":material/check_circle: **Operação Fluida:** Nenhuma ruptura registrada no período. "
            "O estoque atendeu todas as requisições."
        )
        return

    vis = df_rup.copy()
    vis["ultima_ocorrencia"] = vis["ultima_ocorrencia"].apply(fmt)
    vis = vis.rename(
        columns={
            "part_number": "PN",
            "nome_item": "Item Crítico",
            "qtd_rupturas": "Qtd. Rupturas",
            "ultima_ocorrencia": "Última Falha",
        }
    )

    def _realce(val):
        if isinstance(val, (int, float)) and val >= 3:
            return f"color: {PAL['negativo']}; font-weight: bold;"
        return ""

    st.dataframe(
        vis.style.map(_realce, subset=["Qtd. Rupturas"]),
        width="stretch",
        hide_index=True,
        height=250,
        column_config={
            "Qtd. Rupturas": st.column_config.ProgressColumn(
                "Freq. Ruptura",
                format="%d",
                min_value=0,
                max_value=int(vis["Qtd. Rupturas"].max()),
                color=PAL["negativo"],
            ),
            "Última Falha": st.column_config.TextColumn(width="small"),
        },
    )
    st.warning(
        ":material/lightbulb: **Ação Recomendada:** Revise o **Estoque Mínimo** e o "
        "**Lead Time** destes itens imediatamente para evitar paradas de linha."
    )


def _render_dash_compras_mro(vm):
    """:material/shopping_cart: Dashboard do Comprador (§1) — material MRO.

    v5.9.0: reduzido a **4 cards + 5 gráficos** (pedido do usuário). Saíram os blocos
    redundantes ("Setores" repetia o Ranking de Departamentos; "Comparativo por
    Comprador" repetia o gráfico de barras) e os que ninguém lia (aging, SC→PO,
    tendência semanal, status dos POs, itens por pedido, lead time por fornecedor).
    Clicável (cards com 🔍 + seletor abaixo de cada gráfico)."""
    from services.drill_down import (
        rows_itens_em_aberto,
        rows_fornecedores_aberto,
        rows_scs_status,
        rows_scs_mes,
    )

    k = vm["kpis"]
    ch, cw = st.columns([3, 1])
    ch.markdown("### :material/shopping_cart: Dashboard do Comprador · Inventus Power")
    cw.markdown(
        f"<div style='text-align:right'><b>WK {vm['wk']}</b> · {vm['ano']}</div>", unsafe_allow_html=True
    )
    ua = vm.get("ultima_atualizacao")
    st.caption(
        f":material/update: Última atualização do Relatório de SCs: **{fmt(ua) if ua else '—'}** · "
        f"escopo do ano de {vm['ano']}, só material MRO. "
        ":material/ads_click: cards com 🔍 e seletor abaixo de cada gráfico."
    )

    # ── 4 cards ──
    m1, m2, m3, m4 = st.columns(4)
    _card_drill(
        m1,
        ":material/request_quote: Itens em Aberto",
        k["itens_abertos"],
        "cmp_cot",
        lambda: rows_scs_status("Em Cotação"),
        help="Linhas de item de SC cuja SC está em Cotação.",
    )
    _card_drill(
        m2,
        ":material/receipt_long: SCs em Aberto",
        k["scs_abertas"],
        "cmp_scab",
        lambda: rows_itens_em_aberto(),
        help="SCs distintas com ao menos um item MRO em Cotação.",
    )
    m3.metric(
        ":material/shopping_cart_checkout: QTY Pedidos Emitidos",
        k["pos_emitidos"],
        help="Pedidos de Compra distintos emitidos no ano.",
    )
    m4.metric(
        ":material/inventory: QTY Itens com P.O.",
        k["itens_com_po"],
        help="Linhas de item de SC que já têm Pedido de Compra.",
    )

    # ── Gráficos 1 e 2: Qtd. de Itens por Mês · Qtd. de SCs por Mês ──
    st.divider()
    vmn = vm["volume_mensal"]
    _meses_lbl = [_mes_label(m) for m in vmn["meses"]]
    a1, a2 = st.columns(2)
    with a1:
        with st.container(border=True):
            st.markdown("##### :material/bar_chart: Qtd. de Itens por Mês (SCs)")
            if vmn["meses"]:
                st.plotly_chart(
                    _barv(_meses_lbl, vmn["itens"]), width="stretch", config={"displayModeBar": False}
                )
                _drill_select(
                    "cmp_itmes",
                    vmn["meses"],
                    lambda l: f"SCs de {_mes_label(l)}",
                    lambda l: rows_scs_mes(l),
                    display=_meses_lbl,
                )
            else:
                st.caption("Sem SCs no ano.")
    with a2:
        with st.container(border=True):
            st.markdown("##### :material/bar_chart: Qtd. de SCs por Mês")
            if vmn["meses"]:
                st.plotly_chart(
                    _barv(_meses_lbl, vmn["scs"]), width="stretch", config={"displayModeBar": False}
                )
                _drill_select(
                    "cmp_scmes",
                    vmn["meses"],
                    lambda l: f"SCs de {_mes_label(l)}",
                    lambda l: rows_scs_mes(l),
                    display=_meses_lbl,
                )
            else:
                st.caption("Sem SCs no ano.")

    # ── Gráficos 3 e 4: Dispêndio Mensal · Ranking de Dispêndio por Setor ──
    d1, d2 = st.columns(2)
    with d1:
        with st.container(border=True):
            st.markdown("##### :material/payments: Dispêndio Mensal MRO")
            dm = vm["dispendio_mensal"]
            if dm["meses"]:
                # Rótulo compacto na barra ("R$ 34,0k") e valor cheio no hover — antes a
                # barra escrevia o float cru ("34012.0").
                st.plotly_chart(
                    _barv(
                        [_mes_label(m) for m in dm["meses"]],
                        dm["valores"],
                        textos=[_brl_compact(v) for v in dm["valores"]],
                        hover=[fmt_brl(v) for v in dm["valores"]],
                    ),
                    width="stretch",
                    config={"displayModeBar": False},
                )
                st.caption(
                    "Valor dos itens no **mês do Pedido de Compra** (`data_po`) — "
                    "item ainda sem PO não entra."
                )
            else:
                st.caption("Sem dispêndio no ano.")
    with d2:
        with st.container(border=True):
            st.markdown("##### :material/apartment: Ranking de Dispêndio por Setor")
            ds = vm["dispendio_setor"]
            if ds:
                st.plotly_chart(
                    _barv(
                        [x["setor"] for x in ds],
                        [x["valor"] for x in ds],
                        textos=[_brl_compact(x["valor"]) for x in ds],
                        hover=[fmt_brl(x["valor"]) for x in ds],
                    ),
                    width="stretch",
                    config={"displayModeBar": False},
                )
                st.caption(
                    "Mesmo valor do gráfico ao lado, atribuído ao setor que **de fato consome** "
                    "o item (consumo real) — item sem consumo fica fora."
                )
            else:
                st.caption("Sem dispêndio atribuível a setor.")

    # ── Gráfico 5: Fornecedores por valor ──
    with st.container(border=True):
        _bloco_top(
            "🏭 Fornecedores por Valor",
            vm["fornecedores_top"],
            lambda x: x["fornecedor"][:22],
            "valor",
            lambda v: _brl_compact(v),
        )
        if vm["fornecedores_top"]:
            _drill_select(
                "cmp_forn",
                [x["fornecedor"] for x in vm["fornecedores_top"]],
                lambda l: "Fornecedores (SCs abertas por valor)",
                lambda l: rows_fornecedores_aberto(),
            )


# v5.9.0 — `_render_dash_comprador` foi removido: era código morto (nenhum chamador
# desde que a aba do Comprador passou a usar `_render_dash_compras_mro`). O assembler
# que ele lia, `montar_visao_comprador()`, PERMANECE — `montar_visao_executiva()` o usa.


def _clear_drill():
    for _k in ("_drill_titulo", "_drill_df", "_drill_on", "_chart_sig"):
        st.session_state.pop(_k, None)


@st.dialog("🔍 Detalhes", width="large", on_dismiss=_clear_drill)
def _drill_modal():
    """Modal reutilizável de drill-down (v4.5.0). Lê título/df de session_state para
    persistir entre reruns (busca dentro do modal não o fecha)."""
    titulo = st.session_state.get("_drill_titulo", "Detalhes")
    _dialog_drill_down(st.session_state.get("_drill_df"), titulo)


def _abrir_drill(titulo, df):
    st.session_state["_drill_titulo"] = titulo
    st.session_state["_drill_df"] = df
    st.session_state["_drill_on"] = True


def _drill_btn(dkey: str, provider, titulo: str) -> None:
    """Botão 🔍: ao clicar, computa o provider (lazy) e abre o modal de drill-down."""
    if st.button("🔍", key=f"drill_{dkey}", help="Ver os itens que compõem este número"):
        _abrir_drill(titulo, provider())


def _card_drill(col, label, valor, dkey, provider, *, help=None, delta=None, delta_color="normal") -> None:
    """Métrica + botão 🔍 de drill-down na mesma coluna."""
    with col:
        st.metric(label, valor, delta=delta, delta_color=delta_color, help=help)
        _drill_btn(dkey, provider, label)


def _drill_select(dkey, labels, titulo_fn, provider_fn, display=None):
    """Plano B (confiável): seletor '🔍 Ver itens de:' ao lado do gráfico. Abre o drill
    quando a escolha MUDA — não depende de clique na barra/fatia do Plotly (que o
    Streamlit não captura de forma confiável). Sem loop de reabertura."""
    opts = ["—"] + list(labels)
    disp = ["—"] + list(display if display is not None else labels)
    escolha = st.selectbox("🔍 Ver itens de:", disp, key=f"sd_{dkey}")
    prev = f"sdp_{dkey}"
    if escolha != st.session_state.get(prev):
        st.session_state[prev] = escolha
        if escolha != "—":
            lab = opts[disp.index(escolha)]
            _abrir_drill(titulo_fn(lab), provider_fn(lab))
            st.rerun()


def _dialog_drill_down(df: pd.DataFrame, titulo: str = "Detalhes") -> None:
    """Renderiza um dialog com tabela, busca e export. Reutilizável para qualquer DataFrame."""
    if not isinstance(df, pd.DataFrame):
        st.error("Dados não disponíveis")
        return

    if df.empty:
        st.info(f"Sem registros para '{titulo}'.")
        return

    st.caption(f"{len(df):,} registros".replace(",", "."))

    # Buscador simples (filtro global)
    busca = st.text_input("🔍 Buscar", key=f"search_{titulo}")
    if busca:
        mask = df.astype(str).apply(lambda x: x.str.contains(busca, case=False, na=False)).any(axis=1)
        df_filtrado = df[mask]
    else:
        df_filtrado = df

    # Tabela interativa
    st.dataframe(df_filtrado, width="stretch")

    # Botão de download (CSV)
    csv = df_filtrado.to_csv(index=False)
    st.download_button(
        label="📥 Baixar CSV",
        data=csv,
        file_name=f"{titulo}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key=f"download_{titulo}",
    )
