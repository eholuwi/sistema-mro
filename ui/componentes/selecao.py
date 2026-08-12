"""ui/componentes/selecao.py — seleção de material reutilizável (v5.3.0 / F4a).

Extraído do topo do `app.py` (F1 adiou p/ F4). `sel_material` é o selectbox de item
usado por várias telas (Saldo em Estoque, Cadastro de Itens, Movimentação, Ficha 360,
Controle de SC) — vive aqui num único lugar para não duplicar.

Leitura direta de `listar_inventario()` (SEM cache): o helper é compartilhado por
páginas ainda inline no app.py (Movimentação/Ficha 360) cujas escritas ainda não
foram pareadas com `invalidar_leituras()`. A ativação de cache das telas migradas é
feita no read da própria página (ex.: `inventario_cached()`), não neste selectbox.
"""

from __future__ import annotations

from typing import Iterable

import streamlit as st

from services.db_functions import listar_inventario


def rotulo_item(item, incluir_descricao=False):
    """Rótulo do item no selectbox: `"<PN> — <nome>"` (+ ` · <descrição>` opcional).

    Fonte única do rótulo (v5.9.0): quem precisa reapontar a seleção depois de
    alterar o item — o Part Number, por exemplo — monta a chave nova por aqui em vez
    de repetir a concatenação e correr o risco de divergir de `itens_select`."""
    rotulo = f"{item['part_number']} — {item['nome_item']}"
    if incluir_descricao:
        desc = (item.get("descricao") or "").strip()
        if desc and desc.lower() not in (item.get("nome_item") or "").lower():
            rotulo += f" · {desc}"
    return rotulo


def itens_select(incluir_descricao=False):
    """Dicionário `"<PN> — <nome>" -> item` de todo o inventário (fonte do selectbox).

    Com `incluir_descricao=True` o rótulo ganha ` · <descrição>` quando a descrição
    acrescenta informação ao nome — assim o type-ahead nativo do selectbox também
    encontra o item pela descrição, sem precisar de um campo de busca separado."""
    return {rotulo_item(i, incluir_descricao=incluir_descricao): i for i in listar_inventario()}


def sel_material(label, key, placeholder=" ", incluir_descricao=False):
    """Selectbox com opção vazia no topo para forçar seleção consciente.

    `incluir_descricao` repassa para `itens_select` (busca também pela descrição).
    Devolve `(rotulo_selecionado, item_dict_ou_None, opcoes_dict)`."""
    opcoes = itens_select(incluir_descricao=incluir_descricao)
    lista = [placeholder] + list(opcoes.keys())
    sel = st.selectbox(label, lista, index=0, key=key)
    item = opcoes.get(sel) if sel != placeholder else None
    return sel, item, opcoes


def resetar_campos_ao_trocar(chave_controle: str, identidade, campos: Iterable[str]) -> None:
    """Limpa `campos` do `session_state` quando o item selecionado muda (v5.9.0).

    Num formulário "escolhe item → mostra os campos do item", widgets com `key=` fixo
    NÃO se atualizam ao trocar de item: quando há `key`, o Streamlit toma a key como
    identidade principal do widget e descarta `options`/`index`/`value` do cálculo do
    id (`key_as_main_identity` em `streamlit/elements/lib/utils.py`). O `index=`/`value=`
    só vale na 1ª renderização — nas seguintes o valor vem do `session_state`, ou seja,
    do item ANTERIOR. Isso não é cosmético: o formulário grava os dados do item A no
    item B.

    Chamar isto ANTES de desenhar os widgets devolve a identidade ao item selecionado,
    sem remover as keys (que continuam necessárias: as duas abas da tela usam widgets
    de mesmo rótulo/opções e, sem key, colidiriam em `StreamlitDuplicateElementId`).

    ⚠️ **Prefira pendurar o id do item na própria key** (ver `gerenciar_itens.k_ed`,
    v6.5.1). Este helper tem uma corrida que a suíte não pega: a limpeza acontece antes
    dos widgets serem desenhados e o Streamlit cancela a execução em curso quando chega
    uma nova interação — se ela morre nessa janela, a trava já diz "não mudou", o
    navegador devolve os valores antigos e o formulário trava no item anterior até um
    F5. Com o id na key, item diferente é widget diferente e não há janela nenhuma."""
    if st.session_state.get(chave_controle) != identidade:
        st.session_state[chave_controle] = identidade
        for campo in campos:
            st.session_state.pop(campo, None)


def opcoes_com_atual(base, atual):
    """Garante que o valor atual (ex.: tipo livre vindo da base do Neidson) apareça
    na lista de opções, evitando que o selectbox troque silenciosamente o valor."""
    opcoes = list(base)
    if atual and atual not in opcoes:
        opcoes = [atual] + opcoes
    return opcoes
