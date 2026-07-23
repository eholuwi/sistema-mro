from services.db_functions import obter_dados_dashboard 
import streamlit as st
import pandas as pd
import json, io, math, os, sys, time, urllib.parse
from streamlit_option_menu import option_menu
from datetime import date, datetime, timedelta
from services.styles import inject_custom_css
from services.logging_config import setup_logging
from services.constants import (
    PREVISAO_RUPTURA_SEM_RISCO, ORDENACAO_RUPTURA_INFINITO,
    AGING_ALERTA_DIAS, AGING_CRITICO_DIAS, RUPTURA_CRISE_DIAS,
    PADROES_DEMANDA,
    IMPORTANCIAS, TIPOS, SETORES, UNIDADES, STATUS_SC,
)

sys.path.insert(0, os.path.dirname(__file__))
from database import criar_banco
from services.db_functions import (
    buscar_item_por_id, listar_inventario, salvar_item, desmarcar_inventariado,
    registrar_movimentacao, listar_movimentacoes, categoria_movimentacao,
    criar_sc, atualizar_sc, registrar_recebimento_sc, listar_scs,
    atualizar_pedido_guarda_chuva, obter_pedido_sc,
    criar_guarda_chuva, listar_guarda_chuva, obter_guarda_chuva, atualizar_guarda_chuva,
    registrar_recebimento_guarda_chuva, remover_guarda_chuva, saldo_total_por_material,
    GUARDA_CHUVA_ESTAGIOS,
    listar_itens_sc, buscar_scs_por_item, itens_com_sc_aberta, exportar_inventario_df,
    listar_valores, adicionar_valor_lista, remover_valor_lista,
    listar_setores_conhecidos, sincronizar_setores_config,
    criar_requisicao, listar_requisicoes, listar_itens_requisicao, mapa_pn_por_requisicao,
    entregar_requisicao, adicionar_itens_requisicao, remover_item_requisicao,
    cancelar_requisicao, listar_requisicoes_abertas,
    importar_solicitacoes_protheus, listar_recebimentos_sc,
    atualizar_localizacao_e_inventariar, atualizar_item_inventario,
    obter_analitico_movimentacoes, obter_analitico_divergencias,
    obter_analitico_rupturas, exportar_movimentacoes_df,
    importar_inventario_neidson, alterar_part_number,
    listar_historico_part_number, buscar_item_por_pn,
    registrar_feedback, listar_feedbacks, atualizar_feedback,
    importar_relatorio_scs, tirar_snapshot_estoque,
    sincronizar_monitor_sc, listar_monitor_sc, salvar_monitor_sc,
    carregar_planilha_livre, salvar_planilha_livre,
    obter_cadastro_mro_para_cruzamento,
    obter_maturidade_dados, calcular_giro,
    obter_valor_imobilizado, obter_evolucao_valor_imobilizado,
    obter_evolucao_preco, obter_abc_valor,
    obter_fornecedores_por_item,
    filtrar_itens_por_busca, sincronizar_fornecedores_lista,
    sugerir_conversao, setor_dominante_por_item,
)
from services.constants import UNIDADES_COMPRA_SUGERIDAS, FATOR_CONVERSAO_PADRAO
from services.planejamento import (
    gerar_sugestoes_reposicao, sugestao_para_item_sc,
    registrar_desfecho_sugestao, buscar_sc_id_por_numero,
    agrupar_por_tipo_material, resumir_grupo_sc,
)
from services.ficha import (
    montar_ficha_360, salvar_imagem_item, remover_imagem_item,
    agrupar_saldo_residual_por_fornecedor,
)
from services.monitor_cruzamento import preparar_df, cruzar_scm_sc7, COLUNAS_SAIDA
from services import scm_client
from services.monitor_scm import cotacoes_no_escopo, montar_scs_nao_atendidas, COLUNAS_SCS_NAO_ATENDIDAS
from services.dashboards import (
    montar_dashboard, montar_visao_compras_mro, montar_visao_almoxarifado,
    PUBLICO_COMPRADOR, PUBLICO_GESTAO, PUBLICO_EXECUTIVO,
)
from ui.tema import paleta_atual
from ui.formatos import fmt, fmt_date_input
from ui.sidebar import render_sidebar
from ui.componentes.selecao import sel_material, opcoes_com_atual
from ui.router import ROTAS_MIGRADAS, render_pagina

setup_logging()
criar_banco()

# v2.2.0 — foto diária do estoque (idempotente por dia; sem scheduler externo).
# Só executa a primeira vez que o app abre no dia; nas demais é praticamente no-op.
try:
    tirar_snapshot_estoque()
except Exception:
    pass

# v3.9.0 — sync diário do Monitor de SC (mesmo hook "1ª abertura do dia"): recalcula as
# colunas técnicas das SCs abertas e reseta o "Revisado". Gated por dia (no-op nas demais).
try:
    sincronizar_monitor_sc()
except Exception:
    pass

st.set_page_config(page_title="MRO Inventus Power 5.2.0", page_icon=":material/build:", layout="wide", initial_sidebar_state="expanded")


# Paleta única do tema escolhido (via ui.tema.paleta_atual) — consumida pelo CSS
# global, pelo option_menu e pelos gráficos, p/ tudo acompanhar claro/escuro (v2.11.0).
PAL = paleta_atual()
inject_custom_css(PAL)

# Constantes de cadastro/filtros (IMPORTANCIAS/TIPOS/SETORES/UNIDADES/STATUS_SC) e os
# selecionadores de material (sel_material/itens_select/opcoes_com_atual) foram
# centralizados na F4a (v5.3.0) em services.constants e ui.componentes.selecao (imports no topo).

# ── Sidebar ───────────────────────────────────────────────────────────────────

pagina = render_sidebar()

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — v3.0.0 (por público: 👤 Comprador · 📊 Gestão · 🏛️ Diretoria)
# Os assemblers puros vivem em services/dashboards.py; aqui é só o desenho (DT-3).
# ══════════════════════════════════════════════════════════════════════════════

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
            dados = obter_dados_dashboard()
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


_MESES_PT = ["", "jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]


def _mes_label(ym):
    """'2026-07' → 'jul/26' (rótulo curto pt-BR para eixos de gráfico)."""
    try:
        a, m = str(ym).split("-")[:2]
        return f"{_MESES_PT[int(m)]}/{a[2:]}"
    except (ValueError, IndexError):
        return str(ym)


def _brl_compact(v):
    """R$ compacto p/ rótulo de barra: 18800 → 'R$ 18,8k'; 1250000 → 'R$ 1,3M'."""
    try:
        v = float(v)
    except (ValueError, TypeError):
        return "R$ —"
    if abs(v) >= 1_000_000:
        return f"R$ {v/1_000_000:.1f}M".replace(".", ",")
    if abs(v) >= 1_000:
        return f"R$ {v/1_000:.1f}k".replace(".", ",")
    return f"R$ {v:.0f}"


# Paleta de série p/ donuts (laranja da marca → tons de apoio).
_SERIE_CORES = ["#F36F21", "#F7941E", "#FFB65C", "#6C7A89", "#8E44AD",
                "#2E86C1", "#27AE60", "#C0392B", "#B3B3B3"]


def _barh(labels, values, textos, cor=None, height=300, label_outside=False):
    """Gráfico de barras horizontais (ranking). `labels`/`values`/`textos` já na ordem
    de exibição (maior no topo = último da lista, convenção do Plotly horizontal).
    `label_outside=True` põe o rótulo FORA da barra — evita número girado/minúsculo em
    barras curtas (ex.: contagens pequenas de Setores em demanda aberta). v4.1.0."""
    import plotly.graph_objects as go
    fig = go.Figure(go.Bar(
        y=labels, x=values, orientation="h",
        marker=dict(color=cor or PAL["accent"], line=dict(width=1, color=PAL["accent_borda"])),
        text=textos,
        textposition="outside" if label_outside else "auto",
        cliponaxis=not label_outside,
        textfont=dict(size=15, color=PAL["texto"]), hoverinfo="skip"))
    fig.update_layout(
        template=PAL["plotly_template"], height=height,
        margin=dict(l=0, r=44 if label_outside else 16, t=6, b=0), paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"], showlegend=False,
        font=dict(family="Inter", color=PAL["texto"]),
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, tickfont=dict(size=13, color=PAL["texto"])))
    return fig


def _donut(labels, values, height=300, fmt=None):
    """Donut de composição com legenda e % nas fatias."""
    import plotly.graph_objects as go
    txt = [(fmt(v) if fmt else str(v)) for v in values]
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.58, sort=False,
        marker=dict(colors=_SERIE_CORES[:len(labels)] or None,
                    line=dict(color=PAL["paper_bg"], width=1)),
        textinfo="percent", textfont=dict(size=11, color="#111"),
        customdata=txt, hovertemplate="%{label}: %{customdata} (%{percent})<extra></extra>"))
    fig.update_layout(
        template=PAL["plotly_template"], height=height,
        margin=dict(l=0, r=0, t=6, b=0), paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"],
        font=dict(family="Inter", color=PAL["texto"], size=11),
        legend=dict(orientation="v", x=1, y=0.5, font=dict(size=10)))
    return fig


def _barv(labels, values, textos=None, cor=None, height=280):
    """Barras verticais temáticas (categorias/tempo) — espelha `_barh` p/ telas que só
    precisam de um bar chart no padrão da marca (Ficha 360 etc.). v3.3.0."""
    import plotly.graph_objects as go
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker=dict(color=cor or PAL["accent"], line=dict(width=1, color=PAL["accent_borda"])),
        text=textos if textos is not None else values, textposition="outside",
        textfont=dict(size=11, color=PAL["texto"]), hoverinfo="skip", cliponaxis=False))
    fig.update_layout(
        template=PAL["plotly_template"], height=height,
        margin=dict(l=0, r=8, t=18, b=0), paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"], showlegend=False,
        font=dict(family="Inter", color=PAL["texto"]),
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=11, color=PAL["texto"])),
        yaxis=dict(showgrid=False, zeroline=False, visible=False))
    return fig


def _receber_por_sc(centros):
    """v3.4.0 — Recebimento começando pela SC/PO: escolhe uma SC aberta e recebe todos
    os itens pendentes de uma vez (itera `registrar_recebimento_sc` por item, mesma função
    do fluxo por material — sem duplicar conversão/ledger). Complementa o 'Por Material'."""
    scs = listar_scs(apenas_abertas=True)
    if not scs:
        st.info("Nenhuma SC aberta para receber. Importe o Relatório de SCs ou crie uma SC.")
        return
    with st.container(border=True):
        opc = {
            (f"SC {s['numero_sc']} · PO {s.get('numero_po') or '—'} · "
             f"{s.get('fornecedor') or 'sem fornecedor'} · "
             f"{int(s.get('total_itens') or 0)} itens · pendente {float(s.get('total_pendente') or 0):g}"): s
            for s in scs
        }
        sel = st.selectbox("Selecione a SC / PO", list(opc.keys()), index=None,
                           placeholder="Selecione a SC / PO…", key="rec_sc_sel")
        if sel not in opc:
            st.info("Selecione uma SC para ver e receber os itens pendentes.")
            return
        sc = opc[sel]
        itens = [it for it in listar_itens_sc(sc["id"]) if (it.get("pendente") or 0) > 0]
        if not itens:
            st.success(":material/check_circle: Todos os itens desta SC já foram recebidos.")
            return

        st.markdown(f"**SC {sc['numero_sc']}** · PO `{sc.get('numero_po') or '—'}` · "
                    f"Fornecedor: {sc.get('fornecedor') or '—'} · Status: {sc.get('status') or '—'}")

        h1, h2, h3 = st.columns(3)
        forn = h1.text_input("Fornecedor", value=sc.get("fornecedor") or "", key="rec_sc_forn")
        dt_r = h2.date_input("Data Recebimento", value=date.today(), key="rec_sc_dt")
        _cc_opts = centros if centros else ["—"]
        _cc_def = next((i for i, c in enumerate(_cc_opts) if "ALMOXARIFADO" in str(c).upper()), 0)
        cc_r = h3.selectbox("Centro de Custo", _cc_opts, index=_cc_def, key="rec_sc_cc",
                            help="Padrão MRO: Almoxarifado.")

        base = pd.DataFrame([{
            "Receber": True,
            "PN": it["part_number"],
            "Item": (it.get("nome_item") or "")[:40],
            "Un": it.get("unidade") or "UN",
            "Pendente": float(it.get("pendente") or 0),
            "Qtd a receber": float(it.get("pendente") or 0),
            "NF / Documento": "",
            "_item_sc_id": int(it["id"]),
        } for it in itens])
        edit = st.data_editor(
            base, hide_index=True, width="stretch", key="rec_sc_editor",
            column_config={
                "Receber": st.column_config.CheckboxColumn("Receber", help="Desmarque itens que ainda não chegaram."),
                "PN": st.column_config.TextColumn(disabled=True),
                "Item": st.column_config.TextColumn(disabled=True),
                "Un": st.column_config.TextColumn(disabled=True),
                "Pendente": st.column_config.NumberColumn(format="%.0f", disabled=True),
                "Qtd a receber": st.column_config.NumberColumn(format="%.2f", min_value=0.0,
                    help="Default = pendente. Recebimento parcial: reduza aqui."),
                "NF / Documento": st.column_config.TextColumn(help="NF por item (opcional; usa a do lote se vazio)."),
                "_item_sc_id": None,
            },
        )
        nf_lote = st.text_input("Nota Fiscal / Documento do lote", key="rec_sc_nf",
                                help="Aplicada aos itens sem NF própria na tabela acima.")

        if st.button(":material/download: Confirmar recebimento da SC", type="primary",
                     width="stretch", key="rec_sc_btn"):
            recebidos, erros = 0, []
            for _, r in edit.iterrows():
                if not r["Receber"]:
                    continue
                qtd = float(r["Qtd a receber"] or 0)
                if qtd <= 0:
                    continue
                nf = str(r["NF / Documento"]).strip() or nf_lote.strip()
                ok, msg = registrar_recebimento_sc(
                    sc_id=sc["id"], item_sc_id=int(r["_item_sc_id"]),
                    qtd_recebida=qtd, centro_custo=cc_r,
                    solicitante="Almoxarifado", emitente="Almoxarifado",
                    fornecedor=forn, data_recebimento=str(dt_r), obs_nf=nf)
                if ok:
                    recebidos += 1
                else:
                    erros.append(f"{r['PN']}: {msg}")
            if recebidos:
                st.success(f":material/check_circle: {recebidos} item(ns) recebido(s) na SC {sc['numero_sc']}.")
            if erros:
                st.error(":material/warning: Não recebidos — " + " | ".join(erros))
            if recebidos and not erros:
                time.sleep(1.5)
                st.rerun()


def _render_receber_material():
    """Recebimento de material — Por Material (item → SC/avulsa) ou Por SC / PO.
    v3.8.0: movido do Controle de SC para uma aba da Movimentação. `_receber_por_sc`
    é module-level; nada de estado global além do já usado."""
    _modo_rec = st.radio(
        "Como quer receber?", ["📦 Por Material", "📋 Por SC / PO"],
        horizontal=True, key="rec_modo",
        help="Por Material começa pelo item; Por SC / PO escolhe a SC e recebe todos os itens pendentes de uma vez.")
    if _modo_rec == "📋 Por SC / PO":
        _receber_por_sc(listar_valores("centro_custo"))
        return
    with st.container(border=True):
        st.markdown("### :material/inventory_2: Registrar Recebimento de Material")
        st.caption("Vincule a uma SC aberta ou registre como entrada avulsa.")

        centros = listar_valores("centro_custo")
        _, item_rec, _ = sel_material("Material *", "sel_rec")

        if item_rec:
            # v2.9.0: conversão de unidades. A qtd recebida é informada na UNIDADE
            # DE COMPRA; o estoque/ledger vive na UNIDADE DE ESTOQUE. fator=1 (itens
            # de UM única) → sem diferença, tudo como antes.
            _fator_rec = float(item_rec.get('fator_conversao') or 1.0) or 1.0
            _ue_rec = item_rec.get('unidade') or 'UN'
            _uc_rec = item_rec.get('unidade_compra') or _ue_rec
            _tem_conv = abs(_fator_rec - 1.0) > 1e-9 and _uc_rec.upper() != _ue_rec.upper()

            st.markdown(f"`{item_rec['part_number']}` — **{item_rec['nome_item']}** | Saldo Atual: `{item_rec['estoque_atual']}` {_ue_rec}")
            if item_rec.get("unidade_divergente"):
                st.warning(":material/warning: Este item é comprado em unidade diferente da de estoque e ainda "
                           "**não tem fator de conversão** definido — o recebimento somará a "
                           "quantidade crua. Cadastre o fator em **Gerenciar Itens → Conversão "
                           "de unidades** antes de receber.")

            scs_item = buscar_scs_por_item(item_rec["id"], apenas_abertas=True)
            sc_sel = None

            if scs_item:
                vincular = st.checkbox(":material/link: Vincular a uma S.C. Aberta", value=True)
                if vincular:
                    opc_sc = {f"SC {s['numero_sc']} | PO: {s.get('po_item') or '—'} | Saldo: {s['pendente']} {_uc_rec}": s for s in scs_item}
                    sel_sc_str = st.selectbox("Selecionar SC", list(opc_sc.keys()), label_visibility="collapsed")
                    sc_sel = opc_sc[sel_sc_str]

                    with st.container(border=True):
                        st.markdown(f":material/check_circle: **SC {sc_sel['numero_sc']}** | PO: `{sc_sel['numero_po'] or '—'}` | Fornecedor: {sc_sel.get('fornecedor_item') or sc_sel['fornecedor'] or '—'}")
                        st.markdown(f"Solicitado: `{sc_sel['quantidade_solicitada']}` | Negociado: `{sc_sel.get('quantidade_negociada') or sc_sel['quantidade_solicitada']}` | Recebido: `{sc_sel['quantidade_recebida']}` | **Saldo Residual: `{sc_sel['pendente']}` {_uc_rec}**")
            else:
                st.info("ℹ️ Nenhuma SC aberta para este material. A entrada será registrada como avulsa.")

            # v2.9.0: qtd fora do form → conversão em tempo real (form não faz rerun).
            limite_rec = float(sc_sel["pendente"]) if sc_sel else None
            qtd_default = min(1.0, limite_rec) if limite_rec else 1.0
            lbl_qtd = f"Qtd Recebida (em {_uc_rec}) *" if _tem_conv else "Qtd Recebida *"
            if limite_rec:
                qtd_r = st.number_input(lbl_qtd, min_value=0.01, max_value=limite_rec, step=1.0, value=qtd_default, key="rec_qtd")
            else:
                qtd_r = st.number_input(lbl_qtd, min_value=0.01, step=1.0, key="rec_qtd")
            if _tem_conv:
                _incr = qtd_r / _fator_rec
                st.caption(f":material/straighten: **{qtd_r:g} {_uc_rec}** ÷ fator {_fator_rec:g} = **+{_incr:g} {_ue_rec}** no estoque.")

            with st.form("form_rec"):
                st.markdown("##### :material/download: Dados do Recebimento")
                c2, c3 = st.columns(2)
                # v2.7.1: Fornecedor não é obrigatório (pré-preenche da SC quando há).
                forn   = c2.text_input("Fornecedor", value=(sc_sel.get("fornecedor_item") or sc_sel.get("fornecedor") or "") if sc_sel else "")
                dt_r   = c3.date_input("Data Recebimento", value=date.today())

                # v2.7.1: CC não é obrigatório — recebimentos MRO caem no Almoxarifado
                # por padrão (quase todas as SCs deste time vão para o MRO).
                _cc_opts = centros if centros else ["—"]
                _cc_default = next((i for i, c in enumerate(_cc_opts)
                                    if "ALMOXARIFADO" in str(c).upper()), 0)
                cc_r   = st.selectbox("Centro de Custo", _cc_opts, index=_cc_default,
                                      help="Padrão MRO: Almoxarifado. Ajuste se necessário.")
                obs_nf = st.text_input("Nota Fiscal / Documento *" if sc_sel else "Obs / Nota Fiscal")

                rec_b  = st.form_submit_button(":material/download: Confirmar Recebimento", width="stretch", type="primary")

            if rec_b:
                if sc_sel and not obs_nf.strip():
                    st.warning(":material/warning: Informe o número da Nota Fiscal para rastreabilidade.")
                elif sc_sel:
                    # qtd_r na UM de compra; registrar_recebimento_sc converte ao estoque.
                    ok, msg = registrar_recebimento_sc(
                        sc_id=sc_sel["id"], item_sc_id=sc_sel["item_sc_id"],
                        qtd_recebida=qtd_r, centro_custo=cc_r,
                        solicitante="Almoxarifado", emitente="Almoxarifado",
                        fornecedor=forn, data_recebimento=str(dt_r), obs_nf=obs_nf
                    )
                    if ok: st.success(f":material/check_circle: **Recebimento registrado!** {msg}"); time.sleep(2); st.rerun()
                    else:  st.error(f":material/cancel: {msg}")
                else:
                    # v2.9.0: entrada avulsa converte aqui (registrar_movimentacao é
                    # primitivo em unidade de ESTOQUE — a conversão é responsabilidade
                    # da borda, como no recebimento de SC).
                    _qtd_estoque = qtd_r / _fator_rec
                    _obs_conv = (f" | convertido {qtd_r:g} {_uc_rec} ÷ {_fator_rec:g} = "
                                 f"{_qtd_estoque:g} {_ue_rec}") if _tem_conv else ""
                    ok, msg = registrar_movimentacao(
                        item_id=item_rec["id"], tipo="entrada", quantidade=_qtd_estoque,
                        centro_custo=cc_r, solicitante="Almoxarifado", emitente="Almoxarifado",
                        observacao=f"Fornecedor: {forn} | {obs_nf}{_obs_conv}"
                    )
                    if ok: st.success(f":material/check_circle: **Entrada avulsa registrada!** {msg}"); time.sleep(2); st.rerun()
                    else:  st.error(f":material/cancel: {msg}")


def _render_requisicao():
    """Requisição de material — Nova Requisição + Histórico. v3.8.0: movido da página
    própria para uma aba da Movimentação. Usa guarda if/else (NÃO st.stop()) no fluxo
    de sucesso, para não matar as abas irmãs da Movimentação."""
    st.markdown("### :material/assignment: Requisição de Material")
    st.caption("Fluxo digital: abre-se a requisição (vai para a fila) e o almoxarife entrega o "
               "material (parcial ou total), dando baixa no estoque só na entrega — com autorização.")

    aba_nova, aba_fila, aba_hist_req = st.tabs([
        ":material/edit_note: Nova Requisição",
        ":material/list_alt: Fila / Separação",
        ":material/history: Histórico"])

    autorizadores_lista = listar_valores("autorizador") or ["Gestor", "Líder", "Reserva"]

    with aba_nova:
        if "itens_req" not in st.session_state: st.session_state.itens_req = []
        if "req_confirmada" not in st.session_state: st.session_state.req_confirmada = None

        # v3.8.0: guarda if/else (sem st.stop(), que mataria as abas irmãs da Movimentação).
        if st.session_state.req_confirmada:
            st.success(f"### :material/check_circle: Requisição {st.session_state.req_confirmada} criada!")
            st.info("A requisição entrou na **Fila / Separação**. O estoque só é baixado quando o "
                    "almoxarife registrar a entrega (com autorização).")
            if st.button("Iniciar Nova Requisição", width="stretch"):
                st.session_state.req_confirmada = None
                st.rerun()
        else:
            # Padroniza os setores: registra em Configurações os que só existiam no
            # histórico (uma vez por sessão, idempotente) e monta o select a partir da
            # união (Configurações + histórico de movimentações/requisições).
            if not st.session_state.get("_setores_sync"):
                sincronizar_setores_config()
                st.session_state["_setores_sync"] = True

            # --- BLOCO 1: IDENTIFICAÇÃO ---
            with st.container():
                st.markdown("##### 1. Identificação da Demanda")
                c1, c2, c3 = st.columns(3)
                req_setor = c1.selectbox(
                    "Setor Solicitante *", options=[""] + listar_setores_conhecidos(),
                    index=0, accept_new_options=True,
                    help="Escolha um setor já usado ou digite um novo para padronizar o cadastro.")
                req_emit  = c2.text_input("Nome do Emitente *")
                opcoes_cc = [""] + (listar_valores("centro_custo") or [])
                req_cc    = c3.selectbox("Centro de Custo *", options=opcoes_cc, index=0)

            st.markdown("---")

            # --- BLOCO 2: SELEÇÃO DE MATERIAIS ---
            with st.container():
                st.markdown("##### 2. Adicionar Materiais")
                _, item_req_add, _ = sel_material("Pesquise o material para requisitar", "sel_req_add")

                if item_req_add:
                    # Card de disponibilidade rápida (cores acompanham o tema via PAL)
                    st.markdown(f"""
                        <div style="border: 1px solid {PAL['painel_borda']}; padding: 10px; border-radius: 5px; background-color: {PAL['painel_bg']}; margin-bottom: 10px;">
                            <span style="color: {PAL['accent']}; font-weight: bold;">DISPONÍVEL:</span> {item_req_add.get('estoque_atual',0)} {item_req_add.get('unidade','UN')}
                        </div>
                    """, unsafe_allow_html=True)

                with st.form("form_add_item_req", clear_on_submit=True):
                    qtd_sol = st.number_input(
                        "Qtd Solicitada *", min_value=1.0, step=1.0, value=1.0,
                        help="Quanto o setor está pedindo. A quantidade efetivamente ENTREGUE é definida "
                             "na aba Fila, na hora da entrega (pode ser parcial). Pode-se solicitar mais "
                             "do que o saldo atual — a fila mostra o que dá para atender.")
                    add_item = st.form_submit_button(":material/add: ADICIONAR À LISTA", width="stretch")

                if add_item:
                    if not item_req_add:
                        st.warning(":material/warning: Selecione um material antes de adicionar.")
                    else:
                        st.session_state.itens_req.append({
                            "item_id": item_req_add["id"], "part_number": item_req_add["part_number"],
                            "nome_item": item_req_add["nome_item"], "unidade": item_req_add.get("unidade","UN"),
                            "estoque_disponivel": item_req_add.get("estoque_atual",0),
                            "quantidade_solicitada": qtd_sol,
                        })
                        st.rerun()

            # --- LISTA DE ITENS TEMPORÁRIA ---
            if st.session_state.itens_req:
                st.markdown("###### :material/inventory_2: Itens na Requisição Atual:")
                for idx, it in enumerate(st.session_state.itens_req):
                    with st.expander(f"{it['part_number']} — {it['nome_item']}", expanded=True):
                        c_info, c_del = st.columns([5, 1])
                        c_info.write(f"**Solicitado:** {it['quantidade_solicitada']:g} {it['unidade']} "
                                     f"· _saldo hoje:_ {it.get('estoque_disponivel', 0):g}")

                        if c_del.button("Remover", key=f"rm_req_{idx}", type="primary"):
                            st.session_state.itens_req.pop(idx)
                            st.rerun()
            else:
                st.info("Aguardando adição de materiais...")

            st.markdown("---")

            # --- BLOCO 3: OBSERVAÇÕES E ENVIO ---
            # v4.7.0: autorização e SESMT saíram da criação — passaram para a ENTREGA
            # (aba Fila / Separação), que é o momento em que o material realmente sai.
            # Aqui só se ABRE o pedido; nada é baixado do estoque ainda.
            with st.container():
                st.markdown("##### 3. Observações e Envio")
                obs_req = st.text_area(
                    "Observações Gerais da Requisição", height=70,
                    placeholder="Opcional. Ex.: urgência, referência de OS, local de entrega...")

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(":material/send: CRIAR REQUISIÇÃO (enviar para a fila)", type="primary", width="stretch"):
                erros = []
                if not req_setor or not req_emit:
                    erros.append("Preencha Setor e Emitente (campos com *).")
                if not st.session_state.itens_req:
                    erros.append("A lista de materiais está vazia.")

                if erros:
                    for e in erros: st.error(e)
                else:
                    with st.spinner("Criando requisição..."):
                        ok, resultado = criar_requisicao(
                            setor=req_setor, emitente=req_emit, centro_custo=req_cc,
                            autorizador_tipo="", autorizador_nome="",
                            entrega_individual=False, destinatarios=[],
                            sesmt=False, sesmt_responsavel="",
                            itens=st.session_state.itens_req, observacoes=obs_req
                        )
                        if ok:
                            st.session_state.itens_req = []
                            st.session_state.req_confirmada = resultado
                            st.rerun()
                        else:
                            st.error(f"Erro ao criar requisição: {resultado}")

    # --- ABA: FILA / SEPARAÇÃO (v4.7.0) ---
    with aba_fila:
        st.markdown("### :material/list_alt: Fila de Separação")
        st.caption("Requisições aguardando entrega. Registre a saída (parcial ou total) — só aqui o "
                   "estoque é baixado. Material só sai com autorização (gestor; +SESMT se for EPI/SSO).")

        abertas = listar_requisicoes_abertas()
        if not abertas:
            st.success(":material/inventory: Nenhuma requisição pendente na fila. Tudo em dia!")
        else:
            mp1, mp2 = st.columns(2)
            mp1.metric(":material/pending_actions: Requisições na fila", len(abertas))
            mp2.metric(":material/hourglass_top: Mais antiga",
                       str(min(a["data_hora"] for a in abertas))[:10])

            def _fmt_fila(a):
                _falt = int(a.get("itens_pendentes") or 0)
                return (f"{a['numero_requisicao']} · {a['setor']} · {a['emitente']} "
                        f"· {a['status']} · {_falt} pendente(s)")

            opc_fila = {_fmt_fila(a): a for a in abertas}
            sel_f = st.selectbox("Escolha a requisição para separar/entregar:",
                                 [""] + list(opc_fila.keys()), key="fila_sel")

            req = opc_fila.get(sel_f) if sel_f else None
            if req:
                req_id = req["id"]
                st.markdown(f"#### :material/assignment: {req['numero_requisicao']} "
                            f"— {req['setor']} · {req['emitente']}")
                st.caption(f"Aberta em {str(req['data_hora'])[:16]} · "
                           f"C.Custo: {req.get('centro_custo') or '—'} · Status: **{req['status']}**")
                if req.get("observacoes"):
                    st.info(f":material/sticky_note_2: {req['observacoes']}")

                itens_f = listar_itens_requisicao(req_id)

                st.markdown("##### 1. Itens — quanto entregar agora")
                entregas = []
                for it in itens_f:
                    falta = float(it["quantidade_solicitada"]) - float(it["quantidade_atendida"])
                    disp = float(it.get("estoque_atual") or 0)
                    ci1, ci2, ci3 = st.columns([3, 2, 2])
                    ci1.markdown(f"**{it['part_number']}** — {it['nome_item']}")
                    ci1.caption(f"Solicitado {float(it['quantidade_solicitada']):g} · "
                                f"atendido {float(it['quantidade_atendida']):g} · "
                                f"falta {max(falta, 0):g} {it['unidade']}")
                    ci2.markdown(f":material/inventory_2: Disp.: **{disp:g}** {it['unidade']}")
                    if falta <= 0:
                        ci3.success("Completo")
                        continue
                    _max = float(min(falta, disp))
                    q = ci3.number_input(
                        "Entregar", min_value=0.0,
                        max_value=float(disp) if disp > 0 else 0.0,
                        value=_max if _max > 0 else 0.0, step=1.0,
                        key=f"ent_{req_id}_{it['id']}",
                        help="Sem saldo em estoque para este item." if disp <= 0 else None)
                    if q > 0:
                        entregas.append({"item_req_id": it["id"], "quantidade": float(q)})

                st.markdown("##### 2. Autorização da saída")
                ca1, ca2 = st.columns(2)
                f_aut_tipo = ca1.selectbox("Tipo de Autorizador *", autorizadores_lista, key=f"aut_t_{req_id}")
                f_aut_nome = ca2.text_input("Nome do Autorizador (gestor) *", key=f"aut_n_{req_id}")
                f_sesmt = st.checkbox("Material SESMT? (EPI/SSO — exige responsável do SESMT)",
                                      key=f"sesmt_{req_id}")
                f_sesmt_resp = ""
                if f_sesmt:
                    f_sesmt_resp = st.text_input("Responsável SESMT *", key=f"sesmt_r_{req_id}")

                if st.button(":material/local_shipping: REGISTRAR ENTREGA", type="primary",
                             width="stretch", key=f"btn_ent_{req_id}"):
                    if not entregas:
                        st.warning("Informe ao menos um item com quantidade a entregar.")
                    else:
                        ok, res = entregar_requisicao(
                            req_id, entregas, f_aut_tipo, f_aut_nome, f_sesmt, f_sesmt_resp)
                        if ok:
                            st.success(f":material/check_circle: Entrega registrada. Status: **{res}**.")
                            st.rerun()
                        else:
                            st.error(f":material/cancel: {res}")

                st.markdown("---")
                with st.expander(":material/add_circle: Adicionar item (o caso 'põe no mesmo pedido')"):
                    _, item_add_f, _ = sel_material("Material para incluir nesta requisição", f"add_fila_{req_id}")
                    qadd = st.number_input("Qtd Solicitada", min_value=1.0, step=1.0, value=1.0, key=f"qadd_{req_id}")
                    if st.button(":material/add: Incluir item", key=f"btn_add_{req_id}"):
                        if not item_add_f:
                            st.warning("Selecione um material.")
                        else:
                            ok, res = adicionar_itens_requisicao(
                                req_id, [{"item_id": item_add_f["id"], "quantidade_solicitada": qadd}])
                            if ok:
                                st.success(res)
                                st.rerun()
                            else:
                                st.error(res)

                if req["status"] == "Aberta":
                    if st.button(":material/cancel: Cancelar requisição (nada foi entregue)",
                                 key=f"btn_cancel_{req_id}"):
                        ok, res = cancelar_requisicao(req_id)
                        if ok:
                            st.warning(res)
                            st.rerun()
                        else:
                            st.error(res)

    # --- ABA: HISTÓRICO ---
    with aba_hist_req:
        st.markdown("### :material/history: Histórico de Requisições")
        reqs = listar_requisicoes(limit=500)
        if not reqs:
            st.info("Nenhuma requisição registrada até o momento.")
        else:
            df_all = pd.DataFrame(reqs)

            # v3.4.0 — resumo em métricas
            _itens = int(pd.to_numeric(df_all.get("total_itens"), errors="coerce").fillna(0).sum())
            m1, m2, m3 = st.columns(3)
            m1.metric(":material/receipt_long: Requisições", len(df_all))
            m2.metric(":material/inventory_2: Itens requisitados", _itens)
            m3.metric(":material/domain: Setores atendidos", int(df_all["setor"].nunique()))

            # v3.4.0 — filtros (setor + busca livre)  ·  v4.3.0 — busca também por PN/material
            fc1, fc2 = st.columns(2)
            setores_op = ["Todos"] + sorted(s for s in df_all["setor"].dropna().unique())
            f_set = fc1.selectbox("Setor", setores_op, key="hist_req_setor")
            f_txt = fc2.text_input(":material/search: Buscar (Nº, emitente, autorizador ou PN/material)", key="hist_req_busca")

            fil = df_all.copy()
            if f_set != "Todos":
                fil = fil[fil["setor"] == f_set]
            if f_txt.strip():
                t = f_txt.strip().lower()
                # v4.3.0 — índice PN/nome por requisição (1 query; só quando há busca).
                mapa_pn = mapa_pn_por_requisicao()
                fil = fil[fil.apply(
                    lambda r: t in str(r.get("numero_requisicao", "")).lower()
                    or t in str(r.get("emitente", "")).lower()
                    or t in str(r.get("autorizador_nome", "")).lower()
                    or t in mapa_pn.get(r.get("id"), ""), axis=1)]

            # v3.4.0 — mini-gráfico: requisições por setor
            if not fil.empty:
                by_set = fil["setor"].fillna("—").value_counts()
                if len(by_set):
                    st.plotly_chart(
                        _barv(list(by_set.index), [int(v) for v in by_set.values]),
                        width="stretch", config={"displayModeBar": False})

            # v4.1.0 — "Detalhes da Requisição" vem ANTES da tabela e mais completo
            # (emitente, autorizador, centro de custo, setor e a lista de itens).
            st.markdown("#### :material/search: Detalhes da Requisição")
            opcoes_req = {f"REQ-{r['numero_requisicao']} | {r['setor']} | {str(r['data_hora'])[:10]}": r
                          for r in fil.to_dict("records")}
            sel_req = st.selectbox("Escolha uma requisição para ver os detalhes:",
                                   [""] + list(opcoes_req.keys()))

            if sel_req:
                r_det = opcoes_req[sel_req]
                with st.container(border=True):
                    st.markdown(f"**Resumo REQ-{r_det['numero_requisicao']}** · "
                                f"{str(r_det.get('data_hora',''))[:16]} · "
                                f"Status: **{r_det.get('status') or '—'}**")
                    c_a, c_b, c_c, c_d = st.columns(4)
                    c_a.write(f":material/person: **Emitente:** {r_det['emitente']}")
                    c_b.write(f":material/edit: **Autorizador:** {r_det.get('autorizador_nome') or '—'}")
                    c_c.write(f":material/apartment: **C.Custo:** {r_det['centro_custo']}")
                    c_d.write(f":material/domain: **Setor:** {r_det.get('setor') or '—'}")

                    itens_det = listar_itens_requisicao(r_det["id"])
                    if itens_det:
                        df_det = pd.DataFrame(itens_det)[["part_number", "nome_item", "quantidade_solicitada", "quantidade_atendida", "unidade"]]
                        df_det.columns = ["PN", "Material", "Solicitado", "Atendido", "UN"]
                        st.caption(f"{len(df_det)} item(ns) nesta requisição:")
                        st.dataframe(df_det, width="stretch", hide_index=True)
                    else:
                        st.caption("Sem itens detalhados para esta requisição.")

            st.markdown("---")
            st.markdown("##### :material/table_rows: Todas as requisições")
            df_reqs = fil[["numero_requisicao", "data_hora", "status", "setor", "emitente",
                           "autorizador_nome", "total_itens"]].copy()
            df_reqs.columns = ["Nº Req", "Data/Hora", "Status", "Setor", "Emitente",
                               "Autorizador", "Qtd Itens"]
            st.dataframe(df_reqs, width="stretch", hide_index=True)


def _linhas(x, series, height=260):
    """Gráfico de linhas multi-série (WK/tempo). series = [(nome, valores, cor)]. v3.5.0."""
    import plotly.graph_objects as go
    fig = go.Figure()
    for nome, vals, cor in series:
        fig.add_trace(go.Scatter(x=x, y=vals, name=nome, mode="lines+markers",
                                 line=dict(color=cor, width=2), marker=dict(size=5)))
    fig.update_layout(
        template=PAL["plotly_template"], height=height,
        margin=dict(l=0, r=8, t=10, b=0), paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"], font=dict(family="Inter", color=PAL["texto"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=11)),
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=PAL["texto"])),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=10, color=PAL["texto"])))
    return fig


def _barras_agrupadas(x, series, height=260, mostrar_valores=False):
    """Barras verticais agrupadas. series = [(nome, valores, cor)]. v3.5.0.
    `mostrar_valores=True` escreve a quantidade em cima de cada barra — evita depender do
    hover (ex.: Histórico mensal Entradas × Saídas). v4.1.0."""
    import plotly.graph_objects as go
    fig = go.Figure()
    for nome, vals, cor in series:
        fig.add_trace(go.Bar(
            x=x, y=vals, name=nome, marker_color=cor,
            text=[f"{v:g}" for v in vals] if mostrar_valores else None,
            textposition="outside" if mostrar_valores else "none",
            textfont=dict(size=11, color=PAL["texto"]), cliponaxis=False))
    fig.update_layout(
        barmode="group", template=PAL["plotly_template"], height=height,
        margin=dict(l=0, r=8, t=18 if mostrar_valores else 10, b=0), paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"], font=dict(family="Inter", color=PAL["texto"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=11)),
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=PAL["texto"])),
        yaxis=dict(showgrid=False, zeroline=False, visible=False))
    return fig


def _bloco_top(titulo, itens, label_fn, value_key, value_fmt, cor=None,
               height=300, caption=None, label_outside=False):
    """Renderiza um card com um ranking Top N em barras horizontais (maior no topo).
    `label_outside=True` põe os números fora das barras (bom p/ contagens pequenas)."""
    with st.container(border=True):
        st.markdown(f"#### {titulo}")
        if caption:
            st.caption(caption)
        if not itens:
            st.caption("Sem dados para o período.")
            return
        labels = [label_fn(x) for x in itens][::-1]
        values = [x[value_key] for x in itens][::-1]
        textos = [value_fmt(x[value_key]) for x in itens][::-1]
        st.plotly_chart(_barh(labels, values, textos, cor, height, label_outside),
                        width="stretch", config={"displayModeBar": False})


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de Drill-down e Ajuda (v4.2.0) — explicabilidade clicável
# ──────────────────────────────────────────────────────────────────────────────

def _ajuda_popover(titulo: str, chave_ajuda: str = None) -> None:
    """Renderiza um título com popover "?" lado a lado.
    Se chave_ajuda está em AJUDA_DADOS, mostra o texto. Caso contrário, silencia."""
    from services.ajuda_conteudo import AJUDA_DADOS
    c1, c2 = st.columns([0.9, 0.1])
    c1.write(titulo)
    if chave_ajuda and chave_ajuda in AJUDA_DADOS:
        with c2.popover("❓"):
            st.markdown(AJUDA_DADOS[chave_ajuda], help=None)


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



def _render_ficha_visao_geral(ficha):
    """Corpo original da Ficha 360 (v4.4.0: extraido para a 1a aba \"Visao Geral\")."""
    it = ficha["item"]
    rep = ficha["reposicao"]
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
                unsafe_allow_html=True)
        with st.expander(":material/image: Imagem do produto"):
            up = st.file_uploader(
                "Enviar/atualizar (png/jpg/webp, até 5 MB)",
                type=["png", "jpg", "jpeg", "webp", "gif"], key="ficha_img_up")
            cb1, cb2 = st.columns(2)
            if cb1.button(":material/save: Salvar", key="ficha_img_save",
                          disabled=up is None, width="stretch"):
                ok, msg = salvar_imagem_item(it["id"], up.name, up.getvalue())
                if ok:
                    st.success("Imagem salva."); st.rerun()
                else:
                    st.error(msg)
            if ficha["imagem_abs"] and cb2.button(
                    ":material/delete: Remover", key="ficha_img_del", width="stretch"):
                remover_imagem_item(it["id"]); st.rerun()
    with col_cad:
        st.subheader(f"{it['part_number']} — {it['nome_item']}")
        # v4.1.0: "Setor que mais consome" (top do consumo real por setor) no lugar do
        # antigo "Setor responsável" (campo estático, ~98% "Improdutivo"); Local mostra
        # as 2 locações quando houver.
        _top_setor = (ficha["departamentos"]["por_setor"][0]["chave"]
                      if ficha["departamentos"]["por_setor"] else "—")
        _locais = " · ".join(
            x for x in [it.get('local_armazenagem'), it.get('local_armazenagem_2')] if x
        ) or "—"
        st.markdown(
            f"**Categoria/Tipo:** {it.get('tipo_material') or '—'}  \n"
            f"**Unidade:** {it.get('unidade') or '—'} · "
            f"**Criticidade:** {it.get('importancia') or '—'}  \n"
            f"**Setor que mais consome:** {_top_setor}  \n"
            f"**Local:** {_locais}"
            + (f" · Caixa {it.get('caixa_identificacao')}" if it.get('caixa_identificacao') else "")
        )
        if it.get("descricao"):
            st.caption(it["descricao"])

        # v2.7.0 — Situação de consumo (real = saída por requisição)
        if it.get("sem_movimentacao"):
            st.caption("⚪ **Situação de consumo:** Sem movimentação "
                       "(nunca teve saída por requisição) — fora da lista de compra.")
        else:
            _ult = it.get("ultima_requisicao_data")
            _ult_txt = f" · última em {fmt(_ult)}" if _ult else ""
            st.caption(f"🟢 **Situação de consumo:** {it.get('qtd_requisicoes', 0)} "
                       f"requisição(ões){_ult_txt}.")

    # ── Conversão de unidades (v2.9.0) ────────────────────────────────
    _fat_f = float(it.get("fator_conversao") or 1.0) or 1.0
    _uc_f = it.get("unidade_compra")
    if abs(_fat_f - 1.0) > 1e-9 and _uc_f:
        st.caption(f":material/sync: **Conversão:** compra em **{_uc_f}** · **1 {it.get('unidade') or 'UN'}** "
                   f"de estoque = **{_fat_f:g} {_uc_f}** (fator {_fat_f:g}).")

    # ── Recomendação de reposição (read-only, reusa v2.5) ─────────────
    un = it.get("unidade") or "UN"
    if it.get("sem_movimentacao"):
        st.info("⚪ **Sem movimentação** — item sem consumo real; fora da lista "
                "de compra. Revise no **Assistente de Reposição** (opção "
                "\"Mostrar itens sem movimentação\") se for um spare a manter em estoque.")
    elif rep["precisa"] and rep["qtd_sugerida"] > 0:
        st.warning(f":material/shopping_cart: **{rep['prioridade']}** — repor **{rep['qtd_sugerida']} "
                   f"{un}**. {rep['justificativa']}")
    elif rep["precisa"]:
        # v2.7.1: gatilho ativo mas qtd = 0 → o saldo residual já cobre o alvo
        # (antes aparecia "repor 0", confuso).
        st.info(f"🟡 **{rep['prioridade']}** — **sem compra agora**: o saldo residual "
                f"(**{_g(it.get('estoque_em_transito'))} {un}** já negociados) "
                f"cobre o alvo de **{_g(rep['alvo'])} {un}**. Reavaliar quando o material chegar.")
    else:
        st.success(":material/check_circle: Sem necessidade de reposição no momento "
                   "(estoque + saldo residual cobrem o horizonte).")

    # ── Estoque / cobertura / giro ────────────────────────────────────
    st.divider()
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Estoque atual", _g(it.get("estoque_atual")))
    e2.metric("Quantidade Mínima", _g(it.get("estoque_minimo")),
              help="Baseado no reajuste de compras.")
    e3.metric("Quantidade Máxima", _g(it.get("estoque_maximo")),
              help="Baseado no reajuste de compras.")
    e4.metric("Saldo Item (PO)", _g(it.get("estoque_em_transito")),
              help="Qtd já negociada em pedidos (PO/SC) aprovados que ainda falta chegar.")

    cob = it.get("dias_cobertura")
    giro = ficha["giro"]
    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Dias até acabar",
              f"{cob:.0f} d" if cob is not None and cob < PREVISAO_RUPTURA_SEM_RISCO else "—",
              help="Quantos dias o estoque atual ainda dura no ritmo de consumo atual "
                   "(estoque atual ÷ consumo médio diário). '—' = sem consumo registrado, "
                   "logo não há previsão de término.")
    tend = it.get("tendencia_label")
    tend_txt = (f"{tend} {'+' if (it.get('tendencia_pct') or 0) >= 0 else ''}"
                f"{_g(it.get('tendencia_pct'))}%") if tend else None
    g2.metric("Consumo/dia", f"{_g1(it.get('consumo_medio_diario'))} {un}/dia", delta=tend_txt,
              delta_color="inverse",
              help="Média de quanto sai por dia deste item, pelas saídas reais por requisição "
                   "na janela de 30 dias. A seta indica a tendência vs. os 30 dias anteriores.")
    _cons_mes = (ficha.get("classificacao") or {}).get("consumo_mensal_ponderado")
    g3.metric("Consumo/Mensal",
              f"{_g1(_cons_mes)} {un}/mês" if _cons_mes is not None else "—", delta=tend_txt,
              delta_color="inverse",
              help="Consumo médio por mês: média PONDERADA dos últimos 3 meses completos, com o "
                   "mês mais recente pesando mais (3/2/1). Usa as saídas reais por mês (dias úteis "
                   "já embutidos); meses sem saída contam 0 e a média decai se o item parar. A "
                   "seta é a mesma tendência do Consumo/dia.")
    g4.metric("Giro anual", _g(giro["giro_anual"]),
              help="Quantas vezes o estoque \"vira\" no ano: "
                   "(saídas dos últimos 90 d ÷ estoque médio das fotos diárias) × (365 ÷ 90). "
                   "Base: estoque_snapshots (fotos diárias do saldo) + saídas de movimentações. "
                   "Maior = gira mais rápido; menor = parado. "
                   f"Tempo médio em estoque: "
                   f"{giro['tempo_medio_dias'] if giro['tempo_medio_dias'] else '—'} d · "
                   f"baseado em {giro['n_snapshots']} fotos.")
    lt_calc = it.get("lead_time_calculado")
    g5.metric("Lead time (Compras)", f"{int(it.get('lead_time_dias') or 0)} d",
              help=(f"Calculado (sugestão): {int(lt_calc)} d "
                    f"({it.get('lead_time_calculado_amostras') or 0} amostras, "
                    f"{it.get('lead_time_calculado_origem') or '—'})" if lt_calc
                    else "Sem lead time calculado ainda."))

    # ── Consumo (30/60/90) + Valor ────────────────────────────────────
    cc1, cc2 = st.columns(2)
    with cc1:
        with st.container(border=True):
            st.markdown("##### :material/trending_down: Consumo médio/dia por janela")
            st.caption("Média de saída por dia em 3 janelas (30/60/90 dias). Comparar as três "
                       "mostra se o consumo está **acelerando** (30d > 90d) ou **desacelerando**.")
            _cons_j = [round(it.get("consumo_30d") or 0, 1),
                       round(it.get("consumo_60d") or 0, 1),
                       round(it.get("consumo_90d") or 0, 1)]
            st.plotly_chart(
                _barv(["30 dias", "60 dias", "90 dias"], _cons_j,
                      textos=[f"{v:g}" for v in _cons_j]),
                width="stretch", config={"displayModeBar": False})
    with cc2:
        with st.container(border=True):
            st.markdown("##### :material/payments: Valor")
            st.caption("Quanto este item representa em dinheiro: **parado em estoque** hoje e "
                       "**consumido no ano** (estimado pelo último preço de compra).")
            vc = ficha["valor"]["valor_consumido"]
            st.metric("Valor em estoque",
                      f"R$ {ficha['valor']['valor_estoque']:,.2f}")
            # v2.7.1: valor unitário (preço de referência) logo abaixo
            _preco_un = vc.get("preco") or 0
            st.caption(f"Valor unitário: **{vc['moeda']} {_preco_un:,.2f}** / {un} "
                       f"· origem {vc['origem']}")
            st.metric(f"Valor consumido (YTD {date.today().year})",
                      f"{vc['moeda']} {vc['valor']:,.2f}",
                      help=f"Estimativa (último preço, origem {vc['origem']}). "
                           f"Acumulado de 01/01/{date.today().year} até hoje.")
            if ficha["abc"]:
                st.caption(f"Curva ABC (valor): classe **{ficha['abc']['classe']}** "
                           f"· {ficha['abc']['pct_acumulado']}% acumulado.")

    # ── Evolução de preço ─────────────────────────────────────────────
    ep = ficha["evolucao_preco"]
    if ep:
        st.markdown("##### :material/trending_up: Evolução de preço")
        df_ep = pd.DataFrame(ep)
        df_ep["data"] = pd.to_datetime(df_ep["data"], errors="coerce")
        st.line_chart(df_ep.dropna(subset=["data"]).set_index("data")["preco_unitario"])

    # ── Quem consome (departamentos / centros de custo) ───────────────
    st.markdown("##### :material/group: Quem consome (últimos 180 dias)")
    dep = ficha["departamentos"]
    if dep["total"] <= 0:
        st.caption("Sem saídas registradas no período.")
    else:
        d1, d2 = st.columns(2)
        d1.caption("Por centro de custo")
        d1.dataframe(pd.DataFrame([
            {"Centro de custo": r["chave"], "Qtd": r["qtd"], "%": r["pct"]}
            for r in dep["por_centro_custo"]], ), hide_index=True, width="stretch")
        d2.caption("Por setor")
        d2.dataframe(pd.DataFrame([
            {"Setor": r["chave"], "Qtd": r["qtd"], "%": r["pct"]}
            for r in dep["por_setor"]]), hide_index=True, width="stretch")

    # ── Fornecedores ──────────────────────────────────────────────────
    with st.expander(f":material/apartment: Fornecedores ({len(ficha['fornecedores'])})"):
        fs = ficha["fornecedores"]
        if not fs:
            st.caption("Sem fornecedores vinculados (vêm dos pedidos do Relatório de SCs).")
        else:
            st.dataframe(pd.DataFrame([{
                "Fornecedor": f["fornecedor"], "Último Preço": f["ultimo_preco"],
                "Moeda": f["moeda"], "Nº Compras": f["n_compras"],
                "Lead Time (d)": f["lead_time_fornecedor"], "E-mail": f["email"] or "—",
                "Melhor preço": "⭐" if f.get("melhor") else "",
            } for f in fs]), hide_index=True, width="stretch")

    # ── Histórico de SCs / POs ────────────────────────────────────────
    with st.expander(f":material/receipt_long: Histórico de SCs / POs ({len(ficha['scs_pos'])})"):
        sp = ficha["scs_pos"]
        if not sp:
            st.caption("Nenhuma SC registrada para este item.")
        else:
            st.dataframe(pd.DataFrame([{
                "SC": s["numero_sc"], "PO": s.get("po_item") or s.get("numero_po") or "—",
                "Fornecedor": s.get("fornecedor_item") or "—", "Status": s.get("status"),
                "Abertura": fmt(s.get("data_abertura")),
                "Solic.": s.get("quantidade_solicitada"),
                "Receb.": s.get("quantidade_recebida"), "Pendente": s.get("pendente"),
            } for s in sp]), hide_index=True, width="stretch")

    # ── Histórico de movimentações ────────────────────────────────────
    with st.expander(f":material/sync: Movimentações recentes ({len(ficha['movimentacoes'])})"):
        mv = ficha["movimentacoes"]
        if not mv:
            st.caption("Sem movimentações.")
        else:
            st.dataframe(pd.DataFrame([{
                "Data": fmt(m.get("data_hora")), "Tipo": m.get("tipo"),
                "Qtd": m.get("quantidade"), "Saldo": m.get("saldo_apos"),
                "Centro de custo": m.get("centro_custo") or "—",
                "Setor": m.get("setor") or "—", "Obs": m.get("observacao") or "",
            } for m in mv]), hide_index=True, width="stretch")

    # ── Histórico de Part Number ──────────────────────────────────────
    if ficha["historico_pn"]:
        with st.expander(f":material/bookmark: Histórico de Part Number ({len(ficha['historico_pn'])})"):
            st.dataframe(pd.DataFrame(ficha["historico_pn"]),
                         hide_index=True, width="stretch")

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
            st.caption(f"ADI {dem['adi']} · CV² {dem['cv2']} · "
                       f"{dem['n_eventos']} semana(s) com consumo · "
                       f"confiança {dem.get('confianca', '—')}.")
    with xd2:
        _cx = xyz.get("classe")
        if _cx:
            _rot = {"X": "estável", "Y": "variável", "Z": "errático"}.get(_cx, "")
            st.markdown(f"**XYZ:** **{_cx}** ({_rot})")
            st.caption(f"Coef. de variação mensal {xyz.get('cv')} · "
                       f"{xyz.get('n_meses')} mês(es) · confiança {xyz.get('confianca', '—')}.")
        else:
            st.markdown("**XYZ:** —")
            st.caption("Precisa de ≥2 meses de consumo para medir a variabilidade.")

    if cm:
        st.markdown("###### :material/calendar_month: Consumo real por mês")
        st.plotly_chart(
            _barv([_mes_label(x["mes"]) for x in cm],
                  [round(x["qtd"], 1) for x in cm],
                  textos=[f"{round(x['qtd'], 1):g}" for x in cm]),
            width="stretch", config={"displayModeBar": False})

    if not saz.get("disponivel"):
        st.caption(f":material/eco: **Sazonalidade:** amadurecendo — "
                   f"{saz.get('meses_atuais', 0)}/{saz.get('meses_necessarios', 12)} "
                   "meses (precisa de 1 ciclo anual completo para um perfil confiável).")
    st.caption(f":material/calendar_month: Indicadores de série baseados em ~{mat['dias']} dias de histórico — "
               "diagnóstico que amadurece conforme os dados acumulam. A base do "
               "Compras (mín/máx/lead time/categoria) permanece intocada.")


def _render_ficha_guarda_chuva(ficha):
    """[DEPRECADO em v4.9.0 — NÃO MAIS LIGADO À UI] A sub-aba Guarda-Chuva saiu da Ficha
    360 e virou um controle MANUAL próprio em "Controle de SC → ☂️ Guarda-Chuva"
    (`_render_guarda_chuva_controle`, tabela `guarda_chuva`). Esta versão baseada em SCs
    reais (`ficha['scs_pos']`) fica aqui só como referência e pode ser removida num
    follow-up (os serviços que ela usa seguem cobertos por test_v457).

    v4.4.0 — Guarda-Chuva: pedidos (SC/PO) do material por fornecedor, com kanban de
    4 estágios (Pedido Colocado → Aguardando Entrega → NF Emitida → Recebido) e o saldo
    residual pendente agregado por fornecedor, sobre ficha['scs_pos'].

    v4.5.7 — kanban FUNCIONAL: cada card tem 'Editar / Receber' que abre um dialog para
    editar os metadados do pedido (Nº PO, datas, NF, qtd negociada) via
    `atualizar_pedido_guarda_chuva` e registrar entrega via `registrar_recebimento_sc`
    (ledger). O estágio continua DERIVADO dos campos — mover o card = editar o campo que o
    define; nada de estágio armazenado."""
    it = ficha["item"]
    scs = ficha.get("scs_pos") or []
    un = it.get("unidade") or ""

    # v4.5.6 — removidos os cards "Em trânsito (pedidos)" e "Saldo total projetado"
    # (pedido do usuário); o saldo pendente já é detalhado no kanban e na tabela por
    # fornecedor logo abaixo.
    est = float(it.get("estoque_atual") or 0)
    st.metric("Saldo em estoque", f"{est:g} {un}")

    if not scs:
        st.info("Este material não tem pedidos (SC/PO) registrados.")
        return

    fornecedores = sorted({(s.get("fornecedor_item") or "Sem fornecedor") for s in scs})
    escolha = st.selectbox("Fornecedor", ["Todos"] + fornecedores, key="gc_fornecedor")
    linhas = scs if escolha == "Todos" else [
        s for s in scs if (s.get("fornecedor_item") or "Sem fornecedor") == escolha]

    def _estagio(s):
        if (s.get("pendente") or 0) <= 0:
            return "Recebido"
        if s.get("documento_nf"):
            return "NF Emitida"
        if s.get("data_prev_nfe") or s.get("data_necessidade"):
            return "Aguardando Entrega"
        return "Pedido Colocado"

    st.markdown("##### :material/view_kanban: Kanban de pedidos")
    estagios = ["Pedido Colocado", "Aguardando Entrega", "NF Emitida", "Recebido"]
    cols = st.columns(len(estagios))
    for col, nome in zip(cols, estagios):
        with col:
            grupo = [s for s in linhas if _estagio(s) == nome]
            st.markdown(f"**{nome}** · {len(grupo)}")
            for s in grupo:
                with st.container(border=True):
                    st.caption(f"SC {s.get('numero_sc') or '—'} · "
                               f"PO {s.get('po_item') or s.get('numero_po') or '—'}")
                    st.markdown(f"**{s.get('fornecedor_item') or '—'}**")
                    st.caption(
                        f"Neg. {(s.get('quantidade_negociada') or 0):g} · "
                        f"Receb. {(s.get('quantidade_recebida') or 0):g} · "
                        f"Pend. {(s.get('pendente') or 0):g} {un}")
                    _prev = s.get("data_prev_nfe") or s.get("data_necessidade")
                    if _prev:
                        st.caption(f":material/event: Prev.: {str(_prev)[:10]}")
                    if s.get("documento_nf"):
                        st.caption(f":material/receipt_long: NF {s.get('documento_nf')}")
                    if st.button(":material/edit: Editar / Receber",
                                 key=f"gc_edit_{s['item_sc_id']}", width="stretch"):
                        st.session_state["_gc_pedido_edit"] = int(s["item_sc_id"])
                        st.rerun()

    grupos = agrupar_saldo_residual_por_fornecedor(scs)
    if grupos:
        st.markdown("##### :material/inventory: Saldo residual pendente por fornecedor")
        df = pd.DataFrame([{
            "Fornecedor": g["fornecedor"],
            "Pedidos c/ saldo": g["n_pedidos"],
            f"Saldo pendente ({un})": round(g["saldo_pendente"], 2),
        } for g in grupos])
        st.dataframe(df, width="stretch", hide_index=True)


def _clear_gc_edit():
    st.session_state.pop("_gc_pedido_edit", None)


@st.dialog("Pedido — Guarda-Chuva", width="large", on_dismiss=_clear_gc_edit)
def _dialog_pedido_guarda_chuva():
    """v4.5.7 — Edita um pedido (linha de itens_sc) e registra recebimento sem sair do
    kanban. Relê o pedido do banco a cada render (`obter_pedido_sc`) para refletir
    recebimentos parciais feitos aqui dentro. Persistência: metadados via
    `atualizar_pedido_guarda_chuva` (não toca o ledger); entrada de estoque via
    `registrar_recebimento_sc` (estoque + movimentações + status, atômico)."""
    item_sc_id = st.session_state.get("_gc_pedido_edit")
    p = obter_pedido_sc(item_sc_id) if item_sc_id else None
    if not p:
        st.info("Pedido não encontrado (pode ter sido removido).")
        return
    un = p.get("unidade") or ""
    pend = float(p.get("pendente") or 0)

    # Estágio atual — mesma derivação de _estagio (o card não guarda estágio).
    if pend <= 0:
        estagio_atual = "Recebido"
    elif p.get("documento_nf"):
        estagio_atual = "NF Emitida"
    elif p.get("data_prev_nfe") or p.get("data_necessidade"):
        estagio_atual = "Aguardando Entrega"
    else:
        estagio_atual = "Pedido Colocado"

    st.markdown(f"`{p.get('part_number') or '—'}` — **{p.get('nome_item') or '—'}**")
    st.caption(f"SC {p.get('numero_sc') or '—'} · Estágio atual: **{estagio_atual}**")
    m1, m2, m3 = st.columns(3)
    m1.metric("Negociada", f"{(p.get('quantidade_negociada') or 0):g} {un}")
    m2.metric("Recebida", f"{(p.get('quantidade_recebida') or 0):g} {un}")
    m3.metric("Pendente", f"{pend:g} {un}")

    # ── Form 1 — dados do pedido (metadados; NÃO mexe no ledger) ──────────────────
    with st.form("form_gc_pedido"):
        st.markdown("##### :material/edit: Dados do pedido")
        c1, c2 = st.columns(2)
        po   = c1.text_input("Nº PO", value=p.get("po_item") or "")
        forn = c2.text_input("Fornecedor", value=p.get("fornecedor_item") or "")
        qtd_neg = c1.number_input("Qtd negociada", min_value=0.0, step=1.0,
                                  value=float(p.get("quantidade_negociada") or 0))
        nf = c2.text_input("NF (documento)", value=p.get("documento_nf") or "",
                           help="Preencher move o card para 'NF Emitida'. Limpar volta para "
                                "'Aguardando Entrega'.")
        c3, c4 = st.columns(2)
        nec = c3.date_input("Data necessidade", value=fmt_date_input(p.get("data_necessidade")))
        sem_prev = c4.checkbox("Sem previsão de entrega", value=not bool(p.get("data_prev_nfe")))
        prev = None if sem_prev else c4.date_input(
            "Data prev. entrega", value=fmt_date_input(p.get("data_prev_nfe")))
        salvar = st.form_submit_button(":material/save: Salvar dados", type="primary",
                                       width="stretch")
    if salvar:
        ok, msg = atualizar_pedido_guarda_chuva(item_sc_id, {
            "numero_po": po, "fornecedor_item": forn, "quantidade_pedido": qtd_neg,
            "documento_nf": nf,
            "data_necessidade": str(nec) if nec else None,
            "data_prev_nfe": str(prev) if prev else None,
        })
        if ok:
            st.success(":material/check_circle: Pedido atualizado.")
            st.rerun()
        else:
            st.error(f":material/cancel: {msg}")

    # ── Form 2 — registrar recebimento (Qtd entregue → ledger) ────────────────────
    if pend > 0:
        with st.form("form_gc_receber"):
            st.markdown("##### :material/download: Registrar recebimento")
            st.caption("Mover para 'Recebido' = registrar a entrega: atualiza o estoque e o "
                       "histórico de movimentações. Reverter um recebimento (estorno) não é "
                       "feito aqui.")
            cc_opts = listar_valores("centro_custo") or ["—"]
            _cc_def = next((i for i, c in enumerate(cc_opts) if "ALMOXARIFADO" in str(c).upper()), 0)
            r1, r2 = st.columns(2)
            cc = r1.selectbox("Centro de custo", cc_opts, index=_cc_def,
                              help="Padrão MRO: Almoxarifado.")
            dt = r2.date_input("Data do recebimento", value=date.today())
            qtd_rec = r1.number_input(f"Qtd a receber ({un})", min_value=0.0,
                                      max_value=pend, value=pend, step=1.0,
                                      help="Default = pendente. Recebimento parcial: reduza aqui.")
            nf_rec = r2.text_input("NF (documento)", value=p.get("documento_nf") or "",
                                   key="gc_nf_receber")
            receber = st.form_submit_button(":material/download: Confirmar recebimento",
                                            type="primary", width="stretch")
        if receber:
            ok, msg = registrar_recebimento_sc(
                sc_id=p["id"], item_sc_id=item_sc_id, qtd_recebida=float(qtd_rec),
                centro_custo=cc, solicitante="Almoxarifado", emitente="Almoxarifado",
                fornecedor=p.get("fornecedor_item") or "",
                data_recebimento=str(dt), obs_nf=nf_rec)
            if ok:
                st.success(f":material/check_circle: {msg}")
                st.rerun()
            else:
                st.error(f":material/cancel: {msg}")
    else:
        st.success(":material/check_circle: Pedido totalmente recebido.")


# ══════════════════════════════════════════════════════════════════════════════
# ☂️ GUARDA-CHUVA MANUAL (v4.9.0) — controle próprio em Controle de SC
# ══════════════════════════════════════════════════════════════════════════════

def _render_guarda_chuva_controle():
    """v4.9.0 — Guarda-Chuva MANUAL: acordos de congelamento de preço por (produto +
    fornecedor) com entregas parciais. Controle 100% manual e desacoplado das SCs
    importadas (tabela `guarda_chuva`). Fluxo: adicionar produto (busca por PN/descrição)
    → adicionar código de fornecedor → kanban dos 4 estágios (editável) → 'Saldo total de
    todos os fornecedores' por material."""
    st.markdown("### :material/umbrella: Guarda-Chuva — saldo por fornecedor (controle manual)")
    st.caption("Acordo com o fornecedor para **congelar o preço** de um produto e fazer um pedido "
               "com **entregas parciais** (ideal: X por mês, para não faturar tudo de uma vez). "
               "É um **controle manual**: cadastre o produto e o(s) fornecedor(es) e mova os cards "
               "pelos estágios. Serve para saber **quanto ainda temos de saldo** daquele material "
               "com **quais fornecedores**.")

    # ── Adicionar produto + código de fornecedor ──────────────────────────────
    with st.expander(":material/add: Adicionar um produto ao Guarda-Chuva", expanded=False):
        _busca = st.text_input("Pesquisar produto (part number ou descrição)", key="gc_busca_add")
        _itens = filtrar_itens_por_busca(listar_inventario(), _busca) if _busca else []
        if _busca and not _itens:
            st.warning("Nenhum material encontrado para a busca.")
        _opcoes = {f"{i['part_number']} — {i['nome_item']}": i["id"] for i in _itens[:50]}
        _sel = st.selectbox("Material", ["—"] + list(_opcoes.keys()), key="gc_sel_add",
                            disabled=not _opcoes)
        with st.form("form_gc_add", clear_on_submit=True):
            st.markdown("**Adicionar código de fornecedor**")
            f1, f2 = st.columns(2)
            _cod = f1.text_input("Código do fornecedor *", key="gc_add_cod")
            _nome = f2.text_input("Nome do fornecedor (opcional)", key="gc_add_nome")
            f3, f4, f5 = st.columns(3)
            _qneg = f3.number_input("Qtd negociada", min_value=0.0, step=1.0, key="gc_add_qneg")
            _preco = f4.number_input("Preço congelado (R$)", min_value=0.0, step=0.01, key="gc_add_preco")
            _ideal = f5.number_input("Ideal por mês", min_value=0.0, step=1.0, key="gc_add_ideal")
            _add = st.form_submit_button(":material/add: Adicionar ao Guarda-Chuva", type="primary",
                                         width="stretch")
        if _add:
            _item_id = _opcoes.get(_sel)
            if not _item_id:
                st.error("Selecione um material (busque por PN ou descrição).")
            elif not (_cod or "").strip():
                st.error("Informe o código do fornecedor.")
            else:
                ok, res = criar_guarda_chuva(
                    _item_id, _cod, fornecedor_nome=(_nome or None),
                    qtd_negociada=_qneg, preco_congelado=(_preco or None),
                    qtd_ideal_mes=(_ideal or None))
                if ok:
                    st.success(":material/check_circle: Acordo adicionado ao Guarda-Chuva.")
                    st.rerun()
                else:
                    st.error(f":material/cancel: {res}")

    # ── Foco por material + saldo total de todos os fornecedores ──────────────
    _todos = listar_guarda_chuva()
    if not _todos:
        st.info("Nenhum acordo guarda-chuva cadastrado ainda. Use **Adicionar um produto** acima.")
        return

    _mats = {}
    for g in _todos:
        _mats.setdefault(g["item_id"], f"{g['part_number']} — {g['nome_item']}")
    _rotulos = {v: k for k, v in _mats.items()}
    _foco = st.selectbox("Material em foco", ["Todos"] + sorted(_rotulos.keys()), key="gc_foco")
    _foco_id = _rotulos.get(_foco)
    _linhas = _todos if _foco == "Todos" else [g for g in _todos if g["item_id"] == _foco_id]
    _un = (_linhas[0].get("unidade") or "") if _linhas else ""

    if _foco_id is not None:
        st.metric("Saldo total de todos os fornecedores",
                  f"{saldo_total_por_material(_foco_id):g} {_un}")
    else:
        _tot = sum(max(float(g.get("saldo_residual") or 0), 0.0) for g in _todos)
        st.metric("Saldo total de todos os fornecedores (todos os materiais)", f"{_tot:g}")

    # ── Kanban dos 4 estágios (editável) ──────────────────────────────────────
    st.markdown("##### :material/view_kanban: Kanban de acordos (manual)")
    _cols = st.columns(len(GUARDA_CHUVA_ESTAGIOS))
    for _col, _nome in zip(_cols, GUARDA_CHUVA_ESTAGIOS):
        with _col:
            _grupo = [g for g in _linhas if (g.get("estagio") or "Pedido Colocado") == _nome]
            st.markdown(f"**{_nome}** · {len(_grupo)}")
            for g in _grupo:
                with st.container(border=True):
                    _u = g.get("unidade") or ""
                    st.caption(f"`{g.get('part_number') or '—'}`")
                    st.markdown(f"**Forn. {g.get('fornecedor_codigo') or '—'}**"
                                + (f" · {g.get('fornecedor_nome')}" if g.get("fornecedor_nome") else ""))
                    st.caption(f"Neg. {(g.get('qtd_negociada') or 0):g} · "
                               f"Receb. {(g.get('qtd_recebida') or 0):g} · "
                               f"Saldo {(g.get('saldo_residual') or 0):g} {_u}")
                    if g.get("preco_congelado"):
                        st.caption(f":material/sell: R$ {float(g['preco_congelado']):.2f} congelado")
                    if st.button(":material/edit: Editar", key=f"gc_m_edit_{g['id']}", width="stretch"):
                        st.session_state["_gc_manual_edit"] = int(g["id"])
                        st.rerun()

    # ── Tabela: saldo por fornecedor ─────────────────────────────────────────
    st.markdown("##### :material/inventory: Saldo por fornecedor")
    _agg = {}
    for g in _linhas:
        _k = (g.get("fornecedor_codigo") or "—", g.get("fornecedor_nome") or "")
        _d = _agg.setdefault(_k, {"n": 0, "saldo": 0.0})
        _d["n"] += 1
        _d["saldo"] += max(float(g.get("saldo_residual") or 0), 0.0)
    if _agg:
        _df_gc = pd.DataFrame([{
            "Fornecedor (código)": k[0], "Nome": k[1],
            "Acordos": v["n"], f"Saldo pendente ({_un})": round(v["saldo"], 2),
        } for k, v in _agg.items()])
        st.dataframe(_df_gc, width="stretch", hide_index=True)


def _clear_gc_manual_edit():
    st.session_state.pop("_gc_manual_edit", None)


@st.dialog("Acordo — Guarda-Chuva", width="large", on_dismiss=_clear_gc_manual_edit)
def _dialog_guarda_chuva():
    """v4.9.0 — Edita um acordo guarda-chuva (manual) e registra recebimento parcial. Relê
    do banco a cada render (`obter_guarda_chuva`). Controle manual: não toca estoque."""
    gc_id = st.session_state.get("_gc_manual_edit")
    g = obter_guarda_chuva(gc_id) if gc_id else None
    if not g:
        st.info("Acordo não encontrado (pode ter sido removido).")
        return
    un = g.get("unidade") or ""
    saldo = float(g.get("saldo_residual") or 0)
    st.markdown(f"`{g.get('part_number') or '—'}` — **{g.get('nome_item') or '—'}**")
    m1, m2, m3 = st.columns(3)
    m1.metric("Negociada", f"{(g.get('qtd_negociada') or 0):g} {un}")
    m2.metric("Recebida", f"{(g.get('qtd_recebida') or 0):g} {un}")
    m3.metric("Saldo", f"{saldo:g} {un}")

    with st.form("form_gc_manual"):
        st.markdown("##### :material/edit: Dados do acordo")
        c1, c2 = st.columns(2)
        cod = c1.text_input("Código do fornecedor", value=g.get("fornecedor_codigo") or "")
        nome = c2.text_input("Nome do fornecedor", value=g.get("fornecedor_nome") or "")
        qneg = c1.number_input("Qtd negociada", min_value=0.0, step=1.0,
                               value=float(g.get("qtd_negociada") or 0))
        preco = c2.number_input("Preço congelado (R$)", min_value=0.0, step=0.01,
                                value=float(g.get("preco_congelado") or 0))
        ideal = c1.number_input("Ideal por mês", min_value=0.0, step=1.0,
                                value=float(g.get("qtd_ideal_mes") or 0))
        _est_idx = (list(GUARDA_CHUVA_ESTAGIOS).index(g["estagio"])
                    if g.get("estagio") in GUARDA_CHUVA_ESTAGIOS else 0)
        estagio = c2.selectbox("Estágio", GUARDA_CHUVA_ESTAGIOS, index=_est_idx)
        po = c1.text_input("Nº PO (opcional)", value=g.get("numero_po") or "")
        obs = st.text_area("Observação", value=g.get("observacao") or "")
        salvar = st.form_submit_button(":material/save: Salvar dados", type="primary", width="stretch")
    if salvar:
        ok, msg = atualizar_guarda_chuva(gc_id, {
            "fornecedor_codigo": cod, "fornecedor_nome": nome, "qtd_negociada": qneg,
            "preco_congelado": preco, "qtd_ideal_mes": ideal, "estagio": estagio,
            "numero_po": po, "observacao": obs,
        })
        if ok:
            st.success(f":material/check_circle: {msg}")
            st.rerun()
        else:
            st.error(f":material/cancel: {msg}")

    # ── Recebimento parcial (manual) ──────────────────────────────────────────
    if saldo > 0:
        with st.form("form_gc_manual_receber"):
            st.markdown("##### :material/download: Registrar recebimento (parcial)")
            st.caption("Controle manual — abate o saldo do acordo. NÃO mexe no estoque nem no "
                       "histórico de movimentações.")
            qtd = st.number_input(f"Qtd a receber ({un})", min_value=0.0, max_value=saldo,
                                  value=saldo, step=1.0)
            receber = st.form_submit_button(":material/download: Confirmar recebimento",
                                            type="primary", width="stretch")
        if receber:
            ok, msg = registrar_recebimento_guarda_chuva(gc_id, float(qtd))
            if ok:
                st.success(f":material/check_circle: {msg}")
                st.rerun()
            else:
                st.error(f":material/cancel: {msg}")

    st.divider()
    if st.button(":material/delete: Remover este acordo", key="gc_manual_remover"):
        ok, msg = remover_guarda_chuva(gc_id)
        if ok:
            _clear_gc_manual_edit()
            st.rerun()
        else:
            st.error(f":material/cancel: {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# 📡 MONITOR DE SC (v4.11.0) — seções reordenadas: (1) Controle Manual de Críticos,
# (2) SCs/Itens não atendidos (via API SCM), (3) fallback de cruzamento por upload.
# ══════════════════════════════════════════════════════════════════════════════

def _render_controle_manual_criticos():
    """v4.11.0 — 'Controle Manual de Críticos' (ex-'Planilha livre'), no TOPO do Monitor:
    grade colável do Excel com colunas configuráveis. Persiste em `monitor_livre`."""
    st.markdown("### :material/edit_note: Controle Manual de Críticos")
    st.caption("Cole um intervalo do Excel direto na grade — seu controle manual de itens "
               "críticos. As colunas começam como A, B, C…, mas você pode **criar** e "
               "**remover** colunas próprias (persistem junto com as linhas). **Crie as "
               "colunas antes de colar** os dados. A **1ª linha** vira o cabeçalho da "
               "pré-visualização abaixo.")

    def _mon_nz(v):
        return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v

    _pl = carregar_planilha_livre()
    if "pl_livre_cols" not in st.session_state:
        st.session_state.pl_livre_cols = _pl["colunas"] or list("ABCDEFGHIJ")
    _LIVRE_COLS = st.session_state.pl_livre_cols

    _pc1, _pc2 = st.columns([3, 1])
    with _pc1:
        _nova_col = st.text_input("Nome da nova coluna", key="pl_nova_col",
                                  label_visibility="collapsed", placeholder="Nome da nova coluna")
    with _pc2:
        if st.button("➕ Criar coluna", key="pl_criar_col", width="stretch"):
            _nome = (_nova_col or "").strip()
            if not _nome:
                st.warning("Digite um nome para a coluna.")
            elif _nome in _LIVRE_COLS:
                st.warning("Já existe uma coluna com esse nome.")
            else:
                st.session_state.pl_livre_cols = list(_LIVRE_COLS) + [_nome]
                st.rerun()
    _rem = st.multiselect("Remover coluna(s)", _LIVRE_COLS, key="pl_rem_cols")
    if st.button("🗑️ Remover coluna(s) selecionada(s)", key="pl_remover_col", disabled=not _rem):
        _restantes = [c for c in _LIVRE_COLS if c not in _rem]
        st.session_state.pl_livre_cols = _restantes or list("ABCDEFGHIJ")
        st.rerun()

    _linhas_pl = _pl["linhas"]
    if _linhas_pl:
        _df_livre = pd.DataFrame(_linhas_pl)
        for _c in _LIVRE_COLS:
            if _c not in _df_livre.columns:
                _df_livre[_c] = None
        _df_livre = _df_livre.reindex(columns=_LIVRE_COLS)
    else:
        _df_livre = pd.DataFrame({_c: pd.Series(dtype="object") for _c in _LIVRE_COLS})

    _livre_edit = st.data_editor(
        _df_livre, num_rows="dynamic", hide_index=True, width="stretch",
        height=360, key="monitor_livre_editor__" + "|".join(_LIVRE_COLS))

    if st.button("💾 Salvar Controle Manual de Críticos", key="monitor_livre_salvar"):
        _regs = [
            {_c: _mon_nz(r.get(_c)) for _c in _LIVRE_COLS}
            for _, r in _livre_edit.iterrows()
            if any(_mon_nz(r.get(_c)) is not None for _c in _LIVRE_COLS)
        ]
        _n = salvar_planilha_livre(_LIVRE_COLS, _regs)
        st.success(f":material/check_circle: Controle salvo ({_n} linha(s), {len(_LIVRE_COLS)} coluna(s)).")
        time.sleep(1.0); st.rerun()

    if len(_livre_edit) > 1:
        _prev = _livre_edit.reset_index(drop=True)
        _header = [str(x) if _mon_nz(x) is not None else "" for x in _prev.iloc[0].tolist()]
        _cols_final, _seen = [], {}
        for _i, _h in enumerate(_header):
            _name = _h or f"Col{_i+1}"
            if _name in _seen:
                _seen[_name] += 1
                _name = f"{_name}_{_seen[_name]}"
            else:
                _seen[_name] = 0
            _cols_final.append(_name)
        _corpo = _prev.iloc[1:].copy()
        _corpo.columns = _cols_final
        st.caption("Pré-visualização (1ª linha como cabeçalho):")
        st.dataframe(_corpo, width="stretch", hide_index=True)


def _render_scs_nao_atendidas():
    """v4.11.0 — 'SCs/Itens não atendidos' via API do SCM: SCs do almoxarifado em fase de
    cotação (sem pedido) cruzadas com o estoque MRO. Read-only, carregado sob demanda."""
    st.markdown("### :material/assignment_late: SCs/Itens não atendidos")
    st.caption("SCs do **almoxarifado** em **fase de cotação** (ainda sem pedido gerado), "
               "direto do **SCM**, cruzadas com o estoque MRO. **Status**, **Esgotado em** e "
               "**Faltando (d)** vêm do inventário (igual à aba 'Saldo em Estoque').")

    _l1, _l2 = st.columns([3, 1])
    with _l2:
        _load = st.button(":material/cloud_sync: Carregar/Atualizar do SCM", key="scs_na_load",
                          width="stretch")
    if _load:
        for _fn in (scm_client.cotacoes_em_andamento, scm_client.sc_timeline):
            try:
                _fn.clear()
            except Exception:
                pass
        if not scm_client.esta_disponivel():
            st.session_state["_scs_na_rows"] = "OFFLINE"
        else:
            with st.spinner("Consultando SCs em cotação no SCM…"):
                _solic_mro, _pns, _dep = obter_cadastro_mro_para_cruzamento()
                _lic = scm_client.cotacoes_em_andamento()
                _escopo = cotacoes_no_escopo(_lic, _solic_mro)
                _itens = {}
                for _c in _escopo:
                    _tl = scm_client.sc_timeline(_c["sc_id"]) or {}
                    _itens[_c["sc_id"]] = _tl.get("items") or []
                _inv = {str(i["part_number"]).strip().upper(): {
                    "status_material": i.get("status_material"),
                    "unidade": i.get("unidade"),
                    "nome_item": i.get("nome_item"),
                    "previsao_ruptura_dias": i.get("previsao_ruptura_dias"),
                } for i in listar_inventario()}
                st.session_state["_scs_na_rows"] = montar_scs_nao_atendidas(_escopo, _itens, _inv)

    _rows = st.session_state.get("_scs_na_rows")
    if _rows is None:
        st.info(":material/cloud: Clique em **Carregar/Atualizar do SCM** para buscar as SCs "
                "em cotação. (Requer rede até o SCM; senão use o fallback de upload abaixo.)")
        return
    if _rows == "OFFLINE":
        st.warning(":material/cloud_off: Não foi possível conectar ao SCM "
                   "(`mansrvapp03:5715`). Use o **fallback de upload** abaixo.")
        return
    if not _rows:
        st.success(":material/check_circle: Nenhuma SC/Item do almoxarifado em cotação pendente.")
        return
    _df_na = pd.DataFrame(_rows, columns=COLUNAS_SCS_NAO_ATENDIDAS)
    st.caption(f"**{len(_df_na)}** item(ns) em cotação, do escopo do almoxarifado (mais urgente primeiro).")
    st.dataframe(_df_na, width="stretch", hide_index=True, height=460, column_config={
        "QTY Solicitada": st.column_config.NumberColumn(format="%.0f"),
        "Saldo PO": st.column_config.NumberColumn(format="%.0f"),
        "Faltando (d)": st.column_config.NumberColumn(format="%.1f"),
    })
    _buf = io.BytesIO()
    with pd.ExcelWriter(_buf, engine="openpyxl") as _w:
        _df_na.to_excel(_w, index=False, sheet_name="SCs nao atendidos")
    st.download_button(":material/download: Baixar (Excel)", data=_buf.getvalue(),
                       file_name="scs_nao_atendidos.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key="scs_na_dl")


def _render_cruzamento_upload_fallback():
    """v4.11.0 — Fallback (sem rede ao SCM): cruzamento SCM × SC7 por UPLOAD manual (v4.6.0),
    dentro de um expander. Efêmero: nada é gravado no banco."""
    with st.expander(":material/cloud_off: Sem rede ao SCM? Cruzamento por upload (SCM × SC7)"):
        st.caption("Alternativa manual à tabela acima: envie os **dois exports crus** — "
                   "**SCM** (`Solicitações.xlsx`) e **SC7** (`Relatório de Compras.xlsx`) — e o "
                   "sistema casa por **PO** + Produto. Traz só material do MRO. Efêmero.")
        _cz1, _cz2 = st.columns(2)
        with _cz1:
            _up_scm = st.file_uploader("SCM — Solicitações.xlsx (cru)", type=["xlsx", "xls"], key="cruz_scm")
        with _cz2:
            _up_sc7 = st.file_uploader("SC7 — Relatório de Compras.xlsx (cru)", type=["xlsx", "xls"], key="cruz_sc7")
        if not (_up_scm and _up_sc7):
            st.info(":material/upload: Envie os **dois** arquivos crus (SCM e SC7) para gerar o cruzamento.")
            return
        _df_scm, _meta_scm = preparar_df(_up_scm, "SCM")
        _df_sc7, _meta_sc7 = preparar_df(_up_sc7, "SC7")
        if _df_scm is None:
            st.error(f":material/error: {_meta_scm['erro']}")
            return
        if _df_sc7 is None:
            st.error(f":material/error: {_meta_sc7['erro']}")
            return
        _solic_mro, _pns_mro, _dep_solic = obter_cadastro_mro_para_cruzamento()
        _res = cruzar_scm_sc7(_df_scm, _df_sc7, solicitantes_mro=_solic_mro,
                              pns_mro=_pns_mro, dep_por_solic=_dep_solic)
        if _res.get("erro"):
            st.error(f":material/error: {_res['erro']}")
            return
        _s = _res["stats"]
        _k1, _k2, _k3, _k4, _k5 = st.columns(5)
        _k1.metric("Casadas", _s["casadas"])
        _k2.metric("Sem pedido", _s["sem_pedido"])
        _k3.metric("PO sem SC7", _s["po_sem_sc7"])
        _k4.metric("Órfãos (PO s/ SC)", _s["orfaos"])
        _k5.metric("Saldo pendente", f"{_s['saldo_pendente_total']:,.0f}")
        st.caption(f"Fora do escopo MRO (ignoradas): **{_s['fora_escopo']}** linha(s) do SCM. "
                   f"Lidas: SCM {_s['n_scm']} × SC7 {_s['n_sc7']} linhas.")
        _df_cruz = pd.DataFrame(_res["linhas"], columns=_res["colunas"])
        _dep_sel = st.selectbox("Filtrar por Departamento", ["Todos"] + _res["departamentos"], key="cruz_dep")
        if _dep_sel != "Todos":
            _df_cruz = _df_cruz[_df_cruz["Departamento"] == _dep_sel]
        if _df_cruz.empty:
            st.info("Nenhuma linha do MRO no cruzamento para o filtro atual.")
        else:
            st.dataframe(_df_cruz, width="stretch", hide_index=True, height=460, column_config={
                "Qty (SC)": st.column_config.NumberColumn(format="%.0f"),
                "Qtd Entregue": st.column_config.NumberColumn(format="%.0f"),
                "Saldo": st.column_config.NumberColumn(format="%.0f"),
            })
            _buf_cz = io.BytesIO()
            with pd.ExcelWriter(_buf_cz, engine="openpyxl") as _w_cz:
                _df_cruz.to_excel(_w_cz, index=False, sheet_name="Cruzamento")
            st.download_button(":material/download: Baixar cruzamento (Excel)", data=_buf_cz.getvalue(),
                               file_name="monitor_sc_2_cruzamento.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="cruz_download")
        if _res["orfaos"]:
            with st.expander(f":material/warning: Órfãos — {len(_res['orfaos'])} PO(s) do SC7 sem SC no MRO"):
                st.caption("Compras (PO) de material MRO **sem SC correspondente** na planilha SCM.")
                st.dataframe(pd.DataFrame(_res["orfaos"]), width="stretch", hide_index=True)


if pagina in ROTAS_MIGRADAS:
    render_pagina(pagina)

elif pagina == "Dashboard":
    st.title(":material/bar_chart: Dashboard — MRO Inventus Power")
    if not listar_inventario():
        st.info("Nenhum item cadastrado. Vá em **:material/add: Gerenciar Itens** para começar.")
        st.stop()

    # v4.1.0 — a aba "Gestão" foi extinta; seu conteúdo (2 linhas de distribuição, Top 10
    # consumo, padrões de demanda, requisições por setor/emitente) migrou para o Almoxarifado.
    tab_comp, tab_almox, tab_mensal = st.tabs(
        [f":material/person: {PUBLICO_COMPRADOR}",
         ":material/warehouse: Almoxarifado",
         f":material/calendar_month: {PUBLICO_EXECUTIVO}"])
    with tab_comp:
        _render_dash_compras_mro(montar_visao_compras_mro())
    with tab_almox:
        _render_dash_almoxarifado(montar_visao_almoxarifado(), montar_dashboard(PUBLICO_GESTAO))
    with tab_mensal:
        _render_dash_executivo(montar_dashboard(PUBLICO_EXECUTIVO))

    # v4.5.0 — modal de drill-down: abre quando um card/gráfico clicável marca o estado.
    if st.session_state.get("_drill_on"):
        _drill_modal()

# ══════════════════════════════════════════════════════════════════════════════
# GERENCIAR ITENS
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Gerenciar Itens":
    st.title(":material/add: Gerenciar Itens MRO")

    # --- TABS PARA ORGANIZAÇÃO ---
    tab_editar, tab_novo = st.tabs([":material/edit: Editar Item Existente", ":material/fiber_new: Cadastrar Novo Item"])

    # === TAB 1: CADASTRAR NOVO ===
    with tab_novo:
        with st.container(border=True):
            st.subheader("Dados do Novo Item")
            c1, c2 = st.columns(2)
            
            with c1:
                pn_novo = st.text_input("Part Number (PN) *", placeholder="Ex: 12345-ABC")
                nome_novo = st.text_input("Nome do Item *", placeholder="Ex: Parafuso Sextavado M8")
                desc_novo = st.text_area("Observação", placeholder="Informações adicionais sobre o item", height=80)
                un_novo = st.selectbox("Unidade", UNIDADES, index=0)
                tipo_novo = st.selectbox("Tipo / Categoria", TIPOS, index=0)
            
            with c2:
                imp_novo = st.selectbox("Importância", IMPORTANCIAS, index=0)
                loc_novo = st.selectbox("Localidade", listar_valores("local") or ["Geral"], index=0)
                caixa_novo = st.selectbox("Caixa/ID", listar_valores("local") or ["Geral"], index=0)
                lead_novo = st.number_input("Lead Time (Dias)", min_value=1, value=20)

            c3, c4 = st.columns(2)
            min_novo = c3.number_input("Estoque Mínimo *", min_value=0, value=10)
            est_ini_novo = c4.number_input("Estoque Inicial", min_value=0.0, value=0.0)

            # ── Conversão de unidades (curadoria v2.9.0) — opcional ──────────────
            st.markdown("###### :material/sync: Conversão de unidades (se comprado em outra unidade)")
            _sug_novo = sugerir_conversao(
                {"nome_item": nome_novo, "descricao": desc_novo, "unidade": un_novo})
            cvn1, cvn2 = st.columns(2)
            uc_novo = cvn1.text_input(
                "Unidade de compra", value=(_sug_novo['unidade_compra_sugerida'] or un_novo),
                help="Unidade em que o fornecedor vende (L, KG, BB, par…). "
                     "Igual à de estoque se não houver diferença.")
            fator_novo = cvn2.number_input(
                "Fator de conversão", min_value=0.0,
                value=float(_sug_novo['fator_sugerido'] or 1.0), step=1.0,
                help="Quantas unidades de compra cabem em 1 de estoque. Ex.: 1 GL = 5 L → 5.")
            if _sug_novo['fator_sugerido']:
                st.caption(f":material/lightbulb: Sugestão automática pelo nome do item: {_sug_novo['origem']}.")

            if st.button(":material/save: Salvar Novo Item", type="primary", width="stretch"):
                if not pn_novo or not nome_novo:
                    st.error("Preencha Part Number e Nome.")
                else:
                    # Verificar duplicidade
                    itens_existentes = listar_inventario()
                    if any(i['part_number'].lower() == pn_novo.lower() for i in itens_existentes):
                        st.error(f"PN '{pn_novo}' já cadastrado!")
                    else:
                        ok, msg = salvar_item(
                            part_number=pn_novo,
                            nome_item=nome_novo,
                            descricao=desc_novo,
                            unidade=un_novo,
                            importancia=imp_novo,
                            tipo_material=tipo_novo,
                            setor="Improdutivo",
                            local=loc_novo,
                            caixa=caixa_novo,
                            estoque_atual=est_ini_novo,
                            estoque_minimo=min_novo,
                            lead_time=lead_novo,
                            unidade_compra=(uc_novo or "").strip() or None,
                            fator_conversao=fator_novo if fator_novo > 0 else FATOR_CONVERSAO_PADRAO,
                        )
                        if ok:
                            st.success(msg)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

    # === TAB 2: EDITAR EXISTENTE ===
    with tab_editar:
        with st.container(border=True):
            st.subheader("Selecionar Item para Edição")
            _, item_sel, _ = sel_material("Busque pelo PN ou Nome", "sel_edit_item")

            if item_sel:
                st.info(f"**Editando:** `{item_sel['part_number']} — {item_sel['nome_item']}`")
                if item_sel.get("unidade_divergente"):
                    st.warning(
                        ":material/warning: **Revisar unidade:** este item é comprado numa unidade diferente "
                        "da de estoque (visto nos POs). Defina a *unidade de compra* e o *fator* abaixo para que "
                        "o recebimento converta corretamente."
                    )
                ed_desc = st.text_area("Observação", value=item_sel.get('descricao', ''), height=70, key="ed_desc")

                st.markdown("---")
                
                c1, c2, c3 = st.columns(3)
                tipos_opts = opcoes_com_atual(TIPOS, item_sel.get('tipo_material'))
                locais_opts = listar_valores("local") or ["Geral"]
                with c1:
                    ed_un = st.selectbox("Unidade", UNIDADES, index=UNIDADES.index(item_sel['unidade']) if item_sel['unidade'] in UNIDADES else 0, key="ed_un")
                    ed_tipo = st.selectbox("Tipo / Categoria", tipos_opts, index=tipos_opts.index(item_sel['tipo_material']) if item_sel.get('tipo_material') in tipos_opts else 0, key="ed_tipo")
                    ed_imp = st.selectbox("Importância", IMPORTANCIAS, index=IMPORTANCIAS.index(item_sel['importancia']) if item_sel['importancia'] in IMPORTANCIAS else 0, key="ed_imp")

                with c2:
                    ed_loc = st.selectbox("Localidade", locais_opts,
                                          index=locais_opts.index(item_sel.get('local_armazenagem', 'Geral')) if item_sel.get('local_armazenagem') in locais_opts else 0, key="ed_loc")
                    # v4.5.6 — 2ª locação (opcional) editável aqui, além da Contagem Física.
                    _op_loc2 = [""] + locais_opts
                    _l2_atual = item_sel.get("local_armazenagem_2") or ""
                    if _l2_atual and _l2_atual not in _op_loc2:
                        _op_loc2.insert(1, _l2_atual)
                    ed_loc2 = st.selectbox(
                        "Localidade (2ª)", _op_loc2,
                        index=_op_loc2.index(_l2_atual) if _l2_atual in _op_loc2 else 0,
                        key="ed_loc2",
                        help="2º ponto de armazenagem do mesmo item (opcional). Deixe em branco se não houver.")
                    ed_caixa = st.selectbox("Caixa/ID", locais_opts,
                                            index=locais_opts.index(item_sel.get('caixa_identificacao', 'Geral')) if item_sel.get('caixa_identificacao') in locais_opts else 0, key="ed_caixa")
                    ed_lead = st.number_input("Lead Time (Dias)", min_value=0, value=int(item_sel.get('lead_time_dias') or 0), key="ed_lead")

                with c3:
                    ed_min = st.number_input("Estoque Mínimo (30 dias)", min_value=0.0, value=float(item_sel.get('estoque_minimo') or 0), key="ed_min")
                    ed_max = st.number_input("Estoque Máximo (60 dias)", min_value=0.0, value=float(item_sel.get('estoque_maximo') or 0), key="ed_max",
                                             help="0 = usa o cálculo automático (Mínimo × 2).")
                    # v3.7.0: Estoque de Segurança desativado — o buffer virou o próprio
                    # Mínimo do Neidson (não deixar atingir o mínimo nem passar do máximo).
                    # Nota: Estoque atual NÃO deve ser editado aqui, apenas via Movimentação/Inventário
                    st.markdown(f"**Estoque Atual:** `{item_sel['estoque_atual']}` (Alterar em *Inventário*)")
                    st.markdown(f"**Status:** `{item_sel['status_material']}`")

                # ── Conversão de unidades (curadoria v2.9.0) ─────────────────────
                st.markdown("---")
                st.markdown("##### :material/sync: Conversão de unidades (compra ↔ estoque)")
                _sug = sugerir_conversao(item_sel)
                _un_est = item_sel.get('unidade') or 'UN'
                _stored_fator = float(item_sel.get('fator_conversao') or 1.0)
                _stored_uc = item_sel.get('unidade_compra')
                # Item ainda não curado (fator=1 e sem UM de compra) → pré-preenche com
                # a sugestão; já curado → mostra o que o gestor gravou.
                _nao_curado = abs(_stored_fator - 1.0) < 1e-9 and not _stored_uc
                _def_uc = (_stored_uc or (_sug['unidade_compra_sugerida'] if _nao_curado else None)
                           or _un_est)
                _def_fator = (_sug['fator_sugerido'] or 1.0) if (_nao_curado and _sug['fator_sugerido']) else _stored_fator
                cvc1, cvc2 = st.columns([1, 1])
                ed_uc = cvc1.text_input(
                    "Unidade de compra", value=_def_uc, key="ed_uc",
                    help="Unidade em que o fornecedor vende (L, KG, BB, par…). "
                         "Deixe igual à de estoque se não houver diferença. "
                         f"Sugestões: {', '.join(UNIDADES_COMPRA_SUGERIDAS[:10])}…")
                ed_fator = cvc2.number_input(
                    "Fator de conversão", min_value=0.0, value=float(_def_fator), step=1.0,
                    key="ed_fator",
                    help="Quantas unidades de COMPRA cabem em 1 unidade de ESTOQUE. "
                         "Ex.: 1 GL = 5 L → fator 5. Fator 1 = mesma unidade (sem conversão).")
                _uc_txt = (ed_uc or _un_est).strip() or _un_est
                if abs(ed_fator - 1.0) > 1e-9 and _uc_txt.upper() != _un_est.upper():
                    st.caption(f":material/straighten: **1 {_un_est}** de estoque = **{ed_fator:g} {_uc_txt}** de compra. "
                               f"No recebimento, cada {ed_fator:g} {_uc_txt} recebidos viram 1 {_un_est} no estoque.")
                else:
                    st.caption(":material/straighten: Sem conversão (compra e estoque na mesma unidade).")
                st.caption(f":material/lightbulb: Sugestão do sistema: {_sug['origem']}.")

                if st.button(":material/check_circle: Atualizar Item", type="primary", width="stretch"):
                    dados_edicao = {
                        "descricao": ed_desc,
                        "unidade": ed_un,
                        "tipo_material": ed_tipo,
                        "importancia": ed_imp,
                        "local_armazenagem": ed_loc,
                        "local_armazenagem_2": (ed_loc2 or "").strip(),
                        "caixa_identificacao": ed_caixa,
                        "lead_time_dias": ed_lead,
                        "estoque_minimo": ed_min,
                        "estoque_maximo": ed_max,
                        "unidade_compra": (ed_uc or "").strip() or None,
                        "fator_conversao": ed_fator if ed_fator > 0 else FATOR_CONVERSAO_PADRAO,
                    }
                    ok, msg = atualizar_item_inventario(item_sel['id'], dados_edicao)
                    if ok:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)

                # ── Lead Time: cadastrado vs calculado (sugestão) — v2.2.1 ──────
                _lt_calc = item_sel.get('lead_time_calculado')
                if _lt_calc is not None:
                    _lt_cad = int(item_sel.get('lead_time_dias') or 0)
                    _amostras = int(item_sel.get('lead_time_calculado_amostras') or 0)
                    _origem = item_sel.get('lead_time_calculado_origem') or "—"
                    st.markdown("---")
                    lc1, lc2 = st.columns([2, 1])
                    lc1.info(
                        f":material/timer: **Lead Time** — cadastrado (Compras): **{_lt_cad}d** · "
                        f"calculado: **{_lt_calc}d** ({_amostras} amostras, origem {_origem}). "
                        f"O calculado é apenas uma sugestão; a base cadastrada não é alterada automaticamente."
                    )
                    if int(_lt_calc) != _lt_cad and lc2.button("Usar calculado", key="btn_usar_lt_calc", width="stretch"):
                        ok, msg = atualizar_item_inventario(item_sel['id'], {"lead_time_dias": int(_lt_calc)})
                        if ok:
                            st.success(f"Lead time atualizado para {int(_lt_calc)}d.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

                # ── Alteração de Part Number (Item 2 / v2.1.0) ───────────────
                st.markdown("---")
                st.markdown("##### :material/sync: Alterar Part Number")
                st.caption("Use quando o PN for corrigido no Protheus. O histórico (movimentações, "
                           "SCs e requisições) é preservado e o PN antigo continua pesquisável.")
                cpn1, cpn2 = st.columns([1, 1])
                novo_pn = cpn1.text_input("Novo Part Number", key="pn_novo", placeholder=item_sel['part_number'])
                motivo_pn = cpn2.text_input("Motivo da alteração", key="pn_motivo", placeholder="Ex: padronização Protheus")
                confirma_pn = st.checkbox("Confirmo a alteração do Part Number", key="pn_confirma")
                if st.button(":material/sync: Alterar Part Number", key="btn_alterar_pn", width="stretch"):
                    if not confirma_pn:
                        st.warning("Marque a confirmação para prosseguir.")
                    else:
                        ok, msg = alterar_part_number(item_sel['id'], novo_pn, motivo=motivo_pn, usuario="Luis Oliveira")
                        if ok:
                            st.success(msg)
                            time.sleep(1.2)
                            st.rerun()
                        else:
                            st.error(msg)

                hist_pn = listar_historico_part_number(item_sel['id'])
                if hist_pn:
                    with st.expander(f":material/history: Histórico de Part Numbers ({len(hist_pn)})"):
                        st.dataframe(
                            pd.DataFrame([{
                                "Data": fmt(h["data_hora"]), "PN Antigo": h["pn_antigo"],
                                "PN Novo": h["pn_novo"], "Motivo": h.get("motivo") or "—",
                                "Usuário": h.get("usuario") or "—",
                            } for h in hist_pn]),
                            width="stretch", hide_index=True
                        )

# ══════════════════════════════════════════════════════════════════════════════
# MOVIMENTAÇÕES
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Movimentação":
    st.title(":material/sync: Movimentação")

    # v3.8.0 — Requisição e Receber Material aninhados aqui (abas), ao lado de Analytics,
    # Ajuste Rápido e Histórico. Os corpos vivem em _render_receber_material /
    # _render_requisicao (module-level) — sem duplicar nem mover blocos indentados.
    tab_dash, tab_rec, tab_req, tab_ajuste, tab_hist = st.tabs([
        ":material/bar_chart: Dashboard movimentações", ":material/inventory_2: Receber Material",
        ":material/assignment: Requisição", ":material/balance: Ajuste Rápido",
        ":material/history: Histórico Completo"])

    centros = listar_valores("centro_custo") or ["Geral"]

    with tab_rec:
        _render_receber_material()
    with tab_req:
        _render_requisicao()

    # === TAB: AJUSTE RÁPIDO DE ESTOQUE (v4.3.0 — 4 tipos) ===
    with tab_ajuste:
        with st.container(border=True):
            st.subheader(":material/balance: Ajuste Manual de Saldo")
            st.caption("Lançamentos avulsos (sem SC/Requisição): entradas e saídas pontuais, devoluções e perdas.")

            # Rótulo -> (tipo do ledger, sinal: +1 soma / -1 subtrai do estoque).
            # O CHECK de movimentacoes.tipo continua ('entrada','saida','devolucao');
            # o rótulo é guardado em `motivo` para o filtro do Histórico (v4.3.0).
            TIPOS_AJUSTE = {
                "Entrada Avulsa":    ("entrada",   +1),
                "Devolução":         ("devolucao", +1),
                "Perda de Material": ("saida",     -1),
                "Saída Avulsa":      ("saida",     -1),
            }

            _, item_aj, _ = sel_material("Selecione o Item para Ajuste", "sel_ajuste_estoque")

            if item_aj:
                st.info(f"**Item:** `{item_aj['part_number']} — {item_aj['nome_item']}` | **Saldo Atual:** `{item_aj['estoque_atual']}`")

                c1, c2 = st.columns(2)
                rotulo_aj = c1.selectbox("Tipo de Ajuste", list(TIPOS_AJUSTE.keys()))
                tp, _sinal = TIPOS_AJUSTE[rotulo_aj]
                _hint = "soma ao estoque" if _sinal > 0 else "subtrai do estoque"
                qtd_aj = c2.number_input("Quantidade", min_value=0.01, step=1.0,
                                         help=f"'{rotulo_aj}' {_hint}.")

                obs_aj = st.text_input("Motivo / Observação *",
                                       placeholder="Ex: Avaria, sobra de contagem, devolução do setor...")
                resp_aj = st.text_input("Responsável pelo Ajuste *")

                if st.button(":material/check_circle: Confirmar Ajuste", type="primary", width="stretch"):
                    if not resp_aj or not obs_aj:
                        st.error("Preencha o responsável e o motivo para auditoria.")
                    elif _sinal < 0 and qtd_aj > item_aj['estoque_atual']:
                        st.error(f"Quantidade ({qtd_aj}) superior ao estoque disponível ({item_aj['estoque_atual']}).")
                    else:
                        ok, msg = registrar_movimentacao(
                            item_id=item_aj["id"], tipo=tp, quantidade=qtd_aj,
                            centro_custo=None, solicitante=resp_aj, emitente=resp_aj,
                            observacao=f"AJUSTE: {obs_aj}", motivo=rotulo_aj,
                            data_hora=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )
                        if ok:
                            st.success(f":material/check_circle: '{rotulo_aj}' registrado! Novo saldo: {msg}")
                            time.sleep(1.2)
                            st.rerun()
                        else:
                            st.error(f":material/cancel: Erro: {msg}")

    # === TAB 2: HISTÓRICO COMPLETO ===
    with tab_hist:
        with st.container(border=True):
            st.subheader(":material/history: Histórico de Movimentações")
            
            c1, c3 = st.columns([3, 1])
            f_item = c1.selectbox("Filtrar por Item", ["Todos"] + [f"{i['part_number']} - {i['nome_item']}" for i in listar_inventario()])
            limit = c3.number_input("Limite", min_value=50, max_value=1000, value=200, step=50)

            item_id_f = None
            if f_item != "Todos":
                pn_busca = f_item.split(" - ")[0]
                for i in listar_inventario():
                    if i['part_number'] == pn_busca:
                        item_id_f = i['id']
                        break

            movs = listar_movimentacoes(item_id=item_id_f, limit=int(limit))
            for _m in movs:
                _m["_categoria"] = categoria_movimentacao(_m)

            # v4.3.0 — filtro por Categoria (derivada de tipo+motivo): Requisição,
            # Entrada/Saída Avulsa, Devolução, Perda de Material, Conferência, etc.
            cats_presentes = sorted({_m["_categoria"] for _m in movs})
            f_cat = st.multiselect("Filtrar por Categoria", cats_presentes, default=cats_presentes)
            if f_cat:
                movs = [_m for _m in movs if _m["_categoria"] in f_cat]

            if movs:
                df_mov = pd.DataFrame(movs)
                df_mov['data_hora'] = df_mov['data_hora'].apply(fmt)
                
                cols_exib = ["data_hora", "part_number", "nome_item", "_categoria", "tipo", "quantidade", "saldo_apos", "emitente", "observacao"]
                df_exib = df_mov[cols_exib].copy()
                df_exib.columns = ["Data/Hora", "PN", "Nome", "Categoria", "Tipo", "Qtd", "Saldo Pós", "Responsável", "Obs"]

                # Estilização por tipo
                def colorir_tipo(val):
                    if val == 'entrada': return 'color: #2ecc71; font-weight: bold;'
                    if val == 'saida': return 'color: #e74c3c; font-weight: bold;'
                    if val == 'devolucao': return 'color: #3498db; font-weight: bold;'
                    return ''

                st.dataframe(
                    df_exib.style.map(colorir_tipo, subset=['Tipo']), # Mantém a cor original do tipo banco
                    width="stretch",
                    hide_index=True,
                    height=600,
                    column_config={
                        "Qtd": st.column_config.NumberColumn(format="%.2f"),
                        "Saldo Pós": st.column_config.NumberColumn(format="%.2f")
                    }
                )
            else:
                st.info("Nenhuma movimentação encontrada para os filtros selecionados.")
            
        # --- BOTÃO DE EXPORTAR (Abaixo do dataframe de histórico) ---
            st.markdown("---")
            col_btn, _ = st.columns([1, 4])
            with col_btn:
                    # Passamos os filtros atuais para a função
                _cats_all = bool(f_cat) and len(f_cat) == len(cats_presentes)
                df_exp_mov = exportar_movimentacoes_df(
                    item_id=item_id_f,
                    categorias_selecionadas=None if _cats_all else (f_cat or None))
                    
                if not df_exp_mov.empty:
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as w:
                        df_exp_mov.to_excel(w, index=False, sheet_name="Movimentacoes")
                        
                    st.download_button(
                        label="⬇️ Baixar planilha excel completo de todas as movimentações",
                        data=buf.getvalue(),
                        file_name=f"movimentacoes_{date.today().strftime('%d-%m-%Y')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_exp_mov"
                    )


    # === TAB 3: DASHBOARD MOVIMENTAÇÕES (VOLUME + DIVERGÊNCIAS + RUPTURA) ===
    with tab_dash:
        st.subheader(":material/bar_chart: Dashboard movimentações")

        # v4.1.0 — Tendência de consumo (comparação 30d vs. 30d anteriores)
        with st.container(border=True):
            st.markdown("#### :material/psychology: Tendência de consumo")
            st.caption("Compara o consumo dos últimos 30 dias com os 30 dias anteriores, item a item.")
            try:
                df_series = exportar_inventario_df()
            except Exception as e:
                df_series = pd.DataFrame()
                st.error(f"Erro ao calcular indicadores: {e}")
            if df_series.empty:
                st.caption("Sem dados suficientes.")
            else:
                if "Tendência" in df_series.columns:
                    vc = df_series["Tendência"].value_counts()
                    tca = st.columns(3)
                    tca[0].metric("🔺 Em alta", int(vc.get("Alta", 0)),
                                  help="Itens cujo consumo dos últimos 30 dias está mais de 15% ACIMA "
                                       "dos 30 dias anteriores (demanda aumentando vs. o mês passado).")
                    tca[1].metric("🔻 Em queda", int(vc.get("Queda", 0)),
                                  help="Itens cujo consumo dos últimos 30 dias está mais de 15% ABAIXO "
                                       "dos 30 dias anteriores (demanda diminuindo vs. o mês passado).")
                    tca[2].metric(":material/remove: Estável", int(vc.get("Estável", 0)),
                                  help="Itens cujo consumo dos últimos 30 dias variou menos de 15% "
                                       "em relação aos 30 dias anteriores (demanda estável).")

        st.markdown("---")

        # v2.3.0 — 💰 Financeiro: valor imobilizado · ABC por valor · evolução de preço
        with st.container(border=True):
            st.markdown("#### :material/payments: Financeiro (Valoração — estimativas rotuladas)")
            st.caption(
                "Valores são **estimativas** baseadas no **último preço** conhecido "
                "(SCM; na falta, último preço de PO/SC7). Não substituem o custo contábil."
            )
            try:
                vi = obter_valor_imobilizado()
            except Exception as e:
                vi = None
                st.error(f"Erro ao calcular valoração: {e}")

            if vi:
                k1, k2, k3 = st.columns(3)
                k1.metric(
                    ":material/payments: Valor imobilizado (BRL)", f"R$ {vi['total_brl']:,.2f}",
                    help="Σ (estoque atual × preço de valoração) dos itens em BRL. "
                         "Estimativa pelo último preço.",
                )
                k2.metric(
                    ":material/check_circle: Itens valorados", vi["itens_valorados"],
                    help="Itens com preço de referência conhecido (SCM ou histórico).",
                )
                k3.metric(
                    ":material/warning: Sem preço", vi["itens_sem_preco"],
                    help="Itens COM estoque mas SEM preço conhecido — subestimam o total. "
                         "Aparecem quando o material ainda não foi comprado via SCM/SC7.",
                )
                if vi["itens_nao_brl"]:
                    st.caption(
                        f":material/language: {vi['itens_nao_brl']} item(ns) com moeda ≠ BRL "
                        f"(≈ {vi['total_nao_brl']:,.2f} na moeda original) somados à parte — "
                        "sem conversão cambial nesta versão."
                    )

            fa, fb = st.columns(2)

            # Evolução do valor imobilizado (fotos diárias)
            with fa:
                st.markdown("**:material/trending_up: Evolução do valor imobilizado**")
                st.caption("Soma diária de (estoque × preço) — capital parado ao longo do tempo.")
                try:
                    ev = obter_evolucao_valor_imobilizado(dias=180)
                except Exception:
                    ev = {"serie": [], "n_snapshots": 0}
                if ev["serie"]:
                    df_ev = pd.DataFrame(ev["serie"]).set_index("data")
                    st.line_chart(df_ev["valor"], height=240)
                    st.caption(f"Baseado em {ev['n_snapshots']} foto(s) de estoque.")
                else:
                    st.info("Ainda sem fotos suficientes — a série amadurece a cada import diário.")

            # Curva ABC por valor
            with fb:
                st.markdown("**:material/bar_chart: Curva ABC por valor (últimos 90d)**")
                st.caption("Ranking pelo valor consumido = qtd saída × preço. A=80% · B=95% · C=resto.")
                try:
                    abc = obter_abc_valor(dias=90, limit=15)
                except Exception:
                    abc = []
                if abc:
                    df_abc_v = pd.DataFrame(abc)
                    df_abc_v["Item"] = df_abc_v["part_number"] + " • " + \
                        df_abc_v["nome_item"].astype(str).str.slice(0, 18)
                    st.dataframe(
                        df_abc_v[["Item", "classe", "valor", "pct_acumulado", "origem"]]
                        .rename(columns={"classe": "Classe", "valor": "Valor (R$)",
                                         "pct_acumulado": "% Acum.", "origem": "Origem"}),
                        hide_index=True, width="stretch", height=280,
                        column_config={
                            "Valor (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                            "% Acum.": st.column_config.NumberColumn(format="%.1f%%"),
                        },
                    )
                else:
                    st.info("Sem saídas valorizáveis no período.")

            # Top capital parado (valor alto + giro 0) — alvo de redução de imobilizado
            if not df_series.empty and "Valor em Estoque" in df_series.columns \
                    and "Giro(anual)" in df_series.columns:
                st.markdown("**:material/ac_unit: Top capital parado (maior valor em estoque, giro 0)**")
                st.caption("Dinheiro parado sem saída no período — candidatos a reduzir/realocar.")
                _cols_cap = [c for c in ["PN", "Nome", "UN", "Estoque Atual", "Valor em Estoque"]
                             if c in df_series.columns]
                parado_val = (df_series[(df_series["Giro(anual)"] == 0) &
                                        (df_series["Valor em Estoque"] > 0)]
                              .nlargest(8, "Valor em Estoque")[_cols_cap])
                if not parado_val.empty:
                    st.dataframe(
                        parado_val, hide_index=True, width="stretch",
                        column_config={"Valor em Estoque":
                                       st.column_config.NumberColumn(format="R$ %.2f")},
                    )
                else:
                    st.success(":material/check_circle: Nenhum item de valor relevante totalmente parado.")

        st.markdown("---")

        # --- LINHA 1: VOLUME E DIVERGÊNCIAS (Lado a Lado) ---
        c_vol, c_div = st.columns(2)

        # 1. VOLUME DE ENTRADAS E SAÍDAS
        with c_vol:
            with st.container(border=True):
                st.markdown("#### :material/inventory_2: Volume de Movimentações")
                periodo_sel = st.selectbox("Agrupar por:", ["Mensal", "Semanal", "Diário"], index=0, key="sel_periodo_vol")
                periodo_map = {"Mensal": "mensal", "Semanal": "semanal", "Diário": "diario"}
                df_anal = obter_analitico_movimentacoes(periodo=periodo_map[periodo_sel])

                if df_anal.empty:
                    st.caption("Sem dados no período.")
                else:
                    try:
                        df_pivot = df_anal.pivot_table(index='periodo', columns='tipo', values='vol_unidades', aggfunc='sum', fill_value=0)
                        for col in ['entrada', 'saida', 'devolucao']:
                            if col not in df_pivot.columns: df_pivot[col] = 0
                        
                        df_pivot = df_pivot.rename(columns={'entrada': 'Entradas', 'saida': 'Saídas', 'devolucao': 'Dev'})
                        df_pivot = df_pivot.sort_index(ascending=True)

                        t1, t2 = st.columns(2)
                        t1.metric("Total Entradas", f"{df_pivot['Entradas'].sum():,.0f}")
                        t2.metric("Total Saídas", f"{df_pivot['Saídas'].sum():,.0f}")

                        st.bar_chart(df_pivot[['Entradas', 'Saídas']], color=["#2ecc71", "#e74c3c"])
                    except Exception as e:
                        st.error(f"Erro ao processar volume: {e}")

        # 2. DIVERGÊNCIAS DE INVENTÁRIO
        with c_div:
            with st.container(border=True):
                st.markdown("#### :material/balance: Top Itens com Divergências")
                st.caption("Ajustes manuais frequentes (sem Req/SC) indicam erro de processo.")
                
                df_div = obter_analitico_divergencias(days=90)
                
                if df_div.empty:
                    st.success(":material/check_circle: Nenhuma divergência significativa.")
                else:
                    df_div_display = df_div.copy()
                    df_div_display.columns = ["PN", "Item", "Nº Ajustes", "Vol. Ajustado"]
                    
                    st.dataframe(
                        df_div_display,
                        width="stretch",
                        hide_index=True,
                        height=320,
                        column_config={
                            "Nº Ajustes": st.column_config.ProgressColumn("Freq.", format="%d", min_value=0, max_value=int(df_div_display["Nº Ajustes"].max()), color="#F7941E"),
                            "Vol. Ajustado": st.column_config.NumberColumn(format="%.2f")
                        }
                    )

        st.markdown("---")

        # --- LINHA 2: RUPTURA DE ESTOQUE (Destaque Total) ---
        with st.container(border=True):
            st.markdown("#### :material/emergency: Ruptura de Estoque (Impacto na Operação)")
            st.caption("Itens que zeraram o estoque durante uma requisição nos últimos 90 dias. Indica falha de abastecimento.")
            
            df_rup = obter_analitico_rupturas(days=90)
            
            if df_rup.empty:
                st.success(":material/check_circle: **Operação Fluida:** Nenhuma ruptura registrada no período. O estoque atendeu todas as requisições.")
            else:
                # Formatar data para exibição
                df_rup['ultima_ocorrencia'] = df_rup['ultima_ocorrencia'].apply(fmt)
                
                # Renomear colunas
                df_rup_display = df_rup.rename(columns={
                    "part_number": "PN",
                    "nome_item": "Item Crítico",
                    "qtd_rupturas": "Qtd. Rupturas",
                    "ultima_ocorrencia": "Última Falha"
                })

                # Estilização: Vermelho para alta frequência
                def highlight_ruptura(val):
                    if isinstance(val, (int, float)) and val >= 3:
                        return 'color: #e74c3c; font-weight: bold;'
                    return ''

                st.dataframe(
                    df_rup_display.style.map(highlight_ruptura, subset=['Qtd. Rupturas']),
                    width="stretch",
                    hide_index=True,
                    height=250,
                    column_config={
                        "Qtd. Rupturas": st.column_config.ProgressColumn(
                            "Freq. Ruptura", 
                            format="%d", 
                            min_value=0, 
                            max_value=int(df_rup_display["Qtd. Rupturas"].max()),
                            color="#e74c3c" # Vermelho para alertar
                        ),
                        "Última Falha": st.column_config.TextColumn(width="small")
                    }
                )
                
                st.warning(":material/lightbulb: **Ação Recomendada:** Revise o **Estoque Mínimo** e o **Lead Time** destes itens imediatamente para evitar paradas de linha.")

# ══════════════════════════════════════════════════════════════════════════════
# CONTROLE DE SC
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Controle de SC":
    st.title(":material/receipt_long: Controle de SC")
    
    # Estrutura de abas mantida conforme solicitado
    # v3.8.0 — "Receber Material" saiu daqui (agora vive na Movimentação).
    # v4.9.0 — "☂️ Guarda-Chuva" (controle manual) entrou logo após o Monitor. 8 abas.
    aba_mon, aba_gc, aba_assist, aba_forn, aba_nova_sc, aba_ed, aba_h, aba_import = st.tabs([
    ":material/sensors: Monitor", ":material/umbrella: Guarda-Chuva", ":material/psychology: Assistente de Reposição", ":material/apartment: Fornecedores & Cotação", ":material/add: Nova SC",
    ":material/sync: Detalhes SC", ":material/history: Histórico", ":material/download: Importar Relatório de SCs"
    ])

    # ══════════════════════════════════════════════════════════════════════════════
    # ☂️ GUARDA-CHUVA (controle manual — v4.9.0)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_gc:
        _render_guarda_chuva_controle()
        if st.session_state.get("_gc_manual_edit"):
            _dialog_guarda_chuva()
    # ══════════════════════════════════════════════════════════════════════════════
    # 📡 MONITOR DE COMPRAS 
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_mon:
        # v4.11.0 — Monitor reordenado: (1) Controle Manual de Críticos (topo), (2) SCs/Itens
        # não atendidos via API do SCM, (3) fallback de cruzamento por upload (sem rede). A
        # grade técnica de 15 linhas (sync diário) saiu da UI — o vivo do SCM a substitui;
        # `sincronizar_monitor_sc`/`listar_monitor_sc` seguem no db_functions só p/ regressão.
        # v5.2.0 (F3) — a sincronização SCM (API → banco) e a consulta das SCs migraram para
        # a página **SCM Integrado** (menu, abaixo de Controle de SC).
        _render_controle_manual_criticos()
        st.divider()
        st.info(":material/cloud_sync: A **sincronização SCM (API → banco)** e a consulta "
                "unificada das SCs agora vivem na página **SCM Integrado** (menu lateral).")
        st.divider()
        _render_scs_nao_atendidas()
        st.divider()
        _render_cruzamento_upload_fallback()

     # ══════════════════════════════════════════════════════════════════════════════
    #   📥 IMPORTAR PROTHEUS
    # ═══════════════════════════════════════════════════════════════════════════════
    with aba_import:
        with st.container(border=True):
            st.markdown("### :material/download: Importar Relatório de SCs")
            st.caption("Upload da planilha diária dos compradores. Roteia por aba: **SCM** (SCs + preço), "
                       "**SC7** (histórico de preços), **FORNECEDORES** (cadastro + e-mails) e **SCM USERS** "
                       "(solicitantes). Upsert com histórico preservado; backup automático antes de gravar.")
            arquivo = st.file_uploader("Arquivo Excel (.xlsx / .xls)", type=["xlsx", "xls"], key="upload_relatorio_scs")

            if arquivo:
                if st.button(":material/sync: Processar Relatório de SCs", width="stretch", type="primary"):
                    with st.spinner("Processando abas do Relatório de SCs..."):
                        ok, resultado = importar_relatorio_scs(arquivo, arquivo.name)
                    if ok:
                        # v3.9.0 — refaz o sync do Monitor de SC para refletir o import na hora.
                        try:
                            sincronizar_monitor_sc(force=True)
                        except Exception:
                            pass
                        scm = resultado.get("SCM", {}) or {}
                        if isinstance(scm, dict) and not scm.get("erro"):
                            st.markdown("**:material/description: SCM — Solicitações + Preço**")
                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric(":material/download: Importadas", scm.get("linhas_importadas", 0))
                            m2.metric(":material/block: Ignoradas", scm.get("linhas_ignoradas", 0))
                            m3.metric(":material/attach_money: Preços", scm.get("precos_capturados", 0))
                            m4.metric("🔴 Rupturas", scm.get("rupturas", 0))
                            m5, m6, m7, m8 = st.columns(4)
                            m5.metric(":material/description: SCs Criadas", scm.get("scs_criadas", 0))
                            m6.metric(":material/sync: SCs Atualizadas", scm.get("scs_atualizadas", 0))
                            m7.metric(":material/warning: Divergências", scm.get("divergencias", 0))
                            m8.metric(":material/local_fire_department: Críticos", scm.get("criticos", 0))

                        st.markdown("**:material/link: Demais fontes**")
                        sc7 = resultado.get("SC7", {}) or {}
                        forn = resultado.get("FORNECEDORES", {}) or {}
                        usr = resultado.get("SCM USERS", {}) or {}
                        c1, c2, c3 = st.columns(3)
                        c1.metric(":material/attach_money: Preços SC7", sc7.get("precos_inseridos", 0) if isinstance(sc7, dict) else 0)
                        c2.metric(":material/apartment: Fornecedores", f"{forn.get('upserted', 0)}" if isinstance(forn, dict) else "—",
                                  help=f"Com e-mail: {forn.get('com_email', 0)}" if isinstance(forn, dict) else None)
                        c3.metric(":material/group: Solicitantes", usr.get("upserted", 0) if isinstance(usr, dict) else 0)

                        erros = {aba: r.get("erro") for aba, r in resultado.items()
                                 if isinstance(r, dict) and r.get("erro")}
                        if erros:
                            st.warning("Abas com aviso: " + " · ".join(f"**{a}**: {e}" for a, e in erros.items()))
                        if isinstance(scm, dict) and scm.get("ignorados_amostra"):
                            with st.expander("Amostra de linhas ignoradas (SCM)"):
                                st.dataframe(pd.DataFrame(scm["ignorados_amostra"]), width="stretch", hide_index=True)
                        st.success(f":material/check_circle: Importação concluída. Foto de estoque do dia: "
                                   f"{resultado.get('_snapshot_criados', 0)} itens.")
                    else:
                        erros = {aba: r.get("erro") for aba, r in resultado.items()
                                 if isinstance(r, dict) and r.get("erro")}
                        st.error(":material/cancel: Falha ao importar. " +
                                 ("; ".join(f"{a}: {e}" for a, e in erros.items()) if erros else str(resultado)))

            with st.expander("↩️ Importação antiga (export cru do SCM — fallback)"):
                arq_old = st.file_uploader("Arquivo Excel (export cru)", type=["xlsx", "xls"], key="upload_protheus_legacy")
                if arq_old and st.button("Processar (fallback)", key="btn_import_legacy"):
                    with st.spinner("Processando..."):
                        ok_o, res_o = importar_solicitacoes_protheus(arq_old, arq_old.name)
                    if ok_o:
                        st.success(f"Importado: {res_o.get('linhas_importadas', 0)} linhas.")
                    else:
                        st.error(f"Falha: {res_o.get('erro', 'erro')}")
    # ══════════════════════════════════════════════════════════════════════════════
    #   🏢 FORNECEDORES & COTAÇÃO (v2.4.0) — busca material → fornecedores/preços,
    #   melhor fornecedor (menor último preço), lead time por fornecedor e rascunho
    #   de e-mail. Assistente: o sistema prepara a cotação; o comprador revisa e ENVIA.
    # ══════════════════════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════════════════════
    #   🧠 ASSISTENTE DE REPOSIÇÃO (v2.5.0) — recomenda o quê/quando/quanto/de quem;
    #   o comprador decide e cria a SC. Nada sobrescreve a base do Neidson.
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_assist:
        st.markdown("### :material/psychology: Assistente de Reposição")
        st.caption("Fila priorizada do que repor — o quê, quando, quanto, por quê e de quem. "
                   "O sistema **recomenda**; o comprador decide e cria a SC. Nada aqui "
                   "sobrescreve a base do Compras (mín/máx/lead time/categoria).")

        incluir_sem_mov = st.checkbox(
            "⚪ Mostrar itens sem movimentação (revisão)", value=False, key="rep_incl_semmov",
            help="Por padrão, itens que nunca tiveram consumo real ficam fora da fila. "
                 "Marque para revisá-los — inclui os spares 'Parada de Linha' que o "
                 "Compras estoca sem giro.")

        with st.spinner("Calculando sugestões de reposição…"):
            sugestoes = gerar_sugestoes_reposicao(incluir_sem_movimentacao=incluir_sem_mov)

        # v3.7.0 — Setor DOMINANTE (derivado do consumo real) no lugar do
        # `setor_responsavel` (98% "Improdutivo", inútil); e Qtd Sugerida = MÁXIMO
        # cadastrado do material (decisão D2). Fallback ao híbrido só quando não há
        # máximo resolvido (> 0), para nunca criar SC com quantidade 0.
        _setor_dom = setor_dominante_por_item([s["item_id"] for s in sugestoes])
        for s in sugestoes:
            s["setor"] = _setor_dom.get(s["item_id"], "—")
            _qmax = int(math.ceil(s.get("estoque_maximo") or 0))
            if _qmax > 0:
                s["qtd_sugerida"] = _qmax

        if not sugestoes:
            st.success(":material/check_circle: Nenhuma reposição necessária agora. Estoque + saldo "
                       "residual cobrem o horizonte planejado para todos os itens.")
        else:
            # --- Filtros ---
            # v3.10.0: a fila do Assistente mostra SÓ material CRÍTICO (no/abaixo do ROP)
            # e que AINDA não tem SC aberta — é exatamente o que precisa virar SC agora.
            _itens_com_sc = itens_com_sc_aberta()
            base_criticos = [s for s in sugestoes
                             if s["prioridade_tier"] == 0 and s["item_id"] not in _itens_com_sc]

            setores = sorted({s["setor"] for s in base_criticos if s["setor"] and s["setor"] != "—"})
            f_setor = st.selectbox("Setor (consumo real)", ["Todos"] + setores, key="rep_setor")

            filtradas = base_criticos
            if f_setor != "Todos":
                filtradas = [s for s in filtradas if s["setor"] == f_setor]

            def _cate(s):
                """'Comprar até' formatado (⏰ = já atrasado; '—' = sem consumo)."""
                ca = s.get("comprar_ate")
                if not ca:
                    return "—"
                dd = datetime.strptime(ca, "%Y-%m-%d").strftime("%d/%m/%Y")
                return f"⏰ {dd}" if s.get("comprar_atrasado") else dd

            st.caption(f"🔴 **{len(filtradas)}** item(ns) crítico(s) sem SC — no/abaixo do ponto "
                       "de pedido (ROP) e ainda sem SC aberta.")
            if not filtradas:
                st.success(":material/check_circle: Nenhum item crítico sem SC agora — tudo o que "
                           "está no/abaixo do ROP já tem SC aberta.")

            st.divider()

            # v3.4.0 — tabela ENRIQUECIDA + SELEÇÃO (pedido do §3): o comprador marca o
            # que entra nas "SCs sugeridas" (default: tudo). Colunas: estoque, mín, máx,
            # segurança (efetivo, c/ piso pelo mínimo), cobertura, consumo/dia+un, setores.
            def _linha_rep(s, incluir=None):
                d = {
                    "PN": s["part_number"],
                    "Item": s["nome_item"],
                    "Estoque": s.get("estoque_atual"),
                    "Mín": s.get("estoque_minimo"),
                    "Máx": s.get("estoque_maximo"),
                    "Cobertura(d)": (s["cobertura_dias"]
                                     if s["cobertura_dias"] < PREVISAO_RUPTURA_SEM_RISCO else None),
                    "Consumo/dia": round(float(s.get("consumo_diario") or 0), 2),
                    "Un": s["unidade"],
                    "Comprar até": _cate(s),
                    "Setor": s.get("setor") or "—",
                    "Qtd Sugerida": s["qtd_sugerida"],
                    "Fornecedor (melhor preço)": s["fornecedor_sugerido"] or "—",
                }
                return {"Incluir": incluir, **d} if incluir is not None else d

            _num_cols = {
                "Estoque": "%.0f", "Mín": "%.0f", "Máx": "%.0f",
                "Cobertura(d)": "%.1f", "Consumo/dia": "%.2f", "Qtd Sugerida": "%d",
            }
            df_sel = pd.DataFrame([_linha_rep(s, incluir=True) for s in filtradas])
            edit_sel = st.data_editor(
                df_sel, hide_index=True, width="stretch", key="rep_sel_editor",
                column_config={
                    "Incluir": st.column_config.CheckboxColumn(
                        "Incluir", help="Marque os itens que entram nas SCs sugeridas abaixo."),
                    **{c: st.column_config.NumberColumn(format=f, disabled=True)
                       for c, f in _num_cols.items()},
                    **{c: st.column_config.TextColumn(disabled=True)
                       for c in ("PN", "Item", "Un", "Comprar até", "Setor",
                                 "Fornecedor (melhor preço)")},
                },
            )
            _incluir = list(edit_sel["Incluir"]) if "Incluir" in edit_sel else [True] * len(filtradas)
            selecionadas = [s for s, inc in zip(filtradas, _incluir) if inc]
            st.caption(f"**{len(selecionadas)}** de {len(filtradas)} itens selecionados · "
                       "Qtd Sugerida = **Máximo** cadastrado do material · Setor = consumo real.")

            _df_export = pd.DataFrame([_linha_rep(s) for s in filtradas])
            buf_rep = io.BytesIO()
            with pd.ExcelWriter(buf_rep, engine="openpyxl") as w:
                _df_export.to_excel(w, index=False, sheet_name="Sugestões")
            exp1, exp2 = st.columns(2)
            exp1.download_button(
                "⬇️ Exportar sugestões (Excel)", data=buf_rep.getvalue(),
                file_name=f"reposicao_mro_{date.today():%d-%m-%Y}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="rep_export", width="stretch")
            exp2.download_button(
                "⬇️ Exportar sugestões (CSV)",
                data=_df_export.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"reposicao_mro_{date.today():%d-%m-%Y}.csv",
                mime="text/csv", key="rep_export_csv", width="stretch")

            # --- 📦 SCs sugeridas (agrupadas por TIPO DO MATERIAL) — "de mão beijada" ---
            st.divider()
            st.markdown("#### :material/inventory_2: SCs sugeridas")
            st.caption("Itens juntados pelo **Tipo do material** (campo do cadastro do item), com "
                       "título, justificativa e **centro de custo** sugeridos. Revise, edite e crie "
                       "a SC agrupada em um clique — o sistema recomenda, você decide.")
            grupos_sc = agrupar_por_tipo_material(selecionadas)
            resumos = [resumir_grupo_sc(label, sugs, criterio="tipo de material") for label, sugs in grupos_sc.items()]
            if not resumos:
                st.info("Marque ao menos um item na tabela acima para gerar as SCs sugeridas.")
            for gi, r in enumerate(resumos):
                label_curto = r["label"]
                cabecalho = f"{label_curto} · {r['n_itens']} itens · {r['prioridade']}"
                if r["comprar_ate_min"]:
                    cabecalho += (" · comprar até "
                                  + datetime.strptime(r["comprar_ate_min"], "%Y-%m-%d").strftime("%d/%m"))
                with st.expander(cabecalho, expanded=(gi == 0 and r["prioridade_tier"] == 0)):
                    st.dataframe(
                        pd.DataFrame([_linha_rep(s) for s in r["itens"]]),
                        hide_index=True, width="stretch",
                        column_config={c: st.column_config.NumberColumn(format=f)
                                       for c, f in _num_cols.items()},
                    )
                    cap = f":material/sell: Centro de custo sugerido: **{r['cc_sugerido']}**"
                    if r["valor_estimado"] > 0:
                        cap += f"  ·  :material/payments: Valor estimado: ~R$ {r['valor_estimado']:,.2f}"
                    st.caption(cap)
                    with st.form(f"form_sc_grupo_{gi}", clear_on_submit=False):
                        gc1, gc2 = st.columns([2, 1])
                        titulo_g = gc1.text_input("Título da SC (tipo do material)", value=r["titulo"],
                                                  key=f"sc_tit_{gi}")
                        num_sc_g = gc2.text_input(
                            "Número da SC *",
                            value=f"REP-{datetime.now():%Y%m%d-%H%M}-{gi + 1}",
                            key=f"sc_num_{gi}")
                        gc3, gc4 = st.columns([1, 1])
                        cc_g = gc3.text_input("Centro de custo (sugestão)", value=r["cc_sugerido"],
                                              key=f"sc_cc_{gi}")
                        dt_g = gc4.date_input("Data de abertura", value=date.today(),
                                              key=f"sc_dt_{gi}")
                        just_g = st.text_area("Justificativa", value=r["justificativa"],
                                              height=90, key=f"sc_just_{gi}")
                        criar_g = st.form_submit_button(
                            f":material/check_circle: Criar esta SC ({r['n_itens']} itens)", type="primary",
                            width="stretch")
                    if criar_g:
                        if not num_sc_g.strip():
                            st.warning(":material/warning: Informe o número da SC.")
                        else:
                            itens_g = [sugestao_para_item_sc(s, data_necessidade=str(date.today()))
                                       for s in r["itens"]]
                            _snap = pd.DataFrame([_linha_rep(s) for s in r["itens"]]).to_string(index=False)
                            obs_g = (f"{titulo_g}\nCentro de custo sugerido: {cc_g}\n\n{just_g}\n\n"
                                     f"— Tabela de reposição (anexo) —\n{_snap}")
                            ok, msg = criar_sc(num_sc_g.strip(), str(dt_g), itens_g, obs_g)
                            if ok:
                                sc_id_g = buscar_sc_id_por_numero(num_sc_g.strip())
                                for s in r["itens"]:
                                    registrar_desfecho_sugestao(s, "criou_sc", sc_id=sc_id_g)
                                st.success(f":material/check_circle: {msg} Desfechos registrados no histórico.")
                            else:
                                st.error(f":material/cancel: {msg}")

    with aba_forn:
        st.markdown("### :material/apartment: Fornecedores & Cotação")
        st.caption("Busque um material para ver seus fornecedores, último preço e lead time, "
                   "e gerar um e-mail de cotação pronto. O sistema recomenda; o comprador decide.")

        # v3.3.0 — busca única: o próprio select filtra por PN, nome OU descrição (o
        # rótulo inclui a descrição), eliminando o campo de busca redundante acima.
        opcoes_forn = {}
        for i in listar_inventario():
            desc = (i.get("descricao") or "").strip()
            rot = f"{i['part_number']} — {i['nome_item']}"
            if desc and desc.lower() not in (i.get("nome_item") or "").lower():
                rot += f" · {desc}"
            opcoes_forn[rot] = i
        lista_forn = [" "] + list(opcoes_forn.keys())
        sel_forn = st.selectbox("Selecione o material (busque por PN, nome ou descrição)",
                                lista_forn, index=0, key="forn_item_sel")
        item_forn = opcoes_forn.get(sel_forn) if sel_forn != " " else None
        if not item_forn:
            st.info("Selecione um material para consultar os fornecedores.")
        else:
            lt_cad = int(item_forn.get("lead_time_dias") or 0)
            lt_calc = item_forn.get("lead_time_calculado")
            lt_calc_txt = (
                f" · Lead time calculado: {int(lt_calc)}d "
                f"({item_forn.get('lead_time_calculado_amostras') or 0} amostras, "
                f"{item_forn.get('lead_time_calculado_origem') or '—'})"
            ) if lt_calc else ""
            st.info(
                f"**{item_forn['part_number']} — {item_forn['nome_item']}**  \n"
                f"Saldo: {(item_forn.get('estoque_atual') or 0):g} {item_forn.get('unidade', '')} · "
                f"Mínimo: {(item_forn.get('estoque_minimo') or 0):g} · "
                f"Lead time cadastrado (Compras): {lt_cad}d{lt_calc_txt}"
            )

            fs = obter_fornecedores_por_item(item_forn["id"])
            if not fs:
                st.warning("Sem fornecedores para este item ainda. Os fornecedores vêm dos "
                           "pedidos importados no Relatório de SCs (Nome Fantasia por nº do pedido).")
            else:
                melhor = next((f for f in fs if f.get("melhor")), None)
                if melhor:
                    st.success(
                        f":material/star: **Melhor fornecedor: {melhor['fornecedor']}** — {melhor['melhor_motivo']}. "
                        f"E-mail: {melhor['email'] or 'sem e-mail no cadastro'}."
                    )

                df_fs = pd.DataFrame([{
                    "Fornecedor": f["fornecedor"],
                    "Último Preço": f["ultimo_preco"],
                    "Moeda": f["moeda"],
                    "Nº Compras": f["n_compras"],
                    "Última Compra": fmt(f["ultima_data"]),
                    "Lead Time (d)": f["lead_time_fornecedor"],
                    "E-mail": f["email"] or "—",
                    "Contato": f["contato"] or "—",
                    "Telefone": f["telefone"] or "—",
                    "Cadastro": ":material/check_circle:" if f["no_cadastro"] else ":material/warning:",
                } for f in fs])
                st.dataframe(
                    df_fs, hide_index=True, width="stretch",
                    column_config={
                        "Último Preço": st.column_config.NumberColumn(format="%.2f"),
                        "Lead Time (d)": st.column_config.NumberColumn(
                            format="%d",
                            help="Mediana do prazo real (SC7) atribuído ao fornecedor via nº do pedido."),
                    },
                )
                st.caption("Ordenado por menor último preço. Lead time por fornecedor = mediana do "
                           "prazo real (SC7) atribuído pelo nº do pedido. ‘:material/warning:’ = fornecedor sem "
                           "correspondência no cadastro (sem e-mail para cotação).")

                # --- Rascunho de cotação (não envia) ---
                st.markdown("#### :material/mail: Rascunho de cotação")
                nomes = [f["fornecedor"] for f in fs]
                default_sel = [melhor["fornecedor"]] if melhor else nomes[:1]
                sel_forn = st.multiselect("Fornecedores para cotar", nomes,
                                          default=default_sel, key="forn_cotar")
                qtd_cotar = st.number_input(
                    "Quantidade a cotar", min_value=0.0,
                    value=float(item_forn.get("estoque_minimo") or 0),
                    step=1.0, key="forn_qtd")
                prazo = st.text_input("Prazo desejado (opcional)",
                                      placeholder="Ex.: até 15 dias", key="forn_prazo")

                escolhidos = [f for f in fs if f["fornecedor"] in sel_forn]
                emails = [f["email"] for f in escolhidos if f["email"]]
                sem_email = [f["fornecedor"] for f in escolhidos if not f["email"]]

                assunto = f"Cotação — {item_forn['part_number']} ({item_forn['nome_item']})"
                corpo = (
                    "Prezados,\n\n"
                    "Solicitamos cotação para o item abaixo:\n\n"
                    f"• Part Number: {item_forn['part_number']}\n"
                    f"• Descrição: {item_forn['nome_item']}\n"
                    f"• Quantidade: {qtd_cotar:g} {item_forn.get('unidade', '')}\n"
                    + (f"• Prazo desejado: {prazo}\n" if prazo else "")
                    + "\nFavor informar preço unitário, prazo de entrega e condições de pagamento.\n\n"
                    "Atenciosamente,\nCompras — Inventus Power"
                )
                st.text_area("Corpo do e-mail (copie ou edite)", corpo, height=220, key="forn_corpo")
                if emails:
                    st.markdown("**Destinatários:**")
                    st.code(", ".join(emails), language=None)
                    mailto = ("mailto:" + ",".join(emails)
                              + "?subject=" + urllib.parse.quote(assunto)
                              + "&body=" + urllib.parse.quote(corpo))
                    st.link_button(":material/mail: Abrir e-mail no meu cliente", mailto)
                elif escolhidos:
                    st.warning("Nenhum fornecedor selecionado tem e-mail no cadastro.")
                if sem_email:
                    st.caption("Sem e-mail no cadastro: " + ", ".join(sem_email))
                st.caption("O sistema **prepara** a cotação; o envio é feito pelo comprador, "
                           "no próprio cliente de e-mail.")
    # ══════════════════════════════════════════════════════════════════════════════
    #   ➕ NOVA SC (Formulário em Grid + Agrupamento Lógico)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_nova_sc:
        st.markdown("### :material/add: Nova SC")
        st.caption("**Nova SC (caso não esteja no sistema MRO).** Cadastro manual de uma "
                   "solicitação de compra que ainda não veio do Relatório de SCs.")
        if "itens_nova_sc" not in st.session_state: st.session_state.itens_nova_sc = []
        if "sc_criada" not in st.session_state: st.session_state.sc_criada = None

        if st.session_state.sc_criada:
            st.success(f":material/check_circle: {st.session_state.sc_criada}")
            if st.button(":material/add: Criar outra SC", width="stretch"):
                st.session_state.sc_criada = None; st.rerun()
            st.stop()

        # UX: Seletor de material isolado
        _, item_sc_add, _ = sel_material("Selecionar Material", "sel_sc_add")

        with st.form("form_add_isc", clear_on_submit=True):
            st.markdown("##### :material/inventory_2: Adicionar Item à Lista ")
            c1, c2 = st.columns(2)
            # Apenas Quantidade e Data de Necessidade na criação
            qtd_i   = c1.number_input("Qtd Solicitada *", min_value=0.01, step=1.0)
            d_nec   = c2.date_input("Data de Necessidade *", value=date.today())
            
            obs_i    = st.text_area("Justificativa / Urgência", placeholder="Ex: Parada de linha iminente...", height=60)
            
            add_isc = st.form_submit_button(":material/add: Adicionar à Lista", width="stretch")

        if add_isc:
            if not item_sc_add:
                st.warning(":material/warning: Selecione um material antes de adicionar.")
            else:
                st.session_state.itens_nova_sc.append({
                    "item_id": item_sc_add["id"], 
                    "part_number": item_sc_add["part_number"],
                    "nome_item": item_sc_add["nome_item"], 
                    "quantidade_solicitada": qtd_i,
                    "quantidade_pedido": qtd_i, # Inicialmente negociada = solicitada
                    "numero_po": "",            # Vazio na criação
                    "data_necessidade": str(d_nec) if d_nec else None,
                    "data_prev_nfe": None,      # Vazio na criação
                    "fornecedor_item": "",      # Vazio na criação
                    "observacao_item": obs_i,
                })
                st.rerun()
                
        if st.session_state.itens_nova_sc:
            st.markdown("###### :material/assignment: Itens Pré-cadastrados:")
            df_prev_sc = pd.DataFrame(st.session_state.itens_nova_sc)[["part_number", "nome_item", "quantidade_solicitada", "data_necessidade"]]
            df_prev_sc.columns = ["PN", "Nome", "Qtd Solic.", "Data Nec."]
            df_prev_sc["Data Nec."] = df_prev_sc["Data Nec."].apply(fmt)
            st.dataframe(df_prev_sc, width="stretch", hide_index=True)
            
            if st.button(":material/delete: Limpar Lista", type="secondary"):
                st.session_state.itens_nova_sc = []; st.rerun()

        st.divider()
        with st.form("form_criar_sc"):
            st.markdown("##### :material/edit_note: Finalizar S.C. (Registro Inicial)")
            c1, c2 = st.columns(2)
            num_sc = c1.text_input("Número da SC *", placeholder="Ex: SC-2026-001")
            dt_ab  = c2.date_input("Data de Abertura *", value=date.today())
            obs_sc = st.text_area("Observações Gerais", height=60)
            criar_b = st.form_submit_button(":material/check_circle: Criar S.C.", width="stretch", type="primary")
            
        if criar_b:
            if not num_sc.strip():
                st.warning(":material/warning: O Número da SC é obrigatório.")
            elif not st.session_state.itens_nova_sc:
                st.warning(":material/warning: Adicione ao menos um item à lista.")
            else:
                ok, msg = criar_sc(num_sc.strip(), str(dt_ab), st.session_state.itens_nova_sc, obs_sc)
                if ok:
                    st.session_state.itens_nova_sc = []
                    st.session_state.sc_criada = msg; st.rerun()
                else:
                    st.error(f":material/cancel: {msg}")

    # ══════════════════════════════════════════════════════════════════════════════
    # 🔄 ATUALIZAR STATUS E DADOS DA S.C. (Corrigido: Variáveis definidas antes do uso)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_ed:
        with st.container(border=True):
            st.markdown("### :material/sync: Atualizar Status e Dados da S.C.")
            st.caption("Preencha as informações conforme elas chegarem (PO, Fornecedor, Previsões). O status será sugerido automaticamente.")
            
            scs_todas = listar_scs()
            opc_ed = {f"SC {s['numero_sc']} — {s['status']}": s for s in scs_todas} if scs_todas else {}
            sel_ed = st.selectbox("Selecionar SC", list(opc_ed.keys()), index=None,
                                  placeholder="Selecione a S.C.…",
                                  label_visibility="collapsed") if scs_todas else None
            if not scs_todas:
                st.info("Nenhuma SC cadastrada para atualização.")
            elif sel_ed not in opc_ed:
                st.info("Selecione uma S.C. para editar seus dados.")
            else:
                sc_ed  = opc_ed[sel_ed]
                
                # ✅ CORREÇÃO 1: Carregar fornecedores das configurações
                fornecedores_cfg = listar_valores("fornecedor") or [""]
                forn_atual = sc_ed.get("fornecedor") or ""
                if forn_atual and forn_atual not in fornecedores_cfg: 
                    fornecedores_cfg.insert(0, forn_atual)
                
                idx_forn = fornecedores_cfg.index(forn_atual) if forn_atual in fornecedores_cfg else 0

                # ✅ CORREÇÃO 2: Carregar itens da SC AGORA, antes de usar na lógica de status
                itens_atuais = listar_itens_sc(sc_ed["id"])

                with st.form("form_ed_sc"):
                    st.markdown("##### :material/assignment: Informações Gerais (Cabeçalho)")
                    
                    c1, c2 = st.columns(2)
                    
                    # 1. Data de Aprovação (Gatilho para sair de 'Aguardando')
                    dt_aprovacao_val = fmt_date_input(sc_ed.get("data_aprovacao"))
                    dt_aprovacao = c1.date_input("Data de Aprovação/Cotação", value=dt_aprovacao_val)
                    
                    # 2. Fornecedor Principal (Gatilho para 'Aguardando Entrega')
                    opcoes_forn = [""] + fornecedores_cfg
                    idx_select = idx_forn + 1 if forn_atual else 0
                    fornecedor_sel = c2.selectbox("Fornecedor Principal", opcoes_forn, index=idx_select)
                    forn_final = fornecedor_sel if fornecedor_sel != "" else None

                    # 3. PO Geral (Opcional, pois cada item pode ter seu PO)
                    n_po = st.text_input("Número PO Geral (Protheus)", value=sc_ed.get("numero_po") or "")
                    
                    # 4. Observações
                    obs_ed = st.text_area("Observações Gerais", value=sc_ed.get("observacoes") or "", height=60)
                    
                    # ✅ LÓGICA DE SUGESTÃO DE STATUS INTELIGENTE (Usa itens_atuais definido acima)
                    status_atual_db = sc_ed["status"]
                    sugestao_status = status_atual_db
                    
                    # Regra 1: Se tem Fornecedor E (PO Geral ou PO em algum item), sugere Aguardando Entrega
                    tem_po_geral = bool(n_po.strip())
                    # Verifica se algum item já tem PO preenchido (usando a variável carregada anteriormente)
                    tem_po_item = any(it.get("numero_po") for it in itens_atuais if it.get("numero_po"))
                    
                    if forn_final and (tem_po_geral or tem_po_item) and status_atual_db not in ["Recebido", "Cancelado"]:
                        sugestao_status = "Aguardando Entrega"
                    
                    # Regra 2: Se tem Data Aprovação mas não tem Fornecedor, sugere Em Cotação
                    elif dt_aprovacao and not forn_final and status_atual_db == "Aguardando Aprovação":
                        sugestao_status = "Em Cotação"
                        
                    st_ed = st.selectbox("Status Atual (Sugestão Automática)", STATUS_SC, index=STATUS_SC.index(sugestao_status) if sugestao_status in STATUS_SC else 0)
                    
                    st.divider()
                    st.markdown("##### :material/inventory_2: Detalhes dos Itens (PO, Fornecedor e Previsões por Item)")
                    
                    itens_editados = []
                    # Loop pelos itens carregados anteriormente
                    for item_sc in itens_atuais:
                        with st.container(border=True):
                            st.markdown(f"`{item_sc['part_number']}` — **{item_sc['nome_item']}**")
                            
                            ci1, ci2, ci3, ci4 = st.columns(4)
                            qtd_solic = ci1.number_input("Qtd Solic.", min_value=0.0, step=1.0, value=float(item_sc.get("quantidade_solicitada") or 0), key=f"ed_qs_{item_sc['id']}")
                            qtd_neg   = ci2.number_input("Qtd Neg./Pedido", min_value=0.0, step=1.0, value=float(item_sc.get("quantidade_pedido") or item_sc.get("quantidade_solicitada") or 0), key=f"ed_qn_{item_sc['id']}")
                            
                            # Campos cruciais para o status "Aguardando Entrega"
                            po_ind   = ci3.text_input("PO Item", value=item_sc.get("numero_po") or "", key=f"ed_po_{item_sc['id']}")
                            forn_ind = ci4.text_input("Fornecedor Item", value=item_sc.get("fornecedor_item") or "", key=f"ed_forn_{item_sc['id']}")
                            
                            ci5, ci6, ci7 = st.columns(3)
                            # Previsão de Entrega/NFe
                            prev_item_none = ci5.checkbox("Sem Previsão", value=not bool(item_sc.get("data_prev_nfe")), key=f"ed_prev_none_{item_sc['id']}")
                            prev_item = None if prev_item_none else ci5.date_input("Previsão NFe/Entrega", value=fmt_date_input(item_sc.get("data_prev_nfe")), key=f"ed_prev_{item_sc['id']}")
                            
                            nec_item  = ci6.date_input("Data Necessidade", value=fmt_date_input(item_sc.get("data_necessidade")), key=f"ed_nec_{item_sc['id']}")
                            ci7.metric("Já Recebido", item_sc.get("quantidade_recebida") or 0)
                            
                        itens_editados.append({
                            "item_sc_id": item_sc["id"], 
                            "quantidade_solicitada": qtd_solic,
                            "quantidade_pedido": qtd_neg, 
                            "quantidade_recebida": item_sc.get("quantidade_recebida") or 0,
                            "numero_po": po_ind, 
                            "fornecedor_item": forn_ind,
                            "data_prev_nfe": str(prev_item) if prev_item else None,
                            "data_necessidade": str(nec_item) if nec_item else None,
                            "observacao_item": item_sc.get("observacao_item") or "",
                        })
                        
                    salv_sc = st.form_submit_button(":material/save: Salvar Atualizações", width="stretch", type="primary")
                    
                if salv_sc:
                    data_aprovacao_str = str(dt_aprovacao) if dt_aprovacao else None
                    
                    ok, msg = atualizar_sc(sc_ed["id"], data_aprovacao_str,
                        n_po or None, forn_final, None, st_ed, obs_ed or None,
                        itens=itens_editados)
                    
                    if ok:  
                        st.success(f":material/check_circle: **SC Atualizada!** Status definido como: `{st_ed}`")
                        time.sleep(2)
                        st.rerun()
                    else:  
                        st.error(f":material/cancel: {msg}")
    # ══════════════════════════════════════════════════════════════════════════════
    # 📜 HISTÓRICO (Lista Limpa + Detalhes em Caption)
    # ══════════════════════════════════════════════════════════════════════════════
    
    
    with aba_h:
        with st.container(border=True):
            st.markdown("### :material/history: Linha do Tempo de Recebimentos")
            st.caption("Registro cronológico de entradas vinculadas a S.C. — quem "
                       "entregou, quanto, contra qual PO e o que ainda falta na SC.")

            recebimentos = listar_recebimentos_sc(limit=300)
            if not recebimentos:
                st.info("ℹ️ Nenhum recebimento vinculado a SC encontrado no histórico.")
            else:
                _tot_qtd = sum(float(r["quantidade"] or 0) for r in recebimentos)
                _forns = len({(r["fornecedor"] or "").strip()
                              for r in recebimentos if r["fornecedor"]})
                _rc = st.columns(3)
                _rc[0].metric("Recebimentos", len(recebimentos))
                _rc[1].metric("Qtd total recebida", f"{_tot_qtd:g}")
                _rc[2].metric("Fornecedores distintos", _forns)
                st.caption(f"Últimos {len(recebimentos)} recebimentos (mais recentes primeiro).")
                st.divider()

                from itertools import groupby
                for _dia, _grupo in groupby(recebimentos,
                                            key=lambda r: (r["data_hora"] or "")[:10]):
                    _grupo = list(_grupo)
                    st.markdown(f"#### :material/calendar_month: {fmt(_dia)} · "
                                f"{len(_grupo)} recebimento(s)")
                    for r in _grupo:
                        with st.container(border=True):
                            _un = r["unidade"] or "UN"
                            _pend = r.get("pendente")
                            _pend_txt = (f"Ainda falta **{float(_pend):g} {_un}**"
                                         if _pend is not None and float(_pend) > 0
                                         else "**SC completa**")
                            _hora = (r["data_hora"] or "")[11:16] or "—"
                            st.markdown(
                                f"`{r['part_number']}` — **{r['nome_item']}**  |  "
                                f":material/add_box: **+{float(r['quantidade'] or 0):g} {_un}**"
                                f"  ·  {_pend_txt}")
                            _c1, _c2, _c3 = st.columns([3, 3, 2])
                            _c1.caption(f":material/apartment: **Fornecedor:** "
                                        f"{r['fornecedor'] or '—'}")
                            _c2.caption(f":material/receipt_long: **SC:** {r['numero_sc']} · "
                                        f"**PO:** {r['numero_po'] or '—'} · "
                                        f"**NF:** {r['documento_nf'] or '—'}")
                            _c3.caption(f":material/schedule: **{_hora}**")
                            _d1, _d2 = st.columns([3, 3])
                            _qs = r.get("qtd_solicitada")
                            _d1.caption(f":material/inventory_2: Solicitado na SC: "
                                        f"{_qs if _qs is not None else '—'} {_un}")
                            _d2.caption(f":material/person: Recebido por: "
                                        f"{r['emitente'] or '—'}"
                                        + (f" · {r['observacao']}" if r['observacao'] else ""))

# ══════════════════════════════════════════════════════════════════════════════
# 📇 FICHA 360 DO MATERIAL (v2.6.0) — vida útil do item em uma tela (read-only,
#     exceto a imagem do produto). Montagem de dados já existentes (v2.2–v2.5).
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Ficha 360":
    st.title(":material/badge: Ficha 360 do Material")
    st.caption("Toda a vida útil do material em uma tela — cadastro, estoque, consumo, "
               "compras, utilização, indicadores e recomendação. Somente leitura "
               "(a única escrita é a imagem do produto).")

    _, item_f, _ = sel_material("Selecione o material (PN ou nome)", "ficha_item")
    if not item_f:
        st.info("Selecione um material para ver a ficha completa.")
    else:
        ficha = montar_ficha_360(item_f["id"])
        if not ficha:
            st.error("Material não encontrado.")
        else:
            # v4.9.0 — a sub-aba Guarda-Chuva saiu da Ficha 360 e virou um controle
            # próprio e manual em "Controle de SC → ☂️ Guarda-Chuva" (tabela guarda_chuva).
            # A Ficha 360 volta a ser só a Visão Geral (read-only).
            _render_ficha_visao_geral(ficha)
