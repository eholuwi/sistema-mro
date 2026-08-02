import streamlit as st
import os, sys
from services.constants import VERSAO
from services.styles import inject_custom_css
from services.logging_config import setup_logging

sys.path.insert(0, os.path.dirname(__file__))
from database import criar_banco
from services.db_functions import tirar_snapshot_estoque, sincronizar_monitor_sc
from services.usuarios import semear_usuarios
from ui.auth import gate
from ui.tema import paleta_atual
from ui.sidebar import render_sidebar
from ui.router import render_pagina

setup_logging()
criar_banco()

# v6.1.0 — usuários a partir dos Solicitantes MRO + papéis manuais. Idempotente: no 1º
# render cria as linhas, nas demais aberturas é um SELECT e nenhum INSERT. Fora do
# try/except de propósito — igual a `criar_banco()`: falhar aqui é problema de banco, e
# engolir o erro entregaria um sistema de acesso silenciosamente vazio.
semear_usuarios()

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
    page_title=f"MRO Inventus Power {VERSAO}",
    page_icon=":material/build:",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Paleta única do tema escolhido (via ui.tema.paleta_atual) — consumida pelo CSS
# global, pelo option_menu e pelos gráficos, p/ tudo acompanhar claro/escuro (v2.11.0).
PAL = paleta_atual()
inject_custom_css(PAL)

# ── Gate de acesso + sidebar + despacho ───────────────────────────────────────

# v6.1.0 — trava SÓ quando a flag `exigir_login` está ligada e não há sessão. Roda ANTES
# da sidebar para que o menu não apareça a quem ainda não entrou; com a flag desligada
# (padrão) é no-op e o app abre exatamente como na v6.0.0.
gate()

pagina = render_sidebar()

# Todas as páginas vivem em ui/paginas/ (F4b encerrou a migração do app.py). O shell
# faz só setup + sidebar + despacho para o render da página selecionada.
render_pagina(pagina)
