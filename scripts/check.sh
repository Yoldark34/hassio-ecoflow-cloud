#!/usr/bin/env bash
# Lint (ruff with mise.toml's deferred rules, mypy) and run the tests, without needing mise.
# usage: scripts/check.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
deferred=$(python3 -c "import tomllib,sys; print(''.join(tomllib.load(open(sys.argv[1],'rb'))['env']['RUFF_DEFERRED'].split()))" "$root/mise.toml")
cd "$root/custom_components"
uv run ruff check --ignore "$deferred" .
uv run mypy .
cd "$root"
uv run pytest -q
