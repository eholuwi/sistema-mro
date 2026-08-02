📊 Levantamento Concluído: v6.1.0 Usuários e Login Local
Objetivo: Realizar levantamento da arquitetura do projeto MRO para implementação de fundação de login local sem análise profunda nem modificação de código.

Status: ✅ Concluído com Sucesso

📄 Documentos Gerados
Criei 4 documentos completos na pasta scratchpad:

RESUMO_LEVANTAMENTO.md (5-10 min de leitura)

Visão executiva: objetivo, arquitetura, escopo, impactos, riscos, próximos passos
Ideal para stakeholders e decisores
LEVANTAMENTO_V610_USUARIOS_LOGIN.md (20-30 min de leitura)

Mapeamento técnico: estrutura, schema, módulos, dependências, prototipagem
Ideal para implementadores e arquitetos
ARQUITETURA_V610.md (15-20 min de leitura)

Fluxos visuais: inicialização, login, banco, papéis, menu, seed, configuração
Diagramas ASCII, matriz de validação, grafo de imports, checklist
Ideal para implementadores e revisores
INDICE_LEVANTAMENTO.md (navegação)

Índice de tópicos, referência cruzada, FAQ, checklist de leitura por papel
Guia de como usar os 3 documentos anteriores
🎯 Principais Descobertas
Arquitetura
Stack: Streamlit 1.57+ + SQLite (WAL) + Python 3.10+
Padrão: UI → services → database (regra inviolável)
Projeto: 7 rotas migradas, ~13 tabelas, 50+ testes por versão, grafo de 1947 nós
Pontos de Integração (10 arquivos)
Arquivo	Tipo	Tamanho	O Quê
database.py	Edit	+30L	CREATE TABLE usuarios
services/usuarios.py	Create	350L	Novo domínio auth
ui/auth.py	Create	250L	Sessão + login
ui/router.py	Edit	+15L	ROTAS_POR_PAPEL
ui/sidebar.py	Edit	+30L	Menu filtrado
ui/paginas/configuracoes.py	Edit	+150L	7ª aba
app.py	Edit	+5L	Gate + seed
services/constants.py	Edit	+3L	Versão bump
tests/test_v610_usuarios.py	Create	400L	12 testes
Docs	Create	60L	Changelog + HANDOFF
Total: ~1.300 linhas novas + ~250 de edição

Decisões Arquiteturais Travadas
✅ Login 100% local (sem authlib, sem OIDC) — stdlib apenas
✅ Flag exigir_login padrão DESLIGADO → backward-compatible
✅ services/usuarios.py módulo separado → autenticação é novo domínio
✅ Seed idempotente + respeita edições manuais
✅ Papéis futuros prontos (requisitante, gestor, portaria) sem telas ainda
✅ Guarda: último almoxarife nunca morre (operação recusada)
Banco de Dados
Nova tabela: usuarios (10 colunas)
Índices: nome_norm, ident_norm, papel
Seed: ~250 requisitantes + 5 manuais (idempotente)
Compatibilidade: ✅ Aditiva, zero risco para dados existentes
UI/UX
Menu: agora 5-7 rotas (antes sempre 7) → versátil
Sidebar: perfil dinâmico (deslogado → "Luis" | logado → nome real)
Configurações: +1 aba (6 → 7)
Login: tela aparece só com flag ON
Performance
Gate check: O(1) + 1 SELECT (negligenciável)
Autenticação: PBKDF2 200k iterações ≈ 100-150ms (aceitável)
Menu: derivado de session_state, sem queries críticas
✅ Pré-requisitos Verificados
 Graphify: Grafo construído (1947 nós, 3966 arestas, 147 comunidades)
 CLAUDE.md: Lido (arquitetura, regras, fluxo)
 Plano v6.1.0: Aprovado pelo Luis (PLANO_V610_USUARIOS_LOGIN.md)
 Banco: Mapeado (schema completo, padrões)
 Router: Entendido (7 rotas migradas, estrutura)
 Dependências: Verificadas (stdlib + Streamlit, nada novo)
 Gate: Confirmado (verify.ps1 exit 0 obrigatório)
🚀 Próximos Passos (Aguardando OK de Luis)
Fase 1: Implementação (ordem fixada)

database.py — CREATE TABLE usuarios
services/usuarios.py — domínio (~350L)
tests/test_v610_usuarios.py — testes (12 casos)
ui/auth.py — sessão + login (~250L)
ui/router.py — ROTAS_POR_PAPEL
ui/sidebar.py — menu + perfil
ui/paginas/configuracoes.py — aba usuários
app.py — semear + gate
Documentação (version bump + changelog + HANDOFF)
.\verify.ps1 → exit 0
Validação real no app com Luis
Commit (com OK do Luis)
Fase 2: Validação com Luis (obrigatória)

 Flag OFF → app v6.0.0 intacto
 Ligar flag → login aparece
 Definir PIN → logar como almoxarife
 Logar como comprador → menu 5 rotas
 PIN errado → recusa genérica
 Desligar flag → app normal
📚 Referências Rápidas
Consultas graphify (zero cost):


graphify query "Como o seed cria usuários"
graphify path "app.py" "usuarios.py"
graphify explain "semear_usuarios"
Documentos do projeto:

PLANO_V610_USUARIOS_LOGIN.md — especificação (entrega)
CLAUDE.md — arquitetura geral + regras
docs/DECISAO_ENTREGA_FINAL_LOGIN.md — decisões de produto
📝 Resumo
O Sistema MRO tem arquitetura sólida e modular. A integração de login local (v6.1.0) é mapeada com precisão: 10 arquivos, ~1.550 linhas, zero quebras de compatibilidade. Domínio testado antes da UI, papéis prototipados para fases futuras, banco aditivo.

Levantamento pronto para implementação. Aguardando OK do Luis para iniciar.

Todos os documentos estão em C:\Users\eholu\AppData\Local\Temp\claude\...\scratchpad\ (4 arquivos .md).