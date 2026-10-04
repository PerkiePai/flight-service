"""One flight over drone-sitl's /ws: the message the website's RUN button
sends. The socket stays open the whole flight because AgentRun's arm ->
takeoff -> offboard only advances while a /ws client is connected (trap 2).
Every frame goes to the run's journals as it arrives. The sim is booted
fresh per job, so the panel window holds only this run's lines."""
import asyncio
import json
import re
import time
from dataclasses import dataclass

DONE_RE = re.compile(r"\] DONE\b")
START_GRACE_S = 20.0     # RUN sent, agent still not arming -> refused
DONE_GRACE_S = 15.0      # DONE logged; let the agent exit by itself this long
RECV_TIMEOUT_S = 10.0    # no telemetry this long -> ws_lost


@dataclass
class Outcome:
    kind: str            # done | crashed | refused | arming_timeout | timeout | ws_lost
    detail: str = ""
    done_line: bool = False
    run_at: float = 0.0


async def fly(ws_url, image_tag, runlog, flight_timeout_s, arming_timeout_s,
              on_telemetry=None, connect=None):
    if connect is None:
        from websockets.asyncio.client import connect
    run_at = time.time()
    try:
        async with connect(ws_url, max_size=None) as ws:
            await ws.send(json.dumps({"type": "agent", "action": "run",
                                      "kind": "docker", "identifier": image_tag}))
            try:
                out = await _watch(ws, runlog, flight_timeout_s, arming_timeout_s, on_telemetry)
            finally:
                await _stop(ws)              # also on kill (CancelledError)
    except asyncio.CancelledError:
        raise
    except Exception as exc:                 # noqa: BLE001 -- refused/dropped/silent socket
        out = Outcome("ws_lost", repr(exc))
    out.run_at = run_at
    return out


async def _stop(ws):
    try:
        await ws.send(json.dumps({"type": "agent", "action": "stop"}))
        await asyncio.sleep(1.0)
    except Exception:                        # noqa: BLE001 -- socket already gone
        pass


def _last_exit(log):
    for line in reversed(log):
        if "agent exited" in line or line.startswith("stop:"):
            return line
    return log[-1] if log else ""


async def _watch(ws, runlog, flight_timeout_s, arming_timeout_s, on_telemetry):
    t0 = time.monotonic()
    started = done_line = False
    arming_since = done_since = last_state = None
    while True:
        if time.monotonic() - t0 > flight_timeout_s:
            return Outcome("timeout", f"still flying after {flight_timeout_s:.0f}s", done_line)
        t = json.loads(await asyncio.wait_for(ws.recv(), RECV_TIMEOUT_S))
        now = time.monotonic() - t0
        runlog.frame(t)
        agent = t.get("agent") or {}
        state, log = agent.get("state"), agent.get("log") or []
        if state != last_state:
            runlog.event("agent_state", state=state)
            last_state = state
        if on_telemetry:
            on_telemetry(t)

        if state in ("arming", "running"):
            started = True
        if started and not done_line and any(DONE_RE.search(l) for l in log):
            done_line, done_since = True, now
        if not started:
            if state == "error":
                return Outcome("refused", log[-1] if log else "agent error before arming")
            if now > START_GRACE_S:
                return Outcome("refused", f"agent never started (state {state!r})")
            continue
        if state == "arming":
            if arming_since is None:
                arming_since = now
            if now - arming_since > arming_timeout_s:
                return Outcome("arming_timeout", f"stuck in arming for {arming_timeout_s:.0f}s")
        elif state == "error":
            return Outcome("crashed", _last_exit(log), done_line)
        elif state != "running":             # stopped (exit 0) or idle
            return Outcome("done", _last_exit(log), done_line)
        if done_line and now - done_since > DONE_GRACE_S:
            return Outcome("done", "DONE logged; runner stopped the agent", True)
