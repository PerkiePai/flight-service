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
RECV_TIMEOUT_S = 10.0    # no telemetry this long -> treat the socket as dropped
RECONNECT_S = 10.0       # dropped socket not back within this long -> ws_lost
RECONNECT_PAUSE_S = 1.0  # between reconnect attempts


@dataclass
class Outcome:
    kind: str            # done | crashed | refused | arming_timeout | timeout | ws_lost
    detail: str = ""
    done_line: bool = False
    run_at: float = 0.0


async def fly(ws_url, image_tag, runlog, flight_timeout_s, arming_timeout_s,
              on_telemetry=None, connect=None):
    """Send RUN once, then follow the flight. A dropped or silent socket is
    reconnected: the agent keeps flying inside drone-sitl meanwhile, so the
    flight is picked up where it was (design 4: ws_lost only when /ws cannot
    be reached again within RECONNECT_S)."""
    if connect is None:
        from websockets.asyncio.client import connect
    run_at = time.time()
    watch = _Watch(runlog, flight_timeout_s, arming_timeout_s, on_telemetry)
    sent_run = False
    lost_at, last_err = None, ""
    while True:
        if lost_at is not None and time.monotonic() - lost_at > RECONNECT_S:
            out = Outcome("ws_lost", f"no /ws for {RECONNECT_S:.0f}s: {last_err}", watch.done_line)
            break
        if sent_run and watch.elapsed() > flight_timeout_s:      # ran out while reconnecting
            out = Outcome("timeout", f"still flying after {flight_timeout_s:.0f}s", watch.done_line)
            break
        frames_before = watch.frames
        try:
            async with connect(ws_url, max_size=None) as ws:
                if not sent_run:
                    await ws.send(json.dumps({"type": "agent", "action": "run",
                                              "kind": "docker", "identifier": image_tag}))
                    sent_run = True
                elif lost_at is not None:
                    runlog.event("ws_reconnected", after_s=round(time.monotonic() - lost_at, 1))
                try:
                    out = await watch.follow(ws)
                except asyncio.CancelledError:
                    await _stop(ws)          # killed: stop the agent before going
                    raise
                await _stop(ws)
                break
        except asyncio.CancelledError:
            raise
        except Exception as exc:             # noqa: BLE001 -- refused/dropped/silent socket
            last_err = repr(exc)
            # Only a connection that delivered telemetry counts as "back": one
            # that connects but stays silent must not restart the window.
            if lost_at is None or watch.frames > frames_before:
                lost_at = time.monotonic()
                runlog.event("ws_lost", error=last_err)
            await asyncio.sleep(RECONNECT_PAUSE_S)
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


class _Watch:
    """What we know about the flight; survives a reconnect."""

    def __init__(self, runlog, flight_timeout_s, arming_timeout_s, on_telemetry):
        self.runlog, self.on_telemetry = runlog, on_telemetry
        self.flight_timeout_s, self.arming_timeout_s = flight_timeout_s, arming_timeout_s
        self.t0 = time.monotonic()
        self.started = self.done_line = False
        self.arming_since = self.done_since = self.last_state = None
        self.frames = 0

    def elapsed(self):
        return time.monotonic() - self.t0

    async def follow(self, ws):
        """Outcome once the flight is decided; raises when the socket fails."""
        while True:
            if self.elapsed() > self.flight_timeout_s:
                return Outcome("timeout", f"still flying after {self.flight_timeout_s:.0f}s",
                               self.done_line)
            t = json.loads(await asyncio.wait_for(ws.recv(), RECV_TIMEOUT_S))
            out = self._frame(t, self.elapsed())
            if out is not None:
                return out

    def _frame(self, t, now):
        self.frames += 1
        self.runlog.frame(t)
        agent = t.get("agent") or {}
        state, log = agent.get("state"), agent.get("log") or []
        if state != self.last_state:
            self.runlog.event("agent_state", state=state)
            self.last_state = state
        if self.on_telemetry:
            self.on_telemetry(t)

        if state in ("arming", "running"):
            self.started = True
        if self.started and not self.done_line and any(DONE_RE.search(l) for l in log):
            self.done_line, self.done_since = True, now
        if not self.started:
            if state == "error":
                return Outcome("refused", log[-1] if log else "agent error before arming")
            if now > START_GRACE_S:
                return Outcome("refused", f"agent never started (state {state!r})")
            return None
        if state == "arming":
            if self.arming_since is None:
                self.arming_since = now
            if now - self.arming_since > self.arming_timeout_s:
                return Outcome("arming_timeout", f"stuck in arming for {self.arming_timeout_s:.0f}s")
        elif state == "error":
            return Outcome("crashed", _last_exit(log), self.done_line)
        elif state != "running":             # stopped (exit 0) or idle
            return Outcome("done", _last_exit(log), self.done_line)
        if self.done_line and now - self.done_since > DONE_GRACE_S:
            return Outcome("done", "DONE logged; runner stopped the agent", True)
        return None
