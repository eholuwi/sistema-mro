1. Pasta raiz do projeto "Sistema MRO"
c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\

Confirmado por conter ui/paginas/, services/db_functions.py, services/constants.py, services/planejamento.py, services/classificacao.py, services/scm_sync.py, além de app.py, database.py e CLAUDE.md (documentação oficial do projeto, que serve como fonte canônica).

Nota: existe uma cópia empacotada em sistema-mro\build\portatil\app\ (build de distribuição do pacote portátil), com os mesmos arquivos — não é a raiz de trabalho, é artefato gerado por scripts/portatil.py. Ignorar para fins de desenvolvimento/refatoração.

2. Páginas em ui/paginas/ — confirmadas 9, via ui/router.py (fonte única do menu)
Fonte: c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\router.py (dict ROTAS)

#	Rótulo no menu	Arquivo (path completo)
1	Dashboard	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\dashboard.py (1129 linhas)
2	Saldo em Estoque	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\saldo_estoque.py (321 linhas)
3	Ficha 360	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\ficha_360.py (457 linhas)
4	Cadastro de Itens	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\gerenciar_itens.py (409 linhas)
5	Movimentação	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\movimentacao.py (1720 linhas)
6	Controle de SC	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\controle_sc.py (1519 linhas)
7	SCM Integrado	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\scm_integrado.py (444 linhas)
8	Ajuda	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\ajuda.py (225 linhas)
9	Configurações	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\configuracoes.py (342 linhas)
ROTAS_MIGRADAS == ROTAS (todas as 9 já migradas para ui/paginas/, conforme comentário do próprio router).

3. Template_Moderno.html
Não encontrado em nenhuma subpasta de c:\Users\eholu\OneDrive\Documentos\programa (busca recursiva por **/Template_Moderno.html retornou zero resultados). Não existe no diretório de trabalho atual.

4. graphify-out/
Existe em c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\graphify-out\, com:

graph.json, graph.html, manifest.json, .graphify_labels.json, .graphify_root
GRAPH_REPORT.md
converted/ (ex.: movimentacoes_26-07-2026_598f5a24.md)
cache/ast/v0.9.27/ (grande volume de JSONs de cache AST — 267 arquivos ao todo na árvore)
Segundo o CLAUDE.md do projeto: 1947 nós, 3966 arestas, 147 comunidades, gerado por AST local (custo zero de tokens). Há também um .gitignore que exclui graphify-out/ do versionamento — está pronto para uso com o skill graphify.

Nota: há também um graphify-out/ na raiz de programa/ (fora de sistema-mro/) — não explorado em detalhe, mas é o mesmo tipo de artefato; o relevante para o Sistema MRO é o de dentro de sistema-mro/.

5. Componentes reutilizáveis em ui/componentes/
Pasta: c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\componentes\

Diferente do que a pergunta presumia, os componentes de gráfico não são arquivos separados (_barh.py, _donut.py etc.) — estão todos consolidados em um único arquivo graficos.py, como funções privadas:

Item solicitado	Status	Localização
_barh	função em graficos.py, linha 59 — def _barh(labels, values, textos, cor=None, height=300, label_outside=False)	
_donut	função em graficos.py, linha 94 — def _donut(labels, values, height=300, fmt=None)	
_barv	função em graficos.py, linha 127 — def _barv(labels, values, textos=None, cor=None, height=280)	
_linhas	função em graficos.py, linha 159 — def _linhas(x, series, height=260)	
_barras_agrupadas	função em graficos.py, linha 190 — def _barras_agrupadas(x, series, height=260, mostrar_valores=False)	
filtros.py	existe	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\componentes\filtros.py
tabela.py	existe	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\componentes\tabela.py
selecao.py	existe	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\componentes\selecao.py
status.py	existe	c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\componentes\status.py
exportar.py	existe	c:\Users\eholu\OneDrih\Documentos\programa\sistema-mro\ui\componentes\exportar.py
Arquivo consolidado de gráficos: c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\componentes\graficos.py (importado no dashboard.py como _barv, _barras_agrupadas, _bloco_top, _mes_label, _brl_compact, _MESES_PT, etc.)

Itens de conteúdo específico
db_functions.py — prévia das 4 funções
Path: c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\services\db_functions.py (arquivo grande — as funções pedidas ficam entre as linhas ~4178–4600)

calcular_giro(item_id, dias=GIRO_JANELA_DIAS, conn=None) (linha 4178) — giro anual e tempo médio em estoque; usa média de fotos diárias (estoque_snapshots) na janela, fallback para estoque atual se <2 fotos; giro_anual = (saídas no período / estoque_médio) × (365/dias).
_preco_valoracao(c, item_id) (linha 4249) — preço unitário + origem + moeda para valoração. Prioridade: preco_referencia (cache SCM) → preço mais recente de precos_historico → (0.0, None, 'BRL'). Recebe conexão já aberta (reuso em varreduras).
obter_valor_imobilizado(conn=None) (linha 4270) — Σ(estoque_atual × preço de valoração) em BRL; conta separadamente itens valorados, sem preço, e moeda≠BRL (v2.3.0).
obter_abc_valor(dias=VALOR_CONSUMIDO_JANELA_DIAS, limit=None, conn=None) (linha 4574) — curva ABC por valor consumido (qtd_saída × preço), classes A/B/C por limiares 80/95. Nota importante do docstring (v3.2.0): usa SAIDA_REAL_WHERE (consumo real por requisição) em vez de tipo='saida' cru, pois este último incluía ajustes físicos de inventário e inflava a curva.
constants.py — valores confirmados
Path: c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\services\constants.py, linhas 60-98:


ABC_LIMIAR_A = 80
ABC_LIMIAR_B = 95
VALOR_CONSUMIDO_JANELA_DIAS = 90  # janela padrão de valor consumido / ABC-valor

MOEDA_PADRAO = "BRL"
MOEDA_MAP = {
    1: "BRL",
    2: "USD",
    3: "EUR",
}
Dashboard Almoxarifado (montar_visao_almoxarifado)
Path: c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\services\dashboards.py, linha 482.

Não usa comparação "mês anterior" (MoM) como KPI — busquei mes_anterior, mês-1, comparaç etc. dentro dessa função e não há nenhuma ocorrência. O que existe é um histórico mensal em série temporal (não comparativo mês-1), montado nas linhas 605-626:


hist = [... SELECT substr(data_hora,1,7) ym, SUM(entrada), SUM(saida) ... GROUP BY ym ORDER BY ym ...]
historico_mensal = {"meses": [...], "entradas": [...], "saidas": [...]}
Isso alimenta um gráfico de linhas/série ao longo dos meses, não um card comparativo "vs. mês anterior". A visão executiva (PUBLICO_EXECUTIVO = "KPI Mensal", comentário: "apresentação mês a mês") é quem trata a granularidade mensal — mas não há lógica de delta/variação percentual mês a mês identificada nesse arquivo.

Indicador "Consumido no Ano"
UI: string exibida em ui/paginas/dashboard.py, linha 847 — ":material/shopping_cart: Consumido no ano (YTD)", dentro de _render_dash_compras_mro (aba "Compras").
Cálculo/fonte: chave kpis.valor_consumido_ytd em services/dashboards.py, linha 903, atribuída a partir da variável total_consumido (cálculo de saídas reais × preço, do ano corrente).
Drill-down: rows_consumo_ytd() (de services/drill_down.py) — a linha 225 desse arquivo tem o comentário """de Valor == 'Consumido no ano'.""".
Outras menções relacionadas: dashboard.py:957 ("Curva ABC por valor consumido (ano corrente)"), dashboard.py:1038 ("Top 10 — dinheiro dormindo (sem consumo no ano)"), ficha_360.py:242 ("consumido no ano" na Ficha 360).
Ficha 360 — recomendação automática de reposição
Path: c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\ficha_360.py, linha 120:


# ── Recomendação de reposição (read-only, reusa v2.5) ─────────────
Lógica: usa um dict rep (provavelmente vindo de services/ficha.py ou services/planejamento.py, não confirmado o produtor exato) com chaves rep["precisa"], rep["qtd_sugerida"], rep["prioridade"], rep["justificativa"]. Comportamento:

Se sem_movimentacao: mensagem info "sem consumo real; fora da lista de compra", sugere revisar no "Assistente de Reposição".
Se precisa and qtd_sugerida > 0: st.warning com prioridade e quantidade sugerida.
Se precisa mas qtd_sugerida == 0: caso especial (v2.7.1) — gatilho ativo mas saldo residual já cobre o alvo.
O motor de cálculo real (função que produz rep) provavelmente está em services/planejamento.py (não lido diretamente — recomendo abrir esse arquivo se for aprofundar na lógica de sugestão).

Gráfico "Evolução de Preço"
Dado: obter_evolucao_preco(item_id, conn=None) em c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\services\db_functions.py, linha 4318 — busca série de precos_historico (SCM+SC7) ordenada por data. Docstring explícito: "base do gráfico 'evolução de preço'".
Consumo: importado e usado em c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\services\ficha.py, linha 24 (import) e linha 277 ("evolucao_preco": obter_evolucao_preco(item_id)), ou seja, faz parte do view-model da Ficha 360.
Dashboard Movimentação
Path: c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\movimentacao.py, render() na linha 1210.

Docstring: "Movimentacao (v3.8.0+): 5 abas - Dashboard, Receber, Requisicao, Ajuste Rapido e Historico Completo."

5 abas (linha 1218-1226):


tab_dash, tab_rec, tab_req, tab_ajuste, tab_hist = st.tabs([
    ":material/bar_chart: Dashboard movimentações",
    ":material/inventory_2: Receber Material",
    ":material/assignment: Requisição",
    ":material/balance: Ajuste Rápido",
    ":material/history: Histórico Completo",
])
tab_ajuste contém "Ajuste Manual de Saldo" (lançamentos avulsos sem SC/Requisição: entradas/saídas pontuais, devoluções, perdas).

Páginas "Monitor" e "Fornecedores e Cotação"
Não existem como páginas dedicadas em ui/paginas/ nem estão registradas em ui/router.py (que só tem as 9 rotas listadas no item 2). Achados relacionados:

services/monitor_scm.py e services/monitor_cruzamento.py existem como serviços/lógica, não páginas de UI.
A funcionalidade "Monitor de SC" parece estar embutida dentro de ui/paginas/controle_sc.py (esse arquivo referencia monitor_scm/MONITOR_SC) — não é uma página separada no menu.
Nenhuma string "Fornecedores e Cotação" encontrada em lugar nenhum do código (ui/ ou services/).
Conclusão: essas seriam páginas hipotéticas/planejadas mencionadas na pergunta, mas não existem hoje como itens de menu — a funcionalidade de monitor de SC está consolidada em Controle de SC / SCM Integrado.
SCM Integrado e Controle de SC
Confirmadas como páginas separadas e distintas:

c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\controle_sc.py (1519 linhas) — rota "Controle de SC", ícone receipt.
c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\scm_integrado.py (444 linhas) — rota "SCM Integrado", ícone cloud-check, docstring do router: "consulta unificada" (F3).
Ajuda e Configurações
Confirmadas como páginas separadas:

c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\ajuda.py (225 linhas)
c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\ui\paginas\configuracoes.py (342 linhas)
Configurações NÃO usa st.tabs (busquei o padrão e não há nenhuma ocorrência de st.tabs no arquivo) — a organização interna é por seções em st.container(border=True), não abas. Seções identificadas no início do arquivo (linhas 37-90+):

:material/palette: Aparência (tema claro/escuro)
:material/backup: Backup do Banco
(continua além do que foi lido — arquivo tem 342 linhas; docstring do topo cita também "importação da base (Tipo/Mín/Máx/Lead Time)" e "gestão das Listas Mestras (centros de custo, locais, fornecedores, autorizadores, setores)" como seções adicionais).
Observação adicional relevante para a análise de refatoração
O arquivo c:\Users\eholu\OneDrive\Documentos\programa\sistema-mro\CLAUDE.md é a documentação canônica do projeto e já mapeia exatamente essa estrutura em uma tabela "Onde está cada coisa" — vale como referência primária para qualquer trabalho futuro, além de definir regras invioláveis (não duplicar lógica, não mudar regra de negócio sem teste, gate verify.ps1 obrigatório antes de considerar algo pronto). Existe também uma skill de projeto atualizar-sistema-mro (sistema-mro\.claude\skills\) que deve ser usada como fluxo de entrada para qualquer pedido de evolução/refatoração do sistema, conforme instruído pelo próprio CLAUDE.md.