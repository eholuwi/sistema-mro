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

import os
import time

import pandas as pd
import streamlit as st

from services.db_functions import (
    importar_inventario_neidson,
    listar_valores,
    adicionar_valor_lista,
    remover_valor_lista,
    sincronizar_fornecedores_lista,
    listar_solicitantes_mro,
    marcar_solicitante_mro,
    definir_codigo_solicitante_mro,
)
from services import scm_sync
from services import backup
from services import usuarios as U
from ui.cache import invalidar_leituras
from ui.paginas import ajuda
from ui.tema import paleta_atual


def render() -> None:
    """Configurações em 7 abas (v6.1.0 — entrou **Usuários**). Antes da v6.0.0 eram 8
    blocos empilhados num scroll só; cada seção virou uma aba, as 5 Listas Mestras foram
    agrupadas em uma, e a Central de Ajuda entrou como aba (deixou de ser item do menu)."""
    st.title(":material/settings: Configurações do Sistema")
    st.caption("Parâmetros globais, usuários, listas mestras, backup e a Central de Ajuda.")

    aba_apar, aba_usr, aba_bkp, aba_imp, aba_sol, aba_listas, aba_ajuda = st.tabs(
        [
            ":material/palette: Aparência",
            ":material/group: Usuários",
            ":material/backup: Backup",
            ":material/download: Importar Base",
            ":material/badge: Solicitantes MRO",
            ":material/list: Listas Mestras",
            ":material/help: Ajuda",
        ]
    )
    with aba_apar:
        _secao_aparencia()
    with aba_usr:
        _secao_usuarios()
    with aba_bkp:
        _secao_backup()
    with aba_imp:
        _secao_importar_base()
    with aba_sol:
        _secao_solicitantes_mro()
    with aba_listas:
        _secao_listas_mestras()
    with aba_ajuda:
        ajuda.conteudo()


def _secao_aparencia() -> None:
    """Aparência / Tema (v2.11.0)."""
    pal = paleta_atual()
    with st.container(border=True):
        st.subheader(":material/palette: Aparência")
        _tema_txt = ":material/dark_mode: Escuro" if pal["tipo"] == "dark" else ":material/light_mode: Claro"
        st.markdown(f"**Tema atual:** {_tema_txt}  ·  **Padrão:** :material/light_mode: Claro")
        st.caption(
            "Para alternar entre **claro** e **escuro**, use o botão **Tema** na **barra "
            "lateral** (abaixo do menu). A escolha é lembrada ao recarregar (fica na URL). "
            "O fundo, os textos, o menu e os gráficos acompanham. :material/warning: Observação: no modo "
            "escuro, as **tabelas** podem continuar claras — é uma limitação do Streamlit "
            "(as grades seguem o tema base); no modo claro (padrão) fica tudo consistente."
        )
        st.markdown("<br>", unsafe_allow_html=True)


def _secao_usuarios() -> None:
    """Usuários, papéis e PIN (v6.1.0) — a administração do login local.

    É a única tela que escreve em `usuarios`, e só o almoxarife a alcança (Configurações
    não está no menu do comprador). Toda ação delega para `services.usuarios` e mostra o
    `(ok, msg)` de volta — a tela não decide nada sobre permissão.
    """
    with st.container(border=True):
        st.subheader(":material/group: Usuários e Acesso")
        st.info(
            ":material/info: **Login 100% local** — os usuários vivem no `mro.db`. Não depende "
            "da API do SCM, nem de Kódigos, nem da TI. O PIN é guardado com hash (pbkdf2), "
            "nunca em texto."
        )

        usuarios = U.listar_usuarios()
        com_pin = [u for u in usuarios if u["tem_pin"] and u["ativo"]]

        # ── Interruptor geral ────────────────────────────────────────────────
        exigir_atual = U.exigir_login()
        if not exigir_atual:
            st.warning(
                ":material/warning: Ao ligar, **todo acesso passa a exigir nome + PIN**. Defina "
                "o PIN das pessoas ANTES de ligar — quem estiver sem PIN não consegue entrar."
            )
        novo_exigir = st.toggle(
            "Exigir login para acessar o sistema",
            value=exigir_atual,
            key="usr_exigir_login",
            help="Desligado (padrão): o sistema abre direto, como sempre foi.",
        )
        if novo_exigir != exigir_atual:
            # Guarda de porta trancada: ligar sem NENHUM usuário ativo com PIN deixa o
            # sistema inacessível pela própria tela que o desligaria. É a mesma família
            # da guarda do "último almoxarife" — não existe desfazer pela UI.
            if novo_exigir and not com_pin:
                st.error(
                    "Nenhum usuário ativo tem PIN definido — ligar agora trancaria o sistema "
                    "para todo mundo, inclusive para você. Defina ao menos um PIN abaixo."
                )
            else:
                U.definir_exigir_login(novo_exigir)
                st.rerun()
        elif exigir_atual:
            st.success(f":material/lock: Login exigido. {len(com_pin)} usuário(s) ativo(s) com PIN definido.")

        st.divider()

        if not usuarios:
            st.info(
                "Nenhum usuário cadastrado ainda. Eles são criados automaticamente na abertura "
                "do sistema, a partir dos **Solicitantes MRO** — ou à mão, no formulário abaixo."
            )
        else:
            # ── Grade ────────────────────────────────────────────────────────
            df = pd.DataFrame(
                [
                    {
                        "Nome": u["nome"],
                        "Login": u["login"] or "—",
                        "Papel": U.ROTULO_PAPEL.get(u["papel"], u["papel"]),
                        "Departamento": u["departamento"] or "—",
                        "Ativo": "Sim" if u["ativo"] else "Não",
                        "PIN definido": "Sim" if u["tem_pin"] else "Não",
                        "Último acesso": u["ultimo_login"] or "—",
                    }
                    for u in usuarios
                ]
            )
            st.dataframe(df, width="stretch", hide_index=True)

            # ── Ações por usuário ────────────────────────────────────────────
            st.markdown("##### Editar usuário")
            rotulos = {
                f"{u['nome']}  ·  {U.ROTULO_PAPEL.get(u['papel'], u['papel'])}"
                + ("" if u["ativo"] else "  (inativo)"): u
                for u in usuarios
            }
            escolha = st.selectbox("Usuário", list(rotulos.keys()), key="usr_sel")
            alvo = rotulos[escolha]
            uid = alvo["id"]

            c_papel, c_pin, c_ativo = st.columns([2, 2, 1])

            with c_papel:
                novo_papel = st.selectbox(
                    "Papel",
                    U.PAPEIS,
                    index=U.PAPEIS.index(alvo["papel"]) if alvo["papel"] in U.PAPEIS else 0,
                    format_func=lambda p: U.ROTULO_PAPEL.get(p, p),
                    key=f"usr_{uid}_papel",
                )
                if st.button(":material/save: Salvar papel", key=f"usr_{uid}_papel_btn", width="stretch"):
                    _feedback_usuario(U.definir_papel(uid, novo_papel))

            with c_pin:
                novo_pin = st.text_input(
                    "PIN (4 dígitos)",
                    type="password",
                    max_chars=4,
                    key=f"usr_{uid}_pin",
                    placeholder="ex.: 1234",
                )
                cb_def, cb_rm = st.columns(2)
                if cb_def.button(":material/key: Definir", key=f"usr_{uid}_pin_btn", width="stretch"):
                    _feedback_usuario(U.definir_pin(uid, novo_pin))
                if cb_rm.button(
                    ":material/key_off: Remover",
                    key=f"usr_{uid}_pin_rm",
                    width="stretch",
                    disabled=not alvo["tem_pin"],
                ):
                    _feedback_usuario(U.remover_pin(uid))

            with c_ativo:
                st.markdown("<br>", unsafe_allow_html=True)
                # Botão, não checkbox: a ação pode ser RECUSADA (último almoxarife) e um
                # checkbox ficaria marcado contra o estado real do banco no rerun.
                _lbl = ":material/block: Desativar" if alvo["ativo"] else ":material/check: Ativar"
                if st.button(_lbl, key=f"usr_{uid}_ativo", width="stretch"):
                    _feedback_usuario(U.ativar_usuario(uid, not alvo["ativo"]))

        st.divider()

        # ── Cadastro manual ──────────────────────────────────────────────────
        with st.expander(":material/person_add: Adicionar usuário manualmente"):
            st.caption(
                "Para quem não vem dos Solicitantes MRO (compradores, portaria). O usuário "
                "nasce **sem PIN** — defina o PIN dele acima para que consiga entrar."
            )
            with st.form("form_add_usuario", clear_on_submit=True):
                c_n, c_p, c_d = st.columns([3, 2, 2])
                nome_novo = c_n.text_input("Nome completo", placeholder="ex.: Miguel Nascimento")
                papel_novo = c_p.selectbox("Papel", U.PAPEIS, format_func=lambda p: U.ROTULO_PAPEL.get(p, p))
                depto_novo = c_d.text_input("Departamento (opcional)")
                if st.form_submit_button(":material/add: Adicionar", width="stretch"):
                    _feedback_usuario(U.salvar_usuario(nome_novo, papel_novo, depto_novo))
        st.markdown("<br>", unsafe_allow_html=True)


def _feedback_usuario(resultado: tuple[bool, str]) -> None:
    """Mostra o `(ok, msg)` de `services.usuarios` e recarrega quando deu certo."""
    ok, msg = resultado
    if not ok:
        st.error(msg)
        return
    invalidar_leituras()
    st.success(msg)
    time.sleep(0.8)
    st.rerun()


def _secao_backup() -> None:
    """Backup do banco (v5.8.0).

    Os .bak automáticos só cobrem migração e o sync diário da API. Este é o backup sob
    demanda + o único caminho para quem usa o sistema pela REDE tirar uma cópia do
    servidor (o download_button entrega o arquivo na máquina de quem clicou)."""
    with st.container(border=True):
        st.subheader(":material/backup: Backup do Banco")
        st.caption(
            "Gera uma cópia do banco **na hora**, em `backups/` ao lado dele. Opcionalmente "
            "copia também para uma pasta sua (disco externo, pasta de rede) e entrega o "
            "arquivo pelo navegador. Os backups automáticos acontecem só antes de uma "
            "migração e no sync diário da API — este botão é o backup sob demanda."
        )

        destino_atual = backup.destino_configurado()
        if destino_atual:
            _ok_dest, _msg_dest = backup.validar_destino(destino_atual)
            if not _ok_dest:
                st.warning(
                    f":material/warning: {_msg_dest} — a cópia extra vai falhar até você "
                    "corrigir. O backup em `backups/` continua funcionando."
                )

        c_dest, c_salvar = st.columns([4, 1])
        novo_destino = c_dest.text_input(
            "Pasta de destino (opcional)",
            value=destino_atual or "",
            key="bkp_destino",
            placeholder="ex.: D:\\Backups  ou  \\\\servidor\\backups\\mro",
            help="Em branco = guarda apenas em `backups/`.",
        )
        with c_salvar:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(":material/save: Salvar", key="bkp_salvar_destino", width="stretch"):
                ok_s, msg_s = backup.definir_destino(novo_destino)
                if ok_s:
                    st.success(msg_s)
                    time.sleep(0.8)
                    st.rerun()
                else:
                    st.error(msg_s)

        st.divider()

        if st.button(":material/backup: Fazer backup agora", type="primary", key="bkp_agora"):
            st.session_state["ultimo_backup"] = backup.fazer_backup("manual")

        res = st.session_state.get("ultimo_backup")
        if res:
            if not res["ok"]:
                st.error(
                    "Não foi possível gerar o backup. Confira o log do servidor — o banco "
                    "pode não existir ainda ou a pasta `backups/` pode estar sem permissão."
                )
            else:
                _mb = res["tamanho"] / (1024 * 1024)
                st.success(
                    f"Backup criado: **{res['nome']}** ({_mb:.1f} MB) em `{os.path.dirname(res['caminho'])}`"
                )
                if res["erro_destino"]:
                    st.warning(f":material/warning: {res['erro_destino']}")
                elif res["destino_extra"] and res["destino_extra"] != res["caminho"]:
                    st.info(f"Cópia também gravada em `{res['destino_extra']}`.")

                try:
                    with open(res["caminho"], "rb") as fh:
                        _dados = fh.read()
                except OSError as e:
                    st.warning(f"Backup gravado, mas não consegui lê-lo para download: {e}")
                else:
                    st.download_button(
                        ":material/download: Baixar este backup",
                        _dados,
                        file_name=res["nome"],
                        mime="application/octet-stream",
                        key="bkp_download",
                    )
                    st.caption(
                        "Para restaurar: pare o sistema, substitua o `mro.db` por este "
                        "arquivo e **apague** os `mro.db-wal` / `mro.db-shm` — restaurar "
                        "deixando um WAL de outra geração mistura dois estados do banco."
                    )
        st.markdown("<br>", unsafe_allow_html=True)


def _secao_importar_base() -> None:
    """Importação da base do Neidson — Tipo, Mínimo, Máximo, Lead Time (Item 1)."""
    with st.container(border=True):
        st.subheader(":material/download: Importar Base (Tipo/Categoria, Mínimo, Máximo, Lead Time)")
        st.caption(
            "Atualiza itens **existentes** (casados pelo PN) com os dados apurados pelo "
            "Compras. PNs não encontrados são apenas relatados — nenhum item é criado. "
            "Um backup do banco é criado automaticamente antes de aplicar."
        )
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
                            st.download_button(
                                "⬇️ Baixar lista (CSV)",
                                df_ne.to_csv(index=False).encode("utf-8-sig"),
                                file_name="pns_nao_encontrados.csv",
                                mime="text/csv",
                                key="dl_ne",
                            )
                    if res_p["pns_duplicados_planilha"]:
                        st.warning(
                            "PNs duplicados na planilha (mantém a última ocorrência): "
                            + ", ".join(res_p["pns_duplicados_planilha"][:20])
                        )
                    st.warning("Confira os números acima e clique em **Aplicar** para gravar.")
                    if st.button(
                        ":material/check_circle: Aplicar atualização", type="primary", key="btn_apply_neidson"
                    ):
                        ok_a, res_a = importar_inventario_neidson(arq_neidson, nome_p, dry_run=False)
                        if ok_a:
                            st.success(
                                f"Importação concluída — atualizados: {res_a['atualizados']} | "
                                f"ignorados: {res_a['ignorados']}."
                            )
                            st.session_state.pop("prev_neidson", None)
                            invalidar_leituras()
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error(res_a.get("erro", "Falha na importação."))
        st.markdown("<br>", unsafe_allow_html=True)


def _secao_solicitantes_mro() -> None:
    """Solicitantes MRO (SCM) — escopo do sync da API (v5.1.0 / F2)."""
    with st.container(border=True):
        st.subheader(":material/badge: Solicitantes MRO (SCM)")
        st.caption(
            "Quem é do **escopo MRO** ao puxar SCs da API do SCM (aba Monitor › "
            "*Atualizar agora*). O **código** Protheus é resolvido pelo nome via API — ou "
            "informado à mão. **Só solicitantes com código entram na sincronização.**"
        )

        incluidos = listar_solicitantes_mro(apenas_incluidos=True)
        if incluidos:
            for s in incluidos:
                with st.container(border=True):
                    cN, cC, cS, cB = st.columns([3, 2, 1, 1])
                    _dep = f"  ·  _{s['departamento']}_" if s.get("departamento") else ""
                    cN.markdown(f"**{s['nome']}**{_dep}")
                    if not (s.get("codigo") or "").strip():
                        cN.caption(":material/warning: sem código — não entra no sync")
                    _cod = cC.text_input(
                        "Código",
                        value=s.get("codigo") or "",
                        key=f"cod_sol_{s['id']}",
                        placeholder="ex.: 001054",
                        label_visibility="collapsed",
                    )
                    if cS.button(":material/save:", key=f"savecod_{s['id']}", help="Salvar código"):
                        definir_codigo_solicitante_mro(s["id"], _cod)
                        invalidar_leituras()
                        st.rerun()
                    if cB.button(":material/close:", key=f"rmsol_{s['id']}", help="Remover do escopo MRO"):
                        marcar_solicitante_mro(s["nome"], incluir=False)
                        invalidar_leituras()
                        st.rerun()
        else:
            st.info("Nenhum solicitante no escopo MRO ainda. Adicione abaixo.")

        st.divider()
        candidatos = [c["nome"] for c in listar_solicitantes_mro(apenas_incluidos=False)]
        c_add1, c_add2 = st.columns([3, 1])
        with c_add1:
            escolhido = ""
            if candidatos:
                escolhido = st.selectbox(
                    "Adicionar da lista (aba SCM USERS)", [""] + candidatos, key="add_sol_sel"
                )
            else:
                st.caption("Sem candidatos importados (aba SCM USERS) — use o campo abaixo.")
            novo_nome = st.text_input(
                "…ou digite um nome novo", key="add_sol_txt", placeholder="Nome completo do solicitante"
            )
        with c_add2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(":material/person_add: Adicionar", key="add_sol_btn", width="stretch"):
                alvo = (novo_nome or "").strip() or (escolhido or "").strip()
                if alvo:
                    marcar_solicitante_mro(alvo, incluir=True)
                    invalidar_leituras()
                    st.rerun()
                else:
                    st.warning("Escolha um nome da lista ou digite um.")

        if st.button(
            ":material/sync: Resolver códigos agora (via API)",
            key="resolve_cod_btn",
            help="Consulta a API do SCM e preenche os códigos faltantes casando pelo nome.",
        ):
            try:
                n = scm_sync.resolver_codigos_solicitantes()
                invalidar_leituras()
                st.success(f"{n} código(s) resolvido(s) pela API.")
                time.sleep(0.8)
                st.rerun()
            except Exception as e:
                st.error(f"Não foi possível resolver via API: {e}")
        st.markdown("<br>", unsafe_allow_html=True)


# Definição das categorias de listas
LISTAS_CONFIG = {
    "centro_custo": ":material/work: Centros de Custo",
    "local": ":material/location_on: Locais de Armazenagem",
    "fornecedor": ":material/factory: Fornecedores",
    "autorizador": ":material/key: Tipos de Autorizador",
    "setor": ":material/apartment: Setores Solicitantes",  # Adicionado setor se necessário
}


def _secao_listas_mestras() -> None:
    """As 5 listas mestras. v6.0.0: agrupadas numa aba só, com sub-navegação por lista —
    cinco abas de 1º nível para o mesmo tipo de coisa era o oposto de simplificar."""
    sub = st.tabs(list(LISTAS_CONFIG.values()))
    for aba, (tipo_lista, titulo) in zip(sub, LISTAS_CONFIG.items()):
        with aba:
            _lista_mestra(tipo_lista, titulo)


def _lista_mestra(tipo_lista, titulo) -> None:
    """Grade + remoção + adição de UMA lista mestra (corpo original do laço)."""
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
            if st.button(
                ":material/sync: Sincronizar do Relatório de SCs",
                key="sync_forn",
                help="Adiciona os Nomes Fantasia do cadastro mestre (importado no "
                "Relatório de SCs) que ainda não estão na lista.",
            ):
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
                label_visibility="collapsed",
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
