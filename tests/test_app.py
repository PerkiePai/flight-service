import asyncio

from conftest import http

from flight_service.app import create_app
from flight_service.config import Settings
from flight_service.jobs import KILLED, QUEUED, JobStore

TOKEN = "k" * 40


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
        return False

    def accepting(self):
        return self.phase != "degraded" and len(self.queued()) + self.receiving < self.max_pending

    def health(self):
        return {"ok": self.phase != "degraded", "ready": self.accepting(),
                "phase": self.phase, "pending": len(self.queued())}


def make(tmp_path, serve, **kw):
    s = Settings(token=TOKEN, drone_sitl_dir=tmp_path, runs_dir=tmp_path / "runs", **kw)
    store = JobStore(s.runs_dir)
    worker = StubWorker(store)
    return serve(create_app(s, store, worker)), store, worker


def submit(url, image="perkiepai/x:1", **extra):
    return http("POST", url + "/jobs", TOKEN, {"image": image, **extra})


def test_healthz_is_open_and_says_nothing_about_jobs(tmp_path, serve):
    url, _, worker = make(tmp_path, serve)
    assert http("GET", url + "/healthz") == (200, {"ok": True, "ready": True, "phase": "idle",
                                                  "pending": 0})
    assert worker.recovered


def test_everything_else_needs_the_token(tmp_path, serve):
    url, _, _ = make(tmp_path, serve)
    assert http("GET", url + "/jobs")[0] == 401
    assert http("GET", url + "/jobs", token="wrong" * 10)[0] == 401
    assert http("POST", url + "/jobs", body={"image": "perkiepai/x:1"})[0] == 401
    assert http("POST", url + "/jobs/x/kill")[0] == 401
    assert http("GET", url + "/jobs/x/files/result.json", raw=True)[0] == 401


def test_create_list_get(tmp_path, serve):
    url, store, worker = make(tmp_path, serve)
    code, body = submit(url)
    assert code == 202 and body["state"] == "queued" and body["source"] == "registry"
    assert worker.submitted == [body["job_id"]]
    code, listing = http("GET", url + "/jobs", TOKEN)
    assert code == 200 and [j["job_id"] for j in listing["jobs"]] == [body["job_id"]]
    assert "telemetry" not in listing["jobs"][0]
    code, job = http("GET", f"{url}/jobs/{body['job_id']}", TOKEN)
    assert code == 200 and job["flight_timeout_s"] == 600 and job["result"] is None
    assert http("GET", url + "/jobs/nope", TOKEN)[0] == 404


def test_create_rejections(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    assert submit(url, "postgres:15.4")[0] == 403
    assert submit(url, "perkiepai/x:1 ; ls")[0] == 400
    assert http("POST", url + "/jobs", TOKEN, {"nope": 1})[0] == 400
    assert http("POST", url + "/jobs", TOKEN, b"{not json")[0] == 400
    assert submit(url, flight_timeout_s=5000)[0] == 400
    assert submit(url, pad="x" * 5000)[0] == 413
    assert http("POST", url + "/jobs", TOKEN, b"data", ctype="text/plain")[0] == 415
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
    code, body = http("POST", f"{url}/jobs/{jid}/kill", TOKEN)
    assert code == 200 and body["state"] == "killed" and body["failed_in"] == "queued"
    assert http("POST", f"{url}/jobs/{jid}/kill", TOKEN)[0] == 409
    assert http("POST", url + "/jobs/nope/kill", TOKEN)[0] == 404
    assert http("GET", f"{url}/jobs/{jid}/kill", TOKEN)[0] in (404, 405)      # no GET kill


def test_files_are_served_by_name_only(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    jid = submit(url)[1]["job_id"]
    (store.dir(store.get(jid)) / "telemetry.jsonl").write_text('{"t": 0}\n')
    assert http("GET", f"{url}/jobs/{jid}/files/telemetry.jsonl", TOKEN, raw=True) == (200, b'{"t": 0}\n')
    for name in ("job.json", "panel.log", "..%2Fjob.json"):
        assert http("GET", f"{url}/jobs/{jid}/files/{name}", TOKEN, raw=True)[0] == 404


def test_a_journal_growing_during_download_arrives_whole(tmp_path, serve):
    """Journals are downloadable mid-flight (design 13.4): a file that grows
    while it is being sent must still match its own Content-Length."""
    import urllib.request
    url, store, _ = make(tmp_path, serve)
    jid = submit(url)[1]["job_id"]
    path = store.dir(store.get(jid)) / "telemetry.jsonl"
    original = b'{"t": 0}\n' * (32 * 1024 * 1024 // 9)             # ~32 MB, more than socket buffers
    path.write_bytes(original)
    req = urllib.request.Request(f"{url}/jobs/{jid}/files/telemetry.jsonl",
                                 headers={"Authorization": f"Bearer {TOKEN}"})
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
    return http("POST", f"{url}/jobs?{query}", TOKEN, data, ctype=ctype)


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
