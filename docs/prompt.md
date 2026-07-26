1 mudança é na aba ficha 360 ao lado do card Consumo/dia adicionar um card Consumo/Mensal

2
sub-aba Guarda-Chuva Pedidos vai para controle de SC

é um controle de guarda chuva
guarda-chuva é um acordo com o fornecedor para que ele congele o preço deum produto e seja feito um pedido de compra para entregas parciais(ideal que x quantidade por mês, para não sair esse material todo no faturamento de um só mês)
fluxo ideal
Entra na aba
"Adicionar um produto"
Pesquisa por partnumber ou descrição
após isso
"Adicionar código de fornecedor"
Pronto agora kanban mostra os mesmos status, é um controle manual, não há como automatizar isso
é para sabermos quanto temos de saldo daquele material com quais fornecedores
Ao invés de card Saldo em estoque
Deve ser "Saldo total de todos os fornecedores"
Kanban continua editavel

3
Monitor de SC
A tabela tem que sempre mostrar todas as SCs não atendidas do almoxarifado, SCs com status = cotação
Tabela 
SC, Produto, Descrição, Status(Ok, Atenção, Crítico e Sem movimentação igual está na aba "Saldo em estoque"), UN, QTY Solicitada, Saldo PO, Esgotado em, Faltando(d)
Com base no cruzamento das planilhas Solicitações e Relatório de Compras

Planilha livre você move pra cima e poe o titulo "Controle Manual de Críticos"

já o modelo que estava descrevendo, vc pode por o titulo de "SCs/Itens não atendidos"


3 se pudessmos integrar conforme estavamos estudando a api, acho que melhoraria isso tudo de SC
✅ Entrevista feita, plano completo aprovado em 22/07/2026 → ver `docs/PLANO_V5_EVOLUCAO.md`
(sincronização API→banco, página SCM Integrado, refatoração faseada, distribuição). Execução ainda
não iniciada.

4. precisamos estudar mais sobre as requisicoes digitais
Fora do escopo da evolução v5.x (decisão do Luis na entrevista) — retomar depois, como trilha
separada (ver estudo em `docs/REQUISICOES_DIGITAIS_ESTUDO.md`).

Continuar o Sistema MRO (Inventus Power). Leia @docs/HANDOFF.md — a seção "STATUS ATUAL" no topo é
a autoridade sobre o que já foi feito e o que vem a seguir. Trabalhe na branch `feat/v5.0.0`
(`git pull` antes). Siga a skill `atualizar-sistema-mro`, feche cada etapa com `.\verify.ps1` verde
e PARE para aprovação antes de cada commit.