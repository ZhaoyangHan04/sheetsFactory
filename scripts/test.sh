#!/usr/bin/env bash
set -euo pipefail
FACTORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FACTORY_ROOT"
exec .venv312/bin/python -m pytest "$@"
