#!/usr/bin/env bash
set -euo pipefail
FACTORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FACTORY_ROOT"
if [[ ! -x .venv312/bin/python ]]; then
  uv venv .venv312 --python 3.12
  uv pip install --python .venv312/bin/python -e '.[test]'
fi
export PYTHONPATH="$FACTORY_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec .venv312/bin/python -m sheets_factory.cli "$@"
