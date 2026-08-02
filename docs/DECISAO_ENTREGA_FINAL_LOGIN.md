# Decisão — Entrega Final: Vue.js × Login no Streamlit (portal self-service)

> `@`-referencie este arquivo na próxima sessão que retomar este assunto.
> Registro da conversa de 31/07/2026: a decisão de manter o sistema em **Streamlit**, adicionar
> **login local** e implementar o **portal self-service** com os 5 papéis, SEM depender de Kódigos/TI.
> Complementa `docs/REQUISICOES_DIGITAIS_ESTUDO.md` (fase R3) e `docs/HANDOFF.md`.

---

## 1. Contexto

- O sistema MRO é **projeto individual do Luis** — não pode pedir nada a Kódigos nem à TI.
- Roda em produção há **3 meses** (Streamlit + SQLite, servido via `C:\MRO\`, `MRO.exe` portátil).
- O Luis tratava o projeto como MVP; se fosse "entrega final", pensava em **Vue.js** para imitar a
  interface do **SCM**.
- **Fato que derrubou a premissa:** o Streamlit já em uso (**1.60.0**) tem **login nativo**
  (`st.login`). Verificado no venv do projeto. Não há custo de "inventar" autenticação.

## 2. Stack completa atual (referência)

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.12 (embeddable no servidor; venv no dev) |
| UI | Streamlit 1.60.0 + roteador próprio (`ui/router.py`) |
| Banco | SQLite (`mro.db`), schema/migração em `database.py` |
| Dados | pandas 3.0.5 |
| Gráficos | plotly 6.9.0 |
| Menu | streamlit-option-menu 0.4.0 |
| Planilhas | openpyxl 3.1.5 (import/export Excel) |
| API externa | requests 2.34.2 (integração Protheus/SCM, **somente leitura**) |
| Testes | pytest 9.1.1 + pytest-cov 7.1.0 (~638+ testes) |
| Lint/format | ruff 0.16.0 (gate via `verify.ps1` + CI) |
| Empacotamento | pyinstaller 6.21.0 (só o launcher `MRO.exe`) |

## 3. O SCM (sistema externo)

- Sistema **interno da empresa, criado por terceirizada Kódigos**, integrado com o Protheus.
- O Luis descobriu as APIs no **modo desenvolvedor** do SCM e usa **sem autorização formal** — mas
  **nada é inputado, só puxa informação** (read-only).
- Tem endpoints `/Usuario` e `/Usuario/Filter` (read-only) — candidatos a fonte de identidade, mas
  **descartados** para o login (ver §6).

## 4. Decisão tomada

**Manter em Streamlit. Não fazer reescrita Vue.**

Justificativas:
1. **A regra de negócio é o valor, não a tela.** Tudo de valor (estoque, curva ABC, cobertura,
   dashboard, sync SCM) está em `services/` + `database.py`, coberto por ~638 testes e 3 meses de
   produção. Reescrita Vue refaz só a UI e adiciona uma camada de API — o custo mais alto para a
   parte de menor valor.
2. **Todos os 5 papéis são uso interno, na rede da fábrica.** Não há requisito externo de interface.
   "Parecer com SCM" era ideia do Luis, não exigência de ninguém.
3. `st.login` existe no 1.60 — login sai barato.
4. 3 dos 5 papéis **já existem** (almoxarife faz tudo; comprador vê). O que falta são perfis + telas.

**Quando Vue passaria a fazer sentido (condição para reabrir a discussão):** se surgir requisito
externo concreto (gestão/IT exigir interface padrão SCM) ou consumidor fora do fluxo interno. Nesse
caso o caminho seria FastAPI expondo `services/` + Vue consumindo, com o Streamlit virando ferramenta
interna do almoxarife.

## 5. Os 5 papéis e o que cada um vê

| Papel | O que faz | No app |
|---|---|---|
| Almoxarife | controle de materiais (faz tudo hoje) | acesso total (admin) |
| Comprador | comprar material | views de compra (já existe hoje) |
| Requisitante | solicitar material ao almoxarife | **novo**: "Minhas requisições" + criar |
| Gestor de setor | aprovar solicitação do requisitante | **novo**: fila de aprovação do setor |
| Portaria | liberar a saída do requisitante com o material | **novo**: consulta read-only da requisição |

**Controle de acesso em duas camadas:**
1. **Rota** — o roteador (`ui/router.py`, fonte única do menu) filtra as `ROTAS` por papel. O que não
   é permitido não aparece no menu nem renderiza.
2. **Dado** — dentro das páginas, filtro por usuário/setor. Requisitante vê só os próprios pedidos
   (já testado: `test_solicitante_ve_os_proprios_pedidos_em_qualquer_status`); gestor vê só as do
   departamento dele. Dashboard, saldo, inventário, SCM integrado e Configurações ficam fora do
   alcance dos não-admins.

## 6. Usuários e login — 100% local, sem dependência externa

- **Login local no `mro.db`** (tabela `usuarios`, senha/PIN). `st.login` nativo, ou um módulo
  próprio simples (`ui/auth.py`) com formulário + `session_state` — a escolha é de implementação,
  com preferência ao caminho mais testável pelo gate.
- **Seed da tabela a partir do `solicitantes_mro`** (já existe — `database.py:412`, gerida em
  Configurações, com `nome`, `departamento`, `codigo`, `incluir_mro`):
  - cada solicitante → papel **requisitante**
  - `departamento` → vínculo do **gestor** (aprova as do setor dele)
  - almoxarife + comprador → definidos à mão (os 2 de hoje)
- **NÃO** usar `/Usuario` do SCM para login — mantém o sistema independente de Kódigos/TI.

## 7. Riscos e restrições

- **API do SCM sem contrato**: o sistema depende de uma API não formalizada (só leitura). Risco
  operacional: pode mudar sem aviso. Como é projeto individual, manter como está, mas **não criar
  novas dependências** (ex.: login) em cima dela.
- **Regra de negócio intocada**: nada muda em `services/`/`database.py` sem o gate (`verify.ps1`) e
  teste novo.
- **Migração aditiva** (regra inviolável nº4): tabela `usuarios` nova, `_backup_db` antes, migração
  idempotente e com rollback testado.
- **Regra inviolável nº6**: commit só após validação no app real + OK explícito do Luis.

## 8. Estimativa de tempo (solo, em paralelo)

| Entrega | Esforço |
|---|---|
| Login + tabela usuários + papéis | 2–3 semanas |
| Tela do requisitante (criar + minhas requisições) | parte do acima |
| Fila do gestor (aprovação por setor) | parte do acima |
| Portal da portaria (view read-only, pode ser PIN/código) | parte do acima |
| **Total da fase** | **~3–4 semanas**, gate valendo |
| Reescrita Vue só nas 3 telas novas | 4–8 semanas (e vira 2 apps p/ manter) |
| Reescrita Vue completa | 3–6 meses |

## 9. Próximos passos (retomar por aqui)

1. Confirmar o modelo de login: `st.login` (provider local/custom) vs módulo próprio `ui/auth.py`.
   Preferir o mais simples e testável — o gate exige testes.
2. Criar tabela `usuarios` (migração aditiva + backup) e seed a partir de `solicitantes_mro`.
3. Adicionar papel ao `session_state` e filtrar `ROTAS` no `ui/router.py`.
4. Implementar as telas novas (requisitante, gestor, portaria) — reusar `criar_requisicao`,
   `entregar_requisicao`, `adicionar_itens_requisicao` já existentes e testados.
5. Definir fluxo da portaria (view simples, possivelmente sem login — PIN/código da requisição).
6. Rodar `.\verify.ps1` + validação no app real + OK do Luis antes de qualquer commit.

## 10. Onde está cada coisa (referência rápida)

- Roteador/menu: `ui/router.py` (`ROTAS`, `ROTAS_MIGRADAS`, `render_pagina`)
- Login nativo disponível: `st.login` (Streamlit 1.60) — verificado no venv
- Solicitantes (seed de usuários): `solicitantes_mro` em `database.py:412`; gestão em
  `ui/paginas/configuracoes.py`
- Ciclo de vida de requisição: `services/db_functions.py` (`criar_requisicao`, `entregar_requisicao`,
  `adicionar_itens_requisicao`, `_calcular_status_requisicao`)
- Testes de escopo por solicitante: `tests/test_v570_fila_duas_visoes.py`
- Estudo com as fases R1/R2/R3: `docs/REQUISICOES_DIGITAIS_ESTUDO.md`
