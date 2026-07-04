# MRO Inventus Power v2.7.0

Plataforma inteligente de gestão MRO, compras, inventário e rastreabilidade operacional com 190+ testes.

## Visão geral

Aplicação Streamlit + SQLite para inteligência operacional: prevenção de ruptura, rastreabilidade logística e suporte à tomada de decisão industrial. Versão atual: **2.7.0** (04/07/2026) — higiene da lista de compra com o status **⚪ Sem Movimentação**.

## Arquivos principais

- `app.py` — interface Streamlit, navegação e páginas do aplicativo.
- `database.py` — criação do banco SQLite, migrações, seeds e índices.
- `services/db_functions.py` — núcleo de lógica operacional (inventário, SC, requisições, movimentações).
- `services/planejamento.py` — motor de reposição inteligente (v2.5.0+).
- `services/ficha.py` — montagem da Ficha 360 do Material (v2.6.0+).
- `services/constants.py` — constantes de domínio.
- `services/logging_config.py` — configuração de logging.
- `services/styles.py` — injeção de estilo visual.
- `tests/` — 180+ casos de teste com `pytest`.

## Como executar

1. Crie e ative o ambiente virtual.
2. Instale dependências com:

```powershell
pip install -r requirements.txt
```

4. Execute a aplicação com:

```powershell
streamlit run app.py
```

## Banco de dados local

- O arquivo SQLite `mro.db` é criado automaticamente na mesma pasta.
- `database.py` habilita `PRAGMA journal_mode = WAL` para melhor comportamento de escrita/leitura.
- A migração de esquema é feita de forma não-destrutiva com `PRAGMA table_info` e `ALTER TABLE ADD COLUMN`.

## Páginas da aplicação

- **Dashboard** — KPIs, itens críticos, cobertura real, pendências.
- **Ficha 360 do Material** (v2.6.0) — consolidado: cadastro, estoque, consumo, compras, utilização, indicadores, histórico de vida útil, imagem do produto.
- **Inventário** — visualização e filtros.
- **Gerenciar Itens** — edição, alteração de Part Number com histórico.
- **Movimentações** — histórico de entradas/saídas com rastreabilidade.
- **Requisição** — solicitações operacionais.
- **Compras (SC)** — gestão de solicitações de compra com **Assistente de Reposição** (v2.5.0): fila priorizada, gatilhos de reposição, quantidade sugerida, decisões auditadas.
- **Feedback** — sugestões e backlog.
- **Configurações** — importação de base (Tipo, Mín/Máx, Lead Time).

## Observações

- Versão atual: `2.6.0` (Ficha 360 + Imagem do Produto).
- Arquitetura modularizada: `db_functions.py` (core), `planejamento.py` (reposição), `ficha.py` (consolidação).
- 180+ testes com cobertura de cálculos, migrações, integração e UI.
- A pasta `.agents/` e `.claude/` são artefatos de ferramenta/IDE.

## Estrutura do projeto

```text
sistema-mro/
  ├── app.py
  ├── database.py
  ├── requirements.txt
  ├── requirements-dev.txt
  ├── pytest.ini
  ├── services/
  │   ├── db_functions.py      (core: inventário, SC, requisições)
  │   ├── planejamento.py      (v2.5.0: assistente de reposição)
  │   ├── ficha.py             (v2.6.0: ficha 360 do material)
  │   ├── constants.py
  │   ├── logging_config.py
  │   └── styles.py
  ├── tests/                   (180+ testes)
  ├── changelog/               (histórico de releases)
  ├── docs/                    (blueprints e contexto)
  └── docs/itens/              (imagens de produtos)
```

### Módulos principais

- **`db_functions.py`**: cálculos, consultas SQL, regras de negócio, analytics.
- **`planejamento.py`**: motor de reposição (ROP, gatilho com antecedência, quantidade híbrida).
- **`ficha.py`**: consolidação de dados por item (consumo por departamento, imagem, histórico).

---

# 🛠️ Instalação

## 1. Criar ambiente virtual

```bash
python -m venv venv
```

---

## 2. Ativar ambiente

### Windows

```bash
venv\Scripts\activate
```

### Linux/macOS

```bash
source venv/bin/activate
```

---

## 3. Instalar dependências

```bash
pip install -r requirements.txt
```

---

## 4. Executar sistema

```bash
streamlit run app.py
```

---

# 🗄️ Banco de Dados

O sistema utiliza:

```text
mro.db
```

As migrações são automáticas e não destrutivas.

O mecanismo `_migrar()`:

* verifica colunas existentes
* adiciona novos campos
* preserva dados antigos

---

# 📌 Evolução da Plataforma

## v1.x — Controle Operacional

* Gestão de estoque básica
* SC simples
* Inventário manual

## v2.0–2.1 — Inteligência Logística

* Cobertura real (estoque + em trânsito / consumo)
* Gestão de saldo residual
* Lead Time real
* Rastreabilidade avançada
* Analytics operacionais

## v2.2–2.4 — Consolidação de Dados

* Consumo real por item
* Lead Time efetivo (calculado + cadastrado)
* Estoque de segurança
* Curva ABC (quantidade + valor)
* Fornecedores por item

## v2.5 — Pilar de Planejamento

* Assistente de Reposição (ROP + gatilho + quantidade sugerida)
* Priorização automática (crítico, antecipar, atenção)
* Fila priorizada com auditoria de decisões
* Motor de reposição testável e modular

## v2.6 — Ficha 360 do Material

* Consolidação completa: cadastro + estoque + consumo + compras + histórico
* Imagem do produto (upload/remoção)
* Consumo por departamento/centro de custo
* Recomendação de reposição embutida
* Transparência de origem e fórmulas

---

# 🎯 Objetivo Estratégico

O sistema opera como:

> uma plataforma de inteligência operacional voltada para prevenção de ruptura, rastreabilidade logística e suporte à tomada de decisão industrial — com assistência inteligente de reposição e consolidação completa da vida útil do material.

---

---

# 🚀 Próximos Passos

* **v2.7.0** — Críticos automáticos, XYZ & Sazonalidade
* **v3.0.0** — Dashboards por público (Comprador / Gestão / Diretoria)

---

# 👨‍💻 Desenvolvimento

Desenvolvido por **Luis Gabriel Arruda de Oliveira**
Inventus Power · MRO Intelligence System 🟠

Última atualização: **04/07/2026** (v2.7.0)
