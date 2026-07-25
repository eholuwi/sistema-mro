"""ui/componentes/filtros.py — barra de filtros reutilizável (v5.2.0 / F3).

Uma barra de filtros para tabelas: pesquisa livre (case/acento-insensível), "pills"
de filtros rápidos (predicados nomeados) e um expander de filtros avançados
(período por data, multiselect por coluna). A lógica de FILTRAGEM é pura (funções
`_filtrar_*`), testável sem Streamlit; `barra_filtros` só desenha os widgets e
encadeia essas funções sobre o DataFrame.

Contrato:
- `filtros_rapidos`: dict[rótulo -> callable(df) -> máscara booleana]. Multi-seleção;
  combinados por AND (cada pill escolhido estreita mais).
- `avancados`: dict opcional com:
    "periodo": (rótulo, coluna_de_data)
    "multiselect": [(rótulo, coluna), ...]
Estado por widget fica em `st.session_state` sob o prefixo `chave`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from services.db_functions import _normalizar_txt


# ── Filtragem pura (sem Streamlit) ────────────────────────────────────────────


def _filtrar_texto(df, campos_pesquisa, termo):
    """Mantém linhas em que o termo (normalizado) aparece em QUALQUER dos campos.
    Termo vazio → df inalterado. Robusto a colunas ausentes."""
    termo = _normalizar_txt(termo)
    if not termo or df.empty:
        return df
    campos = [c for c in campos_pesquisa if c in df.columns]
    if not campos:
        return df
    mask = pd.Series(False, index=df.index)
    for c in campos:
        col_norm = df[c].map(lambda v: _normalizar_txt("" if v is None else str(v)))
        mask = mask | col_norm.str.contains(termo, regex=False, na=False)
    return df[mask]


def _aplicar_pills(df, filtros_rapidos, selecionados):
    """Aplica os predicados dos pills selecionados, combinados por AND. Predicado
    inválido/erro é ignorado (não derruba a barra)."""
    if df.empty or not selecionados:
        return df
    out = df
    for rotulo in selecionados:
        pred = (filtros_rapidos or {}).get(rotulo)
        if pred is None:
            continue
        try:
            mask = pred(out)
            out = out[mask]
        except Exception:
            continue
    return out


def _filtrar_periodo(df, coluna, ini, fim):
    """Mantém linhas cuja data (ISO, 10 primeiros chars) está em [ini, fim]. Limites
    None não restringem aquele lado. Datas não parseáveis são descartadas quando há
    qualquer limite."""
    if df.empty or coluna not in df.columns or (ini is None and fim is None):
        return df
    datas = pd.to_datetime(df[coluna].astype(str).str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
    mask = pd.Series(True, index=df.index)
    if ini is not None:
        mask &= datas >= pd.Timestamp(ini)
    if fim is not None:
        mask &= datas <= pd.Timestamp(fim)
    return df[mask.fillna(False)]


def _filtrar_multiselect(df, coluna, valores):
    """Mantém linhas cujo valor da coluna está entre os `valores`. Lista vazia → df
    inalterado (sem seleção = sem filtro)."""
    if df.empty or not valores or coluna not in df.columns:
        return df
    return df[df[coluna].isin(valores)]


# ── Barra de filtros (Streamlit) ──────────────────────────────────────────────


def barra_filtros(df, chave, campos_pesquisa, filtros_rapidos=None, avancados=None):
    """Desenha a barra e devolve o DataFrame filtrado. `chave` isola o estado dos
    widgets (prefixo em session_state)."""
    if df is None or df.empty:
        st.caption("Sem dados para filtrar.")
        return df

    termo = st.text_input(
        "Pesquisar", key=f"{chave}__busca", placeholder="Digite parte do texto…", label_visibility="collapsed"
    )

    selecionados = []
    if filtros_rapidos:
        selecionados = (
            st.pills(
                "Filtros rápidos",
                options=list(filtros_rapidos.keys()),
                selection_mode="multi",
                key=f"{chave}__pills",
                label_visibility="collapsed",
            )
            or []
        )

    filtrado = _filtrar_texto(df, campos_pesquisa, termo)
    filtrado = _aplicar_pills(filtrado, filtros_rapidos, selecionados)

    if avancados:
        with st.expander(":material/tune: Filtros avançados"):
            periodo = avancados.get("periodo")
            if periodo:
                rotulo, coluna = periodo
                intervalo = st.date_input(rotulo, value=(), key=f"{chave}__periodo", format="DD/MM/YYYY")
                if isinstance(intervalo, (tuple, list)) and len(intervalo) == 2:
                    filtrado = _filtrar_periodo(filtrado, coluna, intervalo[0], intervalo[1])

            for rotulo, coluna in avancados.get("multiselect") or []:
                if coluna not in df.columns:
                    continue
                opcoes = sorted({str(v) for v in df[coluna].dropna().tolist() if str(v).strip()})
                if not opcoes:
                    continue
                escolhidos = st.multiselect(rotulo, opcoes, key=f"{chave}__ms_{coluna}")
                if escolhidos:
                    filtrado = filtrado[filtrado[coluna].astype(str).isin(escolhidos)]

    st.caption(f"{len(filtrado)} de {len(df)} registro(s).")
    return filtrado
