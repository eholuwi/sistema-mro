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

from services.db_functions import listar_inventario, listar_scs


@st.cache_data(ttl=120, show_spinner=False)
def inventario_cached():
    """`listar_inventario()` com cache curto — leitura mais quente (sidebar + telas)."""
    return listar_inventario()


@st.cache_data(ttl=120, show_spinner=False)
def scs_cached(apenas_abertas: bool = True):
    """`listar_scs()` com cache curto (contagem de SCs abertas na sidebar etc.)."""
    return listar_scs(apenas_abertas=apenas_abertas)


def invalidar_leituras() -> None:
    """Limpa o cache de leituras. Chamar após TODA escrita (movimentação, SC, config…)."""
    st.cache_data.clear()
