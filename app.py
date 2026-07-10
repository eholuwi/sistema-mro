from services.db_functions import obter_dados_dashboard 
import streamlit as st
import pandas as pd
import json, io, os, sys, time, urllib.parse
from streamlit_option_menu import option_menu
from datetime import date, datetime
from services.styles import inject_custom_css
from services.tema import paleta
from services.logging_config import setup_logging
from services.constants import (
    PREVISAO_RUPTURA_SEM_RISCO, ORDENACAO_RUPTURA_INFINITO,
    AGING_ALERTA_DIAS, AGING_CRITICO_DIAS, RUPTURA_CRISE_DIAS,
    PADROES_DEMANDA,
)

sys.path.insert(0, os.path.dirname(__file__))
from database import criar_banco
from services.db_functions import (
    buscar_item_por_id, listar_inventario, salvar_item, desmarcar_inventariado,
    registrar_movimentacao, listar_movimentacoes,
    criar_sc, atualizar_sc, registrar_recebimento_sc, listar_scs,
    listar_itens_sc, buscar_scs_por_item, exportar_inventario_df,
    listar_valores, adicionar_valor_lista, remover_valor_lista,
    listar_setores_conhecidos, sincronizar_setores_config,
    criar_requisicao, listar_requisicoes, listar_itens_requisicao,
    importar_solicitacoes_protheus, listar_recebimentos_sc,
    atualizar_localizacao_e_inventariar, atualizar_item_inventario,
    obter_analitico_movimentacoes, obter_analitico_divergencias,
    obter_analitico_rupturas, exportar_movimentacoes_df,
    importar_inventario_neidson, alterar_part_number,
    listar_historico_part_number, buscar_item_por_pn,
    registrar_feedback, listar_feedbacks, atualizar_feedback,
    importar_relatorio_scs, tirar_snapshot_estoque,
    obter_maturidade_dados, calcular_giro,
    obter_valor_imobilizado, obter_evolucao_valor_imobilizado,
    obter_evolucao_preco, obter_abc_valor,
    obter_fornecedores_por_item,
    filtrar_itens_por_busca, sincronizar_fornecedores_lista,
    sugerir_conversao,
)
from services.constants import UNIDADES_COMPRA_SUGERIDAS, FATOR_CONVERSAO_PADRAO
from services.planejamento import (
    gerar_sugestoes_reposicao, sugestao_para_item_sc,
    registrar_desfecho_sugestao, listar_sugestoes, buscar_sc_id_por_numero,
    agrupar_por_tipo_material, resumir_grupo_sc,
)
from services.ficha import (
    montar_ficha_360, salvar_imagem_item, remover_imagem_item,
    agrupar_saldo_residual_por_fornecedor,
)
from services.ajuda_conteudo import GUIAS_PERSONA, MANUAL
from services.dashboards import (
    montar_dashboard,
    PUBLICO_COMPRADOR, PUBLICO_GESTAO, PUBLICO_EXECUTIVO,
)

setup_logging()
criar_banco()

# v2.2.0 — foto diária do estoque (idempotente por dia; sem scheduler externo).
# Só executa a primeira vez que o app abre no dia; nas demais é praticamente no-op.
try:
    tirar_snapshot_estoque()
except Exception:
    pass

st.set_page_config(page_title="MRO Inventus Power 3.3.0", page_icon=":material/build:", layout="wide", initial_sidebar_state="expanded")


def tema_atual():
    """Tema escolhido pelo usuário ('light'/'dark'), lido da URL (?tema=) para persistir
    ao recarregar. Padrão ESCURO. O Streamlit 1.57 não troca o tema por código, então
    o app o controla: um botão na sidebar grava `?tema=` e o CSS/paleta reaplica tudo."""
    try:
        v = st.query_params.get("tema", "dark")
    except Exception:
        v = "dark"
    return "light" if v == "light" else "dark"


# Paleta única do tema escolhido — consumida pelo CSS global, pelo option_menu e pelos
# gráficos, para tudo acompanhar claro/escuro (v2.11.0).
PAL = paleta(tema_atual())
inject_custom_css(PAL)

IMPORTANCIAS = ["Parada de Linha","Importante","Admin"]
# tipo_material agora é livre (v2.1.0); a lista abaixo são apenas sugestões e inclui
# as categorias apuradas pela base do Sr. Neidson. Campos pré-selecionam o valor atual.
TIPOS        = ["Spare Parts","Consumivel","Expediente","Uniforme","Improdutivo",
                "Químico","ESD","Vestimenta ESD","Corte","Ponta","Limpeza Stencil",
                "Impressão","Embalagem"]
SETORES      = ["Improdutivo","Engenharia de SMT","LED DRIVER","MANUTENÇÃO","PRODUÇÃO","QUALIDADE","ALMOXARIFADO","ADMINISTRATIVO","SESMT"]
UNIDADES     = ["UN","CX","GL","RL","PCT","LT","RM"]
STATUS_SC    = ["Aguardando Aprovação","Em Cotação","Pedido Emitido",
                "Aguardando Entrega","Parcial","Recebido","Cancelado"]
TIPOS_FEEDBACK = ["Sugestão de melhoria","Nova funcionalidade","Melhoria de design",
                  "Melhoria de UI","Melhoria de UX","Relato de bug","Relato de glitch",
                  "Problema operacional","Outra observação"]
STATUS_FEEDBACK = ["Novo","Em análise","Planejado","Em andamento","Concluído","Recusado"]

def fmt(s):
    if not s: return "—"
    try: return datetime.strptime(s,"%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        try: return datetime.strptime(s,"%Y-%m-%d").strftime("%d/%m/%Y")
        except (ValueError, TypeError): return s

def fmt_date_input(s):
    if not s: return date.today()
    try: return datetime.strptime(s,"%Y-%m-%d").date()
    except (ValueError, TypeError): return date.today()

def itens_select():
    return {f"{i['part_number']} — {i['nome_item']}": i for i in listar_inventario()}

def sel_material(label, key, placeholder=" "):
    """Selectbox com opção vazia no topo para forçar seleção consciente."""
    opcoes = itens_select()
    lista = [placeholder] + list(opcoes.keys())
    sel = st.selectbox(label, lista, index=0, key=key)
    item = opcoes.get(sel) if sel != placeholder else None
    return sel, item, opcoes

def opcoes_com_atual(base, atual):
    """Garante que o valor atual (ex.: tipo livre vindo da base do Neidson) apareça
    na lista de opções, evitando que o selectbox troque silenciosamente o valor."""
    opcoes = list(base)
    if atual and atual not in opcoes:
        opcoes = [atual] + opcoes
    return opcoes

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    # 1. Cabeçalho com Logo/Título
    st.markdown("""
    <div class="sidebar-title">
        <span style="font-size: 1.8rem;">MRO Inventus 3.3.0</span>
    </div>
    """, unsafe_allow_html=True)

    # 2. Navegação (Option Menu)

    opcoes_limpas = ["Dashboard", "Inventário", "Ficha 360", "Gerenciar Itens", "Movimentações", "Requisição", "Controle de SC", "Ajuda", "Configurações"]

    escolha_limpa = option_menu(
        menu_title=None,
        options=opcoes_limpas,
        icons=["bar-chart-fill", "box-seam", "card-image", "plus-circle", "arrow-repeat", "clipboard-check", "receipt", "question-circle", "gear"],
        menu_icon="cast",
        default_index=0,
        styles=PAL["option_menu_styles"],
    )

    # 'pagina' = nome limpo escolhido no menu (o próprio option_menu já mostra o ícone).
    pagina = escolha_limpa

    # 2b. Tema (claro/escuro) — controlado pelo app e lembrado na URL (?tema=).
    # O Streamlit 1.57 não troca o tema por código; aqui gravamos a escolha e o topo do
    # script reaplica a paleta. Padrão escuro. (Tabelas seguem o tema base do config.)
    _op_tema = {"Claro": "light", "Escuro": "dark"}
    _lbl_atual = "Escuro" if PAL["tipo"] == "dark" else "Claro"
    _escolha_tema = st.radio("Tema", list(_op_tema.keys()),
                             index=list(_op_tema.keys()).index(_lbl_atual),
                             horizontal=True, key="sb_tema")
    if _op_tema[_escolha_tema] != PAL["tipo"]:
        st.query_params["tema"] = _op_tema[_escolha_tema]
        st.rerun()

    st.markdown("---")

    # 3. Métricas em Grid (Visual da Imagem)
    itens_all = listar_inventario()
    total = len(itens_all)
    # Ajuste conforme sua lógica de status atual (OK, ATENÇÃO, COMPRAR)
    comprar = sum(1 for i in itens_all if "COMPRAR" in i.get("status_material", ""))
    atencao = sum(1 for i in itens_all if "ATENÇÃO" in i.get("status_material", ""))
    scs_abertas = len(listar_scs(apenas_abertas=True))
    inv_count = sum(1 for i in itens_all if i.get("data_inventario"))

    st.markdown(f"""
    <div class="sidebar-metrics-grid">
        <div class="metric-card">
            <div class="metric-label">Total</div>
            <div class="metric-value">{total}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Alerta <span class="dot dot-yellow"></span></div>
            <div class="metric-value">{atencao}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Críticos <span class="dot dot-red"></span></div>
            <div class="metric-value">{comprar}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">SCs</div>
            <div class="metric-value">{scs_abertas}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 4. Barra de Progresso de Inventário
    progresso = inv_count / total if total > 0 else 0
    st.markdown(f"""
    <div class="progress-container">
        <div class="progress-label">Inventariados: {inv_count}/{total}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Usa o st.progress nativo, mas o CSS acima tenta estilizar o container se possível
    # Ou podemos usar uma barra HTML customizada se o st.progress ficar claro demais
    st.progress(progresso)

    # 5. Perfil do Usuário (Rodapé)
    # Você pode trocar a URL da imagem por uma local ou base64 se preferir
    avatar_url = "https://ui-avatars.com/api/?name=Luis+Oliveira&background=F36F21&color=fff" 
    
    st.markdown(f"""
    <div class="user-profile">
        <img src="{avatar_url}" class="user-avatar" alt="User">
        <div class="user-info">
            <h4>Luis Oliveira</h4>
            <p>Inventus Power</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

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


def _render_dash_gestao(vm):
    """:material/bar_chart: Gestão — saúde da operação: serviço, cobertura, valor, giro, status e demanda."""
    k = vm["kpis"]
    c1, c2, c3, c4 = st.columns(4)
    ns = k["nivel_servico"]
    c1.metric(":material/ads_click: Nível de Serviço", f"{ns}%" if ns is not None else "—",
              help="% dos itens COM consumo real que estão fora de ruptura (estoque > 0). "
                   "Proxy de disponibilidade — NÃO é OTIF de fornecedor (esse depende de dado ainda ausente).")
    cm = k["cobertura_media"]
    c2.metric(":material/calendar_month: Cobertura média", f"{cm} d" if cm is not None else "—",
              help="Média de dias de cobertura (estoque atual ÷ consumo) dos itens com consumo; "
                   "exclui itens sem consumo.")
    c3.metric(":material/payments: Valor imobilizado", _dash_fmt_brl(k["valor_imobilizado"]),
              help="Σ(estoque × preço de valoração), em BRL. Detalhe logo abaixo.")
    gm = k["giro_medio"]
    c4.metric(":material/sync: Giro médio (ano)", f"{gm}x" if gm is not None else "—",
              help="Média do giro anual dos itens com saída na janela de 90 dias.")

    vd = vm["valor_detalhe"]
    st.caption(
        f":material/payments: Valor: {vd['itens_valorados']} itens valorados · "
        f"{vd['itens_sem_preco']} com estoque sem preço (subestima o total) · "
        f"{vd['itens_nao_brl']} em moeda ≠ BRL ({_dash_fmt_brl(vd['total_nao_brl'])}, somados à parte)."
    )
    st.markdown("---")

    d = vm["distribuicao"]; total = vm["total"]
    def _pct(n): return f"{round(n / total * 100)}%" if total else "0%"
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    s1.metric(":material/check_circle: OK", d["ok"], _pct(d["ok"]))
    s2.metric("🟡 Atenção", d["atencao"], _pct(d["atencao"]), delta_color="off")
    s3.metric(":material/warning: Críticos", d["comprar"], _pct(d["comprar"]), delta_color="inverse")
    s4.metric("⚪ Sem Mov.", d["sem_mov"], _pct(d["sem_mov"]), delta_color="off",
              help="Nunca tiveram saída por requisição — ficam fora da lista de compra.")
    s5.metric("🔴 Zerados", d["zerados"], _pct(d["zerados"]), delta_color="inverse")
    s6.metric(":material/search: Inventariado", f"{d['inventariado']}/{total}", _pct(d["inventariado"]))

    st.markdown("---")

    # Saúde física do estoque — conta TODOS os itens (inclusive Sem Movimentação),
    # pelo nível físico vs. mínimo. Complementa a linha acima (que tira o Sem Mov. da compra).
    sf = vm["saude_fisica"]
    st.markdown("#### :material/monitor_heart: Saúde física do estoque")
    st.caption("Nível físico de **todos** os itens vs. estoque mínimo — inclui também os "
               "**Sem Movimentação** (por isso o total difere da linha acima, que os separa da compra).")
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("🟢 Ok", sf["ok"], _pct(sf["ok"]),
              help="Acima do nível confortável (mínimo × 1,2).")
    h2.metric("🟡 Atenção", sf["atencao"], _pct(sf["atencao"]), delta_color="off",
              help="Perto de ficar abaixo do mínimo (entre o mínimo e mínimo × 1,2).")
    h3.metric("🔴 Crítico", sf["critico"], _pct(sf["critico"]), delta_color="inverse",
              help="Abaixo ou no mínimo, mas ainda com saldo (> 0).")
    h4.metric("⚫ Zerado", sf["zerado"], _pct(sf["zerado"]), delta_color="inverse",
              help="Estoque atual = 0.")

    st.markdown("---")
    colA, colB = st.columns(2)

    with colA:
        with st.container(border=True):
            st.markdown("#### :material/trending_down: Top 10 Consumidores (mês anterior)")
            dados = obter_dados_dashboard()
            st.caption(f"Referência: consumo real de {dados['kpis'].get('periodo_abc', '—')}.")
            df_abc = pd.DataFrame(dados["abc"])
            if not df_abc.empty:
                import plotly.graph_objects as go
                df_abc = df_abc.sort_values("total_saida", ascending=True)
                df_abc["lbl"] = df_abc.apply(lambda x: f"{x['part_number']} • {str(x['nome_item'])[:15]}", axis=1)
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
            else:
                st.info("Sem consumo registrado no período.")

    with colB:
        with st.container(border=True):
            st.markdown("#### :material/science: Padrões de demanda")
            st.caption("Cada item é lido por duas coisas: **com que regularidade** ele sai e "
                       "**o quanto o tamanho de cada saída varia**. Juntas, essas medidas "
                       "indicam o quão previsível é repor cada material.")
            ordem = ["Suave", "Intermitente", "Errático", "Irregular", "Poucos dados"]
            dem = vm["demanda"]
            dados_dem = [{"Padrão": p, "Itens": dem.get(p, 0)} for p in ordem if dem.get(p, 0)]
            if dados_dem:
                st.bar_chart(pd.DataFrame(dados_dem).set_index("Padrão"), color="#F7941E", height=200)
            else:
                st.caption("Ainda sem consumo real suficiente para classificar.")

            # Legenda: o que cada padrão significa (frases já validadas em PADROES_DEMANDA),
            # com a contagem de itens ao lado — para o gestor ler sem precisar do jargão.
            _expl = {v["label"]: (v["emoji"], v["explicacao"]) for v in PADROES_DEMANDA.values()}
            st.markdown("**O que cada padrão significa:**")
            for p in ["Suave", "Intermitente", "Errático", "Irregular"]:
                emoji, exp = _expl[p]
                n = dem.get(p, 0)
                st.markdown(
                    f"{emoji} **{p}** — {exp} "
                    f"<span style='opacity:.65'>· {n} {'item' if n == 1 else 'itens'}</span>",
                    unsafe_allow_html=True)

            xyz = vm["xyz"]
            if xyz:
                st.caption("**XYZ** mede o quanto o consumo varia de mês a mês "
                           "(X estável · Y variável · Z errático — baixa confiança com poucos meses): "
                           f"X {xyz.get('X', 0)} · Y {xyz.get('Y', 0)} · Z {xyz.get('Z', 0)}.")

            with st.expander("Como é calculado"):
                st.caption("Método de Syntetos-Boylan (SBC): combina o **intervalo médio entre "
                           "saídas** (regularidade no tempo) com a **variação das quantidades** "
                           "(regularidade no tamanho), a partir das saídas reais por requisição. "
                           "É apoio à decisão — não altera o cálculo de reposição.")

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


def _barh(labels, values, textos, cor=None, height=300):
    """Gráfico de barras horizontais (ranking). `labels`/`values`/`textos` já na ordem
    de exibição (maior no topo = último da lista, convenção do Plotly horizontal)."""
    import plotly.graph_objects as go
    fig = go.Figure(go.Bar(
        y=labels, x=values, orientation="h",
        marker=dict(color=cor or PAL["accent"], line=dict(width=1, color=PAL["accent_borda"])),
        text=textos, textposition="auto",
        textfont=dict(size=11, color=PAL["texto"]), hoverinfo="skip"))
    fig.update_layout(
        template=PAL["plotly_template"], height=height,
        margin=dict(l=0, r=16, t=6, b=0), paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"], showlegend=False,
        font=dict(family="Inter", color=PAL["texto"]),
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, tickfont=dict(size=11, color=PAL["texto"])))
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
        _ph = "— selecione uma SC —"
        sel = st.selectbox("Selecione a SC / PO", [_ph] + list(opc.keys()), key="rec_sc_sel")
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


def _bloco_top(titulo, itens, label_fn, value_key, value_fmt, cor=None,
               height=300, caption=None):
    """Renderiza um card com um ranking Top N em barras horizontais (maior no topo)."""
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
        st.plotly_chart(_barh(labels, values, textos, cor, height),
                        width="stretch", config={"displayModeBar": False})


def _render_dash_executivo(vm):
    """:material/insights: Mensal — panorama do ano corrente (YTD): KPIs em R$/serviço, séries, ABC e vários Top 10."""
    ano = vm["ano"]
    st.subheader(f":material/insights: Panorama {ano} — visão executiva")
    st.caption(f"Tudo nesta tela é do **ano corrente ({ano})**, de 1º de janeiro até hoje. "
               "Consumo = saídas reais por requisição (ajustes de inventário não entram). "
               "Valores em R$ pela valoração de referência (último preço negociado).")

    k = vm["kpis"]; vd = vm["valor_detalhe"]
    # ── Faixa 1: financeiro / volume ──
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(":material/payments: Valor imobilizado", _dash_fmt_brl(k["valor_imobilizado"]),
              help="Capital parado em estoque hoje: Σ(estoque × preço de referência).")
    c2.metric(":material/shopping_cart: Consumido no ano (YTD)", _dash_fmt_brl(k["valor_consumido_ytd"]),
              help="Valor total consumido de 1º/jan até hoje (saídas reais × preço).")
    c3.metric(":material/assignment: Requisições (YTD)", f"{k['n_requisicoes_ytd']:,}".replace(",", "."),
              help="Nº de requisições atendidas no ano corrente.")
    c4.metric(":material/inventory_2: Itens movimentados (YTD)", k["itens_consumidos_ytd"],
              help="Quantos itens diferentes tiveram consumo real no ano.")
    st.caption(f":material/info: Valoração: {vd['itens_valorados']} itens com preço · "
               f"{vd['itens_sem_preco']} com estoque sem preço (subestima o total).")

    # ── Faixa 2: operação / serviço ──
    o1, o2, o3, o4 = st.columns(4)
    ns = k["nivel_servico"]
    o1.metric(":material/ads_click: Nível de serviço", f"{ns}%" if ns is not None else "—",
              help="% dos itens com consumo real fora de ruptura. Proxy de disponibilidade.")
    gm = k["giro_medio"]
    o2.metric(":material/sync: Giro médio (ano)", f"{gm}x" if gm is not None else "—",
              help="Quantas vezes o estoque se renova por ano, em média.")
    o3.metric("🔴 Críticos", k["criticos"], delta_color="off",
              help="Itens que já precisam de compra agora (abaixo do ponto de pedido).")
    o4.metric(":material/emergency: Rupturas", k["rupturas"], delta_color="off",
              help="Itens com consumo real e estoque zerado — risco imediato.")

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
            else:
                st.caption("Sem consumo valorado no ano.")

    # ── Curva ABC ──
    with st.container(border=True):
        abc = vm["abc"]; classes = abc["classes"]
        st.markdown("#### :material/emoji_events: Curva ABC por valor consumido (ano corrente)")
        st.caption("Poucos itens concentram a maior parte do gasto — classe A = os que mais pesam.")
        ca, cb, cc = st.columns(3)
        ca.metric("🅰️ Classe A", classes.get("A", 0), help="Itens que somam até 80% do valor consumido.")
        cb.metric("🅱️ Classe B", classes.get("B", 0), delta_color="off", help="De 80% a 95% do valor.")
        cc.metric("🅲 Classe C", classes.get("C", 0), delta_color="off", help="Os 5% finais do valor.")
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


if pagina == "Dashboard":
    st.title(":material/bar_chart: Dashboard — MRO Inventus Power")
    if not listar_inventario():
        st.info("Nenhum item cadastrado. Vá em **:material/add: Gerenciar Itens** para começar.")
        st.stop()

    # v3.3.0 — abas por público (substitui as "bolinhas"/radio), no mesmo padrão das
    # telas Controle de SC / Movimentações. Diretoria removida; "Mensal" → "KPI Mensal".
    tab_comp, tab_gest, tab_mensal = st.tabs(
        [f":material/person: {PUBLICO_COMPRADOR}",
         f":material/insights: {PUBLICO_GESTAO}",
         f":material/calendar_month: {PUBLICO_EXECUTIVO}"])
    with tab_comp:
        _render_dash_comprador(montar_dashboard(PUBLICO_COMPRADOR))
    with tab_gest:
        _render_dash_gestao(montar_dashboard(PUBLICO_GESTAO))
    with tab_mensal:
        _render_dash_executivo(montar_dashboard(PUBLICO_EXECUTIVO))

# ══════════════════════════════════════════════════════════════════════════════
# INVENTÁRIO
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Inventário":
    st.title(":material/assignment: Inventário MRO")
    itens = listar_inventario()
    if not itens:
        st.info("Nenhum item cadastrado. Vá em **:material/add: Gerenciar Itens** para começar.")
        st.stop()

    # --- CONTAINER 1: FILTROS ---
    with st.container(border=True):
        with st.expander(":material/search: Filtros Avançados", expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            
            locais_db = listar_valores("local")
            if not locais_db:
                locais_db = [f"ARM-{i:02d}" for i in range(1, 6)] + [f"MRO-{i:02d}" for i in range(1, 6)]
                
            f_loc    = c1.selectbox(":material/location_on: Localização", ["Todas"] + locais_db)
            f_imp    = c2.multiselect("Importância", IMPORTANCIAS)
            f_tipo   = c3.multiselect("Tipo", TIPOS)
            f_status = c4.multiselect("Status", ["🟢 OK", "🟡 ATENÇÃO", "🔴 COMPRAR", "⚪ Sem Movimentação"])
            
            c5, c6 = st.columns(2)
            f_busca  = c5.text_input(":material/search: Buscar PN ou Nome")
            f_inv    = c6.selectbox("Inventariado", ["Todos", "Inventariado", "Não inventariado"])
        

        df = pd.DataFrame(itens)
        
        # Aplicação dos Filtros
        if f_loc != "Todas":
            if "local_armazenagem" in df.columns:
                df = df[df["local_armazenagem"] == f_loc]
            
        if f_imp:    
            df = df[df["importancia"].isin(f_imp)]
        if f_tipo:   
            df = df[df["tipo_material"].isin(f_tipo)]
        if f_status: 
            col_status = "status_material" if "status_material" in df.columns else "status_display"
            if col_status in df.columns:
                df = df[df[col_status].isin(f_status)]
            
        if f_inv == "Inventariado":
            df = df[df["data_inventario"].fillna("").str.strip().str.len() > 0]
        if f_inv == "Não inventariado": 
            df = df[~(df["data_inventario"].fillna("").str.strip().str.len() > 0)]
            
        if f_busca:
            b = f_busca.lower()
            df = df[df["part_number"].str.lower().str.contains(b, na=False) | 
                    df["nome_item"].str.lower().str.contains(b, na=False)]

        st.caption(f":material/bar_chart: Exibindo **{len(df)}** de **{len(itens)}** itens")

    # --- CONTAINER 2: TABELA PRINCIPAL ---
    with st.container(border=True):
        # v2.9.0: aviso forward-only de unidade a revisar (comprado em UM ≠ estoque e
        # ainda sem fator de conversão → recebimento pode somar quantidade crua).
        if "unidade_divergente" in df.columns:
            _n_div = int(df["unidade_divergente"].fillna(False).astype(bool).sum())
            if _n_div:
                st.warning(f":material/warning: **{_n_div}** item(ns) comprado(s) em unidade diferente da de estoque "
                           "e ainda **sem fator de conversão**. Revise em **Gerenciar Itens → "
                           "Conversão de unidades** — até lá o recebimento pode somar quantidade crua.")

        cols_show = [
            "part_number", "nome_item", "importancia", "unidade", "tipo_material",
            "local_armazenagem",
            "estoque_minimo", "estoque_maximo", "estoque_atual",
            "status_material", "previsao_ruptura_dias", "data_inventario",
            "lead_time_dias", "sc_numero", "status_sc", "sc_po",
            "caixa_identificacao" # Adicionado para visualização rápida da obs
        ]
        cols_show = [c for c in cols_show if c in df.columns]

        df_exib = df[cols_show].copy()
        df_exib["data_inventario"] = df_exib["data_inventario"].apply(lambda v: fmt(v) if v else "—")
        # v2.9.0: marca visual "⚠️" para itens com unidade a revisar.
        if "unidade_divergente" in df.columns:
            df_exib["Un?"] = df["unidade_divergente"].map(lambda v: "Revisar" if v else "")
        # v2.10.0 (diagnóstico): padrão de demanda (SBC) e classe XYZ derivados.
        if "padrao_demanda" in df.columns:
            df_exib["Demanda"] = df["padrao_demanda"].fillna("—")
        if "classe_xyz" in df.columns:
            df_exib["XYZ"] = df["classe_xyz"].fillna("—")

        num_linhas = len(df_exib)
        altura_tabela = min(40 + (num_linhas * 35), 320) if num_linhas > 0 else 100

        st.dataframe(
            df_exib,
            width="stretch",
            hide_index=True,
            height=altura_tabela,
            column_config={
                "part_number": st.column_config.TextColumn("PN", width="small"),
                "nome_item": st.column_config.TextColumn("Nome", width="medium"),
                "unidade": st.column_config.TextColumn("UN", width="small"),
                "tipo_material": st.column_config.TextColumn("TIPO", width="small"),
                "local_armazenagem": st.column_config.TextColumn("Localidade", width="small"),
                "estoque_minimo": st.column_config.NumberColumn("Mínimo", format="%d"),
                "estoque_maximo": st.column_config.NumberColumn("Máximo", format="%d"),
                "estoque_atual": st.column_config.NumberColumn("Estoque", format="%d"),
                "status_material": st.column_config.TextColumn("Status Material", width="small"),
                "previsao_ruptura_dias": st.column_config.NumberColumn("Dias Ruptura", format="%d"),
                "data_inventario": st.column_config.TextColumn("Inventariado", width="small"),
                "lead_time_dias": st.column_config.NumberColumn("Lead Time", format="%d"),
                "sc_numero": st.column_config.TextColumn("Nº SC", width="small"),
                "status_sc": st.column_config.TextColumn("Status SC", width="small"),
                "sc_po": st.column_config.TextColumn("P.O.", width="small"),
                "caixa_identificacao": st.column_config.TextColumn("Obs. Inventário", width="medium"), # Nova coluna na tabela
                "Un?": st.column_config.TextColumn("Un?", width="small",
                    help=":material/warning: = comprado em unidade diferente da de estoque e ainda sem fator de conversão."),
                "Demanda": st.column_config.TextColumn("Demanda", width="small",
                    help="Padrão de demanda (Syntetos-Boylan) pelas saídas reais: Suave/Intermitente/"
                         "Errático/Irregular. Diagnóstico — não altera a reposição. Detalhe na Ficha 360."),
                "XYZ": st.column_config.TextColumn("XYZ", width="small",
                    help="Variabilidade do consumo mensal: X=estável, Y=variável, Z=errático "
                         "(baixa confiança com poucos meses de histórico)."),
            }
        )

    # --- CONTAINER 3: CONTAGEM FÍSICA ---
    with st.container(border=True):
        st.subheader(":material/inventory_2: Realizar Contagem Física")
        _, item_inv, _ = sel_material("Selecione o item para atualizar saldo/localização", "sel_inventario")

        if item_inv:
            st.info(f"**Item:** `{item_inv['part_number']} — {item_inv['nome_item']}` | **Saldo Atual:** `{item_inv['estoque_atual']} {item_inv.get('unidade','UN')}`")

            # Carrega locais disponíveis
            locais_disp = listar_valores("local") or ["Geral"]
            if item_inv.get("local_armazenagem") and item_inv.get("local_armazenagem") not in locais_disp: 
                locais_disp.insert(0, item_inv["local_armazenagem"])
            
            c_q, c_l, c_l2 = st.columns(3)

            # Inicializa com o estoque atual. Se for 0, começa em 0.
            nova_qtd = c_q.number_input("Quantidade Real", min_value=0.0, step=1.0, value=float(item_inv['estoque_atual']))

            # Selectbox de Local (Obrigatório)
            local_atual = item_inv.get("local_armazenagem")
            idx_local_inicial = 0
            if local_atual and local_atual in locais_disp:
                idx_local_inicial = locais_disp.index(local_atual)

            novo_local = c_l.selectbox("Local (1ª Locação)", options=locais_disp, index=idx_local_inicial)

            # v3.4.0: 2ª locação (opcional) — 2º ponto de armazenagem do mesmo item,
            # independente do Ajuste Rápido de Movimentações (que permanece intacto).
            _op_l2 = ["—"] + locais_disp
            _l2_atual = item_inv.get("local_armazenagem_2") or ""
            _idx_l2 = _op_l2.index(_l2_atual) if _l2_atual in _op_l2 else 0
            novo_local_2 = c_l2.selectbox(
                "Local (2ª Locação)", options=_op_l2, index=_idx_l2,
                help="Opcional — 2º ponto de armazenagem do mesmo item. '—' = sem 2ª locação.")
            
            # ✅ NOVO CAMPO: Observação Operacional (Texto Livre)
            obs_inventario = st.text_input(
                ":material/edit_note: Observação de Inventário", 
                value=item_inv.get("caixa_identificacao") or "", 
                placeholder="Ex: material danificado, sem etiqueta, divergência física, caixa avariada..."
            )

            col_btn1, col_btn2, _ = st.columns([1, 1, 2])
            
            if col_btn1.button(":material/check_circle: Confirmar Contagem", type="primary", width="stretch"):
                delta = nova_qtd - item_inv['estoque_atual']
                
                # Verifica mudanças operacionais
                mudou_local = (novo_local != item_inv.get("local_armazenagem"))
                _l2_val = None if novo_local_2 == "—" else novo_local_2
                _l2_norm = _l2_val or ""
                mudou_local2 = (_l2_norm != (item_inv.get("local_armazenagem_2") or ""))
                mudou_obs = (obs_inventario.strip() != (item_inv.get("caixa_identificacao") or "").strip())
                mudou_qtd = (delta != 0)

                # Se nada mudou, avisa o usuário
                if not mudou_qtd and not mudou_local and not mudou_local2 and not mudou_obs:
                    st.warning(":material/warning: Nenhuma alteração detectada. O item já está com esses dados.")
                else:
                    # 1. Atualiza sempre os metadados (Local, 2ª Locação e Obs) e marca como inventariado
                    ok_loc, msg_loc = atualizar_localizacao_e_inventariar(
                        item_inv["id"], novo_local, obs_inventario, novo_local_2=_l2_val)
                    
                    if ok_loc:
                        # 2. Lógica de Movimentação (Histórico)
                        # Precisamos registrar no histórico se houve mudança de QTD OU de Metadados (Local/Obs)
                        
                        obs_partes = []
                        if mudou_local:
                            obs_partes.append(f"Local: {item_inv.get('local_armazenagem','N/A')} → {novo_local}")
                        if mudou_local2:
                            obs_partes.append(f"2ª Locação: '{item_inv.get('local_armazenagem_2') or ''}' → '{_l2_norm}'")
                        if mudou_obs:
                            obs_partes.append(f"Obs: '{item_inv.get('caixa_identificacao','')}' → '{obs_inventario}'")
                        
                        # Se houve mudança de quantidade, registramos entrada/saída normal
                        if mudou_qtd:
                            tipo_aj = "entrada" if delta > 0 else "saida"
                            qtd_reg = abs(delta)
                            
                            obs_final = f"Ajuste Físico {' | '.join(obs_partes)} | Qtd: {item_inv['estoque_atual']} → {nova_qtd}"
                            
                            registrar_movimentacao(
                                item_id=item_inv["id"], tipo=tipo_aj, quantidade=qtd_reg,
                                centro_custo="INVENTÁRIO", solicitante="Inventário", emitente="Inventário",
                                observacao=obs_final
                            )
                        
                        # ✅ CORREÇÃO: Se NÃO mudou quantidade, mas mudou Local/Obs, registramos uma "Conferência"
                        # Usamos tipo 'entrada' com qtd 0 apenas para gerar o log histórico, 
                        # pois a tabela exige um tipo válido.
                        elif mudou_local or mudou_local2 or mudou_obs:
                            obs_final = f"Conferência de Inventário (Sem alteração de Qtd) {' | '.join(obs_partes)}"
                            
                            registrar_movimentacao(
                                item_id=item_inv["id"], tipo="entrada", quantidade=0.0, # Qtd 0 para não alterar saldo
                                centro_custo="INVENTÁRIO", solicitante="Inventário", emitente="Inventário",
                                observacao=obs_final
                            )

                        st.success(f":material/check_circle: Contagem registrada! Novo saldo: `{nova_qtd}`")
                        time.sleep(1.2)
                        st.rerun()
                    else:
                        st.error(f":material/cancel: Erro ao atualizar localização: {msg_loc}")

            if item_inv.get("data_inventario") and col_btn2.button(":material/cancel: Remover Marcação", width="stretch"):
                desmarcar_inventariado(item_inv["id"])
                st.warning("Marcação de inventário removida.")
                time.sleep(1.2)
                st.rerun()

    # --- EXPORTAÇÃO ---
    st.markdown("---")
    col_exp, _, _ = st.columns([1, 3, 1])
    with col_exp:
        df_exp = exportar_inventario_df()
        if not df_exp.empty:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df_exp.to_excel(w, index=False, sheet_name="Inventário")
            st.download_button(
                "⬇️ Exportar Excel", data=buf.getvalue(),
                file_name=f"inventario_mro_{date.today().strftime('%d-%m-%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    

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
                desc_novo = st.text_area("Descrição", placeholder="Informações adicionais sobre o item", height=80)
                un_novo = st.selectbox("Unidade", UNIDADES, index=0)
                tipo_novo = st.selectbox("Tipo / Categoria", TIPOS, index=0)
            
            with c2:
                imp_novo = st.selectbox("Importância", IMPORTANCIAS, index=0)
                loc_novo = st.selectbox("Localidade", listar_valores("local") or ["Geral"], index=0)
                caixa_novo = st.selectbox("Caixa/ID", listar_valores("local") or ["Geral"], index=0)
                lead_novo = st.number_input("Lead Time (Dias)", min_value=1, value=7)

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
                        "da de estoque (visto nos POs), mas ainda **sem fator de conversão** "
                        "(fator = 1). Defina a *unidade de compra* e o *fator* abaixo para que "
                        "o recebimento converta corretamente."
                    )
                ed_desc = st.text_area("Descrição / Observação", value=item_sel.get('descricao', ''), height=70, key="ed_desc")

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
                    ed_caixa = st.selectbox("Caixa/ID", locais_opts,
                                            index=locais_opts.index(item_sel.get('caixa_identificacao', 'Geral')) if item_sel.get('caixa_identificacao') in locais_opts else 0, key="ed_caixa")
                    ed_lead = st.number_input("Lead Time (Dias)", min_value=0, value=int(item_sel.get('lead_time_dias') or 0), key="ed_lead")

                with c3:
                    ed_min = st.number_input("Estoque Mínimo (30 dias)", min_value=0.0, value=float(item_sel.get('estoque_minimo') or 0), key="ed_min")
                    ed_max = st.number_input("Estoque Máximo (60 dias)", min_value=0.0, value=float(item_sel.get('estoque_maximo') or 0), key="ed_max",
                                             help="0 = usa o cálculo automático (Mínimo × 2).")
                    _seg_calc = float(item_sel.get('estoque_seguranca_calculado') or 0)
                    ed_seg = st.number_input("Estoque de Segurança", min_value=0.0, value=float(item_sel.get('estoque_seguranca') or 0), key="ed_seg",
                                             help=f"Parâmetro manual do gestor (entre Mínimo e Máximo). "
                                                  f"Sugestão calculada (consumo×lead time×1,5, arredondada p/ cima): {_seg_calc:.0f}.")
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
                        "caixa_identificacao": ed_caixa,
                        "lead_time_dias": ed_lead,
                        "estoque_minimo": ed_min,
                        "estoque_maximo": ed_max,
                        "estoque_seguranca": ed_seg,
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
elif pagina == "Movimentações":
    st.title(":material/sync: Controle de Estoque")

    # --- TABS: AJUSTE, HISTÓRICO E DASHBOARD ---
    tab_dash, tab_ajuste, tab_hist = st.tabs([":material/bar_chart: Analytics", ":material/balance: Ajuste Rápido", ":material/history: Histórico Completo"])

    centros = listar_valores("centro_custo") or ["Geral"]

    # === TAB 1: AJUSTE RÁPIDO DE ESTOQUE ===
    with tab_ajuste:
        with st.container(border=True):
            st.subheader(":material/balance: Ajuste Manual de Saldo")
            st.caption("Utilize apenas para correções de inventário, perdas ou sobras não justificadas por SC/Req.")
            
            _, item_aj, _ = sel_material("Selecione o Item para Ajuste", "sel_ajuste_estoque")
            
            if item_aj:
                st.info(f"**Item:** `{item_aj['part_number']} — {item_aj['nome_item']}` | **Saldo Atual:** `{item_aj['estoque_atual']}`")
                
                c1, c2, c3 = st.columns(3)
                tipo_aj = c1.radio("Tipo de Ajuste", ["Entrada (Sobra)", "Saída (Perda/Ajuste)"], horizontal=True)
                qtd_aj = c2.number_input("Quantidade", min_value=0.01, step=1.0)
                cc_aj = c3.selectbox("Centro de Custo (Responsável)", centros, index=0)
                
                obs_aj = st.text_input("Motivo do Ajuste *", placeholder="Ex: Avaria, erro de contagem anterior...")
                resp_aj = st.text_input("Responsável pelo Ajuste *")

                if st.button(":material/check_circle: Confirmar Ajuste", type="primary", width="stretch"):
                    if not resp_aj or not obs_aj:
                        st.error("Preencha o responsável e o motivo para auditoria.")
                    else:
                        tp = "entrada" if "Entrada" in tipo_aj else "saida"
                        
                        # Validação de saldo para saída
                        if tp == "saida" and qtd_aj > item_aj['estoque_atual']:
                            st.error(f"Quantidade ({qtd_aj}) superior ao estoque disponível ({item_aj['estoque_atual']}).")
                        else:
                            ok, msg = registrar_movimentacao(
                                item_id=item_aj["id"], tipo=tp, quantidade=qtd_aj,
                                centro_custo=cc_aj, solicitante=resp_aj, emitente=resp_aj,
                                observacao=f"AJUSTE: {obs_aj}", data_hora=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            )
                            if ok:
                                st.success(f":material/check_circle: Ajuste registrado! Novo saldo: {msg}")
                                time.sleep(1.2)
                                st.rerun()
                            else:
                                st.error(f":material/cancel: Erro: {msg}")

    # === TAB 2: HISTÓRICO COMPLETO ===
    with tab_hist:
        with st.container(border=True):
            st.subheader(":material/history: Histórico de Movimentações")
            
            c1, c2, c3 = st.columns([3, 2, 1])
            f_item = c1.selectbox("Filtrar por Item", ["Todos"] + [f"{i['part_number']} - {i['nome_item']}" for i in listar_inventario()])
            f_tipo = c2.multiselect("Filtrar por Tipo", ["entrada", "saida", "devolucao"], default=["entrada", "saida", "devolucao"])
            limit = c3.number_input("Limite", min_value=50, max_value=1000, value=200, step=50)

            item_id_f = None
            if f_item != "Todos":
                pn_busca = f_item.split(" - ")[0]
                for i in listar_inventario():
                    if i['part_number'] == pn_busca:
                        item_id_f = i['id']
                        break

            movs = listar_movimentacoes(item_id=item_id_f, limit=int(limit))
            
            # Filtro de tipo em memória
            if f_tipo:
                movs = [m for m in movs if m['tipo'] in f_tipo]

            if movs:
                df_mov = pd.DataFrame(movs)
                df_mov['data_hora'] = df_mov['data_hora'].apply(fmt)
                
                cols_exib = ["data_hora", "part_number", "nome_item", "tipo", "quantidade", "saldo_apos", "emitente", "observacao"]
                df_exib = df_mov[cols_exib].copy()
                df_exib.columns = ["Data/Hora", "PN", "Nome", "Tipo", "Qtd", "Saldo Pós", "Responsável", "Obs"]

                # Estilização por tipo
                def colorir_tipo(val):
                    if val == 'entrada': return 'color: #2ecc71; font-weight: bold;'
                    if val == 'saida': return 'color: #e74c3c; font-weight: bold;'
                    if val == 'devolucao': return 'color: #3498db; font-weight: bold;'
                    return ''

                # Opcional: Adicionar uma coluna calculada para identificar "Conferência"
                df_exib['Tipo Display'] = df_exib.apply(lambda x: 'Conferência' if x['Qtd'] == 0 else x['Tipo'], axis=1)

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
                df_exp_mov = exportar_movimentacoes_df(item_id=item_id_f, tipos_selecionados=f_tipo)
                    
                if not df_exp_mov.empty:
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as w:
                        df_exp_mov.to_excel(w, index=False, sheet_name="Movimentacoes")
                        
                    st.download_button(
                        label="⬇️ Baixar Excel",
                        data=buf.getvalue(),
                        file_name=f"movimentacoes_{date.today().strftime('%d-%m-%Y')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_exp_mov"
                    )


    # === TAB 3: ANALYTICS COMPLETO (VOLUME + DIVERGÊNCIAS + RUPTURA) ===
    with tab_dash:
        st.subheader(":material/bar_chart: Analytics Operacional Completo")

        # v2.2.1 — Rótulo de maturidade do histórico (transparência)
        _mat = obter_maturidade_dados()
        if _mat["dias"] > 0:
            st.caption(
                f":material/calendar_month: Indicadores de série (consumo, tendência, giro) baseados em "
                f"**{_mat['dias']} dias** de histórico — desde "
                f"{fmt(_mat['data_inicio']) if _mat['data_inicio'] else '—'} · "
                f"{_mat['n_snapshots']} fotos de estoque. A confiança aumenta conforme "
                f"os dados acumulam."
            )

        # v2.2.1 — Inteligência de Estoque: Cobertura · Tendência · Giro
        with st.container(border=True):
            st.markdown("#### :material/psychology: Inteligência de Estoque (Cobertura · Tendência · Giro)")
            try:
                df_series = exportar_inventario_df()
            except Exception as e:
                df_series = pd.DataFrame()
                st.error(f"Erro ao calcular indicadores: {e}")
            if df_series.empty:
                st.caption("Sem dados suficientes.")
            else:
                ca, cb, cc = st.columns(3)
                with ca:
                    st.markdown("**:material/trending_up: Tendência de consumo**")
                    if "Tendência" in df_series.columns:
                        vc = df_series["Tendência"].value_counts()
                        st.metric("🔺 Em alta", int(vc.get("Alta", 0)),
                                  help="Consumo dos últimos 30d mais de 15% acima dos 30d anteriores.")
                        st.metric("🔻 Em queda", int(vc.get("Queda", 0)))
                        st.metric(":material/remove: Estável", int(vc.get("Estável", 0)))
                with cb:
                    st.markdown("**:material/shield: Menor cobertura (dias)**")
                    st.caption("Estoque atual ÷ consumo diário")
                    if "Cobertura(d)" in df_series.columns:
                        _cols_lc = [c for c in ["PN", "Nome", "Cobertura(d)"] if c in df_series.columns]
                        low = (df_series[df_series["Cobertura(d)"] < 900]
                               .nsmallest(8, "Cobertura(d)")[_cols_lc])
                        st.dataframe(low, hide_index=True, width="stretch", height=250)
                with cc:
                    st.markdown("**:material/sync: Itens parados (giro 0 c/ estoque)**")
                    st.caption("Capital imobilizado sem saída no período.")
                    if "Giro(anual)" in df_series.columns:
                        parados = df_series[(df_series["Giro(anual)"] == 0) &
                                            (df_series["Estoque Atual"] > 0)]
                        st.caption(f"Total: {len(parados)} itens")
                        _cols_par = [c for c in ["PN", "Nome", "Estoque Atual"] if c in df_series.columns]
                        st.dataframe(parados[_cols_par].head(8),
                                     hide_index=True, width="stretch", height=210)

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
                _cols_cap = [c for c in ["PN", "Nome", "Estoque Atual", "Valor em Estoque"]
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
# REQUISIÇÃO
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Requisição":
    st.title(":material/assignment: Requisição de Material")
    
    aba_nova, aba_hist_req = st.tabs([":material/edit_note: Nova Requisição", ":material/history: Histórico"])
    
    # Configurações de contexto
    autorizadores_lista = listar_valores("autorizador") or ["Gestor", "Líder", "Reserva"]
    centros = listar_valores("centro_custo")

    with aba_nova:
        if "itens_req" not in st.session_state: st.session_state.itens_req = []
        if "req_confirmada" not in st.session_state: st.session_state.req_confirmada = None

        # --- FEEDBACK DE SUCESSO ---
        if st.session_state.req_confirmada:
            st.success(f"### :material/check_circle: Requisição {st.session_state.req_confirmada} enviada!")
            st.info("O estoque foi atualizado e o registro foi salvo no histórico.")
            if st.button("Iniciar Nova Requisição", width="stretch"):
                st.session_state.req_confirmada = None
                st.rerun()
            st.stop()

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
                ci1, ci2 = st.columns(2)
                qtd_sol = ci1.number_input("Qtd Solicitada *", min_value=1.0, step=1.0, value=1.0)
                qtd_ate = ci2.number_input("Qtd Atendida *", min_value=0.0, step=1.0, value=1.0)
                add_item = st.form_submit_button(":material/add: ADICIONAR À LISTA", width="stretch")

            if add_item:
                if not item_req_add:
                    st.warning(":material/warning: Selecione um material antes de adicionar.")
                elif qtd_ate > item_req_add.get("estoque_atual", 0):
                    st.error(f":material/cancel: Saldo insuficiente! Estoque: {item_req_add.get('estoque_atual', 0)}")
                else:
                    st.session_state.itens_req.append({
                        "item_id": item_req_add["id"], "part_number": item_req_add["part_number"],
                        "nome_item": item_req_add["nome_item"], "unidade": item_req_add.get("unidade","UN"),
                        "estoque_disponivel": item_req_add.get("estoque_atual",0),
                        "quantidade_solicitada": qtd_sol, "quantidade_atendida": qtd_ate,
                    })
                    st.rerun()

        # --- LISTA DE ITENS TEMPORÁRIA ---
        if st.session_state.itens_req:
            st.markdown("###### :material/inventory_2: Itens na Requisição Atual:")
            for idx, it in enumerate(st.session_state.itens_req):
                with st.expander(f"{it['part_number']} — {it['nome_item']}", expanded=True):
                    c_info, c_del = st.columns([5, 1])
                    c_info.write(f"**Atendido:** {it['quantidade_atendida']} / **Solicitado:** {it['quantidade_solicitada']} {it['unidade']}")
                    
                    if c_del.button("Remover", key=f"rm_req_{idx}", type="primary"):
                        st.session_state.itens_req.pop(idx)
                        st.rerun()
        else:
            st.info("Aguardando adição de materiais...")

        st.markdown("---")

        # --- BLOCO 3: REGRAS ESPECIAIS ---
        with st.container():
            st.markdown("##### 3. Regras de Entrega e SESMT")
            col_ei, col_sesmt = st.columns(2)
            with col_ei:
                entrega_ind = st.checkbox(":material/inventory_2: Entrega Individual (EPI/Uniforme)")
                if entrega_ind:
                    destinatarios_txt = st.text_area("Lista de Destinatários *", 
                        placeholder="MATRÍCULA — NOME (um por linha)", height=100)
            with col_sesmt:
                is_sesmt = st.checkbox(":material/engineering: Requer Aprovação SESMT")
                if is_sesmt:
                    sesmt_resp = st.text_input("Responsável SESMT *")

        # --- BLOCO 4: AUTORIZAÇÃO E FINALIZAÇÃO ---
        with st.container():
            st.markdown("##### 4. Autorização Final")
            ca1, ca2 = st.columns(2)
            aut_tipo = ca1.selectbox("Tipo de Autorizador *", autorizadores_lista)
            aut_nome = ca2.text_input("Assinatura / Nome do Autorizador *")
            obs_req  = st.text_area("Observações Gerais da Requisição", height=70)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(":material/check_circle: FINALIZAR E ATUALIZAR ESTOQUE", type="primary", width="stretch"):
            erros = []
            if not req_setor or not req_emit or not aut_nome: erros.append("Campos obrigatórios com (*) não preenchidos.")
            if not st.session_state.itens_req: erros.append("A lista de materiais está vazia.")
            if entrega_ind and not destinatarios_txt: erros.append("Para entrega individual, informe os destinatários.")
            
            if erros:
                for e in erros: st.error(e)
            else:
                with st.spinner("Processando requisição e baixando estoque..."):
                    destinatarios = []
                    if entrega_ind and destinatarios_txt:
                        for linha in destinatarios_txt.strip().split("\n"):
                            if "—" in linha or "-" in linha:
                                sep = "—" if "—" in linha else "-"
                                p = linha.split(sep, 1)
                                destinatarios.append({"matricula": p[0].strip(), "nome": p[1].strip() if len(p)>1 else ""})
                    
                    ok, resultado = criar_requisicao(
                        setor=req_setor, emitente=req_emit, centro_custo=req_cc,
                        autorizador_tipo=aut_tipo, autorizador_nome=aut_nome,
                        entrega_individual=entrega_ind, destinatarios=destinatarios,
                        sesmt=is_sesmt, sesmt_responsavel=sesmt_resp if is_sesmt else "",
                        itens=st.session_state.itens_req, observacoes=obs_req
                    )
                    
                    if ok:
                        st.session_state.itens_req = []
                        st.session_state.req_confirmada = resultado
                        st.rerun()
                    else:
                        st.error(f"Erro no processamento: {resultado}")

    # --- ABA: HISTÓRICO ---
    with aba_hist_req:
        st.markdown("### :material/history: Histórico de Requisições")
        reqs = listar_requisicoes(limit=200)
        if not reqs:
            st.info("Nenhuma requisição registrada até o momento.")
        else:
            df_reqs = pd.DataFrame(reqs)[["numero_requisicao", "data_hora", "setor", "emitente", "autorizador_nome", "total_itens"]]
            df_reqs.columns = ["Nº Req", "Data/Hora", "Setor", "Emitente", "Autorizador", "Qtd Itens"]
            st.dataframe(df_reqs, width="stretch", hide_index=True)
            
            st.markdown("---")
            st.markdown("#### :material/search: Detalhes da Requisição")
            opcoes_req = {f"REQ-{r['numero_requisicao']} | {r['setor']} | {r['data_hora'][:10]}": r for r in reqs}
            sel_req = st.selectbox("Escolha uma requisição para ver os detalhes:", [""] + list(opcoes_req.keys()))
            
            if sel_req:
                r_det = opcoes_req[sel_req]
                with st.container():
                    st.markdown(f"**Resumo REQ-{r_det['numero_requisicao']}**")
                    c_a, c_b, c_c = st.columns(3)
                    c_a.write(f":material/person: **Emitente:** {r_det['emitente']}")
                    c_b.write(f":material/edit: **Autorizador:** {r_det['autorizador_nome']}")
                    c_c.write(f":material/apartment: **C.Custo:** {r_det['centro_custo']}")
                    
                    itens_det = listar_itens_requisicao(r_det["id"])
                    if itens_det:
                        df_det = pd.DataFrame(itens_det)[["part_number", "nome_item", "quantidade_solicitada", "quantidade_atendida", "unidade"]]
                        df_det.columns = ["PN", "Material", "Solicitado", "Atendido", "UN"]
                        st.table(df_det)
                        
# ══════════════════════════════════════════════════════════════════════════════
# CONTROLE DE SC
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Controle de SC":
    st.title(":material/receipt_long: Controle de SC")
    
    # Estrutura de abas mantida conforme solicitado
    aba_mon, aba_assist, aba_forn, aba_nova_sc, aba_rec, aba_ed, aba_h, aba_import = st.tabs([
    ":material/sensors: Monitor", ":material/psychology: Assistente de Reposição", ":material/apartment: Fornecedores & Cotação", ":material/add: Nova SC",
    ":material/inventory_2: Receber Material", ":material/sync: Atualizar Status", ":material/history: Histórico", ":material/download: Importar Relatório de SCs"
    ])
    # ══════════════════════════════════════════════════════════════════════════════
    # 📡 MONITOR DE COMPRAS 
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_mon:
        st.markdown("### :material/sensors: Monitor de Compras")
        st.caption("Acompanhe todas as SCs abertas. Colunas críticas destacadas para leitura rápida.")
        
        # UX: Filtros rápidos
        c_filt1, c_filt2 = st.columns([3, 2])
        with c_filt1:
            f_busca = st.text_input(":material/search: Buscar PN, Nº SC ou Fornecedor", placeholder="Ex: SC-2026, 123456, SKF...", key="busca_monitor_sc")
        with c_filt2:
            f_crise = st.checkbox(f":material/emergency: Focar apenas em Ruptura < {RUPTURA_CRISE_DIAS} dias", value=False, key="filtro_ruptura_sc")

        scs = listar_scs(apenas_abertas=True)
        if not scs:
            st.success(":material/check_circle: Nenhuma SC aberta! Operação fluida.")
        else:
            dados = []
            for sc in scs:
                importancias = (sc.get('importancias_itens') or "").split(',')
                
                for item in listar_itens_sc(sc['id']):
                    pend = item.get('saldo_residual') or item.get('pendente', 0)
                    if pend <= 0: continue  # UX: Foca apenas no que exige ação
                    
                    inv = buscar_item_por_id(item['item_id'])
                    qty_min = inv.get('estoque_minimo', 0 ) if inv else 0
                    
                    # ✅ CORREÇÃO: Usar a previsão de ruptura REAL do inventário
                    # Em vez de calcular (Estoque + Pendente) / Consumo, usamos o campo já existente
                    dias_ruptura_real = inv.get('previsao_ruptura_dias', PREVISAO_RUPTURA_SEM_RISCO) if inv else PREVISAO_RUPTURA_SEM_RISCO
                    if dias_ruptura_real is None:
                        dias_ruptura_real = PREVISAO_RUPTURA_SEM_RISCO
                    
                    # Formatação para exibição na tabela
                    if dias_ruptura_real >= PREVISAO_RUPTURA_SEM_RISCO:
                        rupt_display = "∞"
                    else:
                        rupt_display = f"{dias_ruptura_real:.1f}"

                    # ✅ CORREÇÃO: Definir 'forn' e 'po' ANTES de usar no dicionário
                    forn = item.get('fornecedor_item') or sc.get('fornecedor') or "—"
                    po = item.get('numero_po') or sc.get('numero_po') or "—"

                    # Lógica semafórica de trâmite baseada no Status Real do Banco
                    status_db = sc.get('status', 'Aguardando Aprovação')
                    
                    if status_db == "Aguardando Aprovação":
                        status_display, cor = "Aguardando Aprovação", "🔴"
                    elif status_db == "Em Cotação":
                        status_display, cor = "Em Cotação", "🟡"
                    elif status_db == "Pedido Emitido":
                        status_display, cor = "Pedido Emitido", "🔵"
                    elif status_db == "Aguardando Entrega":
                        status_display, cor = "Aguardando Entrega", "🔵"
                    elif status_db == "Parcial":
                        status_display, cor = "Recebimento Parcial", "🟠"
                    elif status_db == "Recebido":
                        status_display, cor = "Recebido", "🟢"
                    else:
                        # Fallback visual antigo se status for genérico
                        if forn != "—": status_display, cor = "Aguardando Entrega", "🔵"
                        elif po != "—": status_display, cor = "Verificar Fornecedor", "🟡"
                        else: status_display, cor = "Abrir Cotação", "🔴"

                    # Cálculo de Aging (Dias desde abertura)
                    dias = item.get('dias_atendimento', 0) 
                    dias_v = f"🔴 {dias}d" if dias > AGING_CRITICO_DIAS else (f"🟡 {dias}d" if dias > AGING_ALERTA_DIAS else f"🟢 {dias}d")
                    
                    # 📊 CHAVES DE ORDENAÇÃO
                    # Agora ordenamos pela ruptura REAL do inventário
                    sort_ruptura = dias_ruptura_real if dias_ruptura_real < PREVISAO_RUPTURA_SEM_RISCO else ORDENACAO_RUPTURA_INFINITO
                    crit_rank = 1 if 'Parada de Linha' in importancias else (2 if 'Importante' in importancias else 3)
                    
                    dados.append({
                        "SC": sc['numero_sc'],
                        "Importância.": "🔴 Crítico" if 'Parada de Linha' in importancias else ("🟡 Importante" if 'Importante' in importancias else "🔵 Administrativo"),
                        "PN": f"{item['part_number']}",
                        "Item": item['nome_item'],
                        "Solicitado": f"{pend} {item['unidade']}",
                        "Estoque": f"{inv.get('estoque_atual', '—')} {item['unidade']}" if inv else "—",
                        "Qty Mín": f"{qty_min} {item['unidade']}",
                        "Ruptura (d)": rupt_display,
                        "Trâmite": f"{cor} {status_display}",
                        "Aging": dias_v,
                        "Fornecedor": forn,
                        "PO": po,
                        "Prev. NF": item.get('data_prev_nfe') or sc.get('data_prev_entrega') or "—",
                        "Justificativa": item.get('observacao_item') or "—",
                        "_sort_ruptura": sort_ruptura,
                        "_sort_crit": crit_rank,
                        "_sort_aging": dias
                    })

            df = pd.DataFrame(dados)
            if df.empty:
                st.info("Nenhum item pendente encontrado nas SCs abertas.")
            else:
                # UX: Filtro client-side
                if f_crise:
                    df = df[df["_sort_ruptura"] < RUPTURA_CRISE_DIAS]
                if f_busca:
                    b = f_busca.lower()
                    df = df[
                        df["SC"].str.lower().str.contains(b) | 
                        df["PN"].str.lower().str.contains(b) | 
                        df["Fornecedor"].str.lower().str.contains(b) |
                        df["Item"].str.lower().str.contains(b)
                    ]

                # 🚀 ORDENAÇÃO AUTOMÁTICA POR URGÊNCIA REAL (Invisível mas funcional)
                # Garante que a linha #1 seja sempre o mais crítico do sistema AGORA
                df = df.sort_values(['_sort_ruptura', '_sort_crit', '_sort_aging'], ascending=True)

                col_cfg = {
                    # ✅ REMOVIDO da config: "🎯 Prioridade": ...
                    "SC": st.column_config.TextColumn("SC", width="small"),
                    "Importância.": st.column_config.TextColumn("Importância.", width="small"),
                    "PN": st.column_config.TextColumn("Part Number", width="small"),
                    "Item": st.column_config.TextColumn("Descrição", width="large"),
                    "Solicitado": st.column_config.TextColumn("Solicitado", width="small"),
                    "Estoque": st.column_config.TextColumn("Estoque Atual", width="small"),
                    "Qty Mín": st.column_config.TextColumn("Mínimo", width="small"),
                    "Ruptura (d)": st.column_config.TextColumn("Ruptura", width="small"),
                    "Trâmite": st.column_config.TextColumn("Trâmite", width="medium"),
                    "Aging": st.column_config.TextColumn("Aging", width="small"),
                    "Fornecedor": st.column_config.TextColumn("Fornecedor", width="medium"),
                    "PO": st.column_config.TextColumn("PO", width="small"),
                    "Prev. NF": st.column_config.TextColumn("Prev. NF", width="small"),
                    "Justificativa": st.column_config.TextColumn("Justificativa", width="large"),
                    "_sort_ruptura": None, "_sort_crit": None, "_sort_aging": None  # Sempre ocultas
                }

                st.dataframe(
                    df.drop(columns=["_sort_ruptura", "_sort_crit", "_sort_aging"]),
                    width="stretch",
                    hide_index=True,
                    column_config=col_cfg,
                    height=600,
                    row_height=34
                )
                
                st.caption(":material/bar_chart: Ordenado automaticamente por: 1º Dias até Ruptura | 2º Impacto na Produção | 3º Tempo de Espera")
                                    
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

        _mat = obter_maturidade_dados()
        st.caption(
            f":material/calendar_month: Indicadores de série baseados em ~{_mat['dias']} dias de histórico"
            + (f" (desde {fmt(_mat['data_inicio'])})" if _mat.get('data_inicio') else "")
            + " — amadurecem conforme os dados acumulam."
        )

        incluir_sem_mov = st.checkbox(
            "⚪ Mostrar itens sem movimentação (revisão)", value=False, key="rep_incl_semmov",
            help="Por padrão, itens que nunca tiveram consumo real ficam fora da fila. "
                 "Marque para revisá-los — inclui os spares 'Parada de Linha' que o "
                 "Compras estoca sem giro.")

        with st.spinner("Calculando sugestões de reposição…"):
            sugestoes = gerar_sugestoes_reposicao(incluir_sem_movimentacao=incluir_sem_mov)

        if not sugestoes:
            st.success(":material/check_circle: Nenhuma reposição necessária agora. Estoque + saldo "
                       "residual cobrem o horizonte planejado para todos os itens.")
        else:
            # --- Filtros ---
            cflt1, cflt2, cflt3 = st.columns(3)
            with cflt1:
                so_criticos = st.checkbox("🔴 Só críticos", value=False, key="rep_so_crit",
                                          help="Itens no/abaixo do ponto de pedido (ROP).")
            with cflt2:
                setores = sorted({s["setor"] for s in sugestoes if s["setor"]})
                f_setor = st.selectbox("Setor", ["Todos"] + setores, key="rep_setor")
            with cflt3:
                forns = sorted({s["fornecedor_sugerido"] or "Sem fornecedor sugerido"
                                for s in sugestoes})
                f_forn = st.selectbox("Fornecedor sugerido (agrupar)", ["Todos"] + forns,
                                      key="rep_forn")

            filtradas = sugestoes
            if so_criticos:
                filtradas = [s for s in filtradas if s["prioridade_tier"] == 0]
            if f_setor != "Todos":
                filtradas = [s for s in filtradas if s["setor"] == f_setor]
            if f_forn != "Todos":
                filtradas = [s for s in filtradas
                             if (s["fornecedor_sugerido"] or "Sem fornecedor sugerido") == f_forn]

            def _cate(s):
                """'Comprar até' formatado (:material/alarm: = já atrasado; '—' = sem consumo)."""
                ca = s.get("comprar_ate")
                if not ca:
                    return "—"
                dd = datetime.strptime(ca, "%Y-%m-%d").strftime("%d/%m/%Y")
                return f":material/alarm: {dd}" if s.get("comprar_atrasado") else dd

            k1, k2, k3 = st.columns(3)
            k1.metric("Itens a repor", len(filtradas))
            k2.metric("🔴 Críticos", sum(1 for s in filtradas if s["prioridade_tier"] == 0))
            k3.metric(":material/block: Parada de Linha", sum(1 for s in filtradas if s["parada_linha"]))

            # --- 🔴 Críticos automáticos (versão auto da lista CRÍTICOS manual) ---
            criticos = [s for s in filtradas if s["prioridade_tier"] == 0]
            if criticos:
                with st.expander(f"🔴 Críticos automáticos ({len(criticos)}) — comprar primeiro",
                                 expanded=True):
                    st.caption("Itens no/abaixo do ponto de pedido (ROP): vão romper por consumo. "
                               "Ordenados pela data-limite de compra.")
                    crit_ord = sorted(criticos, key=lambda s: s.get("comprar_ate") or "9999-99-99")
                    st.dataframe(
                        pd.DataFrame([{
                            "PN": s["part_number"],
                            "Item": s["nome_item"],
                            "Cobertura(d)": (s["cobertura_dias"]
                                             if s["cobertura_dias"] < PREVISAO_RUPTURA_SEM_RISCO else None),
                            "Comprar até": _cate(s),
                            "Qtd": s["qtd_sugerida"],
                            "Un": s["unidade"],
                            "Fornecedor": s["fornecedor_sugerido"] or "—",
                        } for s in crit_ord]),
                        hide_index=True, width="stretch",
                    )

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
                    "Segurança": s.get("estoque_seguranca"),
                    "Cobertura(d)": (s["cobertura_dias"]
                                     if s["cobertura_dias"] < PREVISAO_RUPTURA_SEM_RISCO else None),
                    "Consumo/dia": round(float(s.get("consumo_diario") or 0), 2),
                    "Un": s["unidade"],
                    "Comprar até": _cate(s),
                    "Setor": s.get("setor") or "—",
                    "Qtd Sugerida": s["qtd_sugerida"],
                    "Fornecedor": s["fornecedor_sugerido"] or "—",
                }
                return {"Incluir": incluir, **d} if incluir is not None else d

            _num_cols = {
                "Estoque": "%.0f", "Mín": "%.0f", "Máx": "%.0f", "Segurança": "%.0f",
                "Cobertura(d)": "%.1f", "Consumo/dia": "%.2f", "Qtd Sugerida": "%d",
            }
            df_sel = pd.DataFrame([_linha_rep(s, incluir=True) for s in filtradas])
            edit_sel = st.data_editor(
                df_sel, hide_index=True, width="stretch", key="rep_sel_editor",
                column_config={
                    "Incluir": st.column_config.CheckboxColumn(
                        "Incluir", help="Marque os itens que entram nas SCs sugeridas abaixo."),
                    "Segurança": st.column_config.NumberColumn(
                        format="%.0f", disabled=True,
                        help="Estoque de segurança efetivo: manual do gestor > calculado > "
                             "piso pelo mínimo (itens sem consumo)."),
                    **{c: st.column_config.NumberColumn(format=f, disabled=True)
                       for c, f in _num_cols.items() if c != "Segurança"},
                    **{c: st.column_config.TextColumn(disabled=True)
                       for c in ("PN", "Item", "Un", "Comprar até", "Setor", "Fornecedor")},
                },
            )
            _incluir = list(edit_sel["Incluir"]) if "Incluir" in edit_sel else [True] * len(filtradas)
            selecionadas = [s for s, inc in zip(filtradas, _incluir) if inc]
            st.caption(f"**{len(selecionadas)}** de {len(filtradas)} itens selecionados · "
                       "Segurança = efetivo (piso pelo mínimo do gestor quando não há consumo).")

            buf_rep = io.BytesIO()
            with pd.ExcelWriter(buf_rep, engine="openpyxl") as w:
                pd.DataFrame([_linha_rep(s) for s in filtradas]).to_excel(
                    w, index=False, sheet_name="Sugestões")
            st.download_button(
                "⬇️ Exportar sugestões (Excel)", data=buf_rep.getvalue(),
                file_name=f"reposicao_mro_{date.today():%d-%m-%Y}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="rep_export")

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

            st.divider()

            with st.expander(":material/history: Histórico de decisões de reposição"):
                hist = listar_sugestoes(limit=50)
                if not hist:
                    st.caption("Nenhuma decisão registrada ainda.")
                else:
                    st.dataframe(
                        pd.DataFrame([{
                            "Quando": fmt(h["data_geracao"]),
                            "PN": h["part_number"],
                            "Item": h["nome_item"],
                            "Qtd": h["qtd_sugerida"],
                            "Desfecho": h["desfecho"],
                            "Fornecedor": h["fornecedor_sugerido"] or "—",
                        } for h in hist]),
                        hide_index=True, width="stretch",
                    )

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
    #  📦 RECEBER MATERIAL (Grid Inteligente + Feedback Visual Aprimorado)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_rec:
        _modo_rec = st.radio(
            "Como quer receber?", ["📦 Por Material", "📋 Por SC / PO"],
            horizontal=True, key="rec_modo",
            help="Por Material começa pelo item; Por SC / PO escolhe a SC e recebe todos os itens pendentes de uma vez.")
        if _modo_rec == "📋 Por SC / PO":
            _receber_por_sc(listar_valores("centro_custo"))
        else:
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

                # UX: Card de contexto do item selecionado
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

    # ══════════════════════════════════════════════════════════════════════════════
    # 🔄 ATUALIZAR STATUS E DADOS DA S.C. (Corrigido: Variáveis definidas antes do uso)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_ed:
        with st.container(border=True):
            st.markdown("### :material/sync: Atualizar Status e Dados da S.C.")
            st.caption("Preencha as informações conforme elas chegarem (PO, Fornecedor, Previsões). O status será sugerido automaticamente.")
            
            scs_todas = listar_scs()
            opc_ed = {f"SC {s['numero_sc']} — {s['status']}": s for s in scs_todas} if scs_todas else {}
            _ph_sc = "— selecione uma SC —"
            sel_ed = st.selectbox("Selecionar SC", [_ph_sc] + list(opc_ed.keys()),
                                  index=0, label_visibility="collapsed") if scs_todas else None
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
            st.caption("Registro cronológico de entradas vinculadas a S.C.")
            
            recebimentos = listar_recebimentos_sc(limit=300)
            if recebimentos:
                # UX: Layout de lista vertical para melhor leitura de logs
                for r in recebimentos:
                    with st.container(border=True):
                        # Linha Principal: PN + Item + Quantidade (Destaque Mono)
                        st.markdown(f"`{r['part_number']}` — **{r['nome_item']}** | `+{r['quantidade']} UN`")
                        
                        # Linha Secundária: Detalhes em caption para não poluir visual
                        c_meta1, c_meta2, c_meta3 = st.columns([2, 2, 3])
                        c_meta1.caption(f":material/calendar_month: **{fmt(r['data_hora'])}**")
                        c_meta2.caption(f":material/receipt_long: **SC:** {r['numero_sc']} | **NF:** {r['documento_nf'] or '—'}")
                        c_meta3.caption(f":material/person: **Recebido por:** {r['emitente']} | {r['observacao']}")
            else:
                st.info("ℹ️ Nenhum recebimento vinculado a SC encontrado no histórico.")

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
                        "<div style='border:1px dashed #444;border-radius:8px;"
                        "padding:32px;text-align:center;color:#888;'>Sem imagem</div>",
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
                st.markdown(
                    f"**Categoria/Tipo:** {it.get('tipo_material') or '—'}  \n"
                    f"**Unidade:** {it.get('unidade') or '—'} · "
                    f"**Criticidade:** {it.get('importancia') or '—'}  \n"
                    f"**Setor responsável:** {it.get('setor_responsavel') or '—'}  \n"
                    f"**Local:** {it.get('local_armazenagem') or '—'}"
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
            if it.get("unidade_divergente"):
                st.warning(":material/warning: **Revisar unidade:** comprado em unidade diferente da de estoque "
                           "(visto nos POs) e ainda **sem fator de conversão**. Cadastre em "
                           "**Gerenciar Itens → Conversão de unidades** para o recebimento converter certo.")
            elif abs(_fat_f - 1.0) > 1e-9 and _uc_f:
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
            e1, e2, e3, e4, e5 = st.columns(5)
            e1.metric("Estoque atual", _g(it.get("estoque_atual")))
            e2.metric("Mínimo", _g(it.get("estoque_minimo")))
            e3.metric("Máximo", _g(it.get("estoque_maximo")))
            e4.metric("Segurança", _g(it.get("estoque_seguranca")),
                      help=f"Origem: {rep['estoque_seguranca_origem']}.")
            e5.metric("Saldo Residual", _g(it.get("estoque_em_transito")),
                      help="Qtd já negociada que ainda falta chegar (SCs abertas).")

            ver_saldo_key = f"ver_saldo_{item_f['id']}"
            if st.button(":material/visibility: Ver detalhes do Saldo Residual",
                         key=f"btn_{ver_saldo_key}"):
                st.session_state[ver_saldo_key] = not st.session_state.get(ver_saldo_key, False)
            if st.session_state.get(ver_saldo_key):
                pedidos_com_saldo = [s for s in ficha["scs_pos"] if (s.get("pendente") or 0) > 0]
                cont1, cont2 = st.columns(2)
                with cont1:
                    st.markdown("**:material/receipt_long: Pedidos com Saldo**")
                    if not pedidos_com_saldo:
                        st.caption("Nenhum pedido com saldo em aberto para este item.")
                    else:
                        st.dataframe(pd.DataFrame([{
                            "SC": s["numero_sc"], "PO": s.get("po_item") or s.get("numero_po") or "—",
                            "Status": s.get("status"),
                            "Solic.": s.get("quantidade_solicitada"),
                            "Receb.": s.get("quantidade_recebida"),
                            "Pendente": s.get("pendente"),
                        } for s in pedidos_com_saldo]), hide_index=True, width="stretch")
                with cont2:
                    st.markdown("**:material/apartment: Saldo Residual por Fornecedor**")
                    grupos_saldo = agrupar_saldo_residual_por_fornecedor(ficha["scs_pos"])
                    if not grupos_saldo:
                        st.caption("Sem saldo residual por fornecedor para este item.")
                    else:
                        st.dataframe(pd.DataFrame([{
                            "Fornecedor": g["fornecedor"],
                            "Saldo Pendente": g["saldo_pendente"],
                            "Nº Pedidos": g["n_pedidos"],
                            "Entrega Parcial": ("Sim" if any(l["entrega_parcial"] for l in g["linhas"])
                                                else "Não"),
                        } for g in grupos_saldo]), hide_index=True, width="stretch")
                st.caption(":material/info: Fundação: visão por este item. Consolidação entre "
                           "materiais/fornecedores e os campos Controle AP/Elimin. Resíduo "
                           "(fonte: Relatório de SCs, aba SC7) ficam para uma próxima etapa.")

            cob = it.get("dias_cobertura")
            giro = ficha["giro"]
            g1, g2, g3, g4 = st.columns(4)
            g1.metric("Cobertura",
                      f"{cob:.0f} d" if cob is not None and cob < PREVISAO_RUPTURA_SEM_RISCO else "—",
                      help="Estoque atual ÷ consumo diário.")
            tend = it.get("tendencia_label")
            tend_txt = (f"{tend} {'+' if (it.get('tendencia_pct') or 0) >= 0 else ''}"
                        f"{_g(it.get('tendencia_pct'))}%") if tend else None
            g2.metric("Consumo/dia", f"{_g1(it.get('consumo_medio_diario'))} {un}/dia", delta=tend_txt,
                      delta_color="inverse", help="Média diária de saídas (janela 30d).")
            g3.metric("Giro anual", _g(giro["giro_anual"]),
                      help=f"Tempo médio em estoque: "
                           f"{giro['tempo_medio_dias'] if giro['tempo_medio_dias'] else '—'} d · "
                           f"baseado em {giro['n_snapshots']} fotos.")
            lt_calc = it.get("lead_time_calculado")
            g4.metric("Lead time (Compras)", f"{int(it.get('lead_time_dias') or 0)} d",
                      help=(f"Calculado (sugestão): {int(lt_calc)} d "
                            f"({it.get('lead_time_calculado_amostras') or 0} amostras, "
                            f"{it.get('lead_time_calculado_origem') or '—'})" if lt_calc
                            else "Sem lead time calculado ainda."))

            # ── Consumo (30/60/90) + Valor ────────────────────────────────────
            cc1, cc2 = st.columns(2)
            with cc1:
                st.markdown("##### :material/trending_down: Consumo médio/dia por janela")
                _cons_j = [round(it.get("consumo_30d") or 0, 1),
                           round(it.get("consumo_60d") or 0, 1),
                           round(it.get("consumo_90d") or 0, 1)]
                st.plotly_chart(
                    _barv(["30 dias", "60 dias", "90 dias"], _cons_j,
                          textos=[f"{v:g}" for v in _cons_j]),
                    width="stretch", config={"displayModeBar": False})
            with cc2:
                st.markdown("##### :material/payments: Valor")
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
                        ":material/star:": ":material/star:" if f.get("melhor") else "",
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

# ══════════════════════════════════════════════════════════════════════════════
# FEEDBACK / SUGESTÕES (Item 3 / v2.1.0)
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Ajuda":
    st.title(":material/help: Central de Ajuda")
    st.caption("Guias por perfil, o **Manual do Sistema** (tela a tela) e o canal de feedback. "
               ":material/lightbulb: Tema claro/escuro: botão **Tema** na barra lateral.")

    tab_inicio, tab_manual, tab_enviar, tab_gerenciar = st.tabs(
        [":material/rocket_launch: Começar aqui", ":material/menu_book: Manual do Sistema", ":material/edit: Enviar Feedback", ":material/folder: Backlog"])

    with tab_inicio:
        st.caption("Guias rápidos por perfil. Para o detalhe de cada botão/card/gráfico, veja a "
                   "aba **:material/menu_book: Manual do Sistema**.")
        _perfil = st.radio("Qual é o seu perfil?",
                           ["Assistente de Materiais (almoxarifado)", "Comprador"],
                           horizontal=True, key="ajuda_perfil")
        _chave = "assistente" if _perfil.startswith("Assistente") else "comprador"
        st.markdown(GUIAS_PERSONA[_chave])

    with tab_manual:
        st.caption("Explica **cada elemento** da interface: para que serve · com base em quê · "
                   "como o sistema calcula. Ligue o modo abaixo para uma explicação bem simples.")
        _eli5 = st.toggle("Explicar em linguagem simples", value=False, key="ajuda_eli5",
                          help="Reescreve tudo em linguagem simples — ótimo para entender os "
                               "cálculos e os dashboards.")
        _busca_manual = st.text_input(":material/search: Filtrar por palavra (opcional)", key="ajuda_busca",
                                      placeholder="ex.: cobertura, ABC, conversão, saldo residual")
        _b = (_busca_manual or "").strip().lower()
        for _sec in MANUAL:
            _itens = _sec["itens"]
            if _b:
                _itens = [it for it in _itens
                          if _b in (it["nome"] + it["para_que"] + it["base"]
                                    + it["como"] + it["crianca"] + _sec["tela"]).lower()]
            if not _itens:
                continue
            st.subheader(_sec["tela"])
            if _sec.get("intro"):
                st.caption(_sec["intro"])
            for _it in _itens:
                with st.expander(_it["nome"]):
                    if _eli5:
                        st.markdown(f" {_it['crianca']}")
                    else:
                        st.markdown(f"**Para que serve:** {_it['para_que']}")
                        st.markdown(f"**Com base em quê:** {_it['base']}")
                        st.markdown(f"**Como o sistema faz:** {_it['como']}")

    with tab_enviar:
        with st.container(border=True):
            with st.form("form_feedback", clear_on_submit=True):
                c1, c2 = st.columns(2)
                fb_tipo = c1.selectbox("Tipo *", TIPOS_FEEDBACK, index=0)
                fb_autor = c2.text_input("Seu nome (opcional)", placeholder="Ex: Luis Oliveira")
                fb_titulo = st.text_input("Título *", placeholder="Resuma em uma frase")
                fb_desc = st.text_area("Descrição", height=120,
                                       placeholder="Descreva a sugestão, o problema ou a ideia em detalhes...")
                fb_pagina = st.selectbox("Página/área relacionada (opcional)",
                                         ["—", "Dashboard", "Inventário", "Gerenciar Itens",
                                          "Movimentações", "Requisição", "Controle de SC",
                                          "Configurações", "Geral"], index=0)
                enviado = st.form_submit_button(":material/mail: Enviar Feedback", type="primary", width="stretch")
                if enviado:
                    ok, msg = registrar_feedback(
                        fb_tipo, fb_titulo, fb_desc,
                        autor=(fb_autor or None),
                        pagina_origem=(None if fb_pagina == "—" else fb_pagina),
                    )
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    with tab_gerenciar:
        f1, f2 = st.columns(2)
        filtro_tipo = f1.selectbox("Filtrar por tipo", ["Todos"] + TIPOS_FEEDBACK, index=0, key="fb_f_tipo")
        filtro_status = f2.selectbox("Filtrar por status", ["Todos"] + STATUS_FEEDBACK, index=0, key="fb_f_status")
        feedbacks = listar_feedbacks(tipo=filtro_tipo, status=filtro_status)

        if not feedbacks:
            st.info("Nenhum feedback encontrado com os filtros atuais.")
        else:
            df_fb = pd.DataFrame([{
                "Data": fmt(f["data_hora"]), "Tipo": f["tipo"], "Título": f["titulo"],
                "Status": f["status"], "Prioridade": f.get("prioridade") or "—",
                "Autor": f.get("autor") or "—", "Página": f.get("pagina_origem") or "—",
                "Descrição": f.get("descricao") or "",
            } for f in feedbacks])
            st.download_button("⬇️ Exportar backlog (CSV)",
                               df_fb.to_csv(index=False).encode("utf-8-sig"),
                               file_name="feedback_backlog.csv", mime="text/csv")
            st.dataframe(df_fb, width="stretch", hide_index=True)

            st.divider()
            st.markdown("##### Atualizar um feedback")
            mapa_fb = {f"#{f['id']} — [{f['tipo']}] {f['titulo']}": f for f in feedbacks}
            escolha_fb = st.selectbox("Selecione", list(mapa_fb.keys()), key="fb_sel")
            fb = mapa_fb[escolha_fb]
            u1, u2 = st.columns(2)
            novo_status = u1.selectbox("Status", STATUS_FEEDBACK,
                                       index=STATUS_FEEDBACK.index(fb["status"]) if fb["status"] in STATUS_FEEDBACK else 0,
                                       key="fb_up_status")
            nova_prio = u2.selectbox("Prioridade", ["—", "Baixa", "Média", "Alta", "Crítica"],
                                     index=(["—", "Baixa", "Média", "Alta", "Crítica"].index(fb["prioridade"])
                                            if fb.get("prioridade") in ["Baixa", "Média", "Alta", "Crítica"] else 0),
                                     key="fb_up_prio")
            resposta = st.text_area("Resposta / nota interna", value=fb.get("resposta") or "", key="fb_up_resp")
            if st.button(":material/save: Salvar atualização", type="primary", key="fb_up_btn"):
                ok, msg = atualizar_feedback(
                    fb["id"], status=novo_status,
                    prioridade=(None if nova_prio == "—" else nova_prio),
                    resposta=resposta,
                )
                if ok:
                    st.success(msg)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "Configurações":
    st.title(":material/settings: Configurações do Sistema")
    st.caption("Gestão de Listas Mestras e Parâmetros Globais.")

    # ── Aparência / Tema (v2.11.0) ────────────────────────────────────────────
    with st.container(border=True):
        st.subheader(":material/palette: Aparência")
        _tema_txt = ":material/dark_mode: Escuro" if PAL["tipo"] == "dark" else ":material/light_mode: Claro"
        st.markdown(f"**Tema atual:** {_tema_txt}  ·  **Padrão:** :material/dark_mode: Escuro")
        st.caption("Para alternar entre **claro** e **escuro**, use o botão **Tema** na **barra "
                   "lateral** (abaixo do menu). A escolha é lembrada ao recarregar (fica na URL). "
                   "O fundo, os textos, o menu e os gráficos acompanham. :material/warning: Observação: no modo "
                   "claro, as **tabelas** podem continuar escuras — é uma limitação do Streamlit "
                   "(as grades seguem o tema base); no modo escuro fica tudo consistente.")
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Importação da base do Neidson — Tipo, Mínimo, Máximo, Lead Time (Item 1) ──
    with st.container(border=True):
        st.subheader(":material/download: Importar Base (Tipo/Categoria, Mínimo, Máximo, Lead Time)")
        st.caption("Atualiza itens **existentes** (casados pelo PN) com os dados apurados pelo "
                   "Compras. PNs não encontrados são apenas relatados — nenhum item é criado. "
                   "Um backup do banco é criado automaticamente antes de aplicar.")
        arq_neidson = st.file_uploader("Planilha (.xlsx)", type=["xlsx"], key="upl_neidson")
        if arq_neidson is not None:
            if st.button(":material/search: Pré-visualizar (simulação)", key="btn_prev_neidson"):
                ok_p, res_p = importar_inventario_neidson(arq_neidson, arq_neidson.name, dry_run=True)
                st.session_state["prev_neidson"] = (ok_p, res_p, arq_neidson.name)

            prev = st.session_state.get("prev_neidson")
            if prev:
                ok_p, res_p, nome_p = prev
                if not ok_p:
                    st.error(res_p.get("erro", "Não foi possível ler a planilha."))
                else:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Linhas lidas", res_p["linhas_lidas"])
                    m2.metric("Serão atualizados", res_p["atualizados"])
                    m3.metric("Ignorados (PN não encontrado)", res_p["ignorados"])
                    if res_p["pns_nao_encontrados"]:
                        with st.expander(f"Ver {len(res_p['pns_nao_encontrados'])} PNs não encontrados"):
                            df_ne = pd.DataFrame({"PN não encontrado": res_p["pns_nao_encontrados"]})
                            st.dataframe(df_ne, width="stretch", hide_index=True)
                            st.download_button("⬇️ Baixar lista (CSV)",
                                               df_ne.to_csv(index=False).encode("utf-8-sig"),
                                               file_name="pns_nao_encontrados.csv", mime="text/csv",
                                               key="dl_ne")
                    if res_p["pns_duplicados_planilha"]:
                        st.warning("PNs duplicados na planilha (mantém a última ocorrência): "
                                   + ", ".join(res_p["pns_duplicados_planilha"][:20]))
                    st.warning("Confira os números acima e clique em **Aplicar** para gravar.")
                    if st.button(":material/check_circle: Aplicar atualização", type="primary", key="btn_apply_neidson"):
                        ok_a, res_a = importar_inventario_neidson(arq_neidson, nome_p, dry_run=False)
                        if ok_a:
                            st.success(f"Importação concluída — atualizados: {res_a['atualizados']} | "
                                       f"ignorados: {res_a['ignorados']}.")
                            st.session_state.pop("prev_neidson", None)
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error(res_a.get("erro", "Falha na importação."))
        st.markdown("<br>", unsafe_allow_html=True)

    # Definição das categorias de listas
    LISTAS_CONFIG = {
        "centro_custo": ":material/work: Centros de Custo",
        "local": ":material/location_on: Locais de Armazenagem",
        "fornecedor": ":material/factory: Fornecedores",
        "autorizador": ":material/key: Tipos de Autorizador",
        "setor": ":material/apartment: Setores Solicitantes" # Adicionado setor se necessário
    }

    for tipo_lista, titulo in LISTAS_CONFIG.items():
        with st.container(border=True):
            st.subheader(titulo)
            
            # 1. Visualização da Lista Atual (Grid)
            valores = listar_valores(tipo_lista)
            
            if valores:
                # Cria colunas dinâmicas (4 por linha)
                cols = st.columns(4)
                for i, val in enumerate(valores):
                    with cols[i % 4]:
                        # Card simples para cada item
                        with st.container(border=True):
                            c_txt, c_btn = st.columns([3, 1])
                            c_txt.markdown(f"**{val}**")
                            if c_btn.button(":material/close:", key=f"rm_{tipo_lista}_{i}", help="Remover"):
                                remover_valor_lista(tipo_lista, val)
                                st.rerun()
            else:
                st.info(f"Nenhum {titulo.split(' ')[-1].lower()} cadastrado.")

            st.divider()

            # v3.3.0 — atalho: semear a lista com o cadastro mestre de fornecedores
            if tipo_lista == "fornecedor":
                if st.button(":material/sync: Sincronizar do Relatório de SCs", key="sync_forn",
                             help="Adiciona os Nomes Fantasia do cadastro mestre (importado no "
                                  "Relatório de SCs) que ainda não estão na lista."):
                    _add, _tot = sincronizar_fornecedores_lista()
                    st.success(f"{_add} fornecedor(es) adicionado(s) — {_tot} no cadastro mestre.")
                    time.sleep(1.0)
                    st.rerun()

            # 2. Formulário de Adição
            with st.form(f"form_add_{tipo_lista}", clear_on_submit=True):
                c_input, c_btn = st.columns([3, 1])
                novo_valor = c_input.text_input(
                    f"Adicionar novo {titulo.split(' ', 1)[1].lower()}",
                    placeholder="Digite e pressione Adicionar...",
                    label_visibility="collapsed"
                )
                submitted = c_btn.form_submit_button(":material/add: Adicionar", width="stretch")

                if submitted:
                    if novo_valor.strip():
                        ok, msg = adicionar_valor_lista(tipo_lista, novo_valor.strip())
                        if ok:
                            st.success(msg)
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(msg)
                    else:
                        st.warning("O campo não pode estar vazio.")
        
        st.markdown("<br>", unsafe_allow_html=True) 