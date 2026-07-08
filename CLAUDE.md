## 🎯 MRO Skills Framework — LEIA PRIMEIRO

**Este é um projeto MRO real integrado ao Protheus (TOTVS) com impacto direto na operação de Supply Chain, Compras e Almoxarifado.**

### Fluxo Obrigatório para TODA Solicitação
1. ✅ Entender o problema
2. ✅ Identificar impactos técnicos, operacionais e riscos
3. ✅ **Cada uma das 9 Skills abaixo apresenta sua análise**
4. ✅ Consolidar análises → Plano → Aprovação
5. ✅ **Somente após aprovação iniciar implementação**
6. ✅ Validar após conclusão

### Os 9 Especialistas do Projeto
1. **Product Owner** — Priorização, roadmap, MVP, critérios de aceite
2. **Supply Chain Specialist** — Regras de negócio, cálculos, integração Protheus
3. **Database Engineer** — Migrações versionadas, integridade, auditoria
4. **Backend Engineer (Python)** — Implementação de APIs e algoritmos
5. **Data Engineer** — ETL, validação, qualidade de dados
6. **UX/UI Designer** — Usabilidade, fluxos, labels em português
7. **QA Engineer** — Testes, regressão, validação de cálculos
8. **Software Architect** — Arquitetura, SOLID, modularização
9. **DevOps Engineer** — Deploy, versioning, backup, rollback

**Para detalhes completos de cada skill, consulte a memory:** `project_mro_skills_framework.md`

---

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
