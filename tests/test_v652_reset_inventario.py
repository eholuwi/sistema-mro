"""v6.5.2 — Reset das marcacoes de inventario (manual + agendado).

`data_inventario` marca "item ja contado no ciclo corrente" e alimenta o filtro rapido
"Nao Inventariado". Comecar um ciclo novo e apagar essa marca de todos — pelo botao em
Configuracoes ou por intervalo (a cada N semanas/meses), sem schema novo: os parametros
sao chaves na tabela `configuracoes`, que ja existe desde a v5.8.0.

O que estes testes protegem:
  - o reset apaga SO `data_inventario` (saldo, locais e `caixa_identificacao` intactos);
  - a idempotencia real (2x seguidas = mesmo estado, e a 2a nao "toca" a base de novo);
  - o agendamento: dispara no vencimento, nao dispara antes, nunca dispara desligado;
  - a ancora do ciclo — ligar o agendamento nao pode disparar um reset imediato;
  - `desmarcar_inventariado` individual, que continua sendo outro caminho.
"""

from datetime import date

from services import db_functions as F


def _inventariar(db, item_id, quando="2026-08-01 09:00:00"):
    """Marca o item como contado, direto no banco (sem passar pelo codigo sob teste)."""
    conn = db.get_connection()
    conn.execute("UPDATE inventario SET data_inventario=? WHERE id=?", (quando, item_id))
    conn.commit()
    conn.close()


def _campo(db, item_id, coluna):
    conn = db.get_connection()
    row = conn.execute(f"SELECT {coluna} FROM inventario WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return row[0]


def _config(db, chave):
    conn = db.get_connection()
    row = conn.execute("SELECT valor FROM configuracoes WHERE chave=?", (chave,)).fetchone()
    conn.close()
    return row["valor"] if row else None


# ── Reset manual ──────────────────────────────────────────────────────────────


def test_reset_limpa_a_marcacao_de_todos_os_itens(db, make_item):
    a = make_item(part_number="PN-A")
    b = make_item(part_number="PN-B")
    c = make_item(part_number="PN-C")
    for item in (a, b, c):
        _inventariar(db, item)

    ok, n = F.resetar_inventario()

    assert ok
    assert n == 3
    assert all(_campo(db, item, "data_inventario") is None for item in (a, b, c))


def test_reset_nao_toca_estoque_locais_nem_a_obs_de_inventario(db, make_item):
    item = make_item(part_number="PN-META", estoque=42, local="ARM-08", caixa="CAIXA AVARIADA")
    _inventariar(db, item)

    ok, _ = F.resetar_inventario()

    assert ok
    assert _campo(db, item, "data_inventario") is None
    assert _campo(db, item, "estoque_atual") == 42
    assert _campo(db, item, "local_armazenagem") == "ARM-08"
    assert _campo(db, item, "caixa_identificacao") == "CAIXA AVARIADA"


def test_reset_e_idempotente_a_segunda_vez_nao_mexe_em_ninguem(db, make_item):
    item = make_item(part_number="PN-IDEM")
    _inventariar(db, item)

    ok1, n1 = F.resetar_inventario()
    atualizacao_apos_1 = _campo(db, item, "data_atualizacao")
    ok2, n2 = F.resetar_inventario()

    assert (ok1, n1) == (True, 1)
    assert (ok2, n2) == (True, 0)  # nada a desmarcar: a 2a chamada e no-op de verdade
    assert _campo(db, item, "data_inventario") is None
    assert _campo(db, item, "data_atualizacao") == atualizacao_apos_1


def test_reset_com_base_vazia_nao_estoura(db):
    ok, n = F.resetar_inventario()
    assert (ok, n) == (True, 0)


# ── Nao-regressao: desmarcar item a item ──────────────────────────────────────


def test_desmarcar_inventariado_individual_continua_funcionando(db, make_item):
    a = make_item(part_number="PN-1")
    b = make_item(part_number="PN-2")
    _inventariar(db, a)
    _inventariar(db, b)

    ok, _ = F.desmarcar_inventariado(a)

    assert ok
    assert _campo(db, a, "data_inventario") is None
    assert _campo(db, b, "data_inventario") is not None  # o outro nao foi arrastado junto


# ── Configuracao do agendamento ───────────────────────────────────────────────


def test_configuracao_nasce_desligada_e_com_padrao(db):
    cfg = F.ler_config_reset_inventario()
    assert cfg == {"ativo": False, "periodo": 3, "unidade": "meses", "ultimo": None}


def test_salvar_grava_periodo_unidade_e_ancora_o_ciclo_ao_ligar(db):
    ok, _ = F.salvar_config_reset_inventario(True, 2, "semanas", hoje=date(2026, 8, 12))

    assert ok
    cfg = F.ler_config_reset_inventario()
    assert cfg["ativo"] is True
    assert cfg["periodo"] == 2
    assert cfg["unidade"] == "semanas"
    assert cfg["ultimo"] == "2026-08-12"


def test_ligar_o_agendamento_nao_dispara_reset_imediato(db, make_item):
    """A ancora existe para isto: sem ela, `ultimo` ausente = vencido desde sempre, e o
    primeiro render depois de ligar apagaria a contagem recem-feita."""
    item = make_item(part_number="PN-ANCORA")
    _inventariar(db, item)

    F.salvar_config_reset_inventario(True, 1, "meses", hoje=date(2026, 8, 12))
    disparou, _ = F.aplicar_reset_inventario_agendado(hoje=date(2026, 8, 12))

    assert disparou is False
    assert _campo(db, item, "data_inventario") is not None


def test_valores_sujos_na_tabela_caem_no_padrao_em_vez_de_estourar(db):
    F.salvar_config_reset_inventario(True, 4, "semanas")
    conn = db.get_connection()
    conn.execute("UPDATE configuracoes SET valor='abc' WHERE chave=?", (F.RESET_INV_PERIODO,))
    conn.execute("UPDATE configuracoes SET valor='decadas' WHERE chave=?", (F.RESET_INV_UNIDADE,))
    conn.commit()
    conn.close()

    cfg = F.ler_config_reset_inventario()
    assert cfg["periodo"] == 3
    assert cfg["unidade"] == "meses"


# ── Calculo do vencimento ─────────────────────────────────────────────────────


class TestProximaData:
    def test_semanas(self):
        assert F.proxima_data_reset_inventario(date(2026, 8, 12), 2, "semanas") == date(2026, 8, 26)

    def test_meses(self):
        assert F.proxima_data_reset_inventario(date(2026, 8, 12), 3, "meses") == date(2026, 11, 12)

    def test_meses_viram_o_ano(self):
        assert F.proxima_data_reset_inventario(date(2026, 11, 30), 2, "meses") == date(2027, 1, 30)

    def test_dia_31_gruda_no_ultimo_dia_do_mes_curto(self):
        assert F.proxima_data_reset_inventario(date(2026, 1, 31), 1, "meses") == date(2026, 2, 28)


# ── Aplicacao automatica ──────────────────────────────────────────────────────


def test_vencido_dispara_e_regrava_a_ancora(db, make_item):
    item = make_item(part_number="PN-VENC")
    _inventariar(db, item)
    F.salvar_config_reset_inventario(True, 1, "meses", hoje=date(2026, 7, 1))

    disparou, msg = F.aplicar_reset_inventario_agendado(hoje=date(2026, 8, 12))

    assert disparou is True
    assert "1" in msg
    assert _campo(db, item, "data_inventario") is None
    assert _config(db, F.RESET_INV_ULTIMO) == "2026-08-12"


def test_no_dia_exato_do_vencimento_dispara(db, make_item):
    item = make_item(part_number="PN-DIA")
    _inventariar(db, item)
    F.salvar_config_reset_inventario(True, 1, "meses", hoje=date(2026, 7, 12))

    disparou, _ = F.aplicar_reset_inventario_agendado(hoje=date(2026, 8, 12))

    assert disparou is True
    assert _campo(db, item, "data_inventario") is None


def test_antes_do_vencimento_nao_dispara_e_preserva_a_ancora(db, make_item):
    item = make_item(part_number="PN-CEDO")
    _inventariar(db, item)
    F.salvar_config_reset_inventario(True, 3, "meses", hoje=date(2026, 7, 1))

    disparou, msg = F.aplicar_reset_inventario_agendado(hoje=date(2026, 8, 12))

    assert disparou is False
    assert "01/10/2026" in msg
    assert _campo(db, item, "data_inventario") is not None
    assert _config(db, F.RESET_INV_ULTIMO) == "2026-07-01"


def test_desligado_nunca_dispara_mesmo_com_ciclo_vencidissimo(db, make_item):
    item = make_item(part_number="PN-OFF")
    _inventariar(db, item)
    F.salvar_config_reset_inventario(False, 1, "semanas")
    F._gravar_config(F.RESET_INV_ULTIMO, "2020-01-01")

    disparou, msg = F.aplicar_reset_inventario_agendado(hoje=date(2026, 8, 12))

    assert disparou is False
    assert "desligado" in msg.lower()
    assert _campo(db, item, "data_inventario") is not None


def test_agendamento_ativo_sem_ancora_ancora_e_segura_o_gatilho(db, make_item):
    """Caminho de banco legado/mexido na mao: ativo sem `ultimo`. Ancorar e nao disparar
    e o unico comportamento seguro — o contrario apagaria o ciclo em curso."""
    item = make_item(part_number="PN-SEM-ANCORA")
    _inventariar(db, item)
    F._gravar_config(F.RESET_INV_ATIVO, "1")

    disparou, _ = F.aplicar_reset_inventario_agendado(hoje=date(2026, 8, 12))

    assert disparou is False
    assert _campo(db, item, "data_inventario") is not None
    assert _config(db, F.RESET_INV_ULTIMO) == "2026-08-12"

    # e no ciclo seguinte, ja ancorado, ele dispara normalmente
    F.salvar_config_reset_inventario(True, 1, "semanas")
    disparou2, _ = F.aplicar_reset_inventario_agendado(hoje=date(2026, 8, 20))
    assert disparou2 is True
    assert _campo(db, item, "data_inventario") is None


def test_reset_manual_reancora_o_relogio_do_agendamento(db, make_item):
    """O botao manual e o agendamento compartilham a ancora: sem isso, um agendamento
    vencido dispararia de novo no render seguinte ao clique."""
    item = make_item(part_number="PN-MANUAL")
    _inventariar(db, item)
    F.salvar_config_reset_inventario(True, 1, "meses", hoje=date(2026, 6, 1))

    F.resetar_inventario()
    F.marcar_reset_inventario(hoje=date(2026, 8, 12))

    assert _config(db, F.RESET_INV_ULTIMO) == "2026-08-12"
    disparou, _ = F.aplicar_reset_inventario_agendado(hoje=date(2026, 8, 12))
    assert disparou is False
