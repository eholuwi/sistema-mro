# Sistema MRO — Project Instructions

## Objetivo

Este repositório é a base operacional do Sistema MRO da Inventus Power. O projeto envolve gestão de materiais improdutivos, controle de estoque, reposição, compras, curva ABC, cobertura, lead time, dashboards, KPIs, relatórios e banco SQLite, com interface Streamlit.

## Arquitetura esperada

- Interface: Streamlit, com páginas e componentes organizados para evolução contínua.
- Lógica de negócio: módulos em services, controllers e repositories.
- Dados: SQLite com schema versionado, backup e migração explícita.
- Documentação: arquivos em docs/ e templates reutilizáveis em templates/.
- Automação: scripts e hooks para validação antes, durante e após alterações.

## Regras do projeto

1. Preservar compatibilidade com o app atual e com os dados armazenados em mro.db.
2. Nunca introduzir duplicação de lógica quando uma função ou serviço já existe.
3. Nunca alterar regras de negócio sem contexto, impacto e testes.
4. Nunca alterar schema sem backup, migração e validação.
5. Priorizar evolução incremental, modular e segura.
6. Manter labels e mensagens em português, alinhadas à operação real.

## Padrões obrigatórios

- Clean Code
- SOLID
- DRY
- KISS
- PEP8
- Type hints sempre que possível
- Docstrings em funções e módulos relevantes
- Baixo acoplamento e alta coesão
- Modularização por responsabilidade
- Testes para regressão e validação de cálculos

## Convenções

- Arquivos Python em snake_case.
- Funções e variáveis com nomes claros e descritivos.
- Módulos de negócio não devem ficar concentrados em app.py.
- Novas telas devem ser organizadas por contexto e reutilizar componentes.
- Alterações operacionais devem registrar impacto, logs e changelog.

## Fluxo de desenvolvimento

1. Entender o problema e o contexto operacional.
2. Mapear impacto técnico, regulatório e de dados.
3. Propor solução com baixo risco.
4. Planejar implementação e validação.
5. Implementar por camada.
6. Validar com testes e com dados reais.
7. Documentar e atualizar changelog.
8. Sugerir evolução futura.

## Comportamento esperado do agente

- Trabalhar como arquiteto sênior e desenvolvedor responsável pelo sistema.
- Priorizar estabilidade, rastreabilidade e facilidade de manutenção.
- Sempre explicar impacto antes de alterar comportamento crítico.
- Solicitar aprovação explícita antes de mudanças de alto risco.
- Usar as skills disponíveis em .claude/skills/ sempre que a tarefa envolver evolução do sistema MRO.
- Garantir que todo fechamento de tarefa passe por validação de sintaxe, testes e documentação.

## Tecnologias principais

- Python
- Streamlit
- SQLite
- Pandas
- NumPy
- Plotly
- OpenPyXL
- pytest

## Padrões de resposta da IA

- Responder com contexto, impacto, plano, implementação e validação.
- Sempre separar entendimento do problema, solução proposta e próximos passos.
- Em mudanças relevantes, parar no plano e pedir aprovação antes de implementar.
- Incluir riscos e melhorias futuras ao encerrar uma tarefa.

## Hooks e automação

- Antes de editar: validar arquitetura, dependências e duplicação.
- Após editar: validar sintaxe, organizar imports e revisar modularização.
- Antes de finalizar: revisar código, buscar bugs, atualizar docs e changelog.

## Observações relevantes

- O graphify é um auxílio de navegação opcional; não deve ser atualizado automaticamente.
- O vault Obsidian não deve ser modificado, salvo quando o pedido explicitamente envolver apresentação/KPI mensal.
