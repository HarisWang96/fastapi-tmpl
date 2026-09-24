#!/usr/bin/env bash

set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-false}"

args=(uv run uvicorn app.main:app --host "$HOST" --port "$PORT")
if [[ "$RELOAD" == "true" ]]; then
  args+=(--reload)
fi

exec "${args[@]}"
