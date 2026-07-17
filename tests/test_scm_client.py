"""v4.10.0 — Cliente de leitura da API do SCM (`services/scm_client.py`).

Testa o NÚCLEO puro (sem rede): normalização dos dois formatos de resposta
(`_extrair_result`), `_trim`/`_num`, e o transporte `_get` (timeout/retry/desembrulho)
com uma sessão FALSA. Os testes que usam as amostras reais em `openapi/samples/` pulam
se a pasta não estiver presente (o estudo vive fora do repo do MRO).
"""
import json
from pathlib import Path

import pytest

from services import scm_client as C


_SAMPLES = Path(__file__).resolve().parents[2] / "openapi" / "samples"


def _load(nome):
    return json.loads((_SAMPLES / nome).read_text(encoding="utf-8-sig"))


# ── _extrair_result: os dois formatos da API ─────────────────────────────────

def test_extrair_result_envelope():
    assert C._extrair_result({"succeeded": True, "errors": [], "result": {"a": 1}}) == {"a": 1}


def test_extrair_result_array_cru_passa_direto():
    assert C._extrair_result([1, 2, 3]) == [1, 2, 3]


def test_extrair_result_dict_sem_result_passa_direto():
    assert C._extrair_result({"a": 1}) == {"a": 1}


# ── _trim / _num ─────────────────────────────────────────────────────────────

def test_trim_remove_padding_protheus():
    assert C._trim("90402    ") == "90402"
    assert C._trim(None) == ""
    assert C._trim("  PC  ") == "PC"


def test_num_formatos():
    assert C._num(4000.0) == 4000.0
    assert C._num("1.234,50") == 1234.50
    assert C._num("1,234.50") == 1234.50
    assert C._num("") == 0.0
    assert C._num(None, default=-1) == -1
    assert C._num("lixo", default=0.0) == 0.0


# ── Transporte _get (sessão FALSA; sem rede) ─────────────────────────────────

class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self._payload


class _FakeSession:
    """Devolve respostas em sequência; um item Exception é levantado (simula falha)."""
    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        r = self._respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return _FakeResp(r)


def test_get_desembrulha_envelope_e_monta_url(monkeypatch):
    fake = _FakeSession([{"succeeded": True, "result": {"ok": 1}}])
    monkeypatch.setattr(C, "_session", fake)
    assert C._get("/X/1") == {"ok": 1}
    assert fake.calls == [C.BASE_URL + "/X/1"]


def test_get_array_cru(monkeypatch):
    fake = _FakeSession([[{"a": 1}, {"a": 2}]])
    monkeypatch.setattr(C, "_session", fake)
    assert C._get("/lista") == [{"a": 1}, {"a": 2}]


def test_get_retry_apos_falha(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda *_a, **_k: None)  # não espera
    fake = _FakeSession([RuntimeError("reciclou"), [9]])
    monkeypatch.setattr(C, "_session", fake)
    assert C._get("/y", retries=2) == [9]
    assert len(fake.calls) == 2


def test_get_propaga_apos_esgotar_retries(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda *_a, **_k: None)
    fake = _FakeSession([RuntimeError("x"), RuntimeError("x")])
    monkeypatch.setattr(C, "_session", fake)
    with pytest.raises(RuntimeError):
        C._get("/z", retries=2)


def test_esta_disponivel(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(C, "_session", _FakeSession([["comprador"]]))
    assert C.esta_disponivel() is True
    monkeypatch.setattr(C, "_session", _FakeSession([RuntimeError("sem rede")]))
    assert C.esta_disponivel() is False


# ── Amostras reais (pulam se a pasta do estudo não existir) ───────────────────

@pytest.mark.skipif(not _SAMPLES.exists(), reason="openapi/samples não presente")
def test_extrair_result_com_amostra_envelope():
    tl = _load("SC_Timeline_41468.json")
    res = C._extrair_result(tl)
    assert isinstance(res, dict) and "items" in res


@pytest.mark.skipif(not _SAMPLES.exists(), reason="openapi/samples não presente")
def test_extrair_result_com_amostra_array():
    lic = _load("Cotacao_ListInCotacoes.json")
    assert C._extrair_result(lic) is lic  # lista crua passa direto
