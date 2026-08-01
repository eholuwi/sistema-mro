import streamlit as st

from services.tema import paleta


def inject_custom_css(pal=None):
    """Injeta o CSS global da identidade Inventus Power, theme-aware (v4.0.0 — redesign).

    Recebe a paleta de `services.tema.paleta()` e emite as variáveis do `:root` a partir
    dela; todo o restante do CSS usa `var(--...)`, então a MESMA folha serve para claro e
    escuro — basta a paleta mudar. Padrão CLARO (v4.0.0). `pal=None` → light (compat)."""
    if pal is None:
        pal = paleta("light")
    c = pal["css"]

    # Apenas o :root é gerado a partir da paleta; o corpo do CSS referencia as variáveis.
    root = f"""
        :root {{
            --primary-orange: {c["accent"]};
            --primary-hover: {c["accent_hover"]};
            --accent-tint: {c["accent_tint"]};
            --bg-sidebar: {c["bg_sidebar"]};
            --bg-main: {c["bg_main"]};
            --bg-card: {c["bg_card"]};
            --bg-metric: {c["bg_metric"]};
            --bg-grid: {c["bg_grid"]};
            --bg-th: {c["bg_th"]};
            --bg-expander: {c["bg_expander"]};
            --bg-input-focus: {c["bg_input_foco"]};
            --border-color: {c["borda"]};
            --text-white: {c["texto"]};
            --text-gray: {c["texto_suave"]};
            --shadow: {c["shadow"]};
            --shadow-lg: {c["shadow_lg"]};
            --positive: {c["positivo"]};
            --negative: {c["negativo"]};
            --warning: {c["atencao"]};
            --radius: {c["raio"]};
            --accent-glow: {c["accent_glow"]};
        }}
    """

    st.markdown(
        """
    <style>
        /* --- 1. FONTES --- */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');
    """
        + root
        + """
        /* --- 2. SIDEBAR --- */
        section[data-testid="stSidebar"] {
            background-color: var(--bg-sidebar) !important;
            border-right: 1px solid var(--border-color);
            width: 288px !important;
        }

        .sidebar-title {
            font-family: 'Inter', sans-serif;
            font-weight: 800;
            font-size: 1.4rem;
            letter-spacing: -0.02em;
            color: var(--text-white);
            margin-bottom: 1.5rem;
            display: flex;
            align-items: baseline;
            gap: 8px;
        }

        .sidebar-title span { color: var(--primary-orange); }

        /* Grade de KPIs da sidebar — tiles individuais */
        .sidebar-metrics-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin: 12px 0 18px;
        }

        .metric-card {
            text-align: left;
            padding: 11px 12px;
            background-color: var(--bg-grid);
            border: 1px solid var(--border-color);
            border-radius: 10px;
        }
        .metric-label { font-size: 0.72rem; color: var(--text-gray); font-family: 'Inter', sans-serif; font-weight: 600; letter-spacing: 0.3px; display: flex; align-items: center; gap: 6px; }
        .metric-value { font-size: 1.5rem; font-weight: 700; color: var(--text-white); font-family: 'JetBrains Mono', monospace; margin-top: 4px; letter-spacing: -0.02em; }
        .dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; }
        .dot-yellow { background-color: var(--warning); }
        .dot-red { background-color: var(--negative); }

        .progress-container { margin: 6px 0 4px; }
        .progress-label { font-size: 0.78rem; color: var(--text-gray); font-weight: 600; letter-spacing: 0.3px; margin-bottom: 6px; }

        .user-profile {
            display: flex; align-items: center; gap: 12px; padding: 14px 4px 4px;
            border-top: 1px solid var(--border-color); margin-top: 12px;
        }
        .user-avatar { width: 40px; height: 40px; border-radius: 50%; object-fit: cover; border: 2px solid var(--border-color); }
        .user-info h4 { margin: 0; font-size: 0.92rem; color: var(--text-white); font-weight: 600; }
        .user-info p { margin: 0; font-size: 0.78rem; color: var(--primary-orange); font-weight: 600; }

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

        h1, h2, h3, h4, h5, h6 { color: var(--text-white) !important; font-weight: 700; letter-spacing: -0.01em; }
        h1 { font-weight: 800; }
        p, label, div, span, li { color: var(--text-gray); }

        /* MÉTRICAS (ST.METRIC) COMO CARDS */
        [data-testid="stMetric"] {
            background-color: var(--bg-metric) !important;
            padding: 16px 18px !important;
            border-radius: var(--radius) !important;
            border: 1px solid var(--border-color) !important;
            box-shadow: var(--shadow);
            transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease !important;
        }

        [data-testid="stMetric"]:hover {
            border-color: var(--primary-orange) !important;
            transform: translateY(-2px);
            box-shadow: var(--shadow-lg);
        }

        [data-testid="stMetricLabel"] {
            color: var(--text-gray) !important;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.6px;
        }

        [data-testid="stMetricValue"] {
            color: var(--text-white) !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-weight: 700;
            font-size: 1.7rem;
            letter-spacing: -0.02em;
        }

        [data-testid="stMetricDelta"] {
            font-family: 'Inter', sans-serif;
            font-weight: 600;
        }

        /* CONTÊINERES COM BORDA (st.container(border=True)) COMO CARDS */
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: var(--radius) !important;
            box-shadow: var(--shadow);
        }

        /* BOTÕES PRIMÁRIOS (SÓLIDO LARANJA) */
        div.stButton > button[kind="primary"] {
            background-color: var(--primary-orange) !important;
            color: #FFFFFF !important;
            border: 1px solid var(--primary-orange) !important;
            border-radius: 8px !important;
            font-weight: 700 !important;
            padding: 0.5rem 1.4rem !important;
            box-shadow: 0 1px 2px var(--accent-glow) !important;
            transition: all 0.15s ease !important;
        }

        div.stButton > button[kind="primary"]:hover {
            background-color: var(--primary-hover) !important;
            border-color: var(--primary-hover) !important;
            transform: translateY(-1px) !important;
            box-shadow: var(--shadow-lg) !important;
        }

        div.stButton > button[kind="secondary"] {
            background-color: transparent !important;
            border: 1px solid var(--border-color) !important;
            color: var(--text-gray) !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
        }

        div.stButton > button[kind="secondary"]:hover {
            background-color: var(--bg-card) !important;
            border-color: var(--text-gray) !important;
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
            border-radius: 8px !important;
            transition: all 0.15s ease !important;
        }

        .stTextInput > div > div > input:focus,
        .stNumberInput > div > div > input:focus,
        .stSelectbox > div > div > div:focus-within,
        .stTextArea > div > div > textarea:focus,
        .stDateInput > div > div > input:focus,
        .stMultiSelect > div > div > div:focus-within {
            border-color: var(--primary-orange) !important;
            box-shadow: 0 0 0 3px var(--accent-tint) !important;
            background-color: var(--bg-input-focus) !important;
        }

        .stTextInput label,
        .stNumberInput label,
        .stSelectbox label,
        .stTextArea label,
        .stDateInput label,
        .stMultiSelect label {
            color: var(--text-gray) !important;
            font-size: 0.75rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.5px !important;
        }

        /* --- 4. DATAFRAMES E TABELAS --- */
        .dataframe {
            background-color: var(--bg-card) !important;
            color: var(--text-gray) !important;
            border-radius: 10px !important;
            overflow: hidden !important;
        }

        .dataframe th {
            background-color: var(--bg-th) !important;
            color: var(--text-white) !important;
            border-bottom: 1px solid var(--border-color) !important;
            text-transform: uppercase;
            font-size: 0.72rem;
            letter-spacing: 0.4px;
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
            border-radius: 8px !important;
        }

        .streamlit-expanderContent {
            background-color: var(--bg-expander) !important;
            border: 1px solid var(--border-color) !important;
            border-top: none !important;
            border-radius: 0 0 8px 8px !important;
        }

    </style>
    """,
        unsafe_allow_html=True,
    )
