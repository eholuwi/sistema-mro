# Migrações

Este diretório concentra o histórico de mudanças de schema e regras de evolução do banco SQLite.

## Diretrizes

- Cada migração deve ser idempotente.
- Sempre preservar dados existentes.
- Documentar impacto e rollback possível.
