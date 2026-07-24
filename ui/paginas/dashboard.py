"""Página Dashboard (v5.3.0 / F4a) — 3 abas por público (Comprador/Almoxarifado/Mensal).

Migrada do bloco inline do `app.py`. Os assemblers seguem puros em
`services/dashboards.py`; aqui é só o desenho. Os construtores de gráfico foram para
`ui/componentes/graficos.py` (compartilhados com Ficha 360/Movimentação na F4b).

O cluster de DRILL-DOWN (modal + cards/seletores clicáveis) permanece nesta página:
hoje o Dashboard é seu único consumidor — extrair p/ ui/componentes/ seria abstração
antecipada. Se a Ficha 360/Movimentação precisarem dele na F4b, promove-se então.

Cache: os assemblers (caros) passam por `ui/cache.py`; toda escrita do app chama
`invalidar_leituras()`, então o TTL de 120s é só rede de segurança.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from services.constants import PADROES_DEMANDA
from services.dashboards import PUBLICO_COMPRADOR, PUBLICO_GESTAO, PUBLICO_EXECUTIVO
from services.db_functions import listar_requisicoes
from ui.formatos import fmt
from ui.tema import paleta_atual
from ui.cache import (
    inventario_cached, dashboard_cached, visao_compras_cached,
    visao_almoxarifado_cached, dados_dashboard_cached,
)
from ui.componentes.graficos import (
    _barh, _donut, _barv, _linhas, _barras_agrupadas, _bloco_top,
    _mes_label, _brl_compact, _MESES_PT,
)


def render() -> None:
    st.title(":material/bar_chart: Dashboard — MRO Inventus Power")
    if not inventario_cached():
        st.info("Nenhum item cadastrado. Vá em **:material/add: Gerenciar Itens** para começar.")
        return

    # v4.1.0 — a aba "Gestão" foi extinta; seu conteúdo (2 linhas de distribuição, Top 10
    # consumo, padrões de demanda, requisições por setor/emitente) migrou para o Almoxarifado.
    tab_comp, tab_almox, tab_mensal = st.tabs(
        [f":material/person: {PUBLICO_COMPRADOR}",
         ":material/warehouse: Almoxarifado",
         f":material/calendar_month: {PUBLICO_EXECUTIVO}"])
    with tab_comp:
        _render_dash_compras_mro(visao_compras_cached())
    with tab_almox:
        _render_dash_almoxarifado(visao_almoxarifado_cached(), dashboard_cached(PUBLICO_GESTAO))
    with tab_mensal:
        _render_dash_executivo(dashboard_cached(PUBLICO_EXECUTIVO))

    # v4.5.0 — modal de drill-down: abre quando um card/gráfico clicável marca o estado.
    if st.session_state.get("_drill_on"):
        _drill_modal()

def _dash_fmt_brl(v):
    """Formata número como R$ pt-BR (milhar com ponto, decimal com vírgula)."""
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ —"


def _render_dash_almoxarifado(vm, vm_gestao):
    """:material/warehouse: Dashboard do Almoxarifado (§2) — saúde do estoque, prioridades
    do dia, entradas/saídas por período, materiais mais movimentados, setores e histórico.
    v4.1.0: incorpora o conteúdo da antiga aba Gestão (2 linhas de distribuição, Top 10 de
    consumo, padrões de demanda e requisições por setor/emitente)."""
    from services.drill_down import (rows_inventario_filtro, rows_mov_periodo,
                                     rows_requisicoes_dia, rows_cobertura_faixa,
                                     rows_padrao_demanda, rows_abc_classe,
                                     rows_mov_mes, rows_saidas_item)
    PAL = paleta_atual()
    k = vm["kpis"]
    st.markdown("### :material/warehouse: Dashboard do Almoxarifado · Inventus Power")
    st.caption(":material/ads_click: Clique no 🔍 de qualquer card — ou use o seletor **🔍 Ver itens de:** abaixo de cada gráfico — para abrir a tabela que compõe o número.")
    r1 = st.columns(3)
    _card_drill(r1[0], "📦 Itens cadastrados", k["itens_cadastrados"], "alm_cad",
                lambda: rows_inventario_filtro("todos"))
    _card_drill(r1[1], "📥 Entradas hoje", k["entradas_hoje"], "alm_ent_hoje",
                lambda: rows_mov_periodo("entrada", "hoje"))
    _card_drill(r1[2], "📤 Requisições hoje", k["requisicoes_hoje"], "alm_req_hoje",
                lambda: rows_requisicoes_dia())
    r2 = st.columns(4)
    _card_drill(r2[0], "🔴 Compra urgente", k["compra_urgente"], "alm_urg",
                lambda: rows_inventario_filtro("compra_urgente"), delta_color="inverse")
    _card_drill(r2[1], "⚠️ Sem giro", k["sem_giro"], "alm_semgiro",
                lambda: rows_inventario_filtro("sem_mov"))
    _card_drill(r2[2], "💰 Valor estoque", _brl_compact(k["valor_estoque"]), "alm_valor",
                lambda: rows_inventario_filtro("com_valor"))
    _card_drill(r2[3], "📊 Cobertura média",
                f"{k['cobertura_media']}d" if k["cobertura_media"] is not None else "—",
                "alm_cobmed", lambda: rows_inventario_filtro("cobertura"))

    # ── Status dos itens (2 linhas migradas da antiga aba Gestão) ────────────────
    st.divider()
    dg = vm_gestao["distribuicao"]; total_g = vm_gestao["total"]
    def _pctg(n): return f"{round(n / total_g * 100)}%" if total_g else "0%"
    st.markdown("#### :material/inventory_2: Status dos itens (base de compra — só itens com consumo)")
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    _card_drill(s1, ":material/check_circle: OK", dg["ok"], "alm_d_ok",
                lambda: rows_inventario_filtro("ok"), delta=_pctg(dg["ok"]))
    _card_drill(s2, "🟡 Atenção", dg["atencao"], "alm_d_at",
                lambda: rows_inventario_filtro("atencao"), delta=_pctg(dg["atencao"]), delta_color="off")
    _card_drill(s3, ":material/warning: Críticos", dg["comprar"], "alm_d_cr",
                lambda: rows_inventario_filtro("comprar"), delta=_pctg(dg["comprar"]), delta_color="inverse")
    _card_drill(s4, "⚪ Sem movimentação", dg["sem_mov"], "alm_d_sm",
                lambda: rows_inventario_filtro("sem_mov"), delta=_pctg(dg["sem_mov"]), delta_color="off",
                help="Nunca tiveram saída por requisição — ficam fora da lista de compra.")
    _card_drill(s5, "🔴 Zerados", dg["zerados"], "alm_d_ze",
                lambda: rows_inventario_filtro("zerados"), delta=_pctg(dg["zerados"]), delta_color="inverse")
    _card_drill(s6, ":material/search: Inventariado", f"{dg['inventariado']}/{total_g}", "alm_d_inv",
                lambda: rows_inventario_filtro("inventariado"), delta=_pctg(dg["inventariado"]))

    sf = vm_gestao["saude_fisica"]
    st.markdown("#### :material/monitor_heart: Status de TODO o material (mesmo sem movimentação)")
    st.caption("Nível físico de **todos** os itens vs. estoque mínimo — inclui os que nunca "
               "tiveram consumo (por isso o total difere da linha acima, que os separa da compra).")
    h1, h2, h3, h4 = st.columns(4)
    _card_drill(h1, "🟢 OK", sf["ok"], "alm_f_ok", lambda: rows_inventario_filtro("fis_ok"),
                delta=_pctg(sf["ok"]), help="Acima do nível confortável (mínimo × 1,2).")
    _card_drill(h2, "🟡 Atenção", sf["atencao"], "alm_f_at", lambda: rows_inventario_filtro("fis_atencao"),
                delta=_pctg(sf["atencao"]), delta_color="off", help="Entre o mínimo e mínimo × 1,2.")
    _card_drill(h3, "🔴 Críticos", sf["critico"], "alm_f_cr", lambda: rows_inventario_filtro("fis_critico"),
                delta=_pctg(sf["critico"]), delta_color="inverse", help="No/abaixo do mínimo, mas ainda com saldo (> 0).")
    _card_drill(h4, "⚫ Zerados", sf["zerado"], "alm_f_ze", lambda: rows_inventario_filtro("fis_zerado"),
                delta=_pctg(sf["zerado"]), delta_color="inverse", help="Estoque atual = 0.")

    st.divider()
    s1c, s2c, s3c = st.columns(3)
    with s1c:
        with st.container(border=True):
            st.markdown("##### :material/donut_large: Distribuição de Itens por Status")
            d = vm["distribuicao"]
            _dlabels = ["OK", "Atenção", "Comprar", "Sem giro"]
            st.plotly_chart(
                _donut(_dlabels, [d["ok"], d["atencao"], d["comprar"], d["sem_mov"]]),
                width="stretch", config={"displayModeBar": False})
            _dmap = {"OK": "ok", "Atenção": "atencao", "Comprar": "comprar", "Sem giro": "sem_mov"}
            _drill_select("alm_ch_dist", _dlabels, lambda l: f"Distribuição · {l}",
                          lambda l: rows_inventario_filtro(_dmap.get(l, "todos")))
    with s2c:
        with st.container(border=True):
            st.markdown("##### :material/timeline: Cobertura (dias)")
            st.caption("Estoque atual ÷ consumo diário = quantos dias o estoque dura no ritmo atual.")
            cf = vm["cobertura_faixa"]
            _clabels = [f"{kk} dias" for kk in cf.keys()]
            st.plotly_chart(_barv(_clabels, [int(v) for v in cf.values()]),
                            width="stretch", config={"displayModeBar": False})
            _drill_select("alm_ch_cob", list(cf.keys()),
                          lambda l: f"Cobertura · {l} dias",
                          lambda l: rows_cobertura_faixa(l), display=_clabels)
    with s3c:
        with st.container(border=True):
            st.markdown("##### :material/leaderboard: Curva ABC (valor)")
            st.caption("Classe por valor consumido em 90 d: A = 80% do valor, B = próximos 15%, C = resto. "
                       "Rótulo = nº de itens · % do valor.")
            a = vm["abc"]
            st.plotly_chart(
                _barv(["A", "B", "C"], [a["A"]["n"], a["B"]["n"], a["C"]["n"]],
                      textos=[f"{a['A']['n']} · {a['A']['pct']}%",
                              f"{a['B']['n']} · {a['B']['pct']}%",
                              f"{a['C']['n']} · {a['C']['pct']}%"]),
                width="stretch", config={"displayModeBar": False})
            _drill_select("alm_ch_abc", ["A", "B", "C"],
                          lambda l: f"Curva ABC · Classe {l}", lambda l: rows_abc_classe(l))

    # ── Entradas / Saídas com o período explícito (hoje/semana/mês) ──────────────
    _hoje = date.today()
    _seg = _hoje - timedelta(days=_hoje.weekday())   # segunda-feira da semana atual
    _dom = _seg + timedelta(days=6)                  # domingo
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
            _card_drill(e1, "Hoje", en["hoje"]["n"], "alm_e_h", lambda: rows_mov_periodo("entrada", "hoje"),
                        help=f"Recebimentos de hoje ({_hoje_str}).")
            _card_drill(e2, "Semana", en["semana"]["n"], "alm_e_s", lambda: rows_mov_periodo("entrada", "semana"),
                        help=f"Recebimentos da semana atual — {_sem_str}.")
            _card_drill(e3, "Mês", en["mes"]["n"], "alm_e_m", lambda: rows_mov_periodo("entrada", "mes"),
                        help=f"Recebimentos do mês atual — {_mes_str}.")
    with sa:
        with st.container(border=True):
            st.markdown("#### 📤 Saídas (requisições)")
            st.caption(f"Hoje **{_hoje_str}** · Semana **{_sem_str}** · Mês **{_mes_str}**")
            sd = vm["saidas"]
            x1, x2, x3 = st.columns(3)
            _card_drill(x1, "Hoje", sd["hoje"]["n"], "alm_x_h", lambda: rows_mov_periodo("saida", "hoje"),
                        help=f"Saídas por requisição de hoje ({_hoje_str}).")
            _card_drill(x2, "Semana", sd["semana"]["n"], "alm_x_s", lambda: rows_mov_periodo("saida", "semana"),
                        help=f"Saídas da semana atual — {_sem_str}.")
            _card_drill(x3, "Mês", sd["mes"]["n"], "alm_x_m", lambda: rows_mov_periodo("saida", "mes"),
                        help=f"Saídas do mês atual — {_mes_str}.")

    tc1, tc2 = st.columns(2)
    with tc1:
        _bloco_top("📥 Top materiais recebidos (mês)", vm["top_recebidos"],
                   lambda x: f'{x["pn"]} — {(x["item"] or "")[:26]}', "q", lambda v: f"{v:g}")
    with tc2:
        _bloco_top("📤 Materiais mais consumidos (mês)", vm["mais_consumidos"],
                   lambda x: f'{x["pn"]} — {(x["item"] or "")[:26]}', "q", lambda v: f"{v:g}")
    _bloco_top("🏭 Setores que mais retiram", vm["setores"],
               lambda x: x["setor"], "n", lambda v: f"{int(v)}")

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
                df_abc["lbl"] = df_abc.apply(lambda x: f"{x['part_number']} • {str(x['nome_item'])[:15]}", axis=1)  # top10-almox
                fig = go.Figure(data=[go.Bar(
                    y=df_abc["lbl"], x=df_abc["total_saida"], orientation="h",
                    marker=dict(color=PAL["accent"], line=dict(width=1, color=PAL["accent_borda"])),
                    text=df_abc["total_saida"].apply(lambda x: f"{int(x)}"), textposition="outside",
                    textfont=dict(size=11, color=PAL["texto_suave"]),
                )])
                fig.update_layout(
                    template=PAL["plotly_template"], height=320,
                    margin=dict(l=0, r=20, t=10, b=0), paper_bgcolor=PAL["paper_bg"],
                    plot_bgcolor=PAL["plot_bg"], showlegend=False,
                    font=dict(family="Inter", color=PAL["texto"]),
                    xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(color=PAL["texto_suave"])),
                    yaxis=dict(showgrid=False, tickfont=dict(size=11, color=PAL["texto"])))
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                _drill_select("alm_ch_top10", list(df_abc["part_number"]),
                              lambda l: f"Saídas recentes (30d) · {l}",
                              lambda l: rows_saidas_item(l), display=list(df_abc["lbl"]))
            else:
                st.info("Sem consumo registrado no período.")
    with colB:
        with st.container(border=True):
            st.markdown("#### :material/science: Padrões de demanda")
            st.caption("Cada item é lido por duas coisas: **com que regularidade** ele sai e "
                       "**o quanto o tamanho de cada saída varia**. Juntas, indicam o quão "
                       "previsível é repor cada material. O número na coluna = quantos itens.")
            ordem = ["Suave", "Intermitente", "Errático", "Irregular", "Poucos dados"]
            dem = vm_gestao["demanda"]
            dados_dem = [(p, dem.get(p, 0)) for p in ordem if dem.get(p, 0)]
            if dados_dem:
                _plabels = [p for p, _ in dados_dem]
                st.plotly_chart(
                    _barv(_plabels, [n for _, n in dados_dem],
                          textos=[f"{n}" for _, n in dados_dem], height=220),
                    width="stretch", config={"displayModeBar": False})
                _drill_select("alm_ch_dem", _plabels, lambda l: f"Padrão de demanda · {l}",
                              lambda l: rows_padrao_demanda(l))
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
                    unsafe_allow_html=True)

            xyz = vm_gestao["xyz"]
            if xyz:
                st.caption("**XYZ** mede o quanto o consumo varia de mês a mês "
                           "(X estável · Y variável · Z errático — baixa confiança com poucos meses): "
                           f"X {xyz.get('X', 0)} · Y {xyz.get('Y', 0)} · Z {xyz.get('Z', 0)}.")

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
                    st.bar_chart(dc.set_index("Setor"), color="#F7941E", height=250)
                else:
                    st.caption("Sem dados de setor preenchidos.")
            with colE:
                if "emitente" in df_r.columns and not df_r["emitente"].isna().all():
                    dc = df_r["emitente"].value_counts().head(10).reset_index()
                    dc.columns = ["Emitente", "Qtd"]
                    st.dataframe(dc, width="stretch", hide_index=True, height=250,
                                 column_config={"Qtd": st.column_config.ProgressColumn(
                                     "Qtd", format="%d", min_value=0,
                                     max_value=int(dc["Qtd"].max()) if not dc.empty else 100, color="#F7941E")})
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
                _barras_agrupadas([_mes_label(m) for m in h["meses"]],
                                  [("Entradas", h["entradas"], "#22c55e"),
                                   ("Saídas", h["saidas"], "#ef4444")],
                                  mostrar_valores=True),
                width="stretch", config={"displayModeBar": False})
            _drill_select("alm_ch_hist", h["meses"], lambda l: f"Movimentações de {_mes_label(l)}",
                          lambda l: rows_mov_mes(l), display=[_mes_label(m) for m in h["meses"]])
        else:
            st.caption("Sem movimentações registradas.")

    st.caption(":material/map: **Mapa do Almoxarifado** (prateleiras por status de cor) fica "
               "para quando houver um modelo de localização/posição — hoje o local é texto livre.")


def _render_dash_compras_mro(vm):
    """:material/shopping_cart: Dashboard Compras MRO (§1) — espelha o Dashboard SCM WK29,
    porém só com material MRO. Clicável (cards com 🔍 + seletor abaixo de cada gráfico). v4.5.5."""
    from services.drill_down import (rows_itens_em_aberto, rows_fornecedores_aberto,
                                     rows_setores_demanda_aberta, rows_scs_status,
                                     rows_scs_comprador, rows_scs_mes, rows_scs_itens_faixa)
    k = vm["kpis"]
    ch, cw = st.columns([3, 1])
    ch.markdown("### :material/shopping_cart: Dashboard Compras MRO · Inventus Power")
    cw.markdown(f"<div style='text-align:right'><b>WK {vm['wk']}</b> · {vm['ano']}</div>",
                unsafe_allow_html=True)
    ua = vm.get("ultima_atualizacao")
    st.caption(f":material/update: Última atualização do Relatório de SCs: **{fmt(ua) if ua else '—'}** · "
               f"escopo do ano de {vm['ano']}. Espelha o **Dashboard SCM**, só com material MRO. "
               ":material/ads_click: cards com 🔍 e seletor abaixo de cada gráfico.")

    # ── KPIs ──
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    _card_drill(m1, ":material/request_quote: Em cotação", k["itens_abertos"], "cmp_cot",
                lambda: rows_scs_status("Em Cotação"), help="SCs abertas com status de Cotação.")
    m2.metric("🔴 Críticos", k["itens_criticos"], delta_color="inverse",
              help="Itens abertos com estoque no/abaixo do mínimo.")
    m3.metric(":material/timer: Aging médio",
              f"{k['aging_medio']}d" if k["aging_medio"] is not None else "—",
              help="Tempo médio Emissão → atendimento (PO/aprovação) das SCs do ano.")
    _card_drill(m4, ":material/receipt_long: SCs abertas", k["scs_abertas"], "cmp_scab",
                lambda: rows_itens_em_aberto(), help="SCs com saldo pendente (itens em aberto).")
    m5.metric(":material/shopping_cart_checkout: POs emitidos", k["pos_emitidos"])
    m6.metric(":material/payments: Valor comprado", _brl_compact(k["valor_comprado"]))

    # ── SCM: Qtd. de Itens por Mês · Qtd. de SCs por Mês ──
    st.divider()
    vmn = vm["volume_mensal"]
    _meses_lbl = [_mes_label(m) for m in vmn["meses"]]
    a1, a2 = st.columns(2)
    with a1:
        with st.container(border=True):
            st.markdown("##### :material/bar_chart: Qtd. de Itens por Mês (SCs)")
            if vmn["meses"]:
                st.plotly_chart(_barv(_meses_lbl, vmn["itens"]),
                                width="stretch", config={"displayModeBar": False})
                _drill_select("cmp_itmes", vmn["meses"], lambda l: f"SCs de {_mes_label(l)}",
                              lambda l: rows_scs_mes(l), display=_meses_lbl)
            else:
                st.caption("Sem SCs no ano.")
    with a2:
        with st.container(border=True):
            st.markdown("##### :material/bar_chart: Qtd. de SCs por Mês")
            if vmn["meses"]:
                st.plotly_chart(_barv(_meses_lbl, vmn["scs"]),
                                width="stretch", config={"displayModeBar": False})
                _drill_select("cmp_scmes", vmn["meses"], lambda l: f"SCs de {_mes_label(l)}",
                              lambda l: rows_scs_mes(l), display=_meses_lbl)
            else:
                st.caption("Sem SCs no ano.")

    # ── SCM: Ranking de Departamentos · Itens por comprador ──
    b1, b2 = st.columns(2)
    with b1:
        with st.container(border=True):
            st.markdown("##### :material/apartment: Ranking de Departamentos (demanda em aberto)")
            pdep = vm["por_departamento"][:10]
            if pdep:
                st.plotly_chart(_barv([x["departamento"] or "—" for x in pdep], [x["n"] for x in pdep]),
                                width="stretch", config={"displayModeBar": False})
                _drill_select("cmp_dep", [x["departamento"] or "—" for x in pdep],
                              lambda l: "Setores (demanda em aberto)",
                              lambda l: rows_setores_demanda_aberta())
            else:
                st.caption("Sem demanda em aberto por setor.")
    with b2:
        with st.container(border=True):
            st.markdown("##### :material/badge: Itens atribuídos por comprador")
            pc = vm["por_comprador"][:10]
            if pc:
                st.plotly_chart(_barv([x["comprador"] for x in pc], [x["itens"] for x in pc]),
                                width="stretch", config={"displayModeBar": False})
                _drill_select("cmp_comp", [x["comprador"] for x in pc],
                              lambda l: f"Comprador · {l}", lambda l: rows_scs_comprador(l))
            else:
                st.caption("Sem compradores no período.")

    # ── SCM: Status dos POs (rosca) · Qtd. de Itens por Pedido (rosca) ──
    g1, g2 = st.columns(2)
    with g1:
        with st.container(border=True):
            st.markdown("##### :material/donut_large: Status dos Pedidos de Compra (POs)")
            sp = vm["status_pos"]
            if sp:
                lbls = list(sp.keys())
                st.plotly_chart(_donut(lbls, [sp[x] for x in lbls]),
                                width="stretch", config={"displayModeBar": False})
                _drill_select("cmp_stpo", lbls, lambda l: f"SCs · Status {l}",
                              lambda l: rows_scs_status(l))
            else:
                st.caption("Sem SCs no ano.")
    with g2:
        with st.container(border=True):
            st.markdown("##### :material/donut_large: Qtd. de Itens por Pedido")
            ipp = vm["itens_por_pedido"]
            if ipp:
                lbls = list(ipp.keys())
                st.plotly_chart(_donut(lbls, [ipp[x] for x in lbls]),
                                width="stretch", config={"displayModeBar": False})
                _drill_select("cmp_ipp", lbls, lambda l: f"Pedidos com {l}",
                              lambda l: rows_scs_itens_faixa(l))
            else:
                st.caption("Sem itens por pedido.")

    # ── SCM: Aging dos itens em aberto (faixa de dias) ──
    # v4.5.6 — removidos "Ranking de Aging por Depto (>15d)" e "Semana atual vs.
    # anterior" (pedido do usuário); os 2 gráficos mantidos passam a ocupar a largura toda.
    with st.container(border=True):
        st.markdown("##### :material/donut_large: Aging dos itens em aberto (faixa de dias)")
        ad = vm["aging_dist"]
        st.plotly_chart(_donut(list(ad.keys()), [int(v) for v in ad.values()]),
                        width="stretch", config={"displayModeBar": False})
        st.caption("Dias desde a **aprovação** da SC · itens sem aprovação ficam fora.")

    # ── SCM: Tendência por Semana — aprovados × POs ──
    with st.container(border=True):
        st.markdown("##### :material/show_chart: Tendência por Semana — aprovados × POs")
        ev = vm["evolucao_semanal"]
        if ev["weeks"]:
            st.plotly_chart(_linhas([f"WK{w}" for w in ev["weeks"]],
                                    [("Itens aprovados", ev["aprovados"], "#3b82f6"),
                                     ("POs emitidos", ev["pos"], "#22c55e")]),
                            width="stretch", config={"displayModeBar": False})
        else:
            st.caption("Sem dados semanais.")

    # ── Mantidos como estão (pedido do usuário): Fornecedor por valor + Setores ──
    st.divider()
    cc, cd = st.columns(2)
    with cc:
        _bloco_top("🏭 Fornecedores por valor", vm["fornecedores_top"],
                   lambda x: x["fornecedor"][:22], "valor", lambda v: _brl_compact(v))
        if vm["fornecedores_top"]:
            _drill_select("cmp_forn", [x["fornecedor"] for x in vm["fornecedores_top"]],
                          lambda l: "Fornecedores (SCs abertas por valor)",
                          lambda l: rows_fornecedores_aberto())
    with cd:
        _bloco_top("📦 Setores (demanda em aberto)", vm["por_departamento"],
                   lambda x: (x["departamento"] or "—"), "n", lambda v: f"{int(v)}",
                   height=340, label_outside=True)

    # ── Detalhamento ──
    st.divider()
    st.markdown("#### :material/table_rows: Detalhamento")
    if st.button("🔍 Ver todos os itens em aberto (fila do dia)", key="cmp_painel_btn"):
        _abrir_drill("Itens em aberto (fila do dia)", rows_itens_em_aberto())
    if vm["por_comprador"]:
        st.markdown("##### 📈 Comparativo por Comprador")
        st.dataframe(pd.DataFrame([{
            "Comprador": c["comprador"], "Itens": c["itens"], "POs": c["pos"],
            "Valor": c["valor"], "Aging médio (d)": c["aging_medio"]} for c in vm["por_comprador"]]),
            hide_index=True, width="stretch", column_config={
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                "Aging médio (d)": st.column_config.NumberColumn(format="%.1f")})

    _bloco_top("📅 Lead Time por Fornecedor (dias)", vm["lead_time_fornecedor"],
               lambda x: x["fornecedor"][:24], "dias", lambda v: f"{v:g}d",
               caption="Tempo médio Emissão → PO por fornecedor — maior = alvo de negociação.")


def _render_dash_comprador(vm):
    """:material/person: Comprador — o que fazer agora: KPIs de ação, fila priorizada, SCs sugeridas, aging."""
    k = vm["kpis"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Críticos", k["criticos"],
              help="Itens tier-0 na fila de reposição (abaixo do ponto de pedido, com consumo real).")
    c2.metric(":material/alarm: Comprar até atrasados", k["comprar_atrasados"], delta_color="inverse",
              help="Sugestões cujo prazo-limite de compra (cobertura − lead time − 15d) já passou.")
    c3.metric(":material/receipt_long: SCs abertas", k["scs_abertas"],
              help="Solicitações de compra com saldo pendente (não recebidas/canceladas).")
    c4.metric(":material/emergency: Rupturas", k["rupturas"], delta_color="inverse",
              help="Itens com consumo real e estoque físico = 0 (parada iminente).")

    st.markdown("---")
    col_fila, col_lado = st.columns([3, 2])

    with col_fila:
        with st.container(border=True):
            st.markdown(f"#### :material/psychology: Fila de reposição — top {len(vm['fila'])} de {vm['total_fila']}")
            st.caption("Priorizada por urgência. Ação completa em **Controle de SC → :material/psychology: Assistente de Reposição**.")
            if vm["fila"]:
                df = pd.DataFrame([{
                    "Prio": s.get("prioridade"),
                    "Part Number": s.get("part_number"),
                    "Item": (s.get("nome_item") or "")[:32],
                    "Cobertura(d)": s.get("cobertura_dias"),
                    "Comprar até": fmt(s.get("comprar_ate")) if s.get("comprar_ate") else "—",
                    "Qtd": s.get("qtd_sugerida"),
                    "Un": s.get("unidade"),
                    "Fornecedor": s.get("fornecedor_sugerido") or "—",
                } for s in vm["fila"]])
                st.dataframe(df, width="stretch", hide_index=True, height=400)
            else:
                st.success("Nenhuma reposição pendente no momento. :material/celebration:")

    with col_lado:
        with st.container(border=True):
            st.markdown("#### :material/inventory_2: SCs sugeridas (agrupadas)")
            st.caption("Itens já agrupados por natureza — de 'mão beijada' para o Protheus.")
            if vm["scs_sugeridas"]:
                for g in vm["scs_sugeridas"][:6]:
                    ca = fmt(g["comprar_ate_min"]) if g.get("comprar_ate_min") else "—"
                    st.markdown(f"**{g['titulo']}** — {g['n_itens']} itens · qtd {g['qtd_total']} · comprar até {ca}")
                    st.caption(f"CC sugerido: {g.get('cc_sugerido', '—')}")
            else:
                st.caption("Sem SCs sugeridas no momento.")

        with st.container(border=True):
            st.markdown("#### :material/timer: Aging das SCs abertas")
            ag = vm["aging"]
            a1, a2, a3 = st.columns(3)
            a1.metric("0–7 dias", ag["0-7"])
            a2.metric("8–15 dias", ag["8-15"], delta_color="off")
            a3.metric("15+ dias", ag["15+"], delta_color="inverse",
                      help="SCs abertas há mais de 15 dias — o gargalo entre abrir e comprar.")
            if ag.get("sem_data"):
                st.caption(f"{ag['sem_data']} SC(s) sem data de abertura registrada.")


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


def _card_drill(col, label, valor, dkey, provider, *, help=None, delta=None,
                delta_color="normal") -> None:
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
        key=f"download_{titulo}"
    )


def _render_dash_executivo(vm):
    """:material/insights: Mensal — panorama do ano corrente (YTD): KPIs em R$/serviço, séries, ABC e vários Top 10."""
    from services.drill_down import (rows_inventario_filtro, rows_consumo_ytd,
                                     rows_requisicoes_ano, rows_criticos_reposicao,
                                     rows_abc_ytd_classe, rows_consumo_ytd_tipo,
                                     rows_saidas_mes, rows_padrao_demanda)
    ano = vm["ano"]
    st.subheader(f":material/insights: Panorama {ano} — visão executiva")
    st.caption(f"Tudo nesta tela é do **ano corrente ({ano})**, de 1º de janeiro até hoje. "
               "Consumo = saídas reais por requisição (ajustes de inventário não entram). "
               "Valores em R$ pela valoração de referência (último preço negociado).")

    k = vm["kpis"]; vd = vm["valor_detalhe"]
    # ── Faixa 1: financeiro / volume ──
    c1, c2, c3, c4 = st.columns(4)
    _card_drill(c1, ":material/payments: Valor imobilizado", _dash_fmt_brl(k["valor_imobilizado"]), "kpi_imob",
                lambda: rows_inventario_filtro("com_valor"),
                help="Capital parado em estoque hoje: Σ(estoque × preço de referência).")
    _card_drill(c2, ":material/shopping_cart: Consumido no ano (YTD)", _dash_fmt_brl(k["valor_consumido_ytd"]), "kpi_cons",
                lambda: rows_consumo_ytd(),
                help="Valor total consumido de 1º/jan até hoje (saídas reais × preço).")
    _card_drill(c3, ":material/assignment: Requisições (YTD)", f"{k['n_requisicoes_ytd']:,}".replace(",", "."), "kpi_req",
                lambda: rows_requisicoes_ano(),
                help="Nº de requisições atendidas no ano corrente.")
    _card_drill(c4, ":material/inventory_2: Itens movimentados (YTD)", k["itens_consumidos_ytd"], "kpi_itmov",
                lambda: rows_consumo_ytd(),
                help="Quantos itens diferentes tiveram consumo real no ano.")
    st.caption(f":material/info: Valoração: {vd['itens_valorados']} itens com preço · "
               f"{vd['itens_sem_preco']} com estoque sem preço (subestima o total).")

    # ── Faixa 2: operação / serviço ──
    o1, o2, o3, o4 = st.columns(4)
    ns = k["nivel_servico"]
    _card_drill(o1, ":material/ads_click: Nível de serviço", f"{ns}%" if ns is not None else "—", "kpi_ns",
                lambda: rows_inventario_filtro("com_consumo"),
                help="% dos itens com consumo real fora de ruptura. Proxy de disponibilidade.")
    gm = k["giro_medio"]
    _card_drill(o2, ":material/sync: Giro médio (ano)", f"{gm}x" if gm is not None else "—", "kpi_giro",
                lambda: rows_inventario_filtro("com_consumo"),
                help="Quantas vezes o estoque se renova por ano, em média.")
    _card_drill(o3, "🔴 Críticos", k["criticos"], "kpi_crit", lambda: rows_criticos_reposicao(),
                delta_color="off", help="Itens que já precisam de compra agora (abaixo do ponto de pedido).")
    _card_drill(o4, ":material/emergency: Rupturas", k["rupturas"], "kpi_rup", lambda: rows_inventario_filtro("ruptura"),
                delta_color="off", help="Itens com consumo real e estoque zerado — risco imediato.")

    st.markdown("---")

    # ── Evolução mensal (R$) + composição por tipo (donut) ──
    s = vm["series"]
    colE, colC = st.columns([3, 2])
    with colE:
        with st.container(border=True):
            st.markdown(f"#### :material/trending_up: Consumo mês a mês em {ano} (R$)")
            cm = s["consumo_mensal"]
            if cm:
                df = pd.DataFrame([{"Mês": _mes_label(x["mes"]), "Valor (R$)": x["valor"]} for x in cm])
                st.bar_chart(df.set_index("Mês"), color="#F36F21", height=300)
                _drill_select("kpi_ch_mensal", [x["mes"] for x in cm],
                              lambda l: f"Consumo de {_mes_label(l)}",
                              lambda l: rows_saidas_mes(l), display=[_mes_label(x["mes"]) for x in cm])
            else:
                st.caption("Sem consumo real no ano ainda.")
    with colC:
        with st.container(border=True):
            st.markdown("#### :material/donut_large: Consumo por tipo de material")
            comp = vm["composicao_tipo"]
            if comp:
                st.plotly_chart(_donut([x["tipo"] for x in comp], [x["valor"] for x in comp],
                                       height=300, fmt=_brl_compact),
                                width="stretch", config={"displayModeBar": False})
                _tipos = [x["tipo"] for x in comp if x["tipo"] != "Outros"]
                _drill_select("kpi_ch_comp", _tipos, lambda l: f"Consumo YTD · {l}",
                              lambda l: rows_consumo_ytd_tipo(l))
            else:
                st.caption("Sem consumo valorado no ano.")

    # ── Curva ABC ──
    with st.container(border=True):
        abc = vm["abc"]; classes = abc["classes"]
        st.markdown("#### :material/emoji_events: Curva ABC por valor consumido (ano corrente)")
        st.caption("Poucos itens concentram a maior parte do gasto — classe A = os que mais pesam.")
        ca, cb, cc = st.columns(3)
        _card_drill(ca, "🅰️ Classe A", classes.get("A", 0), "kpi_abc_a", lambda: rows_abc_ytd_classe("A"),
                    help="Itens que somam até 80% do valor consumido.")
        _card_drill(cb, "🅱️ Classe B", classes.get("B", 0), "kpi_abc_b", lambda: rows_abc_ytd_classe("B"),
                    delta_color="off", help="De 80% a 95% do valor.")
        _card_drill(cc, "🅲 Classe C", classes.get("C", 0), "kpi_abc_c", lambda: rows_abc_ytd_classe("C"),
                    delta_color="off", help="Os 5% finais do valor.")
        if abc["itens"]:
            st.plotly_chart(
                _barh([f"{x['part_number']} · {str(x['nome_item'])[:18]}" for x in abc["itens"]][::-1],
                      [x["valor"] for x in abc["itens"]][::-1],
                      [_brl_compact(x["valor"]) for x in abc["itens"]][::-1], height=380),
                width="stretch", config={"displayModeBar": False})

    st.markdown("---")
    st.markdown("### :material/leaderboard: Rankings Top 10 — ano corrente")
    r = vm["rankings"]

    # Linha 1: valor consumido | quantidade
    t1, t2 = st.columns(2)
    with t1:
        _bloco_top(":material/shopping_cart: Top 10 — valor consumido (R$)", r["top_valor_consumido"],
                   lambda x: f"{x['part_number']} · {str(x['nome_item'])[:16]}", "valor", _brl_compact,
                   caption="Onde o dinheiro foi gasto no ano.")
    with t2:
        _bloco_top(":material/format_list_numbered: Top 10 — quantidade consumida", r["top_qtd_consumida"],
                   lambda x: f"{x['part_number']} · {str(x['nome_item'])[:16]}", "qtd",
                   lambda v: f"{v:g}", cor="#F7941E",
                   caption="Maior volume de saída (cada item na sua unidade).")

    # Linha 2: valor imobilizado | dead stock
    t3, t4 = st.columns(2)
    with t3:
        _bloco_top(":material/warehouse: Top 10 — capital parado em estoque", r["top_valor_imobilizado"],
                   lambda x: f"{x['part_number']} · {str(x['nome_item'])[:16]}", "valor", _brl_compact,
                   cor="#6C7A89", caption="Itens que mais imobilizam capital hoje.")
    with t4:
        _bloco_top(":material/bedtime: Top 10 — dinheiro dormindo (sem consumo no ano)", r["top_dead_stock"],
                   lambda x: f"{x['part_number']} · {str(x['nome_item'])[:16]}", "valor", _brl_compact,
                   cor="#C0392B", caption="Estoque parado que NÃO teve saída no ano — candidato a revisão.")

    # Linha 3: centro de custo | emitente
    t5, t6 = st.columns(2)
    with t5:
        _bloco_top(":material/account_tree: Top 10 — centros de custo (R$)", r["top_centro_custo"],
                   lambda x: str(x["rotulo"])[:26], "valor", _brl_compact, cor="#2E86C1",
                   caption="Áreas que mais consomem, em R$ (exclui CCs contábeis genéricos).")
    with t6:
        _bloco_top(":material/person: Top 10 — emitentes (nº requisições)", r["top_emitente"],
                   lambda x: str(x["rotulo"])[:22], "n", lambda v: f"{v}", cor="#27AE60",
                   caption="Quem mais abre requisições.")

    # Linha 4: setor | padrões de demanda
    t7, t8 = st.columns(2)
    with t7:
        _bloco_top(":material/factory: Top 10 — setores (nº requisições)", r["top_setor"],
                   lambda x: str(x["rotulo"])[:22], "n", lambda v: f"{v}", cor="#8E44AD",
                   caption="Setores que mais requisitam material.")
    with t8:
        with st.container(border=True):
            st.markdown("#### :material/science: Padrões de demanda (SBC)")
            st.caption("Quão previsível é repor cada material.")
            ordem = ["Suave", "Intermitente", "Errático", "Irregular", "Poucos dados"]
            dem = vm["destaques"]["demanda"]
            dados_dem = [{"Padrão": p, "Itens": dem.get(p, 0)} for p in ordem if dem.get(p, 0)]
            if dados_dem:
                st.bar_chart(pd.DataFrame(dados_dem).set_index("Padrão"), color="#F7941E", height=240)
                _drill_select("kpi_ch_dem", [d["Padrão"] for d in dados_dem],
                              lambda l: f"Padrão de demanda · {l}", lambda l: rows_padrao_demanda(l))
            else:
                st.caption("Sem consumo real suficiente para classificar.")
            xyz = vm["destaques"]["xyz"]
            if xyz:
                st.caption(f"XYZ: X {xyz.get('X',0)} · Y {xyz.get('Y',0)} · Z {xyz.get('Z',0)}.")

    st.markdown("---")

    # ── Distribuição do inventário + aging ──
    d = vm["destaques"]
    colD, colA = st.columns([3, 2])
    with colD:
        with st.container(border=True):
            st.markdown("#### :material/donut_large: Distribuição do inventário hoje")
            dist = d["distribuicao"]
            labels = ["OK", "Atenção", "Comprar", "Sem Mov.", "Zerados"]
            vals = [dist["ok"], dist["atencao"], dist["comprar"], dist["sem_mov"], dist["zerados"]]
            st.plotly_chart(_donut(labels, vals, height=270, fmt=lambda v: f"{v} itens"),
                            width="stretch", config={"displayModeBar": False})
    with colA:
        with st.container(border=True):
            st.markdown("#### :material/timer: Aging das SCs abertas")
            st.caption("Há quanto tempo as SCs abertas estão paradas.")
            ag = d["aging"]
            a1, a2, a3 = st.columns(3)
            a1.metric("0–7 d", ag["0-7"], delta_color="off")
            a2.metric("8–15 d", ag["8-15"], delta_color="off")
            a3.metric("15+ d", ag["15+"], delta_color="inverse", help="SCs paradas há mais de 15 dias.")
            if ag.get("sem_data"):
                st.caption(f"{ag['sem_data']} SC(s) sem data de abertura.")
