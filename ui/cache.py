"""Camada fina de cache de leituras (v5.0.0).

`services/db_functions.py` permanece PURO (sem `@st.cache_data`) — é a camada baixa,
testável sem Streamlit. Aqui ficam wrappers com cache curto (ttl=120s) sobre as
leituras chamadas a cada rerun; toda ESCRITA deve chamar `invalidar_leituras()` para
não exibir dado velho (o TTL é só a rede de segurança).

Regra: só cachear retornos serializáveis de forma estável — as funções da camada de
serviço já devolvem list[dict]/int (nunca sqlite3.Row).

Estado da adoção (F1): o módulo nasce aqui como infraestrutura. A ATIVAÇÃO nos
call sites (sidebar e páginas) é progressiva e pareada com `invalidar_leituras()` em
cada caminho de escrita — evita servir estoque desatualizado enquanto as páginas
ainda não migraram. Ver docs/PLANO_V5_EVOLUCAO.md (F1 passo 5, F4).
"""
from __future__ import annotations

import streamlit as st

from services.db_functions import listar_inventario, listar_scs, obter_dados_dashboard
from services.dashboards import (
    montar_dashboard, montar_visao_compras_mro, montar_visao_almoxarifado,
)


@st.cache_data(ttl=120, show_spinner=False)
def inventario_cached():
    """`listar_inventario()` com cache curto — leitura mais quente (sidebar + telas)."""
    return listar_inventario()


@st.cache_data(ttl=120, show_spinner=False)
def scs_cached(apenas_abertas: bool = True):
    """`listar_scs()` com cache curto (contagem de SCs abertas na sidebar etc.)."""
    return listar_scs(apenas_abertas=apenas_abertas)


# ── Assemblers do Dashboard (v5.3.0 / F4a) ───────────────────────────────────
# São as leituras mais CARAS do app (varrem inventário/movimentações/SCs para montar
# os view models). Ficavam sem cache e rodavam a cada rerun das 3 abas do Dashboard.
# Os assemblers seguem PUROS em services/dashboards.py; o cache vive só aqui.

@st.cache_data(ttl=120, show_spinner=False)
def dashboard_cached(publico: str):
    """`montar_dashboard(publico)` com cache curto (aba Comprador/Gestão/Mensal)."""
    return montar_dashboard(publico)


@st.cache_data(ttl=120, show_spinner=False)
def visao_compras_cached():
    """`montar_visao_compras_mro()` com cache curto (aba Comprador)."""
    return montar_visao_compras_mro()


@st.cache_data(ttl=120, show_spinner=False)
def visao_almoxarifado_cached():
    """`montar_visao_almoxarifado()` com cache curto (aba Almoxarifado)."""
    return montar_visao_almoxarifado()


@st.cache_data(ttl=120, show_spinner=False)
def dados_dashboard_cached():
    """`obter_dados_dashboard()` com cache curto (distribuição/Top 10 do Almoxarifado)."""
    return obter_dados_dashboard()


def invalidar_leituras() -> None:
    """Limpa o cache de leituras. Chamar após TODA escrita (movimentação, SC, config…)."""
    st.cache_data.clear()
