#!/usr/bin/env bash
# - This shell wrapper only resolves a Python interpreter and forwards to the
#   canonical build-local-core implementation through scripts/build-local.py.
# - Keep logic here minimal so platform behavior does not drift from the other
#   local build entrypoints.

set -euo pipefail

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "Missing required command: python3 (or python)" >&2
  exit 1
fi

cmd=("$PYTHON_BIN" "scripts/build-local-core.py")
if [[ -n "${CMAKE_GENERATOR:-}" ]]; then
  cmd+=(--cmake-generator "${CMAKE_GENERATOR}")
fi
cmd+=("$@")
exec "${cmd[@]}"
