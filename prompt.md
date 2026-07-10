# Feedback e Backlog — Sistema MRO

## 1. Dashboard de Comprador (novo)

### Layout geral
- Trocar a navegação por "bolinhas" pelo padrão de abas já usado em outras telas (ex.: Controle de SC, Movimentações).
- Header: "Dashboard Compras MRO" · Inventus Power
- Última atualização: data e hora da planilha "Relatório SCs" importada (ex.: `12/05/2026 - 08:15`)
- Indicador de semana: `WK 20 · Jan-Dez 2026`
  - Convenção Inventus: conta-se por WK (semana). Hoje (09/07/2026) é WK 28. Ano corrente quase sempre — raramente o ano anterior importa.
- Card com todos os solicitantes do material MRO.

### KPIs — Linha 1
- Itens em aberto — SCs do material MRO com Status = Cotação
- Itens Críticos — SCs com estoque abaixo do mínimo
- Aging médio — tempo médio entre Emissão e Atendimento da SC
- SCs abertas do MRO
- POs emitidos do MRO
- Valor em compras do MRO

### KPIs — Linha 2
- **Evolução Semanal**: Itens aprovados vs. POs emitidas — gráfico de linhas por WK. Mostra se compras está acompanhando a demanda.
- **📈 Volume Mensal**: Itens / SC / POs — gráfico agrupado.

### 🚨 Painel de Prioridades (parte MAIS importante)
- Tabela: Aging · SC · Item · PN · Comprador · Departamento
- Ordenada automaticamente, mais velho primeiro — é literalmente a fila do dia.

### 🟠 Distribuição do Aging
- Faixas: 0-7, 8-15, 16-30, 31-60, 60+
- Cores: verde, amarelo, laranja, vermelho

### 📦 Departamentos
- Barra horizontal — quem mais solicita: Manutenção, Engenharia, Produto, Industrial, TI, RH.

### 👨‍💼 Solicitantes
- Top solicitantes — quem mais gera demanda; ajuda a identificar gargalos.

### 🏭 Fornecedores
- Top 10 por: Valor, Quantidade, Itens, PO, Lead Time, Entrega.

### 📉 Tempo SC → PO
- Gráfico já existe — trocar para histograma: 1 dia, 2-5, 6-10, 11-20, 20+. Mostra eficiência.

### 📅 Lead Time por Fornecedor
- Comparativo fornecedor vs. tempo médio de compra (ex.: Fornecedor A 12 dias, Fornecedor B 4 dias, Fornecedor C 38 dias). Excelente para negociação.

### 💸 Valor Comprado
- Ranking de fornecedores por valor.

### 📈 Comparativo por Comprador
- Ex.: Miguel, Davi (ou qualquer outro, somente os que compram material MRO).
- Mostrar: Itens, PO, Valor, Aging médio.

### 💰 Saving do material MRO
- Saving mensal.

---

## 2. Ideia de Dashboard Geral do Almoxarifado (conceito de referência)

> Mockup solto compartilhado como inspiração — não necessariamente a Dashboard de Comprador acima.

### KPIs gerais (saúde do almoxarifado)
- 📦 Itens Cadastrados — 2.348
- 📥 Entradas Hoje — 42
- 📤 Requisições Hoje — 67
- 📉 Estoque Baixo — 38
- 🔴 Compra Urgente — 11
- ⚠️ Materiais Sem Giro — 126
- 📦 Valor Estoque — R$ 3.421.884
- 📊 Cobertura Média — 47 dias

### 🚨 Prioridades do Dia ⭐ (tela mais importante — substitui "ficar procurando problema")
- 🔴 Comprar imediatamente — ex.: Fita Kapton, Luva Nitrílica, Cabo USB Industrial
- 🟠 Abaixo do mínimo — 18 materiais
- 🟡 Cobertura menor que Lead Time — 9 materiais
- 🔵 Entradas pendentes — 13 materiais *(só quando requisições digitais forem implementadas)*
- 🟢 Requisições aguardando separação — 7 *(só quando requisições digitais forem implementadas)*
- Ao abrir o sistema, ele já sabe onde agir.

### 📦 Saúde do Estoque (painel grande)
- **Distribuição**: 🟢 OK / 🔴 Comprar / 🟡 Atenção
- **Cobertura** (barra horizontal): até 7 dias, 8-15, 16-30, 31-60, 60+, 180+, 365+ — facilita enxergar materiais parados.
- **Curva ABC**: A 15% / B 35% / C 50%

### 📥 Entradas
- Períodos: Hoje / Semana / Mês
- Colunas: Fornecedor, Nota Fiscal, Quantidade, Valor, Tempo até armazenagem
- Gráficos: Entradas por dia · Top fornecedores · Top materiais recebidos

### 📤 Saídas
- Diferença enorme do sistema atual (hoje controlado apenas via requisições) — vale um dashboard completo.
- KPIs: Saídas Hoje (42), Semana (198), Mês (963)
- Materiais mais consumidos (barras)
- Setores que mais retiram: Manutenção, Produção, Engenharia, Facilities, TI

### 📈 Consumo
- Gráfico de linha estilo ERP (Janeiro, Fevereiro, Março...), quebrado por PN.

### 🗺️ Mapa do Almoxarifado ⭐ (inovação)
- Visualização das prateleiras por status de cor (ex.: A01 🟢, A02 🟢, A03 🔴, A04 🟡, B01 🟢...).
- Ao clicar numa posição, mostra todos os materiais daquela localização.

### 📈 Histórico
- Gráfico de Entradas ↓ / Saídas ↓ / Saldo — últimos 24 meses.

---

## 3. Ajustes em Telas Existentes

### Dashboards
- Remover o Dashboard de Diretoria.
- Manter o Dashboard Mensal — só renomear para **"KPI Mensal"** (está ótimo como está).

### Inventário — Contagem Física
- Hoje só existe a 1ª locação para input. Adicionar também a 2ª locação.
- A 2ª locação parece ter virado "ajuste de inventário" — **manter** esse ajuste, mas incluir também a opção de 2º local.

### Ficha 360
- "Saldo residual (Guarda-Chuva)" → título deve ser apenas **"Saldo Residual"**.
- Deixar mais bonitos os gráficos "Consumo médio/dia por janela" e "Consumo real por mês".

### Movimentações
- Reordenar as abas para: 1) Analytics · 2) Ajuste Rápido · 3) Histórico completo.
- Remover o gráfico "Evolução de preço (por item)" da aba Analytics.
- Em aberto: deixar o histórico de movimentações mais completo — pedir sugestões de conteúdo.

### Configurações
- Adicionar todos os fornecedores do material MRO.

### Controle de SC → aba "Atualizar Status e Dados da S.C."
- Hoje o campo sempre vem preenchido com o primeiro pedido. Deixar vazio para forçar o usuário a selecionar.

### Receber Material
- Adicionar opção de receber por SC também.

### Fornecedores & Cotação
- Campo "Buscar material (PN, nome ou descrição)" parece redundante/erro — revisar.
- No select "Selecione o material" abaixo, permitir consulta também por descrição do material.

### Assistente de Reposição
- Simplificar o fluxo:
  1. Mostrar todo material crítico ou em atenção para seleção.
  2. Usuário seleciona os materiais e clica em "Criar SC".
  3. Sistema organiza as SCs por **TIPO** do material.
  4. Sistema sugere uma "descrição" padrão (ex.: "SOLICITAÇÃO DE COMPRA - OUTROS") e uma Justificativa.
     - A justificativa deve mencionar que o material é para consumo de 2 meses, com base no giro de estoque do sistema MRO e na qty mín/máx.
  5. Montar tabela com: estoque atual, mínimo, máximo, segurança (⚠️ revisar cálculo — alguns materiais estão dando números quebrados), cobertura, consumo/dia + unidade, e setores de destino do material.
  6. Anexar print dessa tabela na SC de todo material solicitado.
- Formato validado (gostou bastante) — **"SCs sugeridas"**: itens agrupados pelo Tipo do material (campo do cadastro do item), com título, justificativa e centro de custo sugeridos. Revisar, editar e criar a SC agrupada em um clique — o sistema recomenda, o usuário decide.
  - Exemplos: `ESD · 3 itens · 🔴 Crítico · Parada de Linha · comprar até 09/07`, `Consumível · 26 itens · 🔴 Crítico · Parada de Linha · comprar até 09/07`, `Limpeza Stencil · 1 item · 🔴 Crítico · Parada de Linha · comprar até 09/07`, `Expediente · 23 itens · 🔴 Crítico · comprar até 09/07`, `Vestimenta ESD · 17 itens · 🔴 Crítico · comprar até 09/07`, `Corte · 1 item · 🔴 Crítico · comprar até 09/07`
  - "Detalhe e ação por item" não se mostrou útil — repensar ou remover.

### Requisição de Material
- Deixar mais bonito e detalhado, incluindo o "Histórico de Requisições".

---

## 4. Próximos Passos
- Planejar as **requisições digitais** — usuário pediu para ser entrevistado sobre o tema.
