"""Guarda estática contra NOME INDEFINIDO / import faltando (v5.3.0 / F4a).

Por que existe: a F4a moveu ~2.600 linhas do `app.py` para `ui/`. Bugs do tipo
"esqueci de importar X" (`date`/`timedelta`/`_MESES_PT`/`fmt`) só estouravam quando um
ramo condicional específico rodava no app real — o `fmt` do Dashboard, por exemplo, só
é referenciado quando há Relatório de SCs importado (`ultima_atualizacao` truthy), então
nenhum smoke com banco semeado o pegava. `pyflakes` acha isso ESTATICAMENTE, sem depender
de reproduzir a condição de dado.

Escopo: só falha em `UndefinedName` (bug real). Import não usado é estilo, não quebra —
não falhamos por isso (o `app.py` ainda carrega imports órfãos a limpar no fechamento).
Skip gracioso se pyflakes não estiver instalado (é dependência só de desenvolvimento).
"""
import ast
import glob
import os

import pytest

pytest.importorskip("pyflakes", reason="pyflakes é dependência de desenvolvimento")
from pyflakes.checker import Checker  # noqa: E402
from pyflakes import messages as pfm  # noqa: E402

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _modulos():
    alvos = ["app.py"]
    alvos += glob.glob(os.path.join(_RAIZ, "ui", "**", "*.py"), recursive=True)
    # normaliza p/ caminho absoluto e remove __pycache__
    out = []
    for a in alvos:
        p = a if os.path.isabs(a) else os.path.join(_RAIZ, a)
        if "__pycache__" not in p and os.path.exists(p):
            out.append(p)
    return sorted(set(out))


def _nomes_indefinidos(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    checker = Checker(tree, filename=path)
    return [w for w in checker.messages if isinstance(w, pfm.UndefinedName)]


@pytest.mark.parametrize("modulo", _modulos(), ids=lambda p: os.path.relpath(p, _RAIZ))
def test_sem_nomes_indefinidos(modulo):
    problemas = _nomes_indefinidos(modulo)
    detalhe = "; ".join(f"L{w.lineno}: {w.message % w.message_args}" for w in problemas)
    assert not problemas, f"{os.path.relpath(modulo, _RAIZ)} — nome(s) indefinido(s): {detalhe}"
