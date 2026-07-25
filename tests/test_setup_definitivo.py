from pathlib import Path


def test_setup_definitivo_estrutura_basica():
    root = Path(__file__).resolve().parents[1]
    required = [
        "CLAUDE.md",
        "docs",
        "prompts",
        "skills",
        "hooks",
        "templates",
        "config",
    ]
    for item in required:
        assert (root / item).exists(), f"Esperado: {item}"
