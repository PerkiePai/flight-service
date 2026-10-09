"""scripts/flight.py against a scripted service on a real socket, and (the
tests that say so) against the real app."""
import ast
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "flight.py"
HANG = object()         # in a stream's chunk list: keep the line open and silent
CUT = object()          # as a body: close the line without answering


class Short(bytes):
    """As a body: a file that stops 10 bytes before its Content-Length."""


def load():
    spec = importlib.util.spec_from_file_location("flight", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def flight(monkeypatch):
    """The script as a module, with its waits shrunk to test speed."""
    module = load()
    for name, value in (("READY_POLL_S", 0.01), ("POLL_S", 0.01), ("BACKOFF_S", 0.01),
                        ("BACKOFF_MAX_S", 0.02), ("EXPECT_WAIT_S", 0.05), ("SHOW_EVERY_S", 0)):
        monkeypatch.setattr(module, name, value)
    return module


class FakeService:
    """script: {"METHOD /path": [answer, ...]}. Answers are used in order
    and the last one repeats. An answer is (status, body): a dict is sent
    as JSON, bytes as a file (Short: cut off early), a list as a stream
    (each chunk flushed, then the line closes; HANG in it holds the line
    open), CUT closes the line with no answer. Unscripted = 404.
    `seen` is every request as (method, path with query, headers, body)."""

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.seen, self.hanging, self.release = [], threading.Event(), threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.answer(self)

            do_POST = do_GET

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()

    def answer(self, h):
        body = h.rfile.read(int(h.headers.get("Content-Length") or 0))
        self.seen.append((h.command, h.path, {k.lower(): v for k, v in h.headers.items()}, body))
        answers = self.script.get(f"{h.command} {h.path.split('?')[0]}")
        if not answers:
            status, payload = 404, {"detail": "not scripted"}
        else:
            status, payload = answers.pop(0) if len(answers) > 1 else answers[0]
        if payload is CUT:
            h.connection.shutdown(socket.SHUT_RDWR)
            return
        h.send_response(status)
        if isinstance(payload, list):
            h.send_header("Content-Type", "text/event-stream")
            h.end_headers()
            for chunk in payload:
                if chunk is HANG:
                    self.hanging.set()
                    self.release.wait(30)
                    return
                h.wfile.write(chunk)
                h.wfile.flush()
            return
        data = json.dumps(payload).encode() if isinstance(payload, dict) else payload
        h.send_header("Content-Type", "application/json" if isinstance(payload, dict)
                      else "application/octet-stream")
        h.send_header("Content-Length", str(len(data) + (10 if isinstance(payload, Short) else 0)))
        h.end_headers()
        h.wfile.write(data)

    def calls(self, prefix=""):
        return [f"{method} {path}" for method, path, _, _ in self.seen
                if f"{method} {path}".startswith(prefix)]

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def service():
    """service(script) -> FakeService, closed after the test."""
    made = []

    def start(script):
        made.append(FakeService(script))
        return made[-1]

    yield start
    for s in made:
        s.close()


def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return "http://127.0.0.1:%d" % s.getsockname()[1]


def run(flight, capsys, url, *argv):
    """(exit code, stdout lines, stderr) of `flight.py --url .. <argv>`."""
    code = flight.main(["--url", url, *argv])
    out = capsys.readouterr()
    return code, out.out.splitlines(), out.err


READY = {"ok": True, "ready": True, "phase": "idle", "pending": 0}
BUSY = {"ok": True, "ready": False, "phase": "running", "pending": 1}
DEGRADED = {"ok": False, "ready": False, "phase": "degraded", "pending": 0}


def test_the_script_is_one_executable_file_on_the_standard_library_only():
    source = SCRIPT.read_text()
    tree = ast.parse(source, feature_version=(3, 8))                # nothing newer than Python 3.8
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)
    assert os.access(SCRIPT, os.X_OK)


def test_sse_events_reads_whole_events_only(flight):
    lines = [b": ping\n", b"\n", b"event: state\n", b'data: {"state":"flying"}\n', b"\n",
             b"id: 7\r\n", b"event: telemetry\r\n", b"data: {\r\n", b"data: }\r\n", b"\r\n",
             b"data:no space, no event name\n", b"\n",
             b"id: 8\n", b"event: telemetry\n", b'data: {"cut":'  # the line broke here
             ]
    assert list(flight.sse_events(lines)) == [
        ("state", '{"state":"flying"}', None), ("telemetry", "{\n}", "7"),
        ("message", "no space, no event name", None)]


def test_health_exit_codes(flight, capsys, service):
    assert run(flight, capsys, service({"GET /healthz": [(200, READY)]}).url, "health") \
        == (0, [json.dumps(READY)], "")
    code, out, _ = run(flight, capsys, service({"GET /healthz": [(200, BUSY)]}).url, "health")
    assert (code, json.loads(out[0])["ready"]) == (1, False)
    code, out, err = run(flight, capsys, closed_port(), "health")
    assert (code, out) == (2, []) and "cannot reach the service" in err


def test_the_token_option_is_gone(flight, capsys):
    for argv in (["--token=x", "kill", "j-1"], ["--token", "x", "kill", "j-1"]):   # an old script's call
        with pytest.raises(SystemExit) as e:
            flight.main(["--url", closed_port(), *argv])
        assert e.value.code == 2, argv
    assert "unrecognized arguments: --token=x" in capsys.readouterr().err


def test_url_comes_from_the_environment_and_no_authorization_is_sent(flight, capsys, service, monkeypatch):
    svc = service({"POST /jobs/j-1/kill": [(200, {"state": "killed", "reason": "killed"})]})
    monkeypatch.setenv("FLIGHT_URL", svc.url + "/")             # a trailing slash is harmless
    assert flight.main(["kill", "j-1"]) == 0
    assert "authorization" not in svc.seen[0][2] and svc.calls() == ["POST /jobs/j-1/kill"]


def test_a_leftover_runner_token_variable_is_ignored(flight, capsys, service, monkeypatch):
    svc = service({"POST /jobs/j-1/kill": [(200, {"state": "killed", "reason": "killed"})]})
    monkeypatch.setenv("FLIGHT_URL", svc.url)
    monkeypatch.setenv("RUNNER_TOKEN", "left-over-from-an-old-env")
    assert flight.main(["kill", "j-1"]) == 0
    assert "authorization" not in svc.seen[0][2]


def test_kill_without_an_id_asks_the_service_to_pick_the_flying_job(flight, capsys, service):
    svc = service({"POST /kill": [(200, {"job_id": "j-7", "state": "killed", "reason": "killed"}),
                                  (202, {"job_id": "j-8", "state": "flying", "reason": None}),
                                  (409, {"detail": "no job to kill"})]})
    assert run(flight, capsys, svc.url, "kill") == (
        0, [json.dumps({"job_id": "j-7", "state": "killed", "reason": "killed"})], "")
    code, out, err = run(flight, capsys, svc.url, "kill")
    assert (code, json.loads(out[0])["job_id"]) == (0, "j-8") and "flight.py watch j-8" in err
    code, out, err = run(flight, capsys, svc.url, "kill")
    assert (code, out) == (1, []) and "HTTP 409" in err and "no job to kill" in err
    assert svc.calls() == ["POST /kill"] * 3


def test_kill(flight, capsys, service):
    svc = service({"POST /jobs/j-1/kill": [(200, {"state": "killed", "reason": "killed"})],
                   "POST /jobs/j-2/kill": [(202, {"state": "flying", "reason": None})],
                   "POST /jobs/j-3/kill": [(409, {"detail": "job is done; nothing to kill"})],
                   "POST /jobs/j-5/kill": [(401, {"detail": "missing or wrong bearer token"})]})
    assert run(flight, capsys, svc.url, "kill", "j-1") == (
        0, [json.dumps({"job_id": "j-1", "state": "killed", "reason": "killed"})], "")
    code, out, err = run(flight, capsys, svc.url, "kill", "j-2")
    assert (code, json.loads(out[0])["state"]) == (0, "flying") and "flight.py watch j-2" in err
    code, out, err = run(flight, capsys, svc.url, "kill", "j-3")
    assert (code, out) == (1, []) and "HTTP 409" in err and "nothing to kill" in err
    assert run(flight, capsys, svc.url, "kill", "j-4")[0] == 1                # 404: no such job
    code, _, err = run(flight, capsys, svc.url, "kill", "j-5")      # a 401 from a proxy in front, say
    assert code == 2 and "HTTP 401: missing or wrong bearer token" in err


def test_an_answer_that_is_not_json_is_still_reported(flight, capsys, service):
    svc = service({"GET /healthz": [(502, b"<html>Bad Gateway</html>")]})
    code, out, err = run(flight, capsys, svc.url, "health")
    assert (code, out) == (2, []) and "HTTP 502: <html>Bad Gateway</html>" in err


def test_a_line_cut_before_the_answer_is_unreachable_not_a_traceback(flight, capsys, service):
    svc = service({"GET /healthz": [(200, CUT)]})
    code, _, err = run(flight, capsys, svc.url, "health")
    assert code == 2 and "cannot reach the service" in err


# --- against the real app (uvicorn + create_app, the worker stubbed) --------------

def real(tmp_path, serve, **settings):
    from test_app import make
    return make(tmp_path / "svc", serve, **settings)


def test_real_service_takes_an_upload(flight, tmp_path, serve):
    url, store, _ = real(tmp_path, serve, min_free_gb=0)
    archive = tmp_path / "agent.tar"
    archive.write_bytes(os.urandom(3_000_000))
    status, body = flight.Api(url).upload(str(archive), "kind=image&name=truck")
    assert status == 202 and body["source"] == "upload"
    assert (tmp_path / "svc" / "uploads" / f"{body['job_id']}.tar").read_bytes() == archive.read_bytes()


def test_real_service_refuses_a_file_before_it_is_sent(flight, tmp_path, serve, monkeypatch):
    """What `Expect: 100-continue` buys: a 16 GB file is not pushed down the
    line only to learn it was never going to be taken."""
    import http.client
    sent = []
    send = http.client.HTTPConnection.send
    monkeypatch.setattr(http.client.HTTPConnection, "send",
                        lambda self, data: (sent.append(len(data)), send(self, data))[1])
    url, store, _ = real(tmp_path, serve, min_free_gb=0, max_upload_gb=1e-6)      # ~1 KB allowed
    archive = tmp_path / "agent.tar"
    archive.write_bytes(os.urandom(3_000_000))
    api = flight.Api(url)
    status, body = api.upload(str(archive), "kind=image&name=truck")
    assert status == 413 and "file over" in body["detail"]
    assert sum(sent) < 2000 and store.all() == []                    # headers only
    (tmp_path / "small.tar").write_bytes(b"x" * 100)
    assert api.upload(str(tmp_path / "small.tar"), "kind=image&name=a")[0] == 202
    status, body = api.upload(str(tmp_path / "small.tar"), "kind=image&name=b")   # the slot is taken now
    assert status == 409 and body["detail"] == "busy"


# --- run / watch -------------------------------------------------------------

JOB = "j-20261006-120000-ab12"
ACCEPTED = (202, {"job_id": JOB, "state": "queued", "source": "registry"})
FILES = {"result.json": b'{"ok": 1}', "detections.mp4": b"mp4" * 100_000}


def sse(event, data, eid=None):
    head = f"id: {eid}\n" if eid is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def state(name, reason=None):
    return sse("state", {"state": name, "since": "2026-10-06T12:00:00+0700", "reason": reason})


def tele(n):
    return sse("telemetry", {"t": n, "lat": 14.0, "lon": 100.0, "alt_m": 20.0 + n,
                             "mode": "OFFBOARD", "agent": {"state": "running"}}, n)


def ended(state="done", reason=None, files=tuple(FILES), missing=()):
    """The job as GET /jobs/{id} gives it once it ended."""
    return {"job_id": JOB, "state": state, "reason": reason, "failed_in": None if state == "done" else "flying",
            "detail": "" if state == "done" else "what went wrong",
            "result": {"ended_by": "agent", "flight_s": 484.8, "score": {"version": "v0", "score": 95.6},
                       "files": {n: f"/jobs/{JOB}/files/{n}" for n in files}, "missing": list(missing)}}


def end_of(job):
    return sse("end", {k: job[k] for k in ("job_id", "state", "failed_in", "reason", "detail", "result")})


def flown(job=None, **replace):
    """A service that takes one job, streams the flight, and has its files."""
    job = job or ended()
    script = {"GET /healthz": [(200, READY)],
              "POST /jobs": [ACCEPTED],
              f"GET /jobs/{JOB}/stream": [(200, [state("queued"), state("flying"), tele(1), tele(2),
                                                 state(job["state"], job["reason"]), end_of(job)])],
              f"GET /jobs/{JOB}": [(200, job)],
              **{f"GET /jobs/{JOB}/files/{n}": [(200, data)] for n, data in FILES.items()}}
    script.update(replace)
    return script


def saved(out):
    """{name: bytes} of everything under <out>/<JOB>/."""
    return {p.name: p.read_bytes() for p in (out / JOB).iterdir()}


def test_run_waits_submits_follows_and_fetches(flight, capsys, service, tmp_path):
    svc = service(flown(**{"GET /healthz": [(200, BUSY), (200, READY)],
                           "POST /jobs": [(409, {"detail": "busy", "current_job": "j-0", "pending": ["j-9"]}),
                                          ACCEPTED]}))
    out = tmp_path / "out"
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--timeout", "300",
                           "--out", str(out))
    assert code == 0
    assert svc.calls() == ["GET /healthz", "GET /healthz", "POST /jobs", "GET /healthz", "POST /jobs",
                           f"GET /jobs/{JOB}/stream", f"GET /jobs/{JOB}",
                           f"GET /jobs/{JOB}/files/detections.mp4", f"GET /jobs/{JOB}/files/result.json"]
    method, _, headers, body = svc.seen[4]
    assert json.loads(body) == {"image": "perkiepai/x:1", "flight_timeout_s": 300}
    assert "authorization" not in headers and headers["content-type"] == "application/json"
    assert json.loads(lines[-1]) == {"job_id": JOB, "state": "done", "reason": None, "score": 95.6,
                                     "out_dir": str(out / JOB), "not_downloaded": []}
    assert len(lines) == 1                                       # stdout is that one line
    files = saved(out)
    assert sorted(files) == ["detections.mp4", "job.json", "result.json"]       # and no *.part
    assert json.loads(files["job.json"]) == ended() and files["detections.mp4"] == FILES["detections.mp4"]
    for expected in ("service busy", f"job {JOB} accepted", "state queued", "state flying",
                     "flying alt=21.0 lat=14.0 lon=100.0 mode=OFFBOARD agent=running", "state done",
                     "score 95.6"):
        assert expected in err, expected


def test_without_a_timeout_the_service_decides(flight, capsys, service, tmp_path):
    svc = service(flown())
    assert run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))[0] == 0
    assert json.loads(svc.seen[1][3]) == {"image": "perkiepai/x:1"}


@pytest.mark.parametrize("how, reason", [("failed", "flight_timeout"), ("killed", "killed")])
def test_a_job_that_did_not_end_done_exits_1_with_its_files(flight, capsys, service, tmp_path, how, reason):
    svc = service(flown(ended(how, reason)))
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))
    assert code == 1 and json.loads(lines[-1])["state"] == how and json.loads(lines[-1])["reason"] == reason
    assert f"{how} ({reason}: what went wrong)" in err and "result.json" in saved(tmp_path)


def test_a_degraded_service_is_not_waited_for(flight, capsys, service, tmp_path):
    svc = service(flown(**{"GET /healthz": [(200, DEGRADED)]}))
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--wait", "30",
                           "--out", str(tmp_path / "out"))
    assert (code, lines) == (2, []) and "degraded" in err
    assert svc.calls() == ["GET /healthz"] and not (tmp_path / "out").exists()


def test_a_service_that_stays_busy_ends_the_wait(flight, capsys, service):
    svc = service(flown(**{"GET /healthz": [(200, BUSY)]}))
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--wait", "0.05")
    assert (code, lines) == (2, []) and "still busy after 0.05s" in err and svc.calls("POST") == []


def test_a_slot_that_is_always_taken_ends_the_wait(flight, capsys, service):
    svc = service(flown(**{"POST /jobs": [(409, {"detail": "busy"})]}))      # ready, yet 409 every time
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--wait", "0.05")
    assert (code, lines) == (2, []) and "HTTP 409 (pending slot full): busy" in err


@pytest.mark.parametrize("status, body, says", [
    (403, {"detail": "image not in the allowlist"}, "HTTP 403: image not in the allowlist"),
    (400, {"detail": "flight_timeout_s must be 30..900"}, "HTTP 400: flight_timeout_s must be 30..900"),
    (503, {"detail": "degraded"}, "HTTP 503 (service degraded: someone has to fix the machine): degraded"),
    (401, {"detail": "missing or wrong bearer token"}, "HTTP 401: missing or wrong bearer token")])
def test_a_refused_job_shows_what_the_service_said(flight, capsys, service, status, body, says):
    svc = service(flown(**{"POST /jobs": [(status, body)]}))
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1")
    assert (code, lines) == (2, []) and says in err
    assert svc.calls() == ["GET /healthz", "POST /jobs"]              # asked once, followed nothing


def test_run_needs_exactly_one_of_image_and_file(flight, capsys, tmp_path):
    for argv in (["run"], ["run", "perkiepai/x:1", "--file", "x.tar", "--kind", "image", "--name", "x"],
                 ["run", "--file", "x.tar"], ["run", "--file", "x.tar", "--kind", "zip", "--name", "x"]):
        with pytest.raises(SystemExit) as e:
            flight.main(["--url", closed_port(), *argv])
        assert e.value.code == 2, argv
    capsys.readouterr()
    code, _, err = run(flight, capsys, closed_port(), "run", "--file", str(tmp_path / "nope.tar"),
                       "--kind", "image", "--name", "x")
    assert code == 2 and "no such file" in err


def test_a_broken_stream_resumes_after_the_last_whole_line(flight, capsys, service, tmp_path):
    cut = b'id: 3\nevent: telemetry\ndata: {"t": 3, "alt_m"'       # the line broke inside line 3
    svc = service(flown(**{f"GET /jobs/{JOB}/stream": [
        (200, [state("flying"), tele(1), tele(2), cut]),
        (200, [state("flying"), tele(3), tele(4), state("done"), end_of(ended())])]}))
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))
    assert code == 0
    streams = [headers.get("last-event-id") for _, path, headers, _ in svc.seen if path.endswith("/stream")]
    assert streams == [None, "2"]
    assert [err.count(f"alt={20.0 + n} ") for n in (1, 2, 3, 4)] == [1, 1, 1, 1]   # none lost, none twice
    assert err.count("state flying") == 1 and "stream lost" in err and "after line 2" in err


def test_a_silent_line_counts_as_broken(flight, capsys, service, tmp_path, monkeypatch):
    monkeypatch.setattr(flight, "STREAM_IDLE_S", 0.2)
    svc = service(flown(**{f"GET /jobs/{JOB}/stream": [
        (200, [state("flying"), tele(1), HANG]),
        (200, [state("done"), end_of(ended())])]}))
    code, _, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))
    assert code == 0 and "stream lost" in err
    assert [h.get("last-event-id") for _, p, h, _ in svc.seen if p.endswith("/stream")] == [None, "1"]


def test_a_service_without_the_stream_is_polled(flight, capsys, service, tmp_path):
    flying = {"job_id": JOB, "state": "flying", "reason": None, "result": None,
              "telemetry": {"lat": 14.0, "lon": 100.0, "alt_m": 33.33, "mode": "OFFBOARD",
                            "agent_state": "running"}}
    script = flown(**{f"GET /jobs/{JOB}": [(200, flying), (200, flying), (200, ended())]})
    del script[f"GET /jobs/{JOB}/stream"]                           # 404, like a service before SSE
    svc = service(script)
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))
    assert code == 0 and json.loads(lines[-1])["state"] == "done"
    assert svc.calls(f"GET /jobs/{JOB}/stream") == [f"GET /jobs/{JOB}/stream"]      # asked once
    assert "polling every" in err and "flying alt=33.3 " in err and "agent=running" in err
    assert sorted(saved(tmp_path)) == ["detections.mp4", "job.json", "result.json"]


def test_no_stream_for_too_long_falls_back_to_polling(flight, capsys, service, tmp_path, monkeypatch):
    monkeypatch.setattr(flight, "STREAM_GIVE_UP_S", 0.05)
    svc = service(flown(**{f"GET /jobs/{JOB}/stream": [(200, CUT)]}))
    code, _, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))
    assert code == 0 and "no stream for 0.05s" in err and "polling every" in err
    assert len(svc.calls(f"GET /jobs/{JOB}/stream")) >= 2            # it did try again first


def test_an_event_that_cannot_be_read_falls_back_to_polling(flight, capsys, service, tmp_path):
    svc = service(flown(**{f"GET /jobs/{JOB}/stream": [(200, [state("flying"), b"event: telemetry\ndata: {}\n\n"])]}))
    code, _, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))
    assert code == 0 and "unreadable stream event" in err
    assert len(svc.calls(f"GET /jobs/{JOB}/stream")) == 1            # not asked for the same event again


def test_polling_gives_up_when_the_service_is_gone(flight, capsys, service, tmp_path, monkeypatch):
    monkeypatch.setattr(flight, "POLL_GIVE_UP_S", 0.05)
    script = flown(**{f"GET /jobs/{JOB}": [(200, {"job_id": JOB, "state": "flying", "reason": None}),
                                           (502, b"Bad Gateway")]})
    del script[f"GET /jobs/{JOB}/stream"]
    svc = service(script)
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))
    assert code == 2 and "cannot reach the service for 0.05s" in err and f"flight.py watch {JOB}" in err
    assert json.loads(lines[-1]) == {"job_id": JOB, "state": "flying", "reason": None, "score": None,
                                     "out_dir": None, "not_downloaded": []}


def test_a_file_that_cannot_be_fetched_is_named_and_exits_2(flight, capsys, service, tmp_path):
    svc = service(flown(**{f"GET /jobs/{JOB}/files/detections.mp4": [(200, Short(b"mp4" * 1000))]}))
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))
    assert code == 2 and "could not download detections.mp4" in err
    assert json.loads(lines[-1])["state"] == "done" and json.loads(lines[-1])["not_downloaded"] == ["detections.mp4"]
    assert sorted(saved(tmp_path)) == ["job.json", "result.json"]      # no half file, no *.part


def test_a_file_name_that_would_leave_the_folder_is_not_written(flight, capsys, service, tmp_path):
    job = ended()
    job["result"]["files"]["../evil.sh"] = f"/jobs/{JOB}/files/result.json"
    svc = service(flown(job))
    code, lines, _ = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path / "out"))
    assert code == 2 and json.loads(lines[-1])["not_downloaded"] == ["../evil.sh"]
    assert [p.name for p in tmp_path.iterdir()] == ["out"]


def test_missing_files_are_reported_in_the_services_words(flight, capsys, service, tmp_path):
    svc = service(flown(ended(files=("result.json",), missing=("detections.mp4", "meta.json"))))
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1", "--out", str(tmp_path))
    assert code == 0 and json.loads(lines[-1])["not_downloaded"] == []
    assert "missing detections.mp4" in err and "missing meta.json" in err
    assert svc.calls(f"GET /jobs/{JOB}/files/") == [f"GET /jobs/{JOB}/files/result.json"]


def test_watch_follows_a_job_that_is_already_there(flight, capsys, service, tmp_path):
    svc = service(flown())
    code, lines, _ = run(flight, capsys, svc.url, "watch", JOB, "--out", str(tmp_path))
    assert code == 0 and json.loads(lines[-1])["out_dir"] == str(tmp_path / JOB)
    assert svc.calls()[0] == f"GET /jobs/{JOB}/stream" and svc.calls("POST") == []


def test_watch_of_an_unknown_job(flight, capsys, service, tmp_path):
    svc = service({})
    code, lines, err = run(flight, capsys, svc.url, "watch", "j-nope", "--out", str(tmp_path / "out"))
    assert code == 2 and "HTTP 404" in err and "flight.py watch" not in err
    assert json.loads(lines[-1])["state"] is None and not (tmp_path / "out").exists()


def test_upload_sends_the_file_with_its_length(flight, capsys, service, tmp_path):
    """This fake ignores `Expect: 100-continue` (HTTP/1.0): the client waits
    EXPECT_WAIT_S, then sends anyway."""
    archive = tmp_path / "agent.tar"
    archive.write_bytes(os.urandom(300_000))
    svc = service(flown())
    code, _, err = run(flight, capsys, svc.url, "run", "--file", str(archive), "--kind", "image",
                       "--name", "truck", "--timeout", "120", "--out", str(tmp_path / "out"))
    assert code == 0 and "uploading" in err
    method, path, headers, body = svc.seen[1]
    assert (method, path) == ("POST", "/jobs?kind=image&name=truck&flight_timeout_s=120")
    assert headers["content-length"] == "300000" and headers["expect"] == "100-continue"
    assert "authorization" not in headers and body == archive.read_bytes()


def test_real_service_watch_replays_a_flown_job(flight, capsys, tmp_path, serve):
    """The whole path on real HTTP: chunked SSE, Last-Event-ID 0, file download."""
    from flight_service.jobs import DONE
    url, store, _ = real(tmp_path, serve)
    job = store.new("perkiepai/x:1", 600)
    run_dir = store.dir(job)
    (run_dir / "telemetry.jsonl").write_text("".join(
        json.dumps({"t": i, "lat": 14.0, "lon": 100.0, "alt_m": 20.0 + i, "mode": "OFFBOARD",
                    "agent": {"state": "running"}}) + "\n" for i in range(1, 501)))
    (run_dir / "result.json").write_text('{"ok": 1}')
    job.result = {"ended_by": "agent", "flight_s": 100.0, "score": {"version": "v0", "score": 88.0},
                  "files": {n: f"/jobs/{job.id}/files/{n}" for n in ("telemetry.jsonl", "result.json")},
                  "missing": ["detections.mp4"]}
    store.end(job, DONE)
    code, lines, err = run(flight, capsys, url, "watch", job.id, "--out", str(tmp_path / "out"))
    assert code == 0 and json.loads(lines[-1]) == {
        "job_id": job.id, "state": "done", "reason": None, "score": 88.0,
        "out_dir": str(tmp_path / "out" / job.id), "not_downloaded": []}
    assert err.count(" done alt=") == 500 and "missing detections.mp4" in err
    out = tmp_path / "out" / job.id
    assert (out / "telemetry.jsonl").read_bytes() == (run_dir / "telemetry.jsonl").read_bytes()
    assert json.loads((out / "job.json").read_text())["result"] == job.result


# --- the script as a process: signals, a terminal that is not UTF-8 ---------------

def spawn(svc, *argv, **env):
    return subprocess.Popen([sys.executable, str(SCRIPT), *argv], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            env={**os.environ, "FLIGHT_URL": svc.url, **env})


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_an_interrupted_client_leaves_the_job_alone(service, tmp_path, sig):
    svc = service(flown(**{f"GET /jobs/{JOB}/stream": [(200, [state("flying"), tele(1), HANG])]}))
    p = spawn(svc, "run", "perkiepai/x:1", "--out", str(tmp_path))
    err = ""
    while "flying alt=" not in err:                                  # it is following the flight now
        line = p.stderr.readline()
        assert line, f"the client ended early: {err}"
        err += line
    p.send_signal(sig)
    out, rest = p.communicate(timeout=10)
    err += rest
    assert p.returncode == 3
    assert json.loads(out.splitlines()[-1]) == {"job_id": JOB, "state": "flying", "reason": None,
                                                "score": None, "out_dir": None, "not_downloaded": []}
    assert "NOT killed" in err and f"flight.py watch {JOB}" in err and f"flight.py kill {JOB}" in err
    assert svc.calls("POST") == ["POST /jobs"]                       # no kill was sent


def test_a_terminal_that_is_not_utf8_does_not_break_the_client(service):
    svc = service({"GET /healthz": [(500, {"detail": "ดิสก์เต็ม"})]})
    p = spawn(svc, "health", PYTHONIOENCODING="ascii")
    out, err = p.communicate(timeout=10)
    assert p.returncode == 2 and "HTTP 500: \\u0e14" in err and "Traceback" not in err
