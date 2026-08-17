"""v6.10.0 — Análise de Consumo em PDF (Assistente de Reposição).

O documento sai do sistema e vira **anexo de e-mail para justificar compra**. Isso muda o
que precisa ser protegido: não basta o PDF abrir; ele tem de dizer de onde veio o número.

O que estes testes travam:

- **A fonte é sempre rotulada.** Item com pedido atendido no SC7 e item sem pedido geram
  documentos com textos DIFERENTES — o segundo diz em português que o SC7 não achou nada,
  que o número veio das retiradas e qual foi a conta. Fonte trocada em silêncio é o defeito
  que a v6.5.0 já pagou uma vez (o card SC7 dizendo "12 pedidos" para 12 requisições).
- **Zero ≠ "não sabemos".** Item sem histórico nenhum não pode sair com consumo 0; ele sai
  como `sem_historico` e o documento explica.
- **O PDF sobrevive ao dado real.** Descrição com `&`/`<`/`>` quebra o mini-HTML do
  `Paragraph`, e caractere fora do WinAnsi derruba a fonte padrão. As duas coisas chegam
  pelo cadastro e pelo campo de observações, que é texto livre digitado na tela.
- **A janela é a mesma do SC7** (ano anterior ÷ 12; ano corrente jan→mês anterior ÷ N).
  Janelas diferentes por fonte tornariam os dois números incomparáveis no mesmo documento.
- **A auditoria guarda a versão do SC7 e o modo** — sem isso, dois PDFs do mesmo item em
  datas diferentes seriam indistinguíveis no registro.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import database
from services import analise_consumo as AC

PROJ = Path(__file__).resolve().parents[1]

# 10/08/2026: jan–jul fechados no ano corrente (7 meses), agosto em andamento. Mesma
# âncora do `test_v650_consumo_sc7.py`, de propósito: os dois medem a mesma janela.
HOJE = date(2026, 8, 10)


def _pedido_sc7(conn, produto, emissao="2026-03-01", entregue=70, saldo=0, numero="F900"):
    """Insere uma linha de pedido de compra direto na `consumo_sc7` (o que o import gera)."""
    conn.execute(
        """INSERT INTO consumo_sc7 (numero_pc, produto, dt_emissao, qtd_entregue, saldo, data_importacao)
           VALUES (?,?,?,?,?,?)""",
        (numero, produto, emissao, entregue, saldo, "2026-08-09 10:00:00"),
    )
    conn.commit()


# A saída por requisição vem da fixture `registrar_consumo` do conftest (linha em
# `requisicoes` + `movimentacoes` com `requisicao_id`). Inserir a movimentação à mão aqui
# não funcionaria — a FK de `requisicao_id` recusa, que é justamente a garantia de que
# `SAIDA_REAL_WHERE` só enxerga saída com requisição de verdade.


# ══════════════════════════════════════════════════════════════════════════════
# 1. Escolha e rotulagem da fonte — o coração do documento
# ══════════════════════════════════════════════════════════════════════════════


def test_item_com_pedido_atendido_usa_sc7_e_rotula_o_periodo(db, make_item):
    item_id = make_item(part_number="PN-SC7", nome="ITEM COM PEDIDO", estoque=10, minimo=100)
    conn = db.get_connection()
    _pedido_sc7(conn, "PN-SC7", emissao="2026-03-01", entregue=70)
    conn.close()

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)

    assert dados["modo"] == AC.MODO_SC7
    assert dados["consumo_mensal"] == 10.0  # 70 entregues ÷ 7 meses (jan–jul)
    assert "SC7" in dados["fonte_rotulo"] and "jan–jul" in dados["fonte_rotulo"]
    assert dados["explicacao_fallback"] is None, "com SC7 não pode haver aviso de fallback"


def test_item_sem_pedido_cai_na_requisicao_e_EXPLICA_a_conta(db, make_item, registrar_consumo):
    """O aviso é o ponto da versão: quem lê o PDF não conhece o sistema e precisa saber
    que o número mudou de origem — e qual foi a divisão feita."""
    item_id = make_item(part_number="PN-REQ", nome="ITEM SEM PEDIDO", estoque=5, minimo=50)
    for mes in ("01", "02", "03", "04", "05", "06", "07"):
        registrar_consumo(item_id, 10, f"2026-{mes}-15 09:00:00")

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)

    assert dados["modo"] == AC.MODO_REQUISICAO
    assert dados["consumo_mensal"] == 10.0  # 70 retirados ÷ 7 meses — mesma janela do SC7
    texto = dados["explicacao_fallback"]
    assert "SC7" in texto, "tem de dizer QUAL fonte faltou"
    assert "RETIRADAS" in texto.upper(), "tem de dizer de onde o número veio"
    assert "dividimos por 7" in texto, "tem de mostrar a conta, não só o resultado"
    assert "janeiro a julho" in texto, "tem de dizer o período somado"


def test_item_sem_historico_nenhum_nao_inventa_zero(db, make_item):
    """Consumo 0 e "não temos como saber" são coisas diferentes — e confundi-las na
    justificativa de uma compra é o erro caro."""
    item_id = make_item(part_number="PN-NADA", nome="ITEM PARADO", estoque=0, minimo=5)

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)

    assert dados["modo"] == AC.MODO_SEM_HISTORICO
    assert dados["consumo_mensal"] is None, "sem evidência não pode virar zero"
    assert dados["consumo_diario"] is None
    assert any("não tem histórico" in r for r in dados["riscos"])


def test_o_mes_corrente_nunca_entra_na_conta(db, make_item, registrar_consumo):
    """Agosto está em andamento em `HOJE`: a saída de agosto não pode entrar, senão o
    consumo cairia todo dia 1º (mesmo princípio do SC7 e de `_ultimos_n_meses_completos`)."""
    item_id = make_item(part_number="PN-MES", estoque=5, minimo=50)
    registrar_consumo(item_id, 70, "2026-07-15 09:00:00")
    registrar_consumo(item_id, 999, "2026-08-09 09:00:00")  # mês corrente — fora da janela

    info = AC.consumo_por_requisicao(item_id, hoje=HOJE)

    assert info["meses"] == 7
    assert info["total"] == 70.0, "o mês em andamento entrou na soma"
    assert info["consumo_mensal"] == 10.0


def test_ano_anterior_divide_por_12(db, make_item, registrar_consumo):
    item_id = make_item(part_number="PN-ANT", estoque=5, minimo=50)
    registrar_consumo(item_id, 120, "2025-06-15 09:00:00")

    info = AC.consumo_por_requisicao(item_id, hoje=HOJE)

    assert info["ano_ref"] == 2025
    assert info["meses"] == 12
    assert info["consumo_mensal"] == 10.0


def test_ajuste_de_inventario_nao_conta_como_consumo(db, make_item):
    """O fallback usa `SAIDA_REAL_WHERE` (saída COM requisição). Um ajuste físico é
    correção de estoque, não consumo de setor — contá-lo inflaria a justificativa."""
    item_id = make_item(part_number="PN-AJU", estoque=5, minimo=50)
    conn = database.get_connection()
    conn.execute(
        """INSERT INTO movimentacoes (item_id, tipo, quantidade, saldo_apos, data_hora, centro_custo)
           VALUES (?,'saida',500,0,'2026-05-10 09:00:00','INVENTÁRIO')""",
        (item_id,),
    )
    conn.commit()
    conn.close()

    info = AC.consumo_por_requisicao(item_id, hoje=HOJE)

    assert info["consumo_mensal"] is None, "ajuste de inventário virou consumo"


def test_pedido_pendente_nao_soma_mas_aparece(db, make_item):
    """Material que ainda não chegou não é consumo — mas o gestor precisa saber que existe,
    ou vai ler o consumo baixo como pouca necessidade."""
    item_id = make_item(part_number="PN-PEND", estoque=0, minimo=50)
    conn = db.get_connection()
    _pedido_sc7(conn, "PN-PEND", emissao="2026-05-01", entregue=0, saldo=40)
    conn.close()

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)

    assert dados["modo"] != AC.MODO_SC7, "pedido pendente não pode virar consumo"
    assert (dados["sc7"] or {}).get("pendentes", {}).get("n") == 1
    pdf = AC.gerar_pdf_analise(dados)
    assert pdf.startswith(b"%PDF-")


# ══════════════════════════════════════════════════════════════════════════════
# 2. Riscos — só os aplicáveis, e sem os dois que o Luis vetou
# ══════════════════════════════════════════════════════════════════════════════


def test_riscos_do_item_critico(db, make_item, registrar_consumo):
    item_id = make_item(
        part_number="PN-CRIT", nome="ITEM CRITICO", estoque=20, minimo=100, importancia="Parada de Linha"
    )
    registrar_consumo(item_id, 10, "2026-03-15 09:00:00")

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)
    texto = " ".join(dados["riscos"])

    assert "parada de linha" in texto.lower()
    assert "80" in texto, "o % abaixo do mínimo tem de aparecer ((100-20)/100)"
    assert "ruptura em" not in texto.lower(), "o risco de ruptura em X–Y dias está vetado"
    assert "atendimento da produção" not in texto.lower(), "risco genérico vetado"


def test_estoque_zerado_vira_ruptura_iminente(db, make_item):
    item_id = make_item(part_number="PN-ZERO", estoque=0, minimo=10)

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)

    assert any("RUPTURA IMINENTE" in r for r in dados["riscos"])


def test_item_saudavel_nao_inventa_risco(db, make_item, registrar_consumo):
    """Estoque acima do mínimo, importância Admin e consumo SUAVE: nada a alegar. Um
    documento que lista risco para todo item ensina o leitor a ignorar a seção.

    O consumo é semanal e de quantidade constante de propósito: com retirada só uma vez
    por mês o SBC classifica como **Intermitente** (o intervalo entre demandas passa do
    limiar) e o risco de "consumo não linear" dispara — corretamente. Um item realmente
    regular precisa de demanda regular."""
    item_id = make_item(part_number="PN-OK", estoque=500, minimo=10, importancia="Admin")
    for semana in range(1, 17):  # ~4 meses de retiradas semanais iguais
        dia = date(2026, 3, 1) + timedelta(weeks=semana - 1)
        registrar_consumo(item_id, 10, f"{dia.isoformat()} 09:00:00")

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)

    assert dados["riscos"] == [], f"item com estoque acima do mínimo não tem risco: {dados['riscos']}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. O PDF — abre, e sobrevive ao dado real
# ══════════════════════════════════════════════════════════════════════════════


def test_pdf_do_item_e_do_lote_sao_validos(db, make_item):
    ids = [make_item(part_number=f"PN-{i}", nome=f"ITEM {i}", estoque=i, minimo=50) for i in (1, 2)]
    lote = [AC.montar_dados_analise(i, hoje=HOJE) for i in ids]

    for dados in lote:
        pdf = AC.gerar_pdf_analise(dados)
        assert pdf.startswith(b"%PDF-") and len(pdf) > 1000

    geral = AC.gerar_pdf_analise_geral(lote, hoje=HOJE)
    assert geral.startswith(b"%PDF-") and len(geral) > 500


def test_pdf_sobrevive_a_markup_e_caractere_exotico(db, make_item):
    """`Paragraph` interpreta mini-HTML: um `&` na descrição levantaria erro de parse e o
    documento simplesmente não sairia. E a fonte padrão não mapeia `→`/`▪`.

    O cadastro de hoje está limpo, mas o campo **Observações** é digitado à mão na tela de
    revisão — a próxima observação não tem como estar garantida."""
    item_id = make_item(part_number="PN-X&Y", nome="PORCA & PARAFUSO <M8> → INOX ▪", estoque=0, minimo=5)

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)
    dados["observacoes"] = "trocar por <modelo novo> & revisar → urgente"

    pdf = AC.gerar_pdf_analise(dados)
    assert pdf.startswith(b"%PDF-")
    assert AC.gerar_pdf_analise_geral([dados], hoje=HOJE).startswith(b"%PDF-")


def test_sanitizacao_escapa_para_paragraph_mas_nao_para_celula():
    """Escapar na célula de `Table` imprimiria `&amp;` na cara do leitor — ela não
    interpreta markup."""
    assert AC._texto_pdf("A & B <c>") == "A &amp; B &lt;c&gt;"
    assert AC._texto_pdf("A & B <c>", markup=False) == "A & B <c>"
    assert AC._texto_pdf("seta → fim") == "seta ? fim", "sem mapeamento vira ?, não quebra o PDF"
    assert AC._texto_pdf("acentuação ç ã é") == "acentuação ç ã é", "o português tem de passar"


def test_acentuacao_do_portugues_cabe_na_fonte_padrao():
    """A escolha de não embutir fonte só se sustenta se o WinAnsi cobrir o português.
    Medido caractere a caractere — se um dia faltar, é aqui que aparece."""
    from reportlab.pdfbase._fontdata import encodings
    from reportlab.pdfbase.pdfmetrics import getFont

    winansi, fonte = encodings["WinAnsiEncoding"], getFont("Helvetica")
    for ch in "áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ—–·•ºª%":
        pos = ch.encode("cp1252")[0]
        assert winansi[pos] not in (".notdef", ""), f"{ch!r} não tem glifo no WinAnsi"
        assert fonte.widths[pos] > 0, f"{ch!r} tem largura zero (não desenha)"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Nome do arquivo
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "pn,descricao,esperado",
    [
        ("53EP0067", "PULSEIRA ANTIESTATICA", "Consumo 53EP0067-PULSEIRA ANTIESTATICA.pdf"),
        # O `/` é o caso real e frequente ("KYZEN C8622 P/LIMPEZA"): vira `-`.
        ("12PL0024", "KYZEN P/LIMPEZA", "Consumo 12PL0024-KYZEN P-LIMPEZA.pdf"),
        # O `-` final some: `Consumo PN-ITEM -ASPAS-.pdf` terminaria em traço solto.
        ("30UC0097", 'ITEM "COM" <ASPAS>', "Consumo 30UC0097-ITEM -COM- -ASPAS.pdf"),
        ("34FR0001", None, "Consumo 34FR0001.pdf"),
    ],
)
def test_nome_de_arquivo_sanitizado(pn, descricao, esperado):
    assert AC.nome_arquivo_analise(pn, descricao) == esperado


def test_nome_de_arquivo_nao_estoura_o_limite_do_windows():
    """PN + descrição passa de 200 caracteres em vários itens, e o caminho completo
    (área de trabalho + pasta + nome) estoura o limite do Explorer."""
    nome = AC.nome_arquivo_analise("PN-1", "DESCRICAO MUITO LONGA " * 20)
    assert len(nome) <= 125 and nome.endswith(".pdf")


# ══════════════════════════════════════════════════════════════════════════════
# 5. Frescor do SC7 e auditoria
# ══════════════════════════════════════════════════════════════════════════════


def test_sc7_frescor_sem_import_e_diferente_de_desatualizado(db):
    """ "Nunca houve" e "houve e envelheceu" pedem mensagens diferentes na tela."""
    frescor = AC.sc7_frescor(hoje=HOJE)
    assert frescor["sem_import"] is True
    assert frescor["desatualizado"] is False, "sem import não é 'desatualizado'"
    assert frescor["data"] is None


@pytest.mark.parametrize("dias,esperado", [(0, False), (30, False), (31, True), (120, True)])
def test_sc7_frescor_alerta_depois_de_um_mes(db, dias, esperado):
    quando = (HOJE - timedelta(days=dias)).isoformat()
    conn = db.get_connection()
    conn.execute(
        """INSERT INTO consumo_sc7 (numero_pc, produto, dt_emissao, qtd_entregue, saldo, data_importacao)
           VALUES ('F1','PN-F','2026-01-01',1,0,?)""",
        (f"{quando} 08:00:00",),
    )
    conn.commit()
    conn.close()

    frescor = AC.sc7_frescor(hoje=HOJE)

    assert frescor["dias"] == dias
    assert frescor["desatualizado"] is esperado


def test_auditoria_guarda_pns_versao_do_sc7_e_modo(db, make_item):
    item_id = make_item(part_number="PN-AUD", estoque=0, minimo=5)
    conn = db.get_connection()
    _pedido_sc7(conn, "PN-AUD", emissao="2026-03-01", entregue=70)
    conn.close()

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)
    id_analise = AC.registrar_analise([dados], usuario="Jasiva Lopes", hoje=HOJE)

    assert id_analise
    registro = AC.listar_analises()[0]
    assert registro["usuario"] == "Jasiva Lopes"
    assert registro["part_numbers"] == "PN-AUD"
    assert registro["n_itens"] == 1
    assert registro["modo"] == AC.MODO_SC7
    assert registro["sc7_data_importacao"] == "2026-08-09", (
        "sem a versão do SC7 dois PDFs do mesmo item ficam indistinguíveis no registro"
    )


def test_auditoria_marca_lote_misto(db, make_item):
    """Lote com item de SC7 e item sem: o registro não pode alegar uma fonte só."""
    com = make_item(part_number="PN-COM", estoque=0, minimo=5)
    sem = make_item(part_number="PN-SEM", estoque=0, minimo=5)
    conn = db.get_connection()
    _pedido_sc7(conn, "PN-COM", emissao="2026-03-01", entregue=70)
    conn.close()

    lote = [AC.montar_dados_analise(i, hoje=HOJE) for i in (com, sem)]
    AC.registrar_analise(lote, usuario="Luis", hoje=HOJE)

    assert AC.listar_analises()[0]["modo"] == "misto"
    assert AC.listar_analises()[0]["n_itens"] == 2


def test_registrar_analise_de_lote_vazio_nao_grava(db):
    assert AC.registrar_analise([], usuario="Luis") is None
    assert AC.listar_analises() == []


# ══════════════════════════════════════════════════════════════════════════════
# 6. Schema — aditivo e idempotente
# ══════════════════════════════════════════════════════════════════════════════


def test_tabela_de_auditoria_e_idempotente(db, make_item):
    """`criar_banco()` roda a cada boot do app: rodar de novo não pode apagar registro."""
    item_id = make_item(part_number="PN-IDEM", estoque=0, minimo=5)
    AC.registrar_analise([AC.montar_dados_analise(item_id, hoje=HOJE)], usuario="Luis", hoje=HOJE)

    db.criar_banco()  # segunda abertura do app

    assert len(AC.listar_analises()) == 1, "a migração apagou a auditoria"


def test_tabela_de_auditoria_tem_as_colunas_do_plano(db):
    conn = db.get_connection()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(analises_geradas)").fetchall()}
    conn.close()
    assert {"data_hora", "usuario", "part_numbers", "n_itens", "sc7_data_importacao", "modo"} <= cols


# ══════════════════════════════════════════════════════════════════════════════
# 7. Anti-duplicação — o número do documento é o MESMO da tela
# ══════════════════════════════════════════════════════════════════════════════


def test_o_consumo_sc7_do_documento_e_o_mesmo_da_ficha_360(db, make_item):
    """Se estes dois divergirem, existe uma segunda fórmula de consumo no sistema — que é
    exatamente o que a regra de ouro da v6.10.0 proíbe."""
    from services.consumo_sc7 import consumo_sc7_por_item

    item_id = make_item(part_number="PN-MESMO", estoque=0, minimo=5)
    conn = db.get_connection()
    _pedido_sc7(conn, "PN-MESMO", emissao="2026-04-01", entregue=140)
    da_ficha = consumo_sc7_por_item(conn, item_id=item_id, hoje=HOJE)[item_id]
    conn.close()

    do_documento = AC.montar_dados_analise(item_id, hoje=HOJE)

    assert do_documento["consumo_mensal"] == da_ficha["consumo_mensal"] == 20.0


def test_as_duas_telas_usam_o_MESMO_componente_de_revisao():
    """A Análise é pedida de dois lugares (Assistente e Ficha 360) e a revisão obrigatória
    é a garantia de que nada sai sem alguém ler. Duplicada nas duas telas, ela divergiria —
    e o lado esquecido continuaria liberando download sem confirmação."""
    componente = (PROJ / "ui" / "componentes" / "analise.py").read_text(encoding="utf-8")
    assert "def revisao_e_download" in componente
    assert "def aviso_sc7_desatualizado" in componente

    for pagina in ("controle_sc.py", "ficha_360.py"):
        fonte = (PROJ / "ui" / "paginas" / pagina).read_text(encoding="utf-8")
        assert "from ui.componentes.analise import" in fonte, f"{pagina} não usa o componente"
        assert "revisao_e_download(" in fonte, f"{pagina} não chama a revisão"
        assert "Revisado e de acordo" not in fonte, (
            f"{pagina} reimplementou a revisão em vez de reusar o componente"
        )


def test_reportlab_faltando_avisa_em_vez_de_derrubar_a_pagina(monkeypatch):
    """Aconteceu na validação de 17/08/2026: o import do reportlab vive DENTRO das funções
    de PDF, então o app subia, a Ficha abria, a revisão era feita — e o
    `ModuleNotFoundError` estourava no `download_button`. No Streamlit uma exceção não
    tratada derruba o render inteiro: a pessoa perdia a Ficha toda, com um stack trace no
    lugar, depois de ter revisado o documento.

    A checagem tem de vir ANTES da revisão, e devolver mensagem em vez de explodir."""
    import builtins

    from ui.componentes import analise as componente

    assert componente.reportlab_indisponivel() is None, "com reportlab instalado, nada a avisar"

    real_import = builtins.__import__

    def _sem_reportlab(nome, *args, **kwargs):
        if nome == "reportlab" or nome.startswith("reportlab."):
            raise ImportError("simulado: reportlab ausente")
        return real_import(nome, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _sem_reportlab)
    aviso = componente.reportlab_indisponivel()

    assert aviso and "reportlab" in aviso
    assert "pip install" in aviso, "o aviso tem de dizer COMO resolver"


def test_a_checagem_da_dependencia_vem_antes_da_revisao():
    """Descobrir que o PDF não sai depois de revisar item por item é o pior momento
    possível para dar a notícia."""
    fonte = (PROJ / "ui" / "componentes" / "analise.py").read_text(encoding="utf-8")
    corpo = fonte[fonte.index("def revisao_e_download") :]
    assert corpo.index("reportlab_indisponivel()") < corpo.index("_cartao_revisao("), (
        "a checagem tem de acontecer antes de desenhar os cartões de revisão"
    )


def test_o_seletor_do_assistente_nao_se_limita_a_fila_de_criticos():
    """Pedido do Luis (17/08/2026): escolher QUALQUER item, independente de status ou tipo.

    A tabela da aba lista só o crítico sem SC aberta (`base_criticos` → `filtradas`) — o
    recorte certo para abrir SC e o errado para o documento. Se o `multiselect` da análise
    voltar a ser alimentado por essa lista, o comprador perde de novo a capacidade de
    justificar compra de item que ainda não ficou crítico."""
    fonte = (PROJ / "ui" / "paginas" / "controle_sc.py").read_text(encoding="utf-8")
    bloco = fonte[fonte.index("def _render_analise_consumo") : fonte.index("def _render_import_relatorio")]

    assert "inventario_cached()" in bloco, "o seletor tem de varrer o inventário inteiro"
    assert "st.multiselect(" in bloco
    for fila in ("base_criticos", "filtradas", "sugestoes"):
        assert fila not in bloco, f"o seletor voltou a depender da fila de reposição ({fila})"
    # O que veio marcado na tabela entra como PADRÃO — o caminho comum segue sendo 1 clique.
    assert "default=ids_marcados" in bloco


def test_item_inexistente_falha_alto(db):
    """Erro claro em vez de PDF com campos vazios — documento mudo é pior que erro."""
    with pytest.raises(ValueError):
        AC.montar_dados_analise(999999, hoje=HOJE)


def test_data_do_sc7_vai_impressa_no_documento(db, make_item):
    """O PDF vive sozinho num e-mail: tem de carregar a idade da própria fonte."""
    item_id = make_item(part_number="PN-DATA", estoque=0, minimo=5)
    conn = db.get_connection()
    _pedido_sc7(conn, "PN-DATA", emissao="2026-03-01", entregue=70)
    conn.close()

    dados = AC.montar_dados_analise(item_id, hoje=HOJE)

    assert dados["sc7_importado_em"] == "2026-08-09"
    assert AC._data_br(dados["sc7_importado_em"]) == "09/08/2026"
    assert isinstance(dados["gerado_em"], date) and not isinstance(dados["gerado_em"], datetime)
