# MRO Inventus Power v2.0.0

## Sistema Inteligente de Gestão MRO, Compras e Rastreabilidade Operacional

O **MRO Inventus Power** é uma plataforma desenvolvida para centralizar a gestão de materiais de manutenção, reparo e operação (MRO), eliminando dependência de planilhas paralelas e trazendo inteligência operacional para estoque, inventário e compras.

A versão **2.0.0** representa a evolução do sistema para uma arquitetura orientada à tomada de decisão, com foco em:

* prevenção de ruptura
* rastreabilidade operacional
* gestão inteligente de SCs
* controle de inventário
* integração logística
* governança de dados

---

# 🚀 Principais Objetivos

* Evitar paradas de linha por falta de material
* Centralizar o fluxo de compras e inventário
* Automatizar cálculos operacionais
* Garantir rastreabilidade completa
* Reduzir erros humanos e inconsistências
* Transformar dados operacionais em inteligência logística

---

# 🧠 Principais Recursos

## 📊 Dashboard Inteligente

O Dashboard opera como uma central de decisão operacional.

### Recursos:

* KPIs de estoque
* Itens críticos
* Cobertura real de estoque
* SCs com ação pendente
* Pendências de inventário
* Histórico operacional
* Analytics de ruptura

### Cobertura Real

O sistema calcula automaticamente:

```text
(Estoque Atual + Estoque em Trânsito) / Consumo Diário
```

Com base no Lead Time, o sistema identifica:

* 🔴 risco de ruptura
* 🟡 atenção operacional
* 🟢 estoque seguro

---

# 🧾 Gestão Inteligente de Compras (SC)

A versão 2.0 introduz uma separação completa entre:

* saúde do estoque
* fluxo administrativo da compra

## Status Material

Representa a condição física do estoque:

* 🟢 OK
* 🟡 ATENÇÃO
* 🔴 COMPRAR

## Status SC

Representa o andamento da compra:

* 📢 Aprovação
* ⚠️ Cotação
* 🚚 Aguardando Entrega
* ✅ Concluída

---

## 📦 Estoque em Trânsito

O sistema calcula automaticamente:

* saldo residual
* recebimentos parciais
* materiais ainda pendentes

Isso evita:

* compras duplicadas
* excesso de estoque
* falso alerta de ruptura

---

# 🔄 Inventário & Rastreabilidade

## Controle de Localização

Cada item pode possuir:

* Local
* Caixa/ID
* Histórico de movimentação

## Registro Inteligente

Toda alteração de localização gera histórico automático:

```text
20 UN ARM 12 → MRO 20
```

---

## Integridade de Dados

Movimentações de localização sem alteração de quantidade:

* não afetam curva ABC
* não afetam consumo médio
* não distorcem analytics

---

# 📈 Inteligência Operacional

## Previsão de Ruptura

Cálculo automático:

```text
estoque_atual / consumo_diario
```

Permite prever quantos dias restam até ruptura.

---

## Priorização Automática

O sistema identifica palavras críticas durante importações:

* parada
* urgente
* crítica
* linha

E eleva automaticamente o item para:

```text
🔴 Parada de Linha
```

---

# 🔗 Integração com ERP (Protheus)

O módulo de importação realiza:

* normalização de textos
* remoção de acentos
* padronização de nomenclatura
* prevenção de itens duplicados

---

# ⚙️ Arquitetura Técnica

## Stack Tecnológica

| Camada         | Tecnologia            |
| -------------- | --------------------- |
| Backend        | Python 3.8+           |
| Interface      | Streamlit             |
| Banco de Dados | SQLite                |
| Visualização   | Plotly                |
| Navegação      | streamlit-option-menu |

---

## Performance & Robustez

### SQLite WAL Mode

```sql
PRAGMA journal_mode = WAL;
```

Permite:

* múltiplas leituras simultâneas
* redução de bloqueio de escrita
* maior estabilidade multiusuário

---

## Integridade Referencial

```sql
PRAGMA foreign_keys = ON;
```

Evita:

* registros órfãos
* inconsistência de movimentações
* falhas de relacionamento

---

# 📂 Estrutura do Projeto

```text
├── app.py
├── database.py
├── services/
│   └── db_functions.py
├── requirements.txt
├── mro.db
```

## Arquivos Principais

### `app.py`

Responsável pela interface, navegação e renderização.

### `database.py`

Gerencia:

* conexão SQLite
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
