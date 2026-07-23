"""ui/componentes/selecao.py — seleção de material reutilizável (v5.3.0 / F4a).

Extraído do topo do `app.py` (F1 adiou p/ F4). `sel_material` é o selectbox de item
usado por várias telas (Saldo em Estoque, Gerenciar Itens, Movimentação, Ficha 360,
Controle de SC) — vive aqui num único lugar para não duplicar.

Leitura direta de `listar_inventario()` (SEM cache): o helper é compartilhado por
páginas ainda inline no app.py (Movimentação/Ficha 360) cujas escritas ainda não
foram pareadas com `invalidar_leituras()`. A ativação de cache das telas migradas é
feita no read da própria página (ex.: `inventario_cached()`), não neste selectbox.
"""
from __future__ import annotations

import streamlit as st

from services.db_functions import listar_inventario


def itens_select():
    """Dicionário `"<PN> — <nome>" -> item` de todo o inventário (fonte do selectbox)."""
    return {f"{i['part_number']} — {i['nome_item']}": i for i in listar_inventario()}


def sel_material(label, key, placeholder=" "):
    """Selectbox com opção vazia no topo para forçar seleção consciente.

    Devolve `(rotulo_selecionado, item_dict_ou_None, opcoes_dict)`."""
    opcoes = itens_select()
    lista = [placeholder] + list(opcoes.keys())
    sel = st.selectbox(label, lista, index=0, key=key)
    item = opcoes.get(sel) if sel != placeholder else None
    return sel, item, opcoes


def opcoes_com_atual(base, atual):
    """Garante que o valor atual (ex.: tipo livre vindo da base do Neidson) apareça
    na lista de opções, evitando que o selectbox troque silenciosamente o valor."""
    opcoes = list(base)
    if atual and atual not in opcoes:
        opcoes = [atual] + opcoes
    return opcoes
