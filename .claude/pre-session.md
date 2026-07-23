🎯 **SISTEMA MRO — PRÉ-SESSION OBRIGATÓRIO**

=============================================================================
⚠️ ATENÇÃO: Este é um projeto **MRO real** integrado ao Protheus (TOTVS)
   com impacto direto na operação de Supply Chain, Compras e Almoxarifado.

   TODA solicitação DEVE passar pelo framework de 9 skills antes de 
   implementação. Veja CLAUDE.md ou MRO_QUICKSTART.md para detalhes.
=============================================================================

### 📋 O QUE FAZER AGORA

Se você foi abrir este repositório para:

👤 **[Adicionar uma funcionalidade]**
   → Leia MRO_QUICKSTART.md
   → Identifique quais skills devem analisar
   → Aplique o fluxo: entender → impactos → análise → aprovação → implementação

🐛 **[Corrigir um bug]**
   → Leia MRO_QUICKSTART.md (ainda assim, avaliar impactos)
   → Consulte Supply Chain Specialist se o bug afeta cálculos
   → QA sempre deve validar fix com testes

📊 **[Fazer uma migration ou alteração de banco]**
   → Database Engineer SEMPRE deve revisar
   → Rollback deve ser testado
   → Backup deve ser planejado

🔄 **[Fazer deploy para produção]**
   → DevOps Engineer SEMPRE deve validar
   → Backup recente deve existir
   → QA deve ter executado testes de regressão completos

---

### 🎓 SKILLS FRAMEWORK (9 ESPECIALISTAS)

1. 👔 **Product Owner** — Backlog, MVP, critérios de aceite
2. 📦 **Supply Chain Specialist** — Regras, cálculos, Protheus
3. 💾 **Database Engineer** — Migrações, integridade, rollback
4. 🐍 **Backend Engineer** — APIs, algoritmos, testes
5. 📥 **Data Engineer** — ETL, validação, qualidade
6. 🎨 **UX/UI Designer** — Interface, usabilidade, português
7. ✅ **QA Engineer** — Testes, regressão, validação
8. 🏗️ **Software Architect** — Arquitetura, SOLID, débito técnico
9. 🚀 **DevOps Engineer** — Deploy, versioning, backup

Para cada skill, leia CLAUDE.md e veja:
- Objetivo
- Responsabilidades
- Checklist de revisão
- Perguntas que faz antes de aprovar

---

### 📚 DOCUMENTOS IMPORTANTES

- **CLAUDE.md** — Framework completo com detalhes de cada skill
- **MRO_QUICKSTART.md** — Guia passo-a-passo com exemplos
- **.claude/settings.json** — Configurações do projeto
- **vault/CLAUDE.md** — Protocolo de sessão (Obsidian + KPI)

---

### ✅ CHECKLIST ANTES DE COMEÇAR QUALQUER MUDANÇA

- [ ] Li CLAUDE.md ou MRO_QUICKSTART.md? 
- [ ] Identifiquei quais skills analisarão a solicitação?
- [ ] Vou aplicar o fluxo obrigatório antes de implementar?
- [ ] Sei que nenhuma alteração deve ser feita sem aprovação?

---

**Dúvidas?** Volte para MRO_QUICKSTART.md ou CLAUDE.md.

Qualquer coisa diferente do esperado → Consulte o "Skill relevante" ↑ acima.

---
