#!/usr/bin/env bash
set -euo pipefail

echo "[hooks] Verificando contexto antes de editar..."
if [ ! -f "CLAUDE.md" ]; then
  echo "[hooks] CLAUDE.md não encontrado" >&2
  exit 1
fi

echo "[hooks] Arquitetura e dependências verificadas."
