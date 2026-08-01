"""v6.0.0 — Refatoração de UX/UI: o que deixou de ser só apresentação.

A refatoração é majoritariamente movimentação de blocos prontos entre telas, coberta
pelos smokes de render (`test_v500_router`, `test_v530_dashboard`). Este arquivo cobre
os quatro pontos que viraram CÓDIGO NOVO e que o smoke não pega:

  1. `ui/formatos` — o formatador monetário pt-BR único (antes: 3 padrões na UI, um
     deles imprimindo no formato americano "R$ 1,234.56").
  2. `dashboards.montar_visao_almoxarifado()["ytd"]` — os indicadores do ano herdados
     do extinto KPI Mensal. A REGRESSÃO que importa: o número exibido no Almoxarifado
     tem de ser o MESMO que o KPI Mensal exibia, senão a extinção da aba mudou o KPI.
  3. `gerenciar_itens.tem_conversao` — decide se o checkbox de conversão nasce marcado.
     Errar aqui esconde uma conversão já curada e o salvamento devolve fator 1, o que
     faria o recebimento somar quantidade crua no estoque.
  4. Os 5 filtros rápidos do Saldo em Estoque.
  5. A camada semântica de cores alinhada a `docs/template_moderno.html`.
  6. A versão exibida — três literais que tinham derivado entre si (5.8.0 / 5.8.0 / 5.7.0
     com o app na 5.9.0). Agora há UMA constante e um teste que impede a próxima deriva.
"""

import re
from datetime import date
from pathlib import Path

import pandas as pd

from services import dashboards as D
from services import tema as T
from ui.formatos import fmt_brl, fmt_moeda, fmt_num, colunas_brl
from ui.paginas.gerenciar_itens import tem_conversao
from ui.paginas.saldo_estoque import _FILTROS_RAPIDOS

ANO = date.today().year


# ══════════════════════════════════════════════════════════════════════════════
# 1. Formatação monetária pt-BR
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatacaoMonetaria:
    def test_milhar_com_ponto_e_decimal_com_virgula(self):
        assert fmt_brl(12345.67) == "R$ 12.345,67"
        assert fmt_brl(1234567.8) == "R$ 1.234.567,80"

    def test_valores_pequenos_e_zero(self):
        assert fmt_brl(0) == "R$ 0,00"
        assert fmt_brl(0.5) == "R$ 0,50"
        assert fmt_brl(999) == "R$ 999,00"

    def test_negativo_mantem_sinal(self):
        assert fmt_brl(-1234.5) == "R$ -1.234,50"

    def test_none_e_texto_viram_travessao(self):
        # Item sem preço de referência chega como None — não pode virar "R$ 0,00"
        # (dizer "zero" é diferente de dizer "não sei").
        assert fmt_brl(None) == "R$ —"
        assert fmt_brl("") == "R$ —"
        assert fmt_brl("abc") == "R$ —"

    def test_string_numerica_e_int_aceitos(self):
        assert fmt_brl("1234.5") == "R$ 1.234,50"
        assert fmt_brl(1000) == "R$ 1.000,00"

    def test_fmt_num_sem_casas_para_contagem(self):
        # "Requisições Atendidas no Ano" é contagem: milhar sim, decimal não.
        assert fmt_num(1234, casas=0) == "1.234"
        assert fmt_num(0, casas=0) == "0"

    def test_fmt_moeda_respeita_a_moeda_do_item(self):
        # A Ficha 360 valora pelo último preço, que pode não ser BRL.
        assert fmt_moeda(1234.5, "USD") == "USD 1.234,50"
        assert fmt_moeda(1234.5, "BRL") == "BRL 1.234,50"
        assert fmt_moeda(1234.5, None) == "R$ 1.234,50"  # sem moeda → real

    def test_colunas_brl_formata_so_o_que_existe(self):
        df = pd.DataFrame([{"Valor em Estoque": 1500.0, "Qtd": 3}])
        out = colunas_brl(df, "Valor em Estoque", "Coluna Inexistente")
        assert list(out["Valor em Estoque"]) == ["R$ 1.500,00"]
        assert list(out["Qtd"]) == [3]  # coluna não monetária fica intacta

    def test_colunas_brl_com_df_vazio_nao_quebra(self):
        vazio = pd.DataFrame(columns=["Valor em Estoque"])
        assert colunas_brl(vazio, "Valor em Estoque").empty


# ══════════════════════════════════════════════════════════════════════════════
# 2. YTD do Almoxarifado (herdado do KPI Mensal)
# ══════════════════════════════════════════════════════════════════════════════


def _set_preco(item_id, preco):
    import database

    with database.transaction() as c:
        c.execute("UPDATE inventario SET preco_referencia=? WHERE id=?", (preco, item_id))


class TestYtdAlmoxarifado:
    def test_ytd_bate_com_o_que_o_kpi_mensal_exibia(self, db, make_item, registrar_consumo):
        """REGRESSÃO da extinção do KPI Mensal: mover o indicador não pode mudar o número."""
        it = make_item("PN-YTD", estoque=100, minimo=10)
        _set_preco(it, 10.0)
        registrar_consumo(it, quantidade=3, data_hora=f"{ANO}-03-10 08:00:00")

        ytd = D.montar_visao_almoxarifado()["ytd"]
        exec_vm = D.montar_visao_executiva()

        assert ytd["ano"] == exec_vm["ano"] == ANO
        assert ytd["valor_consumido"] == exec_vm["kpis"]["valor_consumido_ytd"] == 30.0
        assert ytd["n_requisicoes"] == exec_vm["kpis"]["n_requisicoes_ytd"] == 1
        assert ytd["itens_movimentados"] == exec_vm["kpis"]["itens_consumidos_ytd"] == 1
        assert ytd["composicao_tipo"] == exec_vm["composicao_tipo"]

    def test_ytd_ignora_ajuste_fisico(self, db, make_item, registrar_consumo):
        """Consumo é saída POR REQUISIÇÃO. Um ajuste de inventário gigante não pode
        entrar no Consumido no Ano (é o bug que inflava a antiga curva ABC)."""
        import database

        it = make_item("PN-AJU", estoque=1000, minimo=10)
        _set_preco(it, 10.0)
        registrar_consumo(it, quantidade=2, data_hora=f"{ANO}-04-01 08:00:00")
        with database.transaction() as c:  # saída SEM requisicao_id = ajuste físico
            c.execute(
                "INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,"
                "centro_custo,setor,emitente,observacao) VALUES (?,?,?,?,?,?,?,?,?)",
                (it, "saida", 900, None, f"{ANO}-04-02 08:00:00", "INVENTÁRIO", "", "x", "ajuste"),
            )

        ytd = D.montar_visao_almoxarifado()["ytd"]
        assert ytd["valor_consumido"] == 20.0  # só as 2 UN da requisição

    def test_ytd_com_item_sem_preco_nao_quebra(self, db, make_item, registrar_consumo):
        """Item sem preço de referência: entra na contagem, soma 0 no valor."""
        it = make_item("PN-SEMPRECO", estoque=50, minimo=5)
        registrar_consumo(it, quantidade=4, data_hora=f"{ANO}-05-05 08:00:00")

        ytd = D.montar_visao_almoxarifado()["ytd"]
        assert ytd["itens_movimentados"] == 1
        assert ytd["valor_consumido"] == 0.0
        assert ytd["composicao_tipo"] == []  # nada valorado → donut vazio, não erro

    def test_ytd_banco_vazio(self, db):
        ytd = D.montar_visao_almoxarifado()["ytd"]
        assert ytd == {
            "ano": ANO,
            "valor_consumido": 0.0,
            "n_requisicoes": 0,
            "itens_movimentados": 0,
            "composicao_tipo": [],
        }

    def test_total_consumido_ignora_lista_vazia_e_soma_valores(self):
        assert D._total_consumido([]) == 0.0
        assert D._total_consumido([{"valor": 10.5}, {"valor": 0.0}, {"valor": 2.25}]) == 12.75


# ══════════════════════════════════════════════════════════════════════════════
# 3. Checkbox de conversão de unidades
# ══════════════════════════════════════════════════════════════════════════════


class TestTemConversao:
    def test_item_curado_por_fator_nasce_marcado(self):
        assert tem_conversao({"fator_conversao": 5.0, "unidade": "L", "unidade_compra": "GL"})

    def test_item_curado_so_por_unidade_diferente_nasce_marcado(self):
        assert tem_conversao({"fator_conversao": 1.0, "unidade": "UN", "unidade_compra": "CX"})

    def test_item_sem_conversao_nasce_desmarcado(self):
        assert not tem_conversao({"fator_conversao": 1.0, "unidade": "UN", "unidade_compra": None})
        assert not tem_conversao({"fator_conversao": None, "unidade": "UN", "unidade_compra": ""})

    def test_unidade_de_compra_igual_a_de_estoque_nao_e_conversao(self):
        # "compra em UN, estoca em UN" é o caso comum — não deve abrir os campos.
        assert not tem_conversao({"fator_conversao": 1.0, "unidade": "UN", "unidade_compra": "UN"})
        assert not tem_conversao({"fator_conversao": 1.0, "unidade": "un", "unidade_compra": " UN "})

    def test_item_ausente_ou_vazio_nao_quebra(self):
        assert not tem_conversao(None)
        assert not tem_conversao({})


# ══════════════════════════════════════════════════════════════════════════════
# 4. Os 5 filtros rápidos do Saldo em Estoque
# ══════════════════════════════════════════════════════════════════════════════


def _df_saldo():
    return pd.DataFrame(
        [
            {"pn": "A", "status_material": "🔴 COMPRAR", "importancia": "Importante", "data_inventario": ""},
            {
                "pn": "B",
                "status_material": "🟢 OK",
                "importancia": "Parada de Linha",
                "data_inventario": "2026-01-10",
            },
            {"pn": "C", "status_material": "🟡 ATENÇÃO", "importancia": "Admin", "data_inventario": None},
            {
                "pn": "D",
                "status_material": "⚪ Sem Movimentação",
                "importancia": "Parada de Linha",
                "data_inventario": "",
            },
        ]
    )


class TestFiltrosSaldoEstoque:
    def test_os_cinco_filtros_pedidos_estao_presentes(self):
        rotulos = " | ".join(_FILTROS_RAPIDOS)
        for esperado in ("A Comprar", "Atenção", "OK", "Parada de Linha", "Não Inventariado"):
            assert esperado in rotulos

    def test_cada_filtro_seleciona_suas_linhas(self):
        df = _df_saldo()

        def sel(rotulo):
            pred = next(p for r, p in _FILTROS_RAPIDOS.items() if rotulo in r)
            return set(df[pred(df)]["pn"])

        assert sel("A Comprar") == {"A"}
        assert sel("Atenção") == {"C"}
        assert sel("Parada de Linha") == {"B", "D"}
        assert sel("Não Inventariado") == {"A", "C", "D"}

    def test_ok_nao_captura_sem_movimentacao(self):
        # "⚪ Sem Movimentação" não contém "OK" — o filtro OK não pode arrastá-lo junto.
        df = _df_saldo()
        pred = next(p for r, p in _FILTROS_RAPIDOS.items() if "OK" in r)
        assert set(df[pred(df)]["pn"]) == {"B"}

    def test_filtros_sao_independentes_e_combinam_por_and(self):
        """Não há categoria única nem precedência: um item "Parada de Linha" que também
        está "A Comprar" aparece nos dois filtros, e marcar os dois estreita (AND)."""
        df = _df_saldo()
        parada = next(p for r, p in _FILTROS_RAPIDOS.items() if "Parada de Linha" in r)
        nao_inv = next(p for r, p in _FILTROS_RAPIDOS.items() if "Não Inventariado" in r)
        combinado = df[parada(df)]
        assert set(combinado[nao_inv(combinado)]["pn"]) == {"D"}

    def test_predicados_robustos_a_coluna_ausente(self):
        df = pd.DataFrame([{"pn": "X"}])
        for pred in _FILTROS_RAPIDOS.values():
            assert pred(df).all(), "sem a coluna, o filtro não pode esconder linhas nem quebrar"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Cores — camada semântica alinhada a docs/template_moderno.html
# ══════════════════════════════════════════════════════════════════════════════


class TestCoresDoTemplate:
    def test_paleta_expoe_as_semanticas_nos_dois_temas(self):
        for tipo in ("light", "dark"):
            p = T.paleta(tipo)
            assert {"positivo", "negativo", "neutro", "info", "atencao", "serie"} <= set(p)
            for chave in ("positivo", "negativo", "neutro", "info", "atencao"):
                assert p[chave].startswith("#"), f"{tipo}/{chave} não é hex"

    def test_semanticas_do_light_sao_as_do_template(self):
        p = T.paleta("light")
        assert (p["positivo"], p["negativo"]) == ("#16A34A", "#DC2626")  # --positive/--negative
        assert p["neutro"] == "#5B5B5B"  # --sidebar

    def test_dark_usa_tons_mais_claros_que_o_light(self):
        """Os tons do template são calibrados para fundo claro; repetidos no #0E0F12 eles
        somem. O dark tem de divergir — se alguém 'simplificar' isso, o teste avisa."""
        claro, escuro = T.paleta("light"), T.paleta("dark")
        for chave in ("positivo", "negativo", "info"):
            assert claro[chave] != escuro[chave], f"{chave} não foi ajustado no tema escuro"

    def test_serie_categorica_nao_abre_com_laranja_e_verde(self):
        """A ordem é acessibilidade, não gosto: laranja e verde ficam a ΔE 3,3 em
        protanopia. Os 3 primeiros (as fatias que mais aparecem) têm de ser distinguíveis
        — a lista antiga abria com três laranjas seguidos."""
        serie = T.paleta("light")["serie"]
        assert serie[0] == T.ACCENT
        assert serie[:3] == ["#F58220", "#1D4ED8", "#B91C1C"]  # laranja → azul → vermelho
        assert len(serie) == len(set(serie)), "cor repetida na série categórica"

    def test_css_recebe_os_tokens_que_styles_consome(self):
        # services/styles.py referencia estes tokens no :root; faltar um quebra o CSS
        # inteiro com KeyError na injeção, em TODA página.
        c = T.paleta("light")["css"]
        assert {"positivo", "negativo", "atencao", "raio", "accent_glow", "accent_hover"} <= set(c)

    def test_paleta_e_pura_e_nao_compartilha_a_lista_de_series(self):
        # `serie` é lista mutável: se a paleta devolvesse a MESMA instância, uma página
        # que ordenasse/cortasse a lista contaminaria todas as outras.
        a, b = T.paleta("light")["serie"], T.paleta("light")["serie"]
        assert a == b and a is not b


# ══════════════════════════════════════════════════════════════════════════════
# 6. Versão — uma constante, nenhum literal solto
# ══════════════════════════════════════════════════════════════════════════════

PROJ = Path(__file__).resolve().parents[1]


class TestVersaoUnica:
    def test_rotulo_da_sidebar_deriva_da_constante(self):
        from services.constants import VERSAO, VERSAO_ROTULO
        from ui import sidebar

        assert VERSAO_ROTULO == f"v{VERSAO}"
        assert sidebar.VERSAO == VERSAO_ROTULO

    def test_os_tres_pontos_de_exibicao_nao_tem_versao_digitada(self):
        """O bug: `app.py` e `ui/sidebar.py` diziam 5.8.0 e o log de `database.py` dizia
        5.7.0, com a v5.9.0 entregue. Os três pontos que MOSTRAM versão têm de derivá-la.

        A varredura é por linha e cirúrgica de propósito: `database.py` está cheio de
        "Migração v5.7.0: ..." em log de migração, que é registro histórico legítimo e
        não pode ser confundido com a versão corrente."""
        alvos = {
            "app.py": "page_title",  # título da aba do navegador
            "ui/sidebar.py": "VERSAO =",  # rodapé da barra lateral
            "database.py": "criado/verificado",  # log de abertura do banco
        }
        for arquivo, marcador in alvos.items():
            linhas = [
                ln
                for ln in (PROJ / arquivo).read_text(encoding="utf-8").splitlines()
                if marcador in ln and not ln.lstrip().startswith("#")
            ]
            assert linhas, f"{arquivo}: não achei a linha com {marcador!r} — o teste ficou cego"
            for ln in linhas:
                assert not re.search(r"\bv?\d+\.\d+\.\d+\b", ln), (
                    f"{arquivo} voltou a exibir versão literal: {ln.strip()}"
                )

    def test_release_le_a_mesma_versao_que_o_app_exibe(self):
        import importlib.util

        from services.constants import VERSAO

        spec = importlib.util.spec_from_file_location("release_v600", PROJ / "scripts" / "release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        assert release.versao_do_codigo() == VERSAO

    def test_changelog_da_versao_atual_existe(self):
        from services.constants import VERSAO

        assert (PROJ / "changelog" / f"{VERSAO}.md").is_file(), (
            f"Bump para {VERSAO} sem changelog/{VERSAO}.md — a regra do projeto é o "
            "histórico viver em changelog/, não no HANDOFF."
        )
