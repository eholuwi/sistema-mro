# Prompt — Filtros rápidos da tela Saldo em Estoque

> Copie o bloco abaixo e cole na sessão do Claude do Sistema MRO. Ele ativa a skill
> `atualizar-sistema-mro`, que organiza requisitos, mapeia impacto e só implementa
> após aprovação.

---

## O que pedir (copie daqui)

Continuar o Sistema MRO (Inventus Power). Leia @docs/HANDOFF.md — a seção "STATUS
ATUAL" no topo é a autoridade sobre o que já foi feito. Siga a skill
`atualizar-sistema-mro`, feche cada etapa com `.\verify.ps1` verde e PARE para
aprovação antes de qualquer commit.

### Tarefa — atalhos de filtro na tela **Saldo em Estoque**

A tela `ui/paginas/saldo_estoque.py` usa a barra padronizada
`ui/componentes/filtros.py` (`barra_filtros`) com "pills" de filtro rápido
(`_FILTROS_RAPIDOS`) e filtros avançados (`_AVANCADOS`). Hoje existem só 3 pills:
"🔴 A comprar", "🟡 Atenção" e "Não inventariados"; o resto exige abrir "Filtros
avançados".

**Quero transformar os filtros rápidos em botões de um clique, cobrindo os casos
mais usados, sem precisar ir aos avançados.**

#### 1. Botões rápidos (pills) — manter multi-seleção combinada por AND (como hoje)

Substituir `_FILTROS_RAPIDOS` pelos seguintes botões, nesta ordem:

| Rótulo do botão | Regra de filtro |
|---|---|
| `🔴 Comprar` | `status_material` contém `"COMPRAR"` |
| `🟡 Atenção` | `status_material` contém `"ATENÇÃO"` |
| `🟢 Ok` | `status_material` contém `"OK"` |
| `Não inventariados` | sem `data_inventario` (campo vazio) — predicado já existe (`_pill_nao_inventariado`) |
| `Parada de Linha` | `importancia == "Parada de Linha"` |
| `Importante` | `importancia == "Importante"` |
| `Admin` | `importancia == "Admin"` |

Comportamento esperado (igual ao atual, só que com mais botões):
- **Multi-seleção**: pode ativar vários botões juntos; cada botão ativo **estreita**
  mais a lista (combinação por AND).
- Ex.: `🔴 Comprar` + `Não inventariados` = só itens que são para comprar **e** ainda
  não foram inventariados.
- Ex.: `Parada de Linha` + `🔴 Comprar` = só itens críticos de linha que precisam de
  compra.
- Clique de novo no botão ativo = desmarca (comportamento nativo do `st.pills`).

Regras por botão:
- Reutilizar a fábrica de predicado existente `_pill_status_contem(termo)` para os 3
  de status (não duplicar lógica).
- Criar uma fábrica análoga `_pill_importancia(valor)` para os 3 de importância:
  linha cujo `importancia` é **exatamente igual** ao valor (sem substring). Tratar
  coluna ausente e `None` como "não casa".
- Manter os rótulos em português, com os emojis dos status reais (`🔴`/`🟡`/`🟢`).
- Não inventariar nada, não mexer em banco, não alterar colunas da tabela.

#### 2. Filtros avançados — permanecem

Manter o expander "Filtros avançados" exatamente como está
(`_AVANCADOS`): multiselect de **Localização**, **Importância**, **Tipo** e
**Status**. Os valores de importância fora dos 3 botões (ex.: itens sem
classificação) continuam acessíveis pelo multiselect de Importância.

#### 3. Observações de comportamento (não é bug)

- Como cada item tem **um único** valor de importância, combinar
  `Parada de Linha` + `Importante` + `Admin` no modo AND devolve lista vazia — é o
  comportamento correto e esperado; não "consertar".
- A combinação pills + avançados continua AND (barra_filtros já encadeia assim).

#### 4. Verificação

- `.\verify.ps1` verde.
- Conferir no app real (regra inviolável nº6): abrir **Saldo em Estoque**, clicar em
  cada um dos 7 botões isolado e conferir que a lista bate com a regra; combinar
  `🔴 Comprar` + `Não inventariados`; abrir os avançados e confirmar que seguem lá.
- Se existir teste de tela/regressão para `saldo_estoque.py`, atualizar; caso
  contrário, nada de teste novo obrigatório (mudança de tela/texto).
