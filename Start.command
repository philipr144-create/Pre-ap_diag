#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, cantools' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements-lock.txt
fi
exec .venv/bin/python -m teslalab.server "$@"
