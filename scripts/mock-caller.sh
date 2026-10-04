#!/usr/bin/env bash
# mock-caller.sh IMAGE [FLIGHT_TIMEOUT_S] -- play พี่ต้น: one POST, poll
# until the job ends, download every result file to mock-out/<job>/.
# KILL_AFTER_S=N: kill the job N seconds after it starts flying.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a; source "$DIR/.env"; set +a
R="http://${RUNNER_HOST:-127.0.0.1}:${RUNNER_PORT:-8095}"
H="Authorization: Bearer $RUNNER_TOKEN"
IMAGE="${1:?usage: mock-caller.sh IMAGE [FLIGHT_TIMEOUT_S]}"
BODY="$(python3 -c 'import json,sys; print(json.dumps({"image": sys.argv[1], "flight_timeout_s": int(sys.argv[2])}))' "$IMAGE" "${2:-600}")"
resp="$(curl -s -X POST "$R/jobs" -H "$H" -H 'Content-Type: application/json' -d "$BODY")"
echo "$resp"
id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])' <<<"$resp")"
flying_since=""
while :; do
    s="$(curl -s "$R/jobs/$id" -H "$H")"
    line="$(python3 - "$s" <<'PY'
import json, sys
j = json.loads(sys.argv[1]); t = j.get("telemetry") or {}; sl = j.get("score_live") or {}
tail = (j.get("log_tail") or [""])[-1]
print(f"{j['state']} {j['elapsed_s']:.0f}s alt={t.get('alt_m')} lat={t.get('lat')} lon={t.get('lon')} "
      f"agent={t.get('agent_state')} trucks={sl.get('trucks_found')}/{sl.get('trucks_total')} | {tail[:80]}")
PY
)"
    echo "$(date +%T) $line"
    state="${line%% *}"
    [[ "$state" == done || "$state" == failed || "$state" == killed ]] && break
    if [[ "$state" == flying && -n "${KILL_AFTER_S:-}" ]]; then
        flying_since="${flying_since:-$SECONDS}"
        if (( SECONDS - flying_since >= KILL_AFTER_S )); then
            echo ">>> kill"; s="$(curl -s -X POST "$R/jobs/$id/kill" -H "$H")"; break
        fi
    fi
    sleep 5
done
out="$DIR/mock-out/$id"; mkdir -p "$out"; echo "$s" > "$out/job.json"
for f in $(python3 -c 'import json,sys; print(" ".join(((json.load(sys.stdin).get("result") or {}).get("files") or {})))' <<<"$s"); do
    curl -s -f "$R/jobs/$id/files/$f" -H "$H" -o "$out/$f" || echo "missing $f"
done
python3 -c 'import json,sys; j=json.load(sys.stdin); r=j.get("result") or {}; print(json.dumps({k: j.get(k) for k in ("state","failed_in","reason","detail")}, ensure_ascii=False)); print(json.dumps({k: r.get(k) for k in ("ended_by","partial","flight_s","distance_m","score","missing")}, ensure_ascii=False))' <<<"$s"
ls -la "$out"
