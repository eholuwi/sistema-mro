# Banco de Dados

## Estratégia

- SQLite como base operacional atual.
- WAL mode habilitado.
- Migrações versionadas em diretórios dedicados.
- Backups automáticos e snapshots periódicos.

## Princípios

- Nunca apagar dados operacionais sem histórico.
- Preservar integridade referencial.
- Registrar eventos críticos.
- Garantir idempotência em importações.
