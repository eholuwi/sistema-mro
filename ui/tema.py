"""Tema da UI (v5.0.0) — leitura da paleta do tema escolhido pelo usuário.

Ponto único, no lado da UI, para "qual é o tema agora". O tipo ('light'/'dark') é
lido da URL (?tema=) para persistir ao recarregar — o Streamlit 1.57 não troca o tema
por código, então o próprio app o controla (a sidebar grava `?tema=` e o topo do
script reaplica a paleta). A paleta em si é PURA (services.tema.paleta); aqui só
juntamos "ler a escolha" + "montar a paleta".

`paleta_atual()` pode ser chamada várias vezes por rerun sem custo relevante — a
função só monta um dict de tokens a partir de constantes.
"""

from __future__ import annotations

import streamlit as st

from services.tema import paleta


def tema_atual() -> str:
    """'light' | 'dark' — escolha do usuário lida da URL (?tema=). Padrão: claro."""
    try:
        v = st.query_params.get("tema", "light")
    except Exception:
        v = "light"
    return "dark" if v == "dark" else "light"


def paleta_atual() -> dict:
    """Paleta completa do tema atual (ver services.tema.paleta para as chaves)."""
    return paleta(tema_atual())
