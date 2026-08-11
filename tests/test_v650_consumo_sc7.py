"""v6.5.0 — Task 1: Consumo Mensal baseado em Pedido de Compra (SC7).

Substitui os 14 testes da vida útil do lote (v6.4.0). O que estes protegem:

- **Só pedido ATENDIDO soma.** Pendente é material que ainda não chegou: contá-lo diria
  que o item consome o que ninguém usou. Ele não some — vira alerta no card, porque um
  consumo baixo com 3 pedidos a receber conta uma história diferente de um consumo baixo
  sem nada a caminho.
- **O mês corrente nunca entra.** Dividir um mês em andamento por um mês inteiro derruba o
  número todo dia 1º; é o mesmo princípio de `_ultimos_n_meses_completos`.
- **Ausência de evidência não é evidência de zero.** Linha sem `DT Emissao` ou com
  `Qtd.Entregue` zerada é IGNORADA, não somada como zero — senão um PO cancelado puxaria
  a média do item para baixo.
- **A UM de compra é convertida.** `Qtd.Entregue` vem na UM do pedido e o estoque vive na
  UM de estoque: sem `÷ fator_conversao`, uma caixa de 12 viraria 1 unidade.
- **Reimportar não duplica.** O upsert por `(numero_pc, produto)` atualiza saldo no lugar,
  que é como um pedido parcial vira atendido sem ninguém apagar nada.
"""

from datetime import date

import pandas as pd
import pytest

import database
from services import classificacao as C
from services import consumo_sc7 as CS7
from services import db_functions as F

# 10/08/2026: jan–jul fechados no ano corrente (7 meses), agosto em andamento.
HOJE = date(2026, 8, 10)


def _linha(dt_emissao="2026-03-10", qtd_entregue=10, saldo=0):
    """Linha crua para o núcleo puro — o trio que decide tudo."""
    return {"dt_emissao": dt_emissao, "qtd_entregue": qtd_entregue, "saldo": saldo}


def _pedido(numero_pc="F900", produto="PN-SC7", emissao="2026-03-01", quantidade=10, entregue=10, saldo=0):
    """Linha da aba SC7 com os nomes CRUS do "Relatório de Compras" (sem `Prc Unitario`:
    o consumo não depende de preço, ao contrário de `ingerir_sc7_precos`)."""
    return {
        "Numero PC": numero_pc,
        "DT Emissao": emissao,
        "Produto": produto,
        "Descricao": "Item SC7",
        "Unidade": "UN",
        "Quantidade": quantidade,
        "Qtd.Entregue": entregue,
        "Saldo": saldo,
        "Dt. Entrega": "2026-03-20",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. Núcleo puro — a regra do Luis, sem banco
# ══════════════════════════════════════════════════════════════════════════════


def test_ano_passado_divide_por_12():
    r = CS7._consumo_from_linhas([_linha("2025-02-01", 60), _linha("2025-09-15", 60)], HOJE)

    assert r["ano_anterior"]["consumo_mensal"] == 10.0  # 120 ÷ 12
    assert r["consumo_mensal"] == 10.0  # sem pedido em 2026, a referência é 2025
    assert (r["ano_ref"], r["meses"], r["n_pedidos"]) == (2025, 12, 2)


def test_ano_atual_divide_pelos_meses_decorridos_e_exclui_o_mes_corrente():
    """jan–jul ÷ 7 com `hoje = 10/08/2026`; o pedido de agosto fica de fora."""
    r = CS7._consumo_from_linhas([_linha("2026-01-05", 350), _linha("2026-08-09", 999)], HOJE)

    assert r["ano_atual"]["consumo_mensal"] == 50.0  # 350 ÷ 7
    assert r["ano_atual"]["n_pedidos"] == 1
    assert (r["consumo_mensal"], r["ano_ref"], r["meses"]) == (50.0, 2026, 7)
    assert r["fora_janela"] == 1


def test_ano_atual_e_a_referencia_mas_os_dois_anos_voltam():
    """O card mostra os dois: o comparativo é o que revela compra descolada do giro."""
    r = CS7._consumo_from_linhas([_linha("2025-06-01", 240), _linha("2026-02-01", 70)], HOJE)

    assert (r["ano_ref"], r["consumo_mensal"]) == (2026, 10.0)  # 70 ÷ 7
    assert r["ano_anterior"]["consumo_mensal"] == 20.0  # 240 ÷ 12


def test_janeiro_nao_tem_periodo_fechado_e_cai_no_ano_anterior():
    """Em 20/01 o ano corrente tem 0 meses decorridos — dividir por zero seria o bug."""
    r = CS7._consumo_from_linhas([_linha("2025-06-01", 120), _linha("2026-01-05", 999)], date(2026, 1, 20))

    assert (r["ano_ref"], r["consumo_mensal"]) == (2025, 10.0)
    assert r["ano_atual"]["consumo_mensal"] is None


def test_pendente_nao_soma_e_vira_alerta():
    r = CS7._consumo_from_linhas([_linha("2026-03-01", 70), _linha("2026-04-01", 5, saldo=25)], HOJE)

    assert r["consumo_mensal"] == 10.0  # só os 70 do pedido atendido
    assert r["pendentes"] == {"n": 1, "qtd": 25.0}


def test_sem_dt_emissao_ignora():
    """Sem a data não dá para dizer a que mês o pedido pertence — e o mês é o divisor."""
    r = CS7._consumo_from_linhas(
        [_linha(None, 999), _linha("", 999), _linha("não é data", 999), _linha("2026-03-01", 70)], HOJE
    )

    assert r["ignorados"] == 3 and r["consumo_mensal"] == 10.0


def test_quantidade_zero_nao_conta_como_pedido():
    """PO com saldo zero e nada entregue é pedido cancelado/zerado: ausência de evidência,
    não evidência de consumo zero. Contá-lo puxaria a média do item para baixo."""
    r = CS7._consumo_from_linhas([_linha("2026-03-01", 0)], HOJE)

    assert r["consumo_mensal"] is None
    assert (r["ignorados"], r["n_pedidos"]) == (1, 0)


def test_campos_none_nao_quebram():
    """A planilha traz célula vazia em qualquer coluna; nada aqui pode levantar exceção."""
    so_nulos = CS7._consumo_from_linhas(
        [{"dt_emissao": "2026-03-01", "qtd_entregue": None, "saldo": None}], HOJE
    )
    com_entrega = CS7._consumo_from_linhas(
        [{"dt_emissao": "2026-03-01", "qtd_entregue": 70, "saldo": None}], HOJE
    )

    assert so_nulos["consumo_mensal"] is None
    assert com_entrega["consumo_mensal"] == 10.0


def test_sem_linha_nenhuma_devolve_none():
    r = CS7._consumo_from_linhas([], HOJE)

    assert (r["consumo_mensal"], r["ano_ref"], r["origem"]) == (None, None, None)
    assert r["pendentes"] == {"n": 0, "qtd": 0.0}


@pytest.mark.parametrize(
    "um_compra,fator", [("UN", 1), ("CX", 12), ("GL", 4), ("RL", 100), ("PCT", 50), ("LT", 5), ("RM", 500)]
)
def test_converte_a_um_de_compra_para_a_de_estoque(um_compra, fator):
    """Mesma fórmula do recebimento (`qtd ÷ fator_conversao`): a `Qtd.Entregue` do SC7 está
    na UM do PEDIDO, e o consumo tem de sair na UM em que o estoque é contado."""
    r = CS7._consumo_from_linhas([_linha("2025-01-10", 120 * fator)], HOJE, fator=fator)

    assert r["ano_anterior"]["total_entregue"] == 120.0, um_compra
    assert r["consumo_mensal"] == 10.0


@pytest.mark.parametrize("fator", [0, -3, None, "", "x"])
def test_fator_invalido_vira_1(fator):
    """Item sem conversão curada: dividir por 0 ou por None quebraria a Ficha inteira."""
    assert CS7._consumo_from_linhas([_linha("2025-01-10", 120)], HOJE, fator=fator)["consumo_mensal"] == 10.0


def test_rotulos_de_periodo_e_de_fonte():
    """A `origem` do Mín/Máx e o tooltip do card saem daqui — o gestor precisa saber que
    número está aceitando antes de clicar em "Usar calculado"."""
    assert CS7.rotulo_periodo(2025, 12) == "2025"
    assert CS7.rotulo_periodo(2026, 7) == "2026 (jan–jul)"
    assert CS7.rotulo_periodo(2026, 1) == "2026 (jan)"
    assert CS7.rotulo_periodo(None, 0) == "—"

    info = {"consumo_mensal": 8.0, "origem": "sc7", "ano_ref": 2026, "meses": 7}
    assert CS7.rotulo_consumo(info) == "SC7 2026 (jan–jul)"
    assert CS7.rotulo_consumo({**info, "origem": "scm"}) == "SCM 2026 (jan–jul)"
    assert CS7.rotulo_consumo({"consumo_mensal": None}) is None
    # o tooltip da Ficha usa o rótulo longo, que diz de qual planilha a linha veio
    assert CS7.ROTULO_FONTE["sc7"] == "SC7 (Relatório de Compras)"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Ingestão da planilha → tabela `consumo_sc7`
# ══════════════════════════════════════════════════════════════════════════════


def test_migracao_consumo_sc7_e_idempotente(db):
    """Tabela nova e vazia ao migrar (aditiva, sem `_backup_db`); `criar_banco` roda a cada
    abertura do app, então repetir não pode mudar nada."""
    with db.transaction() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(consumo_sc7)")]
        indices = [r[1] for r in c.execute("PRAGMA index_list(consumo_sc7)")]

    assert {"numero_pc", "produto", "dt_emissao", "quantidade", "qtd_entregue", "saldo", "origem"} <= set(
        cols
    )
    assert "idx_consumo_sc7_produto" in indices

    db.criar_banco()
    with db.transaction() as c:
        assert [r[1] for r in c.execute("PRAGMA table_info(consumo_sc7)")] == cols


def test_grava_pn_fora_do_inventario_e_linha_sem_preco(db):
    """Diferença deliberada em relação a `ingerir_sc7_precos`, que descarta os dois: preço
    só serve para item cadastrado, mas o histórico de compra do PN que ainda vai entrar no
    MRO não pode ser jogado fora (mesma lição de `itens_sc_externos`)."""
    res = F.ingerir_sc7_consumo(pd.DataFrame([_pedido(produto="PN-FORA-DO-MRO")]), "compras.xlsx")

    assert (res["inseridos"], res["ignorados"]) == (1, 0)
    with database.transaction() as c:
        row = c.execute("SELECT * FROM consumo_sc7").fetchone()
    assert (row["produto"], row["origem"]) == ("PN-FORA-DO-MRO", "planilha")


def test_agrega_linhas_do_mesmo_pedido_e_produto(db):
    """O mesmo (PO, PN) aparece em mais de uma linha do SC7. Sem agregar, o `UNIQUE` faria
    a segunda linha SOBRESCREVER a primeira e metade do pedido sumiria."""
    df = pd.DataFrame([_pedido(quantidade=4, entregue=4), _pedido(quantidade=6, entregue=6)])

    res = F.ingerir_sc7_consumo(df, "compras.xlsx")

    assert res["inseridos"] == 1
    with database.transaction() as c:
        row = c.execute("SELECT quantidade, qtd_entregue FROM consumo_sc7").fetchone()
    assert (row["quantidade"], row["qtd_entregue"]) == (10.0, 10.0)


def test_reimportar_atualiza_saldo_e_nao_duplica(db):
    """É assim que um pedido parcial vira atendido: o saldo muda no lugar, e o consumo do
    mês passa a contar aquele pedido sem ninguém apagar nada."""
    F.ingerir_sc7_consumo(pd.DataFrame([_pedido(entregue=4, saldo=6)]), "compras.xlsx")

    res = F.ingerir_sc7_consumo(pd.DataFrame([_pedido(entregue=10, saldo=0)]), "compras.xlsx")

    assert (res["inseridos"], res["atualizados"]) == (0, 1)
    with database.transaction() as c:
        rows = c.execute("SELECT qtd_entregue, saldo FROM consumo_sc7").fetchall()
    assert len(rows) == 1
    assert (rows[0]["qtd_entregue"], rows[0]["saldo"]) == (10.0, 0.0)


def test_descarta_o_preenchimento_do_excel_sem_chamar_de_ignorado(db):
    """O "Relatório de Compras" cru vem com **1.048.569 linhas** (o limite do Excel) e só
    ~34 mil com conteúdo. O corte é vetorizado, antes do laço — iterar o milhão em Python
    travaria a tela por minutos. E as vazias não contam como "ignoradas": nunca foram dado,
    e o número esconderia as poucas linhas reais que foram de fato descartadas."""
    df = pd.DataFrame([_pedido(), {}, {}, {}])

    res = F.ingerir_sc7_consumo(df, "compras.xlsx")

    assert (res["linhas_lidas"], res["linhas_vazias"]) == (4, 3)
    assert (res["inseridos"], res["ignorados"]) == (1, 0)


def test_ignora_linha_sem_pedido_ou_sem_produto(db):
    df = pd.DataFrame([_pedido(numero_pc=""), _pedido(produto=""), _pedido()])

    res = F.ingerir_sc7_consumo(df, "compras.xlsx")

    assert (res["inseridos"], res["ignorados"]) == (1, 2)


def test_aba_vazia_ou_sem_colunas_obrigatorias_devolve_erro(db):
    """Contrato dos ingestores: `dict` de stats ou `{"erro": ...}` — nunca exceção."""
    assert "erro" in F.ingerir_sc7_consumo(None, "compras.xlsx")
    assert "erro" in F.ingerir_sc7_consumo(pd.DataFrame(), "compras.xlsx")
    assert "erro" in F.ingerir_sc7_consumo(pd.DataFrame([{"Produto": "X"}]), "compras.xlsx")


def test_relatorio_de_scs_tambem_alimenta_o_consumo(db, make_item, tmp_path):
    """A MESMA aba SC7 vira duas coisas: preço/lead time (`ingerir_sc7_precos`) e linha de
    pedido (`ingerir_sc7_consumo`). Sem esta chave, quem só importa o Relatório de SCs
    ficaria com a Ficha vazia sem entender por quê."""
    from tests.test_ingestao_relatorio_scs import _build_relatorio

    make_item("PN-ING", estoque=5)
    caminho = _build_relatorio(str(tmp_path / "rel.xlsx"))

    ok, res = F.importar_relatorio_scs(caminho, "rel.xlsx")

    assert ok
    assert res["SC7_CONSUMO"]["inseridos"] == 1
    with database.transaction() as c:
        row = c.execute("SELECT numero_pc, saldo FROM consumo_sc7").fetchone()
    assert (row["numero_pc"], row["saldo"]) == ("F900", 6.0)


def test_uploader_dedicado_acha_a_aba_e_o_cabecalho(db, tmp_path):
    """A porta de entrada do "Relatório de Compras.xlsx" usa `preparar_df`, que varre abas
    e as 6 primeiras linhas. As colunas novas do consumo (DT Emissao/Quantidade/Unidade)
    precisam estar no mapa do SC7 — sem elas o mês do pedido se perderia."""
    from services.db_functions import _coluna
    from services.monitor_cruzamento import _SC7_COLS, preparar_df

    caminho = str(tmp_path / "compras.xlsx")
    pd.DataFrame([_pedido()]).to_excel(caminho, sheet_name="SC7", index=False, startrow=3)

    df, meta = preparar_df(caminho, "SC7")

    assert df is not None and meta["header"] == 3
    esperadas = ("pedido", "produto", "saldo", "dt_emissao", "quantidade", "unidade")
    assert all(_coluna(df, _SC7_COLS[chave]) for chave in esperadas)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Leitura por item — fontes, fallbacks e a Ficha 360
# ══════════════════════════════════════════════════════════════════════════════


def test_casa_pelo_part_number_e_soma_o_ano_corrente(db, make_item):
    item_id = make_item("PN-SC7", estoque=0, minimo=5)
    F.ingerir_sc7_consumo(
        pd.DataFrame(
            [
                _pedido(numero_pc="F1", emissao="2026-02-01", entregue=35),
                _pedido(numero_pc="F2", emissao="2026-05-01", entregue=35),
            ]
        ),
        "compras.xlsx",
    )

    with database.transaction() as c:
        info = CS7.consumo_sc7_por_item(c, item_id, hoje=HOJE)[item_id]

    assert info["origem"] == "sc7"
    assert info["consumo_mensal"] == 10.0  # 70 ÷ 7 meses


def test_converte_pelo_fator_do_item(db, make_item):
    """84 CX ÷ fator 12 = 7 UN de estoque no ano passado → 0,58/mês, e não 7/mês."""
    item_id = make_item("PN-SC7", estoque=0, unidade="UN")
    F.atualizar_item_inventario(item_id, {"unidade_compra": "CX", "fator_conversao": 12})
    F.ingerir_sc7_consumo(pd.DataFrame([_pedido(emissao="2025-04-01", entregue=84)]), "compras.xlsx")

    with database.transaction() as c:
        info = CS7.consumo_sc7_por_item(c, item_id, hoje=HOJE)[item_id]

    assert info["ano_anterior"]["total_entregue"] == 7.0
    assert info["consumo_mensal"] == 0.58  # 7 ÷ 12


def test_fallback_scm_quando_o_sc7_nao_tem_o_item(db, make_item):
    """Item que o MRO já comprou mas que não veio no "Relatório de Compras": o pedido do
    Relatório de SCs (`itens_sc`) responde a mesma pergunta com as mesmas colunas."""
    item_id = make_item("PN-SCM", estoque=0)
    with database.transaction() as c:
        cur = c.execute(
            "INSERT INTO solicitacoes_compra (numero_sc, data_abertura, data_po) VALUES (?,?,?)",
            ("SC-900", "2026-01-15", "2026-02-10"),
        )
        c.execute(
            """INSERT INTO itens_sc (sc_id,item_id,numero_po,quantidade_solicitada,
                                     quantidade_pedido,quantidade_recebida_protheus)
               VALUES (?,?,?,?,?,?)""",
            (cur.lastrowid, item_id, "F900", 70, 70, 70),
        )

    with database.transaction() as c:
        info = CS7.consumo_sc7_por_item(c, item_id, hoje=HOJE)[item_id]

    assert info["origem"] == "scm"
    assert info["consumo_mensal"] == 10.0


def test_pedido_scm_ainda_pendente_nao_soma(db, make_item):
    """`quantidade_pedido` − `Qtd.Entregue` > 0 → o material não chegou: vira alerta."""
    item_id = make_item("PN-SCM", estoque=0)
    with database.transaction() as c:
        cur = c.execute(
            "INSERT INTO solicitacoes_compra (numero_sc, data_abertura, data_po) VALUES (?,?,?)",
            ("SC-901", "2026-01-15", "2026-02-10"),
        )
        c.execute(
            """INSERT INTO itens_sc (sc_id,item_id,numero_po,quantidade_solicitada,
                                     quantidade_pedido,quantidade_recebida_protheus)
               VALUES (?,?,?,?,?,?)""",
            (cur.lastrowid, item_id, "F901", 70, 70, 30),
        )

    with database.transaction() as c:
        info = CS7.consumo_sc7_por_item(c, item_id, hoje=HOJE)[item_id]

    assert info["consumo_mensal"] is None
    assert info["pendentes"]["n"] == 1


def test_saida_de_almoxarifado_nunca_vira_consumo_comprado(db, make_item, registrar_consumo):
    """Decisão do Luis (11/08/2026), ao ver o card dizendo "Fonte: saídas reais": este
    número mede COMPRA. Contar requisição aqui apagaria a diferença entre ele e o
    "Consumo/Mensal" ponderado ao lado, que existe justamente para medir a saída — e, com a
    tabela `consumo_sc7` ainda vazia, TODO item cairia no fallback sem avisar."""
    item_id = make_item("PN-SAI", estoque=100)
    registrar_consumo(item_id, quantidade=70, data_hora="2026-03-05 08:00:00")

    with database.transaction() as c:
        info = CS7.consumo_sc7_por_item(c, item_id, hoje=HOJE)[item_id]

    assert (info["consumo_mensal"], info["origem"]) == (None, None)


def test_pendentes_explicam_o_traco_quando_nada_foi_atendido(db, make_item):
    """Item só com pedido a receber: o card mostra "—" e o alerta é o que diz por quê.
    Sem ele, "—" pareceria "ninguém nunca comprou isso"."""
    item_id = make_item("PN-PEND", estoque=100)
    F.ingerir_sc7_consumo(pd.DataFrame([_pedido(produto="PN-PEND", entregue=0, saldo=40)]), "compras.xlsx")

    with database.transaction() as c:
        info = CS7.consumo_sc7_por_item(c, item_id, hoje=HOJE)[item_id]

    assert info["consumo_mensal"] is None
    assert info["pendentes"] == {"n": 1, "qtd": 40.0}


def test_sem_historico_nenhum_devolve_none(db, make_item):
    """Item novo: a chave volta assim mesmo, com `None`, para o card mostrar "—"."""
    item_id = make_item("PN-NADA")

    with database.transaction() as c:
        info = CS7.consumo_sc7_por_item(c, item_id, hoje=HOJE)[item_id]

    assert (info["consumo_mensal"], info["origem"]) == (None, None)


def test_base_inteira_em_uma_varredura(db, make_item):
    """Sem `item_id` só aparecem os itens COM dado — é o mapa que
    `recalcular_min_max_calculado` usa para a base toda, sem uma consulta por item."""
    com_pedido = make_item("PN-SC7", estoque=0)
    sem_nada = make_item("PN-NADA", estoque=0)
    F.ingerir_sc7_consumo(pd.DataFrame([_pedido(entregue=70)]), "compras.xlsx")

    with database.transaction() as c:
        mapa = CS7.consumo_sc7_por_item(c, hoje=HOJE)

    assert mapa[com_pedido]["consumo_mensal"] == 10.0
    assert sem_nada not in mapa


def test_tooltip_mostra_a_conta_de_cada_ano():
    """Formato pedido pelo Luis em 11/08/2026: ele quer ver a CONTA ("10000 ÷ 12 = 833/mês"),
    não totais e contagens. Testado sem Streamlit porque `_ajuda_consumo_sc7` é texto puro."""
    from ui.paginas.ficha_360 import _ajuda_consumo_sc7

    info = CS7._consumo_from_linhas(
        [_linha("2025-03-01", 10000), _linha("2026-02-01", 600), _linha("2026-04-01", 5, saldo=3160)],
        HOJE,
    )
    info["origem"] = "sc7"

    texto = _ajuda_consumo_sc7(info, "RL")

    assert "Fonte: SC7 (Relatório de Compras)." in texto
    assert "Ano passado (2025): 10000 ÷ 12 = média de 833.3 RL por mês" in texto
    assert "Ano corrente (2026): janeiro a julho, média de 85.7 RL/mês" in texto
    assert "7 pedido(s)" not in texto  # contagem de pedidos saiu do texto
    assert "1 pedido(s) com saldo a receber (3160 RL)" in texto


def test_tooltip_sem_pedido_explica_o_traco_e_nao_promete_saidas():
    """O "—" tem de dizer o que fazer (importar) e o que este card NÃO é."""
    from ui.paginas.ficha_360 import _ajuda_consumo_sc7

    texto = _ajuda_consumo_sc7(CS7._consumo_from_linhas([], HOJE), "UN")

    assert "Sem pedido de compra ATENDIDO" in texto
    assert "Relatório de Compras" in texto
    assert "saída de almoxarifado não entra" in texto


def test_entra_na_ficha_360_no_lugar_da_vida_util(db, make_item):
    """A Ficha recebe o dict de `classificar_item` inteiro — nenhuma query nova em
    `services/ficha.py`. Datas relativas a hoje para o teste não vencer na virada do ano."""
    item_id = make_item("PN-SC7", estoque=0)
    ano_passado = date.today().year - 1
    F.ingerir_sc7_consumo(
        pd.DataFrame([_pedido(emissao=f"{ano_passado}-06-01", entregue=120)]), "compras.xlsx"
    )

    cls = C.classificar_item(item_id)

    assert cls["consumo_sc7"]["consumo_mensal"] == 10.0  # 120 ÷ 12
    assert cls["consumo_sc7"]["origem"] == "sc7"
    assert "vida_util" not in cls
    assert {"demanda", "xyz", "consumo_mensal", "sazonalidade"} <= set(cls)
