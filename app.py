from services.db_functions import obter_dados_dashboard 
import streamlit as st
import pandas as pd
import json, io, os, sys, time, urllib.parse
from streamlit_option_menu import option_menu
from datetime import date, datetime
from services.styles import inject_custom_css
from services.logging_config import setup_logging
from services.constants import (
    PREVISAO_RUPTURA_SEM_RISCO, ORDENACAO_RUPTURA_INFINITO,
    AGING_ALERTA_DIAS, AGING_CRITICO_DIAS, RUPTURA_CRISE_DIAS,
)

sys.path.insert(0, os.path.dirname(__file__))
from database import criar_banco
from services.db_functions import (
    buscar_item_por_id, listar_inventario, salvar_item, desmarcar_inventariado,
    registrar_movimentacao, listar_movimentacoes,
    criar_sc, atualizar_sc, registrar_recebimento_sc, listar_scs,
    listar_itens_sc, buscar_scs_por_item, exportar_inventario_df,
    listar_valores, adicionar_valor_lista, remover_valor_lista,
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
)

setup_logging()
criar_banco()

# v2.2.0 — foto diária do estoque (idempotente por dia; sem scheduler externo).
# Só executa a primeira vez que o app abre no dia; nas demais é praticamente no-op.
try:
    tirar_snapshot_estoque()
except Exception:
    pass

st.set_page_config(page_title="MRO Inventus Power 2.4.0", page_icon="🔧", layout="wide", initial_sidebar_state="expanded")

inject_custom_css()

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
        <span style="font-size: 1.8rem;">MRO Inventus 2.3.0</span>
    </div>
    """, unsafe_allow_html=True)

    # 2. Navegação (Option Menu)

    opcoes_limpas = ["Dashboard", "Inventário", "Gerenciar Itens", "Movimentações", "Requisição", "Compras (SC)", "Feedback", "Configurações"]

    escolha_limpa = option_menu(
        menu_title=None,
        options=opcoes_limpas,
        icons=["bar-chart-fill", "box-seam", "plus-circle", "arrow-repeat", "clipboard-check", "receipt", "chat-dots", "gear"],
        menu_icon="cast",
        default_index=0,
        styles={
            "container": {"padding": "0!important", "background-color": "#050505"},
            "icon": {"color": "#F36F21", "font-size": "18px"}, 
            "nav-link": {"font-size": "14px", "text-align": "left", "margin": "0px", "--hover-color": "#1A1A1A", "color": "#B3B3B3"},
            "nav-link-selected": {"background-color": "#1A1A1A", "color": "#FFFFFF", "border-left": "4px solid #F36F21"},
        }
    )

    # Reconstrói a variável 'pagina' para compatibilidade com seus IFs
    pagina = f"📊 {escolha_limpa}" if escolha_limpa == "Dashboard" else \
             f"📋 {escolha_limpa}" if escolha_limpa in ["Inventário", "Requisição"] else \
             f"➕ {escolha_limpa}" if escolha_limpa == "Gerenciar Itens" else \
             f"🔄 {escolha_limpa}" if escolha_limpa == "Movimentações" else \
             f"🧾 {escolha_limpa}" if escolha_limpa == "Compras (SC)" else \
             f"💬 {escolha_limpa}" if escolha_limpa == "Feedback" else \
             f"⚙️ {escolha_limpa}"

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
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if pagina == "📊 Dashboard":
    st.title(" Dashboard — MRO Inventus Power")
    itens = listar_inventario()
    if not itens:
        st.info("Nenhum item cadastrado. Vá em **➕ Gerenciar Itens** para começar.")
        st.stop()
    
    # --- 1. CÁLCULOS INICIAIS ---
    total   = len(itens)
    ok      = sum(1 for i in itens if "OK" in i.get("status_material",""))
    atencao = sum(1 for i in itens if "ATENÇÃO" in i.get("status_material",""))
    comprar = sum(1 for i in itens if "COMPRAR" in i.get("status_material",""))
    
    # ✅ NOVO: Contagem de itens com estoque físico zerado
    zerados = sum(1 for i in itens if (i.get("estoque_atual") or 0) <= 0)
    
    inv_ok  = sum(1 for i in itens if i.get("data_inventario"))
    
    # --- 2. CARDS DE RESUMO (Métricas com Explicação) ---
    # 6 colunas para incluir a nova métrica "Zerados"
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    with c1:
        st.metric("📦 Itens Totais", total, help="Total de SKUs cadastrados no MRO")
    with c2:
        perc_ok = round(ok/total*100) if total else 0
        st.metric("✅ Materiais ok", ok, f"{perc_ok}% do total", help="Itens com estoque acima do mínimo")
    with c3:
        perc_at = round(atencao/total*100) if total else 0
        st.metric("🟡 Perto de criticidade", atencao, f"{perc_at}% do total", delta_color="off", help="Itens atingindo o ponto de pedido")
    with c4:
        perc_co = round(comprar/total*100) if total else 0
        st.metric("⚠️ Críticos", comprar, f"{perc_co}% do total", delta_color="inverse", help="Itens abaixo do estoque mínimo")
    
    # ✅ NOVA MÉTRICA: ZERADOS (estoque físico = 0)
    with c5:
        perc_zer = round(zerados/total*100) if total else 0
        st.metric("🔴 Zerados", zerados, f"{perc_zer}% do total", delta_color="inverse", 
                 help="Itens com estoque físico = 0 (risco imediato de parada)")
    
    with c6:
        perc_inv = round(inv_ok/total*100) if total else 0
        st.metric("🔍 Inventariado", f"{inv_ok}/{total}", f"{perc_inv}% Inventariado", help="Progresso da conferência física")
    
    st.markdown("---")

    # --- 3. CONTAINER DE ANÁLISE (Estratégico) ---
        # === CONTAINER 1: Curva ABC ===
    with st.container(border=True):
        st.markdown("#### 📉 Curva ABC — Top 10 Consumidores")
        
        # Query para pegar dados do Mês Anterior (Lógica v2.0.1)
        from datetime import date, timedelta
        hoje = date.today()
        primeiro_dia_mes_atual = hoje.replace(day=1)
        ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
        primeiro_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)
        
        periodo_str = f"{primeiro_dia_mes_anterior.strftime('%d/%m')} a {ultimo_dia_mes_anterior.strftime('%d/%m')}"
        st.caption(f"Referência: Consumo realizado entre {periodo_str}")

        # DT-3: Curva ABC obtida via camada de servico (sem acesso SQLite na UI)
        df_abc = pd.DataFrame(obter_dados_dashboard()["abc"])

        if not df_abc.empty:
            import plotly.graph_objects as go
            
            # Preparação dos dados
            df_abc['item_label'] = df_abc.apply(lambda x: f"{x['part_number']} • {x['nome_item'][:15]}...", axis=1)
            df_abc = df_abc.sort_values('total_saida', ascending=True) # Ordenar ascendente para barra horizontal

            fig = go.Figure(data=[go.Bar(
                y=df_abc['item_label'],
                x=df_abc['total_saida'],
                orientation='h',
                marker=dict(
                    color='#F36F21', # Laranja Inventus
                    line=dict(width=1, color='#0E0E0E'), # Borda escura para contraste
                    # corner_radius removido para evitar erro de compatibilidade
                ),
                text=df_abc['total_saida'].apply(lambda x: f'{int(x)} un'),
                textposition='outside',
                textfont=dict(size=11, family="Inter", color="#B3B3B3"),
                hoverinfo='text',
                hovertext=[f"<b>{pn}</b><br>{nome}<br>Consumo: {qtd} un" 
                           for pn, nome, qtd in zip(df_abc['part_number'], df_abc['nome_item'], df_abc['total_saida'])]
            )])

            # Layout Premium Dark
            fig.update_layout(
                template="plotly_dark",
                font=dict(family="Inter", size=12, color="#FFFFFF"),
                margin=dict(l=0, r=20, t=10, b=0),
                height=320,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                showlegend=False,
                xaxis=dict(
                    showgrid=False,
                    zeroline=False,
                    tickfont=dict(color="#B3B3B3"),
                    title_text="Quantidade Consumida (Un)",
                    title_font=dict(size=12, color="#B3B3B3")
                ),
                yaxis=dict(
                    showgrid=False,
                    tickfont=dict(size=11, color="#FFFFFF", family="Inter"),
                    categoryorder='total ascending'
                )
            )
            
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})
            
        else:
            st.info(f"Nenhum dado de consumo registrado no período de {periodo_str}.")

        # === CONTAINER 2: Requisições por Setor ===
        with st.container(border=True):
            st.markdown("#### 🏭 Requisições por Setor")
            reqs_all = listar_requisicoes(limit=500)
            if reqs_all:
                df_setor = pd.DataFrame(reqs_all)
                if "setor" in df_setor.columns and not df_setor["setor"].isna().all():
                    df_count = df_setor["setor"].value_counts().head(7).reset_index()
                    df_count.columns = ["Setor", "Qtd"]
                    st.bar_chart(df_count.set_index("Setor"), color="#F7941E", height=250)
                else:
                    st.caption("Sem dados de setor preenchidos.")
            else:
                st.caption("Aguardando histórico de requisições.")

        # === CONTAINER 3: Top Emitentes ===
        with st.container(border=True):
            st.markdown("#### 👤 Top Emitentes")
            if reqs_all:
                df_emit = pd.DataFrame(reqs_all)
                if "emitente" in df_emit.columns and not df_emit["emitente"].isna().all():
                    df_count = df_emit["emitente"].value_counts().head(10).reset_index()
                    df_count.columns = ["Emitente", "Qtd"]
                    st.dataframe(
                        df_count, width="stretch", hide_index=True, height=250,
                        column_config={
                            "Qtd": st.column_config.ProgressColumn("Qtd", format="%d", min_value=0,
                                max_value=int(df_count["Qtd"].max()) if not df_count.empty else 100, color="#F7941E")
                        }
                    )
                else:
                    st.caption("Sem dados de emitente preenchidos.")
            else:
                st.caption("Aguardando histórico de requisições.")

# ══════════════════════════════════════════════════════════════════════════════
# INVENTÁRIO
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "📋 Inventário":
    st.title("📋 Inventário MRO")
    itens = listar_inventario()
    if not itens:
        st.info("Nenhum item cadastrado. Vá em **➕ Gerenciar Itens** para começar.")
        st.stop()

    # --- CONTAINER 1: FILTROS ---
    with st.container(border=True):
        with st.expander("🔍 Filtros Avançados", expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            
            locais_db = listar_valores("local")
            if not locais_db:
                locais_db = [f"ARM-{i:02d}" for i in range(1, 6)] + [f"MRO-{i:02d}" for i in range(1, 6)]
                
            f_loc    = c1.selectbox("📍 Localização", ["Todas"] + locais_db)
            f_imp    = c2.multiselect("Importância", IMPORTANCIAS)
            f_tipo   = c3.multiselect("Tipo", TIPOS)
            f_status = c4.multiselect("Status", ["🟢 OK", "🟡 ATENÇÃO", "🔴 COMPRAR"])
            
            c5, c6 = st.columns(2)
            f_busca  = c5.text_input("🔎 Buscar PN ou Nome")
            f_inv    = c6.selectbox("Inventariado", ["Todos", "✅ Inventariado", "Não inventariado"])
        

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
            
        if f_inv == "✅ Inventariado":    
            df = df[df["data_inventario"].fillna("").str.strip().str.len() > 0]
        if f_inv == "Não inventariado": 
            df = df[~(df["data_inventario"].fillna("").str.strip().str.len() > 0)]
            
        if f_busca:
            b = f_busca.lower()
            df = df[df["part_number"].str.lower().str.contains(b, na=False) | 
                    df["nome_item"].str.lower().str.contains(b, na=False)]

        st.caption(f"📊 Exibindo **{len(df)}** de **{len(itens)}** itens")

    # --- CONTAINER 2: TABELA PRINCIPAL ---
    with st.container(border=True):
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
            }
        )

    # --- CONTAINER 3: CONTAGEM FÍSICA ---
    with st.container(border=True):
        st.subheader("📦 Realizar Contagem Física")
        _, item_inv, _ = sel_material("Selecione o item para atualizar saldo/localização", "sel_inventario")

        if item_inv:
            st.info(f"**Item:** `{item_inv['part_number']} — {item_inv['nome_item']}` | **Saldo Atual:** `{item_inv['estoque_atual']} {item_inv.get('unidade','UN')}`")

            # Carrega locais disponíveis
            locais_disp = listar_valores("local") or ["Geral"]
            if item_inv.get("local_armazenagem") and item_inv.get("local_armazenagem") not in locais_disp: 
                locais_disp.insert(0, item_inv["local_armazenagem"])
            
            c_q, c_l = st.columns(2) 
            
            # Inicializa com o estoque atual. Se for 0, começa em 0.
            nova_qtd = c_q.number_input("Quantidade Real", min_value=0.0, step=1.0, value=float(item_inv['estoque_atual']))
            
            # Selectbox de Local (Obrigatório)
            local_atual = item_inv.get("local_armazenagem")
            idx_local_inicial = 0
            if local_atual and local_atual in locais_disp:
                idx_local_inicial = locais_disp.index(local_atual)
                
            novo_local = c_l.selectbox("Local (1ª Locação)", options=locais_disp, index=idx_local_inicial)
            
            # ✅ NOVO CAMPO: Observação Operacional (Texto Livre)
            obs_inventario = st.text_input(
                "📝 Observação de Inventário", 
                value=item_inv.get("caixa_identificacao") or "", 
                placeholder="Ex: material danificado, sem etiqueta, divergência física, caixa avariada..."
            )

            col_btn1, col_btn2, _ = st.columns([1, 1, 2])
            
            if col_btn1.button("✅ Confirmar Contagem", type="primary", width="stretch"):
                delta = nova_qtd - item_inv['estoque_atual']
                
                # Verifica mudanças operacionais
                mudou_local = (novo_local != item_inv.get("local_armazenagem"))
                mudou_obs = (obs_inventario.strip() != (item_inv.get("caixa_identificacao") or "").strip())
                mudou_qtd = (delta != 0)

                # Se nada mudou, avisa o usuário
                if not mudou_qtd and not mudou_local and not mudou_obs:
                    st.warning("⚠️ Nenhuma alteração detectada. O item já está com esses dados.")
                else:
                    # 1. Atualiza sempre os metadados (Local e Obs) e marca como inventariado
                    ok_loc, msg_loc = atualizar_localizacao_e_inventariar(item_inv["id"], novo_local, obs_inventario)
                    
                    if ok_loc:
                        # 2. Lógica de Movimentação (Histórico)
                        # Precisamos registrar no histórico se houve mudança de QTD OU de Metadados (Local/Obs)
                        
                        obs_partes = []
                        if mudou_local: 
                            obs_partes.append(f"Local: {item_inv.get('local_armazenagem','N/A')} → {novo_local}")
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
                        elif mudou_local or mudou_obs:
                            obs_final = f"Conferência de Inventário (Sem alteração de Qtd) {' | '.join(obs_partes)}"
                            
                            registrar_movimentacao(
                                item_id=item_inv["id"], tipo="entrada", quantidade=0.0, # Qtd 0 para não alterar saldo
                                centro_custo="INVENTÁRIO", solicitante="Inventário", emitente="Inventário",
                                observacao=obs_final
                            )

                        st.success(f"✅ Contagem registrada! Novo saldo: `{nova_qtd}`")
                        time.sleep(1.2)
                        st.rerun()
                    else:
                        st.error(f"❌ Erro ao atualizar localização: {msg_loc}")

            if item_inv.get("data_inventario") and col_btn2.button("❌ Remover Marcação", width="stretch"):
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
elif pagina == "➕ Gerenciar Itens":
    st.title("➕ Gerenciar Itens MRO")

    # --- TABS PARA ORGANIZAÇÃO ---
    tab_editar, tab_novo = st.tabs(["✏️ Editar Item Existente", "🆕 Cadastrar Novo Item"])

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

            if st.button("💾 Salvar Novo Item", type="primary", width="stretch"):
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
                            descricao="",
                            unidade=un_novo,
                            importancia=imp_novo,
                            tipo_material=tipo_novo, 
                            setor="Improdutivo",
                            local=loc_novo, 
                            caixa=caixa_novo,
                            estoque_atual=est_ini_novo, 
                            estoque_minimo=min_novo, 
                            lead_time=lead_novo
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
                                                  f"Sugestão calculada (consumo×lead time×1,5): {_seg_calc:.1f}.")
                    # Nota: Estoque atual NÃO deve ser editado aqui, apenas via Movimentação/Inventário
                    st.markdown(f"**Estoque Atual:** `{item_sel['estoque_atual']}` (Alterar em *Inventário*)")
                    st.markdown(f"**Status:** `{item_sel['status_material']}`")

                if st.button("✅ Atualizar Item", type="primary", width="stretch"):
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
                        f"⏱️ **Lead Time** — cadastrado (Neidson): **{_lt_cad}d** · "
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
                st.markdown("##### 🔁 Alterar Part Number")
                st.caption("Use quando o PN for corrigido no Protheus. O histórico (movimentações, "
                           "SCs e requisições) é preservado e o PN antigo continua pesquisável.")
                cpn1, cpn2 = st.columns([1, 1])
                novo_pn = cpn1.text_input("Novo Part Number", key="pn_novo", placeholder=item_sel['part_number'])
                motivo_pn = cpn2.text_input("Motivo da alteração", key="pn_motivo", placeholder="Ex: padronização Protheus")
                confirma_pn = st.checkbox("Confirmo a alteração do Part Number", key="pn_confirma")
                if st.button("🔁 Alterar Part Number", key="btn_alterar_pn", width="stretch"):
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
                    with st.expander(f"📜 Histórico de Part Numbers ({len(hist_pn)})"):
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
elif pagina == "🔄 Movimentações":
    st.title("🔄 Controle de Estoque")

    # --- TABS: AJUSTE, HISTÓRICO E DASHBOARD ---
    tab_ajuste, tab_hist, tab_dash = st.tabs(["⚖️ Ajuste Rápido", "📜 Histórico Completo", "📊 Analytics"])

    centros = listar_valores("centro_custo") or ["Geral"]

    # === TAB 1: AJUSTE RÁPIDO DE ESTOQUE ===
    with tab_ajuste:
        with st.container(border=True):
            st.subheader("⚖️ Ajuste Manual de Saldo")
            st.caption("Utilize apenas para correções de inventário, perdas ou sobras não justificadas por SC/Req.")
            
            _, item_aj, _ = sel_material("Selecione o Item para Ajuste", "sel_ajuste_estoque")
            
            if item_aj:
                st.info(f"**Item:** `{item_aj['part_number']} — {item_aj['nome_item']}` | **Saldo Atual:** `{item_aj['estoque_atual']}`")
                
                c1, c2, c3 = st.columns(3)
                tipo_aj = c1.radio("Tipo de Ajuste", ["➕ Entrada (Sobra)", "➖ Saída (Perda/Ajuste)"], horizontal=True)
                qtd_aj = c2.number_input("Quantidade", min_value=0.01, step=1.0)
                cc_aj = c3.selectbox("Centro de Custo (Responsável)", centros, index=0)
                
                obs_aj = st.text_input("Motivo do Ajuste *", placeholder="Ex: Avaria, erro de contagem anterior...")
                resp_aj = st.text_input("Responsável pelo Ajuste *")

                if st.button("✅ Confirmar Ajuste", type="primary", width="stretch"):
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
                                st.success(f"✅ Ajuste registrado! Novo saldo: {msg}")
                                time.sleep(1.2)
                                st.rerun()
                            else:
                                st.error(f"❌ Erro: {msg}")

    # === TAB 2: HISTÓRICO COMPLETO ===
    with tab_hist:
        with st.container(border=True):
            st.subheader("📜 Histórico de Movimentações")
            
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
                df_exib['Tipo Display'] = df_exib.apply(lambda x: '📋 Conferência' if x['Qtd'] == 0 else x['Tipo'], axis=1)

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
        st.subheader("📊 Analytics Operacional Completo")

        # v2.2.1 — Rótulo de maturidade do histórico (transparência)
        _mat = obter_maturidade_dados()
        if _mat["dias"] > 0:
            st.caption(
                f"📅 Indicadores de série (consumo, tendência, giro) baseados em "
                f"**{_mat['dias']} dias** de histórico — desde "
                f"{fmt(_mat['data_inicio']) if _mat['data_inicio'] else '—'} · "
                f"{_mat['n_snapshots']} fotos de estoque. A confiança aumenta conforme "
                f"os dados acumulam."
            )

        # v2.2.1 — Inteligência de Estoque: Cobertura · Tendência · Giro
        with st.container(border=True):
            st.markdown("#### 🧠 Inteligência de Estoque (Cobertura · Tendência · Giro)")
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
                    st.markdown("**📈 Tendência de consumo**")
                    if "Tendência" in df_series.columns:
                        vc = df_series["Tendência"].value_counts()
                        st.metric("🔺 Em alta", int(vc.get("Alta", 0)),
                                  help="Consumo dos últimos 30d mais de 15% acima dos 30d anteriores.")
                        st.metric("🔻 Em queda", int(vc.get("Queda", 0)))
                        st.metric("➖ Estável", int(vc.get("Estável", 0)))
                with cb:
                    st.markdown("**🛡️ Menor cobertura (dias)**")
                    st.caption("(estoque + guarda-chuva) ÷ consumo diário")
                    if "Cobertura(d)" in df_series.columns:
                        low = (df_series[df_series["Cobertura(d)"] < 900]
                               .nsmallest(8, "Cobertura(d)")[["PN", "Cobertura(d)"]])
                        st.dataframe(low, hide_index=True, width="stretch", height=250)
                with cc:
                    st.markdown("**🔁 Itens parados (giro 0 c/ estoque)**")
                    st.caption("Capital imobilizado sem saída no período.")
                    if "Giro(anual)" in df_series.columns:
                        parados = df_series[(df_series["Giro(anual)"] == 0) &
                                            (df_series["Estoque Atual"] > 0)]
                        st.caption(f"Total: {len(parados)} itens")
                        st.dataframe(parados[["PN", "Estoque Atual"]].head(8),
                                     hide_index=True, width="stretch", height=210)

        st.markdown("---")

        # v2.3.0 — 💰 Financeiro: valor imobilizado · ABC por valor · evolução de preço
        with st.container(border=True):
            st.markdown("#### 💰 Financeiro (Valoração — estimativas rotuladas)")
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
                    "💰 Valor imobilizado (BRL)", f"R$ {vi['total_brl']:,.2f}",
                    help="Σ (estoque atual × preço de valoração) dos itens em BRL. "
                         "Estimativa pelo último preço.",
                )
                k2.metric(
                    "✅ Itens valorados", vi["itens_valorados"],
                    help="Itens com preço de referência conhecido (SCM ou histórico).",
                )
                k3.metric(
                    "⚠️ Sem preço", vi["itens_sem_preco"],
                    help="Itens COM estoque mas SEM preço conhecido — subestimam o total. "
                         "Aparecem quando o material ainda não foi comprado via SCM/SC7.",
                )
                if vi["itens_nao_brl"]:
                    st.caption(
                        f"🌐 {vi['itens_nao_brl']} item(ns) com moeda ≠ BRL "
                        f"(≈ {vi['total_nao_brl']:,.2f} na moeda original) somados à parte — "
                        "sem conversão cambial nesta versão."
                    )

            fa, fb = st.columns(2)

            # Evolução do valor imobilizado (fotos diárias)
            with fa:
                st.markdown("**📈 Evolução do valor imobilizado**")
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
                st.markdown("**📊 Curva ABC por valor (últimos 90d)**")
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
                st.markdown("**🧊 Top capital parado (maior valor em estoque, giro 0)**")
                st.caption("Dinheiro parado sem saída no período — candidatos a reduzir/realocar.")
                parado_val = (df_series[(df_series["Giro(anual)"] == 0) &
                                        (df_series["Valor em Estoque"] > 0)]
                              .nlargest(8, "Valor em Estoque")[["PN", "Estoque Atual",
                                                                "Valor em Estoque"]])
                if not parado_val.empty:
                    st.dataframe(
                        parado_val, hide_index=True, width="stretch",
                        column_config={"Valor em Estoque":
                                       st.column_config.NumberColumn(format="R$ %.2f")},
                    )
                else:
                    st.success("✅ Nenhum item de valor relevante totalmente parado.")

            # Evolução de preço por item (antecipa parte da Ficha 360 v2.6)
            st.markdown("**🔎 Evolução de preço (por item)**")
            if not df_series.empty and "PN" in df_series.columns:
                _map_pn = {i["part_number"]: i["id"] for i in listar_inventario()}
                pn_sel = st.selectbox("Item", ["—"] + sorted(_map_pn.keys()),
                                      key="fin_pn_preco")
                if pn_sel and pn_sel != "—":
                    serie_p = obter_evolucao_preco(_map_pn[pn_sel])
                    if serie_p:
                        df_p = pd.DataFrame(serie_p)
                        df_p["data"] = pd.to_datetime(df_p["data"], errors="coerce")
                        df_p = df_p.dropna(subset=["data"]).sort_values("data")
                        if not df_p.empty:
                            st.line_chart(df_p.set_index("data")["preco_unitario"], height=220)
                            st.caption(
                                f"{len(df_p)} registro(s) de preço · origem(ns): "
                                f"{', '.join(sorted(df_p['origem'].dropna().unique()))}."
                            )
                        else:
                            st.info("Sem datas válidas no histórico de preço deste item.")
                    else:
                        st.info("Sem histórico de preço para este item ainda.")

        st.markdown("---")

        # --- LINHA 1: VOLUME E DIVERGÊNCIAS (Lado a Lado) ---
        c_vol, c_div = st.columns(2)

        # 1. VOLUME DE ENTRADAS E SAÍDAS
        with c_vol:
            with st.container(border=True):
                st.markdown("#### 📦 Volume de Movimentações")
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
                        
                        df_pivot = df_pivot.rename(columns={'entrada': '📥 Entradas', 'saida': '📤 Saídas', 'devolucao': '↩️ Dev'})
                        df_pivot = df_pivot.sort_index(ascending=True)

                        t1, t2 = st.columns(2)
                        t1.metric("Total Entradas", f"{df_pivot['📥 Entradas'].sum():,.0f}")
                        t2.metric("Total Saídas", f"{df_pivot['📤 Saídas'].sum():,.0f}")

                        st.bar_chart(df_pivot[['📥 Entradas', '📤 Saídas']], color=["#2ecc71", "#e74c3c"])
                    except Exception as e:
                        st.error(f"Erro ao processar volume: {e}")

        # 2. DIVERGÊNCIAS DE INVENTÁRIO
        with c_div:
            with st.container(border=True):
                st.markdown("#### ⚖️ Top Itens com Divergências")
                st.caption("Ajustes manuais frequentes (sem Req/SC) indicam erro de processo.")
                
                df_div = obter_analitico_divergencias(days=90)
                
                if df_div.empty:
                    st.success("✅ Nenhuma divergência significativa.")
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
            st.markdown("#### 🚨 Ruptura de Estoque (Impacto na Operação)")
            st.caption("Itens que zeraram o estoque durante uma requisição nos últimos 90 dias. Indica falha de abastecimento.")
            
            df_rup = obter_analitico_rupturas(days=90)
            
            if df_rup.empty:
                st.success("✅ **Operação Fluida:** Nenhuma ruptura registrada no período. O estoque atendeu todas as requisições.")
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
                
                st.warning("💡 **Ação Recomendada:** Revise o **Estoque Mínimo** e o **Lead Time** destes itens imediatamente para evitar paradas de linha.")

# ══════════════════════════════════════════════════════════════════════════════
# REQUISIÇÃO
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "📋 Requisição":
    st.title("📋 Requisição de Material")
    
    aba_nova, aba_hist_req = st.tabs(["📝 Nova Requisição", "📜 Histórico"])
    
    # Configurações de contexto
    autorizadores_lista = listar_valores("autorizador") or ["Gestor", "Líder", "Reserva"]
    centros = listar_valores("centro_custo")

    with aba_nova:
        if "itens_req" not in st.session_state: st.session_state.itens_req = []
        if "req_confirmada" not in st.session_state: st.session_state.req_confirmada = None

        # --- FEEDBACK DE SUCESSO ---
        if st.session_state.req_confirmada:
            st.success(f"### ✅ Requisição {st.session_state.req_confirmada} enviada!")
            st.info("O estoque foi atualizado e o registro foi salvo no histórico.")
            if st.button("Iniciar Nova Requisição", width="stretch"):
                st.session_state.req_confirmada = None
                st.rerun()
            st.stop()

        # --- BLOCO 1: IDENTIFICAÇÃO ---
        with st.container():
            st.markdown("##### 1️⃣ Identificação da Demanda")
            c1, c2, c3 = st.columns(3)
            req_setor = c1.text_input("Setor Solicitante *")
            req_emit  = c2.text_input("Nome do Emitente *")
            opcoes_cc = [""] + (listar_valores("centro_custo") or [])
            req_cc    = c3.selectbox("Centro de Custo *", options=opcoes_cc, index=0)

        st.markdown("---")

        # --- BLOCO 2: SELEÇÃO DE MATERIAIS ---
        with st.container():
            st.markdown("##### 2️⃣ Adicionar Materiais")
            _, item_req_add, _ = sel_material("Pesquise o material para requisitar", "sel_req_add")
            
            if item_req_add:
                # Card de disponibilidade rápida
                st.markdown(f"""
                    <div style="border: 1px solid #3e424b; padding: 10px; border-radius: 5px; background-color: #1e2130; margin-bottom: 10px;">
                        <span style="color: #F7941E; font-weight: bold;">DISPONÍVEL:</span> {item_req_add.get('estoque_atual',0)} {item_req_add.get('unidade','UN')}
                    </div>
                """, unsafe_allow_html=True)

            with st.form("form_add_item_req", clear_on_submit=True):
                ci1, ci2 = st.columns(2)
                qtd_sol = ci1.number_input("Qtd Solicitada *", min_value=1.0, step=1.0, value=1.0)
                qtd_ate = ci2.number_input("Qtd Atendida *", min_value=0.0, step=1.0, value=1.0)
                add_item = st.form_submit_button("➕ ADICIONAR À LISTA", width="stretch")

            if add_item:
                if not item_req_add:
                    st.warning("⚠️ Selecione um material antes de adicionar.")
                elif qtd_ate > item_req_add.get("estoque_atual", 0):
                    st.error(f"❌ Saldo insuficiente! Estoque: {item_req_add.get('estoque_atual', 0)}")
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
            st.markdown("###### 📦 Itens na Requisição Atual:")
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
            st.markdown("##### 3️⃣ Regras de Entrega e SESMT")
            col_ei, col_sesmt = st.columns(2)
            with col_ei:
                entrega_ind = st.checkbox("📦 Entrega Individual (EPI/Uniforme)")
                if entrega_ind:
                    destinatarios_txt = st.text_area("Lista de Destinatários *", 
                        placeholder="MATRÍCULA — NOME (um por linha)", height=100)
            with col_sesmt:
                is_sesmt = st.checkbox("🦺 Requer Aprovação SESMT")
                if is_sesmt:
                    sesmt_resp = st.text_input("Responsável SESMT *")

        # --- BLOCO 4: AUTORIZAÇÃO E FINALIZAÇÃO ---
        with st.container():
            st.markdown("##### 4️⃣ Autorização Final")
            ca1, ca2 = st.columns(2)
            aut_tipo = ca1.selectbox("Tipo de Autorizador *", autorizadores_lista)
            aut_nome = ca2.text_input("Assinatura / Nome do Autorizador *")
            obs_req  = st.text_area("Observações Gerais da Requisição", height=70)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✅ FINALIZAR E ATUALIZAR ESTOQUE", type="primary", width="stretch"):
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
        st.markdown("### 📜 Histórico de Requisições")
        reqs = listar_requisicoes(limit=200)
        if not reqs:
            st.info("Nenhuma requisição registrada até o momento.")
        else:
            df_reqs = pd.DataFrame(reqs)[["numero_requisicao", "data_hora", "setor", "emitente", "autorizador_nome", "total_itens"]]
            df_reqs.columns = ["Nº Req", "Data/Hora", "Setor", "Emitente", "Autorizador", "Qtd Itens"]
            st.dataframe(df_reqs, width="stretch", hide_index=True)
            
            st.markdown("---")
            st.markdown("#### 🔍 Detalhes da Requisição")
            opcoes_req = {f"REQ-{r['numero_requisicao']} | {r['setor']} | {r['data_hora'][:10]}": r for r in reqs}
            sel_req = st.selectbox("Escolha uma requisição para ver os detalhes:", [""] + list(opcoes_req.keys()))
            
            if sel_req:
                r_det = opcoes_req[sel_req]
                with st.container():
                    st.markdown(f"**Resumo REQ-{r_det['numero_requisicao']}**")
                    c_a, c_b, c_c = st.columns(3)
                    c_a.write(f"👤 **Emitente:** {r_det['emitente']}")
                    c_b.write(f"✍️ **Autorizador:** {r_det['autorizador_nome']}")
                    c_c.write(f"🏢 **C.Custo:** {r_det['centro_custo']}")
                    
                    itens_det = listar_itens_requisicao(r_det["id"])
                    if itens_det:
                        df_det = pd.DataFrame(itens_det)[["part_number", "nome_item", "quantidade_solicitada", "quantidade_atendida", "unidade"]]
                        df_det.columns = ["PN", "Material", "Solicitado", "Atendido", "UN"]
                        st.table(df_det)
                        
# ══════════════════════════════════════════════════════════════════════════════
# COMPRAS (SC)
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "🧾 Compras (SC)":
    st.title("🧾 Gestão de Compras — S.C.")
    
    # Estrutura de abas mantida conforme solicitado
    aba_mon, aba_forn, aba_nova_sc, aba_rec, aba_ed, aba_h, aba_import = st.tabs([
    "📡 Monitor", "🏢 Fornecedores & Cotação", "➕ Nova SC", "📦 Receber Material",
    "🔄 Atualizar Status", "📜 Histórico", "📥 Importar Relatório de SCs"
    ])
    # ══════════════════════════════════════════════════════════════════════════════
    # 📡 MONITOR DE COMPRAS 
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_mon:
        st.markdown("### 📡 Monitor de Compras")
        st.caption("Acompanhe todas as SCs abertas. Colunas críticas destacadas para leitura rápida.")
        
        # UX: Filtros rápidos
        c_filt1, c_filt2 = st.columns([3, 2])
        with c_filt1:
            f_busca = st.text_input("🔍 Buscar PN, Nº SC ou Fornecedor", placeholder="Ex: SC-2026, 123456, SKF...", key="busca_monitor_sc")
        with c_filt2:
            f_crise = st.checkbox(f"🚨 Focar apenas em Ruptura < {RUPTURA_CRISE_DIAS} dias", value=False, key="filtro_ruptura_sc")

        scs = listar_scs(apenas_abertas=True)
        if not scs:
            st.success("✅ Nenhuma SC aberta! Operação fluida.")
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
                        if forn != "—": status_display, cor = "🚚 Aguardando Entrega", "🔵"
                        elif po != "—": status_display, cor = "🔍 Verificar Fornecedor", "🟡"
                        else: status_display, cor = "⚠️ Abrir Cotação", "🔴"

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
                
                st.caption("📊 Ordenado automaticamente por: 1º Dias até Ruptura | 2º Impacto na Produção | 3º Tempo de Espera")
                                    
     # ══════════════════════════════════════════════════════════════════════════════
    #   📥 IMPORTAR PROTHEUS
    # ═══════════════════════════════════════════════════════════════════════════════
    with aba_import:
        with st.container(border=True):
            st.markdown("### 📥 Importar Relatório de SCs")
            st.caption("Upload da planilha diária dos compradores. Roteia por aba: **SCM** (SCs + preço), "
                       "**SC7** (histórico de preços), **FORNECEDORES** (cadastro + e-mails) e **SCM USERS** "
                       "(solicitantes). Upsert com histórico preservado; backup automático antes de gravar.")
            arquivo = st.file_uploader("Arquivo Excel (.xlsx / .xls)", type=["xlsx", "xls"], key="upload_relatorio_scs")

            if arquivo:
                if st.button("🔄 Processar Relatório de SCs", width="stretch", type="primary"):
                    with st.spinner("Processando abas do Relatório de SCs..."):
                        ok, resultado = importar_relatorio_scs(arquivo, arquivo.name)
                    if ok:
                        scm = resultado.get("SCM", {}) or {}
                        if isinstance(scm, dict) and not scm.get("erro"):
                            st.markdown("**📄 SCM — Solicitações + Preço**")
                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric("📥 Importadas", scm.get("linhas_importadas", 0))
                            m2.metric("🚫 Ignoradas", scm.get("linhas_ignoradas", 0))
                            m3.metric("💲 Preços", scm.get("precos_capturados", 0))
                            m4.metric("🔴 Rupturas", scm.get("rupturas", 0))
                            m5, m6, m7, m8 = st.columns(4)
                            m5.metric("📄 SCs Criadas", scm.get("scs_criadas", 0))
                            m6.metric("🔄 SCs Atualizadas", scm.get("scs_atualizadas", 0))
                            m7.metric("⚠️ Divergências", scm.get("divergencias", 0))
                            m8.metric("🔥 Críticos", scm.get("criticos", 0))

                        st.markdown("**🔗 Demais fontes**")
                        sc7 = resultado.get("SC7", {}) or {}
                        forn = resultado.get("FORNECEDORES", {}) or {}
                        usr = resultado.get("SCM USERS", {}) or {}
                        c1, c2, c3 = st.columns(3)
                        c1.metric("💲 Preços SC7", sc7.get("precos_inseridos", 0) if isinstance(sc7, dict) else 0)
                        c2.metric("🏢 Fornecedores", f"{forn.get('upserted', 0)}" if isinstance(forn, dict) else "—",
                                  help=f"Com e-mail: {forn.get('com_email', 0)}" if isinstance(forn, dict) else None)
                        c3.metric("👥 Solicitantes", usr.get("upserted", 0) if isinstance(usr, dict) else 0)

                        erros = {aba: r.get("erro") for aba, r in resultado.items()
                                 if isinstance(r, dict) and r.get("erro")}
                        if erros:
                            st.warning("Abas com aviso: " + " · ".join(f"**{a}**: {e}" for a, e in erros.items()))
                        if isinstance(scm, dict) and scm.get("ignorados_amostra"):
                            with st.expander("Amostra de linhas ignoradas (SCM)"):
                                st.dataframe(pd.DataFrame(scm["ignorados_amostra"]), width="stretch", hide_index=True)
                        st.success(f"✅ Importação concluída. Foto de estoque do dia: "
                                   f"{resultado.get('_snapshot_criados', 0)} itens.")
                    else:
                        erros = {aba: r.get("erro") for aba, r in resultado.items()
                                 if isinstance(r, dict) and r.get("erro")}
                        st.error("❌ Falha ao importar. " +
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
    with aba_forn:
        st.markdown("### 🏢 Fornecedores & Cotação")
        st.caption("Busque um material para ver seus fornecedores, último preço e lead time, "
                   "e gerar um e-mail de cotação pronto. O sistema recomenda; o comprador decide.")

        _, item_forn, _ = sel_material("Busque o material (PN ou nome)", "forn_item")
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
                f"Lead time cadastrado (Neidson): {lt_cad}d{lt_calc_txt}"
            )

            fs = obter_fornecedores_por_item(item_forn["id"])
            if not fs:
                st.warning("Sem fornecedores para este item ainda. Os fornecedores vêm dos "
                           "pedidos importados no Relatório de SCs (Nome Fantasia por nº do pedido).")
            else:
                melhor = next((f for f in fs if f.get("melhor")), None)
                if melhor:
                    st.success(
                        f"⭐ **Melhor fornecedor: {melhor['fornecedor']}** — {melhor['melhor_motivo']}. "
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
                    "Cadastro": "✅" if f["no_cadastro"] else "⚠️",
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
                           "prazo real (SC7) atribuído pelo nº do pedido. ‘⚠️’ = fornecedor sem "
                           "correspondência no cadastro (sem e-mail para cotação).")

                # --- Rascunho de cotação (não envia) ---
                st.markdown("#### ✉️ Rascunho de cotação")
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
                    st.link_button("✉️ Abrir e-mail no meu cliente", mailto)
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
            st.success(f"✅ {st.session_state.sc_criada}")
            if st.button("➕ Criar outra SC", width="stretch"):
                st.session_state.sc_criada = None; st.rerun()
            st.stop()

        # UX: Seletor de material isolado
        _, item_sc_add, _ = sel_material("Selecionar Material", "sel_sc_add")

        with st.form("form_add_isc", clear_on_submit=True):
            st.markdown("##### 📦 Adicionar Item à Lista ")
            c1, c2 = st.columns(2)
            # Apenas Quantidade e Data de Necessidade na criação
            qtd_i   = c1.number_input("Qtd Solicitada *", min_value=0.01, step=1.0)
            d_nec   = c2.date_input("Data de Necessidade *", value=date.today())
            
            obs_i    = st.text_area("Justificativa / Urgência", placeholder="Ex: Parada de linha iminente...", height=60)
            
            add_isc = st.form_submit_button("➕ Adicionar à Lista", width="stretch")

        if add_isc:
            if not item_sc_add:
                st.warning("⚠️ Selecione um material antes de adicionar.")
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
            st.markdown("###### 📋 Itens Pré-cadastrados:")
            df_prev_sc = pd.DataFrame(st.session_state.itens_nova_sc)[["part_number", "nome_item", "quantidade_solicitada", "data_necessidade"]]
            df_prev_sc.columns = ["PN", "Nome", "Qtd Solic.", "Data Nec."]
            df_prev_sc["Data Nec."] = df_prev_sc["Data Nec."].apply(fmt)
            st.dataframe(df_prev_sc, width="stretch", hide_index=True)
            
            if st.button("🗑️ Limpar Lista", type="secondary"):
                st.session_state.itens_nova_sc = []; st.rerun()

        st.divider()
        with st.form("form_criar_sc"):
            st.markdown("##### 📝 Finalizar S.C. (Registro Inicial)")
            c1, c2 = st.columns(2)
            num_sc = c1.text_input("Número da SC *", placeholder="Ex: SC-2026-001")
            dt_ab  = c2.date_input("Data de Abertura *", value=date.today())
            obs_sc = st.text_area("Observações Gerais", height=60)
            criar_b = st.form_submit_button("✅ Criar S.C.", width="stretch", type="primary")
            
        if criar_b:
            if not num_sc.strip():
                st.warning("⚠️ O Número da SC é obrigatório.")
            elif not st.session_state.itens_nova_sc:
                st.warning("⚠️ Adicione ao menos um item à lista.")
            else:
                ok, msg = criar_sc(num_sc.strip(), str(dt_ab), st.session_state.itens_nova_sc, obs_sc)
                if ok:
                    st.session_state.itens_nova_sc = []
                    st.session_state.sc_criada = msg; st.rerun()
                else:
                    st.error(f"❌ {msg}")

    # ══════════════════════════════════════════════════════════════════════════════
    #  📦 RECEBER MATERIAL (Grid Inteligente + Feedback Visual Aprimorado)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_rec:
        with st.container(border=True):
            st.markdown("### 📦 Registrar Recebimento de Material")
            st.caption("Vincule a uma SC aberta ou registre como entrada avulsa.")
            
            centros = listar_valores("centro_custo")
            _, item_rec, _ = sel_material("Material *", "sel_rec")

            if item_rec:
                # UX: Card de contexto do item selecionado
                st.markdown(f"`{item_rec['part_number']}` — **{item_rec['nome_item']}** | Saldo Atual: `{item_rec['estoque_atual']}` {item_rec.get('unidade','UN')}")
                
                scs_item = buscar_scs_por_item(item_rec["id"], apenas_abertas=True)
                sc_sel = None

                if scs_item:
                    vincular = st.checkbox("🔗 Vincular a uma S.C. Aberta", value=True)
                    if vincular:
                        opc_sc = {f"SC {s['numero_sc']} | PO: {s.get('po_item') or '—'} | Saldo: {s['pendente']} {item_rec['unidade']}": s for s in scs_item}
                        sel_sc_str = st.selectbox("Selecionar SC", list(opc_sc.keys()), label_visibility="collapsed")
                        sc_sel = opc_sc[sel_sc_str]
                        
                        with st.container(border=True):
                            st.markdown(f"✅ **SC {sc_sel['numero_sc']}** | PO: `{sc_sel['numero_po'] or '—'}` | Fornecedor: {sc_sel.get('fornecedor_item') or sc_sel['fornecedor'] or '—'}")
                            st.markdown(f"Solicitado: `{sc_sel['quantidade_solicitada']}` | Negociado: `{sc_sel.get('quantidade_negociada') or sc_sel['quantidade_solicitada']}` | Recebido: `{sc_sel['quantidade_recebida']}` | **Saldo Residual: `{sc_sel['pendente']}`**")
                else:
                    st.info("ℹ️ Nenhuma SC aberta para este material. A entrada será registrada como avulsa.")

                with st.form("form_rec"):
                    st.markdown("##### 📥 Dados do Recebimento")
                    c1, c2, c3 = st.columns(3)
                    limite_rec = float(sc_sel["pendente"]) if sc_sel else None
                    qtd_default = min(1.0, limite_rec) if limite_rec else 1.0
                    
                    # UX: Limita input ao saldo pendente para evitar erros humanos
                    if limite_rec:
                        qtd_r = c1.number_input("Qtd Recebida *", min_value=0.01, max_value=limite_rec, step=1.0, value=qtd_default)
                    else:
                        qtd_r = c1.number_input("Qtd Recebida *", min_value=0.01, step=1.0)
                        
                    forn   = c2.text_input("Fornecedor *", value=(sc_sel.get("fornecedor_item") or sc_sel.get("fornecedor") or "") if sc_sel else "")
                    dt_r   = c3.date_input("Data Recebimento", value=date.today())
                    
                    cc_r   = st.selectbox("Centro de Custo *", centros if centros else ["—"])
                    obs_nf = st.text_input("Nota Fiscal / Documento *" if sc_sel else "Obs / Nota Fiscal")
                    
                    rec_b  = st.form_submit_button("📥 Confirmar Recebimento", width="stretch", type="primary")

                if rec_b:
                    if not forn:
                        st.warning("⚠️ Informe o fornecedor.")
                    elif sc_sel and not obs_nf.strip():
                        st.warning("⚠️ Informe o número da Nota Fiscal para rastreabilidade.")
                    elif sc_sel:
                        ok, msg = registrar_recebimento_sc(
                            sc_id=sc_sel["id"], item_sc_id=sc_sel["item_sc_id"],
                            qtd_recebida=qtd_r, centro_custo=cc_r,
                            solicitante="Almoxarifado", emitente="Almoxarifado",
                            fornecedor=forn, data_recebimento=str(dt_r), obs_nf=obs_nf
                        )
                        if ok: st.success(f"✅ **Recebimento registrado!** {msg}"); time.sleep(2); st.rerun()
                        else:  st.error(f"❌ {msg}")
                    else:
                        ok, msg = registrar_movimentacao(
                            item_id=item_rec["id"], tipo="entrada", quantidade=qtd_r,
                            centro_custo=cc_r, solicitante="Almoxarifado", emitente="Almoxarifado",
                            observacao=f"Fornecedor: {forn} | {obs_nf}"
                        )
                        if ok: st.success(f"✅ **Entrada avulsa registrada!** {msg}"); time.sleep(2); st.rerun()
                        else:  st.error(f"❌ {msg}")

    # ══════════════════════════════════════════════════════════════════════════════
    # 🔄 ATUALIZAR STATUS E DADOS DA S.C. (Corrigido: Variáveis definidas antes do uso)
    # ══════════════════════════════════════════════════════════════════════════════
    with aba_ed:
        with st.container(border=True):
            st.markdown("### 🔄 Atualizar Status e Dados da S.C.")
            st.caption("Preencha as informações conforme elas chegarem (PO, Fornecedor, Previsões). O status será sugerido automaticamente.")
            
            scs_todas = listar_scs()
            if not scs_todas:
                st.info("Nenhuma SC cadastrada para atualização.")
            else:
                opc_ed = {f"SC {s['numero_sc']} — {s['status']}": s for s in scs_todas}
                sel_ed = st.selectbox("Selecionar SC", list(opc_ed.keys()), label_visibility="collapsed")
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
                    st.markdown("##### 📋 Informações Gerais (Cabeçalho)")
                    
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
                    st.markdown("##### 📦 Detalhes dos Itens (PO, Fornecedor e Previsões por Item)")
                    
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
                        
                    salv_sc = st.form_submit_button("💾 Salvar Atualizações", width="stretch", type="primary")
                    
                if salv_sc:
                    data_aprovacao_str = str(dt_aprovacao) if dt_aprovacao else None
                    
                    ok, msg = atualizar_sc(sc_ed["id"], data_aprovacao_str,
                        n_po or None, forn_final, None, st_ed, obs_ed or None,
                        itens=itens_editados)
                    
                    if ok:  
                        st.success(f"✅ **SC Atualizada!** Status definido como: `{st_ed}`")
                        time.sleep(2)
                        st.rerun()
                    else:  
                        st.error(f"❌ {msg}")
    # ══════════════════════════════════════════════════════════════════════════════
    # 📜 HISTÓRICO (Lista Limpa + Detalhes em Caption)
    # ══════════════════════════════════════════════════════════════════════════════
    
    
    with aba_h:
        with st.container(border=True):
            st.markdown("### 📜 Linha do Tempo de Recebimentos")
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
                        c_meta1.caption(f"📅 **{fmt(r['data_hora'])}**")
                        c_meta2.caption(f"🧾 **SC:** {r['numero_sc']} | **NF:** {r['documento_nf'] or '—'}")
                        c_meta3.caption(f"👤 **Recebido por:** {r['emitente']} | {r['observacao']}")
            else:
                st.info("ℹ️ Nenhum recebimento vinculado a SC encontrado no histórico.")

# ══════════════════════════════════════════════════════════════════════════════
# FEEDBACK / SUGESTÕES (Item 3 / v2.1.0)
# ══════════════════════════════════════════════════════════════════════════════
elif pagina == "💬 Feedback":
    st.title("💬 Sugestões e Feedback")
    st.caption("Ajude a evoluir o Sistema MRO: registre sugestões, problemas e ideias.")

    tab_enviar, tab_gerenciar = st.tabs(["✍️ Enviar Feedback", "🗂️ Backlog (Gestão)"])

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
                                          "Movimentações", "Requisição", "Compras (SC)",
                                          "Configurações", "Geral"], index=0)
                enviado = st.form_submit_button("📨 Enviar Feedback", type="primary", width="stretch")
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
            if st.button("💾 Salvar atualização", type="primary", key="fb_up_btn"):
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
elif pagina == "⚙️ Configurações":
    st.title("⚙️ Configurações do Sistema")
    st.caption("Gestão de Listas Mestras e Parâmetros Globais.")

    # ── Importação da base do Neidson — Tipo, Mínimo, Máximo, Lead Time (Item 1) ──
    with st.container(border=True):
        st.subheader("📥 Importar Base (Tipo/Categoria, Mínimo, Máximo, Lead Time)")
        st.caption("Atualiza itens **existentes** (casados pelo PN) com os dados apurados pelo "
                   "Sr. Neidson. PNs não encontrados são apenas relatados — nenhum item é criado. "
                   "Um backup do banco é criado automaticamente antes de aplicar.")
        arq_neidson = st.file_uploader("Planilha (.xlsx)", type=["xlsx"], key="upl_neidson")
        if arq_neidson is not None:
            if st.button("🔍 Pré-visualizar (simulação)", key="btn_prev_neidson"):
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
                    if st.button("✅ Aplicar atualização", type="primary", key="btn_apply_neidson"):
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
        "centro_custo": "💼 Centros de Custo",
        "local": "📍 Locais de Armazenagem",
        "fornecedor": "🏭 Fornecedores",
        "autorizador": "🔑 Tipos de Autorizador",
        "setor": "🏢 Setores Solicitantes" # Adicionado setor se necessário
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
                            if c_btn.button("✕", key=f"rm_{tipo_lista}_{i}", help="Remover"):
                                remover_valor_lista(tipo_lista, val)
                                st.rerun()
            else:
                st.info(f"Nenhum {titulo.split(' ')[-1].lower()} cadastrado.")

            st.divider()

            # 2. Formulário de Adição
            with st.form(f"form_add_{tipo_lista}", clear_on_submit=True):
                c_input, c_btn = st.columns([3, 1])
                novo_valor = c_input.text_input(
                    f"Adicionar novo {titulo.split(' ', 1)[1].lower()}",
                    placeholder="Digite e pressione Adicionar...",
                    label_visibility="collapsed"
                )
                submitted = c_btn.form_submit_button("➕ Adicionar", width="stretch")

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