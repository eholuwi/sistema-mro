"""ui/componentes/status.py — indicadores de origem e disponibilidade (v5.2.0 / F3).

Pequenos helpers visuais em torno da integração com o Protheus/SCM: um "badge" da fonte
do dado (API do SCM × Relatório Excel), o ponto de status da API (health-check com cache
curto, para não bater na rede a cada rerun), o painel de saúde do SCM (v5.6.0) e o aviso
de divergência entre o recebimento do MRO e o declarado pelo ERP (v5.7.0).
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from services import scm_client, scm_sync
from ui.formatos import fmt


def badge_origem(origem, quando=None):
    """String markdown com a fonte do dado. `origem` = 'api_scm' | 'excel' | outro;
    `quando` (ISO) vira data/hora legível. Ex.: '🟢 API do SCM · 16/07/2026 11:33'."""
    o = (origem or "").strip().lower()
    if o == "api_scm":
        rotulo = ":green[:material/cloud_done: API do SCM]"
    elif o == "excel":
        rotulo = ":blue[:material/description: Relatório (Excel)]"
    else:
        rotulo = ":gray[:material/help: origem não registrada]"
    if quando:
        rotulo += f" · {fmt(quando)}"
    return rotulo


def divergencia_recebimento(item):
    """Aviso (markdown) quando o Protheus declara mais recebido do que o MRO conferiu.

    v5.7.0 — `itens_sc.quantidade_recebida` passou a ser escrita SÓ pelo MRO e a leitura do
    ERP vive em `quantidade_recebida_protheus`. Quando o ERP declara mais do que entrou na
    doca, o pendente do MRO fica maior de propósito; o aviso existe para que essa diferença
    seja lida como informação e não como erro de saldo. Devolve `None` quando não há espelho
    (linha legada, anterior à migração) ou quando os dois números batem."""
    if not item:
        return None
    protheus = item.get("quantidade_recebida_protheus")
    if protheus is None:
        return None
    mro = item.get("quantidade_recebida") or 0
    if protheus - mro <= 0.0001:
        return None
    return (
        f":material/rule: **Divergência de recebimento:** o Protheus registra `{protheus:g}` "
        f"e o MRO conferiu `{mro:g}`. O saldo pendente segue o MRO."
    )


_CHAVE_DIAG = "_scm_diagnostico"


def testar_conexao_scm():
    """Faz o health-check AGORA e guarda o resultado na sessão. Toca a rede."""
    diag = scm_client.diagnostico()
    st.session_state[_CHAVE_DIAG] = diag
    return diag


def registrar_diagnostico_do_sync(resumo):
    """Deriva o estado da API do resumo de um sync recém-executado.

    O sync já falou com a API — reaproveitar esse resultado evita pedir ao usuário um
    "Testar conexão" logo depois de ele clicar em "Atualizar agora"."""
    if not isinstance(resumo, dict):
        return None
    ok = bool(resumo.get("ok"))
    diag = {
        "ok": ok,
        "latencia_ms": None,
        "erro": None if ok else (resumo.get("detalhe_erro") or resumo.get("erro")),
        "endpoint": "sincronização SCM",
    }
    st.session_state[_CHAVE_DIAG] = diag
    return diag


def diagnostico_conhecido():
    """Último diagnóstico desta sessão, ou None se ninguém testou ainda. NÃO toca a rede.

    v5.6.0 — guardar em `session_state` (em vez de `st.cache_data`) é o que permite
    perguntar "já testamos?" sem disparar o teste. Sem isso, desenhar o indicador ao
    abrir a página custaria até 10s de timeout sempre que a API estivesse fora."""
    return st.session_state.get(_CHAVE_DIAG)


@st.cache_data(ttl=60, show_spinner=False)
def _diagnostico_cached():
    """`diagnostico()` com cache de 60s — para quem precisa do estado sob demanda."""
    return scm_client.diagnostico()


def _api_disponivel_cached():
    """Compatibilidade: só o booleano do diagnóstico cacheado."""
    return _diagnostico_cached()["ok"]


def ponto_status_api(mostrar=True, diag=None):
    """Verifica (com cache) se a API do SCM responde. Se `mostrar`, escreve um
    indicador colorido. Retorna o booleano.

    `diag` permite reaproveitar um diagnóstico já obtido — quem acabou de consultar a
    API não precisa bater na rede de novo só para desenhar o status."""
    diag = diag if diag is not None else _diagnostico_cached()
    ok = diag["ok"]
    if mostrar:
        if ok:
            ms = diag.get("latencia_ms")
            sufixo = f" · {ms} ms" if ms is not None else ""
            st.markdown(f":green[:material/sensors: **API do SCM online**]{sufixo}")
        else:
            st.markdown(
                ":red[:material/sensors_off: **API do SCM offline**] — exibindo apenas dados do banco."
            )
            if diag.get("erro"):
                st.caption(f":red[Motivo:] `{diag['erro']}`")
    return ok


def _ha_quanto_tempo(quando):
    """'há 5 min' / 'há 3 h' / 'há 2 d' a partir de um timestamp ISO. None se não der."""
    if not quando:
        return None
    try:
        dt = datetime.fromisoformat(str(quando))
    except ValueError:
        return None
    seg = (datetime.now() - dt).total_seconds()
    if seg < 0:
        return "agora"
    if seg < 90:
        return "agora há pouco"
    if seg < 3600:
        return f"há {int(seg // 60)} min"
    if seg < 86400:
        return f"há {int(seg // 3600)} h"
    return f"há {int(seg // 86400)} d"


_ROTULO_STATUS_SYNC = {
    "ok": ":green[concluída sem erros]",
    "parcial": ":orange[concluída com avisos]",
    "falha": ":red[falhou]",
}


def painel_saude_scm():
    """Painel de saúde da integração SCM: conectividade, latência e última sincronização.

    v5.6.0 — antes o único indicador vivia DEPOIS do `return` do caso offline dentro do
    expander "Ao vivo", então era estruturalmente incapaz de ficar vermelho, e só aparecia
    depois de o usuário clicar em buscar. Aqui ele fica sempre visível.

    **A rede NÃO é tocada ao abrir a página.** Um health-check contra uma API fora do ar
    custa até 10s de timeout — justamente no cenário em que o indicador importa, a página
    inteira travaria a cada visita. Então: o que vem do banco (última tentativa, volume,
    escopo) é desenhado sempre e é instantâneo; a conectividade mostra o último resultado
    conhecido e só vai à rede quando o usuário clica em "Testar conexão".
    """
    diag = diagnostico_conhecido()
    c1, c2, c3 = st.columns([2, 2, 1])

    with c1:
        if diag is None:
            st.markdown(":gray[:material/sensors: **Conexão não verificada**]")
            st.caption("Clique em **Testar conexão** para checar a API agora.")
        else:
            ponto_status_api(diag=diag)

    with c2:
        u = scm_sync.ultima_sync()
        if not u:
            st.markdown(":gray[:material/history: **Sincronização:** nunca executada]")
        else:
            detalhe = u.get("detalhe") or {}
            status = str(detalhe.get("status") or "")
            quando = _ha_quanto_tempo(u["data_hora"])
            rotulo = _ROTULO_STATUS_SYNC.get(status, f":gray[{status or 'sem status'}]")
            st.markdown(
                f":material/history: **Última tentativa:** {fmt(u['data_hora'])}"
                + (f" ({quando})" if quando else "")
                + f" — {rotulo}"
            )
            if status == "falha":
                st.caption(f":red[Motivo:] `{detalhe.get('erro') or 'não registrado'}`")
            else:
                r = detalhe.get("resumo") or {}
                st.caption(
                    f"{r.get('scs', 0)} SC(s) · {r.get('itens', 0)} item(ns) · "
                    f"{r.get('externos', 0)} externo(s) · {r.get('divergencias', 0)} divergência(s)"
                )

    with c3:
        if st.button(":material/network_ping: Testar conexão", key="scm_saude_testar", width="stretch"):
            with st.spinner("Consultando a API do SCM…"):
                testar_conexao_scm()
            st.rerun()

    escopo = scm_sync.resumo_escopo()
    if not escopo["com_codigo"]:
        st.warning(
            ":material/warning: **O sync não traria nada.** Nenhum dos "
            f"{escopo['no_mro']} solicitante(s) marcado(s) como MRO tem **código Protheus** "
            "preenchido, e a API só busca SCs por código. Cadastre em "
            "**Configurações › Solicitantes MRO (SCM)** (há um botão para resolver pela API)."
        )
    return None if diag is None else diag["ok"]
