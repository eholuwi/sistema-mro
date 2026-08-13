"""CLI do import de fotos da planilha MRO — casca fina sobre `services/importar_imagens.py`.

Uso (a partir da pasta `sistema-mro`):

    venv\\Scripts\\python.exe scripts\\importar_imagens_planilha.py            # SIMULAÇÃO
    venv\\Scripts\\python.exe scripts\\importar_imagens_planilha.py --aplicar  # grava de verdade

    --substituir   troca a foto de itens que JÁ têm imagem (por padrão são pulados)
    --planilha X   caminho de outra planilha (padrão: docs/Material MRO 2026.xlsx)

**Simulação é o padrão.** Sem `--aplicar` nada é gravado.

v6.6.0 — a extração (cadeia célula→imagem do Excel 365), o casamento por Part Number e a
gravação vivem em `services/importar_imagens.py`, compartilhados com a tela
**Configurações › Importar Base › Fotos da planilha**. Este arquivo só faz argumentos e
relatório de console: era ele o dono da lógica até a v6.5.2, e mantê-lo assim obrigaria a
manter duas cópias em sincronia.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# O console do Windows abre em cp1252 e derruba o script no primeiro acento do relatório —
# depois de já ter lido a planilha inteira. Forçar UTF-8 na saída custa uma linha e evita
# perder o trabalho por causa de um caractere.
for _fluxo in (sys.stdout, sys.stderr):
    if hasattr(_fluxo, "reconfigure"):
        _fluxo.reconfigure(encoding="utf-8", errors="replace")

PLANILHA_PADRAO = RAIZ / "docs" / "Material MRO 2026.xlsx"


def _relatorio(stats):
    print()
    print("-" * 78)
    print(f"  Fotos na planilha (PN único) ....... {stats['fotos_na_planilha']}")
    print(f"  Itens no inventário ................ {stats['itens_no_sistema']}")
    print(f"  PN da planilha casado no sistema ... {stats['casados']}")
    print(f"  PN da planilha SEM item no sistema . {stats['sem_item_no_sistema']}  (não serão criados)")
    print(f"  Origem das fotos ................... {stats['por_aba']}")
    print("-" * 78)
    if stats["pns_nao_encontrados"]:
        amostra = ", ".join(stats["pns_nao_encontrados"][:12])
        reticencias = " …" if stats["sem_item_no_sistema"] > 12 else ""
        print(f"\n  PN sem correspondência (amostra): {amostra}{reticencias}")
    print(f"\n  A gravar ........................... {stats['a_gravar']}")
    if stats["ja_tinham_foto"]:
        print(f"  Já têm foto no disco (pulados) ..... {stats['ja_tinham_foto']}")
    if stats["fotos_perdidas"]:
        print(f"  Foto cadastrada mas SUMIDA (repara)  {stats['fotos_perdidas']}")


def main():
    ap = argparse.ArgumentParser(description="Importa as fotos da planilha MRO para o sistema.")
    ap.add_argument("--aplicar", action="store_true", help="grava de verdade (padrão: simulação)")
    ap.add_argument("--substituir", action="store_true", help="troca a foto de quem já tem")
    ap.add_argument("--planilha", default=None, help=f"caminho do .xlsx (padrão: {PLANILHA_PADRAO})")
    args = ap.parse_args()

    caminho = Path(args.planilha) if args.planilha else PLANILHA_PADRAO
    if not caminho.exists():
        raise SystemExit(f"Planilha não encontrada: {caminho}")

    import database
    from services.importar_imagens import coletar_fotos_por_pn, importar_imagens_planilha

    print(f"Planilha : {caminho}")
    print(f"Banco    : {database.DB_PATH}")
    print(f"Modo     : {'APLICAR (grava)' if args.aplicar else 'SIMULAÇÃO (não grava nada)'}")
    print("\nLendo as fotos embutidas...")

    # A coleta é o passo caro (openpyxl num .xlsx de ~118 MB). Feita UMA vez e reusada na
    # gravação — o serviço aceita a lista pronta justamente para isso.
    fotos = coletar_fotos_por_pn(caminho)

    ok, stats = importar_imagens_planilha(caminho, substituir=args.substituir, dry_run=True, fotos=fotos)
    if not ok:
        raise SystemExit(stats.get("erro", "Falha ao ler a planilha."))
    _relatorio(stats)

    if not args.aplicar:
        print("\nSimulação — nada foi gravado. Rode de novo com --aplicar para valer.")
        return
    if not stats["a_gravar"]:
        print("\nNada a gravar.")
        return

    print("\nCriando backup do banco e gravando...")

    def _progresso(feitos, total):
        if feitos % 50 == 0 or feitos == total:
            print(f"  {feitos}/{total}...")

    ok, stats = importar_imagens_planilha(
        caminho, substituir=args.substituir, dry_run=False, fotos=fotos, progresso=_progresso
    )
    if not ok:
        raise SystemExit(stats.get("erro", "Falha ao gravar."))

    print(f"\n  backup ............................. {stats.get('backup') or '(falhou — veja o log)'}")
    print(f"  Fotos gravadas ..................... {stats['gravadas']}")
    if stats["falhas"]:
        print(f"  Falhas ............................. {len(stats['falhas'])}")
        for f in stats["falhas"][:10]:
            print(f"    - {f}")
    print("\nPronto. Confira na Ficha 360 de alguns itens antes de considerar concluído.")


if __name__ == "__main__":
    main()
