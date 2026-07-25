"""ui/componentes/graficos.py — vocabulário visual dos gráficos (v5.3.0 / F4a).

Extraído do `app.py` (a F1 adiou p/ a F4). Reúne os construtores de gráfico Plotly
no padrão da marca (`_barh`/`_donut`/`_barv`/`_linhas`/`_barras_agrupadas`), o bloco
de ranking `_bloco_top` e os formatadores de rótulo (`_mes_label`/`_brl_compact`).

Compartilhado: além do Dashboard, `_barv` e `_mes_label` são usados pela Ficha 360 e
pela Movimentação (ainda inline no app.py, migram na F4b) — por isso vivem aqui.

IMPORTANTE (paleta): cada função busca a paleta com `paleta_atual()` NA CHAMADA, e não
de um global capturado no import — assim o gráfico acompanha a troca de tema claro/escuro.
"""

from __future__ import annotations

import streamlit as st

from ui.tema import paleta_atual

_MESES_PT = ["", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _mes_label(ym):
    """'2026-07' → 'jul/26' (rótulo curto pt-BR para eixos de gráfico)."""
    try:
        a, m = str(ym).split("-")[:2]
        return f"{_MESES_PT[int(m)]}/{a[2:]}"
    except (ValueError, IndexError):
        return str(ym)


def _brl_compact(v):
    """R$ compacto p/ rótulo de barra: 18800 → 'R$ 18,8k'; 1250000 → 'R$ 1,3M'."""
    try:
        v = float(v)
    except (ValueError, TypeError):
        return "R$ —"
    if abs(v) >= 1_000_000:
        return f"R$ {v / 1_000_000:.1f}M".replace(".", ",")
    if abs(v) >= 1_000:
        return f"R$ {v / 1_000:.1f}k".replace(".", ",")
    return f"R$ {v:.0f}"


# Paleta de série p/ donuts (laranja da marca → tons de apoio).
_SERIE_CORES = [
    "#F36F21",
    "#F7941E",
    "#FFB65C",
    "#6C7A89",
    "#8E44AD",
    "#2E86C1",
    "#27AE60",
    "#C0392B",
    "#B3B3B3",
]


def _barh(labels, values, textos, cor=None, height=300, label_outside=False):
    """Gráfico de barras horizontais (ranking). `labels`/`values`/`textos` já na ordem
    de exibição (maior no topo = último da lista, convenção do Plotly horizontal).
    `label_outside=True` põe o rótulo FORA da barra — evita número girado/minúsculo em
    barras curtas (ex.: contagens pequenas de Setores em demanda aberta). v4.1.0."""
    import plotly.graph_objects as go

    PAL = paleta_atual()
    fig = go.Figure(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker=dict(color=cor or PAL["accent"], line=dict(width=1, color=PAL["accent_borda"])),
            text=textos,
            textposition="outside" if label_outside else "auto",
            cliponaxis=not label_outside,
            textfont=dict(size=15, color=PAL["texto"]),
            hoverinfo="skip",
        )
    )
    fig.update_layout(
        template=PAL["plotly_template"],
        height=height,
        margin=dict(l=0, r=44 if label_outside else 16, t=6, b=0),
        paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"],
        showlegend=False,
        font=dict(family="Inter", color=PAL["texto"]),
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, tickfont=dict(size=13, color=PAL["texto"])),
    )
    return fig


def _donut(labels, values, height=300, fmt=None):
    """Donut de composição com legenda e % nas fatias."""
    import plotly.graph_objects as go

    PAL = paleta_atual()
    txt = [(fmt(v) if fmt else str(v)) for v in values]
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.58,
            sort=False,
            marker=dict(
                colors=_SERIE_CORES[: len(labels)] or None, line=dict(color=PAL["paper_bg"], width=1)
            ),
            textinfo="percent",
            textfont=dict(size=11, color="#111"),
            customdata=txt,
            hovertemplate="%{label}: %{customdata} (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        template=PAL["plotly_template"],
        height=height,
        margin=dict(l=0, r=0, t=6, b=0),
        paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"],
        font=dict(family="Inter", color=PAL["texto"], size=11),
        legend=dict(orientation="v", x=1, y=0.5, font=dict(size=10)),
    )
    return fig


def _barv(labels, values, textos=None, cor=None, height=280):
    """Barras verticais temáticas (categorias/tempo) — espelha `_barh` p/ telas que só
    precisam de um bar chart no padrão da marca (Ficha 360 etc.). v3.3.0."""
    import plotly.graph_objects as go

    PAL = paleta_atual()
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker=dict(color=cor or PAL["accent"], line=dict(width=1, color=PAL["accent_borda"])),
            text=textos if textos is not None else values,
            textposition="outside",
            textfont=dict(size=11, color=PAL["texto"]),
            hoverinfo="skip",
            cliponaxis=False,
        )
    )
    fig.update_layout(
        template=PAL["plotly_template"],
        height=height,
        margin=dict(l=0, r=8, t=18, b=0),
        paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"],
        showlegend=False,
        font=dict(family="Inter", color=PAL["texto"]),
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=11, color=PAL["texto"])),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
    )
    return fig


def _linhas(x, series, height=260):
    """Gráfico de linhas multi-série (WK/tempo). series = [(nome, valores, cor)]. v3.5.0."""
    import plotly.graph_objects as go

    PAL = paleta_atual()
    fig = go.Figure()
    for nome, vals, cor in series:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=vals,
                name=nome,
                mode="lines+markers",
                line=dict(color=cor, width=2),
                marker=dict(size=5),
            )
        )
    fig.update_layout(
        template=PAL["plotly_template"],
        height=height,
        margin=dict(l=0, r=8, t=10, b=0),
        paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"],
        font=dict(family="Inter", color=PAL["texto"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=11)),
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=PAL["texto"])),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=10, color=PAL["texto"])),
    )
    return fig


def _barras_agrupadas(x, series, height=260, mostrar_valores=False):
    """Barras verticais agrupadas. series = [(nome, valores, cor)]. v3.5.0.
    `mostrar_valores=True` escreve a quantidade em cima de cada barra — evita depender do
    hover (ex.: Histórico mensal Entradas × Saídas). v4.1.0."""
    import plotly.graph_objects as go

    PAL = paleta_atual()
    fig = go.Figure()
    for nome, vals, cor in series:
        fig.add_trace(
            go.Bar(
                x=x,
                y=vals,
                name=nome,
                marker_color=cor,
                text=[f"{v:g}" for v in vals] if mostrar_valores else None,
                textposition="outside" if mostrar_valores else "none",
                textfont=dict(size=11, color=PAL["texto"]),
                cliponaxis=False,
            )
        )
    fig.update_layout(
        barmode="group",
        template=PAL["plotly_template"],
        height=height,
        margin=dict(l=0, r=8, t=18 if mostrar_valores else 10, b=0),
        paper_bgcolor=PAL["paper_bg"],
        plot_bgcolor=PAL["plot_bg"],
        font=dict(family="Inter", color=PAL["texto"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=11)),
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=PAL["texto"])),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
    )
    return fig


def _bloco_top(
    titulo, itens, label_fn, value_key, value_fmt, cor=None, height=300, caption=None, label_outside=False
):
    """Renderiza um card com um ranking Top N em barras horizontais (maior no topo).
    `label_outside=True` põe os números fora das barras (bom p/ contagens pequenas)."""
    with st.container(border=True):
        st.markdown(f"#### {titulo}")
        if caption:
            st.caption(caption)
        if not itens:
            st.caption("Sem dados para o período.")
            return
        labels = [label_fn(x) for x in itens][::-1]
        values = [x[value_key] for x in itens][::-1]
        textos = [value_fmt(x[value_key]) for x in itens][::-1]
        st.plotly_chart(
            _barh(labels, values, textos, cor, height, label_outside),
            width="stretch",
            config={"displayModeBar": False},
        )
