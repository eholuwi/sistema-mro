from pathlib import Path

root = Path(__file__).resolve().parent.parent
required = [
    "CLAUDE.md",
    "docs",
    "prompts",
    "skills",
    "hooks",
    "templates",
    "config",
    "tests",
]

missing = [item for item in required if not (root / item).exists()]
if missing:
    raise SystemExit(f"Arquivos ou diretórios ausentes: {missing}")

print("Estrutura de setup validada com sucesso.")
