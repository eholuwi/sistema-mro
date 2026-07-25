"""Formatação PT-BR (v5.0.0) — datas para exibição e para widgets.

Helpers sem estado extraídos de app.py na fundação da refatoração (F1). Puros
(dependem só de datetime), reusáveis por qualquer página do pacote ui/.
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
