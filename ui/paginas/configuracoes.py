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
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from services import atualizacao
from services.constants import VERSAO
from services.importar_imagens import (
    caminho_padrao_planilha,
    coletar_fotos_por_pn,
    importar_imagens_planilha,
)
from services.db_functions import (
    importar_inventario_neidson,
    listar_valores,
    listar_valores_material,
    adicionar_valor_lista,
    adicionar_valor_lista_txt,
    contar_itens_com_valor,
    remover_valor_lista,
    sincronizar_fornecedores_lista,
    listar_solicitantes_mro,
    marcar_solicitante_mro,
    definir_codigo_solicitante_mro,
    UNIDADES_RESET_INVENTARIO,
    ler_config_reset_inventario,
    marcar_reset_inventario,
    proxima_data_reset_inventario,
    resetar_inventario,
    salvar_config_reset_inventario,
)
from services import scm_sync
from services import backup
from services import usuarios as U
from ui.cache import invalidar_leituras
from ui.paginas import ajuda
from ui.tema import paleta_atual


def render() -> None:
    """Configurações em 9 abas (v6.1.0 — **Usuários**; v6.5.2 — **Inventário**; v6.6.0 —
    **Atualização**). Antes da v6.0.0 eram 8 blocos empilhados num scroll só; cada seção
    virou uma aba, as 5 Listas Mestras foram agrupadas em uma, e a Central de Ajuda entrou
    como aba (deixou de ser item do menu)."""
    st.title(":material/settings: Configurações do Sistema")
    st.caption(
        "Parâmetros globais, usuários, listas mestras, backup, ciclo de inventário e a Central de Ajuda."
    )

    (
        aba_apar,
        aba_usr,
        aba_bkp,
        aba_atu,
        aba_inv,
        aba_imp,
        aba_sol,
        aba_listas,
        aba_ajuda,
    ) = st.tabs(
        [
            ":material/palette: Aparência",
            ":material/group: Usuários",
            ":material/backup: Backup",
            ":material/system_update: Atualização",
            ":material/inventory_2: Inventário",
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
    with aba_atu:
        _secao_atualizacao()
    with aba_inv:
        _secao_inventario()
    with aba_imp:
        _secao_importar_base()
        _secao_importar_fotos()
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


def _para_data(texto):
    """'YYYY-MM-DD' → `date`; ausente ou inválido → None."""
    try:
        return date.fromisoformat(str(texto).strip()[:10])
    except (TypeError, ValueError):
        return None


def _secao_inventario() -> None:
    """Reset do inventário (v6.5.2) — manual e agendado.

    "Inventariado" marca o item contado no ciclo corrente; começar um ciclo novo é apagar
    essa marca de todo mundo. O reset toca SÓ `data_inventario` — saldo, locais e a Obs.
    de Inventário de cada item ficam como estão."""
    cfg = ler_config_reset_inventario()

    with st.container(border=True):
        st.subheader(":material/restart_alt: Reset das Marcações de Inventário")
        st.caption(
            "Apaga a marcação **inventariado** (a data da última contagem) de **todos** os "
            "itens, para começar um ciclo de contagem novo. **Não** altera saldo, locais "
            "nem a Observação de Inventário — só a marcação. Em Saldo em Estoque, o filtro "
            "**Não Inventariado** volta a listar a base inteira."
        )

        _ultimo = _para_data(cfg["ultimo"])
        st.markdown(
            f"**Último reset:** `{_ultimo.strftime('%d/%m/%Y')}`"
            if _ultimo
            else "**Último reset:** `nunca` — nenhum ciclo foi fechado até agora."
        )

        with st.popover(":material/restart_alt: Resetar marcações agora"):
            st.warning(
                ":material/warning: Isso desmarca **todos** os itens inventariados e não tem "
                "desfazer. Só confirme se o ciclo de contagem realmente terminou."
            )
            if st.button(":material/check: Confirmar reset", type="primary", key="inv_reset_confirmar"):
                ok_r, res_r = resetar_inventario()
                if ok_r:
                    # O relógio do agendamento recomeça de hoje: sem isso, um agendamento
                    # já vencido dispararia de novo no render seguinte ao clique.
                    marcar_reset_inventario()
                    invalidar_leituras()
                    st.session_state["inv_reset_msg"] = f"{res_r} item(ns) desmarcado(s)."
                    st.rerun()
                else:
                    st.error(f":material/cancel: Não foi possível resetar: {res_r}")

        _msg_reset = st.session_state.pop("inv_reset_msg", None)
        if _msg_reset:
            st.success(f":material/check_circle: Marcações de inventário resetadas — {_msg_reset}")

        st.divider()

        st.markdown("**Reset automático por intervalo**")
        st.caption(
            "Com o agendamento ligado, o reset acontece sozinho na **primeira abertura do "
            "sistema depois do vencimento** — não existe serviço rodando em segundo plano."
        )

        c_per, c_uni, c_ativo = st.columns([1, 1, 1])
        periodo = c_per.number_input(
            "A cada", min_value=1, max_value=99, step=1, value=int(cfg["periodo"]), key="inv_reset_periodo"
        )
        unidade = c_uni.selectbox(
            "Unidade",
            options=list(UNIDADES_RESET_INVENTARIO),
            index=list(UNIDADES_RESET_INVENTARIO).index(cfg["unidade"]),
            key="inv_reset_unidade",
        )
        with c_ativo:
            st.markdown("<br>", unsafe_allow_html=True)
            ativo = st.toggle("Agendamento ligado", value=cfg["ativo"], key="inv_reset_ativo")

        if cfg["ativo"] and _ultimo:
            _prox = proxima_data_reset_inventario(_ultimo, cfg["periodo"], cfg["unidade"])
            st.info(f":material/event: Próximo reset automático em **{_prox.strftime('%d/%m/%Y')}**.")

        if st.button(":material/save: Salvar agendamento", key="inv_reset_salvar"):
            ok_s, msg_s = salvar_config_reset_inventario(ativo, periodo, unidade)
            if ok_s:
                st.success(msg_s)
                time.sleep(0.8)
                st.rerun()
            else:
                st.error(msg_s)
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


def _secao_importar_fotos() -> None:
    """Fotos dos itens a partir de "Material MRO 2026.xlsx" (v6.6.0).

    Por CAMINHO em disco, não `file_uploader`: a planilha tem ~118 MB e o upload pelo
    navegador levaria isso duas vezes para a memória do PC-servidor (uma na simulação,
    outra ao aplicar). A leitura é `read_only=True` no openpyxl, direto do arquivo.
    """
    with st.container(border=True):
        st.subheader(":material/imagesmode: Fotos dos itens (planilha do MRO)")
        st.caption(
            "Lê as fotos **embutidas nas células** da planilha e as vincula aos itens pelo "
            "**Part Number**. Nenhum item é criado e nenhum outro campo é alterado. "
            "Um backup do banco é criado automaticamente antes de gravar."
        )

        padrao = str(caminho_padrao_planilha())
        caminho = st.text_input(
            "Caminho da planilha (.xlsx)",
            value=st.session_state.get("cam_fotos", padrao),
            key="cam_fotos",
            help="Cole aqui o caminho completo do arquivo, como aparece no Explorador de Arquivos.",
        )
        substituir = st.checkbox(
            "Substituir fotos que já existem",
            key="chk_subst_fotos",
            help=(
                "Desmarcado, itens que já têm foto NO DISCO são pulados. Itens com foto "
                "cadastrada mas com o arquivo sumido são sempre regravados."
            ),
        )

        if not caminho.strip():
            st.markdown("<br>", unsafe_allow_html=True)
            return
        if not Path(caminho).is_file():
            st.warning(f":material/warning: Arquivo não encontrado: `{caminho}`")
            st.markdown("<br>", unsafe_allow_html=True)
            return

        if st.button(":material/search: Pré-visualizar (simulação)", key="btn_prev_fotos"):
            with st.spinner("Lendo as fotos embutidas... (a planilha é grande, pode levar ~1 min)"):
                try:
                    fotos = coletar_fotos_por_pn(caminho)
                except Exception as e:  # noqa: BLE001 - a mensagem vai para a tela
                    st.session_state["prev_fotos"] = (False, {"erro": str(e)}, None)
                else:
                    ok_p, res_p = importar_imagens_planilha(
                        caminho, substituir=substituir, dry_run=True, fotos=fotos
                    )
                    # A coleta é o passo caro; guardá-la evita reabrir os 118 MB no Aplicar.
                    st.session_state["prev_fotos"] = (ok_p, res_p, fotos)

        prev = st.session_state.get("prev_fotos")
        if not prev:
            st.markdown("<br>", unsafe_allow_html=True)
            return

        ok_p, res_p, fotos = prev
        if not ok_p:
            st.error(res_p.get("erro", "Não foi possível ler a planilha."))
            st.markdown("<br>", unsafe_allow_html=True)
            return

        m1, m2, m3 = st.columns(3)
        m1.metric("Fotos na planilha", res_p["fotos_na_planilha"])
        m2.metric("Casaram com o sistema", res_p["casados"])
        m3.metric("Sem item no sistema", res_p["sem_item_no_sistema"])
        m4, m5, m6 = st.columns(3)
        m4.metric("Já têm foto (pulados)", res_p["ja_tinham_foto"])
        m5.metric("Foto sumida (reparadas)", res_p["fotos_perdidas"])
        m6.metric("A gravar", res_p["a_gravar"])

        if res_p["pns_nao_encontrados"]:
            with st.expander(f"Ver {len(res_p['pns_nao_encontrados'])} PNs sem item no sistema"):
                df_nf = pd.DataFrame({"PN sem cadastro": res_p["pns_nao_encontrados"]})
                st.dataframe(df_nf, width="stretch", hide_index=True)
                st.download_button(
                    "⬇️ Baixar lista (CSV)",
                    df_nf.to_csv(index=False).encode("utf-8-sig"),
                    file_name="pns_sem_cadastro.csv",
                    mime="text/csv",
                    key="dl_fotos_nf",
                )

        if not res_p["a_gravar"]:
            st.info("Nada a gravar com estas opções.")
            st.markdown("<br>", unsafe_allow_html=True)
            return

        st.warning("Confira os números acima e clique em **Aplicar** para gravar as fotos.")
        if st.button(
            ":material/check_circle: Aplicar import de fotos", type="primary", key="btn_apply_fotos"
        ):
            barra = st.progress(0.0, text="Gravando fotos...")

            def _passo(feitos, total):
                barra.progress(feitos / total, text=f"Gravando fotos... {feitos}/{total}")

            ok_a, res_a = importar_imagens_planilha(
                caminho, substituir=substituir, dry_run=False, fotos=fotos, progresso=_passo
            )
            barra.empty()
            if not ok_a:
                st.error(res_a.get("erro", "Falha ao gravar as fotos."))
                return
            st.success(
                f"Import concluído — {res_a['gravadas']} foto(s) gravada(s)"
                + (f" · {len(res_a['falhas'])} falha(s)" if res_a["falhas"] else "")
                + "."
            )
            if res_a["falhas"]:
                with st.expander(f"Ver {len(res_a['falhas'])} falha(s)"):
                    for f in res_a["falhas"][:50]:
                        st.text(f)
            st.session_state.pop("prev_fotos", None)
            invalidar_leituras()
            time.sleep(1.5)
            st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)


def _secao_atualizacao() -> None:
    """Instalar uma nova versão do sistema sem sair do app (v6.6.0).

    Até a v6.5.2 publicar uma versão significava acessar o PC-servidor, extrair o zip e
    copiar arquivos à mão. Aqui quem opera a máquina só escolhe o arquivo que recebeu; a
    troca de `app\\` acontece num processo destacado (`deploy/aplicar_atualizacao.bat`),
    porque o app não consegue substituir a pasta de onde ele próprio está lendo código.
    """
    with st.container(border=True):
        st.subheader(":material/system_update: Atualização do Sistema")

        raiz = atualizacao.raiz_instalacao()
        producao = atualizacao.modo_producao(raiz)

        c1, c2 = st.columns(2)
        c1.metric("Versão instalada", f"v{VERSAO}")
        c2.metric("Modo", "Produção" if producao else "Desenvolvimento")
        st.caption(f"Instalação em `{raiz}`")

        if not producao:
            st.info(
                ":material/info: Esta é uma instalação de **desenvolvimento** (o código roda "
                "direto do repositório, sem a pasta `app\\`). A instalação automática fica "
                "desativada aqui de propósito — trocar esta pasta apagaria o repositório."
            )
            st.markdown("<br>", unsafe_allow_html=True)
            return

        st.caption(
            "Escolha o arquivo **mro-<versão>.zip** que você recebeu. O sistema faz backup do "
            "banco, troca os arquivos e volta sozinho em ~30 segundos. "
            "**O banco de dados não é tocado** — ele vive fora da pasta que é substituída."
        )

        pacote = st.file_uploader("Pacote de atualização (.zip)", type=["zip"], key="upl_atualizacao")
        if pacote is None:
            st.markdown("<br>", unsafe_allow_html=True)
            return

        ok, info = atualizacao.inspecionar_pacote(pacote.getvalue())
        if not ok:
            st.error(f":material/error: {info['erro']}")
            st.markdown("<br>", unsafe_allow_html=True)
            return

        nova = info["versao"]
        situacao = atualizacao.comparar_versoes(VERSAO, nova)
        st.markdown(f"### v{VERSAO} → **v{nova}**")

        if situacao == "nova":
            st.success(f":material/upgrade: Versão mais nova que a instalada ({info['arquivos']} arquivos).")
        elif situacao == "mesma":
            st.warning(
                f":material/info: Este pacote é da **mesma versão** já instalada (v{nova}). "
                "Reinstalar só faz sentido para reparar arquivos."
            )
        else:
            st.error(
                f":material/warning: Este pacote é **mais antigo** (v{nova}) que o instalado "
                f"(v{VERSAO}). Instalar isso é voltar atrás."
            )

        confirmou = st.checkbox(
            "Entendi: o sistema vai fechar e reiniciar agora",
            key="chk_confirma_atualizacao",
        )
        if st.button(
            ":material/download_done: Instalar agora",
            type="primary",
            disabled=not confirmou,
            key="btn_instalar_atualizacao",
        ):
            try:
                destino = atualizacao.guardar_pacote(pacote.getvalue(), nova, raiz)
            except OSError as e:
                st.error(f"Não consegui gravar o pacote: {e}")
                return
            ok_d, msg = atualizacao.disparar(destino, raiz)
            if not ok_d:
                st.error(f":material/error: {msg}")
                return
            st.success(
                f":material/check_circle: Atualização para a **v{nova}** iniciada. "
                "O sistema vai fechar e voltar sozinho — **recarregue esta página em ~30 segundos**."
            )
            st.caption(
                f"Se algo der errado, o log fica em `{atualizacao.pasta_atualizacoes(raiz)}"
                "\\ultima_atualizacao.log` e a versão anterior em `app_anterior\\`."
            )
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
    # v6.5.1 — tipos e unidades do material mudam com frequência; viraram listas
    # administráveis em vez de constantes hardcoded em `constants.py`.
    "tipo_material": ":material/category: Tipos de Material",
    "unidade": ":material/straighten: Unidades",
}

# Listas cujo valor é texto de cadastro, não código: preservam o caso digitado
# ("Spare Parts") e são semeadas com o que já está em uso no `inventario`. As demais
# seguem em maiúsculas (`adicionar_valor_lista`). O valor é o nome no singular, para
# as mensagens da tela saírem em português correto.
LISTAS_TEXTO_LIVRE = {
    "tipo_material": "tipo de material",
    "unidade": "unidade",
}


def _secao_listas_mestras() -> None:
    """As listas mestras. v6.0.0: agrupadas numa aba só, com sub-navegação por lista —
    uma aba de 1º nível por lista, para o mesmo tipo de coisa, era o oposto de simplificar.
    v6.5.1: entraram Tipos de Material e Unidades (antes constantes de `constants.py`)."""
    sub = st.tabs(list(LISTAS_CONFIG.values()))
    for aba, (tipo_lista, titulo) in zip(sub, LISTAS_CONFIG.items()):
        with aba:
            _lista_mestra(tipo_lista, titulo)


def _lista_mestra(tipo_lista, titulo) -> None:
    """Grade + remoção + adição de UMA lista mestra (corpo original do laço)."""
    texto_livre = tipo_lista in LISTAS_TEXTO_LIVRE
    with st.container(border=True):
        st.subheader(titulo)

        # 1. Visualização da Lista Atual (Grid)
        # `fallback=False`: aqui o admin precisa ver a lista como ela está (inclusive
        # vazia); quem mostra as constantes como rede de segurança é o Cadastro de Itens.
        valores = (
            listar_valores_material(tipo_lista, fallback=False) if texto_livre else listar_valores(tipo_lista)
        )

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
                            # Remoção é soft-delete: o item que já usa o valor continua
                            # com o texto gravado. A contagem só avisa o tamanho do efeito.
                            em_uso = contar_itens_com_valor(tipo_lista, val) if texto_livre else 0
                            remover_valor_lista(tipo_lista, val)
                            invalidar_leituras()
                            if em_uso:
                                st.warning(
                                    f"'{val}' removido da lista. {em_uso} item(ns) do inventário ainda "
                                    "usam este valor — eles continuam como estão, o valor é que deixa "
                                    "de aparecer para novos cadastros."
                                )
                                time.sleep(2.0)
                            st.rerun()
        elif texto_livre:
            st.info(
                f"Nenhuma opção de {LISTAS_TEXTO_LIVRE[tipo_lista]} na lista — o Cadastro de Itens "
                "volta a sugerir a lista padrão do sistema até você cadastrar alguma aqui."
            )
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
                placeholder=(
                    f"Digite {'o novo' if tipo_lista == 'tipo_material' else 'a nova'} "
                    f"{LISTAS_TEXTO_LIVRE[tipo_lista]} e pressione Adicionar..."
                    if texto_livre
                    else "Digite e pressione Adicionar..."
                ),
                label_visibility="collapsed",
            )
            submitted = c_btn.form_submit_button(":material/add: Adicionar", width="stretch")

            if submitted:
                if novo_valor.strip():
                    adicionar = adicionar_valor_lista_txt if texto_livre else adicionar_valor_lista
                    ok, msg = adicionar(tipo_lista, novo_valor.strip())
                    if ok:
                        invalidar_leituras()
                        st.success(msg)
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("O campo não pode estar vazio.")
