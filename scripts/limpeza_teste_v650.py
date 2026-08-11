"""Limpeza dos dados de teste/junk do banco (Task 3, v6.5.0).

Uso (a partir da pasta `sistema-mro`):

    venv\\Scripts\\python.exe scripts\\limpeza_teste_v650.py            # SIMULAÇÃO
    venv\\Scripts\\python.exe scripts\\limpeza_teste_v650.py --aplicar  # grava de verdade

**Simulação é o padrão.** Sem `--aplicar` nada é gravado: o script reaudita o banco (as mesmas
queries da seção B do relatório) e mostra o que faria. Com `--aplicar`, o banco é copiado para
`backups/` (via `database._backup_db`) ANTES da primeira escrita, e tudo é apagado numa única
transação atômica.

Relatório de auditoria aprovado pelo Luis em 11/08/2026 — seção B de
`docs/claude/Sessão 4/Plano Gerado Etapa 0.md`, detalhado em
`docs/claude/Sessão 4/Etapa 4 - Task 3 Limpeza do Banco.md`. Este script REAUDITA o banco a cada
execução e só aplica se os ids encontrados baterem com `APROVADO` abaixo; se divergirem
(banco diferente, ou dados novos que também batem no critério), para sem apagar nada e pede
reaprovação — use `--forcar` só depois de revisar e reaprovar.

O que é apagado (critério == aprovado):
  1. Requisições com setor OU emitente == 'TESTE'/'TEST' (igualdade exata, upper/trim) — e o
     que elas arrastam: itens_requisicao (FK com CASCADE) e movimentações ligadas por
     requisicao_id (FK SEM CASCADE — por isso são apagadas ANTES das requisições).
  2. Guarda-chuva de teste: fornecedor 'Miguel do papel' / 'Miguel das luva'.
  3. Lista setor='TESTE': DESATIVADA (ativo=0, mesma lógica de
     `services.db_functions.remover_valor_lista`), NÃO apagada — as 9 requisições a usaram e o
     histórico referencia por texto.
  4. Movimentação #231 ("Ajuste — Teste", ajuste manual sem requisição) — decisão pontual do
     Luis (11/08/2026), não é um critério genérico de busca; por isso o id é literal.

NUNCA apagado (não é junk): saídas por requisição real, recebimentos de SC, contagem física
(CC INVENTÁRIO), saldos, cadastro (inventario/fornecedores/solicitantes_mro/usuarios/
solicitacoes_compra), as requisições reais de "ENG TESTE" (Engenharia de Teste — setor real,
filtrado por IGUALDADE, nunca por `LIKE '%TEST%'`, que as pegaria por engano), e as
movimentações #661/#662 (ajustes físicos reais que só citam "Test..." na observação).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

import database  # noqa: E402

# Aprovado pelo Luis em 11/08/2026 — não é um critério de busca, é uma exceção pontual (ver
# docstring do módulo, item 4).
MOV_ID_AJUSTE_TESTE_AVULSO = 231

REQUISICOES_TESTE_SQL = """
    SELECT id, numero_requisicao, data_hora, setor, emitente, status
      FROM requisicoes
     WHERE UPPER(TRIM(COALESCE(setor,''))) IN ('TESTE','TEST')
        OR UPPER(TRIM(COALESCE(emitente,''))) IN ('TESTE','TEST')
     ORDER BY id
"""

GUARDA_CHUVA_TESTE_SQL = """
    SELECT id, fornecedor_nome, item_id
      FROM guarda_chuva
     WHERE fornecedor_nome IN ('Miguel do papel', 'Miguel das luva')
     ORDER BY id
"""

APROVADO = {
    "requisicoes": [4, 5, 6, 43, 81, 82, 83, 128, 1095],
    "movimentacoes_cascata": [4, 5, 6, 76, 137, 138, 139, 230],
    "guarda_chuva": [1, 2],
}

TABELAS_CONTAGEM = ("requisicoes", "movimentacoes", "itens_requisicao", "guarda_chuva")


def _auditar(conn):
    """Reaudita o banco com os mesmos critérios do relatório aprovado. Só lê."""
    reqs = conn.execute(REQUISICOES_TESTE_SQL).fetchall()
    req_ids = [r["id"] for r in reqs]
    if req_ids:
        ph = ",".join("?" * len(req_ids))
        movs = conn.execute(
            f"SELECT id, item_id, quantidade, data_hora, observacao FROM movimentacoes "
            f"WHERE requisicao_id IN ({ph}) ORDER BY id",
            req_ids,
        ).fetchall()
    else:
        movs = []
    ajuste = (
        conn.execute(
            "SELECT id, item_id, quantidade, observacao FROM movimentacoes WHERE id=?",
            (MOV_ID_AJUSTE_TESTE_AVULSO,),
        ).fetchall()
        if MOV_ID_AJUSTE_TESTE_AVULSO is not None
        else []
    )
    gcs = conn.execute(GUARDA_CHUVA_TESTE_SQL).fetchall()
    lista = conn.execute(
        "SELECT id, tipo, valor, ativo FROM listas WHERE tipo='setor' AND UPPER(TRIM(valor))='TESTE'"
    ).fetchall()
    return {
        "requisicoes": reqs,
        "movimentacoes_cascata": movs,
        "movimentacao_ajuste": ajuste,
        "guarda_chuva": gcs,
        "lista_setor_teste": lista,
    }


def _bate_com_aprovado(achado):
    def ids(rows):
        return sorted(r["id"] for r in rows)

    # MOV_ID_AJUSTE_TESTE_AVULSO=None significa "não há ajuste avulso pontual a apagar
    # nesta execução" (ex.: reexecução após já ter sido apagado, ou banco de teste).
    esperado_ajuste = [MOV_ID_AJUSTE_TESTE_AVULSO] if MOV_ID_AJUSTE_TESTE_AVULSO is not None else []
    return (
        ids(achado["requisicoes"]) == APROVADO["requisicoes"]
        and ids(achado["movimentacoes_cascata"]) == APROVADO["movimentacoes_cascata"]
        and ids(achado["movimentacao_ajuste"]) == esperado_ajuste
        and ids(achado["guarda_chuva"]) == APROVADO["guarda_chuva"]
    )


def _contagens(conn):
    return {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in TABELAS_CONTAGEM}


def _imprimir_achado(achado):
    print(
        f"Requisições de teste ............... {len(achado['requisicoes'])} "
        f"-> {[r['id'] for r in achado['requisicoes']]}"
    )
    print(
        f"Movimentações em cascata ........... {len(achado['movimentacoes_cascata'])} "
        f"-> {[r['id'] for r in achado['movimentacoes_cascata']]}"
    )
    print(
        f"Movimentação de ajuste avulso (#{MOV_ID_AJUSTE_TESTE_AVULSO}) encontrada: {[r['id'] for r in achado['movimentacao_ajuste']]}"
    )
    print(
        f"Guarda-chuva de teste ............... {len(achado['guarda_chuva'])} "
        f"-> {[(r['id'], r['fornecedor_nome']) for r in achado['guarda_chuva']]}"
    )
    print(
        f"Lista setor=TESTE (ativo antes) ..... {[(r['id'], r['ativo']) for r in achado['lista_setor_teste']]}"
    )


def main():
    ap = argparse.ArgumentParser(description="Limpeza de dados de teste/junk (Task 3, v6.5.0).")
    ap.add_argument("--aplicar", action="store_true", help="grava de verdade (padrão: simulação)")
    ap.add_argument(
        "--forcar",
        action="store_true",
        help="aplica mesmo se a reauditoria divergir do aprovado (use só depois de reaprovar com o Luis)",
    )
    args = ap.parse_args()

    conn = database.get_connection()
    print(f"Banco    : {database.DB_PATH}")
    print(f"Modo     : {'APLICAR (grava)' if args.aplicar else 'SIMULAÇÃO (não grava nada)'}")
    print()

    achado = _auditar(conn)
    _imprimir_achado(achado)

    bate = _bate_com_aprovado(achado)
    if not bate:
        print(
            "\n⚠️  A reauditoria NÃO bate com o relatório aprovado em 11/08/2026 "
            f"(esperado: {APROVADO}).\nNada foi apagado."
        )
        if not args.forcar:
            print(
                "Revise o achado acima. Se o banco mudou de forma legítima, atualize APROVADO "
                "neste script e volte ao Luis para reaprovar antes de rodar com --forcar."
            )
            conn.close()
            raise SystemExit(1)
        print("--forcar usado: aplicando mesmo assim.")

    antes = _contagens(conn)
    conn.close()

    if not args.aplicar:
        print("\nSimulação — nada foi gravado. Rode de novo com --aplicar para valer.")
        return

    print("\nCriando backup do banco...")
    destino = database._backup_db("pre-limpeza-teste-v650")
    if not destino:
        raise SystemExit(
            "\n❌ Backup falhou — abortando. A limpeza exige um .bak verificado em backups/ "
            "antes de qualquer DELETE."
        )
    print(f"Backup criado: {destino}")

    req_ids = [r["id"] for r in achado["requisicoes"]]
    mov_ids = [r["id"] for r in achado["movimentacoes_cascata"]]
    if MOV_ID_AJUSTE_TESTE_AVULSO is not None:
        mov_ids.append(MOV_ID_AJUSTE_TESTE_AVULSO)
    gc_ids = [r["id"] for r in achado["guarda_chuva"]]

    # SQL direto (em vez de chamar remover_guarda_chuva/remover_valor_lista) para que as 4
    # exclusões caiam numa ÚNICA transação atômica — uma operação destrutiva sobre 4 tabelas
    # não deve poder parar pela metade.
    with database.transaction() as conn:
        if mov_ids:
            ph_mov = ",".join("?" * len(mov_ids))
            conn.execute(f"DELETE FROM movimentacoes WHERE id IN ({ph_mov})", mov_ids)
        if req_ids:
            ph_req = ",".join("?" * len(req_ids))
            conn.execute(
                f"DELETE FROM requisicoes WHERE id IN ({ph_req})", req_ids
            )  # cascade -> itens_requisicao
        if gc_ids:
            ph_gc = ",".join("?" * len(gc_ids))
            conn.execute(f"DELETE FROM guarda_chuva WHERE id IN ({ph_gc})", gc_ids)
        conn.execute("UPDATE listas SET ativo=0 WHERE tipo='setor' AND UPPER(TRIM(valor))='TESTE'")

    conn2 = database.get_connection()
    depois = _contagens(conn2)
    conn2.close()

    print("\n=== Relatório antes/depois ===")
    for t in TABELAS_CONTAGEM:
        print(f"  {t:<20} {antes[t]:>6} -> {depois[t]:>6}  (delta {depois[t] - antes[t]:+d})")

    print("\nPronto. Confira no app real: telas carregando, histórico real presente, saldos corretos.")


if __name__ == "__main__":
    main()
