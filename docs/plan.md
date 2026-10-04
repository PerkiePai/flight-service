# flight-service Implementation Plan (v3 · 2026-10-05)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **วิธีลงมือที่เลือก: Native** (ทำเองใน session ตาม superpowers:executing-plans แล้วให้ reviewer ตรวจทั้ง branch รอบเดียวตอนจบ)
> **v3:** คิวหลักอยู่ที่ระบบพี่ต้น · worker มีช่องรอเล็ก `MAX_PENDING=1` ไว้กันจังหวะชน · `POST /jobs` เต็ม → `409` · degraded → `503` · state จบตั้ง**หลัง cleanup**

**Goal:** HTTP service ที่รับ docker image (ชื่อบน registry หรือไฟล์) ด้วย curl ครั้งเดียว → เตรียม image → บูต Isaac Sim + PX4 → บิน agent อัตโนมัติ → เขียนทุกข้อมูลเป็น journal ทันทีที่ได้ → จบทางไหนก็ได้ผลรูปแบบเดียว (รวม kill) → ลบ image/container ที่งานนำเข้ามา เก็บ data ย้อนหลัง 10 GB

**Architecture:** FastAPI ตัวเดียว (`flight_service/`) + worker ทำทีละงาน ทุกขั้นเรียก drone-sitl ผ่านของที่มีอยู่ (`sim/run-website.sh`, `sim/stop-website.sh`, HTTP `:8090`, WebSocket `/ws`, `import fly_headless` เฉพาะ `load_truth`/`analyze`) ไม่ copy โค้ด ข้อมูลทุกชนิดเขียนผ่าน `journal.py` (โมดูลกลางที่ไม่พึ่งอะไร) แล้ว `finalize.py` สร้างผลจาก journal บนดิสก์อย่างเดียว ทุก dependency ภายนอกส่งผ่าน constructor ให้เทสต์ใช้ของปลอมได้

**Tech Stack:** Python 3.11 (conda env `drone`), FastAPI 0.141, uvicorn 0.52, websockets 17, pydantic 2, pytest 9 · ไม่ติดตั้ง package เพิ่ม (ไม่มี httpx/pytest-asyncio → เทสต์ใช้ `asyncio.run` และ uvicorn จริงใน thread)

**Spec:** `docs/design.md` (หัวข้อ 3 = API ฉบับรวม, 12 = รับไฟล์, 13 = kill + journal)

## Global Constraints

- โฟลเดอร์: `~/pai/flight-service/` · drone-sitl ที่ `DRONE_SITL_DIR` (default `~/pai/drone-sitl`) · data ที่ `data/runs/<job_id>/`
- **ห้าม copy โค้ด drone-sitl** · แก้ drone-sitl ได้จุดเดียว: `DRONE_SITL_DOCKER_RUN_ARGS` (Task 11) commit บน branch ที่ checkout อยู่ + หลักฐานทั้งสองโปรเจกต์
- **ห้าม `pkill -f`** (ปิด sim ด้วย `stop-website.sh`) · **ห้าม `docker image prune`** · `rmi` เฉพาะสิ่งที่งานนั้นนำเข้ามา (ref ที่มีบนเครื่องก่อนเริ่มงานห้ามลบ)
- รันด้วย `conda run -n drone` · bind `127.0.0.1:8095`
- API มี 6 endpoint ตาม design 3 เท่านั้น: `POST /jobs` · `GET /jobs` · `GET /jobs/{id}` · `POST /jobs/{id}/kill` · `GET /jobs/{id}/files/{name}` · `GET /healthz`
- Token `RUNNER_TOKEN` ≥ 32 ตัวอักษร (ทุก endpoint ยกเว้น `/healthz`)
- Allowlist registry: `^(docker\.io/)?perkiepai/[a-z0-9][a-z0-9_.-]*(:\w[\w.-]{0,127}|@sha256:[0-9a-f]{64})$`
- Timeout: pull 1800 · manifest 30 · boot 420 · PX4 ready 180 · arming 90 · flight 600 (max 900) · collect 60 · cleanup 120 · kill wait 60 (วินาที)
- Limits: `MAX_IMAGE_GB=16` · `MIN_FREE_GB=40` · `MAX_PENDING=1` (งานรอได้ 1 งานหลังงานที่กำลังทำ) · JSON body ≤ 4 KB · `MAX_UPLOAD_GB=16` · bundle ≤ 200 MB · `DATA_RETENTION_GB=10`
- `DRONE_SITL_DOCKER_RUN_ARGS` default: `--memory 24g --memory-swap 24g --pids-limit 1024 --cap-drop ALL --security-opt no-new-privileges`
- States: `queued pulling loading booting flying done failed killed` · `queued` = อยู่ในช่องรอ
- รับงาน: degraded → `503` · ช่องรอเต็ม → `409 {"detail":"busy","current_job","pending"}` · `/healthz` = `{"ok","ready","phase","pending"}` (`ready` = POST ตอนนี้จะถูกรับ)
- **state จบ (`done`/`failed`/`killed`) ตั้งหลัง cleanup เสร็จ** = runner พร้อมแล้ว
- Journal: JSON Lines, flush ทุกบรรทัด, fsync ทุก ≤ 1 s · snapshot: write-temp + `os.replace`

## Review Focus

1. **runner ตายกลางบิน** → เปิดใหม่ต้อง finalize จาก journal (`partial`, `ended_by: runner_restarted`) + ปิด sim ที่ตัวเองเปิด แต่งานที่อยู่แค่ในคิวห้ามแตะ sim → Task 9 `test_recover_*`
2. **kill ซ้ำ / kill ระหว่าง finalize** → ต้องไม่ขัดจังหวะ finalize และ worker loop ต้องไม่ตาย → Task 9 `test_kill_twice_is_harmless`, `test_kill_while_flying_*`
3. **ยิง POST ตอนช่องรอเต็ม / ตอน degraded** → `409` / `503` และไม่สร้างงาน · ระบบพี่ต้นต้องเห็น state จบก็ต่อเมื่อ cleanup เสร็จ → Task 10 `test_busy_and_degraded`, Task 9 `test_state_ends_only_after_cleanup`
4. **ref ที่มีบนเครื่องอยู่แล้ว / tag ในไฟล์อัปโหลดชนของที่มี** → ห้ามลบ / ห้ามทับ → Task 9 `test_preexisting_image_is_not_removed`, B2 `test_archive_tag_that_exists_is_rejected`
5. **retention ลบงานที่เพิ่งจบหรือยังไม่จบ** → ห้าม: ลบเฉพาะงานที่จบแล้วและเก่าสุด → Task 8 `test_prune_*`, Task 9 `test_retention_keeps_the_run_just_finished`

---

## File Structure

```
flight-service/
├── pytest.ini · .gitignore · .env.example · README.md (Task 14)
├── flight_service/
│   ├── __main__.py      python -m flight_service
│   ├── config.py        Settings.from_env()
│   ├── journal.py       Journal, read_jsonl, write_atomic   ← โมดูลกลาง ไม่พึ่งอะไร
│   ├── jobs.py          Job, JobStore, JobFailed, states, FILES
│   ├── policy.py        check_ref, manifest_bytes, check_space
│   ├── dockerctl.py     sh(), tail(), Docker
│   ├── sim.py           SimControl, px4_ready, http_up
│   ├── sitl.py          Sitl (pull, detrec_status · B3: upload_bundle)
│   ├── runlog.py        RunLog: journals ของ 1 งาน, new_lines
│   ├── flightsession.py fly() ผ่าน /ws → Outcome
│   ├── score.py         ScoreV0, score_file, load_truth
│   ├── finalize.py      finalize(), wait_clip(), run_analysis()
│   ├── retention.py     prune()
│   ├── worker.py        Worker
│   ├── app.py           create_app()
│   ├── uploads.py       (B1) receive()
│   └── archive.py       (B2) repo_tags()
├── scripts/  run-service.sh · stop-service.sh · mock-caller.sh
├── tests/    conftest.py · fakes.py · test_<module>.py
├── docs/     design · plan · progress · drone-sitl-changes · verification
└── data/runs/<id>/ · data/uploads/ · logs/ · run/ · mock-out/      (runtime, ไม่เข้า git)
```

**Gate:** Task 1–12 = ขั้น 3 → หยุด · Task 13 = ขั้น 4 (บินจริง + kill จริง) → หยุด · Task 14 = ขั้น 5 → หยุด · ส่วน B (B1–B4) → หยุด

คำสั่งเทสต์: `cd ~/pai/flight-service && conda run -n drone python -m pytest -q <path>`

---

### Task 1: โครงโปรเจกต์ + config + journal

**Files:**
- Create: `pytest.ini`, `.gitignore`, `.env.example`, `flight_service/__init__.py`, `flight_service/config.py`, `flight_service/journal.py`
- Test: `tests/test_config.py`, `tests/test_journal.py`

**Interfaces:**
- Produces: `GB`, `DEFAULT_ALLOWED`, `DEFAULT_RUN_ARGS`, `Settings` (ฟิลด์ตามโค้ด + property `uploads_dir`), `Settings.from_env(env=None)`
- Produces: `Journal(path, fsync_every_s=1.0)` → `.append(record)`, `.close()`, `.count`, context manager · `read_jsonl(path)` (generator, ข้ามบรรทัดเสีย, ไฟล์ไม่มี = ว่าง) · `write_atomic(path, data)` (str/bytes/อื่น ๆ → JSON)

- [ ] **Step 1: git init + ไฟล์โครง**

```bash
cd ~/pai/flight-service && git init -q && mkdir -p flight_service tests scripts && touch flight_service/__init__.py
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
pythonpath = .
```

`.gitignore`:
```
data/
logs/
run/
mock-out/
.env
__pycache__/
```

`.env.example`:
```bash
# cp .env.example .env แล้วตั้ง RUNNER_TOKEN:  python3 -c 'import secrets;print(secrets.token_urlsafe(32))'
RUNNER_TOKEN=
DRONE_SITL_DIR=/home/innovation/pai/drone-sitl
RUNNER_HOST=127.0.0.1
RUNNER_PORT=8095
#RUNS_DIR=/home/innovation/pai/flight-service/data/runs
#ALLOWED_IMAGES=<regex คั่นด้วยช่องว่าง>
#DATA_RETENTION_GB=10
#KEEP_IMAGE=0
```

- [ ] **Step 2: เขียนเทสต์ที่ fail**

`tests/test_config.py`:
```python
import pytest

from flight_service.config import DEFAULT_ALLOWED, Settings

TOKEN = "t" * 32


def test_from_env_requires_a_long_token():
    with pytest.raises(SystemExit):
        Settings.from_env({"RUNNER_TOKEN": "short"})
    with pytest.raises(SystemExit):
        Settings.from_env({})


def test_from_env_defaults():
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN})
    assert (s.host, s.port) == ("127.0.0.1", 8095)
    assert s.allowed_images == (DEFAULT_ALLOWED,)
    assert s.runs_dir.parts[-2:] == ("data", "runs")
    assert s.uploads_dir.parts[-2:] == ("data", "uploads")
    assert (s.data_retention_gb, s.kill_wait_s, s.max_pending) == (10.0, 60.0, 1)
    assert (s.default_flight_s, s.max_flight_s) == (600, 900)
    assert "--cap-drop ALL" in s.docker_run_args and s.keep_image is False


def test_from_env_overrides(tmp_path):
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN, "DRONE_SITL_DIR": str(tmp_path),
                           "ALLOWED_IMAGES": "^a$ ^b$", "KEEP_IMAGE": "1",
                           "ARMING_TIMEOUT_S": "5", "DATA_RETENTION_GB": "0"})
    assert s.drone_sitl_dir == tmp_path and s.allowed_images == ("^a$", "^b$")
    assert s.keep_image is True and s.arming_timeout_s == 5.0 and s.data_retention_gb == 0.0
```

`tests/test_journal.py`:
```python
import json

from flight_service import journal
from flight_service.journal import Journal, read_jsonl, write_atomic


def test_append_is_readable_at_once(tmp_path):
    p = tmp_path / "a.jsonl"
    with Journal(p) as j:
        j.append({"n": 1})
        j.append({"n": 2, "s": "ไทย"})
        assert j.count == 2
        assert [r["n"] for r in read_jsonl(p)] == [1, 2]       # flushed, not yet closed
    assert list(read_jsonl(p))[1]["s"] == "ไทย"


def test_reopen_appends(tmp_path):
    p = tmp_path / "a.jsonl"
    with Journal(p) as j:
        j.append({"n": 1})
    with Journal(p) as j:
        j.append({"n": 2})
    assert [r["n"] for r in read_jsonl(p)] == [1, 2]


def test_torn_last_line_and_missing_file(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"n": 1}\n{"n": 2, "tr')
    assert [r["n"] for r in read_jsonl(p)] == [1]
    assert list(read_jsonl(tmp_path / "none.jsonl")) == []


def test_fsync_is_rate_limited(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(journal.os, "fsync", lambda fd: calls.append(fd))
    j = Journal(tmp_path / "a.jsonl", fsync_every_s=3600)
    for i in range(100):
        j.append({"i": i})
    assert calls == []
    j.close()
    assert len(calls) == 1
    j2 = Journal(tmp_path / "b.jsonl", fsync_every_s=0)
    j2.append({})
    assert len(calls) == 2
    j2.close()


def test_write_atomic(tmp_path):
    p = tmp_path / "s.json"
    write_atomic(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    write_atomic(p, "text\n")
    assert p.read_text() == "text\n"
    write_atomic(p, b"\x00\x01")
    assert p.read_bytes() == b"\x00\x01"
    assert [x.name for x in tmp_path.iterdir()] == ["s.json"]
```

- [ ] **Step 3: รันให้เห็นว่า fail** — `conda run -n drone python -m pytest -q tests/test_config.py tests/test_journal.py` → FAIL `No module named 'flight_service.config'`

- [ ] **Step 4: เขียนโค้ด**

`flight_service/config.py`:
```python
"""Settings from the environment -- one place for every limit and timeout
(design sections 6, 8, 12, 13)."""
import os
from dataclasses import dataclass
from pathlib import Path

GB = 1024 ** 3

DEFAULT_ALLOWED = (r"^(docker\.io/)?perkiepai/[a-z0-9][a-z0-9_.-]*"
                   r"(:\w[\w.-]{0,127}|@sha256:[0-9a-f]{64})$")
DEFAULT_RUN_ARGS = ("--memory 24g --memory-swap 24g --pids-limit 1024 "
                    "--cap-drop ALL --security-opt no-new-privileges")
HERE = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    token: str
    drone_sitl_dir: Path
    runs_dir: Path
    host: str = "127.0.0.1"
    port: int = 8095
    allowed_images: tuple = (DEFAULT_ALLOWED,)
    max_image_gb: float = 16.0
    min_free_gb: float = 40.0
    docker_root: Path = Path("/var/lib/docker")
    max_pending: int = 1          # jobs waiting behind the running one (design 5)
    max_upload_gb: float = 16.0
    data_retention_gb: float = 10.0
    pull_timeout_s: float = 1800.0
    manifest_timeout_s: float = 30.0
    boot_timeout_s: float = 420.0
    px4_ready_timeout_s: float = 180.0
    arming_timeout_s: float = 90.0
    default_flight_s: int = 600
    max_flight_s: int = 900
    collect_timeout_s: float = 60.0
    cleanup_timeout_s: float = 120.0
    kill_wait_s: float = 60.0
    web_url: str = "http://127.0.0.1:8090"
    ws_url: str = "ws://127.0.0.1:8090/ws"
    video_url: str = "http://127.0.0.1:8080/"
    docker_run_args: str = DEFAULT_RUN_ARGS
    keep_image: bool = False
    site: str = "nt-testgs"

    @property
    def uploads_dir(self):
        return self.runs_dir.parent / "uploads"

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        token = env.get("RUNNER_TOKEN", "")
        if len(token) < 32:
            raise SystemExit("RUNNER_TOKEN must be set and at least 32 characters")

        def num(name, default, kind=float):
            return kind(env.get(name, default))

        return cls(
            token=token,
            drone_sitl_dir=Path(env.get("DRONE_SITL_DIR", Path.home() / "pai" / "drone-sitl")),
            runs_dir=Path(env.get("RUNS_DIR", HERE / "data" / "runs")),
            host=env.get("RUNNER_HOST", "127.0.0.1"),
            port=num("RUNNER_PORT", 8095, int),
            allowed_images=tuple(env.get("ALLOWED_IMAGES", DEFAULT_ALLOWED).split()),
            max_image_gb=num("MAX_IMAGE_GB", 16.0),
            min_free_gb=num("MIN_FREE_GB", 40.0),
            docker_root=Path(env.get("DOCKER_ROOT", "/var/lib/docker")),
            max_pending=num("MAX_PENDING", 1, int),
            max_upload_gb=num("MAX_UPLOAD_GB", 16.0),
            data_retention_gb=num("DATA_RETENTION_GB", 10.0),
            pull_timeout_s=num("PULL_TIMEOUT_S", 1800.0),
            manifest_timeout_s=num("MANIFEST_TIMEOUT_S", 30.0),
            boot_timeout_s=num("BOOT_TIMEOUT_S", 420.0),
            px4_ready_timeout_s=num("PX4_READY_TIMEOUT_S", 180.0),
            arming_timeout_s=num("ARMING_TIMEOUT_S", 90.0),
            default_flight_s=num("DEFAULT_FLIGHT_S", 600, int),
            max_flight_s=num("MAX_FLIGHT_S", 900, int),
            collect_timeout_s=num("COLLECT_TIMEOUT_S", 60.0),
            cleanup_timeout_s=num("CLEANUP_TIMEOUT_S", 120.0),
            kill_wait_s=num("KILL_WAIT_S", 60.0),
            docker_run_args=env.get("DRONE_SITL_DOCKER_RUN_ARGS", DEFAULT_RUN_ARGS),
            keep_image=env.get("KEEP_IMAGE", "0") == "1",
            site=env.get("SITE", "nt-testgs"),
        )
```

`flight_service/journal.py`:
```python
"""Crash-safe files for data that arrives over time (design 13.2-13.3).
No dependency on the rest of flight-service: copy it anywhere.

  Journal       append-only JSON Lines. Each record is one line, flushed at
                once; fsync'd at most every `fsync_every_s`. A crash loses
                at most a torn last line.
  read_jsonl    reads one back, skipping lines that do not parse.
  write_atomic  replaces a whole file (snapshot) so no reader ever sees
                half of it: write a temp file, fsync, os.replace.
"""
import json
import os
import time
from pathlib import Path


class Journal:
    def __init__(self, path, fsync_every_s=1.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fsync_every_s = fsync_every_s
        self._f = open(self.path, "a", encoding="utf-8")
        self._synced = time.monotonic()
        self.count = 0

    def append(self, record):
        self._f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._f.flush()
        self.count += 1
        if time.monotonic() - self._synced >= self.fsync_every_s:
            os.fsync(self._f.fileno())
            self._synced = time.monotonic()

    def close(self):
        if not self._f.closed:
            self._f.flush()
            os.fsync(self._f.fileno())
            self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def read_jsonl(path):
    try:
        f = open(path, encoding="utf-8")
    except FileNotFoundError:
        return
    with f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def write_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        payload = data
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    else:
        payload = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
```

- [ ] **Step 5: รันให้ผ่าน** — Expected: `8 passed`

- [ ] **Step 6: Commit**

```bash
git add pytest.ini .gitignore .env.example flight_service tests docs
git commit -m "feat: settings and a crash-safe journal module"
```

---

### Task 2: jobs (Job, JobStore)

**Files:** Create `flight_service/jobs.py` · Test `tests/test_jobs.py`

**Interfaces:**
- Consumes: `write_atomic`
- Produces: `QUEUED PULLING LOADING BOOTING FLYING DONE FAILED KILLED TERMINAL RUNNING_MARK FILES`, `JobFailed(reason, detail)`
- Produces: `Job` + `.summary()` (สำหรับ `GET /jobs`) + `.public()` (สำหรับ `GET /jobs/{id}`) · `JobStore(root)` → `.new(image, flight_timeout_s, source="registry", upload_kind=None, upload_name=None)`, `.get(id)`, `.all()` (ใหม่สุดก่อน), `.dir(job)`, `.save(job)`, `.set_state(job, state)`, `.end(job, state, reason=None, detail="")`, `.fail(job, reason, detail="")`, `.forget(id)`, `.load() -> list[Job]` (ที่ยังไม่จบ)

- [ ] **Step 1: เขียนเทสต์ที่ fail**

`tests/test_jobs.py`:
```python
import json

from flight_service.jobs import (DONE, FAILED, FLYING, KILLED, PULLING, QUEUED,
                                 JobStore)


def test_new_job_is_queued_and_written(tmp_path):
    store = JobStore(tmp_path)
    job = store.new("perkiepai/x:1", 600)
    assert job.state == QUEUED and job.source == "registry"
    assert json.loads((tmp_path / job.id / "job.json").read_text())["image"] == "perkiepai/x:1"
    assert store.get(job.id) is job and not list(tmp_path.glob(f"{job.id}/.*.tmp"))


def test_upload_fields(tmp_path):
    job = JobStore(tmp_path).new("upload:image:truck", 600, source="upload",
                                 upload_kind="image", upload_name="truck")
    assert (job.source, job.upload_kind, job.upload_name) == ("upload", "image", "truck")


def test_fail_and_kill_record_where_and_why(tmp_path):
    store = JobStore(tmp_path)
    a = store.new("perkiepai/a:1", 600)
    store.set_state(a, PULLING)
    store.fail(a, "pull_failed", "no such image")
    assert (a.state, a.failed_in, a.reason, a.detail) == (FAILED, PULLING, "pull_failed", "no such image")
    b = store.new("perkiepai/b:1", 600)
    store.set_state(b, FLYING)
    store.end(b, KILLED, "killed", "killed while flying")
    assert (b.state, b.failed_in) == (KILLED, FLYING)
    c = store.new("perkiepai/c:1", 600)
    store.end(c, DONE)
    assert (c.state, c.failed_in, c.reason) == (DONE, None, None)
    assert b.public()["reason"] == "killed" and "telemetry" not in b.summary()


def test_load_returns_only_unfinished_and_skips_corrupt(tmp_path):
    store = JobStore(tmp_path)
    a, b, c = (store.new(f"perkiepai/{n}:1", 600) for n in "abc")
    store.set_state(a, FLYING)
    store.end(b, DONE)
    (tmp_path / c.id / "job.json").write_text("{not json")
    fresh = JobStore(tmp_path)
    assert [j.id for j in fresh.load()] == [a.id]
    assert fresh.get(b.id).state == DONE and fresh.get(c.id) is None


def test_forget(tmp_path):
    store = JobStore(tmp_path)
    job = store.new("perkiepai/x:1", 600)
    store.forget(job.id)
    assert store.get(job.id) is None and store.all() == []
```

- [ ] **Step 2: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.jobs'`

- [ ] **Step 3: เขียนโค้ด**

`flight_service/jobs.py`:
```python
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
    image_preexisting: bool = True        # safe default: never rmi a ref we did not bring
    owns_sim: bool = False                # this job started drone-sitl's web/sim
    run_at: float | None = None           # wall time RUN was sent
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
```

- [ ] **Step 4: รันให้ผ่าน** — Expected: `5 passed`
- [ ] **Step 5: Commit** — `git add flight_service/jobs.py tests/test_jobs.py && git commit -m "feat: job record and store"`

---

### Task 3: policy

**Files:** Create `flight_service/policy.py` · Test `tests/test_policy.py`

**Interfaces:**
- Produces: `check_ref(ref, patterns) -> None | (status, message)` · `manifest_bytes(text, arch="amd64") -> int|None` · `check_space(free_bytes, image_bytes, min_free_gb, max_image_gb)` → raise `JobFailed("image_too_large"|"disk_low")`

- [ ] **Step 1: เขียนเทสต์ที่ fail**

`tests/test_policy.py`:
```python
import json

import pytest

from flight_service.config import DEFAULT_ALLOWED, GB
from flight_service.jobs import JobFailed
from flight_service.policy import check_ref, check_space, manifest_bytes

P = (DEFAULT_ALLOWED,)


@pytest.mark.parametrize("ref", ["perkiepai/truck-detector:20260929-214240",
                                 "docker.io/perkiepai/truck-detector:latest",
                                 "perkiepai/x@sha256:" + "a" * 64])
def test_allowed_refs(ref):
    assert check_ref(ref, P) is None


@pytest.mark.parametrize("ref", ["submission-truck-detector-20260929-214240",
                                 "competition-base:latest", "postgres:15.4",
                                 "evil.io/perkiepai/x:1", "perkiepai/x:1;rm", "perkiepai/X:1"])
def test_refs_off_the_allowlist_are_403(ref):
    assert check_ref(ref, P)[0] == 403


@pytest.mark.parametrize("ref", ["", " perkiepai/x:1", "perkiepai/x:1\n", "a" * 513, None])
def test_malformed_refs_are_400(ref):
    assert check_ref(ref, P)[0] == 400


def test_manifest_bytes_single_and_multi_platform():
    assert manifest_bytes(json.dumps({"SchemaV2Manifest": {"layers": [{"size": 10}, {"size": 5}]}})) == 15
    multi = [{"Descriptor": {"platform": {"os": "linux", "architecture": "arm64"}},
              "OCIManifest": {"layers": [{"size": 999}]}},
             {"Descriptor": {"platform": {"os": "linux", "architecture": "amd64"}},
              "OCIManifest": {"layers": [{"size": 7}]}}]
    assert manifest_bytes(json.dumps(multi)) == 7
    assert manifest_bytes("not json") is None and manifest_bytes("{}") is None


def test_check_space():
    check_space(100 * GB, 12 * GB, min_free_gb=40, max_image_gb=16)
    check_space(100 * GB, None, min_free_gb=40, max_image_gb=16)
    for free, img, min_free, why in [(100 * GB, 17 * GB, 40, "image_too_large"),
                                     (30 * GB, 1 * GB, 40, "disk_low"),     # under MIN_FREE_GB
                                     (25 * GB, 15 * GB, 20, "disk_low")]:   # under 2x the image
        with pytest.raises(JobFailed) as e:
            check_space(free, img, min_free, 16)
        assert e.value.reason == why
    check_space(50 * GB, 15 * GB, 40, 16)       # 50 >= max(40, 2 x 15)
```

- [ ] **Step 2: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.policy'`

- [ ] **Step 3: เขียนโค้ด**

`flight_service/policy.py`:
```python
"""What the runner agrees to run: which image refs, how big, how much
disk must stay free (design 8)."""
import json
import re

from .config import GB
from .jobs import JobFailed


def check_ref(ref, patterns):
    """None if `ref` may be pulled, else (http status, why not)."""
    if (not isinstance(ref, str) or not ref or len(ref) > 512
            or any(c.isspace() for c in ref)):
        return 400, "image must be a single-line image reference"
    if not any(re.fullmatch(p, ref) for p in patterns):
        return 403, "image is not on the allowlist"
    return None


def manifest_bytes(text, arch="amd64"):
    """Compressed size from `docker manifest inspect -v` for linux/<arch>."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    for entry in data if isinstance(data, list) else [data]:
        if not isinstance(entry, dict):
            continue
        plat = (entry.get("Descriptor") or {}).get("platform") or {}
        if plat and (plat.get("os"), plat.get("architecture")) != ("linux", arch):
            continue
        layers = (entry.get("OCIManifest") or entry.get("SchemaV2Manifest") or {}).get("layers")
        if layers:
            return sum(int(layer.get("size", 0)) for layer in layers)
    return None


def check_space(free_bytes, image_bytes, min_free_gb, max_image_gb):
    if image_bytes is not None and image_bytes > max_image_gb * GB:
        raise JobFailed("image_too_large", f"{image_bytes / GB:.1f} GB > {max_image_gb:g} GB")
    need = max(min_free_gb * GB, 2 * (image_bytes or 0))
    if free_bytes < need:
        raise JobFailed("disk_low", f"{free_bytes / GB:.0f} GB free, need {need / GB:.0f} GB")
```

- [ ] **Step 4: รันให้ผ่าน** — Expected: `16 passed`
- [ ] **Step 5: Commit** — `git add flight_service/policy.py tests/test_policy.py && git commit -m "feat: image allowlist, size and disk checks"`

---

### Task 4: dockerctl + sim

**Files:** Create `flight_service/dockerctl.py`, `flight_service/sim.py` · Test `tests/test_dockerctl.py`, `tests/test_sim.py`

**Interfaces:**
- Produces: `async sh(*argv, timeout=60.0, env=None, cwd=None) -> (code, out)` (124 = timeout, child ถูก kill เมื่อ timeout/cancel) · `tail(text, n=8)`
- Produces: `Docker(run=sh)` → `exists(ref)`, `manifest_bytes(ref, timeout)`, `size(ref)`, `containers_of(tag)`, `rm_force(name)`, `rmi(ref)` (async ทั้งหมด)
- Produces: `READY_LINE`, `http_up(url, timeout=3.0)`, `px4_ready(console, since)`, `SimControl(settings, run=sh, up=http_up)` → async `busy()`, `start_web()`, `start_sim()`, `wait_px4_ready(since, poll=2.0)`, `stop() -> bool`

- [ ] **Step 1: เขียนเทสต์ที่ fail**

`tests/test_dockerctl.py`:
```python
import asyncio
import json

from flight_service.dockerctl import Docker, sh


class Rec:
    """Fake `run`: records argv, answers keyed by argv[1:3]."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def __call__(self, *argv, **kw):
        self.calls.append(list(argv))
        return self.answers.get(tuple(argv[1:3]), (0, ""))


def test_sh_returns_code_and_output_and_times_out():
    assert asyncio.run(sh("sh", "-c", "echo hi; exit 3")) == (3, "hi\n")
    code, out = asyncio.run(sh("sleep", "5", timeout=0.2))
    assert code == 124 and "timed out" in out


def test_docker_wrappers_name_exactly_one_thing():
    run = Rec({("image", "inspect"): (0, "12345\n"),
               ("ps", "-a"): (0, "submission-run-1\nsubmission-run-2\n"),
               ("manifest", "inspect"): (0, json.dumps({"SchemaV2Manifest": {"layers": [{"size": 3}]}}))})
    d = Docker(run)
    assert asyncio.run(d.exists("perkiepai/x:1")) is True
    assert asyncio.run(d.size("submission-x-1")) == 12345
    assert asyncio.run(d.containers_of("submission-x-1")) == ["submission-run-1", "submission-run-2"]
    assert asyncio.run(d.manifest_bytes("perkiepai/x:1", 5)) == 3
    asyncio.run(d.rmi("submission-x-1"))
    assert ["docker", "rmi", "submission-x-1"] in run.calls
    assert ["docker", "ps", "-a", "--filter", "ancestor=submission-x-1", "--format", "{{.Names}}"] in run.calls
    assert not any("prune" in c for call in run.calls for c in call)


def test_docker_failures_read_as_absent():
    d = Docker(Rec({("image", "inspect"): (1, "No such image"), ("manifest", "inspect"): (124, "timed out")}))
    assert asyncio.run(d.exists("perkiepai/x:1")) is False
    assert asyncio.run(d.size("perkiepai/x:1")) is None
    assert asyncio.run(d.manifest_bytes("perkiepai/x:1", 5)) is None
```

`tests/test_sim.py`:
```python
import asyncio
import os
import time

import pytest

from flight_service.config import Settings
from flight_service.jobs import JobFailed
from flight_service.sim import SimControl, px4_ready


def settings(tmp_path, **kw):
    return Settings(token="t" * 32, drone_sitl_dir=tmp_path, runs_dir=tmp_path / "runs",
                    px4_ready_timeout_s=0.3, **kw)


class Runs:
    def __init__(self):
        self.calls = []

    async def __call__(self, *argv, timeout=60.0, env=None, cwd=None):
        self.calls.append((argv, env or {}))
        return 0, "ok"


def test_px4_ready_needs_the_line_and_a_fresh_file(tmp_path):
    console = tmp_path / "launch-sitl.console"
    assert px4_ready(console, 0) is False
    console.write_text("INFO [commander] \x1b[32mReady for takeoff!\x1b[0m\n")
    old = time.time() - 600
    os.utime(console, (old, old))
    assert px4_ready(console, time.time() - 60) is False          # last boot's file
    console.write_text("booting...\n")
    assert px4_ready(console, time.time() - 60) is False
    console.write_text("INFO [commander] \x1b[32mReady for takeoff!\x1b[0m\n")
    assert px4_ready(console, time.time() - 60) is True


def test_start_web_passes_skip_sim_and_run_args(tmp_path):
    run = Runs()
    asyncio.run(SimControl(settings(tmp_path), run=run, up=lambda u, timeout=3.0: True).start_web())
    argv, env = run.calls[0]
    assert argv[0].endswith("sim/run-website.sh") and env["SKIP_SIM"] == "1"
    assert "--cap-drop ALL" in env["DRONE_SITL_DOCKER_RUN_ARGS"]


def test_start_sim_fails_when_camera_never_answers(tmp_path):
    with pytest.raises(JobFailed) as e:
        asyncio.run(SimControl(settings(tmp_path), run=Runs(), up=lambda u, timeout=3.0: False).start_sim())
    assert e.value.reason == "sim_boot_timeout"


def test_wait_px4_ready_times_out(tmp_path):
    sim = SimControl(settings(tmp_path), run=Runs(), up=lambda u, timeout=3.0: True)
    with pytest.raises(JobFailed) as e:
        asyncio.run(sim.wait_px4_ready(time.time(), poll=0.05))
    assert e.value.reason == "px4_not_ready"


def test_busy_and_stop(tmp_path):
    up, run = {"v": True}, Runs()
    sim = SimControl(settings(tmp_path), run=run, up=lambda u, timeout=3.0: up["v"])
    assert asyncio.run(sim.busy()) is True
    up["v"] = False
    assert asyncio.run(sim.stop()) is True
    assert run.calls[-1][0][0].endswith("sim/stop-website.sh")
```

- [ ] **Step 2: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.dockerctl'`

- [ ] **Step 3: เขียนโค้ด**

`flight_service/dockerctl.py`:
```python
"""The docker CLI, only for what the runner itself must do (pull and
bundle builds go through drone-sitl's :8090). Never `prune`, never a
pattern: every call names one image or one container (trap 6)."""
import asyncio

from . import policy


async def sh(*argv, timeout=60.0, env=None, cwd=None):
    """Run argv; (exit code, combined output). 124 on timeout. The child is
    killed if we time out or are cancelled."""
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env=env, cwd=cwd)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        return 124, f"timed out after {timeout:.0f}s"
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return proc.returncode, out.decode(errors="replace")


def tail(text, n=8):
    return "\n".join((text or "").strip().splitlines()[-n:])


class Docker:
    def __init__(self, run=sh):
        self.run = run

    async def exists(self, ref):
        code, _ = await self.run("docker", "image", "inspect", ref, timeout=30)
        return code == 0

    async def manifest_bytes(self, ref, timeout):
        code, out = await self.run("docker", "manifest", "inspect", "-v", ref, timeout=timeout)
        return policy.manifest_bytes(out) if code == 0 else None

    async def size(self, ref):
        code, out = await self.run("docker", "image", "inspect", "--format", "{{.Size}}", ref, timeout=30)
        try:
            return int(out.strip()) if code == 0 else None
        except ValueError:
            return None

    async def containers_of(self, image_tag):
        code, out = await self.run("docker", "ps", "-a", "--filter", f"ancestor={image_tag}",
                                   "--format", "{{.Names}}", timeout=30)
        return out.split() if code == 0 else []

    async def rm_force(self, name):
        await self.run("docker", "rm", "-f", name, timeout=30)

    async def rmi(self, ref):
        code, _ = await self.run("docker", "rmi", ref, timeout=120)
        return code == 0
```

`flight_service/sim.py`:
```python
"""Isaac Sim + PX4 + drone-sitl's :8090 web server, driven only through
drone-sitl's own scripts. Never pkill: stop-website.sh matches drone-sitl's
process signatures (trap 5)."""
import asyncio
import os
import time

from .dockerctl import sh, tail
from .jobs import JobFailed

READY_LINE = "Ready for takeoff"


def http_up(url, timeout=3.0):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:            # noqa: BLE001 -- any failure means "not up"
        return False


def px4_ready(console, since):
    """True once `console` was (re)written after `since` and holds READY_LINE
    (trap 1: RUN before it = PX4 refuses arm and AgentRun never retries).
    The mtime check keeps the previous boot's file from counting."""
    try:
        if os.stat(console).st_mtime < since:
            return False
        with open(console, errors="replace") as f:
            return READY_LINE in f.read()
    except OSError:
        return False


class SimControl:
    def __init__(self, settings, run=sh, up=http_up):
        self.s, self.run, self.up = settings, run, up
        self.dir = settings.drone_sitl_dir
        self.console = self.dir / "logs" / "launch-sitl.console"

    def _env(self, **extra):
        return {**os.environ, "DRONE_SITL_DOCKER_RUN_ARGS": self.s.docker_run_args, **extra}

    async def _up(self, url):
        return await asyncio.to_thread(self.up, url)

    async def busy(self):
        return await self._up(self.s.video_url) or await self._up(self.s.web_url + "/")

    async def start_web(self):
        """Only the :8090 server (SKIP_SIM=1): enough for pull/build."""
        _, out = await self.run(str(self.dir / "sim" / "run-website.sh"), timeout=90,
                                env=self._env(SKIP_SIM="1"), cwd=str(self.dir))
        if not await self._up(self.s.web_url + "/"):
            raise JobFailed("web_start_failed", tail(out))

    async def start_sim(self):
        """Isaac + PX4 (+ the web server if it is not up yet)."""
        wait = int(self.s.boot_timeout_s)
        await self.run(str(self.dir / "sim" / "run-website.sh"), timeout=wait + 60,
                       env=self._env(ISAAC_WAIT_S=str(wait)), cwd=str(self.dir))
        if not await self._up(self.s.video_url):
            raise JobFailed("sim_boot_timeout",
                            f"camera server {self.s.video_url} not up after {wait}s; see {self.console}")

    async def wait_px4_ready(self, since, poll=2.0):
        deadline = time.monotonic() + self.s.px4_ready_timeout_s
        while time.monotonic() < deadline:
            if px4_ready(self.console, since):
                return
            await asyncio.sleep(poll)
        raise JobFailed("px4_not_ready", f"no '{READY_LINE}' in {self.console} after "
                                         f"{self.s.px4_ready_timeout_s:.0f}s")

    async def stop(self):
        """stop-website.sh; True once :8080 and :8090 no longer answer."""
        await self.run(str(self.dir / "sim" / "stop-website.sh"), timeout=self.s.cleanup_timeout_s,
                       env=self._env(), cwd=str(self.dir))
        return not await self.busy()
```

- [ ] **Step 4: รันให้ผ่าน** — Expected: `8 passed`
- [ ] **Step 5: Commit** — `git add flight_service/dockerctl.py flight_service/sim.py tests/test_dockerctl.py tests/test_sim.py && git commit -m "feat: docker CLI wrapper and sim control via drone-sitl scripts"`

---

### Task 5: sitl (HTTP :8090)

**Files:** Create `flight_service/sitl.py` · Test `tests/test_sitl.py`

**Interfaces:**
- Produces: `_open(req, timeout) -> (status|None, dict)`, `_call(method, url, timeout)`, `_fail(reason, code, body)` · `Sitl(web_url, call=_call)` → async `pull(ref, timeout) -> tag` (raise `pull_failed`), async `detrec_status() -> dict|None`

- [ ] **Step 1: เขียนเทสต์ที่ fail**

`tests/test_sitl.py`:
```python
import asyncio

import pytest

from flight_service.jobs import JobFailed
from flight_service.sitl import Sitl


def test_pull_quotes_the_ref_and_returns_the_tag():
    seen = []

    def call(method, url, timeout):
        seen.append((method, url, timeout))
        return 200, {"image_tag": "submission-truck-detector-20261005-120000"}

    assert asyncio.run(Sitl("http://w", call).pull("perkiepai/truck-detector:1", 99)) == \
        "submission-truck-detector-20261005-120000"
    assert seen == [("POST", "http://w/agent/pull-docker?ref=perkiepai%2Ftruck-detector%3A1", 99)]


def test_pull_failure_carries_the_log_tail():
    with pytest.raises(JobFailed) as e:
        asyncio.run(Sitl("http://w", lambda m, u, t: (400, {"detail": "pull failed",
                                                             "log": ["a", "manifest unknown"]})).pull("perkiepai/x:1", 5))
    assert e.value.reason == "pull_failed" and "manifest unknown" in e.value.detail


def test_detrec_status():
    assert asyncio.run(Sitl("http://w", lambda m, u, t: (200, {"on": False})).detrec_status()) == {"on": False}
    assert asyncio.run(Sitl("http://w", lambda m, u, t: (None, {})).detrec_status()) is None
```

- [ ] **Step 2: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.sitl'`

- [ ] **Step 3: เขียนโค้ด**

`flight_service/sitl.py`:
```python
"""drone-sitl's :8090 HTTP endpoints the runner uses."""
import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request

from .jobs import JobFailed


def _open(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {"detail": str(e)}
    except (OSError, ValueError) as e:          # URLError, timeouts, bad JSON
        return None, {"detail": repr(e)}


def _call(method, url, timeout):
    return _open(urllib.request.Request(url, method=method), timeout)


def _fail(reason, code, body):
    lines = [body.get("detail", f"HTTP {code}")] + list(body.get("log") or [])[-5:]
    raise JobFailed(reason, " | ".join(str(l) for l in lines))


class Sitl:
    def __init__(self, web_url, call=_call):
        self.web, self.call = web_url.rstrip("/"), call

    async def pull(self, ref, timeout):
        """docker pull + retag submission-<stem>-<ts> (drone-sitl's
        DockerBuild.pull). Blocks until the pull finishes."""
        url = f"{self.web}/agent/pull-docker?ref={urllib.parse.quote(ref, safe='')}"
        code, body = await asyncio.to_thread(self.call, "POST", url, timeout)
        if code == 200 and body.get("image_tag"):
            return body["image_tag"]
        _fail("pull_failed", code, body)

    async def detrec_status(self):
        code, body = await asyncio.to_thread(self.call, "GET", f"{self.web}/detrec/status", 10)
        return body if code == 200 else None
```

- [ ] **Step 4: รันให้ผ่าน** — Expected: `3 passed`
- [ ] **Step 5: Commit** — `git add flight_service/sitl.py tests/test_sitl.py && git commit -m "feat: drone-sitl HTTP client"`

---

### Task 6: runlog + flightsession

**Files:**
- Create: `flight_service/runlog.py`, `flight_service/flightsession.py`, `tests/fakes.py`
- Test: `tests/test_runlog.py`, `tests/test_flightsession.py`

**Interfaces:**
- Consumes: `Journal`
- Produces: `new_lines(prev, cur) -> list` · `RunLog(run_dir, fsync_every_s=1.0)` → `.event(kind, **fields)`, `.frame(t)`, `.close()`, context manager · journals: `telemetry.jsonl` (ทุกฟิลด์จาก /ws ยกเว้น `agent.log`/`agent.detections`, `t` = เวลา wall), `events.jsonl` (`{"t","kind",...}` kind ∈ `start state agent_state log end`), `detections.jsonl` (`{"t","drone":{lat,lon,alt_m,heading_deg},"boxes"}`)
- Produces: `Outcome(kind, detail="", done_line=False, run_at=0.0)` · `async fly(ws_url, image_tag, runlog, flight_timeout_s, arming_timeout_s, on_telemetry=None, connect=None) -> Outcome` · kind ∈ `done crashed refused arming_timeout timeout ws_lost` · ถูก cancel = ส่ง stop แล้วโยน `CancelledError` ต่อ

- [ ] **Step 1: ของปลอม**

`tests/fakes.py`:
```python
"""Stand-ins for everything outside this repo. No sim, no docker, no network."""
import asyncio
import json

BOX = {"class_name": "Truck", "confidence": 0.9, "bbox": [0, 0, 1, 1]}


class FakeWS:
    """websockets connect() stand-in: replays `frames` to recv(), records
    send(). After the last frame recv() blocks, or raises `end`."""

    def __init__(self, frames, end=None):
        self.frames, self.end, self.sent = list(frames), end, []

    def __call__(self, url, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        await asyncio.sleep(0)
        if self.frames:
            return json.dumps(self.frames.pop(0))
        if self.end:
            raise self.end
        await asyncio.Event().wait()


def frame(state, log=(), lat=14.0, lon=100.0, alt=20.0, boxes=()):
    return {"connected": True, "lat": lat, "lon": lon, "alt_m": alt, "heading_deg": 90.0,
            "roll_deg": 0.0, "pitch_deg": 0.0, "gs": 3.0, "vz": 0.0, "mode": "OFFBOARD",
            "armed": True,
            "agent": {"state": state, "log": list(log), "detections": list(boxes)}}
```

- [ ] **Step 2: เขียนเทสต์ที่ fail**

`tests/test_runlog.py`:
```python
from fakes import BOX, frame

from flight_service.journal import read_jsonl
from flight_service.runlog import RunLog, new_lines


def test_new_lines():
    assert new_lines([], ["a", "b"]) == ["a", "b"]
    assert new_lines(["a", "b"], ["a", "b", "c"]) == ["c"]
    assert new_lines(["a", "b", "c"], ["b", "c", "d"]) == ["d"]     # window slid
    assert new_lines(["a"], ["a"]) == []
    assert new_lines(["x"], ["y", "z"]) == ["y", "z"]


def test_frame_splits_into_three_journals(tmp_path):
    f1 = frame("running", ["a"], boxes=[BOX])
    with RunLog(tmp_path) as rl:
        rl.frame(f1)
        rl.frame(frame("running", ["a", "b"]))
        rl.event("state", state="flying")
    assert f1["agent"]["log"] == ["a"]                       # caller's frame untouched
    tel = list(read_jsonl(tmp_path / "telemetry.jsonl"))
    assert len(tel) == 2 and tel[0]["alt_m"] == 20.0 and tel[0]["connected"] is True
    assert tel[0]["agent"] == {"state": "running"} and "t" in tel[0]
    ev = list(read_jsonl(tmp_path / "events.jsonl"))
    assert [e["line"] for e in ev if e["kind"] == "log"] == ["a", "b"]
    assert (ev[-1]["kind"], ev[-1]["state"]) == ("state", "flying")
    det = list(read_jsonl(tmp_path / "detections.jsonl"))
    assert len(det) == 1 and det[0]["boxes"] == [BOX]
    assert det[0]["drone"] == {"lat": 14.0, "lon": 100.0, "alt_m": 20.0, "heading_deg": 90.0}
```

`tests/test_flightsession.py`:
```python
import asyncio

from fakes import FakeWS, frame

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


def test_socket_drop_and_silence_are_ws_lost(tmp_path, monkeypatch):
    out, _, _ = run([frame("running")], tmp_path / "a", end=ConnectionResetError("gone"))
    assert out.kind == "ws_lost"
    monkeypatch.setattr(fs, "RECV_TIMEOUT_S", 0.05)
    out, _, _ = run([frame("running")], tmp_path / "b")
    assert out.kind == "ws_lost"


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
```

- [ ] **Step 3: รันให้เห็นว่า fail** — `conda run -n drone python -m pytest -q tests/test_runlog.py tests/test_flightsession.py` → FAIL `No module named 'flight_service.runlog'` (`from fakes import` ใช้ได้เพราะ `tests/` ไม่มี `__init__.py`)

- [ ] **Step 4: เขียนโค้ด**

`flight_service/runlog.py`:
```python
"""The journals of one run (design 13.4), open for the whole job. Every
/ws frame is split three ways the moment it arrives: telemetry (all of
PX4's fields), new agent log lines (events), and boxes (detections)."""
import time
from pathlib import Path

from .journal import Journal

POSE_KEYS = ("lat", "lon", "alt_m", "heading_deg")


def new_lines(prev, cur):
    """Lines of `cur` not already in `prev`. Both are the agent panel's
    sliding window (the last N lines), so the longest suffix of `prev`
    that is a prefix of `cur` is what we have already seen."""
    k = min(len(prev), len(cur))
    while k and cur[:k] != prev[-k:]:
        k -= 1
    return cur[k:]


class RunLog:
    def __init__(self, run_dir, fsync_every_s=1.0):
        d = Path(run_dir)
        self.telemetry = Journal(d / "telemetry.jsonl", fsync_every_s)
        self.events = Journal(d / "events.jsonl", fsync_every_s)
        self.detections = Journal(d / "detections.jsonl", fsync_every_s)
        self._log = []

    def event(self, kind, **fields):
        self.events.append({"t": time.time(), "kind": kind, **fields})

    def frame(self, t):
        now = time.time()
        agent = dict(t.get("agent") or {})
        log = agent.pop("log", None) or []
        boxes = agent.pop("detections", None) or []
        self.telemetry.append({**{k: v for k, v in t.items() if k != "agent"},
                               "t": now, "agent": agent})
        for line in new_lines(self._log, log):
            self.event("log", line=line)
        self._log = list(log)
        if boxes:
            self.detections.append({"t": now, "drone": {k: t.get(k) for k in POSE_KEYS},
                                    "boxes": boxes})

    def close(self):
        for j in (self.telemetry, self.events, self.detections):
            j.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
```

`flight_service/flightsession.py`:
```python
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
```

- [ ] **Step 5: รันให้ผ่าน** — Expected: `11 passed`
- [ ] **Step 6: Commit** — `git add flight_service/runlog.py flight_service/flightsession.py tests/fakes.py tests/test_runlog.py tests/test_flightsession.py && git commit -m "feat: journal every /ws frame while flying one agent"`

---

### Task 7: score v0

**Files:** Create `flight_service/score.py` · Test `tests/test_score.py`

**Interfaces:**
- Consumes: `read_jsonl`
- Produces: `enu(lat, lon, origin)`, `ScoreV0(trucks, origin, min_radius_m=10.0)` → `.add(drone, boxes)`, `.live()`, `.result(site)` · `score_file(path, trucks, origin, site)` · `load_truth(drone_sitl_dir, site) -> (origin, trucks)`

- [ ] **Step 1: เขียนเทสต์ที่ fail**

`tests/test_score.py`:
```python
import json
from math import cos, radians
from pathlib import Path

import pytest

from flight_service.score import ScoreV0, enu, load_truth, score_file

ORIGIN = (14.0, 100.0)
TRUCKS = {"A": (0.0, 0.0), "B": (100.0, 0.0)}
BOX = {"class_name": "Truck", "confidence": 0.8, "bbox": [0, 0, 1, 1]}


def at(east, north, alt=20.0):
    return {"lat": ORIGIN[0] + north / 110574.0,
            "lon": ORIGIN[1] + east / (111320.0 * cos(radians(ORIGIN[0]))), "alt_m": alt}


def test_enu_round_trip():
    p = at(30, -40)
    e, n = enu(p["lat"], p["lon"], ORIGIN)
    assert e == pytest.approx(30, abs=0.01) and n == pytest.approx(-40, abs=0.01)


def test_one_truck_found_one_false_alarm():
    s = ScoreV0(TRUCKS, ORIGIN)
    s.add(at(5, 5), [BOX])
    s.add(at(500, 500), [BOX])
    s.add(at(100, 0), [])
    r = s.result("nt-testgs")
    assert r["boxes"]["rows"] == 2 and r["boxes"]["total"] == 2
    assert r["boxes"]["by_class"]["Truck"] == {"count": 2, "conf_mean": 0.8, "conf_max": 0.8}
    assert r["truth"]["found"] == ["A"] and r["truth"]["recall"] == 0.5 and r["truth"]["precision"] == 0.5
    assert r["score"] == 50.0
    assert s.live() == {"rows": 2, "trucks_found": 1, "trucks_total": 2}


def test_radius_grows_with_altitude():
    s = ScoreV0(TRUCKS, ORIGIN)
    s.add(at(30, 0, alt=40.0), [BOX])
    s.add(at(30, 0, alt=5.0), [BOX])
    assert s.result("x")["truth"]["rows_near_truck"] == 1


def test_no_truth_or_no_boxes_scores_zero(tmp_path):
    assert ScoreV0({}, ORIGIN).result("x")["score"] == 0.0
    assert score_file(tmp_path / "missing.jsonl", TRUCKS, ORIGIN, "x")["score"] == 0.0


def test_score_file_reads_detection_journal(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text(json.dumps({"t": 1, "drone": at(0, 0), "boxes": [BOX]}) + "\ngarbage\n"
                 + json.dumps({"t": 2, "drone": at(100, 2), "boxes": [BOX]}) + "\n")
    r = score_file(p, TRUCKS, ORIGIN, "x")
    assert r["truth"]["found"] == ["A", "B"] and r["score"] == 100.0


DRONE_SITL = Path.home() / "pai" / "drone-sitl"


@pytest.mark.skipif(not DRONE_SITL.is_dir(), reason="needs drone-sitl checkout")
def test_load_truth_from_drone_sitl():
    origin, trucks = load_truth(DRONE_SITL, "nt-testgs")
    assert len(origin) == 2 and len(trucks) >= 1
```

- [ ] **Step 2: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.score'`

- [ ] **Step 3: เขียนโค้ด**

`flight_service/score.py`:
```python
"""Detection score v0 (design 9.1): the agent's boxes against the map's
real trucks, using only what the competition contract carries -- boxes
plus where the drone was. Deliberately rough: no projection of boxes onto
the ground; a row is "near" when the drone is within max(alt, 10 m) of a
real truck."""
import math
import sys
from pathlib import Path

from .journal import read_jsonl

M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON_EQ = 111320.0


def enu(lat, lon, origin):
    olat, olon = origin
    return ((lon - olon) * M_PER_DEG_LON_EQ * math.cos(math.radians(olat)),
            (lat - olat) * M_PER_DEG_LAT)


class ScoreV0:
    def __init__(self, trucks, origin, min_radius_m=10.0):
        self.trucks, self.origin, self.min_radius_m = dict(trucks), origin, min_radius_m
        self.rows = self.near = 0
        self.found = set()
        self.by_class = {}           # class -> [count, conf sum, conf max]

    def add(self, drone, boxes):
        if not boxes:
            return
        self.rows += 1
        for b in boxes:
            c = self.by_class.setdefault(b["class_name"], [0, 0.0, 0.0])
            c[0] += 1
            c[1] += b["confidence"]
            c[2] = max(c[2], b["confidence"])
        lat, lon = drone.get("lat"), drone.get("lon")
        if lat is None or lon is None or not self.trucks:
            return
        x, y = enu(lat, lon, self.origin)
        radius = max(drone.get("alt_m") or 0.0, self.min_radius_m)
        dist, name = min((math.hypot(x - tx, y - ty), n) for n, (tx, ty) in self.trucks.items())
        if dist <= radius:
            self.near += 1
            self.found.add(name)

    def live(self):
        return {"rows": self.rows, "trucks_found": len(self.found), "trucks_total": len(self.trucks)}

    def result(self, site):
        total = len(self.trucks)
        recall = len(self.found) / total if total else 0.0
        precision = self.near / self.rows if self.rows else 0.0
        f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
        return {"version": "v0", "site": site,
                "boxes": {"rows": self.rows, "total": sum(c[0] for c in self.by_class.values()),
                          "by_class": {n: {"count": c[0], "conf_mean": round(c[1] / c[0], 3),
                                           "conf_max": round(c[2], 3)}
                                       for n, c in self.by_class.items()}},
                "truth": {"trucks_total": total, "trucks_found": len(self.found),
                          "found": sorted(self.found), "rows_near_truck": self.near,
                          "recall": round(recall, 3), "precision": round(precision, 3)},
                "score": round(100 * f1, 1)}


def score_file(path, trucks, origin, site):
    s = ScoreV0(trucks, origin)
    for row in read_jsonl(path):
        if isinstance(row, dict):
            s.add(row.get("drone") or {}, row.get("boxes") or [])
    return s.result(site)


def load_truth(drone_sitl_dir, site):
    """(origin (lat, lon), {truck: (east, north)}) from drone-sitl's own
    fly_headless.load_truth -- the truth its flight checker uses."""
    path = str(Path(drone_sitl_dir) / "examples" / "competition-submission")
    if path not in sys.path:
        sys.path.insert(0, path)
    import fly_headless
    site_obj, trucks, _bounds = fly_headless.load_truth(site)
    return (site_obj.latitude, site_obj.longitude), trucks
```

- [ ] **Step 4: รันให้ผ่าน** — Expected: `6 passed`
- [ ] **Step 5: Commit** — `git add flight_service/score.py tests/test_score.py && git commit -m "feat: detection score v0 against map truth"`

---

### Task 8: finalize + retention

**Files:** Create `flight_service/finalize.py`, `flight_service/retention.py` · Test `tests/test_finalize.py`, `tests/test_retention.py`

**Interfaces:**
- Consumes: `read_jsonl`, `write_atomic`, `FILES`, `RUNNING_MARK`, `score_file`
- Produces: `async wait_clip(status_fn, since, timeout, poll=1.0) -> Path|None` · `run_analysis(run_dir, drone_sitl_dir, site, timeout=60)` · `finalize(run_dir, *, job_id, ended_by, outcome=None, detail="", done_line=False, truth=((0.0, 0.0), {}), site="nt-testgs", clip_dir=None, drone_sitl_dir=None) -> dict` · `ended_by` ∈ `agent timeout error kill runner_restarted` · `partial = ended_by != "agent"`
- Produces: `prune(runs_dir, max_bytes, keep=()) -> list[str]` (ลบงานที่จบแล้วเก่าสุดก่อนจนไม่เกิน cap · ข้าม `keep` และโฟลเดอร์ที่มี `RUNNING` · `max_bytes <= 0` = ไม่ลบ)

- [ ] **Step 1: เขียนเทสต์ที่ fail**

`tests/test_finalize.py`:
```python
import asyncio
import json
import time

from fakes import BOX, frame

from flight_service.finalize import finalize, wait_clip
from flight_service.jobs import RUNNING_MARK
from flight_service.journal import read_jsonl
from flight_service.runlog import RunLog

TRUTH = ((14.0, 100.0), {"A": (0.0, 0.0)})


def make_run(d):
    d.mkdir(parents=True, exist_ok=True)
    (d / RUNNING_MARK).touch()
    with RunLog(d) as rl:
        rl.frame(frame("running", ["[1s] hi"], boxes=[BOX]))
        rl.frame(frame("stopped", ["[1s] hi", "[2s] DONE"], lat=14.0 + 100 / 110574.0, alt=40.0))


def test_finalize_builds_everything_from_journals(tmp_path):
    make_run(tmp_path)
    r = finalize(tmp_path, job_id="j1", ended_by="agent", outcome="done", done_line=True,
                 truth=TRUTH, site="x")
    assert (r["ended_by"], r["partial"], r["outcome"]) == ("agent", False, "done")
    assert r["track_points"] == 2 and abs(r["distance_m"] - 100) < 0.5 and r["max_alt_m"] == 40.0
    assert r["score"] == {"version": "v0", "score": 100.0, "recall": 1.0, "precision": 1.0,
                          "trucks_found": 1, "trucks_total": 1}
    assert (tmp_path / "panel.log").read_text() == "[1s] hi\n[2s] DONE\n"
    track = list(read_jsonl(tmp_path / "track.jsonl"))
    assert track[0]["t"] == 0.0 and set(track[0]) == {"t", "lat", "lon", "alt", "heading", "roll",
                                                      "pitch", "gs", "vz", "mode", "armed", "state"}
    assert not (tmp_path / RUNNING_MARK).exists()
    assert json.loads((tmp_path / "result.json").read_text()) == r
    assert r["files"]["result.json"] == "/jobs/j1/files/result.json"
    assert "detections.mp4" in r["missing"] and "analysis.txt" not in r["missing"]


def test_finalize_is_idempotent(tmp_path):
    make_run(tmp_path)
    kw = dict(job_id="j1", ended_by="kill", truth=TRUTH, site="x")
    assert finalize(tmp_path, **kw) == finalize(tmp_path, **kw)


def test_finalize_with_nothing_on_disk(tmp_path):
    r = finalize(tmp_path, job_id="j1", ended_by="error", truth=TRUTH, site="x")
    assert r["partial"] is True and r["track_points"] == 0 and r["score"]["score"] == 0.0


def test_finalize_copies_the_clip(tmp_path):
    clip = tmp_path / "clip"
    clip.mkdir()
    (clip / "detections.mp4").write_bytes(b"mp4")
    (clip / "meta.json").write_text("{}")
    run = tmp_path / "run"
    make_run(run)
    r = finalize(run, job_id="j1", ended_by="agent", truth=TRUTH, site="x", clip_dir=clip)
    assert (run / "detections.mp4").read_bytes() == b"mp4" and r["missing"] == []


def test_wait_clip_waits_for_meta(tmp_path):
    clip = tmp_path / "2026-10-05" / "120005_x"
    clip.mkdir(parents=True)
    states = [{"on": True, "last": None}, {"on": False, "last": str(clip / "detections.mp4")}]

    async def status():
        if len(states) > 1:
            return states.pop(0)
        (clip / "meta.json").write_text("{}")
        return states[0]

    assert asyncio.run(wait_clip(status, time.time() - 5, 2.0, poll=0.01)) == clip


def test_wait_clip_gives_up(tmp_path):
    async def status():
        return {"on": False, "last": None}
    assert asyncio.run(wait_clip(status, time.time(), 0.05, poll=0.01)) is None
```

`tests/test_retention.py`:
```python
import os
import time

from flight_service.retention import prune


def mk(root, name, size, age):
    d = root / name
    d.mkdir()
    (d / "job.json").write_text("{}")
    (d / "blob").write_bytes(b"x" * size)
    t = time.time() - age
    os.utime(d / "job.json", (t, t))
    return d


def test_prune_oldest_first_until_under_cap(tmp_path):
    a, b, c = mk(tmp_path, "a", 400, 300), mk(tmp_path, "b", 400, 200), mk(tmp_path, "c", 400, 100)
    assert prune(tmp_path, 1000) == ["a"]
    assert not a.exists() and b.exists() and c.exists()


def test_prune_skips_kept_and_running(tmp_path):
    mk(tmp_path, "a", 400, 300)
    b = mk(tmp_path, "b", 400, 200)
    (b / "RUNNING").touch()
    mk(tmp_path, "c", 400, 100)
    assert prune(tmp_path, 500, keep={"a"}) == ["c"]


def test_prune_off_and_missing_dir(tmp_path):
    mk(tmp_path, "a", 400, 300)
    assert prune(tmp_path, 0) == []
    assert prune(tmp_path / "none", 10) == []
```

- [ ] **Step 2: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.finalize'`

- [ ] **Step 3: เขียนโค้ด**

`flight_service/finalize.py`:
```python
"""Build a run's results from its journals -- the one way every job ends:
the agent finished, timeout, error, kill, or a runner restart (design
13.2). Reads only what is on disk and rewrites every derived file, so
running it twice gives the same result."""
import asyncio
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import score as scoring
from .jobs import FILES, RUNNING_MARK
from .journal import read_jsonl, write_atomic

CLIP_FILES = ("detections.mp4", "meta.json")
# track.jsonl keeps fly_headless's row shape so its analyze() reads our runs.
TRACK_KEYS = (("lat", "lat"), ("lon", "lon"), ("alt", "alt_m"), ("heading", "heading_deg"),
              ("roll", "roll_deg"), ("pitch", "pitch_deg"), ("gs", "gs"), ("vz", "vz"),
              ("mode", "mode"), ("armed", "armed"))


def _derive_track(run_dir):
    rows, t0 = [], None
    for r in read_jsonl(run_dir / "telemetry.jsonl"):
        t0 = r.get("t", 0.0) if t0 is None else t0
        rows.append({"t": round(r.get("t", t0) - t0, 2),
                     **{k: r.get(src) for k, src in TRACK_KEYS},
                     "state": (r.get("agent") or {}).get("state")})
    write_atomic(run_dir / "track.jsonl", "".join(json.dumps(x) + "\n" for x in rows))
    return rows


def _derive_panel(run_dir):
    lines = [e["line"] for e in read_jsonl(run_dir / "events.jsonl")
             if isinstance(e, dict) and e.get("kind") == "log" and "line" in e]
    write_atomic(run_dir / "panel.log", "".join(l + "\n" for l in lines))


def _summarise(rows):
    pts = [(r["lat"], r["lon"]) for r in rows if r["lat"] is not None and r["lon"] is not None]
    dist = 0.0
    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:]):
        dist += math.hypot((lo2 - lo1) * 111320.0 * math.cos(math.radians(la1)),
                           (la2 - la1) * 110574.0)
    alts = [r["alt"] for r in rows if r["alt"] is not None]
    return {"track_points": len(rows), "flight_s": rows[-1]["t"] if rows else 0.0,
            "distance_m": round(dist, 1), "max_alt_m": round(max(alts), 1) if alts else None}


async def wait_clip(status_fn, since, timeout, poll=1.0):
    """det_recorder's clip folder for this run once finished (meta.json is
    written last), or None after `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = await status_fn()
        last = (st or {}).get("last")
        if st and not st.get("on") and last:
            meta = Path(last).parent / "meta.json"
            if meta.exists() and meta.stat().st_mtime >= since:
                return meta.parent
        await asyncio.sleep(poll)
    return None


def run_analysis(run_dir, drone_sitl_dir, site, timeout=60):
    """drone-sitl's own flight checker, for humans (not scored)."""
    examples = Path(drone_sitl_dir) / "examples" / "competition-submission"
    if not (examples / "fly_headless.py").exists():
        return
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import fly_headless; "
            "fly_headless.analyze(sys.argv[2], sys.argv[3])")
    try:
        p = subprocess.run([sys.executable, "-c", code, str(examples), str(run_dir), site],
                           capture_output=True, text=True, timeout=timeout)
        write_atomic(Path(run_dir) / "analysis.txt", p.stdout + p.stderr)
    except (OSError, subprocess.TimeoutExpired):
        pass


def finalize(run_dir, *, job_id, ended_by, outcome=None, detail="", done_line=False,
             truth=((0.0, 0.0), {}), site="nt-testgs", clip_dir=None, drone_sitl_dir=None):
    run_dir = Path(run_dir)
    rows = _derive_track(run_dir)
    _derive_panel(run_dir)
    if clip_dir is not None:
        for name in CLIP_FILES:
            if (Path(clip_dir) / name).exists():
                shutil.copy2(Path(clip_dir) / name, run_dir / name)
    origin, trucks = truth
    sc = scoring.score_file(run_dir / "detections.jsonl", trucks, origin, site)
    write_atomic(run_dir / "score.json", sc)
    if drone_sitl_dir is not None and rows:
        run_analysis(run_dir, drone_sitl_dir, site)
    result = {"ended_by": ended_by, "partial": ended_by != "agent", "outcome": outcome,
              "detail": detail, "done_line": done_line, **_summarise(rows),
              "score": {"version": sc["version"], "score": sc["score"],
                        **{k: sc["truth"][k] for k in ("recall", "precision",
                                                       "trucks_found", "trucks_total")}}}
    present = [n for n in FILES if n == "result.json" or (run_dir / n).exists()]
    result["files"] = {n: f"/jobs/{job_id}/files/{n}" for n in present}
    result["missing"] = [n for n in FILES if n not in present and n != "analysis.txt"]
    write_atomic(run_dir / "result.json", result)
    (run_dir / RUNNING_MARK).unlink(missing_ok=True)
    return result
```

`flight_service/retention.py`:
```python
"""Keep data/runs under a size cap (design 13.6): delete whole finished
runs, oldest first. Only ever touches folders inside runs_dir."""
import os
import shutil
from pathlib import Path

from .jobs import RUNNING_MARK


def _size(d):
    return sum(os.path.getsize(os.path.join(root, f))
               for root, _, files in os.walk(d) for f in files)


def _age_key(d):
    snap = d / "job.json"
    return (snap if snap.exists() else d).stat().st_mtime


def prune(runs_dir, max_bytes, keep=()):
    runs_dir = Path(runs_dir)
    if max_bytes <= 0 or not runs_dir.is_dir():
        return []
    runs = [d for d in runs_dir.iterdir() if d.is_dir()]
    sizes = {d: _size(d) for d in runs}
    total, deleted = sum(sizes.values()), []
    for d in sorted(runs, key=_age_key):
        if total <= max_bytes:
            break
        if d.name in keep or (d / RUNNING_MARK).exists():
            continue
        shutil.rmtree(d, ignore_errors=True)
        total -= sizes[d]
        deleted.append(d.name)
    return deleted
```

- [ ] **Step 4: รันให้ผ่าน** — Expected: `9 passed`
- [ ] **Step 5: Commit** — `git add flight_service/finalize.py flight_service/retention.py tests/test_finalize.py tests/test_retention.py && git commit -m "feat: idempotent finalize from journals, size-capped retention"`

---

### Task 9: worker

**Files:** Create `flight_service/worker.py` · Modify `tests/fakes.py` (ต่อท้าย) · Test `tests/test_worker.py`

**Interfaces:**
- Consumes: Task 1–8
- Produces: `Worker(settings, store, docker, sim, sitl, fly=flightsession.fly, truth=None)` → `.submit(job)`, `.queued()` (ช่องรอ), `.accepting() -> bool`, `.kill(job) -> bool`, `.health() -> {"ok","ready","phase","pending"}`, `.current`, `.phase`, async `run_forever()`, `run_job(job)`, `recover()` · `phase` ∈ `idle running finishing cleanup degraded`
- state จบถูกตั้ง**หลัง** `_cleanup()` เสมอ (และ `phase` กลับเป็น `idle` ก่อนตั้ง state จบ)
- `_acquire(job, runlog)` = จุดต่อของส่วน B

- [ ] **Step 1: ต่อท้าย `tests/fakes.py`**

```python
# --- pipeline fakes (Task 9) ------------------------------------------------
import os
import time

from flight_service.flightsession import Outcome
from flight_service.jobs import JobFailed


class FakeDocker:
    def __init__(self, exists=False, size=5 * 1024 ** 3, manifest=4 * 1024 ** 3):
        self._exists, self._size, self._manifest, self.calls = exists, size, manifest, []

    async def exists(self, ref):
        self.calls.append(("exists", ref))
        return self._exists

    async def manifest_bytes(self, ref, timeout):
        return self._manifest

    async def size(self, ref):
        return self._size

    async def containers_of(self, tag):
        return ["submission-run-1"]

    async def rm_force(self, name):
        self.calls.append(("rm_force", name))

    async def rmi(self, ref):
        self.calls.append(("rmi", ref))
        return True


class FakeSim:
    def __init__(self, busy=False, fail=None, stop_ok=True):
        self._busy, self.fail, self.stop_ok, self.calls = busy, fail, stop_ok, []

    async def _step(self, name):
        self.calls.append(name)
        if self.fail and self.fail[0] == name:
            raise JobFailed(*self.fail[1:])

    async def busy(self):
        self.calls.append("busy")
        return self._busy

    async def start_web(self):
        await self._step("start_web")

    async def start_sim(self):
        await self._step("start_sim")

    async def wait_px4_ready(self, since):
        await self._step("wait_px4_ready")

    async def stop(self):
        self.calls.append("stop")
        return self.stop_ok


class FakeSitl:
    def __init__(self, tag="submission-x-20261005-120000", fail=None, clip=None):
        self.tag, self.fail, self.clip = tag, fail, clip

    async def pull(self, ref, timeout):
        if self.fail:
            raise JobFailed("pull_failed", self.fail)
        return self.tag

    async def detrec_status(self):
        if not self.clip:
            return {"on": False, "last": None}
        os.utime(self.clip / "meta.json")       # the recorder just closed this run's clip
        return {"on": False, "last": str(self.clip / "detections.mp4")}


def make_fly(kind="done", detail="", hold=None, frames=None):
    """flightsession.fly stand-in: journals `frames`, then waits on `hold`."""
    frames = [frame("running", ["[ 0s] up"])] if frames is None else frames

    async def fly(ws_url, tag, runlog, flight_s, arming_s, on_telemetry=None):
        for f in frames:
            runlog.frame(f)
            on_telemetry(f)
        if hold is not None:
            await hold.wait()
        return Outcome(kind, detail, kind == "done", time.time())

    return fly
```

- [ ] **Step 2: เขียนเทสต์ที่ fail**

`tests/test_worker.py`:
```python
import asyncio
import json

from fakes import BOX, FakeDocker, FakeSim, FakeSitl, frame, make_fly

from flight_service.config import Settings
from flight_service.jobs import (BOOTING, DONE, FAILED, FLYING, KILLED, PULLING,
                                 QUEUED, RUNNING_MARK, JobStore)
from flight_service.journal import read_jsonl
from flight_service.worker import Worker

TRUTH = ((14.0, 100.0), {"A": (0.0, 0.0)})
ONE = ["busy", "start_web", "start_sim", "wait_px4_ready", "stop"]


def setup(tmp_path, docker=None, sim=None, sitl=None, fly=None, **kw):
    tmp_path.mkdir(parents=True, exist_ok=True)
    kw.setdefault("data_retention_gb", 0)
    s = Settings(token="t" * 32, drone_sitl_dir=tmp_path / "sitl", runs_dir=tmp_path / "runs",
                 docker_root=tmp_path, min_free_gb=0, collect_timeout_s=0.05, **kw)
    store = JobStore(s.runs_dir)
    w = Worker(s, store, docker or FakeDocker(), sim or FakeSim(), sitl or FakeSitl(),
               fly=fly or make_fly(), truth=lambda: TRUTH)
    return s, store, w


def make_clip(tmp_path):
    clip = tmp_path / "rec" / "2026-10-05" / "120000_x"
    clip.mkdir(parents=True)
    (clip / "detections.mp4").write_bytes(b"mp4")
    (clip / "meta.json").write_text("{}")
    return clip


def run_bg(w, store, until, then=None):
    """Run the worker loop until until(oldest job) is true, then `then`."""
    async def scenario():
        loop = asyncio.create_task(w.run_forever())
        job = store.all()[-1]
        while not until(job):
            await asyncio.sleep(0.01)
        if then:
            await then(job)
        loop.cancel()
        return job
    return asyncio.run(scenario())


def test_happy_path(tmp_path):
    docker, sim = FakeDocker(), FakeSim()
    _, store, w = setup(tmp_path, docker=docker, sim=sim, sitl=FakeSitl(clip=make_clip(tmp_path)),
                        fly=make_fly(frames=[frame("running", ["[ 1s] hello"], boxes=[BOX]),
                                             frame("stopped", ["[ 1s] hello", "[ 2s] DONE"])]))
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert job.state == DONE, (job.reason, job.detail)
    assert sim.calls == ONE
    assert job.score_live == {"rows": 1, "trucks_found": 1, "trucks_total": 1}
    r = job.result
    assert (r["ended_by"], r["partial"], r["score"]["score"]) == ("agent", False, 100.0)
    assert {"telemetry.jsonl", "events.jsonl", "detections.jsonl", "track.jsonl", "panel.log",
            "detections.mp4", "score.json", "result.json"} <= set(r["files"])
    d = store.dir(job)
    assert (d / "panel.log").read_text() == "[ 1s] hello\n[ 2s] DONE\n"
    assert not (d / RUNNING_MARK).exists()
    ev = list(read_jsonl(d / "events.jsonl"))
    assert [e["state"] for e in ev if e["kind"] == "state"] == [PULLING, BOOTING, FLYING]
    assert ev[-1]["kind"] == "end" and ev[-1]["state"] == DONE
    assert ("rmi", "submission-x-20261005-120000") in docker.calls
    assert ("rmi", "perkiepai/x:1") in docker.calls          # this job brought it in
    assert ("rm_force", "submission-run-1") in docker.calls
    assert w.phase == "idle"


def test_preexisting_image_is_not_removed(tmp_path):
    docker = FakeDocker(exists=True)
    _, store, w = setup(tmp_path, docker=docker)
    asyncio.run(w.run_job(store.new("perkiepai/drone-rtdetr-submission:latest", 600)))
    assert ("rmi", "perkiepai/drone-rtdetr-submission:latest") not in docker.calls
    assert ("rmi", "submission-x-20261005-120000") in docker.calls


def test_keep_image(tmp_path):
    docker = FakeDocker()
    _, store, w = setup(tmp_path, docker=docker, keep_image=True)
    asyncio.run(w.run_job(store.new("perkiepai/x:1", 600)))
    assert not any(c[0] == "rmi" for c in docker.calls)


def test_sim_busy_fails_without_touching_the_sim(tmp_path):
    sim = FakeSim(busy=True)
    _, store, w = setup(tmp_path, sim=sim)
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason, job.failed_in) == (FAILED, "sim_busy", PULLING)
    assert sim.calls == ["busy"] and job.result["partial"] is True


def test_pull_failure_stops_the_web_it_started(tmp_path):
    sim = FakeSim()
    _, store, w = setup(tmp_path, sim=sim, sitl=FakeSitl(fail="manifest unknown"))
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason) == (FAILED, "pull_failed") and sim.calls[-1] == "stop"


def test_image_too_large_after_pull(tmp_path):
    docker = FakeDocker(size=20 * 1024 ** 3, manifest=None)
    _, store, w = setup(tmp_path, docker=docker)
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason) == (FAILED, "image_too_large")
    assert ("rmi", "submission-x-20261005-120000") in docker.calls


def test_px4_not_ready(tmp_path):
    sim = FakeSim(fail=("wait_px4_ready", "px4_not_ready", "no line"))
    _, store, w = setup(tmp_path, sim=sim)
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason, job.failed_in) == (FAILED, "px4_not_ready", BOOTING)
    assert sim.calls[-1] == "stop"


def test_flight_failures_map_to_reasons_and_keep_data(tmp_path):
    for kind, reason, ended_by in [("crashed", "agent_crashed", "error"),
                                   ("refused", "run_refused", "error"),
                                   ("arming_timeout", "arming_timeout", "error"),
                                   ("timeout", "flight_timeout", "timeout"),
                                   ("ws_lost", "ws_lost", "error")]:
        _, store, w = setup(tmp_path / kind, fly=make_fly(kind, "why"))
        job = store.new("perkiepai/x:1", 600)
        asyncio.run(w.run_job(job))
        assert (job.state, job.reason, job.failed_in) == (FAILED, reason, FLYING)
        assert (job.result["outcome"], job.result["ended_by"]) == (kind, ended_by)
        assert job.result["track_points"] == 1


def test_missing_clip_still_finishes(tmp_path):
    _, store, w = setup(tmp_path, sitl=FakeSitl(clip=None))
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert job.state == DONE and "detections.mp4" in job.result["missing"]


def test_cleanup_failure_degrades_and_refuses_new_jobs(tmp_path):
    _, store, w = setup(tmp_path, sim=FakeSim(stop_ok=False))
    asyncio.run(w.run_job(store.new("perkiepai/x:1", 600)))
    assert w.phase == "degraded" and w.health()["ok"] is False
    job = store.new("perkiepai/y:1", 600)
    w.submit(job)
    run_bg(w, store, until=lambda _: store.get(job.id).state != QUEUED)
    assert (job.state, job.reason) == (FAILED, "runner_degraded")


def test_state_ends_only_after_cleanup(tmp_path):
    seen = {}

    class WatchSim(FakeSim):
        async def stop(self):
            seen["state"] = job.state
            return await super().stop()

    _, store, w = setup(tmp_path, sim=WatchSim())
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert seen["state"] == FLYING and job.state == DONE and w.phase == "idle"


def test_health_reports_room_for_one_pending_job(tmp_path):
    _, store, w = setup(tmp_path)
    assert w.health() == {"ok": True, "ready": True, "phase": "idle", "pending": 0}
    store.new("perkiepai/x:1", 600)                          # waiting in the slot
    assert w.health()["ready"] is False and w.health()["pending"] == 1


def test_kill_while_flying_keeps_the_data(tmp_path):
    sim, docker = FakeSim(), FakeDocker()
    _, store, w = setup(tmp_path, sim=sim, docker=docker, sitl=FakeSitl(clip=make_clip(tmp_path)),
                        fly=make_fly(hold=asyncio.Event()))
    job = store.new("perkiepai/x:1", 600)
    w.submit(job)

    async def kill(j):
        await asyncio.sleep(0.02)
        assert w.kill(j) is True
        while j.state == FLYING or w.phase != "idle":
            await asyncio.sleep(0.01)

    run_bg(w, store, until=lambda j: j.state == FLYING, then=kill)
    assert (job.state, job.reason, job.failed_in) == (KILLED, "killed", FLYING)
    r = job.result
    assert (r["ended_by"], r["partial"], r["track_points"]) == ("kill", True, 1)
    assert "detections.mp4" in r["files"]                 # clip closed by the agent stop
    assert sim.calls[-1] == "stop" and ("rm_force", "submission-run-1") in docker.calls


def test_kill_twice_is_harmless(tmp_path):
    _, store, w = setup(tmp_path, fly=make_fly(hold=asyncio.Event()))
    job = store.new("perkiepai/x:1", 600)
    w.submit(job)

    async def kill(j):
        assert w.kill(j) and w.kill(j)
        while w.phase != "idle":
            await asyncio.sleep(0.01)

    run_bg(w, store, until=lambda j: j.state == FLYING, then=kill)
    assert job.state == KILLED and job.result is not None


def test_kill_queued(tmp_path):
    _, store, w = setup(tmp_path)
    job = store.new("perkiepai/x:1", 600)
    assert w.kill(job) is True
    assert (job.state, job.failed_in, job.result) == (KILLED, QUEUED, None)
    assert w.kill(job) is False


def test_recover_finalizes_and_stops_only_owned_sims(tmp_path):
    s, store, _ = setup(tmp_path)
    flying = store.new("perkiepai/a:1", 600)
    flying.owns_sim, flying.image_tag = True, "submission-a-1"
    store.set_state(flying, FLYING)
    (store.dir(flying) / RUNNING_MARK).touch()
    (store.dir(flying) / "telemetry.jsonl").write_text(json.dumps(
        {"t": 1.0, "lat": 14.0, "lon": 100.0, "alt_m": 5.0, "agent": {"state": "running"}}) + "\n")
    queued = store.new("perkiepai/b:1", 600)
    sim, fresh = FakeSim(), JobStore(s.runs_dir)
    w = Worker(s, fresh, FakeDocker(), sim, FakeSitl(), fly=make_fly(), truth=lambda: TRUTH)
    asyncio.run(w.recover())
    a, b = fresh.get(flying.id), fresh.get(queued.id)
    assert (a.state, a.reason, a.failed_in) == (FAILED, "runner_restarted", FLYING)
    assert (a.result["ended_by"], a.result["partial"], a.result["track_points"]) == \
        ("runner_restarted", True, 1)
    assert not (s.runs_dir / a.id / RUNNING_MARK).exists()
    assert (b.state, b.reason, b.result) == (FAILED, "runner_restarted", None)
    assert sim.calls == ["stop"]


def test_retention_keeps_the_run_just_finished(tmp_path):
    _, store, w = setup(tmp_path, data_retention_gb=1e-9)        # ~1 byte cap
    old = store.new("perkiepai/old:1", 600)
    store.end(old, DONE)
    (store.dir(old) / "telemetry.jsonl").write_text("x" * 100)
    job = store.new("perkiepai/x:1", 600)
    asyncio.run(w.run_job(job))
    assert not store.dir(old).exists() and store.get(old.id) is None
    assert store.dir(job).exists() and store.get(job.id) is job
```

- [ ] **Step 3: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.worker'`

- [ ] **Step 4: เขียนโค้ด**

`flight_service/worker.py`:
```python
"""The single worker: one job at a time through acquire -> boot -> fly,
then finalize from the run's journals and clean up -- however the job
ended, kill included (design 2, 4, 5, 7, 13). The sim is one shared
resource (trap 4), so there is exactly one Worker per process."""
import asyncio
import logging
import shutil
import time

from . import finalize as fin
from . import flightsession, policy, retention
from . import score as scoring
from .config import GB
from .jobs import (BOOTING, DONE, FAILED, FLYING, KILLED, PULLING, QUEUED,
                   RUNNING_MARK, TERMINAL, JobFailed)
from .runlog import RunLog

log = logging.getLogger("flight_service")

FAIL_REASON = {"crashed": "agent_crashed", "refused": "run_refused",
               "arming_timeout": "arming_timeout", "timeout": "flight_timeout",
               "ws_lost": "ws_lost"}
TELEM_KEYS = ("lat", "lon", "alt_m", "heading_deg", "roll_deg", "pitch_deg",
              "gs", "vz", "mode", "armed")


class Worker:
    def __init__(self, settings, store, docker, sim, sitl, fly=flightsession.fly, truth=None):
        self.s, self.store = settings, store
        self.docker, self.sim, self.sitl, self.fly = docker, sim, sitl, fly
        self._truth_fn = truth or (lambda: scoring.load_truth(settings.drone_sitl_dir, settings.site))
        self._truth = None
        self.queue = asyncio.Queue()
        self.current = None
        self._task = None
        self._kill_sent = False
        self.phase = "idle"          # idle | running | finishing | cleanup | degraded

    # -- queue -----------------------------------------------------------

    def submit(self, job):
        self.queue.put_nowait(job.id)

    def queued(self):
        return [j for j in self.store.all() if j.state == QUEUED]

    def kill(self, job):
        """True if taken. Queued: ends at once. Running: interrupted, then
        finalized and cleaned up like any other end (design 13.5)."""
        if job.state == QUEUED:
            self.store.end(job, KILLED, "killed", "killed while queued")
            return True
        if self.current is job:
            if self.phase == "running" and not self._kill_sent and self._task:
                self._kill_sent = True
                self._task.cancel()
            return True              # already finishing: it ends anyway
        return False

    def accepting(self):
        """Room for one more job: not degraded, and fewer than max_pending
        waiting behind the running one (design 5: the real queue is the
        caller's; this small one only absorbs a dispatch race)."""
        return self.phase != "degraded" and len(self.queued()) < self.s.max_pending

    def health(self):
        return {"ok": self.phase != "degraded", "ready": self.accepting(),
                "phase": self.phase, "pending": len(self.queued())}

    async def run_forever(self):
        while True:
            job = self.store.get(await self.queue.get())
            if job is None or job.state != QUEUED:
                continue             # killed while queued
            if self.phase == "degraded":
                self.store.fail(job, "runner_degraded",
                                "an earlier cleanup could not stop the sim; run "
                                "sim/stop-website.sh by hand, then restart the service")
                continue
            self._task = asyncio.create_task(self.run_job(job))
            await asyncio.wait({self._task})     # never raises for the job's own end

    async def recover(self):
        """At startup: finalize what a restart interrupted, stop a sim it had
        started. A job that was only queued never touched anything."""
        for job in self.store.load():
            was = job.state
            if was != QUEUED:
                job.result = await asyncio.to_thread(
                    self._finalize, job, "runner_restarted", None,
                    f"runner restarted while {was}", None)
                if job.owns_sim and not await self._cleanup(job):
                    self.phase = "degraded"
            self.store.fail(job, "runner_restarted", f"runner restarted while {was}")
        self._prune()

    # -- one job -----------------------------------------------------------

    async def run_job(self, job):
        self.current, self.phase, self._kill_sent = job, "running", False
        run_dir = self.store.dir(job)
        (run_dir / RUNNING_MARK).touch()
        runlog = RunLog(run_dir)
        outcome = None
        end = (FAILED, "error", "internal_error", "worker stopped before the job ended")
        try:
            try:
                runlog.event("start", image=job.image, source=job.source)
                await self._acquire(job, runlog)
                await self._boot(job, runlog)
                outcome = await self._fly(job, runlog)
                if outcome.kind == "done":
                    end = (DONE, "agent", None, outcome.detail)
                elif outcome.kind == "timeout":
                    end = (FAILED, "timeout", "flight_timeout", outcome.detail)
                else:
                    end = (FAILED, "error", FAIL_REASON[outcome.kind], outcome.detail)
            except JobFailed as e:
                end = (FAILED, "error", e.reason, e.detail)
            except asyncio.CancelledError:
                end = (KILLED, "kill", "killed", f"killed while {job.state}")
            except Exception as e:                  # noqa: BLE001
                log.exception("job %s", job.id)
                end = (FAILED, "error", "internal_error", repr(e))
            self.phase = "finishing"                # a kill from here on is a no-op
            state, ended_by, reason, detail = end
            runlog.event("end", state=state, ended_by=ended_by, reason=reason, detail=detail)
            runlog.close()
            clip = None
            if job.run_at:                          # RUN was sent -> det_recorder has a clip
                clip = await fin.wait_clip(self.sitl.detrec_status, job.run_at,
                                           self.s.collect_timeout_s)
            job.result = await asyncio.to_thread(self._finalize, job, ended_by, outcome,
                                                 detail, clip)
        finally:
            runlog.close()
            self.phase = "cleanup"
            ok = await self._cleanup(job)
            self.phase = "idle" if ok else "degraded"
            self.current, self._task = None, None
            state, _, reason, detail = end
            self.store.end(job, state, reason, detail)     # only now: cleanup is done (design 4)
            self._prune(also_keep=job.id)

    def _set(self, job, runlog, state):
        self.store.set_state(job, state)
        runlog.event("state", state=state)

    async def _precheck(self, job, runlog, state):
        self._set(job, runlog, state)
        if await self.sim.busy():
            raise JobFailed("sim_busy", "drone-sitl web (:8090) or sim (:8080) is already "
                                        "running and this runner did not start it")

    async def _acquire(self, job, runlog):
        """Put the image on this box as job.image_tag. Part B adds uploads."""
        if job.source != "registry":
            raise JobFailed("unsupported_source", job.source)
        await self._pull(job, runlog)

    async def _pull(self, job, runlog):
        await self._precheck(job, runlog, PULLING)
        size = await self.docker.manifest_bytes(job.image, self.s.manifest_timeout_s)
        policy.check_space(shutil.disk_usage(self.s.docker_root).free, size,
                           self.s.min_free_gb, self.s.max_image_gb)
        job.image_preexisting = await self.docker.exists(job.image)
        job.owns_sim = True
        self.store.save(job)
        await self.sim.start_web()
        job.image_tag = await self.sitl.pull(job.image, self.s.pull_timeout_s)
        self.store.save(job)
        await self._check_size(job)

    async def _check_size(self, job):
        real = await self.docker.size(job.image_tag)
        if real is not None and real > self.s.max_image_gb * GB:
            raise JobFailed("image_too_large", f"{real / GB:.1f} GB > {self.s.max_image_gb:g} GB")

    async def _boot(self, job, runlog):
        self._set(job, runlog, BOOTING)
        job.owns_sim = True
        self.store.save(job)
        since = time.time()
        await self.sim.start_sim()
        await self.sim.wait_px4_ready(since)

    def _load_truth(self):
        if self._truth is None:
            try:
                self._truth = self._truth_fn()
            except Exception as e:                  # noqa: BLE001 -- score 0, flight still counts
                log.warning("no map truth for score: %r", e)
                self._truth = ((0.0, 0.0), {})
        return self._truth

    async def _fly(self, job, runlog):
        self._set(job, runlog, FLYING)
        origin, trucks = await asyncio.to_thread(self._load_truth)
        live = scoring.ScoreV0(trucks, origin)
        last_save = [0.0]

        def on_telemetry(t):
            agent = t.get("agent") or {}
            job.telemetry = {**{k: t.get(k) for k in TELEM_KEYS}, "agent_state": agent.get("state")}
            job.log_tail = list((agent.get("log") or [])[-20:])
            live.add(t, agent.get("detections") or [])
            job.score_live = live.live()
            if time.monotonic() - last_save[0] > 5.0:
                self.store.save(job)
                last_save[0] = time.monotonic()

        job.run_at = time.time()
        self.store.save(job)
        return await self.fly(self.s.ws_url, job.image_tag, runlog, job.flight_timeout_s,
                              self.s.arming_timeout_s, on_telemetry=on_telemetry)

    def _finalize(self, job, ended_by, outcome, detail, clip):
        return fin.finalize(self.store.dir(job), job_id=job.id, ended_by=ended_by,
                            outcome=outcome.kind if outcome else None, detail=detail,
                            done_line=bool(outcome and outcome.done_line),
                            truth=self._load_truth(), site=self.s.site, clip_dir=clip,
                            drone_sitl_dir=self.s.drone_sitl_dir)

    async def _cleanup(self, job):
        """Remove what this job brought in, keep its data. True if the sim is down."""
        ok = True
        try:
            if job.image_tag:
                for name in await self.docker.containers_of(job.image_tag):
                    await self.docker.rm_force(name)
            if job.owns_sim:
                ok = await self.sim.stop()
            if not self.s.keep_image:
                if job.image_tag:
                    await self.docker.rmi(job.image_tag)
                if job.source == "registry" and job.owns_sim and not job.image_preexisting:
                    await self.docker.rmi(job.image)
        except Exception:                           # noqa: BLE001
            log.exception("cleanup of %s", job.id)
            ok = False
        return ok

    def _prune(self, also_keep=None):
        keep = {j.id for j in self.store.all() if j.state not in TERMINAL} | {also_keep}
        for jid in retention.prune(self.s.runs_dir, self.s.data_retention_gb * GB, keep):
            self.store.forget(jid)
```

- [ ] **Step 5: รันให้ผ่าน** — `conda run -n drone python -m pytest -q tests/test_worker.py` → `17 passed` · แล้วรันทั้งหมด `conda run -n drone python -m pytest -q`
- [ ] **Step 6: Commit** — `git add flight_service/worker.py tests/fakes.py tests/test_worker.py && git commit -m "feat: worker pipeline -- journal, finalize on every end, kill, recover, retention"`

---

### Task 10: app (6 endpoint) + `__main__`

**Files:** Create `flight_service/app.py`, `flight_service/__main__.py`, `tests/conftest.py` · Test `tests/test_app.py`

**Interfaces:**
- Consumes: Worker (`recover run_forever submit queued accepting kill health current phase`), `JobStore`, `check_ref`, `FILES`, `TERMINAL`
- Produces: `create_app(settings, store, worker)`, `build(settings)`, `main()` · `POST /jobs`: `application/json` = registry · Content-Type อื่น → `create_from_upload` (ส่วน A ตอบ `415`, B1 ทำจริง) · `refuse_if_full()` → `503` degraded / `409` busy · ตรวจซ้ำทันทีก่อน `store.new` (ไม่มี `await` คั่น) กันสอง request ได้ช่องเดียวกัน

- [ ] **Step 1: `tests/conftest.py`**

```python
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest
import uvicorn


@pytest.fixture
def serve():
    """serve(app) -> base URL of the app on a real uvicorn in a thread."""
    running = []

    def start(app):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        running.append((server, thread))
        return f"http://127.0.0.1:{port}"

    yield start
    for server, thread in running:
        server.should_exit = True
        thread.join(timeout=5)


def http(method, url, token=None, body=None, raw=False, ctype=None):
    """(status, parsed JSON | bytes)."""
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", ctype or "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = r.read()
            return r.status, payload if raw else json.loads(payload)
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, payload if raw else json.loads(payload or b"{}")
```

- [ ] **Step 2: เขียนเทสต์ที่ fail**

`tests/test_app.py`:
```python
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
        self.current, self.phase, self.max_pending = None, "idle", 1

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
        return self.phase != "degraded" and len(self.queued()) < self.max_pending

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
```

- [ ] **Step 3: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.app'`

- [ ] **Step 4: เขียนโค้ด**

`flight_service/app.py`:
```python
"""HTTP API (design 3): six endpoints, one job each. Bearer token on
everything but /healthz."""
import asyncio
import hmac
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import policy
from .jobs import FILES, TERMINAL

MAX_BODY = 4096
MEDIA = {".mp4": "video/mp4", ".jsonl": "application/x-ndjson", ".json": "application/json",
         ".log": "text/plain", ".txt": "text/plain"}


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str = Field(max_length=512)
    flight_timeout_s: int | None = None


def create_app(settings, store, worker):
    expected = f"Bearer {settings.token}".encode()

    def auth(request: Request):
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected):
            raise HTTPException(401, "missing or wrong bearer token")

    @asynccontextmanager
    async def lifespan(app):
        await worker.recover()
        task = asyncio.create_task(worker.run_forever())
        yield
        task.cancel()

    app = FastAPI(title="flight-service", lifespan=lifespan)

    def job_or_404(job_id):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        return job

    def flight_seconds(value):
        flight_s = value or settings.default_flight_s
        if not 30 <= flight_s <= settings.max_flight_s:
            raise HTTPException(400, f"flight_timeout_s must be 30..{settings.max_flight_s}")
        return flight_s

    receiving = [0]          # uploads still streaming in; each will need a pending slot (B1)

    def refuse_if_full():
        """None if a new job fits, else the response to send (design 5).
        Called again right before store.new with no await in between, so
        two requests can never both take the last slot."""
        if worker.phase == "degraded":
            return JSONResponse({"detail": "degraded"}, status_code=503)
        if not worker.accepting() or len(worker.queued()) + receiving[0] >= settings.max_pending:
            return JSONResponse({"detail": "busy",
                                 "current_job": worker.current.id if worker.current else None,
                                 "pending": [j.id for j in worker.queued()]}, status_code=409)
        return None

    def accepted(job):
        worker.submit(job)
        return {"job_id": job.id, "state": job.state, "source": job.source}

    async def create_from_registry(request):
        refused = refuse_if_full()
        if refused:
            return refused
        body = await request.body()
        if len(body) > MAX_BODY:
            raise HTTPException(413, f"body over {MAX_BODY} bytes")
        try:
            req = JobRequest.model_validate_json(body)
        except ValidationError as e:
            raise HTTPException(400, f"bad request: {e.errors(include_url=False)}")
        bad = policy.check_ref(req.image, settings.allowed_images)
        if bad:
            raise HTTPException(*bad)
        flight_s = flight_seconds(req.flight_timeout_s)
        refused = refuse_if_full()          # re-check: the slot may have gone while we read
        if refused:
            return refused
        return accepted(store.new(req.image, flight_s))

    async def create_from_upload(request):        # part B1
        raise HTTPException(415, "send JSON {\"image\": ...}")

    @app.get("/healthz")
    def healthz():
        return worker.health()

    @app.post("/jobs", status_code=202, dependencies=[Depends(auth)])
    async def create(request: Request):
        """JSON = image on a registry; anything else = an uploaded image file."""
        if request.headers.get("content-type", "").startswith("application/json"):
            return await create_from_registry(request)
        return await create_from_upload(request)

    @app.get("/jobs", dependencies=[Depends(auth)])
    def list_jobs():
        return {"jobs": [j.summary() for j in store.all()[:50]]}

    @app.get("/jobs/{job_id}", dependencies=[Depends(auth)])
    def get_job(job_id: str):
        return job_or_404(job_id).public()

    @app.post("/jobs/{job_id}/kill", dependencies=[Depends(auth)])
    async def kill(job_id: str):
        job = job_or_404(job_id)
        if job.state in TERMINAL or not worker.kill(job):
            raise HTTPException(409, f"job is {job.state}; nothing to kill")
        deadline = time.monotonic() + settings.kill_wait_s
        while job.state not in TERMINAL and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        return JSONResponse(job.public(), status_code=200 if job.state in TERMINAL else 202)

    @app.get("/jobs/{job_id}/files/{name}", dependencies=[Depends(auth)])
    def get_file(job_id: str, name: str):
        path = store.dir(job_or_404(job_id)) / name
        if name not in FILES or not path.is_file():
            raise HTTPException(404, "no such file for this job")
        return FileResponse(path, media_type=MEDIA.get(path.suffix, "application/octet-stream"),
                            filename=name)

    return app
```

`flight_service/__main__.py`:
```python
"""python -m flight_service -- everything wired for real."""
import logging

import uvicorn

from .app import create_app
from .config import Settings
from .dockerctl import Docker
from .jobs import JobStore
from .sim import SimControl
from .sitl import Sitl
from .worker import Worker


def build(settings):
    store = JobStore(settings.runs_dir)
    worker = Worker(settings, store, Docker(), SimControl(settings), Sitl(settings.web_url))
    return create_app(settings, store, worker)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    uvicorn.run(build(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: รันให้ผ่าน** — `conda run -n drone python -m pytest -q` → ทั้งหมดผ่าน
- [ ] **Step 6: Commit** — `git add flight_service/app.py flight_service/__main__.py tests/conftest.py tests/test_app.py && git commit -m "feat: HTTP API -- six endpoints, bearer auth, kill returns partial results"`

---

### Task 11: แก้ drone-sitl (`DRONE_SITL_DOCKER_RUN_ARGS`) + หลักฐาน

**Files:**
- Modify: `~/pai/drone-sitl/joystick-server.py` (`import shlex` ระหว่าง `import queue`/`import shutil` · `AgentRun._spawn`)
- Test: `~/pai/drone-sitl/streaming/tests/test_web_ui.py` (ต่อจาก `test_agent_run_docker_omits_gpus_flag_when_toolkit_unavailable`)
- Create: `~/pai/drone-sitl/docs/changes/2026-10-05-docker-run-args.md`, `~/pai/flight-service/docs/drone-sitl-changes.md`

- [ ] **Step 1: บันทึกสถานะก่อนแก้** — `cd ~/pai/drone-sitl && git status --short && git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD` → ต้อง clean และเป็น `feat/website-usd-map-testgs` ที่ `326290e` (ถ้าไม่ใช่ ให้หยุดถาม)

- [ ] **Step 2: เขียนเทสต์ที่ fail**

```python
def test_agent_run_docker_appends_extra_run_args_from_env(monkeypatch):
    """flight-service starts the web server with resource limits and
    --cap-drop ALL for images it pulled (flight-service docs/design.md 8)."""
    js = _load_server()
    calls = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            calls.append(argv)
            self.stdout = iter([])
        def poll(self):
            return None

    monkeypatch.setattr(js.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(js.shutil, "which", lambda name: None)
    monkeypatch.setenv("DRONE_SITL_DOCKER_RUN_ARGS", "--memory 24g --cap-drop ALL")

    run = js.AgentRun(_FakeLoopThread(), "python", "127.0.0.1", 8090, 8080)
    run.run("docker", "submission-foo-20260908-120000")
    _fly_to_offboard(run)

    argv = calls[0]
    assert argv[:9] == ["docker", "run", "--rm", "--network", "host",
                        "--memory", "24g", "--cap-drop", "ALL"]
    assert argv[-3] == "--name" and argv[-1] == "submission-foo-20260908-120000"
```
Run: `cd ~/pai/drone-sitl && conda run -n drone python -m pytest -q streaming/tests/test_web_ui.py -k docker` → เทสต์ใหม่ FAIL

- [ ] **Step 3: แก้โค้ด** (`_spawn`)

```python
            gpu_flags = (["--gpus", "all"]
                        if shutil.which("nvidia-container-runtime") else [])
            # Extra `docker run` flags from whoever started this server --
            # flight-service passes resource limits and --cap-drop ALL for
            # images it pulled. Unset = exactly the old command line.
            extra = shlex.split(os.environ.get("DRONE_SITL_DOCKER_RUN_ARGS", ""))
            self._proc = subprocess.Popen(
                ["docker", "run", "--rm", "--network", "host", *gpu_flags, *extra,
                 "--name", self._container_name, self.file],
```

- [ ] **Step 4: เทสต์ drone-sitl ทั้งชุด** — `conda run -n drone python -m pytest -q streaming/tests competition/tests examples/competition-submission` → ผ่านทั้งหมด จดตัวเลข

- [ ] **Step 5: Commit drone-sitl**

```bash
cd ~/pai/drone-sitl
git add joystick-server.py streaming/tests/test_web_ui.py
git commit -m "feat(web): DRONE_SITL_DOCKER_RUN_ARGS adds flags to the agent's docker run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: หลักฐาน 2 ที่ (เติม hash/ตัวเลขจริง)**

`~/pai/drone-sitl/docs/changes/2026-10-05-docker-run-args.md`:
```markdown
# 2026-10-05: `DRONE_SITL_DOCKER_RUN_ARGS` สำหรับ `docker run` ของ agent

- **อนุมัติโดย:** เจ้าของ flight-service, 2026-10-05 (`~/pai/flight-service/docs/design.md` หัวข้อ 8 และ 11 ข้อ 5)
- **ทำไม:** flight-service รัน image ของคนอื่นแบบอัตโนมัติ ต้องจำกัด memory/pids และตัด capability ของ container ได้ โดยพฤติกรรมเดิมของเว็บไม่เปลี่ยน
- **แก้อะไร:** `joystick-server.py` `AgentRun._spawn` อ่าน env `DRONE_SITL_DOCKER_RUN_ARGS` (`shlex.split`) ใส่ต่อหลัง `--gpus all` ก่อน `--name` · ไม่ตั้ง env = command line เดิมทุกตัว
- **เทสต์:** `streaming/tests/test_web_ui.py::test_agent_run_docker_appends_extra_run_args_from_env` (ใหม่) · ทั้งชุด `<N> passed`
- **commit:** `<hash>` บน `feat/website-usd-map-testgs` (ก่อนแก้ HEAD = `326290e`) · ยังไม่ push
- **ย้อนกลับ:** `git revert <hash>` หรือไม่ตั้ง env

## diff
<ผลของ `git show <hash> -- joystick-server.py`>
```

`~/pai/flight-service/docs/drone-sitl-changes.md`: เนื้อหาเดียวกัน + ลิงก์ไปไฟล์ใน drone-sitl + ค่าที่ flight-service ส่ง (`DEFAULT_RUN_ARGS`)

```bash
cd ~/pai/drone-sitl && mkdir -p docs/changes && git add docs/changes/2026-10-05-docker-run-args.md && git commit -m "docs: record the approved docker-run-args change

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
cd ~/pai/flight-service && git add docs/drone-sitl-changes.md && git commit -m "docs: record the approved drone-sitl change"
```

---

### Task 12: scripts + smoke test

**Files:** Create `scripts/run-service.sh`, `scripts/stop-service.sh`, `scripts/mock-caller.sh`

- [ ] **Step 1: `scripts/run-service.sh`**

```bash
#!/usr/bin/env bash
# run-service.sh -- start flight-service in the background. Idempotent.
# pid -> run/service.pid, log -> logs/service.console
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
mkdir -p logs run
say() { echo "run-service: $*"; }
if [[ -f run/service.pid ]] && kill -0 "$(cat run/service.pid)" 2>/dev/null; then
    say "already running (pid $(cat run/service.pid))"; exit 0
fi
[[ -f .env ]] || { say "no .env -- cp .env.example .env and set RUNNER_TOKEN" >&2; exit 1; }
set -a; source .env; set +a
# The env's own python, not `conda run`: the saved pid is then the server's
# and stop-service.sh never needs a pattern kill.
PY="$(conda run -n "${CONDA_ENV:-drone}" python -c 'import sys; print(sys.executable)')"
nohup "$PY" -u -m flight_service > logs/service.console 2>&1 &
echo $! > run/service.pid
URL="http://${RUNNER_HOST:-127.0.0.1}:${RUNNER_PORT:-8095}/healthz"
for _ in $(seq 1 20); do curl -sf -o /dev/null "$URL" && break; sleep 1; done
if curl -sf "$URL"; then echo; say "up (pid $(cat run/service.pid))"
else say "not answering -- see logs/service.console" >&2; exit 1; fi
```

- [ ] **Step 2: `scripts/stop-service.sh`**

```bash
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
```

- [ ] **Step 3: `scripts/mock-caller.sh`** (ทำตัวเป็นพี่ต้น)

```bash
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
    line="$(python3 -c '
import json, sys
j = json.load(sys.stdin); t = j.get("telemetry") or {}; sl = j.get("score_live") or {}
tail = (j.get("log_tail") or [""])[-1]
print(f"{j[\"state\"]} {j[\"elapsed_s\"]:.0f}s alt={t.get(\"alt_m\")} lat={t.get(\"lat\")} lon={t.get(\"lon\")} "
      f"agent={t.get(\"agent_state\")} trucks={sl.get(\"trucks_found\")}/{sl.get(\"trucks_total\")} | {tail[:80]}")
' <<<"$s")"
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
```

- [ ] **Step 4: smoke test (ไม่เปิด sim)**

```bash
chmod +x scripts/*.sh
cp .env.example .env && sed -i "s/^RUNNER_TOKEN=.*/RUNNER_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')/" .env
./scripts/run-service.sh                                  # {"ok":true,"phase":"idle"} + up (pid N)
set -a; source .env; set +a
curl -s -o /dev/null -w '%{http_code}\n' localhost:8095/jobs                     # 401
curl -s -X POST localhost:8095/jobs -H "Authorization: Bearer $RUNNER_TOKEN" \
     -H 'Content-Type: application/json' -d '{"image":"postgres:15.4"}'           # 403
ss -ltn | grep 8095                                       # 127.0.0.1:8095 เท่านั้น
./scripts/stop-service.sh                                 # stopped
```

- [ ] **Step 5: Commit** — `git add scripts && git commit -m "feat: run/stop scripts and a mock caller"`
- [ ] **Step 6:** `docs/progress.md` ขั้น 3 = ✅ + จำนวนเทสต์ → commit → **หยุดรออนุมัติ**

---

### Task 13: ทดสอบจริง (ขั้น 4 · ต้องได้อนุมัติก่อน)

**Files:** Create `docs/verification.md`

- [ ] **Step 1: ถามเจ้าของก่อน push** ว่าจะให้ repo บน Docker Hub เป็น **private หรือ public** (image มี weights) แล้วจึงทำ

```bash
docker tag submission-truck-detector-20260929-214240:latest perkiepai/truck-detector:20260929-214240
docker push perkiepai/truck-detector:20260929-214240
```
tag นี้มีบนเครื่องก่อนเริ่มงาน → `image_preexisting=True` → runner ไม่ลบ (ถูกต้องตามกติกา "ลบเฉพาะสิ่งที่งานนั้นนำเข้ามา") ลบแค่ `submission-truck-detector-<ts ใหม่>`

- [ ] **Step 2: เช็กก่อนรัน** — `curl -sf localhost:8080/; curl -sf localhost:8090/` ต้องไม่ตอบ · `df -h /` ว่าง ≥ 40 GB

- [ ] **Step 3: รอบบินเต็ม** — `./scripts/run-service.sh && ./scripts/mock-caller.sh perkiepai/truck-detector:20260929-214240 600 | tee docs/verification-run1.log`
Expected: `pulling → booting → flying → done` · `ended_by=agent partial=false` · ไฟล์ครบ 10 ตัว · trucks_found 3/3 (ผลบินเดิม 2026-09-29)

- [ ] **Step 4: รอบ kill** — `KILL_AFTER_S=90 ./scripts/mock-caller.sh perkiepai/truck-detector:20260929-214240 600 | tee docs/verification-run2.log`
Expected: response ของ kill เป็น `killed`, `ended_by=kill`, `partial=true`, มี track ~90 s · `ffprobe mock-out/<id>/detections.mp4` เล่นได้

- [ ] **Step 5: ทางล้ม** — `./scripts/mock-caller.sh perkiepai/does-not-exist:0 60` → `failed / pull_failed` และ sim ปิดแล้ว

- [ ] **Step 6: ตรวจหลังทุกรอบ** — `curl -s localhost:8095/healthz` → `idle` · `:8080`/`:8090` ไม่ตอบ · `docker ps -a | grep submission-run` ว่าง · `docker images | grep submission-truck-detector-2026100` ว่าง · ระหว่างบินรอบ 1: `docker inspect $(docker ps -q --filter name=submission-run) --format '{{.HostConfig.Memory}} {{.HostConfig.CapDrop}}'` ต้องเห็นค่าจาก `DRONE_SITL_DOCKER_RUN_ARGS` · `du -sh data/runs`

- [ ] **Step 7: ถ้าเจอ** — `--cap-drop ALL` ทำให้ agent/GPU พัง → เอา flag ออกจาก `DEFAULT_RUN_ARGS` แล้วบันทึกใน `docs/drone-sitl-changes.md` · `run_refused: no MAVLink link` (เว็บเปิดก่อน PX4) → ใน `_boot` เรียก `sim.stop()` + `sim.start_web()` ก่อน `start_sim()` และเพิ่มเทสต์ใน `test_worker.py`

- [ ] **Step 8: `docs/verification.md`** — คำสั่ง, timeline ของแต่ละ state, score/ระยะทาง/เวลา, รายการไฟล์, ผลตรวจ cleanup, ปัญหาที่เจอ → commit → progress.md → **หยุดรออนุมัติ**

---

### Task 14: README (ขั้น 5)

- [ ] `README.md`: ทำอะไร (3 บรรทัด) · ติดตั้ง (`.env`) · เปิด/ปิด · API 6 endpoint พร้อม curl (คัดจาก design 3) · state/reason (design 4) · ไฟล์ข้อมูลและ journal (design 13.4) · score v0 · การลบ image/การเก็บ data 10 GB · ความเสี่ยงที่เหลือ (design 8, 13.7) · แก้ปัญหา (`sim_busy` → `stop-website.sh` · `degraded` → ปิด sim เองแล้ว restart service) · เทสต์
- [ ] ทำตาม README จากศูนย์ 1 รอบ (smoke ของ Task 12) → commit → progress.md → **หยุดรออนุมัติ**

---

## ส่วน B: รับไฟล์ image ผ่าน curl (design 12 · ทั้งสองแบบ)

### B1: รับไฟล์ (stream ลงดิสก์) ผ่าน `POST /jobs`

**Files:** Create `flight_service/uploads.py` · Modify `flight_service/app.py` (`create_from_upload`) · Test `tests/test_uploads.py`, ต่อท้าย `tests/test_app.py`

**Interfaces:**
- Produces: `UploadError(status, detail)`, `async receive(chunks, dest, expected, limit) -> int` · `BUNDLE_MAX = 200 * 1024 ** 2` · `NAME_RE`
- `POST /jobs?kind=image|bundle&name=<name>[&flight_timeout_s=]` body = ไฟล์ (Content-Type อะไรก็ได้ที่ไม่ใช่ JSON) · ไม่มี `kind` = `415` เหมือนเดิม · ช่องรอเต็ม = `409` ก่อนรับไฟล์

- [ ] **Step 1: เขียนเทสต์ที่ fail**

`tests/test_uploads.py`:
```python
import asyncio

import pytest

from flight_service.uploads import UploadError, receive


async def chunks(*parts):
    for p in parts:
        yield p


def test_receive_writes_exactly_the_declared_bytes(tmp_path):
    dest = tmp_path / "u" / "a.tar"
    assert asyncio.run(receive(chunks(b"abc", b"de"), dest, 5, 100)) == 5
    assert dest.read_bytes() == b"abcde" and not list(tmp_path.glob("u/*.part"))


@pytest.mark.parametrize("parts,expected,limit,status", [
    ((b"abc",), 5, 100, 400),          # short
    ((b"abcdef",), 5, 100, 413),       # longer than declared
    ((b"abcdef",), 10, 4, 413),        # over the limit
])
def test_receive_rejects_and_leaves_nothing(tmp_path, parts, expected, limit, status):
    dest = tmp_path / "a.tar"
    with pytest.raises(UploadError) as e:
        asyncio.run(receive(chunks(*parts), dest, expected, limit))
    assert e.value.status == status and list(tmp_path.iterdir()) == []
```

ต่อท้าย `tests/test_app.py`:
```python
def upload(url, data, query="kind=image&name=truck", ctype="application/octet-stream"):
    return http("POST", f"{url}/jobs?{query}", TOKEN, data, ctype=ctype)


def test_upload_creates_a_job_with_the_file(tmp_path, serve):
    url, store, worker = make(tmp_path, serve, min_free_gb=0)
    code, body = upload(url, b"x" * 1000)
    assert code == 202 and body["source"] == "upload"
    job = store.get(body["job_id"])
    assert (job.upload_kind, job.upload_name, job.image) == ("image", "truck", "upload:image:truck")
    assert (store.dir(job) / "upload.tar").read_bytes() == b"x" * 1000
    assert worker.submitted == [job.id]
    assert list((tmp_path / "uploads").iterdir()) == []


def test_upload_rejections(tmp_path, serve):
    url, _, _ = make(tmp_path, serve, min_free_gb=0, max_upload_gb=1e-6)   # ~1 KB
    assert upload(url, b"x", "kind=zip&name=truck")[0] == 400
    assert upload(url, b"x", "kind=image&name=../evil")[0] == 400
    assert upload(url, b"x" * 2000)[0] == 413
    assert upload(url, b"x" * 10, "kind=bundle&name=t&flight_timeout_s=5")[0] == 400
    assert upload(url, b"x" * 10)[0] == 202
    assert upload(url, b"x" * 10, "kind=bundle&name=t2")[0] == 409      # slot taken: file refused
    assert list((tmp_path / "uploads").glob("*")) == []


def test_upload_needs_disk(tmp_path, serve):
    url, _, _ = make(tmp_path, serve, min_free_gb=10 ** 6)
    assert upload(url, b"x" * 10)[0] == 507
```

- [ ] **Step 2: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.uploads'`

- [ ] **Step 3: เขียนโค้ด**

`flight_service/uploads.py`:
```python
"""Receive an uploaded file as a stream straight to disk, counting bytes
(design 12). The body never sits in memory; a bad upload leaves nothing."""
import os
from pathlib import Path

BUNDLE_MAX = 200 * 1024 ** 2          # drone-sitl's AGENT_DOCKER_MAX_BYTES
NAME_RE = r"[a-z0-9][a-z0-9_-]{0,63}"


class UploadError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


async def receive(chunks, dest, expected, limit):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    n = 0
    try:
        with open(part, "wb") as f:
            async for chunk in chunks:
                n += len(chunk)
                if n > min(expected, limit):
                    raise UploadError(413, f"body larger than its Content-Length or the {limit} byte limit")
                f.write(chunk)
        if n != expected:
            raise UploadError(400, f"got {n} of {expected} bytes")
        os.replace(part, dest)
        return n
    except BaseException:
        part.unlink(missing_ok=True)
        raise
```

ใน `flight_service/app.py` เพิ่ม import `os, re, secrets, shutil`, `from .config import GB`, `from . import uploads` แล้วแทน `create_from_upload` (ไฟล์ที่กำลังส่งเข้ามานับเป็นงานในช่องรอผ่าน `receiving` จึงไม่มีสองไฟล์ใหญ่ส่งซ้อนกัน):
```python
    async def create_from_upload(request):
        q = request.query_params
        kind, name = q.get("kind", ""), q.get("name", "")
        if kind not in ("image", "bundle"):
            raise HTTPException(415 if not kind else 400,
                                "send JSON {\"image\": ...}, or a file with ?kind=image|bundle&name=")
        if not re.fullmatch(uploads.NAME_RE, name):
            raise HTTPException(400, f"name must match {uploads.NAME_RE}")
        try:
            flight_s = flight_seconds(int(q["flight_timeout_s"]) if "flight_timeout_s" in q else None)
        except ValueError:
            raise HTTPException(400, "flight_timeout_s must be an integer")
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            raise HTTPException(411, "Content-Length required (curl -T sends it)")
        size = int(length)
        limit = int(settings.max_upload_gb * GB) if kind == "image" else uploads.BUNDLE_MAX
        if size > limit:
            raise HTTPException(413, f"file over {limit} bytes")
        if shutil.disk_usage(settings.runs_dir).free < settings.min_free_gb * GB + 2 * size:
            raise HTTPException(507, "not enough free disk for this upload")
        refused = refuse_if_full()          # before taking a single byte of the file
        if refused:
            return refused
        staging = settings.uploads_dir / f"{secrets.token_hex(8)}.tar"
        receiving[0] += 1                   # holds the slot while the file streams in
        try:
            await uploads.receive(request.stream(), staging, size, limit)
        except uploads.UploadError as e:
            raise HTTPException(e.status, e.detail)
        finally:
            receiving[0] -= 1
        refused = refuse_if_full()          # degraded meanwhile? then drop the file
        if refused:
            staging.unlink(missing_ok=True)
            return refused
        job = store.new(f"upload:{kind}:{name}", flight_s, source="upload",
                        upload_kind=kind, upload_name=name)
        os.replace(staging, store.dir(job) / "upload.tar")
        return accepted(job)
```

- [ ] **Step 4: รันให้ผ่าน** — `conda run -n drone python -m pytest -q tests/test_uploads.py tests/test_app.py`
- [ ] **Step 5: Commit** — `git add flight_service/uploads.py flight_service/app.py tests/test_uploads.py tests/test_app.py && git commit -m "feat: accept an uploaded image file on POST /jobs"`

### B2: แบบ image archive (`docker save` → `docker load`)

**Files:** Create `flight_service/archive.py` · Modify `flight_service/dockerctl.py` (`load`, `tag`), `flight_service/worker.py` (`_acquire`, `_load`, `_load_image`, `_load_bundle` placeholder ที่ B3 แทน), `tests/fakes.py` (`FakeDocker.load/tag`) · Test `tests/test_archive.py`, ต่อท้าย `tests/test_dockerctl.py`, `tests/test_worker.py`

**Interfaces:**
- Produces: `repo_tags(path) -> list[str]` (raise `JobFailed("archive_rejected")`) · `Docker.load(path, timeout) -> list[str]` (raise `load_failed`) · `Docker.tag(src, dst)` (raise `load_failed`)

- [ ] **Step 1: เขียนเทสต์ที่ fail**

`tests/test_archive.py`:
```python
import io
import json
import tarfile

import pytest

from flight_service.archive import repo_tags
from flight_service.jobs import JobFailed


def make_tar(path, manifest, mode="w"):
    with tarfile.open(path, mode) as tar:
        for name, data in (("blobs/sha256/aa", b"layer"), ("manifest.json", json.dumps(manifest).encode())):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize("suffix,mode", [(".tar", "w"), (".tar.gz", "w:gz")])
def test_repo_tags(tmp_path, suffix, mode):
    p = tmp_path / f"a{suffix}"
    make_tar(p, [{"Config": "c", "RepoTags": ["truck:1"], "Layers": []}], mode)
    assert repo_tags(p) == ["truck:1"]


def test_untagged_archive_is_fine(tmp_path):
    make_tar(tmp_path / "a.tar", [{"Config": "c", "RepoTags": None, "Layers": []}])
    assert repo_tags(tmp_path / "a.tar") == []


@pytest.mark.parametrize("manifest", [[], [{"RepoTags": ["a:1"]}, {"RepoTags": ["b:1"]}], {"x": 1}])
def test_not_exactly_one_image_is_rejected(tmp_path, manifest):
    make_tar(tmp_path / "a.tar", manifest)
    with pytest.raises(JobFailed) as e:
        repo_tags(tmp_path / "a.tar")
    assert e.value.reason == "archive_rejected"


def test_not_an_archive(tmp_path):
    (tmp_path / "a.tar").write_bytes(b"not a tar")
    with pytest.raises(JobFailed) as e:
        repo_tags(tmp_path / "a.tar")
    assert e.value.reason == "archive_rejected"
```

ต่อท้าย `tests/test_dockerctl.py`:
```python
import pytest

from flight_service.jobs import JobFailed


def test_load_parses_what_was_loaded():
    out = "Loaded image: truck:1\nLoaded image ID: sha256:abc\n"
    d = Docker(Rec({("load", "-i"): (0, out)}))
    assert asyncio.run(d.load("/x.tar", 60)) == ["truck:1", "sha256:abc"]


def test_load_and_tag_failures_raise():
    d = Docker(Rec({("load", "-i"): (1, "invalid tar header"), ("tag", "a"): (1, "no such image")}))
    for coro in (d.load("/x.tar", 60), d.tag("a", "b")):
        with pytest.raises(JobFailed) as e:
            asyncio.run(coro)
        assert e.value.reason == "load_failed"
```

เพิ่มใน `FakeDocker` (`tests/fakes.py`):
```python
    async def load(self, path, timeout):
        self.calls.append(("load", str(path)))
        return ["truck:1"]

    async def tag(self, src, dst):
        self.calls.append(("tag", src, dst))
```

ต่อท้าย `tests/test_worker.py`:
```python
import io
import tarfile


def upload_job(store, kind="image", tags=("truck:1",)):
    job = store.new(f"upload:{kind}:truck", 600, source="upload", upload_kind=kind, upload_name="truck")
    with tarfile.open(store.dir(job) / "upload.tar", "w") as tar:
        data = json.dumps([{"Config": "c", "RepoTags": list(tags), "Layers": []}]).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return job


def test_image_archive_upload_flies_and_cleans_up(tmp_path):
    docker, sim = FakeDocker(), FakeSim()
    _, store, w = setup(tmp_path, docker=docker, sim=sim)
    job = upload_job(store)
    asyncio.run(w.run_job(job))
    assert job.state == DONE, (job.reason, job.detail)
    assert job.image_tag.startswith("submission-truck-")
    assert ("tag", "truck:1", job.image_tag) in docker.calls
    assert ("rmi", "truck:1") in docker.calls                  # the archive's own tag
    assert ("rmi", job.image_tag) in docker.calls              # cleanup
    assert ("rmi", job.image) not in docker.calls
    assert not (store.dir(job) / "upload.tar").exists()
    assert sim.calls == ["busy", "start_sim", "wait_px4_ready", "stop"]
    ev = list(read_jsonl(store.dir(job) / "events.jsonl"))
    assert [e["state"] for e in ev if e["kind"] == "state"][0] == "loading"


def test_archive_tag_that_exists_is_rejected(tmp_path):
    docker = FakeDocker(exists=True)
    _, store, w = setup(tmp_path, docker=docker)
    job = upload_job(store, tags=("competition-base:latest",))
    asyncio.run(w.run_job(job))
    assert (job.state, job.reason, job.failed_in) == (FAILED, "archive_rejected", "loading")
    assert not any(c[0] == "load" for c in docker.calls)
    assert ("rmi", "competition-base:latest") not in docker.calls
    assert not (store.dir(job) / "upload.tar").exists()
```

- [ ] **Step 2: รันให้เห็นว่า fail** — FAIL `No module named 'flight_service.archive'`

- [ ] **Step 3: เขียนโค้ด**

`flight_service/archive.py`:
```python
"""Look inside a `docker save` archive before `docker load` runs it: one
image, and which tags it would create (design 12). Reads only metadata;
nothing is extracted to disk."""
import json
import tarfile

from .jobs import JobFailed


def repo_tags(path):
    try:
        with tarfile.open(path, "r:*") as tar:
            member = tar.getmember("manifest.json")
            data = json.load(tar.extractfile(member))
    except KeyError:
        raise JobFailed("archive_rejected", "no manifest.json: not a `docker save` archive")
    except (tarfile.TarError, OSError, ValueError) as e:
        raise JobFailed("archive_rejected", f"unreadable archive: {e}")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise JobFailed("archive_rejected", "the archive must hold exactly one image")
    return list(data[0].get("RepoTags") or [])
```

ใน `flight_service/dockerctl.py` (เพิ่ม `from .jobs import JobFailed`) เพิ่มใน `Docker`:
```python
    async def load(self, path, timeout):
        """docker load -i; what it loaded (names, or image IDs if untagged)."""
        code, out = await self.run("docker", "load", "-i", str(path), timeout=timeout)
        if code != 0:
            raise JobFailed("load_failed", tail(out))
        loaded = []
        for line in out.splitlines():
            for prefix in ("Loaded image ID: ", "Loaded image: "):
                if line.startswith(prefix):
                    loaded.append(line[len(prefix):].strip())
                    break
        return loaded

    async def tag(self, src, dst):
        code, out = await self.run("docker", "tag", src, dst, timeout=30)
        if code != 0:
            raise JobFailed("load_failed", tail(out))
```

ใน `flight_service/worker.py` (เพิ่ม `from . import archive` และ `LOADING` ใน import ของ `.jobs`) แทน `_acquire` และเพิ่ม:
```python
    async def _acquire(self, job, runlog):
        """Put the image on this box as job.image_tag."""
        if job.source == "registry":
            await self._pull(job, runlog)
        elif job.source == "upload":
            await self._load(job, runlog)
        else:
            raise JobFailed("unsupported_source", job.source)

    async def _load(self, job, runlog):
        await self._precheck(job, runlog, LOADING)
        upload = self.store.dir(job) / "upload.tar"
        try:
            if job.upload_kind == "image":
                await self._load_image(job, upload)
            elif job.upload_kind == "bundle":
                await self._load_bundle(job, upload)
            else:
                raise JobFailed("unsupported_source", f"upload kind {job.upload_kind!r}")
            self.store.save(job)
        finally:
            upload.unlink(missing_ok=True)          # up to 16 GB: not kept for the flight
        await self._check_size(job)

    async def _load_image(self, job, upload):
        tags = await asyncio.to_thread(archive.repo_tags, upload)
        for t in tags:
            if await self.docker.exists(t):
                raise JobFailed("archive_rejected",
                                f"archive tag {t} already exists on this box and would be overwritten")
        loaded = await self.docker.load(upload, self.s.pull_timeout_s)
        if not loaded:
            raise JobFailed("load_failed", "docker load reported nothing loaded")
        tag = f"submission-{job.upload_name}-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            await self.docker.tag(loaded[0], tag)
            job.image_tag = tag
        finally:
            for t in tags:                          # untag what the archive brought in;
                await self.docker.rmi(t)            # the image stays under our own tag

    async def _load_bundle(self, job, upload):     # replaced in B3
        raise JobFailed("unsupported_source", "bundle uploads come in B3")
```

- [ ] **Step 4: รันให้ผ่าน** — `conda run -n drone python -m pytest -q`
- [ ] **Step 5: Commit** — `git add flight_service/archive.py flight_service/dockerctl.py flight_service/worker.py tests && git commit -m "feat: fly an uploaded docker save archive"`

### B3: แบบ build bundle (ส่งต่อให้ `:8090/agent/upload-docker`)

**Files:** Modify `flight_service/sitl.py` (`_send_file`, `upload_bundle`), `flight_service/worker.py` (`_load_bundle`), `tests/fakes.py` (`FakeSitl.upload_bundle`) · Test ต่อท้าย `tests/test_sitl.py`, `tests/test_worker.py`

**Interfaces:**
- Produces: `_send_file(url, path, timeout)`, `Sitl(web_url, call=_call, send_file=_send_file)` → async `upload_bundle(path, name, timeout) -> tag` (raise `load_failed`)

- [ ] **Step 1: เขียนเทสต์ที่ fail**

ต่อท้าย `tests/test_sitl.py`:
```python
def test_upload_bundle_streams_the_file(tmp_path):
    p = tmp_path / "upload.tar"
    p.write_bytes(b"tar")
    seen = []

    def send_file(url, path, timeout):
        seen.append((url, str(path), timeout))
        return 200, {"stored": "truck-1.tar", "image_tag": "submission-truck-20261005-120000"}

    tag = asyncio.run(Sitl("http://w", send_file=send_file).upload_bundle(p, "truck", 99))
    assert tag == "submission-truck-20261005-120000"
    assert seen == [("http://w/agent/upload-docker?name=truck.tar", str(p), 99)]


def test_upload_bundle_build_failure():
    with pytest.raises(JobFailed) as e:
        asyncio.run(Sitl("http://w", send_file=lambda u, p, t: (400, {"detail": "build failed",
                                                                       "log": ["pip: no such package"]}))
                    .upload_bundle("/x.tar", "truck", 5))
    assert e.value.reason == "load_failed" and "pip" in e.value.detail
```

เพิ่มใน `FakeSitl` (`tests/fakes.py`):
```python
    async def upload_bundle(self, path, name, timeout):
        assert os.path.exists(path)
        return f"submission-{name}-20261005-120000"
```

ต่อท้าย `tests/test_worker.py`:
```python
def test_bundle_upload_builds_through_drone_sitl(tmp_path):
    docker, sim = FakeDocker(), FakeSim()
    _, store, w = setup(tmp_path, docker=docker, sim=sim)
    job = upload_job(store, kind="bundle")
    asyncio.run(w.run_job(job))
    assert job.state == DONE, (job.reason, job.detail)
    assert job.image_tag == "submission-truck-20261005-120000"
    assert sim.calls == ONE                                  # web first, for the build
    assert ("rmi", job.image_tag) in docker.calls and not (store.dir(job) / "upload.tar").exists()
```

- [ ] **Step 2: รันให้เห็นว่า fail** — FAIL `TypeError: Sitl.__init__() got an unexpected keyword argument 'send_file'`

- [ ] **Step 3: เขียนโค้ด**

`flight_service/sitl.py` เพิ่ม (import `os`):
```python
def _send_file(url, path, timeout):
    """POST a file without reading it into memory (urllib streams a file
    object when Content-Length is given)."""
    with open(path, "rb") as f:
        req = urllib.request.Request(url, data=f, method="POST", headers={
            "Content-Length": str(os.path.getsize(path)),
            "Content-Type": "application/octet-stream"})
        return _open(req, timeout)
```
และใน `Sitl`:
```python
    def __init__(self, web_url, call=_call, send_file=_send_file):
        self.web, self.call, self.send_file = web_url.rstrip("/"), call, send_file

    async def upload_bundle(self, path, name, timeout):
        """drone-sitl's /agent/upload-docker: build a bundle (Dockerfile FROM
        competition-base) and tag it submission-<name>-<ts>."""
        url = f"{self.web}/agent/upload-docker?name={urllib.parse.quote(name + '.tar')}"
        code, body = await asyncio.to_thread(self.send_file, url, path, timeout)
        if code == 200 and body.get("image_tag"):
            return body["image_tag"]
        _fail("load_failed", code, body)
```

`flight_service/worker.py` แทน `_load_bundle`:
```python
    async def _load_bundle(self, job, upload):
        job.owns_sim = True
        self.store.save(job)
        await self.sim.start_web()
        job.image_tag = await self.sitl.upload_bundle(upload, job.upload_name, self.s.pull_timeout_s)
```

- [ ] **Step 4: รันให้ผ่าน** — `conda run -n drone python -m pytest -q`
- [ ] **Step 5: Commit** — `git add flight_service tests && git commit -m "feat: fly an uploaded build bundle via drone-sitl"`

### B4: ทดสอบจริงแบบอัปโหลด + เอกสาร

- [ ] **archive:** tag ชั่วคราวที่ไม่ชนของที่มี แล้ว save และลบ tag ทิ้ง (image จริงไม่หาย)
```bash
mkdir -p data/test-upload
docker tag submission-truck-detector-20260929-214240:latest truck-upload-test:1
docker save truck-upload-test:1 -o data/test-upload/truck.tar          # ~12.5 GB เช็ก df ก่อน
docker rmi truck-upload-test:1                                          # untag only
set -a; source .env; set +a
curl -s -X POST -T data/test-upload/truck.tar -H "Authorization: Bearer $RUNNER_TOKEN" \
     "localhost:8095/jobs?kind=image&name=truck-detector&flight_timeout_s=600"
```
แล้ว poll จนจบ (`done`) · ตรวจว่า `truck-upload-test:1` ไม่ค้าง, `submission-truck-detector-<ts>` ถูกลบ, `upload.tar` ไม่อยู่ · ลบ `data/test-upload/`
- [ ] **bundle:** `curl -s -X POST -T ~/pai/drone-sitl/examples/competition-submission/truck-detector.tar -H "Authorization: Bearer $RUNNER_TOKEN" "localhost:8095/jobs?kind=bundle&name=truck-detector"` → `done` (build ต้องโหลด torch ใช้เวลานาน)
- [ ] เพิ่มผลใน `docs/verification.md` + หัวข้อ "ส่งไฟล์" ใน README → commit → progress.md → **หยุดรออนุมัติ**
