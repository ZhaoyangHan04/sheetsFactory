#!/usr/bin/env bash
set -euo pipefail
DIFFICULTY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIFFICULTY_ROOT"
UV_PROJECT_ENVIRONMENT="$DIFFICULTY_ROOT/.venv312" uv sync --frozen --extra test --python 3.12
export PYTHONPATH="$DIFFICULTY_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec .venv312/bin/python scripts/iterate_difficulty.py "$@"
