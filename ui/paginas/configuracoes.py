"""Página Configurações (v5.0.0) — Aparência/Tema, importação da base (Tipo/Mín/Máx/
Lead Time) e gestão das Listas Mestras (centros de custo, locais, fornecedores,
autorizadores, setores).

Migrada de app.py na fundação da refatoração (F1). Comportamento idêntico ao bloco
`elif pagina == "Configurações"` anterior — mesmos widgets/`key=`. Duas mudanças de
fundação: (1) a paleta vem de `ui.tema.paleta_atual()` em vez do global `PAL`;
(2) toda escrita chama `invalidar_leituras()` (disciplina de cache — hoje inócua
porque as leituras ainda não são cacheadas; correta quando o cache ativar). É a
página que prova o caminho escrita→invalidação da refatoração.
"""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from services.db_functions import (
    importar_inventario_neidson, listar_valores,
    adicionar_valor_lista, remover_valor_lista, sincronizar_fornecedores_lista,
)
from ui.cache import invalidar_leituras
from ui.tema import paleta_atual


def render() -> None:
    pal = paleta_atual()
    st.title(":material/settings: Configurações do Sistema")
    st.caption("Gestão de Listas Mestras e Parâmetros Globais.")

    # ── Aparência / Tema (v2.11.0) ────────────────────────────────────────────
    with st.container(border=True):
        st.subheader(":material/palette: Aparência")
        _tema_txt = ":material/dark_mode: Escuro" if pal["tipo"] == "dark" else ":material/light_mode: Claro"
        st.markdown(f"**Tema atual:** {_tema_txt}  ·  **Padrão:** :material/light_mode: Claro")
        st.caption("Para alternar entre **claro** e **escuro**, use o botão **Tema** na **barra "
                   "lateral** (abaixo do menu). A escolha é lembrada ao recarregar (fica na URL). "
                   "O fundo, os textos, o menu e os gráficos acompanham. :material/warning: Observação: no modo "
                   "escuro, as **tabelas** podem continuar claras — é uma limitação do Streamlit "
                   "(as grades seguem o tema base); no modo claro (padrão) fica tudo consistente.")
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Importação da base do Neidson — Tipo, Mínimo, Máximo, Lead Time (Item 1) ──
    with st.container(border=True):
        st.subheader(":material/download: Importar Base (Tipo/Categoria, Mínimo, Máximo, Lead Time)")
        st.caption("Atualiza itens **existentes** (casados pelo PN) com os dados apurados pelo "
                   "Compras. PNs não encontrados são apenas relatados — nenhum item é criado. "
                   "Um backup do banco é criado automaticamente antes de aplicar.")
        arq_neidson = st.file_uploader("Planilha (.xlsx)", type=["xlsx"], key="upl_neidson")
        if arq_neidson is not None:
            if st.button(":material/search: Pré-visualizar (simulação)", key="btn_prev_neidson"):
                ok_p, res_p = importar_inventario_neidson(arq_neidson, arq_neidson.name, dry_run=True)
                st.session_state["prev_neidson"] = (ok_p, res_p, arq_neidson.name)

            prev = st.session_state.get("prev_neidson")
            if prev:
                ok_p, res_p, nome_p = prev
                if not ok_p:
                    st.error(res_p.get("erro", "Não foi possível ler a planilha."))
                else:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Linhas lidas", res_p["linhas_lidas"])
                    m2.metric("Serão atualizados", res_p["atualizados"])
                    m3.metric("Ignorados (PN não encontrado)", res_p["ignorados"])
                    if res_p["pns_nao_encontrados"]:
                        with st.expander(f"Ver {len(res_p['pns_nao_encontrados'])} PNs não encontrados"):
                            df_ne = pd.DataFrame({"PN não encontrado": res_p["pns_nao_encontrados"]})
                            st.dataframe(df_ne, width="stretch", hide_index=True)
                            st.download_button("⬇️ Baixar lista (CSV)",
                                               df_ne.to_csv(index=False).encode("utf-8-sig"),
                                               file_name="pns_nao_encontrados.csv", mime="text/csv",
                                               key="dl_ne")
                    if res_p["pns_duplicados_planilha"]:
                        st.warning("PNs duplicados na planilha (mantém a última ocorrência): "
                                   + ", ".join(res_p["pns_duplicados_planilha"][:20]))
                    st.warning("Confira os números acima e clique em **Aplicar** para gravar.")
                    if st.button(":material/check_circle: Aplicar atualização", type="primary", key="btn_apply_neidson"):
                        ok_a, res_a = importar_inventario_neidson(arq_neidson, nome_p, dry_run=False)
                        if ok_a:
                            st.success(f"Importação concluída — atualizados: {res_a['atualizados']} | "
                                       f"ignorados: {res_a['ignorados']}.")
                            st.session_state.pop("prev_neidson", None)
                            invalidar_leituras()
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error(res_a.get("erro", "Falha na importação."))
        st.markdown("<br>", unsafe_allow_html=True)

    # Definição das categorias de listas
    LISTAS_CONFIG = {
        "centro_custo": ":material/work: Centros de Custo",
        "local": ":material/location_on: Locais de Armazenagem",
        "fornecedor": ":material/factory: Fornecedores",
        "autorizador": ":material/key: Tipos de Autorizador",
        "setor": ":material/apartment: Setores Solicitantes"  # Adicionado setor se necessário
    }

    for tipo_lista, titulo in LISTAS_CONFIG.items():
        with st.container(border=True):
            st.subheader(titulo)

            # 1. Visualização da Lista Atual (Grid)
            valores = listar_valores(tipo_lista)

            if valores:
                # Cria colunas dinâmicas (4 por linha)
                cols = st.columns(4)
                for i, val in enumerate(valores):
                    with cols[i % 4]:
                        # Card simples para cada item
                        with st.container(border=True):
                            c_txt, c_btn = st.columns([3, 1])
                            c_txt.markdown(f"**{val}**")
                            if c_btn.button(":material/close:", key=f"rm_{tipo_lista}_{i}", help="Remover"):
                                remover_valor_lista(tipo_lista, val)
                                invalidar_leituras()
                                st.rerun()
            else:
                st.info(f"Nenhum {titulo.split(' ')[-1].lower()} cadastrado.")

            st.divider()

            # v3.3.0 — atalho: semear a lista com o cadastro mestre de fornecedores
            if tipo_lista == "fornecedor":
                if st.button(":material/sync: Sincronizar do Relatório de SCs", key="sync_forn",
                             help="Adiciona os Nomes Fantasia do cadastro mestre (importado no "
                                  "Relatório de SCs) que ainda não estão na lista."):
                    _add, _tot = sincronizar_fornecedores_lista()
                    invalidar_leituras()
                    st.success(f"{_add} fornecedor(es) adicionado(s) — {_tot} no cadastro mestre.")
                    time.sleep(1.0)
                    st.rerun()

            # 2. Formulário de Adição
            with st.form(f"form_add_{tipo_lista}", clear_on_submit=True):
                c_input, c_btn = st.columns([3, 1])
                novo_valor = c_input.text_input(
                    f"Adicionar novo {titulo.split(' ', 1)[1].lower()}",
                    placeholder="Digite e pressione Adicionar...",
                    label_visibility="collapsed"
                )
                submitted = c_btn.form_submit_button(":material/add: Adicionar", width="stretch")

                if submitted:
                    if novo_valor.strip():
                        ok, msg = adicionar_valor_lista(tipo_lista, novo_valor.strip())
                        if ok:
                            invalidar_leituras()
                            st.success(msg)
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(msg)
                    else:
                        st.warning("O campo não pode estar vazio.")
