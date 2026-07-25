"""Página Ajuda (v5.0.0) — Central de Ajuda: guias por perfil, Manual do Sistema
(tela a tela), canal de feedback e backlog.

Migrada de app.py na fundação da refatoração (F1). Comportamento idêntico ao bloco
`elif pagina == "Ajuda"` anterior — mesmos widgets e mesmas `key=` (preservar chaves
mantém o estado da sessão e não quebra os smokes). Reusa o conteúdo em
services.ajuda_conteudo e o feedback já existente em services.db_functions.
"""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from services.ajuda_conteudo import GUIAS_PERSONA, MANUAL
from services.db_functions import (
    registrar_feedback,
    listar_feedbacks,
    atualizar_feedback,
)
from ui.formatos import fmt

# Constantes do canal de feedback — usadas só aqui (vieram de app.py).
TIPOS_FEEDBACK = [
    "Sugestão de melhoria",
    "Nova funcionalidade",
    "Melhoria de design",
    "Melhoria de UI",
    "Melhoria de UX",
    "Relato de bug",
    "Relato de glitch",
    "Problema operacional",
    "Outra observação",
]
STATUS_FEEDBACK = ["Novo", "Em análise", "Planejado", "Em andamento", "Concluído", "Recusado"]


def render() -> None:
    st.title(":material/help: Central de Ajuda")
    st.caption(
        "Guias por perfil, o **Manual do Sistema** (tela a tela) e o canal de feedback. "
        ":material/lightbulb: Tema claro/escuro: botão **Tema** na barra lateral."
    )

    tab_inicio, tab_manual, tab_enviar, tab_gerenciar = st.tabs(
        [
            ":material/rocket_launch: Começar aqui",
            ":material/menu_book: Manual do Sistema",
            ":material/edit: Enviar Feedback",
            ":material/folder: Backlog",
        ]
    )

    with tab_inicio:
        st.caption(
            "Guias rápidos por perfil. Para o detalhe de cada botão/card/gráfico, veja a "
            "aba **:material/menu_book: Manual do Sistema**."
        )
        _perfil = st.radio(
            "Qual é o seu perfil?",
            ["Assistente de Materiais (almoxarifado)", "Comprador"],
            horizontal=True,
            key="ajuda_perfil",
        )
        _chave = "assistente" if _perfil.startswith("Assistente") else "comprador"
        st.markdown(GUIAS_PERSONA[_chave])

    with tab_manual:
        st.caption(
            "Explica **cada elemento** da interface: para que serve · com base em quê · "
            "como o sistema calcula. Ligue o modo abaixo para uma explicação bem simples."
        )
        _eli5 = st.toggle(
            "Explicar em linguagem simples",
            value=False,
            key="ajuda_eli5",
            help="Reescreve tudo em linguagem simples — ótimo para entender os cálculos e os dashboards.",
        )
        _busca_manual = st.text_input(
            ":material/search: Filtrar por palavra (opcional)",
            key="ajuda_busca",
            placeholder="ex.: cobertura, ABC, conversão, saldo residual",
        )
        _b = (_busca_manual or "").strip().lower()
        for _sec in MANUAL:
            _itens = _sec["itens"]
            if _b:
                _itens = [
                    it
                    for it in _itens
                    if _b
                    in (
                        it["nome"] + it["para_que"] + it["base"] + it["como"] + it["crianca"] + _sec["tela"]
                    ).lower()
                ]
            if not _itens:
                continue
            st.subheader(_sec["tela"])
            if _sec.get("intro"):
                st.caption(_sec["intro"])
            for _it in _itens:
                with st.expander(_it["nome"]):
                    if _eli5:
                        st.markdown(f" {_it['crianca']}")
                    else:
                        st.markdown(f"**Para que serve:** {_it['para_que']}")
                        st.markdown(f"**Com base em quê:** {_it['base']}")
                        st.markdown(f"**Como o sistema faz:** {_it['como']}")

    with tab_enviar:
        with st.container(border=True):
            with st.form("form_feedback", clear_on_submit=True):
                c1, c2 = st.columns(2)
                fb_tipo = c1.selectbox("Tipo *", TIPOS_FEEDBACK, index=0)
                fb_autor = c2.text_input("Seu nome (opcional)", placeholder="Ex: Luis Oliveira")
                fb_titulo = st.text_input("Título *", placeholder="Resuma em uma frase")
                fb_desc = st.text_area(
                    "Descrição",
                    height=120,
                    placeholder="Descreva a sugestão, o problema ou a ideia em detalhes...",
                )
                fb_pagina = st.selectbox(
                    "Página/área relacionada (opcional)",
                    [
                        "—",
                        "Dashboard",
                        "Saldo em Estoque",
                        "Gerenciar Itens",
                        "Movimentação",
                        "Controle de SC",
                        "Configurações",
                        "Geral",
                    ],
                    index=0,
                )
                enviado = st.form_submit_button(
                    ":material/mail: Enviar Feedback", type="primary", width="stretch"
                )
                if enviado:
                    ok, msg = registrar_feedback(
                        fb_tipo,
                        fb_titulo,
                        fb_desc,
                        autor=(fb_autor or None),
                        pagina_origem=(None if fb_pagina == "—" else fb_pagina),
                    )
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    with tab_gerenciar:
        f1, f2 = st.columns(2)
        filtro_tipo = f1.selectbox("Filtrar por tipo", ["Todos"] + TIPOS_FEEDBACK, index=0, key="fb_f_tipo")
        filtro_status = f2.selectbox(
            "Filtrar por status", ["Todos"] + STATUS_FEEDBACK, index=0, key="fb_f_status"
        )
        feedbacks = listar_feedbacks(tipo=filtro_tipo, status=filtro_status)

        if not feedbacks:
            st.info("Nenhum feedback encontrado com os filtros atuais.")
        else:
            df_fb = pd.DataFrame(
                [
                    {
                        "Data": fmt(f["data_hora"]),
                        "Tipo": f["tipo"],
                        "Título": f["titulo"],
                        "Status": f["status"],
                        "Prioridade": f.get("prioridade") or "—",
                        "Autor": f.get("autor") or "—",
                        "Página": f.get("pagina_origem") or "—",
                        "Descrição": f.get("descricao") or "",
                    }
                    for f in feedbacks
                ]
            )
            st.download_button(
                "⬇️ Exportar backlog (CSV)",
                df_fb.to_csv(index=False).encode("utf-8-sig"),
                file_name="feedback_backlog.csv",
                mime="text/csv",
            )
            st.dataframe(df_fb, width="stretch", hide_index=True)

            st.divider()
            st.markdown("##### Atualizar um feedback")
            mapa_fb = {f"#{f['id']} — [{f['tipo']}] {f['titulo']}": f for f in feedbacks}
            escolha_fb = st.selectbox("Selecione", list(mapa_fb.keys()), key="fb_sel")
            fb = mapa_fb[escolha_fb]
            u1, u2 = st.columns(2)
            novo_status = u1.selectbox(
                "Status",
                STATUS_FEEDBACK,
                index=STATUS_FEEDBACK.index(fb["status"]) if fb["status"] in STATUS_FEEDBACK else 0,
                key="fb_up_status",
            )
            nova_prio = u2.selectbox(
                "Prioridade",
                ["—", "Baixa", "Média", "Alta", "Crítica"],
                index=(
                    ["—", "Baixa", "Média", "Alta", "Crítica"].index(fb["prioridade"])
                    if fb.get("prioridade") in ["Baixa", "Média", "Alta", "Crítica"]
                    else 0
                ),
                key="fb_up_prio",
            )
            resposta = st.text_area(
                "Resposta / nota interna", value=fb.get("resposta") or "", key="fb_up_resp"
            )
            if st.button(":material/save: Salvar atualização", type="primary", key="fb_up_btn"):
                ok, msg = atualizar_feedback(
                    fb["id"],
                    status=novo_status,
                    prioridade=(None if nova_prio == "—" else nova_prio),
                    resposta=resposta,
                )
                if ok:
                    st.success(msg)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)
