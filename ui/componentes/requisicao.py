"""ui/componentes/requisicao.py — pedaços de tela comuns às requisições (v6.4.0).

Nasceu quando a **Portaria** e a tela do **Gestor** passaram a mostrar a mesma coisa: os
itens de uma requisição, com o solicitado ao lado do entregue. A Portaria já tinha a
tabela; a v6.4.0 deu ao gestor o "Ver requisição completa" (ele precisa saber o que está
sendo pedido antes de aprovar ou devolver). Copiar a tabela deixaria duas telas mostrando
o mesmo dado com formatação que diverge na primeira alteração.

Só formatação — nenhuma regra de negócio e nenhuma escrita.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

COLUNAS_ITENS = {
    "part_number": "PN",
    "nome_item": "Material",
    "unidade": "Un.",
    "quantidade_solicitada": st.column_config.NumberColumn("Solicitado", format="%.0f"),
    "quantidade_atendida": st.column_config.NumberColumn("Entregue", format="%.0f"),
}


def tabela_itens_requisicao(itens, vazio="Requisição sem itens registrados."):
    """Itens da requisição (shape de `listar_itens_requisicao`). Devolve os pendentes —
    os que ainda não saíram por completo — para quem chama decidir o que dizer sobre eles
    (a Portaria avisa a guarita; o Gestor não precisa)."""
    if not itens:
        st.caption(vazio)
        return []
    df = pd.DataFrame(itens).reindex(columns=list(COLUNAS_ITENS))
    st.dataframe(df, width="stretch", hide_index=True, column_config=COLUNAS_ITENS)
    return [i for i in itens if float(i["quantidade_atendida"] or 0) < float(i["quantidade_solicitada"] or 0)]


def aviso_rejeicao(req, para_requisitante=False):
    """Faixa de "devolvida para ajuste", quando a requisição carrega uma rejeição do gestor.

    Aparece na Portaria, na fila do gestor e nos pedidos do requisitante — o mesmo fato
    contado para três públicos, daí só a virada de texto. Requisição já reenviada mostra
    a rejeição como histórico (ela voltou para a fila), e não como pendência."""
    if not req.get("rejeitado_em"):
        return False
    # `reenviado_em` não-nulo já significa "voltou depois da última rejeição" — quem
    # rejeita zera o campo. Ver `DEVOLVIDA_WHERE` em `services/db_functions.py`.
    reenviada = bool(req.get("reenviado_em"))
    motivo = req.get("motivo_rejeicao") or "—"
    quem = req.get("rejeitado_por") or "—"
    if reenviada:
        st.caption(
            f":material/history: Devolvida por **{quem}** em {req['rejeitado_em']} "
            f"(motivo: {motivo}) e reenviada em {req['reenviado_em']}."
        )
        return True
    if para_requisitante:
        st.warning(
            f":material/assignment_return: **Devolvida para ajuste** por {quem} em "
            f"{req['rejeitado_em']}.\n\n**Motivo:** {motivo}\n\nCorrija os itens abaixo e "
            "reenvie para a aprovação."
        )
    else:
        st.warning(
            f":material/assignment_return: **Devolvida ao requisitante** por {quem} em "
            f"{req['rejeitado_em']} — motivo: {motivo}"
        )
    return True
