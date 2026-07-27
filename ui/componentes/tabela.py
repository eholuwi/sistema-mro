"""ui/componentes/tabela.py — tabela paginada com seleção de linha (v5.2.0 / F3).

`tabela_paginada` desenha um `st.dataframe` com `column_config` PT-BR, paginação
manual (fatia + botões) e, opcionalmente, seleção de linha única para navegação
(clique → devolve a linha). A fatia/paginação é pura (`_paginar`), testável sem
Streamlit.
"""

from __future__ import annotations

import hashlib
import math

import streamlit as st


def chave_editor(prefixo, *partes):
    """Chave de `st.data_editor` versionada pela identidade dos dados que ele edita.

    v5.6.0 — No Streamlit 1.60.0, um `data_editor` com `key` e `num_rows="fixed"` passou
    a ter identidade baseada na ASSINATURA DO SCHEMA (colunas, tipos, nº de linhas) e
    **não nos valores** — "This keeps edits alive across pure value changes"
    (`streamlit/elements/widgets/data_editor.py`). Com uma `key` fixa, as edições do
    usuário sobrevivem a mudanças de conteúdo e são reaplicadas sobre dados que já não
    são os mesmos: no recebimento por SC/PO o parcial nunca andava, e na sugestão de
    reposição os checkboxes vazavam entre conjuntos filtrados de mesmo tamanho.

    Passe em `partes` o que identifica o conteúdo (id da SC, geração, PNs filtrados);
    quando qualquer uma mudar, o editor renasce limpo. Partes longas são resumidas em
    hash curto para a chave não crescer sem limite.
    """
    fatias = []
    for p in partes:
        texto = "-".join(str(x) for x in p) if isinstance(p, (list, tuple, set, frozenset)) else str(p)
        if len(texto) > 32:
            texto = hashlib.blake2s(texto.encode("utf-8"), digest_size=8).hexdigest()
        fatias.append(texto)
    return "__".join([prefixo, *fatias])


def _paginar(df, pagina, page_size):
    """Devolve (fatia, total_paginas, pagina_corrigida). Página fora do intervalo é
    ajustada; page_size<=0 desliga a paginação (fatia = df inteiro)."""
    n = len(df)
    if page_size <= 0 or n == 0:
        return df, 1, 0
    total = max(1, math.ceil(n / page_size))
    pagina = max(0, min(pagina, total - 1))
    ini = pagina * page_size
    return df.iloc[ini : ini + page_size], total, pagina


def tabela_paginada(df, chave, colunas_config=None, page_size=50, ordenar_padrao=None, on_select=None):
    """Renderiza a tabela e devolve a linha selecionada (dict) ou None.

    - `colunas_config`: dict p/ `st.dataframe(column_config=...)` (rótulos PT-BR).
    - `ordenar_padrao`: (coluna, ascending) aplicada antes de paginar.
    - `on_select`: se dado, ativa seleção de linha única; ao clicar, chama
      `on_select(linha_dict)` e também devolve a linha."""
    if df is None or df.empty:
        st.info("Nenhum registro para exibir.")
        return None

    dados = df
    if ordenar_padrao:
        col, asc = ordenar_padrao
        if col in dados.columns:
            dados = dados.sort_values(col, ascending=asc, kind="stable")

    pag_key = f"{chave}__pagina"
    pagina = st.session_state.get(pag_key, 0)
    fatia, total_paginas, pagina = _paginar(dados, pagina, page_size)
    st.session_state[pag_key] = pagina

    kwargs = dict(width="stretch", hide_index=True)
    if colunas_config:
        kwargs["column_config"] = colunas_config
    if on_select is not None:
        kwargs["on_select"] = "rerun"
        kwargs["selection_mode"] = "single-row"
        kwargs["key"] = f"{chave}__tabela"

    evento = st.dataframe(fatia.reset_index(drop=True), **kwargs)

    if total_paginas > 1:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            if st.button(
                ":material/chevron_left: Anterior",
                key=f"{chave}__prev",
                disabled=pagina <= 0,
                width="stretch",
            ):
                st.session_state[pag_key] = pagina - 1
                st.rerun()
        with c2:
            st.markdown(
                f"<div style='text-align:center;padding-top:6px;'>Página "
                f"<b>{pagina + 1}</b> de <b>{total_paginas}</b></div>",
                unsafe_allow_html=True,
            )
        with c3:
            if st.button(
                "Próxima :material/chevron_right:",
                key=f"{chave}__next",
                disabled=pagina >= total_paginas - 1,
                width="stretch",
            ):
                st.session_state[pag_key] = pagina + 1
                st.rerun()

    if on_select is not None:
        linhas = getattr(getattr(evento, "selection", None), "rows", None) or []
        if linhas:
            linha = fatia.reset_index(drop=True).iloc[linhas[0]].to_dict()
            on_select(linha)
            return linha
    return None
