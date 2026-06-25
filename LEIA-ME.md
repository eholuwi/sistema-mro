# MRO Inventus Power — Sistema Atualizado

Aplicação Streamlit para gestão de materiais MRO, compras e inventário operacional.

## Visão geral

O código atual está em `2.0.2/sistema-mro/`.
A aplicação utiliza Streamlit para interface e SQLite para persistência local.

## Arquivos principais

- `app.py` — interface Streamlit, navegação e páginas do aplicativo.
- `database.py` — criação do banco SQLite, migrações, seeds e índices.
- `services/db_functions.py` — regras de negócio, operações de inventário, SC, requisições e movimentações.
- `services/constants.py` — constantes de domínio.
- `services/logging_config.py` — configuração de logging.
- `services/styles.py` — injeção de estilo visual.
- `tests/` — casos de teste com `pytest`.

## Como executar

1. Navegue até `2.0.2/sistema-mro/`.
2. Crie e ative o ambiente virtual.
3. Instale dependências com:

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

- Dashboard
- Inventário
- Gerenciar Itens (inclui edição e alteração de Part Number com histórico)
- Movimentações
- Requisição
- Compras (SC)
- Feedback (sugestões e backlog)
- Configurações (inclui importação da base: Tipo, Mínimo, Máximo, Lead Time)

## Observações

- Versão atual: `2.1.0` (cabeçalho e sidebar atualizados). Ver `changelog/2.1.0.md`.
- A arquitetura atual é monolítica; a lógica de negócio está concentrada em `services/db_functions.py` e parte dela permanece em `app.py`.
- A pasta `.agents/` e `.claude/` são artefatos de ferramenta/IDE e não fazem parte do fluxo de execução do sistema.

## Estrutura do projeto

```text
2.0.2/sistema-mro/
  ├── app.py
  ├── database.py
  ├── requirements.txt
  ├── requirements-dev.txt
  ├── pytest.ini
  ├── services/
  │   ├── constants.py
  │   ├── db_functions.py
  │   ├── logging_config.py
  │   └── styles.py
  └── tests/
```

* schema
* migrações
* pragmas

### `services/db_functions.py`

Núcleo de lógica operacional:

* cálculos
* consultas SQL
* regras de negócio
* analytics

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

## v1.x

* Controle operacional básico
* Gestão de estoque
* SC simples
* Inventário manual

## v2.0.0

* Inteligência logística
* Cobertura real
* Gestão de saldo residual
* Lead Time real
* Rastreabilidade avançada
* Analytics operacionais
* Arquitetura relacional robusta

---

# 🎯 Objetivo Estratégico da v2.0.0

O sistema deixa de atuar apenas como um controle de almoxarifado e passa a operar como:

> uma plataforma de inteligência operacional voltada para prevenção de ruptura, rastreabilidade logística e suporte à tomada de decisão industrial.

---

# 👨‍💻 Desenvolvimento

Desenvolvido por **Luis Gabriel Arruda de Oliveira**
Inventus Power · MRO Intelligence System 🟠
