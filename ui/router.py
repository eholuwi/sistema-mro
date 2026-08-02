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

from ui.paginas import (
    configuracoes,
    controle_sc,
    dashboard,
    ficha_360,
    gerenciar_itens,
    movimentacao,
    saldo_estoque,
)


@dataclass(frozen=True)
class Rota:
    icone: str
    render: Optional[Callable[[], None]] = None  # None = ainda inline no app.py


# Ordem = ordem do menu lateral. NÃO reordenar sem intenção (muda a navegação).
# v6.0.0 — o menu caiu de 9 para 7 itens (refatoração de UX): **SCM Integrado** virou
# aba de Controle de SC e **Ajuda** virou aba de Configurações. As telas não sumiram —
# `scm_integrado.conteudo()` e `ajuda.conteudo()` são chamadas pelas abas que as hospedam.
ROTAS: dict[str, Rota] = {
    "Dashboard": Rota("bar-chart-fill", dashboard.render),  # F4a
    "Saldo em Estoque": Rota("box-seam", saldo_estoque.render),  # F4a
    "Ficha 360": Rota("card-image", ficha_360.render),  # F4b
    "Cadastro de Itens": Rota("plus-circle", gerenciar_itens.render),  # F4a (renomeado na v5.9.0)
    "Movimentação": Rota("arrow-repeat", movimentacao.render),  # F4b
    "Controle de SC": Rota("receipt", controle_sc.render),  # F4a
    "Configurações": Rota("gear", configuracoes.render),
}

# Páginas cujo render já vive em ui/paginas/ (as demais seguem no if/elif do app.py).
ROTAS_MIGRADAS: frozenset[str] = frozenset(n for n, r in ROTAS.items() if r.render is not None)

# v6.1.0 — o que cada papel enxerga no menu. Vive AQUI e não em `services/usuarios.py`
# porque nome de rota é conceito de UI (services/* não conhece a navegação); o módulo de
# domínio conhece só os papéis.
#
# "O que o comprador vê" foi definido pelo Luis (01/08/2026): ele planeja e acompanha,
# não movimenta estoque nem administra o sistema — daí a ausência de Movimentação e
# Configurações. Requisitante/gestor/portaria ficam SEM rota nesta fase: as telas deles
# são a próxima fase, e dar acesso às telas do almoxarife enquanto isso seria pior que
# não ter acesso nenhum.
ROTAS_POR_PAPEL: dict[str, frozenset[str]] = {
    "almoxarife": frozenset(ROTAS.keys()),
    "comprador": frozenset(
        {"Dashboard", "Saldo em Estoque", "Ficha 360", "Cadastro de Itens", "Controle de SC"}
    ),
    "requisitante": frozenset(),
    "gestor": frozenset(),
    "portaria": frozenset(),
}


def opcoes_menu(papel: str | None = None) -> list[str]:
    """Rótulos das páginas, na ordem do menu, filtrados pelo papel.

    `papel=None` devolve TUDO — é o comportamento pré-v6.1.0 e o que vale com a flag
    `exigir_login` desligada (ninguém logado, app aberto como sempre foi).
    Papel desconhecido devolve lista vazia (nega por omissão, em vez de liberar tudo).
    """
    if papel is None:
        return list(ROTAS.keys())
    permitidas = ROTAS_POR_PAPEL.get(papel, frozenset())
    return [nome for nome in ROTAS if nome in permitidas]


def icones_menu(papel: str | None = None) -> list[str]:
    """Ícones (Bootstrap) das páginas, na mesma ordem de `opcoes_menu(papel)`."""
    return [ROTAS[nome].icone for nome in opcoes_menu(papel)]


def render_pagina(nome: str) -> None:
    """Despacha para o render da página migrada. Erra se a página não estiver migrada
    (o app.py só deve chamar isto quando `nome in ROTAS_MIGRADAS`)."""
    rota = ROTAS.get(nome)
    if rota is None or rota.render is None:
        raise KeyError(f"Página sem render migrado no router: {nome!r}")
    rota.render()
