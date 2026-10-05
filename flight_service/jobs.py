"""A job's record: jobs live in memory, each one's snapshot is
data/runs/<id>/job.json (atomic replace on every change) so a restart can
tell what was in flight (design 5, 13.4)."""
import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .journal import write_atomic

QUEUED, PULLING, LOADING, BOOTING, FLYING = "queued", "pulling", "loading", "booting", "flying"
DONE, FAILED, KILLED = "done", "failed", "killed"
TERMINAL = (DONE, FAILED, KILLED)
RUNNING_MARK = "RUNNING"          # in a run's folder until finalize ran
# Everything GET /jobs/{id}/files/{name} may serve (design 13.4).
FILES = ("telemetry.jsonl", "events.jsonl", "detections.jsonl", "track.jsonl",
         "panel.log", "detections.mp4", "meta.json", "score.json", "result.json",
         "analysis.txt")


class JobFailed(Exception):
    """Raised by any pipeline step; the worker turns it into state failed."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts)) if ts else None


@dataclass
class Job:
    id: str
    image: str
    flight_timeout_s: int
    source: str = "registry"             # registry | upload
    upload_kind: str | None = None       # image | bundle (source upload)
    upload_name: str | None = None
    state: str = QUEUED
    created_at: float = field(default_factory=time.time)
    state_since: float = field(default_factory=time.time)
    failed_in: str | None = None
    reason: str | None = None
    detail: str | None = None
    image_tag: str | None = None          # submission-<stem>-<ts> on this box
    extra_tags: list = field(default_factory=list)   # names an uploaded archive brought in (proven new)
    image_preexisting: bool = True        # safe default: never rmi a ref we did not bring
    owns_sim: bool = False                # this job started drone-sitl's web/sim
    run_at: float | None = None           # wall time RUN was sent
    pull_started: float | None = None     # wall time the registry pull was asked for
    telemetry: dict | None = None
    log_tail: list = field(default_factory=list)
    score_live: dict | None = None
    result: dict | None = None

    def summary(self):
        return {"job_id": self.id, "state": self.state, "source": self.source,
                "image": self.image, "created_at": _iso(self.created_at),
                "state_since": _iso(self.state_since), "reason": self.reason}

    def public(self):
        return {**self.summary(), "upload_kind": self.upload_kind,
                "image_tag": self.image_tag, "flight_timeout_s": self.flight_timeout_s,
                "elapsed_s": round(time.time() - self.created_at, 1),
                "failed_in": self.failed_in, "detail": self.detail,
                "telemetry": self.telemetry, "log_tail": self.log_tail,
                "score_live": self.score_live, "result": self.result}


class JobStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs = {}

    def dir(self, job):
        return self.root / job.id

    def new(self, image, flight_timeout_s, source="registry", upload_kind=None,
            upload_name=None):
        jid = time.strftime("j-%Y%m%d-%H%M%S-") + secrets.token_hex(2)
        job = Job(jid, image, flight_timeout_s, source=source,
                  upload_kind=upload_kind, upload_name=upload_name)
        self.dir(job).mkdir(parents=True)
        self._jobs[jid] = job
        self.save(job)
        return job

    def get(self, jid):
        return self._jobs.get(jid)

    def all(self):
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def save(self, job):
        write_atomic(self.dir(job) / "job.json", asdict(job))

    def set_state(self, job, state):
        job.state, job.state_since = state, time.time()
        self.save(job)

    def end(self, job, state, reason=None, detail=""):
        if state != DONE and job.state not in TERMINAL:
            job.failed_in = job.state
        job.reason, job.detail = reason, detail
        self.set_state(job, state)

    def fail(self, job, reason, detail=""):
        self.end(job, FAILED, reason, detail)

    def forget(self, jid):
        self._jobs.pop(jid, None)

    def load(self):
        stale = []
        for path in sorted(self.root.glob("*/job.json")):
            try:
                job = Job(**json.loads(path.read_text()))
            except (OSError, ValueError, TypeError):
                continue
            self._jobs[job.id] = job
            if job.state not in TERMINAL:
                stale.append(job)
        return stale
