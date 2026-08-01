"""Formatação PT-BR (v5.0.0) — datas e valores para exibição e para widgets.

Helpers sem estado extraídos de app.py na fundação da refatoração (F1). Puros
(dependem só de datetime), reusáveis por qualquer página do pacote ui/.

v6.0.0 — os formatadores MONETÁRIOS passaram a morar aqui. Antes coexistiam três
padrões na UI: `_dash_fmt_brl` (privado do Dashboard, já correto), `_brl_compact`
(rótulo curto de gráfico, segue em `ui/componentes/graficos.py`) e f-strings cruas
`f"R$ {v:,.2f}"`, que imprimem no padrão AMERICANO ("R$ 1,234.56"). `fmt_moeda` é a
fonte única; `fmt_brl` é o atalho para BRL.
"""

from __future__ import annotations

from datetime import date, datetime


def fmt(s):
    """Data/datetime 'YYYY-...' → 'dd/mm/aaaa[ HH:MM]' para exibição; '—' se vazio."""
    if not s:
        return "—"
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        try:
            return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            return s


def fmt_date_input(s):
    """String 'YYYY-MM-DD' → date para st.date_input; hoje se vazio/inválido."""
    if not s:
        return date.today()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return date.today()


# ── Valores monetários (v6.0.0) ───────────────────────────────────────────────


def fmt_num(v, casas=2):
    """Número no padrão pt-BR: 12345.67 → '12.345,67'. '—' se não for numérico.

    Troca os separadores do format americano do Python sem depender do `locale` do
    servidor (que no Windows/servidor da operação não vem em pt_BR)."""
    try:
        bruto = f"{float(v):,.{casas}f}"
    except (ValueError, TypeError):
        return "—"
    return bruto.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_moeda(v, moeda="R$"):
    """Valor monetário no padrão pt-BR, com a moeda informada: 'R$ 12.345,67'.

    `moeda` aceita tanto o símbolo ('R$') quanto o código que vem do banco
    ('BRL'/'USD'), porque a Ficha 360 exibe a moeda da valoração do item."""
    n = fmt_num(v)
    return f"{moeda or 'R$'} {n}"


def fmt_brl(v):
    """Valor em reais no padrão pt-BR: 12345.67 → 'R$ 12.345,67'; '—' se inválido."""
    return fmt_moeda(v, "R$")


def colunas_brl(df, *colunas):
    """Converte colunas de valor de um DataFrame para TEXTO pt-BR. Altera `df` no
    lugar e o devolve (passe uma cópia se o original ainda for usado).

    Existe porque o `st.column_config.NumberColumn(format="R$ %.2f")` imprime
    "R$ 1234.56" — sem separador de milhar e com ponto decimal. Colunas ausentes são
    ignoradas. **Não usar em `st.data_editor`**: lá o valor precisa seguir numérico
    para ser editável (ex.: "Preço congelado" do Guarda-Chuva)."""
    for c in colunas:
        if c in df.columns:
            df[c] = df[c].map(fmt_brl)
    return df
