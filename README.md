# Sistema MRO — Inventus Power

Gestão de materiais MRO (Manutenção, Reparo e Operações) da Inventus Power (Manaus).
Controla inventário, reposição, compras e cobertura de estoque, integrado ao **Protheus
(TOTVS)** e à **API do SCM**.

O objetivo é um só: **nunca deixar faltar material** — sem comprar demais.

Aplicação web em Streamlit, rodando num PC-servidor da rede. Compradores e almoxarifado
acessam pelo navegador, sem instalar nada.

---

## Rodar localmente

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
venv\Scripts\python.exe -m streamlit run app.py
```

O banco (`mro.db`) é criado e migrado sozinho na primeira execução.

Para instalar no servidor, ver [docs/INSTALACAO_SERVIDOR.md](docs/INSTALACAO_SERVIDOR.md).

---

## Gate de qualidade

```powershell
.\verify.ps1
```

`ruff format --check` + `ruff check` + `pytest`. **Exit 0 é o critério de pronto** — nada é
considerado concluído sem ele verde. O mesmo gate roda no CI a cada push
([`.github/workflows/verify.yml`](.github/workflows/verify.yml)).

Suíte: 491 testes, ~1 min.

---

## Estrutura

```
app.py                 shell (49 linhas): setup + sidebar + despacho
database.py            schema, migrações (criar_banco/_migrar), backup
services/              lógica de negócio, sem Streamlit
  db_functions.py        núcleo (inventário, movimentações, SCs, compras)
  planejamento.py        ROP, cobertura, quantidade sugerida
  classificacao.py       curva ABC, padrão de demanda (XYZ)
  dashboards.py          montagem dos painéis
  scm_client.py          cliente HTTP da API do SCM (só leitura)
  scm_sync.py            sincronização API → mro.db
ui/                    camada de interface
  router.py              fonte única do menu e do despacho
  paginas/               as 9 páginas, uma por arquivo
  componentes/           filtros, tabela paginada, seleção, gráficos
  cache.py               wrappers de @st.cache_data
tests/                 pytest, banco isolado por teste
deploy/                config e launchers do PC-servidor
scripts/release.py     empacota a release
changelog/             um arquivo por versão
```

**Regra de dependência:** `ui/paginas/*` importa `ui/*` e `services/*`;
**`services/*` nunca importa `ui/`** — a camada de serviço fica pura e testável.

---

## Páginas

Dashboard · Saldo em Estoque · Gerenciar Itens · Movimentação · Ficha 360 ·
Controle de SC · SCM Integrado · Configurações · Ajuda

---

## Stack

Python · Streamlit · SQLite (WAL, foreign keys ativas) · pandas · Plotly.
Sem ORM — `sqlite3` direto, com `transaction()` como context manager.

Dependências têm versão fixada em `requirements.txt`. Ao alterar qualquer pin, rode o gate
**e** abra o app: a suíte cobre `services/` e `database.py`, mas `ui/` só tem smoke de render
por rota.

---

## Documentação

| Arquivo | Para quê |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Regras, convenções e mapa de módulos — **fonte única** |
| [docs/FUNCIONALIDADES.md](docs/FUNCIONALIDADES.md) | O que o sistema calcula e por quê |
| [docs/HANDOFF.md](docs/HANDOFF.md) | Estado atual e continuidade entre sessões/máquinas |
| [docs/INSTALACAO_SERVIDOR.md](docs/INSTALACAO_SERVIDOR.md) | Instalação no PC-servidor |
| [docs/PLANO_V5_EVOLUCAO.md](docs/PLANO_V5_EVOLUCAO.md) | Plano da refatoração v5.x |
| [docs/REGRAS_DE_NEGOCIO.md](docs/REGRAS_DE_NEGOCIO.md) | Ciclo da Requisição Digital |
| [docs/prompt.md](docs/prompt.md) | Backlog vivo |
| [changelog/](changelog/) | Histórico versão a versão |

---

## Dado operacional

Este repositório é **público** e contém apenas código. Banco (`mro.db`), backups, exports de
inventário e planilhas de SC ficam **fora do versionamento** — ver `.gitignore`.
