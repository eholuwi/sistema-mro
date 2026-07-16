1. Estou focando em "explicar" o sistema, de forma que qualquer um, seja da diretoria, comprador, almoxarife novo, etc. Bata o olho no sistema e saiba o que signfica cada coisa, se não, que todos os dados tenham o "?" Help, explicando o que é, pra que serve e como foi feito. 


2. Outra coisa que ajudaria na acuracidade é que todos os dados de dashboard fossem clicaveis, Exemplo: Clico em "Itens Cadastrados" e abre uma tabela que cada linha é o material. Clico em "Entradas hoje" e ele mostra uma tabela em que cada linha é um recebimento. E que assim seja pra todos os dados inclusive os dashboards, onde clico na coluna e mostra uma tabela. Tenho exemplo disso em um @Dashboard SCM WK29 que gero para os compradores toda semana, pode estudar para ver como é.

3.Gostei do Dashboard Compras MRO · Inventus Power
Mas alinhando com o comprador Miguel faz mais sentido apenas replicar o @Dashboard SCM na aba do Comprador do Dashboard do SISTEMA MRO, porém o diferencial é claro, que os dados serão apenas do material de MRO e não de compras completo
Dados que gostaria de manter: Gráfico de Fornecedor por valor, exatamente como ele está hoje no SISTEMA MRO, Gráfico de 📦 Setores (demanda em aberto) Só faria ajuste nos números pois estão deitados e pequenos dentro da coluna

4. Aba Gestão vai parar de existir, vai somente alguns dados que achei interessante para a Aba Almoxarifado
Dados que quero manter e vão para a aba Almoxarifado:
Itens Ok, Atenção, Críticos, Sem movimentação, Zerados, Inventariado, estão ótimos do jeito que estão atualmente e sim é interessante deixar 2 linhas a primeira linha sendo esses dados que acabei de mencionar Itens Ok, Atenção, Críticos, Sem movimentação, Zerados, 
E a segunda linha sendo Itens Ok, Atenção, Críticos, Zerados, porém que fique claro que é contando todo material mesmo que o material não tenha movimentação
 Top 10 Consumidores (mês anterior)
Muda só nome para Top 10 Itens com mais consumo no mês anterior. Padrões de demanda só precisa de mais explicação no gráfico, pode ser o número dentro da coluna do gráfico. Requisições por Setor &  Top Emitentes tá perfeito pode passar pro dashboard Almoxarifado. 
Resumindo, Aba Gestão para de existir, tudo que mencionei acima permanece porém de forma organizada com o que existe hoje na aba Almoxarifado

5.Aba Almoxarifado, tira o card "Estoque Baixo"
Gráfico de "Distribuição" melhor que fique "Distribuição de Itens por Status"
Gráfico de Cobertua Dias, falta dizer no parâmetro x que são dias, "<7 dias", "8-15 dias" e o restante...
Gráfico  Curva ABC (valor) Precisa dizer a quantidade também, não só porcentagem
Container de Entradas, o Hoje precisa mostrar a data de hoje, semana precisa mostrar em qual semana estamos, ou Inicio x Fim, que explique isso no help, Mês mostra o mês em que estamos ou data Inicio X Fim. Container de Saídas fazer a mesma tratativa
Gráficos 📥 Top materiais recebidos (mês), 📤 Materiais mais consumidos (mês) e 🏭 Setores que mais retiram estão ok
📈 Histórico mensal — Entradas × Saídas
Precisa de algo mais informativo visualmente, só está sendo mostrado 2 blocão vermelho 1 de entrada e outro de saída mas tem que colocar o mouse encima pra ver a quantidade

6. Página Saldo em estoque
Pode tirar esse "42 item(ns) comprado(s) em unidade diferente da de estoque e ainda sem fator de conversão. Revise em Gerenciar Itens → Conversão de unidades — até lá o recebimento pode somar quantidade crua."
Retire as colunas Un? e XYZ
Coluna Demanda altere o nome pra Tipo de Demanda
Dias de Ruptura ao invés de contar quanto dias vai durar, muda o nome da coluna para "Acaba em", eai mostrará a data em que aquele material está estimado para acabar
Do lado de localidade pode coloca a segunda locação do material que acredito que agora exista sem conflitos
Em Realizar Contagem Física
Local (2ª Locação) quando não tem locação, ou usuário quer deixar vazio, ao invés de um travessão, pode ser nada mesmo " "

Exportar excel precisa ser mais explativo "Exportar todos os itens para planilha Excel"
Retire a coluna "Segurança" ao gerar o excel

7. Página Ficha 350 Material
Debaixo do nome "PN - Descrição do material"
Categoria/Tipo: Expediente
Unidade: RM · Criticidade: Parada de Linha
Setor responsável: Improdutivo
Local: SUPERMERCADO · Caixa AJUSTE DE INVENTÁRIO

Setor responsável não faz sentido ter isso, seria melhor colocar "Setor que mais consome"
Local precisa atualizar já que agora existem 2 locações do material

Pode retirar essa mensgaem "Revisar unidade: comprado em unidade diferente da de estoque (visto nos POs) e ainda sem fator de conversão. Cadastre em Gerenciar Itens → Conversão de unidades para o recebimento converter certo."

Card "Mínimo" e "Máximo" fica Quantidade Minima e Quantidade Maxima.
Adicionar Help com "Baseado no reajuste de compras"

Pode retirar o Botão "Ver detalhes de Saldo Item(PO)"

Cobertura muda o titulo para "Dias até acabar", melhore o Help

Consumo dia melhora o help apenas

Poe o gráfico de consumo médio/dia por janela em um container por favor e deixe mais explicativo

Poe "Valor" em um container e também deixe mais explicativo

Dentro de ficha material vou precisar que tenha uma segunda aba chamada Guarda-Chuva
Funcionará dessa forma
Seleciona o material PN ou nome
Pede pra incluir o código do fornecedor
Então os dados dos pedidos daqueles itens são puxados'
Mostra um kanban
Número P.O/Data P.O -> Data/Entrega -> Nota Fiscal -> Quantidade/ Quantidade Entregue

Saldo total do material

8. Pagina Gerenciar Itens
Editar Unidades
Revisar unidade: este item é comprado numa unidade diferente da de estoque (visto nos POs), mas ainda sem fator de conversão (fator = 1). Defina a unidade de compra e o fator abaixo para que o recebimento converta corretamente.

Apenas retire "mas ainda sem fator de conversão (fator = 1). "
Descrição / Observação deixe somente Observação

Em Cadastrar Novo Item

Descrição muda para Observação
Lead time padrão está 7, muda pra 20

9. Movimentação
Aba Analytics muda para Dashboard movimentações
Não parece que faz sentido essa explicação " Indicadores de série (consumo, tendência, giro) baseados em 88 dias de histórico — desde 16/04/2026 · 2888 fotos de estoque. A confiança aumenta conforme os dados acumulam."
Esse titulo " Inteligência de Estoque (Cobertura · Tendência · Giro)
" Poderia ser somente  Tendência de consumo
os cards, em alta, em queda e estavel, precisam ser mais explicativos
"Em alta" é o que? Itens em alta? Itens com consumo aumentando?
Itens com consumo em alta em comparação com mês passado? que aplique a solução nos outros 2 cards

Na tabela  Top capital parado (maior valor em estoque, giro 0)
Preciso só que adicione a coluna "UN"

Na aba Receber Material
Selecionando Por SC/PO o select mostra "--Selecione a SC / PO--"
Deveria ficar vazio para selecionar

Na aba Requisição, subpágina  Histórico de Requisições
Em  Buscar (Nº, emitente ou autorizador) quero que seja possivel pesquisar por material/pn também

Detalhes da Requisição
Poderia ser mais completo e poderia ficar antes da tabela das requisições

Na aba Ajuste rápido poderiamos melhorar a forma que está sendo registrado Tipo de Ajuste
Entrada (Sobra)
Saída (Perda/Ajuste)
Poderia ser
-Entrada Avulsa
-Devolução
-Perda de Material
-Saída Avulsa
(Isso vai melhorar o  Histórico de Movimentações ao filtrar por tipo) tem como filtrar por entrada, saida, devolução, mas agora com o ajuste será possivel filtrar por Entrada Avulsa, Devolução, Perda de Material, Saída Avulsa

em Quantidade é quantidade a ser adicionada caso entrada avulsa ou devolução e Quantidade a ser subtraida caso Perda ou Saída Avulsa

Não precisa de Centro de custo, pode tirar

Histórico de Movimentações
Baixar Excel muda para Baixar planilha excel completo de todas as movimentações

10. Controle de SC
Aba Monitor de SC
Quero que a tabela que existe hoje na verdade seja completamente editavel sem limite de linhas e colunas podendo editar da forma que quiser, a planilha irá 
ser colada nessa tabela todos os dias independente da quantidade de linhas e colunas

SCs sugeridas
Apenas me confirme que essas SCs mudam conforme o estoque e outros fatores...

Atualizar Status e Dados da S.C.
Select está "--Selecione a SC--"
Deveria ficar vazio para selecionar


Agora tenho a logo da inventus em @inventus_logo
Pode jogar a versão do sistema pro final da barra de navegação



