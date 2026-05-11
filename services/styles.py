import streamlit as st

def inject_custom_css():
    """
    Injeta CSS para identidade visual Inventus Power v2.0.1 - Dark Industrial Premium
    
    PRESERVADO:
    - Sidebar Escura (#050505) com Ícones Laranjas e Métricas em Grid.
    
    RESTAURADO/ADICIONADO:
    - Corpo Principal Dark (#0E0E0E).
    - Cards de Métrica (st.metric) com fundo #121212, borda sutil e hover laranja.
    - Botões Primários Laranjas (#F36F21).
    - Inputs com fundo escuro (#1A1A1A) e foco laranja.
    """
    st.markdown("""
    <style>
        /* --- 1. FONTES E VARIÁVEIS GLOBAIS --- */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;700&display=swap');

        :root {
            --primary-orange: #F36F21;
            --primary-hover: #d65a12;
            --bg-sidebar: #050505;
            --bg-main: #0E0E0E;
            --bg-card: #1A1A1A;
            --bg-metric: #121212; /* Cor específica para métricas */
            --border-color: #2A2A2A;
            --text-white: #FFFFFF;
            --text-gray: #B3B3B3;
        }

        /* --- 2. SIDEBAR (MANTIDA CONFORME APROVADO) --- */
        section[data-testid="stSidebar"] {
            background-color: var(--bg-sidebar) !important;
            border-right: 1px solid var(--border-color);
            width: 280px !important;
        }

        .sidebar-title {
            font-family: 'Inter', sans-serif;
            font-weight: 700;
            font-size: 1.5rem;
            color: var(--text-white);
            margin-bottom: 2rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .sidebar-title span { color: var(--primary-orange); }

        div[data-testid="stSidebarNav"] ul li a {
            background-color: transparent !important;
            color: var(--text-gray) !important;
            font-family: 'Inter', sans-serif;
            font-weight: 500;
            padding: 12px 15px !important;
            margin: 2px 0 !important;
            border-radius: 6px;
            transition: all 0.2s ease;
        }

        div[data-testid="stSidebarNav"] ul li a:hover {
            background-color: #1A1A1A !important;
            color: var(--text-white) !important;
        }

        div[data-testid="stSidebarNav"] ul li a[aria-current="page"] {
            background-color: #1A1A1A !important;
            color: var(--text-white) !important;
            border-left: 4px solid var(--primary-orange);
            font-weight: 600;
        }

        .sidebar-metrics-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 20px;
            margin-bottom: 20px;
            padding: 10px;
            background-color: #0A0A0A;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }

        .metric-card { text-align: left; padding: 5px; }
        .metric-label { font-size: 0.8rem; color: var(--text-gray); font-family: 'Inter', sans-serif; display: flex; align-items: center; gap: 5px; }
        .metric-value { font-size: 1.8rem; font-weight: 700; color: var(--text-white); font-family: 'JetBrains Mono', monospace; margin-top: 5px; }
        .dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; }
        .dot-yellow { background-color: #FFC107; }
        .dot-red { background-color: #FF4444; }

        .progress-container { margin-top: 10px; margin-bottom: 20px; }
        .progress-label { font-size: 0.9rem; color: var(--text-gray); margin-bottom: 5px; }

        .user-profile {
            display: flex; align-items: center; gap: 12px; padding: 15px 10px;
            border-top: 1px solid var(--border-color); margin-top: auto;
        }
        .user-avatar { width: 40px; height: 40px; border-radius: 50%; object-fit: cover; border: 2px solid var(--border-color); }
        .user-info h4 { margin: 0; font-size: 0.95rem; color: var(--text-white); font-weight: 600; }
        .user-info p { margin: 0; font-size: 0.8rem; color: var(--primary-orange); font-weight: 500; }

        section[data-testid="stSidebar"] input, 
        section[data-testid="stSidebar"] select,
        section[data-testid="stSidebar"] textarea {
            background-color: #1A1A1A !important;
            border: 1px solid var(--border-color) !important;
            color: white !important;
        }

        /* --- 3. CORPO PRINCIPAL (MAIN) --- */
        
        .stApp {
            background-color: var(--bg-main);
            color: var(--text-white);
            font-family: 'Inter', sans-serif;
        }

        h1, h2, h3, h4, h5, h6 { color: var(--text-white) !important; font-weight: 700; }
        p, label, div, span, li { color: var(--text-gray); }

        /* ✅ MÉTRICAS (ST.METRIC) ESTILIZADAS COMO CARDS */
        [data-testid="stMetric"] {
            background-color: var(--bg-metric) !important; /* #121212 */
            padding: 15px !important;
            border-radius: 8px !important;
            border: 1px solid var(--border-color) !important; /* Borda sutil */
            text-align: center;
            transition: all 0.2s ease !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }

        /* Hover da Métrica: Borda Laranja e leve elevação */
        [data-testid="stMetric"]:hover {
            border-color: var(--primary-orange) !important;
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(243, 111, 33, 0.15);
        }

        [data-testid="stMetricLabel"] {
            color: var(--text-gray) !important;
            font-size: 0.9rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        [data-testid="stMetricValue"] {
            color: var(--text-white) !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-weight: 700;
            font-size: 1.8rem;
        }

        [data-testid="stMetricDelta"] {
            font-family: 'Inter', sans-serif;
            font-weight: 600;
        }

        /* ✅ BOTÕES PRIMÁRIOS (ESTILO OUTLINE/CONTORNO) */
        div.stButton > button[kind="primary"] {
            background-color: transparent !important; /* Fundo transparente */
            color: var(--primary-orange) !important; /* Letra Laranja */
            border: 2px solid var(--primary-orange) !important; /* Borda Laranja */
            border-radius: 6px !important;
            font-weight: 700 !important;
            padding: 0.5rem 1.5rem !important;
            transition: all 0.3s ease !important; /* Transição suave */
            box-shadow: none !important;
        }

        /* HOVER: Fundo Laranja Sólido, Letra Branca */
        div.stButton > button[kind="primary"]:hover {
            background-color: var(--primary-orange) !important;
            color: #FFFFFF !important;
            border-color: var(--primary-orange) !important;
            transform: translateY(-2px) !important;
            box-shadow: 0 4px 12px rgba(243, 111, 33, 0.4) !important; /* Sombra laranja ao passar o mouse */
        }

        div.stButton > button[kind="secondary"] {
            background-color: transparent !important;
            border: 1px solid var(--border-color) !important;
            color: var(--text-gray) !important;
        }

        div.stButton > button[kind="secondary"]:hover {
            background-color: var(--bg-card) !important;
            border-color: var(--text-white) !important;
            color: var(--text-white) !important;
        }

        /* ✅ INPUTS, SELECTS E TEXTAREAS NO CORPO PRINCIPAL */
        .stTextInput > div > div > input,
        .stNumberInput > div > div > input,
        .stSelectbox > div > div > div,
        .stTextArea > div > div > textarea,
        .stDateInput > div > div > input,
        .stMultiSelect > div > div > div {
            background-color: var(--bg-card) !important; /* #1A1A1A */
            border: 1px solid var(--border-color) !important;
            color: var(--text-white) !important;
            border-radius: 6px !important;
            transition: all 0.2s ease !important;
        }

        .stTextInput > div > div > input:focus,
        .stNumberInput > div > div > input:focus,
        .stSelectbox > div > div > div:focus-within,
        .stTextArea > div > div > textarea:focus,
        .stDateInput > div > div > input:focus,
        .stMultiSelect > div > div > div:focus-within {
            border-color: var(--primary-orange) !important;
            box-shadow: 0 0 0 1px var(--primary-orange) !important;
            background-color: #222222 !important;
        }

        .stTextInput label, 
        .stNumberInput label, 
        .stSelectbox label, 
        .stTextArea label,
        .stDateInput label,
        .stMultiSelect label {
            color: var(--text-gray) !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.5px !important;
        }

        /* --- 4. DATAFRAMES E TABELAS --- */
        .dataframe {
            background-color: var(--bg-card) !important;
            color: var(--text-gray) !important;
            border-radius: 8px !important;
            overflow: hidden !important;
        }
        
        .dataframe th {
            background-color: #252525 !important;
            color: var(--text-white) !important;
            border-bottom: 2px solid var(--border-color) !important;
        }
        
        .dataframe td {
            border-bottom: 1px solid var(--border-color) !important;
            color: var(--text-gray) !important;
        }

        /* --- 5. EXPANDERS --- */
        .streamlit-expanderHeader {
            background-color: var(--bg-card) !important;
            color: var(--text-white) !important;
            border: 1px solid var(--border-color) !important;
            border-radius: 6px !important;
        }
        
        .streamlit-expanderContent {
            background-color: #121212 !important;
            border: 1px solid var(--border-color) !important;
            border-top: none !important;
            border-radius: 0 0 6px 6px !important;
        }

    </style>
    """, unsafe_allow_html=True)