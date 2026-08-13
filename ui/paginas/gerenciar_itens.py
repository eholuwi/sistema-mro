"""Página Cadastro de Itens MRO (v5.3.0 / F4a) — cadastro e edição de itens.

Migrada do bloco inline do `app.py`. É uma página de FORMULÁRIO (2 abas: Cadastrar
Novo / Editar Existente) — o item é escolhido por `sel_material` (selectbox), não há
lista/tabela navegável, então não há adoção de `barra_filtros`/`tabela_paginada`
aqui. Toda escrita (salvar/atualizar/alterar PN) chama `invalidar_leituras()` para
as telas cacheadas (Saldo/Dashboard/sidebar) não exibirem dado velho. Regra de
negócio (conversão de unidades, alteração de PN, lead time) preservada 1:1.

O nome da tela era "Gerenciar Itens" até a v5.9.0; o MÓDULO segue `gerenciar_itens`
de propósito (o router importa por nome explícito — renomear o arquivo só produziria
ruído de diff sem ganho).
"""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from services.constants import (
    IMPORTANCIAS,
    FATOR_CONVERSAO_PADRAO,
    UNIDADES_COMPRA_SUGERIDAS,
)
from services.db_functions import (
    listar_valores,
    listar_valores_material,
    adicionar_valor_lista_txt,
    listar_inventario,
    salvar_item,
    atualizar_item_inventario,
    alterar_part_number,
    listar_historico_part_number,
    recalcular_min_max_calculado,
    sugerir_conversao,
)
from ui.cache import invalidar_leituras
from ui.formatos import fmt
from ui.componentes.selecao import (
    sel_material,
    opcoes_com_atual,
    rotulo_item,
)


def k_ed(nome, item_id):
    """Key dos widgets da aba "Editar Item Existente", AMARRADA ao item (v6.5.1).

    Os widgets precisam de `key` (as duas abas da tela têm campos de mesmo rótulo e
    opções; sem key colidiriam em `StreamlitDuplicateElementId`), e uma key FIXA faz
    o Streamlit tratá-la como identidade principal do widget — `index=`/`value=` só
    valem na 1ª renderização, e trocar de item continuava exibindo (e gravando) os
    dados do item anterior.

    Até a v6.5.1 o remédio era limpar as keys no `session_state` ao trocar de item
    (`resetar_campos_ao_trocar`). Funciona, mas tem uma corrida que só aparece no
    navegador: a limpeza e a trava "item atual" acontecem ANTES dos widgets serem
    desenhados, e o Streamlit **cancela a execução em curso** quando chega uma nova
    interação — nesta tela, que redesenha as 3 abas a cada rerun, a janela é larga. Se
    a execução morre depois da trava e antes dos widgets, o rerun seguinte devolve os
    valores que o navegador ainda tem, a trava já diz "não mudou", e o formulário fica
    preso no item anterior até um F5.

    Pendurar o id do item na key resolve pela raiz: item diferente é WIDGET diferente,
    nasce com o `value=`/`index=` do item certo, e nenhuma execução interrompida pode
    ligar o valor de um item ao formulário de outro."""
    return f"ed_{nome}_{item_id}"


# v6.0.0 — a conversão de unidades passou a ficar atrás de um checkbox nas DUAS abas
# (Novo e Editar). Rótulo único para as duas (DRY) e o predicado que decide se o
# checkbox nasce marcado na edição.
LABEL_CONVERSAO = "Este material é comprado em uma unidade diferente da unidade de estoque"

# v6.5.1 — Unidade e Tipo saíram das constantes e viraram listas mestras editáveis em
# Configurações → Listas. O cadastro passa a ser guiado por elas, mas sem perder a
# liberdade de sempre: quem precisa de um valor que ainda não existe digita na hora, e
# ele vira opção para os próximos cadastros. `inventario` continua sendo texto livre.
OPCAO_NOVO = "➕ Digitar novo…"
LABEL_NOVO = {"tipo_material": "Novo tipo / categoria", "unidade": "Nova unidade"}


def _select_lista_material(rotulo, tipo_lista, atual=None, key=None):
    """Selectbox da lista mestra + opção de digitar um valor novo.

    Devolve o valor escolhido (ou o digitado, já sem espaços nas pontas), ou "" se o
    usuário escolheu digitar e não digitou nada — quem chama valida antes de salvar.
    O valor novo NÃO é gravado na lista aqui: só no salvamento do item, para o que foi
    digitado e abandonado não virar opção. `opcoes_com_atual` mantém visível o valor do
    item que está fora da lista (item legado, importação antiga)."""
    opcoes = opcoes_com_atual(listar_valores_material(tipo_lista), atual)
    escolha = st.selectbox(
        rotulo,
        opcoes + [OPCAO_NOVO],
        index=opcoes.index(atual) if atual in opcoes else 0,
        key=key,
    )
    if escolha == OPCAO_NOVO:
        digitado = st.text_input(
            LABEL_NOVO[tipo_lista],
            key=f"{key}_novo",
            placeholder="Digite e salve o item — vira opção para os próximos.",
        )
        return (digitado or "").strip()
    return escolha


def _persistir_valor_novo(tipo_lista, valor):
    """Grava na lista mestra o valor digitado no cadastro, se ainda não estiver lá.
    Chamado só DEPOIS que o item foi salvo com sucesso."""
    valor = (valor or "").strip()
    if not valor:
        return
    atuais = [v.upper() for v in listar_valores_material(tipo_lista)]
    if valor.upper() not in atuais:
        adicionar_valor_lista_txt(tipo_lista, valor)


def tem_conversao(item):
    """True se o item JÁ tem conversão de unidades curada — fator ≠ 1 **ou** unidade de
    compra gravada e diferente da de estoque.

    É o que faz o checkbox da edição nascer marcado. Sem isso, um item já curado abriria
    com os campos escondidos e o salvamento devolveria fator 1 sem o gestor ver — o
    recebimento passaria a somar a quantidade crua no estoque. Puro/testável."""
    if not item:
        return False
    fator = float(item.get("fator_conversao") or 1.0)
    if abs(fator - 1.0) > 1e-9:
        return True
    uc = (item.get("unidade_compra") or "").strip()
    un = (item.get("unidade") or "").strip()
    return bool(uc) and uc.casefold() != un.casefold()


def _difere(calculado, cadastrado, tolerancia=1.0):
    """A sugestão vale a pena mostrar? True quando difere do cadastrado em ao menos 1
    unidade. Sem tolerância, um mínimo de 10 contra um calculado de 10,4 apareceria como
    "divergente" e a lista em lote viraria ruído — a base do Neidson é em unidades
    inteiras. Pura/testável."""
    return abs(float(calculado or 0) - float(cadastrado or 0)) >= tolerancia


def _sugestoes_min_max(itens):
    """Linhas da visão em lote: itens COM sugestão calculada que difere do cadastrado.

    Item sem consumo na janela não entra (`minimo_calculado` 0 = "não há o que sugerir",
    e propor mínimo zero para a base inteira seria o oposto do que a tela existe para
    fazer). Pura sobre a lista já lida — a UI só monta o DataFrame."""
    linhas = []
    for i in itens:
        min_calc = float(i.get("minimo_calculado") or 0)
        max_calc = float(i.get("maximo_calculado") or 0)
        if min_calc <= 0 and max_calc <= 0:
            continue
        min_cad = float(i.get("estoque_minimo") or 0)
        max_cad = float(i.get("estoque_maximo") or 0)
        if not (_difere(min_calc, min_cad) or _difere(max_calc, max_cad)):
            continue
        linhas.append(
            {
                "Aplicar": False,
                "id": i["id"],
                "PN": i.get("part_number"),
                "Material": i.get("nome_item"),
                "Mín atual": min_cad,
                "Mín calculado": min_calc,
                "Máx atual": max_cad,
                "Máx calculado": max_calc,
                "Saídas (30d)": int(i.get("min_max_amostras") or 0),
                "Base": i.get("min_max_origem") or "—",
            }
        )
    return sorted(linhas, key=lambda linha: linha["PN"] or "")


def _aba_sugestoes_min_max():
    """Visão em LOTE do Mín/Máx calculado — "concordamos e torna real" de uma vez.

    Existe porque adotar item a item na aba de edição não escala: a base tem centenas de
    itens e o Luis revisa a lista inteira de uma sentada. Aplicar grava mínimo E máximo
    do item marcado, pela mesma `atualizar_item_inventario` do botão individual."""
    st.caption(
        "Itens cuja sugestão calculada difere do cadastrado em ao menos 1 unidade. "
        "Fórmulas: **mínimo = consumo/dia × lead time calculado** · "
        "**máximo = consumo/dia × 60 dias**. "
        "Marque *Aplicar* nos que você aprova e confirme abaixo — nada é gravado sem isso."
    )

    # v6.4.0 — recálculo sob demanda. A sugestão é mantida em dia por `_recalcular_consumo`
    # (a cada saída) e pelo backfill da migração, mas o backfill roda UMA VEZ só na vida do
    # banco: quem migrou antes de uma mudança de fórmula fica com números da regra antiga
    # até o item se mexer. Este botão é a saída explícita — e serve também depois de uma
    # revisão de lead times em massa, sem esperar movimento item a item.
    cr1, cr2 = st.columns([3, 1])
    cr1.caption(
        ":material/info: Os números se atualizam sozinhos a cada saída do item. Use o botão "
        "se acabou de revisar lead times ou atualizou o sistema e quer refazer a base inteira."
    )
    if cr2.button(":material/refresh: Recalcular tudo", key="minmax_recalc", width="stretch"):
        with st.spinner("Recalculando as sugestões..."):
            n = recalcular_min_max_calculado()
        invalidar_leituras()
        st.success(f"Sugestões recalculadas para {n} item(ns).")
        time.sleep(1)
        st.rerun()

    linhas = _sugestoes_min_max(listar_inventario())
    if not linhas:
        st.success(
            ":material/check_circle: Nenhuma divergência: todo item com consumo registrado já tem "
            "mínimo e máximo alinhados ao calculado."
        )
        return

    editado = st.data_editor(
        pd.DataFrame(linhas),
        width="stretch",
        hide_index=True,
        key="minmax_lote",
        column_config={
            "Aplicar": st.column_config.CheckboxColumn("Aplicar", help="Marque para adotar a sugestão."),
            "id": None,  # chave técnica: usada para gravar, não para ler
            "Mín atual": st.column_config.NumberColumn(format="%.0f"),
            "Mín calculado": st.column_config.NumberColumn(format="%.0f"),
            "Máx atual": st.column_config.NumberColumn(format="%.0f"),
            "Máx calculado": st.column_config.NumberColumn(format="%.0f"),
        },
        disabled=[c for c in linhas[0] if c != "Aplicar"],
    )

    marcados = [linha for linha in editado.to_dict("records") if linha.get("Aplicar")]
    st.markdown(f"**{len(marcados)}** item(ns) marcado(s) de {len(linhas)}.")
    if st.button(
        ":material/check_circle: Aplicar aos selecionados",
        type="primary",
        width="stretch",
        disabled=not marcados,
    ):
        erros = []
        for linha in marcados:
            ok, msg = atualizar_item_inventario(
                int(linha["id"]),
                {
                    "estoque_minimo": float(linha["Mín calculado"]),
                    "estoque_maximo": float(linha["Máx calculado"]),
                },
            )
            if not ok:
                erros.append(f"{linha['PN']}: {msg}")
        invalidar_leituras()
        if erros:
            st.error("Falhas ao aplicar:\n\n" + "\n".join(f"- {e}" for e in erros))
        else:
            st.success(f"{len(marcados)} item(ns) atualizado(s) com o Mín/Máx calculado.")
            time.sleep(1)
            st.rerun()


def render() -> None:
    st.title(":material/add: Cadastro de Itens MRO")

    # --- TABS PARA ORGANIZAÇÃO ---
    tab_editar, tab_novo, tab_minmax = st.tabs(
        [
            ":material/edit: Editar Item Existente",
            ":material/fiber_new: Cadastrar Novo Item",
            ":material/rule: Sugestões de Mín/Máx",
        ]
    )

    # === TAB 1: CADASTRAR NOVO ===
    with tab_novo:
        with st.container(border=True):
            st.subheader("Dados do Novo Item")
            c1, c2 = st.columns(2)

            with c1:
                pn_novo = st.text_input("Part Number (PN) *", placeholder="Ex: 12345-ABC")
                nome_novo = st.text_input("Nome do Item *", placeholder="Ex: Parafuso Sextavado M8")
                desc_novo = st.text_area(
                    "Observação", placeholder="Informações adicionais sobre o item", height=80
                )
                un_novo = _select_lista_material("Unidade", "unidade", key="novo_un")
                tipo_novo = _select_lista_material("Tipo / Categoria", "tipo_material", key="novo_tipo")

            with c2:
                imp_novo = st.selectbox("Importância", IMPORTANCIAS, index=0)
                loc_novo = st.selectbox("Localidade", listar_valores("local") or ["Geral"], index=0)
                caixa_novo = st.selectbox("Caixa/ID", listar_valores("local") or ["Geral"], index=0)
                lead_novo = st.number_input("Lead Time (Dias)", min_value=1, value=20)

            c3, c4 = st.columns(2)
            min_novo = c3.number_input("Estoque Mínimo *", min_value=0, value=10)
            est_ini_novo = c4.number_input("Estoque Inicial", min_value=0.0, value=0.0)

            # ── Conversão de unidades (curadoria v2.9.0) — opcional ──────────────
            # v6.0.0: os campos só aparecem quando o usuário declara que há conversão.
            # O caso comum (compra e estoque na mesma unidade) grava o padrão de sempre:
            # unidade_compra=None e fator=FATOR_CONVERSAO_PADRAO.
            st.markdown("###### :material/sync: Conversão de unidades")
            _sug_novo = sugerir_conversao(
                {"nome_item": nome_novo, "descricao": desc_novo, "unidade": un_novo}
            )
            tem_conv_novo = st.checkbox(
                LABEL_CONVERSAO,
                value=False,
                key="novo_tem_conversao",
                help="Marque só se o fornecedor vende numa unidade diferente da que você "
                "controla no estoque (ex.: compra em GL, estoca em L).",
            )
            uc_novo, fator_novo = None, FATOR_CONVERSAO_PADRAO
            if tem_conv_novo:
                cvn1, cvn2 = st.columns(2)
                uc_novo = cvn1.text_input(
                    "Unidade de Compra",
                    value=(_sug_novo["unidade_compra_sugerida"] or un_novo),
                    help="Unidade em que o fornecedor vende (L, KG, BB, par…).",
                )
                fator_novo = cvn2.number_input(
                    "Fator de Conversão",
                    min_value=0.0,
                    value=float(_sug_novo["fator_sugerido"] or 1.0),
                    step=1.0,
                    help="Quantas unidades de compra cabem em 1 de estoque. Ex.: 1 GL = 5 L → 5.",
                )
                if _sug_novo["fator_sugerido"]:
                    st.caption(
                        f":material/lightbulb: Sugestão automática pelo nome do item: {_sug_novo['origem']}."
                    )

            if st.button(":material/save: Salvar Novo Item", type="primary", width="stretch"):
                if not pn_novo or not nome_novo:
                    st.error("Preencha Part Number e Nome.")
                elif not un_novo or not tipo_novo:
                    # "Digitar novo…" escolhido e campo em branco.
                    st.error("Informe a unidade e o tipo / categoria do item.")
                else:
                    # Verificar duplicidade. `incluir_inativos=True` NÃO é detalhe: o
                    # UNIQUE de `part_number` vale para a tabela inteira, então sem isto
                    # o cadastro deixaria digitar um PN que existe num item desativado e
                    # o erro só apareceria como IntegrityError cru no INSERT (v6.8.0).
                    itens_existentes = listar_inventario(incluir_inativos=True)
                    _dup = next(
                        (i for i in itens_existentes if i["part_number"].lower() == pn_novo.lower()), None
                    )
                    if _dup:
                        _inativo = not (_dup.get("ativo") if _dup.get("ativo") is not None else 1)
                        st.error(
                            f"PN '{pn_novo}' já cadastrado!"
                            + (
                                " Ele está **desativado** — reative-o na aba *Editar* "
                                "(marque *Mostrar itens desativados*) em vez de criar outro."
                                if _inativo
                                else ""
                            )
                        )
                    else:
                        ok, msg = salvar_item(
                            part_number=pn_novo,
                            nome_item=nome_novo,
                            descricao=desc_novo,
                            unidade=un_novo,
                            importancia=imp_novo,
                            tipo_material=tipo_novo,
                            setor="Improdutivo",
                            local=loc_novo,
                            caixa=caixa_novo,
                            estoque_atual=est_ini_novo,
                            estoque_minimo=min_novo,
                            lead_time=lead_novo,
                            unidade_compra=(uc_novo or "").strip() or None,
                            fator_conversao=(
                                fator_novo if (tem_conv_novo and fator_novo > 0) else FATOR_CONVERSAO_PADRAO
                            ),
                        )
                        if ok:
                            _persistir_valor_novo("unidade", un_novo)
                            _persistir_valor_novo("tipo_material", tipo_novo)
                            invalidar_leituras()
                            st.success(msg)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

    # === TAB 2: EDITAR EXISTENTE ===
    with tab_editar:
        with st.container(border=True):
            st.subheader("Selecionar Item para Edição")
            # v6.8.0 — o desativado só é alcançável aqui; é esta tela que o religa.
            ver_inativos = st.checkbox(
                "Mostrar itens desativados",
                key="ed_ver_inativos",
                help="Itens desativados não aparecem em nenhuma outra tela. Marque para "
                "encontrá-los e reativá-los.",
            )
            _, item_sel, _ = sel_material(
                "Busque pelo PN ou Nome", "sel_edit_item", incluir_inativos=ver_inativos
            )

            if item_sel:
                if not (item_sel.get("ativo") if item_sel.get("ativo") is not None else 1):
                    st.warning(
                        ":material/visibility_off: **Item desativado.** Ele não aparece em "
                        "nenhuma outra tela. Ligue **Item ativo** abaixo e salve para voltar."
                    )
                # Todo widget desta aba tem a key amarrada ao item (ver `k_ed`): é o que
                # faz o formulário acompanhar a troca de item sem depender de limpeza.
                iid = item_sel["id"]
                st.info(f"**Editando:** `{item_sel['part_number']} — {item_sel['nome_item']}`")
                if item_sel.get("unidade_divergente"):
                    st.warning(
                        ":material/warning: **Revisar unidade:** este item é comprado numa unidade diferente "
                        "da de estoque (visto nos POs). Defina a *unidade de compra* e o *fator* abaixo para que "
                        "o recebimento converta corretamente."
                    )
                ed_desc = st.text_area(
                    "Observação", value=item_sel.get("descricao", ""), height=70, key=k_ed("desc", iid)
                )

                st.markdown("---")

                c1, c2, c3 = st.columns(3)
                locais_opts = listar_valores("local") or ["Geral"]
                with c1:
                    ed_un = _select_lista_material(
                        "Unidade", "unidade", atual=item_sel.get("unidade"), key=k_ed("un", iid)
                    )
                    ed_tipo = _select_lista_material(
                        "Tipo / Categoria",
                        "tipo_material",
                        atual=item_sel.get("tipo_material"),
                        key=k_ed("tipo", iid),
                    )
                    ed_imp = st.selectbox(
                        "Importância",
                        IMPORTANCIAS,
                        index=IMPORTANCIAS.index(item_sel["importancia"])
                        if item_sel["importancia"] in IMPORTANCIAS
                        else 0,
                        key=k_ed("imp", iid),
                    )

                with c2:
                    ed_loc = st.selectbox(
                        "Localidade",
                        locais_opts,
                        index=locais_opts.index(item_sel.get("local_armazenagem", "Geral"))
                        if item_sel.get("local_armazenagem") in locais_opts
                        else 0,
                        key=k_ed("loc", iid),
                    )
                    # v4.5.6 — 2ª locação (opcional) editável aqui, além da Contagem Física.
                    _op_loc2 = [""] + locais_opts
                    _l2_atual = item_sel.get("local_armazenagem_2") or ""
                    if _l2_atual and _l2_atual not in _op_loc2:
                        _op_loc2.insert(1, _l2_atual)
                    ed_loc2 = st.selectbox(
                        "Localidade (2ª)",
                        _op_loc2,
                        index=_op_loc2.index(_l2_atual) if _l2_atual in _op_loc2 else 0,
                        key=k_ed("loc2", iid),
                        help="2º ponto de armazenagem do mesmo item (opcional). Deixe em branco se não houver.",
                    )
                    ed_caixa = st.selectbox(
                        "Caixa/ID",
                        locais_opts,
                        index=locais_opts.index(item_sel.get("caixa_identificacao", "Geral"))
                        if item_sel.get("caixa_identificacao") in locais_opts
                        else 0,
                        key=k_ed("caixa", iid),
                    )
                    ed_lead = st.number_input(
                        "Lead Time (Dias)",
                        min_value=0,
                        value=int(item_sel.get("lead_time_dias") or 0),
                        key=k_ed("lead", iid),
                    )

                with c3:
                    ed_min = st.number_input(
                        "Estoque Mínimo (30 dias)",
                        min_value=0.0,
                        value=float(item_sel.get("estoque_minimo") or 0),
                        key=k_ed("min", iid),
                    )
                    ed_max = st.number_input(
                        "Estoque Máximo (60 dias)",
                        min_value=0.0,
                        value=float(item_sel.get("estoque_maximo") or 0),
                        key=k_ed("max", iid),
                        help="0 = usa o cálculo automático (Mínimo × 2).",
                    )
                    # v3.7.0: Estoque de Segurança desativado — o buffer virou o próprio
                    # Mínimo do Neidson (não deixar atingir o mínimo nem passar do máximo).
                    # Nota: Estoque atual NÃO deve ser editado aqui, apenas via Movimentação/Inventário
                    st.markdown(f"**Estoque Atual:** `{item_sel['estoque_atual']}` (Alterar em *Inventário*)")
                    st.markdown(f"**Status:** `{item_sel['status_material']}`")
                    # v6.4.0 — nasce MARCADA em todo item (default 1 na coluna). Vale só
                    # para a tela do Requisitante; almoxarife e comprador seguem vendo o
                    # saldo em qualquer item.
                    ed_saldo_req = st.checkbox(
                        "Mostrar saldo para o requisitante",
                        value=bool(
                            item_sel.get("mostrar_saldo_requisitante")
                            if item_sel.get("mostrar_saldo_requisitante") is not None
                            else 1
                        ),
                        key=k_ed("saldo_req", iid),
                        help="Desmarque para que o requisitante peça sem ver o estoque atual "
                        "deste material. Ele continua conseguindo pedir; a conferência do "
                        "saldo passa a ser do almoxarifado, na separação.",
                    )
                    # v6.8.0 — soft delete. Legado sem a coluna (`None`) conta como ativo.
                    ed_ativo = st.toggle(
                        "Item ativo",
                        value=bool(item_sel.get("ativo") if item_sel.get("ativo") is not None else 1),
                        key=k_ed("ativo", iid),
                        help="Desligue para tirar de circulação um material descontinuado. "
                        "Ele some da Requisição, da Movimentação, da reposição, dos "
                        "dashboards e do saldo — mas o cadastro e TODO o histórico de "
                        "movimentações continuam intactos, e dá para religar aqui.",
                    )
                    if not ed_ativo:
                        _saldo_atual = float(item_sel.get("estoque_atual") or 0)
                        if _saldo_atual > 0:
                            # Avisa e deixa passar: o motivo real de desativar é item
                            # descontinuado, e travar obrigaria a zerar o estoque antes —
                            # ninguem faria, e o item continuaria circulando.
                            st.warning(
                                f":material/warning: Este item ainda tem **{_saldo_atual:g} "
                                f"{item_sel.get('unidade') or 'UN'}** em estoque. Desativar não "
                                "baixa nada: o saldo continua no banco, apenas deixa de aparecer."
                            )

                # ── Conversão de unidades (curadoria v2.9.0) ─────────────────────
                # v6.0.0: escondida atrás de um checkbox. Ele NASCE MARCADO quando o item
                # já tem conversão gravada — do contrário o gestor editaria sem ver os
                # campos e o salvamento zeraria o fator sem ele perceber.
                st.markdown("---")
                st.markdown("##### :material/sync: Conversão de unidades (compra ↔ estoque)")
                _sug = sugerir_conversao(item_sel)
                _un_est = item_sel.get("unidade") or "UN"
                _stored_fator = float(item_sel.get("fator_conversao") or 1.0)
                _stored_uc = item_sel.get("unidade_compra")
                # Item ainda não curado (fator=1 e sem UM de compra) → pré-preenche com
                # a sugestão; já curado → mostra o que o gestor gravou.
                _nao_curado = abs(_stored_fator - 1.0) < 1e-9 and not _stored_uc
                _def_uc = _stored_uc or (_sug["unidade_compra_sugerida"] if _nao_curado else None) or _un_est
                _def_fator = (
                    (_sug["fator_sugerido"] or 1.0)
                    if (_nao_curado and _sug["fator_sugerido"])
                    else _stored_fator
                )
                ed_tem_conv = st.checkbox(
                    LABEL_CONVERSAO,
                    value=tem_conversao(item_sel),
                    key=k_ed("tem_conv", iid),
                    help="Desmarque para voltar ao padrão (compra e estoque na mesma "
                    "unidade, fator 1). Marque para definir a unidade de compra e o fator.",
                )
                ed_uc, ed_fator = None, FATOR_CONVERSAO_PADRAO
                if ed_tem_conv:
                    cvc1, cvc2 = st.columns([1, 1])
                    ed_uc = cvc1.text_input(
                        "Unidade de Compra",
                        value=_def_uc,
                        key=k_ed("uc", iid),
                        help="Unidade em que o fornecedor vende (L, KG, BB, par…). "
                        f"Sugestões: {', '.join(UNIDADES_COMPRA_SUGERIDAS[:10])}…",
                    )
                    ed_fator = cvc2.number_input(
                        "Fator de Conversão",
                        min_value=0.0,
                        value=float(_def_fator),
                        step=1.0,
                        key=k_ed("fator", iid),
                        help="Quantas unidades de COMPRA cabem em 1 unidade de ESTOQUE. "
                        "Ex.: 1 GL = 5 L → fator 5. Fator 1 = mesma unidade (sem conversão).",
                    )
                    _uc_txt = (ed_uc or _un_est).strip() or _un_est
                    if abs(ed_fator - 1.0) > 1e-9 and _uc_txt.upper() != _un_est.upper():
                        st.caption(
                            f":material/straighten: **1 {_un_est}** de estoque = **{ed_fator:g} {_uc_txt}** de compra. "
                            f"No recebimento, cada {ed_fator:g} {_uc_txt} recebidos viram 1 {_un_est} no estoque."
                        )
                    else:
                        st.caption(":material/straighten: Sem conversão (compra e estoque na mesma unidade).")
                    st.caption(f":material/lightbulb: Sugestão do sistema: {_sug['origem']}.")
                else:
                    st.caption(
                        f":material/straighten: Compra e estoque na mesma unidade (**{_un_est}**), "
                        "fator 1 — o recebimento soma a quantidade recebida como veio."
                    )

                if st.button(":material/check_circle: Atualizar Item", type="primary", width="stretch"):
                    # "Digitar novo…" escolhido e campo em branco. Erro simples: `st.stop()`
                    # aqui abortaria o resto da página (troca de PN, histórico, aba Mín/Máx)
                    # e deixaria a tela pela metade até um F5.
                    if not ed_un or not ed_tipo:
                        st.error("Informe a unidade e o tipo / categoria do item.")
                    else:
                        dados_edicao = {
                            "descricao": ed_desc,
                            "unidade": ed_un,
                            "tipo_material": ed_tipo,
                            "importancia": ed_imp,
                            "local_armazenagem": ed_loc,
                            "local_armazenagem_2": (ed_loc2 or "").strip(),
                            "caixa_identificacao": ed_caixa,
                            "lead_time_dias": ed_lead,
                            "estoque_minimo": ed_min,
                            "estoque_maximo": ed_max,
                            "unidade_compra": (ed_uc or "").strip() or None,
                            "fator_conversao": (
                                ed_fator if (ed_tem_conv and ed_fator > 0) else FATOR_CONVERSAO_PADRAO
                            ),
                            "mostrar_saldo_requisitante": int(ed_saldo_req),
                            "ativo": int(ed_ativo),
                        }
                        ok, msg = atualizar_item_inventario(item_sel["id"], dados_edicao)
                        if ok:
                            _persistir_valor_novo("unidade", ed_un)
                            _persistir_valor_novo("tipo_material", ed_tipo)
                            invalidar_leituras()
                            st.success(msg)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

                # ── Lead Time: cadastrado vs calculado (sugestão) — v2.2.1 ──────
                _lt_calc = item_sel.get("lead_time_calculado")
                if _lt_calc is not None:
                    _lt_cad = int(item_sel.get("lead_time_dias") or 0)
                    _amostras = int(item_sel.get("lead_time_calculado_amostras") or 0)
                    _origem = item_sel.get("lead_time_calculado_origem") or "—"
                    st.markdown("---")
                    lc1, lc2 = st.columns([2, 1])
                    lc1.info(
                        f":material/timer: **Lead Time** — cadastrado (Compras): **{_lt_cad}d** · "
                        f"calculado: **{_lt_calc}d** ({_amostras} amostras, origem {_origem}). "
                        f"O calculado é apenas uma sugestão; a base cadastrada não é alterada automaticamente."
                    )
                    if int(_lt_calc) != _lt_cad and lc2.button(
                        "Usar calculado", key="btn_usar_lt_calc", width="stretch"
                    ):
                        ok, msg = atualizar_item_inventario(item_sel["id"], {"lead_time_dias": int(_lt_calc)})
                        if ok:
                            invalidar_leituras()
                            st.success(f"Lead time atualizado para {int(_lt_calc)}d.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

                # ── Mín/Máx: cadastrado vs calculado (sugestão) — v6.4.0 ────────
                # Mesmo padrão do bloco de lead time acima: mostra a sugestão ao lado do
                # cadastrado e só grava na base do Neidson quando o gestor clica. Os dois
                # botões são separados de propósito — dá para concordar com o mínimo e
                # discordar do máximo, e um botão único obrigaria a engolir os dois.
                _min_calc = float(item_sel.get("minimo_calculado") or 0)
                _max_calc = float(item_sel.get("maximo_calculado") or 0)
                if _min_calc > 0 or _max_calc > 0:
                    _min_cad = float(item_sel.get("estoque_minimo") or 0)
                    _max_cad = float(item_sel.get("estoque_maximo") or 0)
                    st.markdown("---")
                    mm1, mm2, mm3 = st.columns([2, 1, 1])
                    mm1.info(
                        f":material/rule: **Mín/Máx sugerido** — mínimo: cadastrado **{_min_cad:g}** · "
                        f"calculado **{_min_calc:g}** · máximo: cadastrado **{_max_cad:g}** · "
                        f"calculado **{_max_calc:g}**. Base: {item_sel.get('min_max_origem') or '—'} "
                        f"({int(item_sel.get('min_max_amostras') or 0)} saída(s) na janela). "
                        "É sugestão — o cadastro de Compras não é alterado automaticamente."
                    )
                    if _difere(_min_calc, _min_cad) and mm2.button(
                        "Usar mínimo", key="btn_usar_min_calc", width="stretch"
                    ):
                        ok, msg = atualizar_item_inventario(item_sel["id"], {"estoque_minimo": _min_calc})
                        if ok:
                            invalidar_leituras()
                            st.success(f"Estoque mínimo atualizado para {_min_calc:g}.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)
                    if _difere(_max_calc, _max_cad) and mm3.button(
                        "Usar máximo", key="btn_usar_max_calc", width="stretch"
                    ):
                        ok, msg = atualizar_item_inventario(item_sel["id"], {"estoque_maximo": _max_calc})
                        if ok:
                            invalidar_leituras()
                            st.success(f"Estoque máximo atualizado para {_max_calc:g}.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

                # ── Alteração de Part Number (Item 2 / v2.1.0) ───────────────
                st.markdown("---")
                st.markdown("##### :material/sync: Alterar Part Number")
                st.caption(
                    "Use quando o PN for corrigido no Protheus. O histórico (movimentações, "
                    "SCs e requisições) é preservado e o PN antigo continua pesquisável."
                )
                cpn1, cpn2 = st.columns([1, 1])
                novo_pn = cpn1.text_input(
                    "Novo Part Number", key=k_ed("pn_novo", iid), placeholder=item_sel["part_number"]
                )
                motivo_pn = cpn2.text_input(
                    "Motivo da alteração", key=k_ed("pn_motivo", iid), placeholder="Ex: padronização Protheus"
                )
                confirma_pn = st.checkbox("Confirmo a alteração do Part Number", key=k_ed("pn_confirma", iid))
                if st.button(":material/sync: Alterar Part Number", key="btn_alterar_pn", width="stretch"):
                    if not confirma_pn:
                        st.warning("Marque a confirmação para prosseguir.")
                    else:
                        ok, msg = alterar_part_number(
                            item_sel["id"], novo_pn, motivo=motivo_pn, usuario="Luis Oliveira"
                        )
                        if ok:
                            invalidar_leituras()
                            # O rótulo da seleção é montado a partir do PN: com o PN novo,
                            # o rótulo antigo some das opções e o formulário desapareceria
                            # logo após salvar. Reaponta a seleção para o rótulo novo.
                            st.session_state["sel_edit_item"] = rotulo_item(
                                {**item_sel, "part_number": novo_pn.strip()}
                            )
                            st.success(msg)
                            time.sleep(1.2)
                            st.rerun()
                        else:
                            st.error(msg)

                hist_pn = listar_historico_part_number(item_sel["id"])
                if hist_pn:
                    with st.expander(f":material/history: Histórico de Part Numbers ({len(hist_pn)})"):
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "Data": fmt(h["data_hora"]),
                                        "PN Antigo": h["pn_antigo"],
                                        "PN Novo": h["pn_novo"],
                                        "Motivo": h.get("motivo") or "—",
                                        "Usuário": h.get("usuario") or "—",
                                    }
                                    for h in hist_pn
                                ]
                            ),
                            width="stretch",
                            hide_index=True,
                        )

    # === TAB 3: SUGESTÕES DE MÍN/MÁX EM LOTE (v6.4.0) ===
    with tab_minmax:
        _aba_sugestoes_min_max()
