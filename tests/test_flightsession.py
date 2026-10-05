import asyncio

from fakes import FakeConnect, FakeWS, frame

from flight_service import flightsession as fs
from flight_service.journal import read_jsonl
from flight_service.runlog import RunLog


def run(frames, tmp_path, end=None, flight=600, arming=90):
    ws, seen = FakeWS(frames, end), []
    with RunLog(tmp_path) as rl:
        out = asyncio.run(fs.fly("ws://x/ws", "submission-x-1", rl, flight, arming,
                                 on_telemetry=seen.append, connect=ws))
    return out, ws, seen


def test_normal_exit_is_done_and_everything_is_journaled(tmp_path):
    out, ws, seen = run([frame("idle"), frame("arming"), frame("running"),
                         frame("running", ["[ 1.0s] DONE all legs"]),
                         frame("stopped", ["[ 1.0s] DONE all legs", "agent exited (0)"])], tmp_path)
    assert out.kind == "done" and out.done_line is True and out.run_at > 0
    assert ws.sent[0] == {"type": "agent", "action": "run", "kind": "docker", "identifier": "submission-x-1"}
    assert ws.sent[-1] == {"type": "agent", "action": "stop"}
    assert len(list(read_jsonl(tmp_path / "telemetry.jsonl"))) == 5 == len(seen)
    ev = list(read_jsonl(tmp_path / "events.jsonl"))
    assert [e["state"] for e in ev if e["kind"] == "agent_state"] == ["idle", "arming", "running", "stopped"]
    assert [e["line"] for e in ev if e["kind"] == "log"] == ["[ 1.0s] DONE all legs", "agent exited (0)"]


def test_done_line_then_agent_keeps_running(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "DONE_GRACE_S", 0.0)
    out, _, _ = run([frame("running"), frame("running", ["[ 9s] DONE"]),
                     frame("running", ["[ 9s] DONE"])], tmp_path)
    assert out.kind == "done" and out.done_line


def test_nonzero_exit_is_crashed(tmp_path):
    out, _, _ = run([frame("running"), frame("error", ["Traceback", "agent exited (1)"])], tmp_path)
    assert out.kind == "crashed" and "exited (1)" in out.detail


def test_refused_before_arming(tmp_path):
    out, _, _ = run([frame("error", ["RUN refused: no MAVLink link"])], tmp_path)
    assert out.kind == "refused" and "no MAVLink" in out.detail


def test_never_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "START_GRACE_S", 0.0)
    out, _, _ = run([frame("idle"), frame("idle")], tmp_path)
    assert out.kind == "refused" and "never started" in out.detail


def test_stuck_in_arming(tmp_path):
    out, _, _ = run([frame("arming")] * 3, tmp_path, arming=0.0)
    assert out.kind == "arming_timeout"


def test_flight_timeout_still_stops_the_agent(tmp_path):
    out, ws, _ = run([frame("running")] * 3, tmp_path, flight=0.0)
    assert out.kind == "timeout" and ws.sent[-1] == {"type": "agent", "action": "stop"}


def test_socket_drop_and_silence_without_a_reconnect_are_ws_lost(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "RECONNECT_S", 0.2)
    monkeypatch.setattr(fs, "RECONNECT_PAUSE_S", 0.01)
    out, _, _ = run([frame("running")], tmp_path / "a", end=ConnectionResetError("gone"))
    assert out.kind == "ws_lost" and "gone" in out.detail
    monkeypatch.setattr(fs, "RECV_TIMEOUT_S", 0.05)
    out, _, _ = run([frame("running")], tmp_path / "b")
    assert out.kind == "ws_lost"


def run_with(connect, tmp_path, flight=600, arming=90):
    seen = []
    with RunLog(tmp_path) as rl:
        out = asyncio.run(fs.fly("ws://x/ws", "submission-x-1", rl, flight, arming,
                                 on_telemetry=seen.append, connect=connect))
    return out, seen


def test_a_dropped_socket_is_reconnected_and_the_flight_followed_on(tmp_path, monkeypatch):
    """design 4: ws_lost only when /ws cannot be reached again within 10 s. The
    agent keeps flying in drone-sitl meanwhile; RUN must not be sent twice."""
    monkeypatch.setattr(fs, "RECONNECT_PAUSE_S", 0.01)
    first = FakeWS([frame("arming"), frame("running", ["[1s] a"])], end=ConnectionResetError("blip"))
    second = FakeWS([frame("running", ["[1s] a", "[2s] b"]),
                     frame("stopped", ["[1s] a", "[2s] b", "agent exited (0)"])])
    out, seen = run_with(FakeConnect(first, OSError("refused"), second), tmp_path)
    assert out.kind == "done" and len(seen) == 4
    runs = [m for m in first.sent + second.sent if m.get("action") == "run"]
    assert len(runs) == 1 and first.sent[0]["action"] == "run"
    assert second.sent[-1] == {"type": "agent", "action": "stop"}
    ev = list(read_jsonl(tmp_path / "events.jsonl"))
    kinds = [e["kind"] for e in ev]
    assert "ws_lost" in kinds and "ws_reconnected" in kinds
    assert [e["line"] for e in ev if e["kind"] == "log"] == ["[1s] a", "[2s] b", "agent exited (0)"]


def test_the_first_connect_is_retried_too(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "RECONNECT_PAUSE_S", 0.01)
    ws = FakeWS([frame("running"), frame("stopped", ["agent exited (0)"])])
    connect = FakeConnect(OSError("not up yet"), ws)
    out, _ = run_with(connect, tmp_path)
    assert out.kind == "done" and connect.calls == 2 and ws.sent[0]["action"] == "run"


def test_cancel_sends_stop_and_propagates(tmp_path):
    ws = FakeWS([frame("running")])

    async def scenario():
        with RunLog(tmp_path) as rl:
            task = asyncio.create_task(fs.fly("ws://x", "t", rl, 600, 90, connect=ws))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                return "cancelled"

    assert asyncio.run(scenario()) == "cancelled"
    assert ws.sent[-1] == {"type": "agent", "action": "stop"}
