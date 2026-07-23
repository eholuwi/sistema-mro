"""ui/componentes/status.py — indicadores de origem e disponibilidade (v5.2.0 / F3).

Pequenos helpers visuais da página SCM Integrado: um "badge" da fonte do dado
(API do SCM × Relatório Excel) e o ponto de status da API (health-check com cache
curto, para não bater na rede a cada rerun).
"""
from __future__ import annotations

import streamlit as st

from services import scm_client
from ui.formatos import fmt


def badge_origem(origem, quando=None):
    """String markdown com a fonte do dado. `origem` = 'api_scm' | 'excel' | outro;
    `quando` (ISO) vira data/hora legível. Ex.: '🟢 API do SCM · 16/07/2026 11:33'."""
    o = (origem or "").strip().lower()
    if o == "api_scm":
        rotulo = ":green[:material/cloud_done: API do SCM]"
    elif o == "excel":
        rotulo = ":blue[:material/description: Relatório (Excel)]"
    else:
        rotulo = ":gray[:material/help: origem não registrada]"
    if quando:
        rotulo += f" · {fmt(quando)}"
    return rotulo


@st.cache_data(ttl=60, show_spinner=False)
def _api_disponivel_cached():
    """`esta_disponivel()` com cache de 60s — evita health-check a cada rerun."""
    return scm_client.esta_disponivel()


def ponto_status_api(mostrar=True):
    """Verifica (com cache) se a API do SCM responde. Se `mostrar`, escreve um
    indicador colorido. Retorna o booleano."""
    ok = _api_disponivel_cached()
    if mostrar:
        if ok:
            st.markdown(":green[:material/sensors: **API do SCM online**]")
        else:
            st.markdown(":red[:material/sensors_off: **API do SCM offline**] "
                        "— exibindo apenas dados do banco.")
    return ok
