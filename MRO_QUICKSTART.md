# 🎯 MRO Skills Framework — Guia de Inicialização Rápida

**Bem-vindo ao Sistema MRO! Este é um projeto real com impacto operacional direto.**

## O Que Fazer Quando Receber Uma Solicitação

Toda solicitação deve passar por um fluxo obrigatório antes da implementação:

### 1️⃣ **ENTENDER O PROBLEMA**
- O que o usuário está pedindo?
- Por que está pedindo agora?
- Qual é o impacto se não fizermos?

### 2️⃣ **IDENTIFICAR IMPACTOS**
- **Técnico**: Qual arquivo/sistema muda?
- **Operacional**: Como muda o fluxo do almoxarife/comprador/gestor?
- **Risco**: O que pode dar errado?

### 3️⃣ **CADA SKILL APRESENTA SUA ANÁLISE** ⭐ CRÍTICO

Leia CLAUDE.md e aplique o framework dos 9 especialistas:

| # | Skill | Valida | Checklist |
|---|-------|--------|-----------|
| 1 | **Product Owner** | Backlog, MVP, User Story, Critério de Aceite | [ ] |
| 2 | **Supply Chain** | Regras, Cálculos, Protheus, Operação real | [ ] |
| 3 | **Database** | Migrações, Schema, Rollback, Integridade | [ ] |
| 4 | **Backend** | Algoritmo, API, Testes Unitários, Performance | [ ] |
| 5 | **Data** | ETL, Validação, Qualidade, Rastreabilidade | [ ] |
| 6 | **UX/UI** | Interface, Usabilidade, Português, Labels | [ ] |
| 7 | **QA** | Testes, Regressão, Dados Reais, Critérios | [ ] |
| 8 | **Architect** | Arquitetura, SOLID, Acoplamento, Débito | [ ] |
| 9 | **DevOps** | Deploy, SemVer, Backup, Rollback, Logs | [ ] |

### 4️⃣ **CONSOLIDAR ANÁLISES**
- Qual skill tem achados críticos?
- Existem conflitos entre as análises?
- Qual é o risco real?

### 5️⃣ **APROVAR OU REJEITAR**
- ✅ Se ALL skills aprovaram → prosseguir para implementação
- ❌ Se alguma skill sinalizou risco crítico → retornar para refinamento

### 6️⃣ **IMPLEMENTAR**
- Seguir exatamente o que foi aprovado
- Respeitar padrões definidos (SOLID, Clean Architecture)
- Não adicionar escopo sem re-aprovação

### 7️⃣ **VALIDAR**
- Testes passam?
- QA testou com dados reais?
- Regressões?
- Pronto para deploy

---

## Exemplos de Solicitações e Como Aplicar as Skills

### 📋 Exemplo 1: "Quero adicionar cálculo de ruptura em tempo real"

**Step 1 - Entender**
- Usuário quer saber quando vai faltar material antes de acontecer

**Step 2 - Impactos**
- Técnico: Nova coluna em SB2, novo endpoint na API
- Operacional: Almoxarife vê alerta de ruptura prevista
- Risco: Cálculo incorreto = pede material que não precisa

**Step 3 - Skills**
- **Supply Chain**: "Como calcular ruptura? Qual fórmula? Dados estão disponíveis no Protheus?" → Define algoritmo
- **Database**: "Precisa migração? SB2 tem campo novo?" → Planeja migração com rollback
- **Backend**: "Implementa serviço de cálculo de ruptura" → Testes unitários com dados reais
- **QA**: "Testa com 100k materiais do almoxarifado real" → Valida resultado
- **UX/UI**: "Como mostrar o alerta?" → Prototipa interface com usuário

**Step 4-5 - Consolidar e Aprovar**
- Supply Chain aprova fórmula
- Database aprova migração
- QA aprova testes com dados reais
- ✅ **Implementar**

---

### 🗂️ Exemplo 2: "Quero exportar relatório de Min/Max para Excel"

**Step 1-2**
- Usuário quer validar cálculos de mínimo/máximo
- Impacto: Nova tela + nova rota + geração de arquivo Excel

**Step 3 - Skills**
- **Product Owner**: "Esse relatório é MVP ou fase 2?" → Define prioridade
- **Supply Chain**: "Quais colunas? Em qual order? Agrupa por quê?" → Define estrutura
- **UX/UI**: "Como apresentar? Filtros? Formato?" → Desenha interface
- **Backend**: "Implementa geração de Excel" → Query otimizada
- **QA**: "Testa com 50k materiais, verifica ordenação e filtros"

**Step 4-5 - Consolidar e Aprovar**
- Se Supply Chain aprovar as colunas e orden
- Se QA validar com dados reais
- ✅ **Implementar**

---

## 🚨 Situações Críticas Que Bloqueiam Implementação

❌ **Não implementar se:**

1. **Supply Chain Specialist não validou** a regra de negócio
2. **Database Engineer não validou** migração com rollback testado
3. **Cálculos não têm testes** com dados reais do almoxarifado
4. **Não existe User Story** com critério de aceite
5. **Interface não foi validada** com usuário real
6. **QA não executou testes** de regressão
7. **DevOps não planejou** backup e rollback
8. **Código viola SOLID** sem justificativa documentada

---

## 📚 Onde Encontrar Informações

- **Detalhes de cada skill**: Leia CLAUDE.md neste repositório
- **Framework completo**: Memory project_mro_skills_framework.md
- **Settings do projeto**: .claude/settings.json
- **Graphify (mapa de código)**: graphify-out/graph.json
- **Vault Obsidian**: ault/ (Daily Notes, Projects, Sessions)

---

## ✅ Checklist Antes de Commitar

- [ ] Todas as skills relevantes analisaram
- [ ] Cada skill deu sua aprovação explícita
- [ ] Código segue SOLID e padrões definidos
- [ ] Testes unitários passando (100% cobertura em lógica crítica)
- [ ] QA testou com dados reais
- [ ] Zero regressões detectadas
- [ ] Migração tem rollback documentado e testado (se houver)
- [ ] Deploy tem backup planejado (se houver)
- [ ] Changelog atualizado (SemVer)
- [ ] Documentation atualizada

---

## 🆘 Precisa de Ajuda?

1. **Qual skill devo consultar?**
   - Regra de negócio/cálculo → Supply Chain Specialist
   - Banco de dados → Database Engineer
   - Algoritmo/código Python → Backend Engineer
   - Integração Protheus → Supply Chain + Database
   - Testes → QA Engineer
   - Interface → UX/UI Designer
   - Arquitetura → Software Architect
   - Deploy → DevOps Engineer

2. **Posso pular a análise de uma skill?**
   - ❌ NÃO. O fluxo é obrigatório para TODA solicitação.

3. **E se uma skill disser "não"?**
   - Volte para a etapa de refinamento (Step 4).
   - Ajuste a solicitação conforme feedback.
   - Retorne para aprovação.

---

**Boa sorte! 🚀**

Sistema MRO — Manufatura, Compras, Almoxarifado, Integração Protheus
