# Estratégia de Testes

## Objetivos

- Proteger regras de negócio e cálculos críticos.
- Reduzir regressão em alterações de estoque, compras e importações.
- Garantir que a evolução do sistema não quebre fluxos existentes.

## Tipos de teste

- Testes unitários para funções e cálculos isolados.
- Testes de integração para fluxo entre banco, services e UI.
- Testes de interface para validar comportamentos visuais e interativos.
- Testes de banco para verificar schema, migração e integridade.
- Testes de performance para cenários de volume e importação.
- Testes de casos críticos para regras de ruptura, compra e recebimento.

## Estratégia

- Os testes devem cobrir cenários de estoque baixo, estoque em trânsito, lead time, ABC e importação Protheus.
- Alterações sensíveis a regras operacionais devem ter testes específicos de regressão.
- Sempre validar comportamento com dados reais quando possível.
