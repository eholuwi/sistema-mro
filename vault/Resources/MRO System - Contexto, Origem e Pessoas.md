---
created: 2026-07-09
status: active
tags:
  - mro-system
  - contexto
  - origem
  - pessoas
related:
  - [[MRO System - Visão Geral]]
  - [[MRO System - Histórico de Versões]]
  - [[Apresentação Inventus Power - KPI Mensal]]
---

# MRO System — Contexto, Origem e Pessoas

Registro consolidado da trajetória de Luis na Inventus Power e de como o MRO System nasceu, evoluiu e por que existe. Complementa [[MRO System - Visão Geral]] (o quê/como técnico) com o porquê e o quem — útil como material de apoio para a apresentação (ver [[Apresentação Inventus Power - KPI Mensal]]) e para qualquer sessão futura que precise de contexto humano/organizacional por trás das decisões do sistema.

## Sobre Luis

Luis Gabriel Arruda de Oliveira, estudante de Engenharia de Software, iniciou a trajetória na Inventus Power como **Estagiário de Materiais**, atuando diretamente no Almoxarifado. Desde o início buscou entender não só a execução das atividades, mas os processos, gargalos e oportunidades de melhoria por trás delas — interesse constante em tecnologia, automação, análise de dados e melhoria contínua.

## A jornada na Inventus

### Início no Almoxarifado

Atuação inicial no setor de Materiais: controle de estoque, recebimento, separação, atendimento a requisições, organização do estoque, apoio ao inventário. Problemas operacionais observados nesse período:

- Muitos controles em planilhas.
- Falta de indicadores.
- Pouca rastreabilidade.
- Informações descentralizadas.
- Dependência de conhecimento individual.
- Muito trabalho manual.

Foi observando esses problemas que surgiu a ideia de criar um sistema próprio.

### Nascimento do MRO System

Objetivo inicial: uma ferramenta para controlar melhor o estoque MRO. Com o tempo, ficou claro que o problema era maior que estoque — processos espalhados entre Almoxarifado, Compras, Engenharia, Planejamento, SCM, Protheus e planilhas Excel. O projeto deixou de ser um controle de estoque e passou a ser uma plataforma de gestão operacional.

### Mudança para Compras

Luis foi emprestado para o setor de Compras, trabalhando diretamente com Solicitações de Compra (SC), cotações, equalização, fornecedores, Pedidos de Compra (PO) e acompanhamento de entregas. Isso ampliou a visão de todo o fluxo:

`Necessidade → Solicitação → Cotação → Pedido → Recebimento → Estoque → Consumo`

Essa mudança redirecionou completamente o projeto.

### Evolução da ideia

Hoje o MRO System não é mais um sistema de Almoxarifado — é uma plataforma que centraliza estoque, materiais, compras, inventário, requisições, indicadores, dashboards e inteligência operacional.

## Objetivo e filosofia do projeto

Transformar processos manuais em processos organizados, rastreáveis e baseados em dados — **sem** substituir as pessoas. O sistema ajuda as pessoas a tomarem decisões melhores; a decisão final permanece sempre com o usuário.

> Organizar informações, consolidar dados, gerar indicadores e fornecer recomendações inteligentes para apoiar a tomada de decisão.

Este princípio já está formalizado em [[MRO System - Visão Geral]] como "assistente, não piloto automático".

## Pessoas que influenciaram o projeto

### Neidson — Supervisor de Compras

Revisou e validou dados que passaram a ser a **referência oficial** do sistema: Categoria, Tipo, Mínimo, Máximo, Lead Time. É a mesma base de referência mencionada em [[MRO System - Visão Geral]] — nunca sobrescrita por cálculo automático, só sugerida ao lado ("calculado X · cadastrado Y").

### Sullyvan — Gestor de Materiais

Contribuiu na definição operacional de estoque mínimo, estoque máximo e estoque de segurança. Ajudou a simplificar regras importantes do sistema.

### Miguel — Comprador

Trouxe o entendimento do fluxo real de Compras. Conceitos usados por ele hoje fazem parte do sistema: Guarda-Chuva, Follow-up, Acompanhamento de SC, Planilha Relatório de SCs.

### Davi — Comprador (diversas carteiras)

Sua rotina ajudou a compreender melhor o acompanhamento das Solicitações de Compra.

### Juan — Assistente de Materiais

Organiza manualmente materiais críticos com base no MRO System. Essa atividade inspirou uma funcionalidade futura: o sistema identificar materiais críticos e **sugerir** criação de SC agrupando por Tipo, com CC, Descrição e Justificativa sugeridos — SCs com antecedência, sempre como recomendação.

## Funcionalidades que nasceram dessas conversas

### Controle de inventário

Cadastro de materiais, movimentações, histórico, Curva ABC.

### Requisições (hoje em papel)

Objetivo futuro: digitalizar completamente. Cada colaborador com perfil próprio associado a Centro de Custo e departamento, histórico de requisições, acompanhamento de status. O Almoxarife com tela própria de atendimento.

### Sugestão de criação de SC

Em vez de abrir SCs item por item, o sistema sugere o quê comprar, quando, como agrupar, justificativa, categoria e prioridade — **sempre como recomendação, nunca criando SC automaticamente**. Ligado diretamente ao caso de uso do Juan acima.

### Ficha 360 do Material

Tela única com cadastro, estoque, consumo, histórico, compras, fornecedores, lead time, indicadores, gráficos e imagem — já implementada, ver [[MRO System - Visão Geral]].

### Inteligência dos materiais

Melhorar a precisão de consumo, lead time, giro, dias de cobertura, estoque mínimo/máximo/segurança, tendência e classificação XYZ — sempre com dados reais. Parte disso já está em produção via classificação SBC (ver [[MRO System - Visão Geral]]).

## Arquitetura e forma de trabalhar

Preocupação constante com boas práticas: planejamento antes da implementação, versionamento, banco de dados consistente, auditoria, histórico de alterações, escalabilidade. Nenhuma alteração importante é feita sem passar por planejamento antes.

## Time de especialistas (Skills)

Conjunto de especialistas virtuais consultados antes de toda evolução relevante do sistema: Product Owner, Supply Chain Specialist, Database Engineer, Backend Engineer, Data Engineer, UX/UI Designer, QA Engineer, Software Architect, DevOps Engineer. Framework aplicado automaticamente — ver seção "MRO Skills Framework" no `CLAUDE.md` da raiz do repositório.

## Visão do produto

Pilares: organização, rastreabilidade, precisão dos dados, inteligência operacional, apoio à decisão, facilidade de uso, escalabilidade.

## Objetivo profissional

Além de resolver problemas reais da operação, o MRO System representa a evolução profissional de Luis dentro da Inventus Power: capacidade de entender processos, desenvolver soluções, integrar tecnologia ao negócio, e trabalhar com Supply Chain, Compras e Engenharia de Software. A expectativa é que o projeto gere valor suficiente para apoiar a efetivação e a migração das atividades predominantemente operacionais do Almoxarifado para uma função mais estratégica, voltada à tecnologia, melhoria de processos e Supply Chain.

## Visão de longo prazo

Não é criar apenas um software — é construir uma plataforma que concentre o conhecimento operacional de Materiais e Compras, transformando dados dispersos em informações úteis para toda a empresa. No futuro: centralizar informações de materiais, digitalizar processos operacionais, melhorar o planejamento de compras, apoiar compradores e gestores, reduzir atividades manuais, aumentar rastreabilidade, fornecer indicadores confiáveis para decisão, e servir como plataforma de melhoria contínua para os processos internos da Inventus Power.

Em resumo: o MRO System deixou de ser um projeto de controle de estoque feito por um estagiário e passou a representar uma iniciativa de transformação operacional baseada em tecnologia, engenharia de software e conhecimento de Supply Chain.
