import streamlit as st

from services.tema import paleta


def inject_custom_css(pal=None):
    """Injeta o CSS global da identidade Inventus Power, AGORA theme-aware (v2.11.0).

    Recebe a paleta de `services.tema.paleta()` e emite as variáveis do `:root` a partir
    dela; todo o restante do CSS usa `var(--...)`, então a MESMA folha serve para claro e
    escuro — basta a paleta mudar. Antes o dark ficava preso por `!important`; agora o app
    acompanha o tema ativo (☰ → Settings → Theme). `pal=None` → dark (compat)."""
    if pal is None:
        pal = paleta("dark")
    c = pal["css"]

    # Apenas o :root é gerado a partir da paleta; o corpo do CSS referencia as variáveis.
    root = f"""
        :root {{
            --primary-orange: {c['accent']};
            --primary-hover: {c['accent_hover']};
            --bg-sidebar: {c['bg_sidebar']};
            --bg-main: {c['bg_main']};
            --bg-card: {c['bg_card']};
            --bg-metric: {c['bg_metric']};
            --bg-grid: {c['bg_grid']};
            --bg-th: {c['bg_th']};
            --bg-expander: {c['bg_expander']};
            --bg-input-focus: {c['bg_input_foco']};
            --border-color: {c['borda']};
            --text-white: {c['texto']};
            --text-gray: {c['texto_suave']};
        }}
    """

    st.markdown("""
    <style>
        /* --- 1. FONTES --- */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;700&display=swap');
    """ + root + """
        /* --- 2. SIDEBAR --- */
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
            background-color: var(--bg-card) !important;
            color: var(--text-white) !important;
        }

        div[data-testid="stSidebarNav"] ul li a[aria-current="page"] {
            background-color: var(--bg-card) !important;
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
            background-color: var(--bg-grid);
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
            background-color: var(--bg-card) !important;
            border: 1px solid var(--border-color) !important;
            color: var(--text-white) !important;
        }

        /* --- 3. CORPO PRINCIPAL (MAIN) --- */

        .stApp {
            background-color: var(--bg-main);
            color: var(--text-white);
            font-family: 'Inter', sans-serif;
        }

        h1, h2, h3, h4, h5, h6 { color: var(--text-white) !important; font-weight: 700; }
        p, label, div, span, li { color: var(--text-gray); }

        /* MÉTRICAS (ST.METRIC) COMO CARDS */
        [data-testid="stMetric"] {
            background-color: var(--bg-metric) !important;
            padding: 15px !important;
            border-radius: 8px !important;
            border: 1px solid var(--border-color) !important;
            text-align: center;
            transition: all 0.2s ease !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }

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

        /* BOTÕES PRIMÁRIOS (OUTLINE LARANJA) */
        div.stButton > button[kind="primary"] {
            background-color: transparent !important;
            color: var(--primary-orange) !important;
            border: 2px solid var(--primary-orange) !important;
            border-radius: 6px !important;
            font-weight: 700 !important;
            padding: 0.5rem 1.5rem !important;
            transition: all 0.3s ease !important;
            box-shadow: none !important;
        }

        div.stButton > button[kind="primary"]:hover {
            background-color: var(--primary-orange) !important;
            color: #FFFFFF !important;
            border-color: var(--primary-orange) !important;
            transform: translateY(-2px) !important;
            box-shadow: 0 4px 12px rgba(243, 111, 33, 0.4) !important;
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

        /* INPUTS, SELECTS E TEXTAREAS */
        .stTextInput > div > div > input,
        .stNumberInput > div > div > input,
        .stSelectbox > div > div > div,
        .stTextArea > div > div > textarea,
        .stDateInput > div > div > input,
        .stMultiSelect > div > div > div {
            background-color: var(--bg-card) !important;
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
            background-color: var(--bg-input-focus) !important;
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
            background-color: var(--bg-th) !important;
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
            background-color: var(--bg-expander) !important;
            border: 1px solid var(--border-color) !important;
            border-top: none !important;
            border-radius: 0 0 6px 6px !important;
        }

    </style>
    """, unsafe_allow_html=True)
