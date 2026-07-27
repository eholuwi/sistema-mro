"""v4.10.0 — Cliente de LEITURA da API do SCM (Solicitação de Compras).

Consome a API REST do SCM para enriquecer o MRO com o que já está em processo de
compra (SCs em cotação, pedidos, fornecedores). Um ÚNICO módulo dentro de `services/`,
uma função por endpoint GET, com cache do Streamlit.

A documentação da API (`openapi/`, `RELATORIO_FINAL.md`) fica FORA deste repositório —
contém dados reais de fornecedores e funcionários, e o repo é público. As regras abaixo
são o resumo do que importa; a fonte está com o Luis, junto de `SCM_API_Docs/`.

Regras invioláveis:
- **API anônima na rede interna** — não há login/token; basta rota até `mansrvapp03:5715`.
- **SOMENTE GET.** Nunca chamar endpoints de escrita (POST/PUT/DELETE) — eles alteram
  dados reais do SCM em produção (gerar pedido no Protheus, enviar e-mail…).
- **Dois formatos de resposta:** array cru OU envelope `{succeeded, errors, result}` —
  `_extrair_result` normaliza os dois.
- **Sem paginação server-side:** preferir endpoints filtrados; cache para não repuxar.
- **Campos Protheus vêm com padding de espaços** (`"90402    "`) → usar `_trim`.
- A API pode **reciclar sob carga** → `timeout` + **retry com backoff**.
"""

from __future__ import annotations

import time

import requests

try:  # cache do Streamlit quando disponível; no-op fora dele (ex.: testes/CLI).
    import streamlit as st

    _cache = st.cache_data
except Exception:  # pragma: no cover - ambiente sem streamlit

    def _cache(**_kwargs):
        def _deco(fn):
            return fn

        return _deco


BASE_URL = "http://mansrvapp03:5715/api"
_TIMEOUT = 60  # generoso: a API pode ser lenta sob carga
_RETRIES = 3  # nº de tentativas antes de desistir
_BACKOFF = 1.5  # segundos × tentativa (backoff linear)

_session = requests.Session()
_session.headers.update({"Accept": "application/json"})


# ── Helpers PUROS (testáveis sem rede) ────────────────────────────────────────


def _extrair_result(payload):
    """Normaliza os dois formatos da API: envelope `{succeeded, errors, result}` →
    devolve `result`; array/obj cru → devolve ele mesmo. (Doc SCM §2.1.)"""
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


def _trim(valor):
    """Remove o padding de espaços dos campos Protheus. None → ''."""
    return "" if valor is None else str(valor).strip()


def _num(valor, default=0.0):
    """Converte para float tolerante (aceita '1.234,50'/'1,234.50'/número); erro → default."""
    if valor is None or valor == "":
        return default
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip().replace(" ", "")
    if "," in s and "." in s:  # heurística de milhar/decimal
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


# ── Transporte (GET com timeout + retry/backoff) ──────────────────────────────


def _get(path, *, timeout=_TIMEOUT, retries=_RETRIES):
    """GET em `BASE_URL + path`, desembrulhando o `result`. SÓ LEITURA.

    Faz `retries` tentativas com backoff linear (a API pode reciclar). Propaga a última
    exceção se todas falharem. `path` deve começar com '/'."""
    url = f"{BASE_URL}{path}"
    ultimo_erro = None
    for tentativa in range(retries):
        try:
            resp = _session.get(url, timeout=timeout)
            resp.raise_for_status()
            return _extrair_result(resp.json())
        except Exception as e:  # rede/HTTP/JSON — tenta de novo, depois propaga
            ultimo_erro = e
            if tentativa < retries - 1:
                time.sleep(_BACKOFF * (tentativa + 1))
    raise ultimo_erro


# ── Endpoints de LEITURA priorizados para o MRO (Monitor de SC) ───────────────


@_cache(ttl=900)  # 15 min
def cotacoes_em_andamento():
    """`GET /Cotacao/ListInCotacoes` — cotações em andamento (fase de cotação, ainda
    NÃO viraram pedido). Base das 'SCs/Itens não atendidos' do Monitor."""
    return _get("/Cotacao/ListInCotacoes")


@_cache(ttl=900)
def novas_solicitacoes():
    """`GET /Cotacao/NovasSolicitacoes` — SCs aprovadas aguardando cotação."""
    return _get("/Cotacao/NovasSolicitacoes")


@_cache(ttl=900)
def cotacoes_em_pedido():
    """`GET /Cotacao/ListInPedidos` — cotações JÁ convertidas em pedido (para excluir do
    'sem pedido')."""
    return _get("/Cotacao/ListInPedidos")


@_cache(ttl=900)
def sc_timeline(sc_id):
    """`GET /SolicitacaoCompras/Timeline/{id}` — detalhe da SC com `items[]` (produto,
    quantidade, um). Envelope `Result<T>`."""
    return _get(f"/SolicitacaoCompras/Timeline/{sc_id}")


# ── v5.1.0 (F2) — endpoints do SYNC persistente (API → mro.db) ────────────────


def sc_por_usuario(usuario, ini, fim):
    """`GET /solicitacaoCompras/ByUser/{usuario}/{ini}/{fim}` — SCs de um solicitante no
    período. `usuario` = código Protheus (ex.: '001054'); `ini`/`fim` no formato
    `yyyyMMdd`. Traz só o CABEÇALHO da SC (sem itens) — os itens vêm de `sc_timeline`.

    **SEM cache** de propósito: é a fonte do sync manual; cada "Atualizar agora" precisa
    de dado fresco. Endpoint FILTRADO (por usuário) — nunca usar os amplos (`/Produto`,
    `/SolicitacaoCompras` sem filtro), que já derrubaram o serviço."""
    return _get(f"/solicitacaoCompras/ByUser/{usuario}/{ini}/{fim}")


@_cache(ttl=3600)
def usuarios():
    """`GET /Usuario` — diretório de usuários (código + nome + login + flags). Usado para
    resolver o `codigo` Protheus dos solicitantes MRO por nome. Diretório moderado
    (não é endpoint amplo proibido); cache de 1 h."""
    return _get("/Usuario")


@_cache(ttl=3600)
def fornecedores():
    """`GET /Fornecedor` — cadastro de fornecedores (código + loja + nome)."""
    return _get("/Fornecedor")


@_cache(ttl=900)
def pedido(filial, numero):
    """`GET /Pedidos/ByNumero/{filial}/{numero}` — itens do pedido (Protheus SC7, `C7_*`)."""
    return _get(f"/Pedidos/ByNumero/{filial}/{numero}")


# ── v5.2.0 (F3) — endpoints do "ao vivo da API" da página SCM Integrado ────────


@_cache(ttl=900)
def sc_timeline_v2(sc_id):
    """`GET /SolicitacaoCompras/Timelinev2/{id}` — linha do tempo em EVENTOS (`title`,
    `created`, `information`, `typeProcess`). Envelope `Result<TimelineEvento[]>`.
    Complementa `sc_timeline` (que traz os itens): aqui é o histórico do fluxo da SC."""
    return _get(f"/SolicitacaoCompras/Timelinev2/{sc_id}")


@_cache(ttl=900)
def cotacao_por_codigo(codigo):
    """`GET /Cotacao/GetByCodigo/{codigo}` — detalhe da cotação (`CTxxxxx`): status,
    comprador, fornecedores/produtos/valores. Envelope `Result<T>`."""
    return _get(f"/Cotacao/GetByCodigo/{codigo}")


@_cache(ttl=900)
def aprovadores_pedido(filial, numero):
    """`GET /Pedidos/getAprovadores/{filial}/{numero}` — aprovadores do pedido (Protheus
    SCR — `CR_NIVEL`, `CR_USER`, `AK_NOME`, `CR_STATUS`, `CR_DATALIB`). `CR_STATUS`: '01'
    pendente, '02' liberado (doc SCM §7.12)."""
    return _get(f"/Pedidos/getAprovadores/{filial}/{numero}")


_ENDPOINT_SAUDE = "/Usuario/Compradores"


def diagnostico(timeout=10):
    """Health-check COM diagnóstico: `{ok, latencia_ms, erro, endpoint}`. NÃO cacheia.

    v5.6.0 — `esta_disponivel` devolvia só um bool e engolia a exceção, então a tela não
    tinha o que mostrar além de verde/vermelho: nem quanto demorou, nem por que falhou.
    O motivo do erro é o que permite distinguir "sem rota até o servidor" de "servidor
    respondeu 500" — diagnósticos com ações diferentes para quem opera.

    Continua batendo num endpoint pequeno (`/Usuario/Compradores`); note que ele NÃO é o
    endpoint do sync (`ByUser`/`Timeline`), então verde aqui significa "a API responde",
    não "o sync vai funcionar".
    """
    inicio = time.perf_counter()
    try:
        _get(_ENDPOINT_SAUDE, timeout=timeout, retries=1)
        ok, erro = True, None
    except Exception as e:
        ok, erro = False, f"{type(e).__name__}: {e}".strip()
    return {
        "ok": ok,
        "latencia_ms": int((time.perf_counter() - inicio) * 1000),
        "erro": erro,
        "endpoint": f"{BASE_URL}{_ENDPOINT_SAUDE}",
    }


def esta_disponivel(timeout=10):
    """Teste de conectividade LEVE (endpoint pequeno `/Usuario/Compradores`). True se a
    API respondeu; False em qualquer erro de rede/HTTP. NÃO cacheia (é health-check)."""
    return diagnostico(timeout=timeout)["ok"]
