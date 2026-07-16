# Setup Definitivo do Sistema MRO

## Visão geral

Este setup transforma o projeto em uma base de engenharia madura para evolução contínua do Sistema MRO, preservando a arquitetura atual em Streamlit + SQLite e adicionando camadas de documentação, automação, qualidade e governança.

## Arquitetura ideal

- Camada de apresentação: Streamlit, páginas e componentes reutilizáveis.
- Camada de aplicação: serviços e controladores com regras de negócio.
- Camada de dados: SQLite, schema, migrações e repositórios.
- Camada de domínio: modelos e contratos claros para itens, SCs, requisições, estoque e KPIs.
- Camada de observabilidade: logs, backups, auditoria e métricas.

## Organização proposta

- app/: entrada da aplicação e bootstrapping.
- core/: utilidades transversais e abstrações.
- database/: schema, migrações, seeds e backups.
- repositories/: acesso a dados isolado do restante do app.
- models/: classes e estruturas de domínio.
- controllers/: orquestração entre UI e serviços.
- pages/: páginas Streamlit desacopladas.
- dashboards/: componentes e agregações para visões operacionais.
- reports/: exportações e relatórios.
- assets/: imagens, logos e arquivos estáticos.
- docs/: documentação viva do projeto.
- scripts/: rotinas de manutenção e utilidades.
- tests/: testes unitários, integração, interface e regressão.
- logs/: registros de execução e auditoria.
- backups/: cópias de segurança e snapshots.
- migrations/: histórico versionado de mudanças de schema.
- config/: configuração e parâmetros do sistema.
- prompts/: templates reutilizáveis para IA.
- skills/: expertise operacional para agentes.
- hooks/: validações automáticas antes/depois da edição.
- templates/: modelos de changelog, PR, issues e relatórios.

## Padrões

- Clean Code.
- SOLID.
- DRY.
- KISS.
- PEP8.
- Type hints sempre que possível.
- Docstrings em módulos, funções e classes de regra de negócio.
- Modularização por responsabilidade.
- Baixo acoplamento e alta coesão.

## Fluxo de desenvolvimento

1. Entender o problema.
2. Mapear impactos e riscos.
3. Propor solução com mínimo impacto.
4. Planejar implementação e migração.
5. Implementar em camadas.
6. Validar com testes e dados reais.
7. Documentar.
8. Atualizar changelog.
9. Sugerir evolução futura.

## Riscos

- Alterar regras sem rastreabilidade.
- Aumentar acoplamento entre UI e banco.
- Introduzir duplicação de lógica em services e controllers.
- Fazer alterações de schema sem backup e migração.

## Melhorias futuras

- Separar ainda mais a camada de dados via repositories.
- Introduzir versionamento de schema e rollback automatizado.
- Criar uma camada de API interna para integrações futuras.
- Expandir dashboards para análise preditiva.
