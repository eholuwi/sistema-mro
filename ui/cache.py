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

from services.db_functions import (
    listar_inventario,
    listar_scs,
    obter_dados_dashboard,
    exportar_inventario_df,
    obter_analitico_divergencias,
    obter_analitico_rupturas,
)
from services.dashboards import (
    montar_dashboard,
    montar_visao_compras_mro,
    montar_visao_almoxarifado,
)


@st.cache_data(ttl=120, show_spinner=False)
def inventario_cached(incluir_inativos: bool = False):
    """`listar_inventario()` com cache curto — leitura mais quente (sidebar + telas).

    v6.8.0 — o parâmetro entra na CHAVE do `@st.cache_data`, então a visão com inativos
    e a sem inativos não se contaminam. Sem ele no argumento, a primeira chamada da
    sessão decidiria o conteúdo das duas pelos 120s seguintes.
    """
    return listar_inventario(incluir_inativos=incluir_inativos)


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


# ── Blocos herdados da Movimentação (v6.0.0) ─────────────────────────────────
# Tendência de consumo, Top capital parado, Maior valor em estoque, Divergências e
# Ruptura saíram da aba Dashboard da Movimentação e passaram ao Almoxarifado — a página
# mais visitada. Sem cache, `exportar_inventario_df()` (giro + valoração POR ITEM) seria
# recalculado a cada rerun da página inteira; por isso entram aqui, não no call site.


@st.cache_data(ttl=120, show_spinner=False)
def inventario_indicadores_cached():
    """`exportar_inventario_df()` com cache curto — o DF largo (giro, valoração,
    tendência) que alimenta 3 blocos do Almoxarifado de uma só passada."""
    return exportar_inventario_df()


@st.cache_data(ttl=120, show_spinner=False)
def divergencias_cached(days: int = 90):
    """`obter_analitico_divergencias()` com cache curto (Top itens com divergências)."""
    return obter_analitico_divergencias(days=days)


@st.cache_data(ttl=120, show_spinner=False)
def rupturas_cached(days: int = 90):
    """`obter_analitico_rupturas()` com cache curto (Ruptura de estoque)."""
    return obter_analitico_rupturas(days=days)


def invalidar_leituras() -> None:
    """Limpa o cache de leituras. Chamar após TODA escrita (movimentação, SC, config…)."""
    st.cache_data.clear()
