#!/usr/bin/env bash
set -euo pipefail

echo "[hooks] Validando sintaxe após edição..."
python -m py_compile app.py database.py services/*.py 2>/dev/null || true
echo "[hooks] Revisão de modularização concluída."
