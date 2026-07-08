## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Segundo Cérebro (Obsidian)

Este projeto tem um vault Obsidian dedicado em `vault/`, sincronizado entre múltiplas máquinas, usado para preparar a apresentação do MRO System na reunião mensal de KPI da Inventus Power.

Rules:
- `vault/CLAUDE.md` tem o protocolo completo de sessão (o que ler ao iniciar, o que escrever ao finalizar).
- Para qualquer tarefa relacionada à apresentação/KPI mensal, ler primeiro `vault/Projects/Apresentação Inventus Power - KPI Mensal.md`, a Daily Note mais recente em `vault/Daily Notes/` e o Session Log mais recente em `vault/AI/Sessions/`.
- Ao finalizar um trabalho relevante nessa frente, gerar um novo Session Log em `vault/AI/Sessions/` e atualizar a Daily Note do dia — segue o método descrito em `vault/CLAUDE.md`.
- Sempre fazer `git pull` antes de começar a trabalhar e `git push` após terminar, para manter o vault sincronizado entre computadores.
