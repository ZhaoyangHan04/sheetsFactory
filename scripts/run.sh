#!/usr/bin/env bash
set -euo pipefail
FACTORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FACTORY_ROOT"
UV_PROJECT_ENVIRONMENT="$FACTORY_ROOT/.venv312" uv sync --frozen --extra test --python 3.12
.venv312/bin/python scripts/restore_runtime_inputs.py
export PYTHONPATH="$FACTORY_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec .venv312/bin/python -m sheets_factory.cli "$@"
