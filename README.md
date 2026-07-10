# MRO Inventus Power v2.8.0

## Plataforma Inteligente de Gestão MRO, Compras e Rastreabilidade Operacional

O **MRO Inventus Power** é uma plataforma modular que centraliza a gestão de materiais de manutenção, reparo e operação (MRO), eliminando planilhas paralelas e trazendo inteligência operacional com assistência de reposição e consolidação completa da vida útil do material.

A versão **2.7.0** (04/07/2026) adiciona a **higiene da lista de compra**: itens que nunca tiveram consumo real (nenhuma saída por requisição) ganham o status **`⚪ Sem Movimentação`** e saem da lista de COMPRAR — que caiu de 227 para 77 candidatos reais no banco de produção. Mantém o foco em:

* **Prevenção de ruptura** com assistência inteligente de reposição
* **Rastreabilidade completa** desde cadastro até consumo
* **Ficha 360 do Material** — consolidação da vida útil
* **Gestão de saldo residual** e estoque em trânsito
* **Lead Time efetivo** — calculado + cadastrado
* **Análise por departamento** e centro de custo
* **180+ testes** para estabilidade

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

Central de decisão operacional com:

* KPIs de estoque (cobertura, dias até ruptura)
* Itens críticos identificados
* Cobertura real (com estoque em trânsito)
* SCs com ação pendente
* Pendências de inventário
* Tendência de consumo
* Alertas de ruptura

### Cobertura Real

O sistema calcula automaticamente:

```text
(Estoque Atual + Estoque em Trânsito) / Consumo Diário
```

Com base no Lead Time, identifica:

* 🔴 risco de ruptura (≤ ROP)
* 🟡 atenção operacional (antecedência 15d)
* 🟢 estoque seguro

## 🧠 Assistente de Reposição (v2.5.0+)

Motor inteligente que transforma dados em ações de compra:

* **ROP (Reorder Point)** = consumo_diário × lead_time + estoque_segurança
* **Gatilho com antecedência** — dispara 15 dias antes da ruptura
* **Quantidade sugerida híbrida** — máximo entre piso do Neidson e 60 dias de consumo
* **Priorização automática** — crítico → antecipar → atenção
* **Fila priorizada** — "o quê, quando, quanto, por quê, de quem"
* **Agrupamento por fornecedor** — otimiza pedidos
* **Auditoria de decisões** — rastreia "Criar SC", "Adiar", "Ignorar"

### Princípio: Assistente, não Piloto Automático
O sistema RECOMENDA, o comprador DECIDE. Nunca sobrescreve a base do Neidson (mín/máx/lead time).

## 📇 Ficha 360 do Material (v2.6.0+)

Consolidação completa da vida útil de um item em uma tela:

* **Cadastro** — descrição, tipo, localização
* **Estoque** — atual, mínimo, máximo, segurança
* **Cobertura** — dias até ruptura, ROP
* **Consumo** — por dia, tendência (30/60/90d), por departamento/centro de custo
* **Compras** — histórico de SCs, POs, lead time real vs cadastrado
* **Utilização** — giro, dias em estoque, valor consumido
* **ABC** — classe ABC e evolução de preço
* **Fornecedores** — lista e histórico
* **Imagem** — upload do produto (png/jpg/webp)
* **Histórico** — Part Number, movimentações, decisões de reposição
* **Recomendação** — sugestão de reposição com transparência

---

# 🧾 Gestão Inteligente — Controle de SC

Separação completa entre saúde do estoque e fluxo administrativo da compra:

## Status Material

Condição física do estoque (calculada):

* 🟢 OK — estoque acima da faixa de atenção
* 🟡 ATENÇÃO — dentro de 20% acima do mínimo
* 🔴 COMPRAR — estoque ≤ mínimo **e com consumo real** (candidato de compra)
* ⚪ Sem Movimentação (v2.7.0) — nunca teve saída por requisição; fora da lista de compra, revisável no Assistente

## Status SC

Andamento administrativo da compra (manual):

* 📢 Aprovação
* ⚠️ Cotação
* 🚚 Aguardando Entrega
* ✅ Concluída

---

## 📦 Estoque em Trânsito (Guarda-Chuva)

Cálculo automático que evita compras duplicadas:

* **Saldo residual** — quanto ainda falta chegar de SCs anteriores
* **Recebimentos parciais** — rastreamento de múltiplas entregas
* **Desconto da quantidade** — protege contra pedir em duplicidade

Evita:

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
sistema-mro/
├── app.py                       (interface Streamlit, navegação)
├── database.py                  (SQLite, migrações, pragmas)
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── services/
│   ├── db_functions.py          (core: 136KB, inventário, SC, requisições)
│   ├── planejamento.py          (v2.5.0: assistente de reposição)
│   ├── ficha.py                 (v2.6.0: consolidação por item)
│   ├── constants.py
│   ├── logging_config.py
│   └── styles.py
├── tests/                       (180+ testes)
├── changelog/
├── docs/                        (blueprints, contexto)
└── docs/itens/                  (imagens de produtos)
```

## Arquivos Principais

### `app.py`

Interface Streamlit: navegação, renderização, páginas do aplicativo.

### `database.py`

Gerencia:
* conexão SQLite (WAL mode)
* schema relacional
* migrações aditivas (não-destrutivas)
* pragmas (`foreign_keys=ON`)

### `services/db_functions.py`

Núcleo operacional (136 KB):
* cálculos de cobertura, ROP, giro
* consultas SQL otimizadas
* regras de negócio (estoque, inventário, SC, requisições)
* analytics (ABC, consumo, lead time)

### `services/planejamento.py` (v2.5.0+)

Motor de reposição modular:
* cálculo de ROP e gatilho
* quantidade sugerida
* priorização
* decisões auditadas

### `services/ficha.py` (v2.6.0+)

Consolidação de dados por item:
* consumo por departamento
* montagem da ficha 360
* imagem do produto

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

## v1.x — Controle Básico

* Gestão de estoque operacional
* SC simples
* Inventário manual

## v2.0–2.1 — Inteligência Logística

* Cobertura real (estoque + em trânsito / consumo)
* Gestão de saldo residual
* Lead Time real
* Rastreabilidade avançada
* Analytics operacionais

## v2.2–2.4 — Consolidação de Dados

* Consumo real calculado (não apenas registrado)
* Lead Time efetivo (calculado + cadastrado)
* Estoque de segurança
* Curva ABC (quantidade e valor)
* Fornecedores por item

## v2.5 — Pilar de Planejamento

* Assistente de Reposição: ROP, gatilho, quantidade sugerida
* Priorização automática (crítico, antecipar, atenção)
* Fila priorizada com auditoria
* Motor modular (`services/planejamento.py`)

## v2.6 — Ficha 360 do Material

* Consolidação completa por item
* Consumo por departamento/centro de custo
* Imagem do produto
* Recomendação embutida
* 180+ testes

---

# 🎯 Objetivo Estratégico

O sistema opera como:

> uma plataforma de inteligência operacional voltada para **prevenção de ruptura**, **rastreabilidade logística** e **suporte à tomada de decisão industrial** — com **assistência inteligente de reposição** e **consolidação completa da vida útil do material**.

---

---

# 🚀 Próximos Passos

* **v2.7.0** — Críticos automáticos, XYZ & Sazonalidade
* **v3.0.0** — Dashboards por público (Comprador / Gestão / KPI Mensal)

---

# 👨‍💻 Desenvolvimento

Desenvolvido por **Luis Gabriel Arruda de Oliveira**
Inventus Power · MRO Intelligence System 🟠

Última atualização: **04/07/2026** (v2.8.0)
