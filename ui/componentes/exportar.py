"""ui/componentes/exportar.py — download de planilha (Excel/CSV) reutilizável (v5.9.0).

O bloco `BytesIO` → `pd.ExcelWriter(engine="openpyxl")` → `st.download_button` estava
copiado literalmente em quatro telas (Reposição e Cruzamento no Controle de SC, Saldo em
Estoque e Relatório de Movimentações). O Guarda-Chuva seria a quinta cópia — daí a
extração.

Convenções consolidadas do que já se praticava:
- Excel via `openpyxl` (pin do requirements) — sem formatação avançada, ninguém pediu.
- CSV em `utf-8-sig`: o BOM faz o Excel pt-BR abrir acentuação correta.
- nome do arquivo com a data do dia (`%d-%m-%Y`), salvo `sufixo` explícito.
- `key=` sempre presente: `download_button` provoca rerun (ver changelog 5.8.0).

As funções `bytes_excel`/`bytes_csv` são puras — dá para testar a planilha sem Streamlit.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_CSV = "text/csv"


def bytes_excel(df: pd.DataFrame, sheet_name: str = "Dados") -> bytes:
    """Planilha .xlsx do DataFrame, em memória."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=sheet_name[:31])  # limite do Excel
    return buf.getvalue()


def bytes_csv(df: pd.DataFrame) -> bytes:
    """CSV do DataFrame com BOM — o Excel pt-BR abre sem quebrar acento."""
    return df.to_csv(index=False).encode("utf-8-sig")


def nome_arquivo(base: str, ext: str, sufixo: str | None = None) -> str:
    """`base` + sufixo + extensão. `sufixo=None` usa a data de hoje; `""` não põe nada."""
    if sufixo is None:
        sufixo = f"_{date.today():%d-%m-%Y}"
    return f"{base}{sufixo}.{ext}"


def botoes_export(
    df: pd.DataFrame,
    nome_base: str,
    *,
    key: str,
    sheet_name: str = "Dados",
    csv: bool = True,
    label_excel: str = "⬇️ Exportar para Excel",
    label_csv: str = "⬇️ Exportar para CSV",
    help: str | None = None,
    sufixo: str | None = None,
    width: str = "content",
) -> None:
    """Desenha o(s) botão(ões) de download do `df`.

    Com `csv=True` os dois botões ficam lado a lado em duas colunas; com `csv=False`
    sai só o Excel, no container corrente (a tela decide se está numa coluna).
    DataFrame vazio não desenha nada — não há planilha para baixar.
    """
    if df is None or df.empty:
        return

    dados_xlsx = bytes_excel(df, sheet_name=sheet_name)
    alvo_excel, alvo_csv = st.columns(2) if csv else (st, None)

    alvo_excel.download_button(
        label_excel,
        data=dados_xlsx,
        file_name=nome_arquivo(nome_base, "xlsx", sufixo),
        mime=MIME_XLSX,
        key=key,
        help=help,
        width=width,
    )
    if csv and alvo_csv is not None:
        alvo_csv.download_button(
            label_csv,
            data=bytes_csv(df),
            file_name=nome_arquivo(nome_base, "csv", sufixo),
            mime=MIME_CSV,
            key=f"{key}_csv",
            width=width,
        )
