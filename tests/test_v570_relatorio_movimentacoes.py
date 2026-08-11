"""v5.7.0 (CP4) — Relatório de Movimentações: período, teto removido e colunas explodidas.

Item 9 do pedido de 26/07/2026 + decisões nº6, nº7 e nº3 da entrevista de 27/07/2026.

Três defeitos andam juntos aqui, e por isso os testes também:

1. **Teto silencioso.** `exportar_movimentacoes_df` buscava `limit=5000` sobre um ledger
   ordenado por data DESCENDENTE — o corte caía sempre na cauda, apagando as movimentações
   mais ANTIGAS sem uma linha de aviso. Com 2.822 linhas em três meses, o histórico
   começaria a sumir em ~6 meses.
2. **Observação como depósito.** Nº da requisição, NF, PO e SC já existiam no banco em
   colunas e FKs, mas a planilha só entregava a string montada por código. Auditar exigia
   ler texto com o olho.
3. **Ajustes indistinguíveis.** Os três caminhos de ajuste (inventário físico, edição de
   cadastro, correção de balcão) desabavam todos em "Entrada"/"Saída", tornando impossível
   somar perda sem contaminar com correção de cadastro.

O que estes testes protegem, em uma frase: **a FK manda, o texto é fallback do legado, e
nada é cortado em silêncio.**
"""

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from services import db_functions as F
from services.constants import CC_EDICAO, CC_INVENTARIO

CC = "21106 - MANUTENÇÃO"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mov_bruta(db, item_id, **campos):
    """INSERT direto no ledger — o único jeito de reproduzir o LEGADO, em que `motivo` é
    NULL (0% preenchido nas 2.822 linhas reais) e a origem só aparece no texto."""
    campos.setdefault("tipo", "saida")
    campos.setdefault("quantidade", 1.0)
    campos.setdefault("data_hora", "2026-05-10 08:00:00")
    campos["item_id"] = item_id
    cols = ",".join(campos)
    conn = db.get_connection()
    try:
        cur = conn.execute(
            f"INSERT INTO movimentacoes ({cols}) VALUES ({','.join('?' * len(campos))})",
            tuple(campos.values()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _linha(db, item_id, **campos):
    """A movimentação recém-inserida, já explodida nas colunas do relatório.

    Busca pelo `id` devolvido, nunca por `[0]`: o ledger é ordenado por `data_hora` e
    lançamentos do mesmo segundo empatam — indexar pela posição pegaria a linha errada."""
    mov_id = _mov_bruta(db, item_id, **campos)
    mov = next(m for m in F.listar_movimentacoes(item_id=item_id, limit=None) if m["id"] == mov_id)
    return F._explodir_linha_movimentacao(mov)


# ══════════════════════════════════════════════════════════════════════════════
# listar_movimentacoes — período e ausência de teto
# ══════════════════════════════════════════════════════════════════════════════


def test_periodo_e_fechado_no_ultimo_dia(db, make_item):
    """A armadilha do fim-do-dia: `data_hora` é TEXT e a comparação é lexicográfica.
    Sem o '23:59:59' explícito, `<= '2026-05-10'` descartaria TODAS as movimentações do
    próprio dia 10 (que gravam hora) — o usuário pediria "até dia 10" e perderia o dia 10."""
    item = make_item("PN-PER", estoque=0)
    _mov_bruta(db, item, tipo="entrada", quantidade=5, data_hora="2026-05-10 14:08:23")

    assert len(F.listar_movimentacoes(item_id=item, data_fim="2026-05-10")) == 1
    assert len(F.listar_movimentacoes(item_id=item, data_inicio="2026-05-10")) == 1
    # E o recorte de fato exclui o que está fora.
    assert F.listar_movimentacoes(item_id=item, data_fim="2026-05-09") == []
    assert F.listar_movimentacoes(item_id=item, data_inicio="2026-05-11") == []


def test_periodo_aceita_objeto_date_da_tela(db, make_item):
    """`st.date_input` devolve `date`, não string — a borda não deve ter de converter."""
    item = make_item("PN-DATE", estoque=0)
    _mov_bruta(db, item, tipo="entrada", quantidade=5, data_hora="2026-05-10 14:08:23")
    achadas = F.listar_movimentacoes(item_id=item, data_inicio=date(2026, 5, 10), data_fim=date(2026, 5, 10))
    assert len(achadas) == 1


def test_limit_none_traz_tudo_e_default_preserva_o_contrato(db, make_item):
    """`limit=None` = sem LIMIT. O default 200 continua valendo para o Histórico e a
    Ficha 360, que já chamavam a função — estender não pode mudar quem já usava."""
    item = make_item("PN-LIM", estoque=0)
    for i in range(210):
        _mov_bruta(db, item, tipo="entrada", quantidade=1, data_hora=f"2026-05-10 08:{i % 60:02d}:00")

    assert len(F.listar_movimentacoes(item_id=item)) == 200  # default intacto
    assert len(F.listar_movimentacoes(item_id=item, limit=None)) == 210
    assert len(F.listar_movimentacoes(item_id=item, limit=5)) == 5


def test_exportacao_nao_corta_as_movimentacoes_mais_antigas(db, make_item):
    """A regressão exata do teto de 5.000: como o ledger vem em ordem DESCENDENTE, o corte
    comia a cauda — justamente o histórico antigo que a auditoria procura."""
    item = make_item("PN-TETO", estoque=0)
    conn = db.get_connection()
    try:
        conn.executemany(
            "INSERT INTO movimentacoes (item_id,tipo,quantidade,data_hora,observacao) VALUES (?,?,?,?,?)",
            [
                (item, "entrada", 1.0, f"2026-06-{1 + i // 400:02d} {i % 24:02d}:00:00", "")
                for i in range(5010)
            ]
            + [(item, "entrada", 1.0, "2026-04-16 14:08:23", "A MAIS ANTIGA DE TODAS")],
        )
        conn.commit()
    finally:
        conn.close()

    df = F.exportar_movimentacoes_df(item_id=item)
    assert len(df) == 5011  # 5.010 + a mais antiga: nenhuma cortada
    assert "A MAIS ANTIGA DE TODAS" in set(df["Observação"]), (
        "o teto de 5.000 voltou: a movimentação mais antiga sumiu da exportação"
    )


# ══════════════════════════════════════════════════════════════════════════════
# categoria_movimentacao — os três caminhos de ajuste (decisão nº7)
# ══════════════════════════════════════════════════════════════════════════════


def test_conferencia_vence_antes_de_qualquer_derivacao():
    """Ordem preservada de propósito (afirmada desde a v4.3.0): contagem sem alteração de
    saldo é Conferência, não "Ajuste de Inventário" — senão a divergência do mês inflaria
    com 195 linhas que, por definição, não mudaram nada."""
    m = {"tipo": "entrada", "quantidade": 0, "centro_custo": CC_INVENTARIO}
    assert F.categoria_movimentacao(m) == "Conferência"


def test_tres_caminhos_de_ajuste_nao_se_confundem_mais():
    """O coração do CP4: antes os três caíam juntos em "Entrada"/"Saída"."""
    inventario = {"tipo": "saida", "quantidade": 3, "centro_custo": CC_INVENTARIO}
    edicao = {"tipo": "entrada", "quantidade": 2, "centro_custo": CC_EDICAO}
    balcao = {"tipo": "saida", "quantidade": 1, "observacao": "AJUSTE: MATERIAL PAGO SEM REQUISIÇÃO"}

    assert F.categoria_movimentacao(inventario) == "Ajuste de Inventário"
    assert F.categoria_movimentacao(edicao) == "Ajuste por Edição"
    assert F.categoria_movimentacao(balcao) == "Ajuste Manual"
    assert len({F.categoria_movimentacao(m) for m in (inventario, edicao, balcao)}) == 3


@pytest.mark.parametrize(
    "observacao",
    [
        "Ajuste Físico Obs: '' → 'AJUSTE DE INVENTÁRIO'",
        "Ajuste de Qtd: 20.0 -> 1.0",
        "Ajuste via tela de Inventário: 26.0 -> 8.0",
        "174 UN Caixa: MRO 13→TENDA",
        "Ajuste de inventário físico: 18.0 → 22.0",
    ],
)
def test_templates_legados_do_inventario_caem_todos_no_mesmo_rotulo(observacao):
    """A tela de Inventário trocou de template cinco vezes ao longo das versões, mas nunca
    trocou o centro de custo — é por isso que a derivação se apoia nele, e não no texto."""
    m = {
        "tipo": "saida",
        "quantidade": 3,
        "centro_custo": CC_INVENTARIO,
        "observacao": observacao,
    }
    assert F.categoria_movimentacao(m) == "Ajuste de Inventário"


def test_ajuste_rapido_novo_usa_o_motivo_e_nao_a_derivacao():
    """Lançamento pós-v4.3.0 traz `motivo`: ele manda, e é o que permite somar PERDA sem
    varrer junto correção de cadastro (a primeira pergunta da decisão nº7)."""
    perda = {"motivo": "Perda de Material", "tipo": "saida", "quantidade": 2, "observacao": "AJUSTE: caiu"}
    assert F.categoria_movimentacao(perda) == "Perda de Material"


def test_saldo_inicial_do_cadastro_nao_vira_ajuste_por_edicao(db, make_item):
    """`_mov_inline` grava CC='EDIÇÃO' nos DOIS casos — saldo inicial e ajuste por edição.
    Sem o prefixo o cadastro de item novo seria contado como correção de saldo."""
    item = make_item("PN-SALDO-INI", estoque=40)
    mov = F.listar_movimentacoes(item_id=item, limit=None)[-1]
    assert mov["observacao"] == "Saldo inicial (cadastro)"
    assert F.categoria_movimentacao(mov) == "Saldo Inicial"


def test_requisicao_continua_vencendo_a_derivacao_por_texto():
    """O vínculo é checado ANTES do CC: uma saída por requisição feita a partir da tela de
    Inventário continua sendo consumo, não ajuste."""
    m = {"tipo": "saida", "quantidade": 5, "requisicao_id": 9, "centro_custo": CC_INVENTARIO}
    assert F.categoria_movimentacao(m) == "Requisição"


# ══════════════════════════════════════════════════════════════════════════════
# _explodir_linha_movimentacao — FK manda, texto é fallback
# ══════════════════════════════════════════════════════════════════════════════


def test_fk_da_requisicao_vence_e_a_observacao_sobra_vazia(db, make_item):
    """Nas 1.887 saídas por requisição do histórico real a Observação é só 'Req REQ-…' —
    100% redundante com a coluna nova. O resíduo tem de ser vazio, não repetido."""
    item = make_item("PN-EXPL-REQ", estoque=50)
    ok, res = F.criar_requisicao_com_baixa(
        "MANUTENÇÃO",
        "Joao",
        CC,
        "Gestor",
        "Chefe",
        False,
        [],
        False,
        "",
        [{"item_id": item, "quantidade_solicitada": 4}],
    )
    assert ok, res
    num = res["numero"]

    linha = next(
        x
        for x in (F._explodir_linha_movimentacao(m) for m in F.listar_movimentacoes(item_id=item, limit=None))
        if x["Categoria"] == "Requisição"
    )
    assert linha["Nº Requisição"] == num
    assert linha["Observação"] == "", "o número da requisição virou coluna; não pode sobrar no texto"
    # CP3: os dois fluxos gravam o mesmo ledger — a Padrão não é caso à parte aqui.
    assert linha["Fluxo"] == F.FLUXO_PADRAO
    assert linha["Centro de Custo"] == CC
    assert linha["Setor"] == "MANUTENÇÃO"


def test_fluxo_digital_e_legado_saem_distinguiveis(db, make_item):
    """`tipo_fluxo` é NULL em todo o histórico anterior à v5.7.0: célula vazia, não
    "Padrão" presumido — presumir seria inventar dado que ninguém registrou."""
    item = make_item("PN-EXPL-FLUXO", estoque=50)
    ok, num = F.criar_requisicao(
        "SMT", "Ana", CC, "", "", False, [], False, "", [{"item_id": item, "quantidade_solicitada": 2}]
    )
    assert ok, num
    conn = db.get_connection()
    rid = conn.execute("SELECT id FROM requisicoes WHERE numero_requisicao=?", (num,)).fetchone()["id"]
    conn.close()
    F.entregar_requisicao(
        rid,
        [{"item_req_id": F.listar_itens_requisicao(rid)[0]["id"], "quantidade": 2}],
        "Gestor",
        "Chefe",
    )
    digital = next(
        x
        for x in (F._explodir_linha_movimentacao(m) for m in F.listar_movimentacoes(item_id=item, limit=None))
        if x["Categoria"] == "Requisição"
    )
    assert digital["Fluxo"] == F.FLUXO_DIGITAL

    # Legado: saída com requisicao_id mas sem tipo_fluxo gravado.
    conn = db.get_connection()
    conn.execute("UPDATE requisicoes SET tipo_fluxo=NULL WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    legado = next(
        x
        for x in (F._explodir_linha_movimentacao(m) for m in F.listar_movimentacoes(item_id=item, limit=None))
        if x["Categoria"] == "Requisição"
    )
    assert legado["Fluxo"] == ""
    assert legado["Nº Requisição"] == num, "sem tipo_fluxo o número ainda tem de sair pela FK"


def test_fk_da_nf_vence_o_texto_que_mente(db, make_item, make_sc):
    """Caso real do mro.db: a Observação guarda 'F61846' (que é o PO, não a NF) enquanto
    `itens_sc.documento_nf` traz 169357. Se o texto ganhasse, a auditoria leria errado."""
    item = make_item("PN-EXPL-NF", estoque=0)
    sc_id = make_sc(numero_sc="41494", item_id=item)
    conn = db.get_connection()
    isc = conn.execute("SELECT id FROM itens_sc WHERE sc_id=?", (sc_id,)).fetchone()["id"]
    conn.execute("UPDATE itens_sc SET documento_nf='169357', numero_po='F61846' WHERE id=?", (isc,))
    conn.commit()
    conn.close()

    linha = _linha(db, item, tipo="entrada", quantidade=10, observacao="F61846", sc_item_id=isc)
    assert linha["NF"] == "169357"
    assert linha["SC/PO"] == "SC 41494 · PO F61846"
    assert linha["Observação"] == "F61846", "sem FK de NF no texto, o resíduo é preservado como está"


def test_fallback_de_texto_cobre_o_legado_sem_fk(db, make_item):
    """Linhas anteriores às FKs: o regex é a rede, e só ela."""
    item = make_item("PN-EXPL-LEG", estoque=0)

    req = _linha(db, item, observacao="Requisição REQ-20260504-006", quantidade=2)
    assert req["Nº Requisição"] == "REQ-20260504-006"
    assert req["Observação"] == ""

    # v6.5.0 — o número virou sequencial, mas as 2.320 observações antigas não foram
    # reescritas: o regex tem de reconhecer OS DOIS formatos, ou o legado volta a sujar a
    # coluna Observação com o texto que já virou coluna própria.
    novo = _linha(db, item, observacao="Req 123", quantidade=4)
    assert novo["Nº Requisição"] == "123"
    assert novo["Observação"] == ""

    nf = _linha(db, item, tipo="entrada", quantidade=3, observacao="NF: NF 315900")
    assert nf["NF"] == "NF 315900"
    assert nf["Observação"] == ""


def test_residuo_preserva_o_que_nao_virou_coluna(db, make_item):
    """ "O que sobra" é informação real do almoxarife — a extração não pode comê-la."""
    item = make_item("PN-EXPL-RES", estoque=0)

    conv = _linha(
        db,
        item,
        tipo="entrada",
        quantidade=5,
        observacao="NF: NF 315900 · convertido: 10 CX ÷ 2 = 5 UN",
    )
    assert conv["NF"] == "NF 315900"
    assert conv["Observação"] == "convertido: 10 CX ÷ 2 = 5 UN"

    balcao = _linha(db, item, observacao="AJUSTE: MATERIAL PAGO SEM REQUISIÇÃO")
    assert balcao["Categoria"] == "Ajuste Manual"
    assert balcao["Observação"] == "MATERIAL PAGO SEM REQUISIÇÃO", "a nota do almoxarife sumiu"

    fisico = _linha(db, item, centro_custo=CC_INVENTARIO, observacao="Ajuste Físico Local: ARM-08 → MRO-14")
    assert fisico["Categoria"] == "Ajuste de Inventário"
    assert fisico["Observação"] == "Ajuste Físico Local: ARM-08 → MRO-14"


def test_ajuste_sai_sem_centro_de_custo(db, make_item):
    """Decisão nº3: ajuste é correção do almoxarifado, não consumo de setor. Célula vazia
    é a informação CORRETA — atribuir um CC a ele contaminaria o rateio do mês."""
    item = make_item("PN-EXPL-CC", estoque=50)
    ok, msg = F.registrar_movimentacao(
        item_id=item,
        tipo="saida",
        quantidade=2,
        centro_custo=None,
        solicitante="Sidinei",
        emitente="Sidinei",
        observacao="AJUSTE: avaria",
        motivo="Perda de Material",
    )
    assert ok, msg
    linha = next(
        F._explodir_linha_movimentacao(m)
        for m in F.listar_movimentacoes(item_id=item, limit=None)
        if m["motivo"]
    )
    assert linha["Categoria"] == "Perda de Material"
    assert linha["Centro de Custo"] == ""
    assert linha["Motivo"] == "Perda de Material"


# ══════════════════════════════════════════════════════════════════════════════
# exportar_movimentacoes_df — o recorte da tela
# ══════════════════════════════════════════════════════════════════════════════


def test_exportacao_recorta_por_periodo(db, make_item):
    item = make_item("PN-EXP-PER", estoque=0)
    _mov_bruta(db, item, tipo="entrada", quantidade=1, data_hora="2026-04-16 14:08:23", observacao="ABRIL")
    _mov_bruta(db, item, tipo="entrada", quantidade=1, data_hora="2026-06-20 09:00:00", observacao="JUNHO")

    junho = F.exportar_movimentacoes_df(item_id=item, data_inicio="2026-06-01", data_fim="2026-06-30")
    assert set(junho["Observação"]) == {"JUNHO"}
    assert len(F.exportar_movimentacoes_df(item_id=item)) == 2  # sem período: tudo


def test_exportacao_vazia_quando_o_periodo_nao_casa_nada(db, make_item):
    item = make_item("PN-EXP-ZERO", estoque=10)
    df = F.exportar_movimentacoes_df(item_id=item, data_inicio="2020-01-01", data_fim="2020-12-31")
    assert df.empty


# ══════════════════════════════════════════════════════════════════════════════
# Smoke de render — a tela (ui/ só tem o smoke por rota; ver regra nº6)
# ══════════════════════════════════════════════════════════════════════════════


def _render_movimentacao(**estado):
    at = AppTest.from_string("from ui.router import render_pagina\nrender_pagina('Movimentação')\n")
    for k, v in estado.items():
        at.session_state[k] = v
    at.run()
    return at


def _textos(at):
    return " ".join(
        str(e.value) for grupo in (at.warning, at.info, at.caption, at.markdown, at.error) for e in grupo
    )


def test_tela_mostra_o_volume_do_recorte(db, make_item):
    """Nunca mais cortar em silêncio: a tela diz quantas linhas saem."""
    item = make_item("PN-UI-VOL", estoque=0)
    for i in range(3):
        _mov_bruta(db, item, tipo="entrada", quantidade=1, data_hora=f"2026-06-2{i} 09:00:00")

    at = _render_movimentacao()
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    texto = _textos(at)
    # Texto exclusivo do bloco novo — sem isto o teste passaria mesmo que ele não rendesse.
    assert "Relatório de Movimentações" in texto
    assert "3 linhas** no recorte" in texto, "a contagem de linhas do recorte não apareceu"


def test_tela_avisa_periodo_invertido(db, make_item):
    make_item("PN-UI-INV", estoque=10)
    at = _render_movimentacao(exp_mov_ini=date(2026, 7, 31), exp_mov_fim=date(2026, 7, 1))
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    assert "período está invertido" in _textos(at)


def test_tela_avisa_recorte_vazio_em_vez_de_sumir_com_o_botao(db, make_item):
    make_item("PN-UI-VAZIO", estoque=10)
    at = _render_movimentacao(exp_mov_ini=date(2020, 1, 1), exp_mov_fim=date(2020, 12, 31))
    assert not at.exception, f"lançou: {[e.value for e in at.exception]}"
    assert "Nenhuma movimentação no recorte" in _textos(at)
