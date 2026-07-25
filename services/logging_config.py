"""Infraestrutura minima de logging (Fase 4.1 / F4-06).

Centraliza a configuracao do logging padrao do Python para que as mensagens dos
modulos que usam logging.getLogger(__name__) sejam exibidas com formato
consistente. Deve ser chamada uma unica vez no ponto de entrada da aplicacao
(app.py) ou da CLI (database.py). E idempotente."""

import logging

_configured = False


def setup_logging(level=logging.INFO):
    """Configura o logging raiz uma unica vez (idempotente)."""
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    _configured = True
