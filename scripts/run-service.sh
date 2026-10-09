#!/usr/bin/env bash
# run-service.sh -- start flight-service in the background. Idempotent.
# pid -> run/service.pid, log -> logs/service.console
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
mkdir -p logs run
say() { echo "run-service: $*"; }
if [[ -f run/service.pid ]] && kill -0 "$(cat run/service.pid)" 2>/dev/null; then
    say "already running (pid $(cat run/service.pid))"; exit 0
fi
[[ -f .env ]] || { say "no .env -- cp .env.example .env" >&2; exit 1; }
set -a; source .env; set +a
# The env's own python, not `conda run`: the saved pid is then the server's
# and stop-service.sh never needs a pattern kill.
PY="$(conda run -n "${CONDA_ENV:-drone}" python -c 'import sys; print(sys.executable)')"
nohup "$PY" -u -m flight_service > logs/service.console 2>&1 &
echo $! > run/service.pid
URL="http://${RUNNER_HOST:-127.0.0.1}:${RUNNER_PORT:-8095}/healthz"
for _ in $(seq 1 20); do curl -sf -o /dev/null "$URL" && break; sleep 1; done
if curl -sf "$URL"; then echo; say "up (pid $(cat run/service.pid))"
else say "not answering -- see logs/service.console" >&2; exit 1; fi
