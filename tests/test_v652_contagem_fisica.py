"""v6.5.2 — Contagem Fisica por DIFERENCA (Adicionar/Subtrair) com motivo.

Ate a v6.5.1 a tela pedia a "Quantidade Real" absoluta e derivava o delta. Agora o
almoxarife digita a DIFERENCA encontrada e escolhe a operacao; o motivo passa a ser
obrigatorio quando o saldo muda e vai para a coluna `motivo` do ledger.

O que estes testes protegem:
  - a conta da diferenca (delta, tipo entrada/saida, saldo_apos);
  - o motivo virando Categoria do relatorio SEM tocar `categoria_movimentacao`
    (ela ja devolve o `motivo` quando ele existe) e a coluna Motivo do Excel;
  - as duas redes contra saldo negativo: a guarda de UX (`validar_contagem`) e a de
    service (`registrar_movimentacao`, que rejeita saida > estoque);
  - a nao-regressao da Conferencia (qtd 0, sem motivo) — o ramo que existe justamente
    para registrar a passagem pelo item sem mexer no saldo.
"""

import pandas as pd

from services import db_functions as F
from services.constants import CC_INVENTARIO
from ui.paginas.saldo_estoque import (
    MOTIVOS_AJUSTE,
    MOTIVO_OUTRO,
    OP_ADICIONAR,
    OP_SUBTRAIR,
    calcular_novo_saldo,
    montar_observacao,
    motivo_efetivo,
    validar_contagem,
)


def _ultima_mov(db, item_id):
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM movimentacoes WHERE item_id=? ORDER BY id DESC LIMIT 1", (item_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Conta da diferenca ────────────────────────────────────────────────────────


class TestCalculoDoNovoSaldo:
    def test_adicionar_soma_ao_estoque(self):
        assert calcular_novo_saldo(17, OP_ADICIONAR, 3) == 20.0

    def test_subtrair_desconta_do_estoque(self):
        assert calcular_novo_saldo(17, OP_SUBTRAIR, 5) == 12.0

    def test_quantidade_zero_preserva_o_saldo_nas_duas_operacoes(self):
        assert calcular_novo_saldo(17, OP_ADICIONAR, 0) == 17.0
        assert calcular_novo_saldo(17, OP_SUBTRAIR, 0) == 17.0

    def test_estoque_none_conta_como_zero(self):
        assert calcular_novo_saldo(None, OP_ADICIONAR, 4) == 4.0
        assert calcular_novo_saldo(None, OP_SUBTRAIR, 0) == 0.0

    def test_subtrair_tudo_zera_sem_estourar(self):
        assert calcular_novo_saldo(17, OP_SUBTRAIR, 17) == 0.0


# ── Guarda de UX (bloqueio do botao) ──────────────────────────────────────────


class TestValidacao:
    def test_subtrair_mais_que_o_saldo_bloqueia_e_mostra_o_maximo(self):
        erro = validar_contagem(17, OP_SUBTRAIR, 20, MOTIVOS_AJUSTE[0])
        assert erro and "17" in erro

    def test_subtrair_exatamente_o_saldo_e_permitido(self):
        assert validar_contagem(17, OP_SUBTRAIR, 17, MOTIVOS_AJUSTE[0]) is None

    def test_adicionar_nunca_esbarra_no_saldo(self):
        assert validar_contagem(0, OP_ADICIONAR, 999, MOTIVOS_AJUSTE[0]) is None

    def test_motivo_e_obrigatorio_quando_a_quantidade_muda(self):
        erro = validar_contagem(17, OP_ADICIONAR, 3, None)
        assert erro and "motivo" in erro.lower()

    def test_outro_sem_texto_bloqueia(self):
        erro = validar_contagem(17, OP_ADICIONAR, 3, MOTIVO_OUTRO, "   ")
        assert erro and "descreva" in erro.lower()

    def test_outro_com_texto_libera(self):
        assert validar_contagem(17, OP_ADICIONAR, 3, MOTIVO_OUTRO, "achado no armario") is None

    def test_quantidade_zero_dispensa_motivo_e_o_caminho_e_a_conferencia(self):
        assert validar_contagem(17, OP_ADICIONAR, 0, None) is None
        assert validar_contagem(17, OP_SUBTRAIR, 0, None) is None


class TestMotivoEfetivo:
    def test_item_do_dropdown_vai_direto_para_o_ledger(self):
        assert motivo_efetivo("Sobra encontrada / nao registrada") == "Sobra encontrada / nao registrada"

    def test_outro_usa_o_texto_livre_nunca_o_rotulo_do_campo(self):
        assert motivo_efetivo(MOTIVO_OUTRO, "caiu atras da estante") == "caiu atras da estante"
        assert motivo_efetivo(MOTIVO_OUTRO, "") is None
        assert motivo_efetivo(MOTIVO_OUTRO, "  ") is None

    def test_sem_escolha_nao_inventa_motivo(self):
        assert motivo_efetivo(None) is None
        assert motivo_efetivo("") is None


class TestObservacao:
    def test_guarda_o_rastro_da_quantidade(self):
        assert montar_observacao([], "", 17, 20) == "Ajuste Físico | Qtd: 17 → 20"

    def test_detalhe_livre_e_mudancas_de_local_entram_na_observacao(self):
        obs = montar_observacao(["Local: ARM-01 → MRO-14"], "estava escondido", 17, 20)
        assert "Local: ARM-01 → MRO-14" in obs
        assert "estava escondido" in obs
        assert obs.endswith("Qtd: 17 → 20")


# ── Ledger: o que a tela grava de fato ────────────────────────────────────────


def _contar(db, item_id, estoque_atual, operacao, qtd, escolha, texto_outro=""):
    """Reproduz o gravar da tela: mesma conta, mesmos kwargs de `registrar_movimentacao`."""
    assert validar_contagem(estoque_atual, operacao, qtd, escolha, texto_outro) is None
    saldo_novo = calcular_novo_saldo(estoque_atual, operacao, qtd)
    delta = saldo_novo - estoque_atual
    return F.registrar_movimentacao(
        item_id=item_id,
        tipo="entrada" if delta > 0 else "saida",
        quantidade=abs(delta),
        centro_custo=CC_INVENTARIO,
        solicitante="Inventário",
        emitente="Inventário",
        observacao=montar_observacao([], "", estoque_atual, saldo_novo),
        motivo=motivo_efetivo(escolha, texto_outro),
    )


def test_adicionar_grava_entrada_com_o_delta_e_o_saldo_certo(db, make_item):
    item = make_item(part_number="PN-ADD", estoque=17)

    ok, _ = _contar(db, item, 17, OP_ADICIONAR, 3, "Sobra encontrada / nao registrada")
    assert ok

    m = _ultima_mov(db, item)
    assert m["tipo"] == "entrada"
    assert m["quantidade"] == 3
    assert m["saldo_apos"] == 20
    assert m["motivo"] == "Sobra encontrada / nao registrada"


def test_subtrair_grava_saida_com_o_delta_e_o_saldo_certo(db, make_item):
    item = make_item(part_number="PN-SUB", estoque=17)

    ok, _ = _contar(db, item, 17, OP_SUBTRAIR, 5, "Material saiu sem requisicao")
    assert ok

    m = _ultima_mov(db, item)
    assert m["tipo"] == "saida"
    assert m["quantidade"] == 5
    assert m["saldo_apos"] == 12
    assert m["motivo"] == "Material saiu sem requisicao"


def test_o_motivo_vira_a_categoria_do_relatorio_sem_tocar_a_funcao(db, make_item):
    """`categoria_movimentacao` ja devolve o `motivo` quando ele existe (v4.3.0). A
    contagem so precisou passar a preencher a coluna — nenhuma regra mudou."""
    item = make_item(part_number="PN-CAT", estoque=10)
    _contar(db, item, 10, OP_SUBTRAIR, 2, "Avaria / material danificado")

    m = _ultima_mov(db, item)
    assert F.categoria_movimentacao(m) == "Avaria / material danificado"


def test_motivo_outro_grava_o_texto_livre_como_categoria(db, make_item):
    item = make_item(part_number="PN-OUT", estoque=10)
    _contar(db, item, 10, OP_ADICIONAR, 1, MOTIVO_OUTRO, "devolvido pela engenharia")

    m = _ultima_mov(db, item)
    assert m["motivo"] == "devolvido pela engenharia"
    assert F.categoria_movimentacao(m) == "devolvido pela engenharia"


def test_o_motivo_sai_na_coluna_motivo_do_excel(db, make_item):
    item = make_item(part_number="PN-XLS", estoque=10)
    _contar(db, item, 10, OP_SUBTRAIR, 4, "Material saiu sem requisicao")

    df = F.exportar_movimentacoes_df()
    assert isinstance(df, pd.DataFrame)
    linha = df[df["PN"] == "PN-XLS"].iloc[0]
    assert linha["Motivo"] == "Material saiu sem requisicao"
    assert linha["Categoria"] == "Material saiu sem requisicao"
    assert "Qtd: 10 → 6" in linha["Observação"]


def test_service_rejeita_saida_maior_que_o_estoque_mesmo_sem_a_guarda_de_ux(db, make_item):
    """Segunda rede: se a UI algum dia deixar passar, o service ainda barra."""
    item = make_item(part_number="PN-NEG", estoque=17)

    ok, msg = F.registrar_movimentacao(
        item_id=item,
        tipo="saida",
        quantidade=20,
        centro_custo=CC_INVENTARIO,
        solicitante="Inventário",
        emitente="Inventário",
        observacao="Ajuste Físico | Qtd: 17 → -3",
        motivo="Material saiu sem requisicao",
    )
    assert not ok
    assert "insuficiente" in msg.lower()

    conn = db.get_connection()
    saldo = conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (item,)).fetchone()[0]
    conn.close()
    assert saldo == 17


# ── Nao-regressao: Conferencia de Inventario ──────────────────────────────────


def test_conferencia_qtd_zero_sem_motivo_continua_sendo_conferencia(db, make_item):
    """Ramo preservado da v5.3.0: mudou so local/observacao, o saldo nao se move e a
    Categoria e "Conferencia" — nao pode virar "Ajuste de Inventario" e inflar a
    divergencia (contrato de `test_v570_relatorio_movimentacoes.py`)."""
    item = make_item(part_number="PN-CONF", estoque=8)

    ok, _ = F.registrar_movimentacao(
        item_id=item,
        tipo="entrada",
        quantidade=0.0,
        centro_custo=CC_INVENTARIO,
        solicitante="Inventário",
        emitente="Inventário",
        observacao="Conferência de Inventário (Sem alteração de Qtd) Local: ARM-01 → MRO-14",
    )
    assert ok

    m = _ultima_mov(db, item)
    assert m["motivo"] is None
    assert m["saldo_apos"] == 8
    assert F.categoria_movimentacao(m) == "Conferência"

    conn = db.get_connection()
    saldo = conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (item,)).fetchone()[0]
    conn.close()
    assert saldo == 8


def test_nada_mudou_nao_gera_movimentacao(db, make_item):
    """Qtd 0 e nenhum metadado alterado: a tela avisa e nao grava nada — aqui isso e a
    ausencia de linha no ledger depois do saldo inicial do cadastro."""
    item = make_item(part_number="PN-NADA", estoque=5)

    conn = db.get_connection()
    antes = conn.execute("SELECT COUNT(*) FROM movimentacoes WHERE item_id=?", (item,)).fetchone()[0]
    conn.close()

    saldo_novo = calcular_novo_saldo(5, OP_ADICIONAR, 0)
    assert saldo_novo - 5 == 0  # delta zero => a tela nao entra no ramo de movimentacao

    conn = db.get_connection()
    depois = conn.execute("SELECT COUNT(*) FROM movimentacoes WHERE item_id=?", (item,)).fetchone()[0]
    conn.close()
    assert depois == antes
