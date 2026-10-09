import asyncio
import json
import threading
import urllib.request

from conftest import http, sse_events

from flight_service import stream
from flight_service.app import create_app
from flight_service.config import Settings
from flight_service.jobs import DONE, FLYING, KILLED, QUEUED, JobStore


class StubWorker:
    """Accepts jobs, never runs them."""

    def __init__(self, store):
        self.store, self.submitted, self.recovered = store, [], False
        self.current, self.phase, self.max_pending, self.receiving = None, "idle", 1, 0

    async def recover(self):
        self.recovered = True

    async def run_forever(self):
        await asyncio.Event().wait()

    def submit(self, job):
        self.submitted.append(job.id)

    def queued(self):
        return [j for j in self.store.all() if j.state == QUEUED]

    def kill(self, job):
        if job.state == QUEUED:
            self.store.end(job, KILLED, "killed", "killed while queued")
            return True
        if self.current is job:
            self.store.end(job, KILLED, "killed", "killed while flying")
            return True
        return False

    def accepting(self):
        return self.phase != "degraded" and len(self.queued()) + self.receiving < self.max_pending

    def health(self):
        return {"ok": self.phase != "degraded", "ready": self.accepting(),
                "phase": self.phase, "pending": len(self.queued())}


def make(tmp_path, serve, **kw):
    s = Settings(drone_sitl_dir=tmp_path, runs_dir=tmp_path / "runs", **kw)
    store = JobStore(s.runs_dir)
    worker = StubWorker(store)
    return serve(create_app(s, store, worker)), store, worker


def submit(url, image="perkiepai/x:1", **extra):
    return http("POST", url + "/jobs", {"image": image, **extra})


def test_healthz_is_open_and_says_nothing_about_jobs(tmp_path, serve):
    url, _, worker = make(tmp_path, serve)
    assert http("GET", url + "/healthz") == (200, {"ok": True, "ready": True, "phase": "idle",
                                                  "pending": 0})
    assert worker.recovered


def test_no_header_is_needed(tmp_path, serve):
    """Only insiders call this service (it binds 127.0.0.1): there is no login."""
    url, _, _ = make(tmp_path, serve)
    assert http("GET", url + "/jobs")[0] == 200
    assert http("POST", url + "/jobs", {"image": "perkiepai/x:1"})[0] == 202
    assert http("POST", url + "/jobs/x/kill")[0] == 404
    assert http("GET", url + "/jobs/x/files/result.json", raw=True)[0] == 404


def test_a_leftover_authorization_header_is_ignored(tmp_path, serve):
    """An old script that still sends its bearer token keeps working."""
    url, _, _ = make(tmp_path, serve)
    req = urllib.request.Request(url + "/jobs", headers={"Authorization": "Bearer old-token"})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200


def test_create_list_get(tmp_path, serve):
    url, store, worker = make(tmp_path, serve)
    code, body = submit(url)
    assert code == 202 and body["state"] == "queued" and body["source"] == "registry"
    assert worker.submitted == [body["job_id"]]
    code, listing = http("GET", url + "/jobs")
    assert code == 200 and [j["job_id"] for j in listing["jobs"]] == [body["job_id"]]
    assert "telemetry" not in listing["jobs"][0]
    code, job = http("GET", f"{url}/jobs/{body['job_id']}")
    assert code == 200 and job["flight_timeout_s"] == 600 and job["result"] is None
    assert http("GET", url + "/jobs/nope")[0] == 404


def test_create_rejections(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    assert submit(url, "postgres:15.4")[0] == 403
    assert submit(url, "perkiepai/x:1 ; ls")[0] == 400
    assert http("POST", url + "/jobs", {"nope": 1})[0] == 400
    assert http("POST", url + "/jobs", b"{not json")[0] == 400
    assert submit(url, flight_timeout_s=5000)[0] == 400
    assert submit(url, pad="x" * 5000)[0] == 413
    assert http("POST", url + "/jobs", b"data", ctype="text/plain")[0] == 415
    assert store.all() == []                               # no rejection created a job


def test_busy_and_degraded(tmp_path, serve):
    url, store, worker = make(tmp_path, serve)
    first = submit(url)[1]["job_id"]                       # takes the one pending slot
    code, body = submit(url, "perkiepai/y:1")
    assert code == 409 and body == {"detail": "busy", "current_job": None, "pending": [first]}
    assert http("GET", url + "/healthz")[1]["ready"] is False
    worker.phase = "degraded"
    assert submit(url, "perkiepai/z:1") == (503, {"detail": "degraded"})
    assert [j.id for j in store.all()] == [first]           # refusals created nothing


def test_kill(tmp_path, serve):
    url, _, _ = make(tmp_path, serve)
    jid = submit(url)[1]["job_id"]
    code, body = http("POST", f"{url}/jobs/{jid}/kill")
    assert code == 200 and body["state"] == "killed" and body["failed_in"] == "queued"
    assert http("POST", f"{url}/jobs/{jid}/kill")[0] == 409
    assert http("POST", url + "/jobs/nope/kill")[0] == 404
    assert http("GET", f"{url}/jobs/{jid}/kill")[0] in (404, 405)      # no GET kill


def start_flying(store, worker, jid):
    """What the worker does when it takes a job off the queue."""
    job = store.get(jid)
    worker.current = job
    store.set_state(job, FLYING)
    return job


def test_kill_without_an_id_stops_the_flying_job_and_leaves_the_queue_alone(tmp_path, serve):
    url, store, worker = make(tmp_path, serve)
    flying = submit(url)[1]["job_id"]
    start_flying(store, worker, flying)
    waiting = submit(url)[1]["job_id"]
    code, body = http("POST", url + "/kill")
    assert (code, body["job_id"], body["state"]) == (200, flying, "killed")
    assert store.get(waiting).state == QUEUED


def test_kill_without_an_id_stops_the_next_queued_job_when_nothing_flies(tmp_path, serve):
    url, store, worker = make(tmp_path, serve)
    worker.max_pending = 3
    first, second = submit(url)[1]["job_id"], submit(url)[1]["job_id"]
    code, body = http("POST", url + "/kill")
    assert (code, body["job_id"], body["state"]) == (200, first, "killed")
    assert store.get(second).state == QUEUED


def test_kill_without_an_id_with_nothing_to_kill(tmp_path, serve):
    url, store, worker = make(tmp_path, serve)
    assert http("POST", url + "/kill") == (409, {"detail": "no job to kill"})
    jid = submit(url)[1]["job_id"]
    http("POST", f"{url}/jobs/{jid}/kill")
    assert http("POST", url + "/kill")[0] == 409                 # the ended job is not a target
    start_flying(store, worker, submit(url)[1]["job_id"])
    store.end(worker.current, KILLED, "killed")                   # current job already over
    assert http("POST", url + "/kill")[0] == 409
    assert http("GET", url + "/kill")[0] == 405                   # no GET kill


def test_files_are_served_by_name_only(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    jid = submit(url)[1]["job_id"]
    (store.dir(store.get(jid)) / "telemetry.jsonl").write_text('{"t": 0}\n')
    assert http("GET", f"{url}/jobs/{jid}/files/telemetry.jsonl", raw=True) == (200, b'{"t": 0}\n')
    for name in ("job.json", "panel.log", "..%2Fjob.json"):
        assert http("GET", f"{url}/jobs/{jid}/files/{name}", raw=True)[0] == 404


def test_a_journal_growing_during_download_arrives_whole(tmp_path, serve):
    """Journals are downloadable mid-flight (design 13.4): a file that grows
    while it is being sent must still match its own Content-Length."""
    import urllib.request
    url, store, _ = make(tmp_path, serve)
    jid = submit(url)[1]["job_id"]
    path = store.dir(store.get(jid)) / "telemetry.jsonl"
    original = b'{"t": 0}\n' * (32 * 1024 * 1024 // 9)             # ~32 MB, more than socket buffers
    path.write_bytes(original)
    req = urllib.request.Request(f"{url}/jobs/{jid}/files/telemetry.jsonl")
    with urllib.request.urlopen(req, timeout=30) as r:
        declared = int(r.headers["Content-Length"])
        first = r.read(65536)
        with open(path, "ab") as f:                                  # the flight keeps writing
            f.write(b'{"t": 1}\n' * 200_000)
        body = first + r.read()
    assert declared == len(original) and body == original


def test_framework_doc_routes_are_not_served(tmp_path, serve):
    url, _, _ = make(tmp_path, serve)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert http("GET", url + path, raw=True)[0] == 404, path


def upload(url, data, query="kind=image&name=truck", ctype="application/octet-stream"):
    return http("POST", f"{url}/jobs?{query}", data, ctype=ctype)


def test_upload_creates_a_job_with_the_file(tmp_path, serve):
    url, store, worker = make(tmp_path, serve, min_free_gb=0)
    code, body = upload(url, b"x" * 1000)
    assert code == 202 and body["source"] == "upload"
    job = store.get(body["job_id"])
    assert (job.upload_kind, job.upload_name, job.image) == ("image", "truck", "upload:image:truck")
    assert (tmp_path / "uploads" / f"{job.id}.tar").read_bytes() == b"x" * 1000
    assert not (store.dir(job) / "upload.tar").exists()          # never inside runs/ (retention)
    assert worker.submitted == [job.id]
    assert [p.name for p in (tmp_path / "uploads").iterdir()] == [f"{job.id}.tar"]


def test_upload_rejections(tmp_path, serve):
    url, _, _ = make(tmp_path, serve, min_free_gb=0, max_upload_gb=1e-6)   # ~1 KB
    assert upload(url, b"x", "kind=zip&name=truck")[0] == 400
    assert upload(url, b"x", "kind=image&name=../evil")[0] == 400
    assert upload(url, b"x" * 2000)[0] == 413
    assert upload(url, b"x" * 10, "kind=bundle&name=t&flight_timeout_s=5")[0] == 400
    assert upload(url, b"x" * 10)[0] == 202
    assert upload(url, b"x" * 10, "kind=bundle&name=t2")[0] == 409      # slot taken: file refused
    assert len(list((tmp_path / "uploads").glob("*"))) == 1             # only the accepted one


def test_upload_needs_disk(tmp_path, serve):
    url, _, _ = make(tmp_path, serve, min_free_gb=10 ** 6)
    assert upload(url, b"x" * 10)[0] == 507


# --- GET /jobs/{id}/stream (design 3.1) --------------------------------------

RESULT = {"ended_by": "agent", "partial": False, "score": {"score": 95.6}, "files": {}, "missing": []}


def flown(store, lines=3):
    """A job that flew and ended, as the worker leaves it."""
    job = store.new("perkiepai/x:1", 600)
    (store.dir(job) / "telemetry.jsonl").write_text(
        "".join(json.dumps({"t": i, "alt_m": 10.0 + i}) + "\n" for i in range(1, lines + 1)))
    job.result = RESULT
    store.end(job, DONE)
    return job


def open_stream(url, jid, last_id=None):
    req = urllib.request.Request(f"{url}/jobs/{jid}/stream")
    if last_id is not None:
        req.add_header("Last-Event-ID", str(last_id))
    return urllib.request.urlopen(req, timeout=10)


def next_event(r):
    """The next (event, id, data) of an open stream, keepalives skipped."""
    block = b""
    while True:
        line = r.readline()
        assert line, "the stream closed"
        block += line
        if line == b"\n":
            got = [e for e in sse_events(block) if e[0] != "ping"]
            if got:
                return got[0]
            block = b""


def test_stream_needs_a_job(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    jid = flown(store).id
    assert http("GET", f"{url}/jobs/nope/stream") == (404, {"detail": "no such job"})
    assert http("POST", f"{url}/jobs/{jid}/stream")[0] == 405


def test_stream_of_a_finished_job_replays_it_and_closes(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    jid = flown(store).id
    with open_stream(url, jid) as r:
        assert r.status == 200
        assert r.headers["Content-Type"].startswith("text/event-stream")
        assert r.headers["Cache-Control"] == "no-cache" and r.headers["X-Accel-Buffering"] == "no"
        got = sse_events(r.read())                              # returns: the service closed the line
    assert [(e, i) for e, i, _ in got] == [("state", None), ("telemetry", 1), ("telemetry", 2),
                                          ("telemetry", 3), ("end", None)]
    assert got[0][2]["state"] == "done" and got[1][2] == {"t": 1, "alt_m": 11.0}
    assert got[-1][2] == {"job_id": jid, "state": "done", "failed_in": None, "reason": None,
                          "detail": "", "result": RESULT}


def test_stream_resumes_after_last_event_id(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    jid = flown(store).id

    def lines(last_id):
        with open_stream(url, jid, last_id) as r:
            return [i for e, i, _ in sse_events(r.read()) if e == "telemetry"]

    assert lines(2) == [3] and lines(3) == [] and lines(0) == [1, 2, 3]
    assert lines("abc") == [1, 2, 3] and lines(-5) == [1, 2, 3]    # not a line number: from the start


def test_stream_follows_a_job_while_it_runs(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    jid = submit(url)[1]["job_id"]
    job = store.get(jid)
    with open_stream(url, jid) as r:
        assert next_event(r)[::2] == ("state", {"state": "queued", "since": job.summary()["state_since"],
                                                "reason": None})
        store.set_state(job, FLYING)
        assert next_event(r)[2]["state"] == "flying"
        with open(store.dir(job) / "telemetry.jsonl", "a") as f:
            f.write('{"t": 1}\n{"t": 2')                        # the second line is still being written
            f.flush()
            assert next_event(r) == ("telemetry", 1, {"t": 1})
            f.write('}\n')
        assert next_event(r) == ("telemetry", 2, {"t": 2})
        store.end(job, KILLED, "killed", "killed while flying")
        assert next_event(r)[2] == {"state": "killed", "since": job.summary()["state_since"],
                                    "reason": "killed"}
        event, _, data = next_event(r)
        assert event == "end" and (data["state"], data["failed_in"], data["result"]) == ("killed", "flying", None)
        assert r.read() == b""                                  # nothing after end


def test_stream_stops_reading_when_the_client_goes_away(tmp_path, serve, monkeypatch):
    closed = threading.Event()
    close = stream.Tail.close
    monkeypatch.setattr(stream.Tail, "close", lambda self: (close(self), closed.set()))
    url, _, _ = make(tmp_path, serve)
    jid = submit(url)[1]["job_id"]                              # queued for ever: the stream never ends
    r = open_stream(url, jid)
    assert next_event(r)[0] == "state"
    r.close()
    assert closed.wait(5), "the journal stayed open after the client left"
