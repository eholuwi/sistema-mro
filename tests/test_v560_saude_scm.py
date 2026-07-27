"""v5.6.0 — Saúde da integração SCM: diagnóstico do cliente, escopo do sync e log de falha.

O indicador "Ao vivo da API do SCM" ficava sempre verde por três razões somadas:
(1) `ponto_status_api()` era chamado DEPOIS do `return` do caso offline — o ramo vermelho
era inalcançável; (2) `esta_disponivel` devolvia só um bool, sem latência nem motivo do
erro; (3) tentativas de sync que falhavam não deixavam rastro nenhum no banco.

Aqui cobrimos o que é testável sem Streamlit: o diagnóstico do cliente e o resumo de
escopo. O log da tentativa falha está em `test_v510_scm_sync.py`.
"""

import pytest
from services import scm_client, scm_sync


class _RespostaFake:
    def __init__(self, payload=None, erro=None):
        self._payload, self._erro = payload if payload is not None else [], erro

    def raise_for_status(self):
        if self._erro:
            raise self._erro

    def json(self):
        return self._payload


class _SessaoFake:
    """Sessão que responde OK, ou levanta a exceção pedida."""

    def __init__(self, erro=None):
        self.erro, self.chamadas = erro, []

    def get(self, url, timeout=None):
        self.chamadas.append((url, timeout))
        if self.erro:
            raise self.erro
        return _RespostaFake([{"codigo": "001"}])


@pytest.fixture
def sessao(monkeypatch):
    def _instalar(erro=None):
        s = _SessaoFake(erro)
        monkeypatch.setattr(scm_client, "_session", s)
        return s

    return _instalar


# ── diagnostico() ─────────────────────────────────────────────────────────────


def test_diagnostico_ok_traz_latencia_e_nenhum_erro(sessao):
    s = sessao()
    d = scm_client.diagnostico()
    assert d["ok"] is True
    assert d["erro"] is None
    assert isinstance(d["latencia_ms"], int) and d["latencia_ms"] >= 0
    assert d["endpoint"].endswith("/Usuario/Compradores")
    assert len(s.chamadas) == 1, "health-check não pode fazer retry (bloquearia a página)"


def test_diagnostico_falha_traz_o_motivo(sessao):
    """O ganho central: sem o motivo, a tela só sabia dizer 'offline'. Distinguir
    'sem rota até o servidor' de 'servidor respondeu erro' muda o que o usuário faz."""
    sessao(erro=ConnectionError("sem rota até mansrvapp03"))
    d = scm_client.diagnostico()
    assert d["ok"] is False
    assert "ConnectionError" in d["erro"]
    assert "sem rota até mansrvapp03" in d["erro"]
    assert isinstance(d["latencia_ms"], int)


def test_diagnostico_nao_levanta_excecao(sessao):
    """É health-check: qualquer falha vira dado, nunca exceção que derruba a página."""
    sessao(erro=ValueError("json inválido"))
    assert scm_client.diagnostico()["ok"] is False


def test_esta_disponivel_deriva_do_diagnostico(sessao):
    """Compatibilidade com os 3 call sites antigos — sem duplicar a lógica de rede."""
    sessao()
    assert scm_client.esta_disponivel() is True
    sessao(erro=ConnectionError("fora"))
    assert scm_client.esta_disponivel() is False


# ── resumo_escopo() ───────────────────────────────────────────────────────────


def _seed(db, nome, codigo=None, incluir=1):
    from services.db_functions import _normalizar_txt

    conn = db.get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO solicitantes_mro (nome, nome_norm, incluir_mro, codigo) VALUES (?,?,?,?)",
        (nome, _normalizar_txt(nome), incluir, codigo),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def solicitantes_zerados(db):
    """`criar_banco()` semeia solicitantes MRO padrão; zerar torna a contagem explícita."""
    conn = db.get_connection()
    conn.execute("DELETE FROM solicitantes_mro")
    conn.commit()
    conn.close()
    return db


def test_escopo_vazio_quando_ninguem_tem_codigo(solicitantes_zerados):
    db = solicitantes_zerados
    """O estado real em 26/07/2026: 4 solicitantes MRO, nenhum com código Protheus —
    o sync varre zero solicitantes e nunca traz nada, sem sinalizar isso em lugar nenhum."""
    _seed(db, "Jasiva Lopes")
    _seed(db, "Luis Gabriel Arruda de Oliveira")
    assert scm_sync.resumo_escopo() == {"no_mro": 2, "com_codigo": 0}


def test_escopo_conta_apenas_codigos_uteis(solicitantes_zerados):
    db = solicitantes_zerados
    _seed(db, "Com código", codigo="001053")
    _seed(db, "Código em branco", codigo="   ")
    _seed(db, "Sem código")
    assert scm_sync.resumo_escopo() == {"no_mro": 3, "com_codigo": 1}


def test_escopo_ignora_quem_esta_fora_do_mro(solicitantes_zerados):
    db = solicitantes_zerados
    _seed(db, "Dentro", codigo="001053")
    _seed(db, "Fora", codigo="002000", incluir=0)
    assert scm_sync.resumo_escopo() == {"no_mro": 1, "com_codigo": 1}


def test_escopo_com_tabela_vazia(solicitantes_zerados):
    assert scm_sync.resumo_escopo() == {"no_mro": 0, "com_codigo": 0}


# ── formatação do "há X" (puro) ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "delta_segundos,esperado",
    [(30, "agora há pouco"), (300, "há 5 min"), (7200, "há 2 h"), (172800, "há 2 d")],
)
def test_ha_quanto_tempo(delta_segundos, esperado):
    from datetime import datetime, timedelta

    from ui.componentes.status import _ha_quanto_tempo

    quando = (datetime.now() - timedelta(seconds=delta_segundos)).isoformat(sep=" ", timespec="seconds")
    assert _ha_quanto_tempo(quando) == esperado


def test_ha_quanto_tempo_tolera_lixo():
    """`log_importacoes.data_hora` é TEXT — não pode derrubar a página se vier torto."""
    from ui.componentes.status import _ha_quanto_tempo

    assert _ha_quanto_tempo(None) is None
    assert _ha_quanto_tempo("nunca") is None


# ── Health-check sob demanda (a página não pode travar ao abrir) ──────────────


def test_diagnostico_conhecido_nao_toca_a_rede(monkeypatch):
    """A garantia central: abrir a página não dispara health-check.

    Um health-check contra API fora custa até 10s de timeout — se fosse feito no render,
    a página inteira travaria a cada visita justamente quando o indicador importa. Foi o
    que quebrou o smoke de render do SCM Integrado na primeira tentativa."""
    from ui.componentes import status

    def _explode(*a, **k):
        raise AssertionError("diagnostico() não pode ser chamado ao desenhar a página")

    monkeypatch.setattr(status.scm_client, "diagnostico", _explode)
    monkeypatch.setattr(status, "st", _SessionFake())
    assert status.diagnostico_conhecido() is None


class _SessionFake:
    """Stand-in mínimo de `st` para o que estes testes exercitam."""

    def __init__(self):
        self.session_state = {}


def test_testar_conexao_guarda_o_resultado_na_sessao(monkeypatch):
    from ui.componentes import status

    fake = _SessionFake()
    monkeypatch.setattr(status, "st", fake)
    monkeypatch.setattr(
        status.scm_client,
        "diagnostico",
        lambda *a, **k: {"ok": True, "latencia_ms": 12, "erro": None, "endpoint": "x"},
    )
    assert status.testar_conexao_scm()["ok"] is True
    assert status.diagnostico_conhecido()["latencia_ms"] == 12


def test_diagnostico_derivado_do_sync_com_falha(monkeypatch):
    """Depois de "Atualizar agora", o painel já sabe o estado — sem pedir outro clique."""
    from ui.componentes import status

    monkeypatch.setattr(status, "st", _SessionFake())
    diag = status.registrar_diagnostico_do_sync(
        {"ok": False, "erro": "API do SCM indisponível", "detalhe_erro": "ConnectionError: sem rota"}
    )
    assert diag["ok"] is False
    assert "sem rota" in diag["erro"]
    assert status.diagnostico_conhecido()["ok"] is False


def test_diagnostico_derivado_do_sync_com_sucesso(monkeypatch):
    from ui.componentes import status

    monkeypatch.setattr(status, "st", _SessionFake())
    diag = status.registrar_diagnostico_do_sync({"ok": True, "scs": 10})
    assert diag["ok"] is True and diag["erro"] is None


def test_diagnostico_do_sync_ignora_resumo_invalido(monkeypatch):
    from ui.componentes import status

    monkeypatch.setattr(status, "st", _SessionFake())
    assert status.registrar_diagnostico_do_sync(None) is None
