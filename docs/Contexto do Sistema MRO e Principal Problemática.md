# Contexto do Sistema MRO e Principal Problemática

# Visão Geral

O Sistema MRO nasceu para resolver problemas operacionais enfrentados diariamente pela equipe do Almoxarifado MRO da Inventus Power.

Mais do que um sistema de controle de estoque, o objetivo é transformar dados operacionais em informações que permitam antecipar necessidades, melhorar o planejamento de compras e evitar rupturas de estoque.

O foco principal do projeto não é apenas informatizar processos, mas criar inteligência para tomada de decisão.

---

# Contexto Atual da Operação

Hoje o abastecimento dos materiais MRO depende diretamente do fluxo de Compras Indiretas.

Quando um material atinge um ponto de reposição, é aberta uma Solicitação de Compra (SC) através do sistema SCM.

O problema é que a falta de materiais normalmente não acontece porque o Almoxarifado deixou de solicitar o item.

Na maioria das vezes o problema ocorre porque existe um grande gargalo no processo de Compras.

---

# Estrutura Atual da Equipe

Atualmente existem apenas dois compradores responsáveis por praticamente toda a demanda de materiais indiretos da empresa.

## Davi

Responsável por:

* Manutenção
* Todas as Engenharias

A carteira da Manutenção concentra aproximadamente **300 itens por SC**, tornando-se atualmente a maior demanda da empresa.

---

## Miguel

Responsável por:

* Almoxarifado
* SSO
* Qualidade
* Diversos outros departamentos

Dentro da carteira do Miguel está todo o material improdutivo utilizado pelo Almoxarifado MRO.

Atualmente existem aproximadamente **83 itens por SC** somente relacionados ao Almoxarifado, embora nem todos sejam exclusivamente materiais MRO.

---

## Adrya (Estagiária)

Atua dando suporte para ambos os compradores.

Grande parte desse suporte é direcionado ao Miguel devido à complexidade dos materiais MRO.

---

# Complexidade das Compras MRO

Os materiais MRO possuem características diferentes dos materiais produtivos.

Cada item pode possuir regras específicas, como:

* Utilização por diversos departamentos.
* Fornecedores diferentes.
* Lead Times distintos.
* Criticidade operacional.
* Consumo variável.
* Diferentes centros de custo.

Isso faz com que praticamente cada material necessite de uma tratativa específica durante a abertura da Solicitação de Compra.

---

# Principal Gargalo Atual

Hoje o maior gargalo está entre a abertura da SC e sua efetiva compra.

Mesmo quando o Almoxarifado realiza a solicitação corretamente, o comprador precisa analisar diversas informações antes de iniciar a cotação.

Frequentemente essas informações não estão organizadas de forma padronizada.

Isso gera questionamentos como:

* Para qual setor é esse material?
* Quem utiliza?
* Qual a urgência?
* Quanto tempo esse estoque dura?
* Qual a justificativa?
* É reposição ou aumento de consumo?
* Existe material equivalente?
* Quanto comprar?

Quanto maior o tempo gasto para responder essas perguntas, maior o atraso da compra.

Consequentemente aumenta o risco de ruptura do estoque.

---

# Objetivo do Sistema MRO

O Sistema MRO pretende eliminar esse retrabalho.

A ideia é que, quando uma SC for aberta, o comprador já receba todas as informações necessárias para tomar sua decisão.

O objetivo é que ele não precise procurar dados em diversas planilhas nem retornar dúvidas ao Almoxarifado.

Idealmente, ao visualizar uma SC, o comprador deverá encontrar automaticamente informações como:

* Justificativa completa.
* Departamento(s) consumidor(es).
* Histórico de consumo.
* Quantidade recomendada.
* Tempo estimado de cobertura.
* Lead Time.
* Estoque atual.
* Estoque mínimo.
* Estoque máximo.
* Criticidade.
* Última compra.
* Último fornecedor.
* Valor histórico.
* Motivo da solicitação.

O processo deve estar "mastigado", permitindo que o comprador concentre seu tempo apenas na negociação e aquisição do material.

---

# Situação Atual da Aba Compras

Foi criada uma aba de Compras dentro do Sistema MRO.

Ela importa um relatório do SCM contendo todas as SCs relacionadas ao Almoxarifado.

Apesar de auxiliar parcialmente no recebimento dos materiais conforme as SCs existentes, ela ainda apresenta limitações importantes:

* Os dados não são totalmente confiáveis.
* Nem todas as informações estão consolidadas.
* Não existe inteligência sobre cada material.
* Ainda depende de análises manuais.

Ou seja, atualmente ela funciona apenas como um relatório operacional.

---

# Problema que o Projeto Pretende Resolver

O objetivo principal é simples:

**Nunca deixar faltar material.**

Para isso, pretende-se criar um sistema capaz de prever necessidades futuras com base em dados históricos e regras de negócio.

As metas são:

* Solicitar materiais com aproximadamente 15 dias de antecedência.
* Abrir SCs considerando um horizonte de abastecimento de aproximadamente dois meses.
* Melhorar significativamente a precisão das compras.
* Reduzir compras emergenciais.
* Reduzir rupturas.
* Melhorar a previsibilidade do estoque.

---

# Visão de Longo Prazo

No futuro, cada material deverá possuir um histórico completo dentro do Sistema MRO.

Ao acessar um único item, deverá ser possível visualizar toda sua vida útil dentro da empresa.

Exemplos de informações desejadas:

## Cadastro

* Part Number
* Descrição
* Categoria
* Tipo
* Unidade
* Criticidade

---

## Estoque

* Estoque atual
* Estoque mínimo
* Estoque máximo
* Estoque de segurança
* Quantidade disponível
* Quantidade reservada
* Quantidade em compra

---

## Consumo

* Consumo diário
* Consumo semanal
* Consumo mensal
* Consumo anual
* Tendência de consumo
* Sazonalidade

---

## Compras

* Histórico de SCs
* Histórico de POs
* Datas das compras
* Quantidades adquiridas
* Valores pagos
* Lead Time real
* Lead Time previsto
* Fornecedor mais utilizado
* Melhor fornecedor

---

## Utilização

* Quais departamentos utilizam
* Quem mais consome
* Qual setor mais consome
* Frequência de utilização
* Quantidade média por requisição

---

## Indicadores

* Giro do estoque
* Tempo médio em estoque
* Dias de cobertura
* Risco de ruptura
* Criticidade
* Valor imobilizado
* Curva ABC
* Classificação XYZ
* Frequência de compra

---

## Inteligência

O sistema deverá ser capaz de responder automaticamente perguntas como:

* Quanto tempo esse estoque ainda dura?
* Quando devo abrir uma nova SC?
* Quanto devo comprar?
* Essa quantidade cobre quantos meses?
* O consumo aumentou?
* O consumo diminuiu?
* Existe risco de ruptura?
* Existe excesso de estoque?
* Qual fornecedor costuma entregar mais rápido?
* Qual fornecedor possui melhor histórico?
* Quanto custará manter esse estoque?
* Vale a pena comprar agora?
* Existe outra SC contendo materiais semelhantes?
* É possível agrupar essa compra com outra categoria?

---

# Objetivo Final

O Sistema MRO deve evoluir de um simples controle de materiais para uma plataforma inteligente de gestão de estoque, planejamento de compras e apoio à decisão.

Toda decisão relacionada à reposição de materiais deve ser baseada em dados confiáveis e indicadores atualizados, permitindo que o Almoxarifado deixe de atuar de forma reativa e passe a atuar de forma preditiva.

O sucesso do projeto será alcançado quando a operação conseguir manter alta disponibilidade de materiais, minimizar rupturas, reduzir retrabalho entre Almoxarifado e Compras e fornecer aos compradores todas as informações necessárias para uma aquisição rápida, precisa e bem fundamentada.
