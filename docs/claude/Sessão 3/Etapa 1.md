 1 ✓ Mapa V6.2.0 Gerado
Arquivo: MAPA_V620_PONTOS_TOQUE.md (scratchpad)

Conteúdo: mapeamento arquivo:linha → símbolo de todos os pontos de toque solicitados:

Categoria	Arquivo	Linhas	Funções
Migração	database.py	43, 884, 985	transaction, _migrar, _backup_db
Requisições	db_functions.py	248, 1262, 1423, 1648, 1663, 1687, 1732	7 funções (criar/cancelar/listar/setores)
Autenticação	auth.py + usuarios.py	55, 96, 18, 23, 29, 312	render_login, gate, usuario_logado, exigir_login
Roteamento	router.py	38, 49, 60, 71, 84, 89	ROTAS, ROTAS_POR_PAPEL, opcoes_menu, render_pagina
UI	sidebar.py + cache.py	38, 64, 104	_render_perfil, render_sidebar, invalidar_leituras
Movimentação	movimentacao.py	24–48	imports + uso de requisições
Assinaturas exatas: incluídas com tipos de retorno onde aplicável.

3 funções novas esperadas v6.2.0: aprovar_requisicao, buscar_requisicao_por_numero, listar_requisicoes_por_setor.

Checklist de 10 itens para guiar implementação após aprovação do plano.

Nenhuma análise ou modificação de código foi feita — apenas extração de localização e símbolo.
