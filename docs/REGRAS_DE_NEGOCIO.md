# Regras de Negócio

## Estoque

- Cobertura e ruptura são calculadas com base em consumo real e lead time.
- Estoque em trânsito é tratado como saldo residual para evitar compras duplicadas.

## Compras

- SCs e POs são tratados separadamente da saúde do estoque.
- Regras de reposição devem preservar a base de compras e apoiar a tomada de decisão.

## Curva ABC

- Acurácia de classe ABC deve ser derivada de dados válidos e consistentes.
- Alterações de localização sem impacto físico não devem distorcer métricas.
