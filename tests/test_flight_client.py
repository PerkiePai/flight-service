"""scripts/flight.py against a scripted service on a real socket, and (the
tests that say so) against the real app."""
import ast
import importlib.util
import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "flight.py"
TOKEN = "k" * 40
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


def run(flight, capsys, url, *argv, token=TOKEN):
    """(exit code, stdout lines, stderr) of `flight.py --url .. --token .. <argv>`."""
    code = flight.main(["--url", url, "--token", token, *argv])
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
    assert run(flight, capsys, service({"GET /healthz": [(200, READY)]}).url, "health", token="") \
        == (0, [json.dumps(READY)], "")                         # no token needed
    code, out, _ = run(flight, capsys, service({"GET /healthz": [(200, BUSY)]}).url, "health")
    assert (code, json.loads(out[0])["ready"]) == (1, False)
    code, out, err = run(flight, capsys, closed_port(), "health")
    assert (code, out) == (2, []) and "cannot reach the service" in err


def test_everything_else_needs_a_token(flight, capsys, service):
    svc = service({})
    code, out, err = run(flight, capsys, svc.url, "kill", "j-1", token="")
    assert (code, out) == (2, []) and "RUNNER_TOKEN" in err and svc.seen == []


def test_url_and_token_come_from_the_environment(flight, capsys, service, monkeypatch):
    svc = service({"POST /jobs/j-1/kill": [(200, {"state": "killed", "reason": "killed"})]})
    monkeypatch.setenv("FLIGHT_URL", svc.url + "/")             # a trailing slash is harmless
    monkeypatch.setenv("RUNNER_TOKEN", TOKEN)
    assert flight.main(["kill", "j-1"]) == 0
    assert svc.seen[0][2]["authorization"] == f"Bearer {TOKEN}" and svc.calls() == ["POST /jobs/j-1/kill"]


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
    code, _, err = run(flight, capsys, svc.url, "kill", "j-5")
    assert code == 2 and "HTTP 401 (token wrong or missing): missing or wrong bearer token" in err


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
    from test_app import TOKEN as APP_TOKEN, make
    assert APP_TOKEN == TOKEN
    return make(tmp_path / "svc", serve, **settings)


def test_real_service_takes_an_upload(flight, tmp_path, serve):
    url, store, _ = real(tmp_path, serve, min_free_gb=0)
    archive = tmp_path / "agent.tar"
    archive.write_bytes(os.urandom(3_000_000))
    status, body = flight.Api(url, TOKEN).upload(str(archive), "kind=image&name=truck")
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
    api = flight.Api(url, TOKEN)
    status, body = api.upload(str(archive), "kind=image&name=truck")
    assert status == 413 and "file over" in body["detail"]
    assert sum(sent) < 2000 and store.all() == []                    # headers only
    (tmp_path / "small.tar").write_bytes(b"x" * 100)
    assert api.upload(str(tmp_path / "small.tar"), "kind=image&name=a")[0] == 202
    status, body = api.upload(str(tmp_path / "small.tar"), "kind=image&name=b")   # the slot is taken now
    assert status == 409 and body["detail"] == "busy"
