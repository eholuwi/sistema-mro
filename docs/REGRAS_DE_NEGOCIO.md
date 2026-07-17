# Regras de Negócio

## Estoque

- Cobertura e ruptura são calculadas com base em consumo real e lead time.
- Estoque em trânsito é tratado como saldo residual para evitar compras duplicadas.

## Requisição de Material (Requisição Digital — v4.7.0)

- **Ciclo de vida:** `Aberta` → `Parcial` → `Entregue`; `Cancelada` só a partir de `Aberta`.
- **A criação não baixa estoque.** O pedido nasce `Aberta` (na fila) e pode pedir mais do que o
  saldo atual. A **baixa acontece só na ENTREGA**, item a item, pela quantidade efetivamente
  entregue — permitindo atendimento **parcial** e **em lote**.
- **Autorização é registrada na entrega** (momento em que o material sai): exige o **autorizador
  (gestor do setor)**; se **Material SESMT** (EPI/SSO), exige também o **responsável do SESMT**.
- **Adicionar itens** a um pedido `Aberta`/`Parcial` é permitido (o caso "o solicitante volta e pede
  mais no mesmo pedido"). Após `Entregue`, abre-se uma nova requisição.
- **Consumo real** continua sendo a saída por requisição (`movimentacoes.saida` com `requisicao_id`);
  ajustes físicos não entram.

## Compras

- SCs e POs são tratados separadamente da saúde do estoque.
- Regras de reposição devem preservar a base de compras e apoiar a tomada de decisão.

## Curva ABC

- Acurácia de classe ABC deve ser derivada de dados válidos e consistentes.
- Alterações de localização sem impacto físico não devem distorcer métricas.
