"""Router da UI (v5.0.0) — fonte única do menu e do despacho de páginas.

`ROTAS` mapeia o rótulo do menu → `Rota(icone, render)`. A sidebar monta o menu a
partir daqui (ordem e ícones), e o app despacha `render_pagina(pagina)` para as
páginas já migradas para ui/paginas/. Páginas ainda não migradas têm `render=None`
e seguem no if/elif do app.py durante a refatoração faseada — ver `ROTAS_MIGRADAS`.

Adicionar/mover um item de menu é uma edição só aqui (não mais em dois pontos do
app.py). Os ícones são os nomes do streamlit-option-menu (Bootstrap Icons).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ui.paginas import ajuda, configuracoes, scm_integrado


@dataclass(frozen=True)
class Rota:
    icone: str
    render: Optional[Callable[[], None]] = None  # None = ainda inline no app.py


# Ordem = ordem do menu lateral. NÃO reordenar sem intenção (muda a navegação).
ROTAS: dict[str, Rota] = {
    "Dashboard":        Rota("bar-chart-fill"),          # inline no app.py (migra na F4)
    "Saldo em Estoque": Rota("box-seam"),                # inline (F4)
    "Ficha 360":        Rota("card-image"),              # inline (F4b)
    "Gerenciar Itens":  Rota("plus-circle"),             # inline (F4)
    "Movimentação":     Rota("arrow-repeat"),            # inline (F4b)
    "Controle de SC":   Rota("receipt"),                 # inline (F4)
    "SCM Integrado":    Rota("cloud-check", scm_integrado.render),   # F3 — consulta unificada
    "Ajuda":            Rota("question-circle", ajuda.render),
    "Configurações":    Rota("gear", configuracoes.render),
}

# Páginas cujo render já vive em ui/paginas/ (as demais seguem no if/elif do app.py).
ROTAS_MIGRADAS: frozenset[str] = frozenset(n for n, r in ROTAS.items() if r.render is not None)


def opcoes_menu() -> list[str]:
    """Rótulos das páginas, na ordem do menu."""
    return list(ROTAS.keys())


def icones_menu() -> list[str]:
    """Ícones (Bootstrap) das páginas, na mesma ordem de `opcoes_menu()`."""
    return [r.icone for r in ROTAS.values()]


def render_pagina(nome: str) -> None:
    """Despacha para o render da página migrada. Erra se a página não estiver migrada
    (o app.py só deve chamar isto quando `nome in ROTAS_MIGRADAS`)."""
    rota = ROTAS.get(nome)
    if rota is None or rota.render is None:
        raise KeyError(f"Página sem render migrado no router: {nome!r}")
    rota.render()
