#!/usr/bin/env bash
# stop-service.sh -- stop flight-service by its pid file (never a pattern kill).
# A job in flight is left as-is: the next start finalizes it from its
# journals (failed / runner_restarted) and stops the sim it had started.
set -uo pipefail
PIDF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/run/service.pid"
say() { echo "stop-service: $*"; }
[[ -f "$PIDF" ]] || { say "not running (no pid file)"; exit 0; }
pid="$(cat "$PIDF")"
if ! kill -0 "$pid" 2>/dev/null; then say "not running"; rm -f "$PIDF"; exit 0; fi
kill "$pid"
for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
kill -0 "$pid" 2>/dev/null && { say "SIGKILL $pid"; kill -9 "$pid"; }
rm -f "$PIDF"; say "stopped"
