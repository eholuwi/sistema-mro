import streamlit as st
import os, sys
from services.styles import inject_custom_css
from services.logging_config import setup_logging

sys.path.insert(0, os.path.dirname(__file__))
from database import criar_banco
from services.db_functions import tirar_snapshot_estoque, sincronizar_monitor_sc
from ui.tema import paleta_atual
from ui.sidebar import render_sidebar
from ui.router import render_pagina

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

st.set_page_config(
    page_title="MRO Inventus Power 5.8.0",
    page_icon=":material/build:",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Paleta única do tema escolhido (via ui.tema.paleta_atual) — consumida pelo CSS
# global, pelo option_menu e pelos gráficos, p/ tudo acompanhar claro/escuro (v2.11.0).
PAL = paleta_atual()
inject_custom_css(PAL)

# ── Sidebar + despacho ────────────────────────────────────────────────────────

pagina = render_sidebar()

# Todas as páginas vivem em ui/paginas/ (F4b encerrou a migração do app.py). O shell
# faz só setup + sidebar + despacho para o render da página selecionada.
render_pagina(pagina)
