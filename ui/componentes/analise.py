"""ui/componentes/analise.py — bloco da Análise de Consumo em PDF (v6.10.0).

Duas telas pedem o mesmo documento por caminhos diferentes:

- **Assistente de Reposição** — lote, escolhido num seletor livre sobre o inventário
  inteiro (o comprador decide o que analisar, independente de status ou tipo);
- **Ficha 360** — o item que já está aberto, um de cada vez.

O que muda entre elas é **quem escolhe o item**; o resto — revisão obrigatória, campo de
observações, auditoria e download — é idêntico e vive aqui. Duplicar esse fluxo nas duas
telas faria a revisão divergir com o tempo, e a revisão é justamente a garantia de que
nada sai do sistema sem alguém ter lido.

**Revisão A é forçada** (decisão do Luis, 13/08/2026): o PDF vira anexo de e-mail para
justificar compra, então o que ele afirma passa a ser afirmação da empresa. Nada baixa
sem "Revisado e de acordo".
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from services import analise_consumo
from ui.auth import usuario_logado
from ui.formatos import fmt


def reportlab_indisponivel():
    """Mensagem de dependência faltando, ou `None` se o `reportlab` está instalado.

    ⚠️ **Aconteceu de verdade em 17/08/2026, na validação.** O import do reportlab vive
    DENTRO das funções de PDF (para o app não pagar o custo dele em toda abertura), então
    o app subia normal, a Ficha 360 abria normal, a revisão era feita normal — e o
    `ModuleNotFoundError` só estourava no `download_button`. No Streamlit uma exceção não
    tratada **derruba o render inteiro**: a pessoa perdia a Ficha toda, com um stack trace
    no lugar, depois de ter revisado o documento.

    Duas lições que valem além deste bloco: (1) import adiado troca custo de startup por
    falha tardia — quem adia tem de checar; (2) o `mro.db` real roda com o Python GLOBAL
    da máquina, não com o `venv\\` do projeto, então **pin em `requirements.txt` não
    garante o pacote instalado onde o app roda**. No pacote portátil não há esse risco:
    o `pip --target` do `scripts/portatil.py` instala do próprio `requirements.txt`.
    """
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return (
            ":material/error: **A geração de PDF precisa da biblioteca `reportlab`**, que não "
            "está instalada neste Python. O resto do sistema funciona normalmente.\n\n"
            "Para instalar, feche o sistema e rode no prompt:\n\n"
            "```\npython -m pip install reportlab==5.0.0\n```\n\n"
            "No PC-servidor (pacote portátil) ela já vem junto — este aviso é de instalação "
            "de desenvolvimento."
        )
    return None


def aviso_sc7_desatualizado():
    """Alerta de planilha SC7 velha/ausente — antes do botão, não depois de gerar.

    O documento afirma "consumo por pedido de compra atendido". Com a planilha de três
    meses atrás a afirmação continua verdadeira e o número continua velho, e quem recebe
    o PDF por e-mail não tem como saber disso."""
    frescor = analise_consumo.sc7_frescor()
    if frescor["sem_import"]:
        st.warning(
            ":material/warning: **O Relatório de Compras (SC7) nunca foi importado.** A análise "
            "vai cair no consumo por **requisição** (retiradas do almoxarifado) para todos os "
            "itens — o documento explica isso, mas o número ideal vem do pedido de compra. "
            "Importe em **Controle de SC › Importar Relatório de SCs**."
        )
    elif frescor["desatualizado"]:
        quando = datetime.strptime(frescor["data"], "%Y-%m-%d").strftime("%d/%m/%Y")
        st.warning(
            f":material/update: **SC7 importado há {frescor['dias']} dias** ({quando}). "
            "Pedidos atendidos depois dessa data não entram na conta. Reimporte em "
            "**Controle de SC › Importar Relatório de SCs** antes de gerar a análise."
        )


def _cartao_revisao(dados, prefixo, indice):
    """Um item na revisão: números, fonte, riscos e o campo de observações."""
    c1, c2, c3 = st.columns(3)
    c1.metric("Estoque atual", f"{fmt(dados['estoque_atual'])} {dados['unidade']}")
    c2.metric("Mínimo", f"{fmt(dados['estoque_minimo'])} {dados['unidade']}")
    c3.metric(
        "Consumo mensal",
        f"{fmt(dados['consumo_mensal'])} {dados['unidade']}" if dados["consumo_mensal"] is not None else "—",
        help=f"Fonte: {dados['fonte_rotulo']}",
    )

    if dados["explicacao_fallback"]:
        st.warning(f":material/warning: {dados['explicacao_fallback']}")
    else:
        st.caption(f":material/verified: Fonte do consumo: **{dados['fonte_rotulo']}**")

    st.markdown(f"**Por que o material é necessário:** {dados['por_que']}")
    if dados["riscos"]:
        st.markdown("**Riscos:**")
        for risco in dados["riscos"]:
            st.markdown(f"- {risco}")
    else:
        st.caption("Sem riscos relevantes identificados para este item.")

    dados["observacoes"] = st.text_area(
        "Observações (entram na seção 3 do documento)",
        value=dados.get("observacoes", ""),
        key=f"{prefixo}_obs_{indice}_{dados['item_id']}",
        height=80,
        placeholder="Opcional — contexto que o documento não tem como saber.",
    )
    return st.checkbox(
        "Revisado e de acordo",
        key=f"{prefixo}_ok_{indice}_{dados['item_id']}",
        help="Confirme que os números e o texto acima estão corretos.",
    )


def revisao_e_download(dados_lote, chave_lote, prefixo, incluir_geral=True, com_expander=True):
    """Revisão obrigatória → auditoria → downloads. Devolve True se liberou.

    `com_expander=False` é a Ficha 360, onde o item já está aberto e um expander dentro do
    outro só esconderia o conteúdo que a pessoa acabou de pedir.
    """
    if not dados_lote:
        return False

    # Checa a dependência ANTES da revisão: descobrir que o PDF não sai depois de revisar
    # item por item é o pior momento possível para dar a notícia.
    faltando = reportlab_indisponivel()
    if faltando:
        st.error(faltando)
        return False

    n_fallback = sum(1 for d in dados_lote if d["modo"] != analise_consumo.MODO_SC7)
    if n_fallback:
        alvo = (
            "Este item não tem"
            if len(dados_lote) == 1
            else f"**{n_fallback} de {len(dados_lote)}** item(ns) não têm"
        )
        st.info(
            f":material/info: {alvo} pedido de compra atendido no SC7. Nesse caso o documento "
            "usa as **retiradas do almoxarifado** e explica a conta — confira o texto antes de "
            "aprovar."
        )

    revisados = []
    for i, dados in enumerate(dados_lote):
        if com_expander:
            with st.expander(f"{dados['part_number']} · {dados['nome_item']}", expanded=len(dados_lote) == 1):
                revisados.append(_cartao_revisao(dados, prefixo, i))
        else:
            revisados.append(_cartao_revisao(dados, prefixo, i))

    if not all(revisados):
        st.warning(
            f":material/pending: **{sum(revisados)} de {len(dados_lote)}** revisados. "
            "Confirme para liberar o download."
        )
        return False

    # A auditoria grava quando o lote é LIBERADO, não a cada download: o `download_button`
    # reexecuta o script a cada arquivo baixado, e gravar ali daria uma linha por clique.
    if st.session_state.get(f"{prefixo}_auditada") != chave_lote:
        # `usuario_logado()` é None com `exigir_login` desligada (modo legado): grava NULL
        # em vez de inventar um nome. "Não se sabe quem gerou" é melhor que carimbar
        # "Sistema" e parecer registro confiável.
        analise_consumo.registrar_analise(dados_lote, usuario=(usuario_logado() or {}).get("nome"))
        st.session_state[f"{prefixo}_auditada"] = chave_lote

    st.success(":material/check_circle: Revisão concluída — documento(s) liberado(s).")
    for i, dados in enumerate(dados_lote):
        nome = analise_consumo.nome_arquivo_analise(dados["part_number"], dados["nome_item"])
        st.download_button(
            f":material/download: {nome}",
            data=analise_consumo.gerar_pdf_analise(dados),
            file_name=nome,
            mime="application/pdf",
            key=f"{prefixo}_dl_{i}_{dados['item_id']}",
            width="stretch",
            type="primary" if len(dados_lote) == 1 else "secondary",
        )
    if incluir_geral and len(dados_lote) > 1:
        st.download_button(
            ":material/download: Analise Geral.pdf (resumo do lote)",
            data=analise_consumo.gerar_pdf_analise_geral(dados_lote),
            file_name="Analise Geral.pdf",
            mime="application/pdf",
            key=f"{prefixo}_dl_geral",
            type="primary",
            width="stretch",
        )
    return True
