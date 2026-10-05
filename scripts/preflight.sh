#!/usr/bin/env bash
# preflight.sh -- is this machine ready to run flight-service? Read-only: lists
# what is missing and how to fix it. Exit 1 if a required check fails.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
# preflight itself needs only the standard library: fall back to python3 when
# the conda env is what is missing.
PY="$(conda run -n "${CONDA_ENV:-drone}" python -c 'import sys; print(sys.executable)' 2>/dev/null)" \
    || PY=python3
exec "$PY" -m flight_service.preflight
