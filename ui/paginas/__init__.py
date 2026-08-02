"""Páginas da UI (v5.0.0). Cada módulo expõe `def render() -> None` e é despachado
pelo router (ui.router). Importa ui/componentes|cache|formatos|tema e services/*;
nunca importa app.py.

v6.2.0 — UMA exceção ao "nem outra página": `requisitante` e `gestor` importam blocos de
`movimentacao` (`_req_bloco_identificacao`, `_req_bloco_materiais`, `_req_painel_pedidos`,
`_opcoes_setor`), que continua sendo o dono deles. A alternativa era uma segunda cópia da
tela de requisição para manter em sincronia com a do almoxarife — a regra "nunca duplicar
lógica" pesa mais aqui. O sentido é sempre esse (tela nova → Movimentação) e nunca o
inverso, então não há ciclo. Bloco que vier a ser usado por três telas sobe para
`ui/componentes/`."""
