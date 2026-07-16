# Arquitetura do Sistema MRO

## Objetivo

Garantir uma base modular para evolução do sistema sem comprometer a operação atual.

## Camadas

### 1. Apresentação

- Streamlit como interface.
- Componentes organizados por páginas e widgets reutilizáveis.

### 2. Aplicação

- Serviços encapsulam regra de negócio.
- Controladores coordenam ações entre UI, serviços e banco.

### 3. Dados

- SQLite como banco operacional.
- Repositórios isolam leitura/escrita.
- Migrações versionadas e backups automatizados.

### 4. Observabilidade

- Logs, auditoria e snapshots para rastrear mudanças.

## Diretrizes de evolução

- Nenhuma tela deve fazer leitura/escrita direta sem passar por uma camada intermediária.
- Regras de negócio não devem ficar em app.py.
- O banco deve ser tratado como ativo operacional e protegido.
