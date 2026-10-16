> **ประวัติ ไม่ใช่สถานะปัจจุบัน:** เอกสารนี้เก็บไว้เป็นหลักฐานของงานที่ทำเสร็จแล้ว ไม่ได้อัปเดตตามโค้ด (เช่นยังพูดถึง `RUNNER_TOKEN` ที่ถอดแล้ว) สถานะจริงดู [../design.md](../../../design.md) และ [../progress.md](../../../progress.md)

# Stream สด (SSE) + client `flight.py` Implementation Plan (2026-10-06)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **ประตูอนุมัติ (ตามวิธีทำงานของโปรเจกต์นี้):** หยุดรออนุมัติหลัง Task 2 (server + เทสต์), หลัง Task 4 (client + เทสต์), **ก่อน**และหลัง Task 5 (รันจริง ใช้ GPU) และหลัง Task 6 (เอกสาร) · ห้ามเริ่มขั้นถัดไปเพราะ "น่าจะโอเค"

**Goal:** ผู้เรียกติดตามการบินได้สดผ่าน `GET /jobs/{id}/stream` (Server-Sent Events) และมี `scripts/flight.py` ไฟล์เดียวที่ส่งงาน ติดตาม ดึงไฟล์ผล แล้วบอกผลด้วย exit code

**Architecture:** `flight_service/stream.py` เป็น async generator ที่อ่าน `job.state` จากหน่วยความจำกับ `telemetry.jsonl` ของงานทุก 0.2 s แล้วแปลงเป็น event `state` / `telemetry` / `end` · `telemetry` มี `id` = เลขบรรทัด จึงต่อใหม่ด้วย `Last-Event-ID` ได้โดยไม่หายไม่ซ้ำ · `app.py` เพิ่ม route เดียว ไม่แตะ worker · client เป็นสคริปต์ standard library ที่ไม่ import อะไรจาก `flight_service/` คุยกับ service ผ่าน HTTP อย่างเดียว และถอยไป poll เองเมื่อไม่มี stream

**Tech Stack:** Python 3.11 (conda env `drone`) · FastAPI 0.141.1 / Starlette 1.3.1 / uvicorn 0.52.0 (h11) · pytest 9 · client: Python 3.8+ standard library (`urllib`, `http.client`, `argparse`) · ไม่ติดตั้ง package เพิ่ม

**Spec:** [`docs/superpowers/specs/2026-10-06-sse-client-design.md`](../specs/2026-10-06-sse-client-design.md) (หัวข้อ 4 ของ spec คือสิ่งที่เติมตอนเขียนแผนนี้ ผู้ใช้ต้องอ่านและเห็นชอบพร้อมแผน)

## สิ่งที่ตรวจแล้ว (2026-10-06)

- เทสต์ตั้งต้นบน `feat/vendor-drone-sitl` @ `c9a7fab`: **195 passed**
- uvicorn 0.52 ประกาศ ASGI `spec_version` 2.3 → Starlette 1.3.1 ใช้ทาง "ฟัง `http.disconnect` แล้วยกเลิก generator" เมื่อ client ตัดสาย (ไม่ต้องรอ ping รอบถัดไป)
- uvicorn ตอบ `100 Continue` เองตอนที่ app เรียกอ่าน body ครั้งแรก · `create_from_upload` ปฏิเสธ (400 / 411 / 413 / 507 / 409) **ก่อน**อ่าน body → client ที่ส่ง `Expect: 100-continue` ได้คำตอบโดยไม่ต้องส่งไฟล์
- `telemetry.jsonl` ของงานจริง (`j-20261006-022911-a24b`): 450 บรรทัดใน 90.2 s = 4.99 Hz · บรรทัดละ 1,294–1,399 byte · ฟิลด์ที่ client ใช้: `lat`, `lon`, `alt_m`, `mode`, `agent.state`
- `events.jsonl` มี `kind: state` ของ `pulling` / `booting` / `flying` แต่ไม่มี `queued` และไม่มี state จบ → stream ใช้ `job.state` (spec 1.3)
- `store.end()` (state จบ) ถูกเรียกหลัง `runlog.close()`, finalize และ cleanup ใน `worker.run_job` → เมื่อ `job.state` เป็น state จบ journal ปิดแล้วและ `job.result` ถูกตั้งแล้ว (เป็น `None` ได้เฉพาะงานที่ถูก kill ตอน `queued` หรือ fail เพราะ `runner_degraded`)
- `urllib` เขียนชื่อ header เป็น `Last-event-id` · Starlette ไม่สนตัวพิมพ์ จึงอ่านด้วย `request.headers.get("last-event-id")`
- **โค้ดทุกก้อนในแผนนี้ผ่านการรันจริงแล้วในสำเนาของ repo ที่ scratchpad** (ไม่ได้แตะ repo): หลัง Task 1 = 206 · Task 2 = 211 · Task 3 = 221 · Task 4 = **249 passed** · กลายพันธุ์ 6 จุดในโค้ด client (ตัด `Expect`, ตัด `Last-Event-ID`, ไม่ตรวจความยาวไฟล์, kill ตอนถูกขัดจังหวะ, ไม่จับ SIGTERM, รอทั้งที่ degraded) เทสต์จับได้ทุกจุด
- เครื่องนี้มี flight-service ตัวจริงเปิดอยู่ที่ `127.0.0.1:8095` · งานจริงล่าสุด (`j-20261006-022911-a24b`) จบ `failed / arming_timeout` (เกี่ยวกับ Task 5 ข้อ 6)

## Global Constraints

- branch ใหม่ `feat/sse-client` แตกจาก `feat/vendor-drone-sitl` (HEAD `c9a7fab`) · ไม่ merge / ไม่ push (เจ้าของจัดการเอง)
- working tree มีไฟล์ untracked ของงาน vendor (`docs/evidence/verification-vendor-*`, `docs/superpowers/plans/2026-10-06-vendor-drone-sitl.md`) ที่**ไม่ใช่ของแผนนี้**: ใช้ `git add <path>` ตามที่แต่ละ Task ระบุเท่านั้น **ห้าม `git add -A` / `git add .` / `git commit -a`**
- endpoint ใหม่: `GET /jobs/{job_id}/stream` · Bearer token เหมือนตัวอื่น · event มี 3 ชนิดเท่านั้น: `state`, `telemetry`, `end` · มีแต่ `telemetry` ที่มี `id`
- ค่าคงที่ฝั่ง server: วนอ่านทุก `0.2` s · `: ping` ทุก `15` s · header `Cache-Control: no-cache` และ `X-Accel-Buffering: no`
- ไม่ส่ง log ของ agent และ detections ผ่าน stream · ไม่ตัดฟิลด์ของ telemetry · ไม่จำกัดจำนวน stream ต่อ job
- `scripts/flight.py`: ไฟล์เดียว · standard library เท่านั้น · syntax ไม่เกิน Python 3.8 · ไม่ import จาก `flight_service/` · ข้อความที่ client พิมพ์เองเป็นอังกฤษ ASCII
- exit code ของ `run` / `watch`: `0` done · `1` failed หรือ killed · `2` ติดต่อ/ส่งงานไม่ได้ หรือดึงไฟล์ผลไม่ครบ · `3` ถูกขัดจังหวะ
- **client ไม่ kill งานเองไม่ว่ากรณีใด** (Ctrl-C, SIGTERM, error) · หยุดงานได้ทางเดียวคือคำสั่ง `kill`
- `scripts/mock-caller.sh` เก็บไว้ ไม่ลบ ไม่แก้
- **เทสต์ห้ามยิงไปที่ service จริงบน `:8095`:** ทุกเทสต์ส่ง `--url` ของ server ปลอมหรือของ app ในเทสต์เสมอ · ตอนลองด้วยมือก่อน Task 5 ห้ามรัน `flight.py run` / `kill` โดยไม่ใส่ `--url`
- รันจริงบน sim (Task 5) ต้องได้รับอนุมัติก่อนทุกครั้ง · กฎเดิมยังอยู่: ห้าม `pkill -f` · ห้าม `docker image prune` · bind `127.0.0.1:8095` · รัน service ด้วย conda env `drone`
- รันเทสต์ด้วย `conda run -n drone python -m pytest -q` · ทุก Task ต้องผ่านทั้งชุดก่อน commit
- commit ใช้ author ที่ตั้งใน repo แล้ว · ท้าย message ทุก commit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01U58PizJ3sdz11yCZuVzp47
  ```

## Review Focus

1. **ไฟล์ที่ service จะไม่รับ (ช่องรอเต็ม / ใหญ่เกิน / ดิสก์ไม่พอ):** คนส่งไฟล์ 16 GB คาดว่าจะรู้ผลทันที ไม่ใช่หลังส่งครบทั้งไฟล์ · เทสต์: Task 3 `test_real_service_refuses_a_file_before_it_is_sent` (นับ byte ที่ส่งจริง)
2. **ระบบของผู้เรียกหยุด client ด้วย SIGTERM ไม่ใช่ Ctrl-C:** ต้องได้ผลเหมือนกัน คือ exit 3, มี `job_id` บน stdout, งานไม่ถูก kill · เทสต์: Task 4 `test_an_interrupted_client_leaves_the_job_alone` (รันทั้ง SIGINT และ SIGTERM กับโปรเซสจริง)
3. **ไฟล์ผลมาไม่ครบ (สายขาดกลางไฟล์ / retention ลบไปก่อน):** ต้องไม่เหลือไฟล์ครึ่งที่ดูเหมือนไฟล์จริง และ exit code ต้องไม่ใช่ 0 · เทสต์: Task 4 `test_a_file_that_cannot_be_fetched_is_named_and_exits_2`
4. **client รันใต้ terminal ที่ไม่ใช่ UTF-8 (`LANG=C` ใน cron / systemd) แล้ว server ตอบ `detail` ภาษาไทย:** ต้องได้ข้อความ ไม่ใช่ `UnicodeEncodeError` · เทสต์: Task 4 `test_a_terminal_that_is_not_utf8_does_not_break_the_client`
5. **`Last-Event-ID` ที่ไม่ใช่เลขบรรทัด และ journal ที่ไม่สะอาด** (ค่ายาว 5,000 หลัก, ติดลบ, ตัวเลขที่ไม่ใช่ ASCII, เกินจำนวนบรรทัด, บรรทัดเสีย, บรรทัดสุดท้ายขาดจาก crash): ต้องไม่ 500 และเลขบรรทัดต้องไม่เพี้ยน · เทสต์: Task 1 `test_last_event_id_header`, `test_unreadable_lines_are_skipped_but_keep_their_number`, `test_a_torn_last_line_is_never_sent`

## ไฟล์

| ไฟล์ | หน้าที่ | Task |
|---|---|---|
| `flight_service/stream.py` (ใหม่) | `events()` generator ของ SSE · `Tail` อ่านบรรทัดที่ครบจากไฟล์ที่ยังโต · `last_event_id()` | 1 |
| `tests/test_stream.py` (ใหม่) | generator กับไฟล์ใน tmp ไม่มี HTTP | 1 |
| `tests/conftest.py` | เพิ่ม `sse_events()` ตัวอ่าน SSE สำหรับเทสต์ฝั่ง server | 1 |
| `flight_service/app.py` | route `GET /jobs/{job_id}/stream` · "six" → "seven" | 2 |
| `tests/test_app.py` | route จริงบน uvicorn: 401 / 404 / header / เล่นย้อน / ต่อใหม่ / ตามงานสด / client ตัดสาย | 2 |
| `docs/design.md` · `docs/api.md` | 6 → 7 endpoint + หัวข้อ stream | 2 |
| `scripts/flight.py` (ใหม่) | client: `health`, `kill` (Task 3) · `run`, `watch` (Task 4) | 3, 4 |
| `tests/test_flight_client.py` (ใหม่) | client กับ server ปลอมบน socket จริง และกับ app จริง | 3, 4 |
| `.gitignore` | `flight-out/` | 4 |
| `docs/verification.md` · `docs/evidence/verification-sse-*` | ผลรันจริง | 5 |
| `README.md` · `docs/followups.md` | วิธีใช้ `flight.py` · งานที่เลื่อน | 6 |
| `docs/progress.md` | แถวของงานนี้ + บันทึกการตัดสินใจ | 0, 2, 4, 5, 6 |

---

### Task 0: branch + บันทึกการตัดสินใจ

**Files:**
- Modify: `docs/progress.md`

- [ ] **Step 1: แตก branch และเช็กจุดเริ่ม**

```bash
cd ~/pai/flight-service
git status --short            # ต้องมีแต่ไฟล์ untracked ใต้ docs/ (ของ vendor + spec/plan นี้) ไม่มีไฟล์ที่ถูกแก้
git switch -c feat/sse-client feat/vendor-drone-sitl
git log --oneline -1          # c9a7fab feat: preflight.sh says what a new machine still lacks
conda run -n drone python -m pytest -q 2>&1 | tail -1   # 195 passed
```

ถ้า HEAD ไม่ใช่ `c9a7fab` หรือจำนวนเทสต์ไม่ใช่ 195: หยุดถามผู้ใช้ (branch ต้นทางเดินหน้าไปแล้ว ตัวเลขในแผนนี้ต้องปรับ)

- [ ] **Step 2: เพิ่มแถวและการตัดสินใจใน `docs/progress.md`**

ต่อท้ายตารางขั้น (หลังแถว `| B | ...`):

```markdown
| C | Stream สด (SSE) + client `flight.py` | spec `docs/superpowers/specs/2026-10-06-sse-client-design.md` · plan `docs/superpowers/plans/2026-10-06-sse-client.md` (Task 0–6) | 🟡 แผนอนุมัติแล้ว · กำลังทำ Task 1 |
```

ต่อท้ายตาราง "บันทึกการตัดสินใจ":

```markdown
| 2026-10-06 | ติดตามสด | **ทาง B:** `GET /jobs/{id}/stream` (SSE) ส่ง telemetry ทุกบรรทัด + state + ผลตอนจบ · ไม่ส่ง log ของ agent / detections (ยังอยู่ใน `GET /jobs/{id}` และ `/files/*`) · poll เดิมยังใช้ได้ · API เป็น 7 endpoint |
| 2026-10-06 | client | `scripts/flight.py` ไฟล์เดียว standard library · **Ctrl-C / SIGTERM ไม่ kill งาน** (งานเป็นของ service) · exit code 0 / 1 / 2 / 3 · `mock-caller.sh` เก็บไว้จนกว่า `flight.py` ผ่านรันจริง |
| 2026-10-06 | ความพร้อมของเครื่องใน `/healthz` | แยกไปทำทีหลัง (ฐานคือ `scripts/preflight.sh`) · อยู่ใน `docs/followups.md` |
```

- [ ] **Step 3: Commit (spec + plan + progress)**

```bash
git add docs/superpowers/specs/2026-10-06-sse-client-design.md docs/superpowers/plans/2026-10-06-sse-client.md docs/progress.md
git commit -m "docs: spec and plan for the SSE stream and the flight.py client

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01U58PizJ3sdz11yCZuVzp47"
```

---

### Task 1: `flight_service/stream.py`

**Files:**
- Create: `flight_service/stream.py`
- Modify: `tests/conftest.py` (ต่อท้ายไฟล์)
- Test: `tests/test_stream.py`

**Interfaces:**
- Consumes: `flight_service.jobs.Job` (อ่าน `id`, `state`, `state_since`, `failed_in`, `reason`, `detail`, `result`, `summary()`), `flight_service.jobs.TERMINAL`
- Produces:
  - `stream.events(job, path, skip=0, poll_s=POLL_S, ping_s=PING_S)` → async generator ของ `bytes` (ก้อนละหนึ่ง event หรือหนึ่ง `: ping`) จบเองหลังส่ง `end`
  - `stream.last_event_id(value: str | None) -> int` (ค่าที่ไม่ใช่เลขบรรทัด → `0`)
  - `stream.Tail(path)` มี `.lines()` (generator ของ `(เลขบรรทัด, bytes ไม่มี \n)`) และ `.close()`
  - `stream.HEADERS: dict` · `stream.POLL_S = 0.2` · `stream.PING_S = 15.0`
  - `conftest.sse_events(payload: bytes) -> list[(event, id | None, data)]` (keepalive = `("ping", None, None)`)
  - รูป event บนสาย: `id: <n>\nevent: telemetry\ndata: <บรรทัด JSON>\n\n` · `event: state\ndata: {"state","since","reason"}\n\n` · `event: end\ndata: {"job_id","state","failed_in","reason","detail","result"}\n\n`

- [ ] **Step 1: เพิ่มตัวอ่าน SSE ของเทสต์ ต่อท้าย `tests/conftest.py`** (เว้นสองบรรทัดว่างจากฟังก์ชัน `http`)

```python
def sse_events(payload):
    """[(event, id, data)] of a Server-Sent Events byte stream, data parsed
    as JSON. A keepalive comment is ("ping", None, None)."""
    out = []
    for block in payload.decode().split("\n\n"):
        if not block:
            continue
        if block.startswith(":"):
            out.append(("ping", None, None))
            continue
        f = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((f["event"], int(f["id"]) if "id" in f else None, json.loads(f["data"])))
    return out
```

- [ ] **Step 2: เขียนเทสต์ที่ล้ม**

`tests/test_stream.py`:

```python
"""stream.events against a journal file and a Job: no HTTP, no worker."""
import asyncio
import json

from conftest import sse_events

from flight_service import stream
from flight_service.jobs import DONE, FAILED, FLYING, PULLING, Job

RESULT = {"ended_by": "agent", "partial": False, "score": {"score": 95.6}}


def a_job(state, **kw):
    return Job("j-1", "perkiepai/x:1", 600, state=state, **kw)


def journal(tmp_path, *lines):
    path = tmp_path / "telemetry.jsonl"
    path.write_bytes(b"".join(lines))
    return path


def row(i):
    return json.dumps({"t": i, "alt_m": 10.0 + i}).encode() + b"\n"


def append(path, data):
    with open(path, "ab") as f:
        f.write(data)


def connect(job, path, script=None, limit=10_000, **kw):
    """Everything one connection receives. `script` is what happens meanwhile:
    {n: fn} runs fn right after the n-th chunk arrived. Stops by itself when
    the stream ends, or after `limit` chunks (the client hangs up)."""
    kw.setdefault("poll_s", 0.001)

    async def go():
        chunks = []
        gen = stream.events(job, path, **kw)
        async for chunk in gen:
            chunks.append(chunk)
            if script and len(chunks) in script:
                script[len(chunks)]()
            if len(chunks) >= limit:
                break
        await gen.aclose()
        return chunks

    return sse_events(b"".join(asyncio.run(asyncio.wait_for(go(), 10))))


def test_a_finished_job_replays_state_every_line_then_end(tmp_path):
    job = a_job(DONE, result=RESULT)
    got = connect(job, journal(tmp_path, row(1), row(2), row(3)))
    assert [(e, i) for e, i, _ in got] == [("state", None), ("telemetry", 1), ("telemetry", 2),
                                          ("telemetry", 3), ("end", None)]
    assert got[0][2] == {"state": "done", "since": job.summary()["state_since"], "reason": None}
    assert got[2][2] == {"t": 2, "alt_m": 12.0}                 # the line as journaled
    assert got[-1][2] == {"job_id": "j-1", "state": "done", "failed_in": None, "reason": None,
                          "detail": None, "result": RESULT}


def test_last_event_id_skips_the_lines_the_client_already_has(tmp_path):
    path = journal(tmp_path, row(1), row(2), row(3))
    got = connect(a_job(DONE), path, skip=2)
    assert [(e, i) for e, i, _ in got] == [("state", None), ("telemetry", 3), ("end", None)]
    got = connect(a_job(DONE), path, skip=99)                   # more than the file has
    assert [e for e, _, _ in got] == ["state", "end"]


def test_last_event_id_header():
    for value, want in ((None, 0), ("", 0), ("0", 0), ("5", 5), (" 7 ", 7), ("-1", 0),
                        ("1.5", 0), ("abc", 0), ("1_0", 0), ("٣", 0), ("9" * 5000, 0)):
        assert stream.last_event_id(value) == want, value


def test_tail_holds_a_line_back_until_its_newline(tmp_path):
    path = journal(tmp_path, row(1), b'{"t":')
    tail = stream.Tail(path)
    assert list(tail.lines()) == [(1, row(1)[:-1])]
    assert list(tail.lines()) == []                             # the half line: not yet
    append(path, b' 2}\n' + row(3))
    assert list(tail.lines()) == [(2, b'{"t": 2}'), (3, row(3)[:-1])]
    tail.close()


def test_tail_waits_for_a_journal_that_does_not_exist_yet(tmp_path):
    tail = stream.Tail(tmp_path / "telemetry.jsonl")
    assert list(tail.lines()) == []                             # queued, pulling
    journal(tmp_path, row(1))
    assert list(tail.lines()) == [(1, row(1)[:-1])]
    tail.close()


def test_a_torn_last_line_is_never_sent(tmp_path):
    """A crash leaves at most a torn last line (journal.py): the stream ends without it."""
    got = connect(a_job(FAILED, reason="runner_restarted"), journal(tmp_path, row(1), b'{"t": 2, "al'))
    assert [(e, i) for e, i, _ in got] == [("state", None), ("telemetry", 1), ("end", None)]


def test_unreadable_lines_are_skipped_but_keep_their_number(tmp_path):
    path = journal(tmp_path, row(1), b"not json\n", b"\n", b'{"t":\r4}\n', row(5))
    got = connect(a_job(DONE), path)
    assert [i for e, i, _ in got if e == "telemetry"] == [1, 5]
    assert [i for e, i, _ in connect(a_job(DONE), path, skip=4) if e == "telemetry"] == [5]


def test_a_live_job_sends_each_state_change_and_each_new_line(tmp_path):
    job, path = a_job(PULLING), tmp_path / "telemetry.jsonl"

    def to(state, **fields):
        def change():
            job.state, job.state_since = state, job.state_since + 1
            for k, v in fields.items():
                setattr(job, k, v)
        return change

    got = connect(job, path, script={
        1: to("booting"),                                       # after "state pulling"
        2: to(FLYING),                                          # after "state booting"
        3: lambda: path.write_bytes(row(1)),                    # after "state flying"
        4: lambda: append(path, row(2)),                        # after "telemetry 1"
        5: to(FAILED, reason="flight_timeout", detail="600 s", failed_in=FLYING,
              result={"ended_by": "timeout"}),                  # after "telemetry 2"
    })
    assert [(e, i) for e, i, _ in got] == [
        ("state", None), ("state", None), ("state", None), ("telemetry", 1), ("telemetry", 2),
        ("state", None), ("end", None)]
    assert [d["state"] for e, _, d in got if e == "state"] == ["pulling", "booting", "flying", "failed"]
    assert got[5][2]["reason"] == "flight_timeout"
    assert got[6][2] == {"job_id": "j-1", "state": "failed", "failed_in": "flying",
                         "reason": "flight_timeout", "detail": "600 s",
                         "result": {"ended_by": "timeout"}}


def test_keepalive_comment_while_there_is_nothing_to_say(tmp_path):
    got = connect(a_job(PULLING), tmp_path / "telemetry.jsonl", limit=3, ping_s=0.01)
    assert [e for e, _, _ in got] == ["state", "ping", "ping"]


def test_no_keepalive_while_lines_flow(tmp_path):
    job, path = a_job(FLYING), journal(tmp_path, row(1))
    more = {n: (lambda n=n: append(path, row(n))) for n in range(2, 30)}
    got = connect(job, path, script=more, limit=30, ping_s=5)
    assert "ping" not in [e for e, _, _ in got]


def test_a_long_backlog_arrives_whole_and_in_order(tmp_path):
    """Lines the size of real ones (~1.3 KB), enough to cross many 64 KB reads."""
    rows = [json.dumps({"t": i, "pad": "x" * 1300}).encode() + b"\n" for i in range(1, 601)]
    got = connect(a_job(DONE), journal(tmp_path, *rows))
    lines = [(i, d["t"]) for e, i, d in got if e == "telemetry"]
    assert lines == [(i, i) for i in range(1, 601)] and got[-1][0] == "end"
```

- [ ] **Step 3: รันให้เห็นว่าล้ม**

Run: `conda run -n drone python -m pytest -q tests/test_stream.py`
Expected: ERROR ตอน collect ด้วย `ImportError: cannot import name 'stream' from 'flight_service'`

- [ ] **Step 4: เขียน `flight_service/stream.py`**

```python
"""GET /jobs/{id}/stream as Server-Sent Events (design 3.1): one flight as
it happens, without polling. Three events:

  state      once on connect, then on every change    {"state","since","reason"}
  telemetry  one per line of telemetry.jsonl          the line as journaled; id = its line number
  end        the job ended and every line was sent    {"job_id","state","failed_in","reason","detail","result"}

Only telemetry carries an id, so a client that comes back with
Last-Event-ID: n gets line n+1 onwards: nothing lost, nothing twice.
No dependency on the worker: it reads the live Job and the run's journal."""
import asyncio
import json
import re
import time

from .jobs import TERMINAL

HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}   # nginx: pass it on at once
POLL_S = 0.2            # how often the journal and the state are looked at
PING_S = 15.0           # a comment line this often while there is nothing to say
CHUNK = 1 << 16
YIELD_EVERY = 100       # lines of a backlog sent before other tasks get a turn


def last_event_id(value):
    """Lines the client already has, from its Last-Event-ID header. Anything
    but a plain non-negative number means: from the start."""
    value = (value or "").strip()
    return int(value) if re.fullmatch(r"[0-9]{1,12}", value) else 0


class Tail:
    """Whole lines of a file that may still be growing, numbered from 1. A
    last line with no newline yet is held back until the rest arrives."""

    def __init__(self, path):
        self.path, self.n = path, 0
        self._f, self._rest = None, b""

    def lines(self):
        """(number, line) for every complete line not handed out before."""
        if self._f is None:
            try:
                self._f = open(self.path, "rb")
            except FileNotFoundError:           # queued, pulling: no journal yet
                return
        while True:
            chunk = self._f.read(CHUNK)
            if not chunk:
                return
            *whole, self._rest = (self._rest + chunk).split(b"\n")
            for line in whole:
                self.n += 1
                yield self.n, line

    def close(self):
        if self._f is not None:
            self._f.close()


def _readable(line):
    """One JSON value that fits one SSE data line. Anything else is skipped
    (as read_jsonl does) but keeps its line number."""
    if b"\r" in line:
        return False
    try:
        json.loads(line)
    except ValueError:
        return False
    return True


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


def _event(name, data, eid=None):
    head = f"id: {eid}\n" if eid is not None else ""
    return f"{head}event: {name}\ndata: ".encode() + data + b"\n\n"


async def events(job, path, skip=0, poll_s=POLL_S, ping_s=PING_S):
    """The byte chunks of one connection, until the job ended or the client
    left. A terminal state is set only after the journal is closed and the
    result is built (design 5), so looking at the state first and the file
    second never ends a stream with lines still unsent."""
    tail = Tail(path)
    told = None                     # (state, state_since) the client last heard
    quiet = time.monotonic()        # when anything was last sent
    try:
        while True:
            state, since = job.state, job.state_since
            if (state, since) != told:
                told = (state, since)
                s = job.summary()
                yield _event("state", _json({"state": state, "since": s["state_since"],
                                             "reason": s["reason"]}))
                quiet = time.monotonic()
            sent = 0
            for n, line in tail.lines():
                if n <= skip or not _readable(line):
                    continue
                yield _event("telemetry", line, n)
                quiet = time.monotonic()
                sent += 1
                if sent % YIELD_EVERY == 0:
                    await asyncio.sleep(0)
            if state in TERMINAL:
                yield _event("end", _json({"job_id": job.id, "state": state,
                                           "failed_in": job.failed_in, "reason": job.reason,
                                           "detail": job.detail, "result": job.result}))
                return
            if time.monotonic() - quiet >= ping_s:
                yield b": ping\n\n"
                quiet = time.monotonic()
            await asyncio.sleep(poll_s)
    finally:
        tail.close()
```

ข้อที่ต้องไม่เปลี่ยนตอนพิมพ์ตาม: ลำดับในลูปคือ (1) จับ `state` (2) อ่านไฟล์ (3) ถ้า `state` ที่จับไว้เป็น state จบจึงส่ง `end` · ถ้าสลับเป็นอ่านไฟล์ก่อนแล้วค่อยดู state จะมีช่องที่บรรทัดสุดท้ายไม่ถูกส่ง

- [ ] **Step 5: รันให้เห็นว่าผ่าน**

Run: `conda run -n drone python -m pytest -q tests/test_stream.py`
Expected: `11 passed`

Run: `conda run -n drone python -m pytest -q 2>&1 | tail -1`
Expected: `206 passed`

- [ ] **Step 6: Commit**

```bash
git add flight_service/stream.py tests/test_stream.py tests/conftest.py
git commit -m "feat: stream.events turns a job's journal into Server-Sent Events

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01U58PizJ3sdz11yCZuVzp47"
```

---

### Task 2: route `GET /jobs/{job_id}/stream` + เอกสาร API

**Files:**
- Modify: `flight_service/app.py` (docstring บรรทัด 1, import บรรทัด 16, คอมเมนต์บรรทัด 59, route ใหม่ก่อน `return app`)
- Modify: `tests/test_app.py` (import ด้านบน + ต่อท้ายไฟล์)
- Modify: `docs/design.md` (หัวข้อ 3 และ 9), `docs/api.md` (หัวข้อ 0 และ 1), `docs/progress.md`

**Interfaces:**
- Consumes: `stream.events(job, path, skip)`, `stream.last_event_id(value)`, `stream.HEADERS` (Task 1) · `conftest.sse_events` (Task 1) · ของเดิมใน `app.py`: `auth`, `job_or_404`, `store.dir(job)`
- Produces: `GET /jobs/{job_id}/stream` → `200 text/event-stream` · `401` ไม่มี/ผิด token · `404 {"detail": "no such job"}` · request header `Last-Event-ID: <n>` = ข้าม n บรรทัดแรกของ telemetry

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

ใน `tests/test_app.py` แก้ import ด้านบน จาก

```python
import asyncio

from conftest import http

from flight_service.app import create_app
from flight_service.config import Settings
from flight_service.jobs import KILLED, QUEUED, JobStore
```

เป็น

```python
import asyncio
import json
import threading
import urllib.request

from conftest import http, sse_events

from flight_service import stream
from flight_service.app import create_app
from flight_service.config import Settings
from flight_service.jobs import DONE, FLYING, KILLED, QUEUED, JobStore
```

แล้วต่อท้ายไฟล์ (เว้นสองบรรทัดว่างจากของเดิม):

```python
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


def open_stream(url, jid, last_id=None, token=TOKEN):
    req = urllib.request.Request(f"{url}/jobs/{jid}/stream")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
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


def test_stream_needs_the_token_and_a_job(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    jid = flown(store).id
    assert http("GET", f"{url}/jobs/{jid}/stream")[0] == 401
    assert http("GET", f"{url}/jobs/{jid}/stream", token="wrong" * 10)[0] == 401
    assert http("GET", f"{url}/jobs/nope/stream", TOKEN) == (404, {"detail": "no such job"})
    assert http("POST", f"{url}/jobs/{jid}/stream", TOKEN)[0] == 405


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
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `conda run -n drone python -m pytest -q tests/test_app.py`
Expected: `5 failed, 12 passed` · เทสต์ `test_stream_*` ทั้ง 5 ล้มเพราะ route ยังไม่มี (ได้ `404 {"detail": "Not Found"}` หรือ `urllib.error.HTTPError: HTTP Error 404`)

- [ ] **Step 3: เพิ่ม route ใน `flight_service/app.py`**

บรรทัด 1 ของ docstring: `"""HTTP API (design 3): six endpoints, one job each.` → `"""HTTP API (design 3): seven endpoints, one job each.`

บรรทัด import: `from . import policy, uploads` → `from . import policy, stream, uploads`

คอมเมนต์เหนือ `app = FastAPI(`: `# The six endpoints of design 3 only:` → `# The seven endpoints of design 3 only:`

แทรก route นี้หลังฟังก์ชัน `get_file` และก่อนบรรทัด `    return app` (ย่อหน้า 4 ช่องเหมือน route อื่น · เว้นบรรทัดว่างหนึ่งบรรทัดก่อน `return app`):

```python
    @app.get("/jobs/{job_id}/stream", dependencies=[Depends(auth)])
    def stream_job(job_id: str, request: Request):
        """The flight as Server-Sent Events (design 3.1). 404 and 401 are
        answered before the stream opens; Last-Event-ID resumes it."""
        job = job_or_404(job_id)
        skip = stream.last_event_id(request.headers.get("last-event-id"))
        return StreamingResponse(stream.events(job, store.dir(job) / "telemetry.jsonl", skip),
                                 media_type="text/event-stream", headers=stream.HEADERS)
```

`def` ธรรมดา (ไม่ใช่ `async def`) เหมือน `get_job`: งานของ route คือหา job แล้วคืน response · ตัว generator ถูกรันบน event loop โดย `StreamingResponse` เอง

ไม่ต้องเขียนโค้ดสำหรับ "exception ระหว่าง stream" (spec หัวข้อ 3): exception ใน generator ทำให้ uvicorn ปิดสายโดยไม่ส่ง chunk ปิดท้าย ไม่มี event ปลอม · ฝั่ง client เห็นเป็นสายขาดแล้วต่อใหม่ด้วย `Last-Event-ID` (เทสต์ฝั่ง client: Task 4 `test_a_broken_stream_resumes_after_the_last_whole_line`)

- [ ] **Step 4: รันให้เห็นว่าผ่าน**

Run: `conda run -n drone python -m pytest -q tests/test_app.py`
Expected: `17 passed`

Run: `conda run -n drone python -m pytest -q 2>&1 | tail -1`
Expected: `211 passed`

- [ ] **Step 5: แก้ `docs/design.md`**

หัวข้อ 3 บรรทัดหัว: `## 3. API (ฉบับรวม 2026-10-05 · 6 endpoint, ตัวละหนึ่งหน้าที่ ไม่ซ้ำกัน)` → `## 3. API (ฉบับรวม 2026-10-05 · 7 endpoint, ตัวละหนึ่งหน้าที่ ไม่ซ้ำกัน · เพิ่ม stream 2026-10-06)`

ในตาราง endpoint เพิ่มแถวนี้ใต้แถว `GET /jobs/{id}`:

```markdown
| `GET` | `/jobs/{id}/stream` | **ติดตามสด** เป็น Server-Sent Events: state, telemetry ทุกบรรทัด, ผลตอนจบ (หัวข้อ 3.1) | ไม่ส่ง log ของ agent หรือ detections (อยู่ใน `GET /jobs/{id}` และ `/files/*`) |
```

ใต้บรรทัด `ข้อผิดพลาดอื่น: \`404\` ไม่มีงาน/ไฟล์ · \`409\` kill งานที่จบไปแล้ว` (ก่อนเส้น `---` ที่คั่นหัวข้อ 4) เพิ่ม:

```markdown

### 3.1 Stream สด: `GET /jobs/{id}/stream` (เพิ่ม 2026-10-06)

Server-Sent Events บน HTTP ธรรมดา · token เดียวกับ endpoint อื่น · `404` / `401` ตอบก่อนเปิดสาย · รายละเอียดและเหตุผล: `docs/superpowers/specs/2026-10-06-sse-client-design.md`

| event | ส่งเมื่อ | data |
|---|---|---|
| `state` | ตอนต่อเข้ามาหนึ่งครั้ง และทุกครั้งที่ state เปลี่ยน | `{"state","since","reason"}` |
| `telemetry` | มีบรรทัดใหม่ใน `telemetry.jsonl` (5 Hz) · มี `id` = เลขบรรทัด | บรรทัด JSON นั้น ทุกฟิลด์ |
| `end` | state จบ และ telemetry ส่งครบแล้ว จากนั้น server ปิดสาย | `{"job_id","state","failed_in","reason","detail","result"}` |

- ต่อใหม่พร้อม header `Last-Event-ID: n` → ได้บรรทัดที่ n+1 เป็นต้นไป ไม่หาย ไม่ซ้ำ (ค่าที่ไม่ใช่เลขบรรทัด = ส่งตั้งแต่ต้น)
- ช่วงที่ไม่มีอะไรจะส่ง (pulling, booting, finalize, cleanup) มีบรรทัดคอมเมนต์ `: ping` ทุก 15 s
- สถานะมาจาก job ในหน่วยความจำ ไม่ใช่ `events.jsonl` · state จบถูกตั้งหลัง cleanup (หัวข้อ 5) ดังนั้น `end` = journal ปิดแล้ว ผลพร้อม ส่งงานถัดไปได้
- service restart กลางบิน: สายขาด ต่อใหม่ได้ `end` พร้อม `failed` / `runner_restarted`
- ไม่ทำ: จำกัดจำนวนสายต่อ job · log ของ agent / detections ใน stream · ตัดฟิลด์ telemetry
```

หัวข้อ 9 ใต้บรรทัดหัว `## 9. ข้อ d: วิธีส่งข้อมูลกลับ → **เลือก A + MP4 หลังจบ**` เพิ่ม (เว้นบรรทัดว่างก่อนและหลัง):

```markdown
> **2026-10-06:** เพิ่ม stream สดแบบ SSE (หัวข้อ 3.1) เป็นทางเสริมของ A · poll ยังใช้ได้เหมือนเดิม · ต่างจากทาง C ตรงที่เป็น HTTP ขาเดียว ไม่มีภาพสด และไม่ต้องเปิดพอร์ตเพิ่ม
```

- [ ] **Step 6: แก้ `docs/api.md`**

หัวข้อ 0 แถว ⑦: `| ⑦ | ระบบคิวพี่ต้น · อ่านผล | poll สถานะ ดาวน์โหลดไฟล์ เห็น state จบแล้วส่งงานถัดไป |` → `| ⑦ | ระบบคิวพี่ต้น · อ่านผล | ติดตามสดทาง stream หรือ poll สถานะ ดาวน์โหลดไฟล์ เห็น state จบแล้วส่งงานถัดไป |`

หัวข้อ 1 บรรทัดหัว: `## 1. Endpoint (6 ตัว ตัวละหนึ่งหน้าที่)` → `## 1. Endpoint (7 ตัว ตัวละหนึ่งหน้าที่)`

ในตาราง endpoint เพิ่มแถวนี้ใต้แถว `GET /jobs/{id}`:

```markdown
| `GET` | `/jobs/{id}/stream` | **ติดตามสด** (Server-Sent Events): state, telemetry ทุกบรรทัด, ผลตอนจบ | `200 text/event-stream` แล้วปิดสายหลัง `end` |
```

ในบล็อก "ตัวอย่าง curl" เพิ่มบรรทัดนี้ใต้ `curl -s $R/jobs/<id> -H "$H"`:

```bash
curl -sN $R/jobs/<id>/stream -H "$H"                              # ติดตามสด · ต่อใหม่: เพิ่ม -H 'Last-Event-ID: <เลขบรรทัดล่าสุดที่ได้>'
```

ใต้ตาราง "ข้อมูลที่ได้" และก่อนหัว `### HTTP status ที่ต้องรับมือ` เพิ่ม:

````markdown
### ติดตามสด: `GET /jobs/{id}/stream`

```
event: state
data: {"state":"flying","since":"2026-10-06T02:29:52+0700","reason":null}

id: 1
event: telemetry
data: {"connected":true,"armed":true,"mode":"OFFBOARD","alt_m":20.1,"lat":14.0283442,"lon":100.4364643,"t":1791228638.13,"agent":{"state":"running"}}

: ping

event: end
data: {"job_id":"j-...","state":"done","failed_in":null,"reason":null,"detail":"","result":{"ended_by":"agent","score":{"score":95.6},"files":{},"missing":[]}}
```

| event | ส่งเมื่อ | data |
|---|---|---|
| `state` | ตอนต่อเข้ามาหนึ่งครั้ง และทุกครั้งที่ state เปลี่ยน | `{"state","since","reason"}` |
| `telemetry` | ทุกบรรทัดใหม่ของ `telemetry.jsonl` (5 Hz, ~1.3 KB) · `id` = เลขบรรทัด | บรรทัดนั้นทุกฟิลด์ (ตัวอย่างข้างบนย่อไว้) |
| `end` | งานจบและส่ง telemetry ครบแล้ว → server ปิดสาย | `job_id`, `state`, `failed_in`, `reason`, `detail`, `result` (รูปเดียวกับใน `GET /jobs/{id}`) |

- **สายขาด:** ต่อใหม่พร้อม `Last-Event-ID: <id ล่าสุดที่ได้ครบ>` จะได้ต่อจากบรรทัดนั้น ไม่หาย ไม่ซ้ำ · `state` ปัจจุบันถูกส่งก่อนเสมอ
- **`: ping`** ทุก 15 s ตอนไม่มีข้อมูล (ก่อนบิน และช่วงเก็บกวาดหลังบิน) · เงียบเกิน ~45 s ให้ถือว่าสายตายแล้วต่อใหม่
- ต่อเข้ามาหลังงานจบก็ได้: ได้ `state` → telemetry ทั้งหมด → `end`
- log ของ agent และ detections ไม่อยู่ใน stream: ดูที่ `log_tail` ของ `GET /jobs/{id}` และ `files/events.jsonl`, `files/detections.jsonl`
- client สำเร็จรูปที่ทำทั้งหมดนี้ให้: `scripts/flight.py` (ดู README)
````

- [ ] **Step 7: อัปเดตแถว C ใน `docs/progress.md`**

คอลัมน์สถานะของแถว C → `🟡 server เสร็จ (Task 1–2 · 211 tests) · ⛔ รออนุมัติก่อน Task 3`
ในโครงโฟลเดอร์: `│   └── app.py                HTTP API 6 endpoint + token` → `│   ├── stream.py             GET /jobs/{id}/stream (SSE)` ตามด้วยบรรทัดใหม่ `│   └── app.py                HTTP API 7 endpoint + token`

- [ ] **Step 8: Commit**

```bash
git add flight_service/app.py tests/test_app.py docs/design.md docs/api.md docs/progress.md
git commit -m "feat: GET /jobs/{id}/stream follows a job as Server-Sent Events

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01U58PizJ3sdz11yCZuVzp47"
```

- [ ] **Step 9: ⛔ ประตูอนุมัติ (server + เทสต์)** สรุปผู้ใช้: จำนวนเทสต์ (211), ไฟล์ที่เปลี่ยน, ตัวอย่าง event จริงจาก `test_stream_follows_a_job_while_it_runs` · service ตัวจริงบน `:8095` ยังรันโค้ดเก่าจนกว่าจะ restart ใน Task 5 · รออนุมัติก่อน Task 3

---

### Task 3: `scripts/flight.py` ส่วนพื้นฐาน (`health`, `kill`, upload, ตัวอ่าน SSE)

**Files:**
- Create: `scripts/flight.py` (mode 755)
- Test: `tests/test_flight_client.py`

**Interfaces:**
- Consumes: HTTP API ของ service เท่านั้น (`GET /healthz`, `POST /jobs?kind=&name=`, `POST /jobs/{id}/kill`, `GET /jobs/{id}/stream`, `GET /jobs/{id}/files/{name}`) · ในเทสต์: `serve` fixture ของ `tests/conftest.py` และ `make`, `TOKEN` ของ `tests/test_app.py`
- Produces (Task 4 ใช้ต่อ ชื่อและชนิดต้องตรงนี้):
  - ค่าคงที่ระดับ module (เทสต์ย่อด้วย `monkeypatch.setattr`): `HTTP_TIMEOUT_S`, `KILL_TIMEOUT_S`, `UPLOAD_TIMEOUT_S`, `EXPECT_WAIT_S`, `STREAM_IDLE_S`, `BACKOFF_S`, `BACKOFF_MAX_S`, `STREAM_GIVE_UP_S`, `POLL_S`, `POLL_GIVE_UP_S`, `READY_POLL_S`, `SHOW_EVERY_S`, `TERMINAL`, `EXIT_OK=0`, `EXIT_FAILED=1`, `EXIT_UNREACHABLE=2`, `EXIT_INTERRUPTED=3` · `sleep = time.sleep`
  - `class Stop(Exception)`: `Stop(message, code=EXIT_UNREACHABLE)` มี `.code` · `class Unreachable(Exception)` · `class HttpError(Exception)`: `HttpError(status, body)` มี `.status`
  - `say(message: str) -> None` (stderr) · `explain(status: int, body) -> str`
  - `sse_events(lines: Iterable[bytes]) -> Iterator[(event: str, data: str, id: str | None)]`
  - `class Api(url, token)`: `.json(method, path, body=None, timeout=None) -> (status: int, body: dict)` · `.stream(job_id, last_id=0) -> Iterator[(event, data, id)]` (raise `HttpError` / `Unreachable`) · `.download(path, dest) -> bool` · `.upload(path, query) -> (status, body)`
  - `cmd_health(api, args) -> int` · `cmd_kill(api, args) -> int` · `main(argv=None) -> int`
  - เครื่องมือเทสต์ใน `tests/test_flight_client.py`: `FakeService`, fixture `service`, fixture `flight`, `run(flight, capsys, url, *argv, token=TOKEN) -> (code, stdout lines, stderr)`, `closed_port()`, `HANG`, `CUT`, `Short`, `READY`, `BUSY`, `DEGRADED`, `real(tmp_path, serve, **settings)`

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

`tests/test_flight_client.py`:

```python
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
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `conda run -n drone python -m pytest -q tests/test_flight_client.py`
Expected: ทั้ง 10 ตัว FAILED หรือ ERROR ด้วย `FileNotFoundError: ... scripts/flight.py`

- [ ] **Step 3: เขียน `scripts/flight.py`**

```python
#!/usr/bin/env python3
"""flight.py -- hand flight-service an image, watch the flight live, bring
the results home. One file, standard library only (Python 3.8+): copy it
anywhere.

  flight.py health
  flight.py run IMAGE [--timeout S] [--out DIR] [--wait S]
  flight.py run --file X.tar --kind image|bundle --name N [--timeout S] [--out DIR] [--wait S]
  flight.py watch JOB_ID [--out DIR]
  flight.py kill JOB_ID

Where and who: --url / FLIGHT_URL (default http://127.0.0.1:8095) and
--token / RUNNER_TOKEN. Progress goes to stderr; stdout carries one JSON
line for whatever called this.

Exit codes of run and watch:
  0  the job ended `done`
  1  the job ended `failed` or `killed`
  2  the service could not be reached, refused the job, or a result file
     could not be fetched
  3  interrupted (Ctrl-C, SIGTERM). The job is NOT killed: it belongs to
     the service. `watch` picks it up again, `kill` stops it.
health: 0 ready, 1 not ready, 2 unreachable. kill: 0 taken, 1 nothing to kill, 2 unreachable.
"""
import argparse
import http.client
import json
import os
import select
import signal
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8095"
TERMINAL = ("done", "failed", "killed")
EXIT_OK, EXIT_FAILED, EXIT_UNREACHABLE, EXIT_INTERRUPTED = 0, 1, 2, 3

HTTP_TIMEOUT_S = 30         # one ordinary request
KILL_TIMEOUT_S = 90         # a kill is answered after up to 60 s of cleanup
UPLOAD_TIMEOUT_S = 120      # silence on the line while a file goes up
EXPECT_WAIT_S = 2           # wait this long for "100 Continue", then send the file anyway
STREAM_IDLE_S = 45          # the service pings every 15 s: this long silent = the line is dead
BACKOFF_S, BACKOFF_MAX_S = 1, 10    # reconnect after 1, 2, 4, 8, 10, 10 ... seconds
STREAM_GIVE_UP_S = 60       # no stream for this long -> poll instead
POLL_S = 3
POLL_GIVE_UP_S = 300        # no answer at all for this long while polling -> exit 2
READY_POLL_S = 2
SHOW_EVERY_S = 5            # one position line per this many seconds
WHAT = {401: "token wrong or missing", 409: "pending slot full",
        503: "service degraded: someone has to fix the machine"}

sleep = time.sleep


class Stop(Exception):
    """Ends the command: a message for stderr and the exit code."""

    def __init__(self, message, code=EXIT_UNREACHABLE):
        super().__init__(message)
        self.code = code


class Unreachable(Exception):
    """No HTTP answer: refused, reset, timed out, cut off half way."""


class HttpError(Exception):
    """An HTTP answer that is not the 200 a stream needs."""

    def __init__(self, status, body):
        super().__init__(explain(status, body))
        self.status = status


def say(message):
    """One progress line on stderr; never dies on a terminal that is not UTF-8."""
    encoding = sys.stderr.encoding or "utf-8"
    line = f"{time.strftime('%H:%M:%S')} {message}\n"
    sys.stderr.write(line.encode(encoding, "backslashreplace").decode(encoding))
    sys.stderr.flush()


def explain(status, body):
    """An HTTP refusal as one line: what it means here + what the service said."""
    detail = body.get("detail") if isinstance(body, dict) else body
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    hint = f" ({WHAT[status]})" if status in WHAT else ""
    return f"HTTP {status}{hint}: {detail}"


def _parse(raw):
    """A JSON object, or {"detail": text} for anything else (a proxy's error page)."""
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    return body if isinstance(body, dict) else {"detail": raw.decode("utf-8", "replace")[:300]}


def _status(response):
    return response.code if isinstance(response, urllib.error.HTTPError) else response.status


def sse_events(lines):
    """(event, data, id) for each complete Server-Sent Event in an iterable
    of byte lines. Comment lines (the keepalive) are dropped, and so is an
    event cut off before its blank line."""
    event, data, eid = "message", [], None
    for raw in lines:
        line = raw.rstrip(b"\r\n").decode("utf-8", "replace")
        if not line:
            if data:
                yield event, "\n".join(data), eid
            event, data, eid = "message", [], None
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
        elif field == "id":
            eid = value


def _may_send(sock):
    """After the headers of an `Expect: 100-continue` request: True to send
    the body (the service said 100 Continue, or nothing at all for
    EXPECT_WAIT_S like a server that ignores Expect), False when its verdict
    is already there."""
    if not select.select([sock], [], [], EXPECT_WAIT_S)[0]:
        return True
    head = b""
    for _ in range(50):
        head = sock.recv(12, socket.MSG_PEEK)
        if len(head) >= 12 or not head:
            break
        time.sleep(0.02)
    return head.startswith(b"HTTP/1.1 100")


class Api:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token

    def _open(self, method, path, body=None, headers=None, timeout=None):
        """The response, whatever its status. Unreachable if there is none."""
        req = urllib.request.Request(self.url + path, data=body, method=method,
                                     headers=headers or {})
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            return urllib.request.urlopen(req, timeout=timeout or HTTP_TIMEOUT_S)
        except urllib.error.HTTPError as e:
            return e                                # an answer, just not 2xx
        except (OSError, http.client.HTTPException) as e:
            raise Unreachable(f"{self.url}: {getattr(e, 'reason', e)}")

    def json(self, method, path, body=None, timeout=None):
        """(status, body as a dict)."""
        headers = {}
        if body is not None:
            body, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
        with self._open(method, path, body, headers, timeout) as r:
            try:
                return _status(r), _parse(r.read())
            except (OSError, http.client.HTTPException) as e:
                raise Unreachable(f"{self.url}: {e}")

    def stream(self, job_id, last_id=0):
        """Events of GET /jobs/{id}/stream after telemetry line `last_id`.
        Returns when the service closes the line; HttpError if it does not
        open one; Unreachable if the line breaks or stays silent."""
        headers = {"Accept": "text/event-stream"}
        if last_id:
            headers["Last-Event-ID"] = str(last_id)
        with self._open("GET", f"/jobs/{job_id}/stream", headers=headers,
                        timeout=STREAM_IDLE_S) as r:
            try:
                if _status(r) != 200:
                    raise HttpError(_status(r), _parse(r.read()))
                yield from sse_events(r)
            except (OSError, http.client.HTTPException) as e:
                raise Unreachable(f"{self.url}: {e}")

    def download(self, path, dest):
        """Save GET `path` as `dest`: written as <dest>.part, renamed only
        when all of it arrived. False (and no file) otherwise."""
        part = dest + ".part"
        try:
            with self._open("GET", path) as r:
                if _status(r) != 200:
                    return False
                want, got = r.headers.get("Content-Length"), 0
                with open(part, "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
            if want is not None and got != int(want):
                raise OSError(f"{got} of {want} bytes")
            os.replace(part, dest)
            return True
        except (Unreachable, OSError, http.client.HTTPException):
            if os.path.exists(part):
                os.remove(part)
            return False

    def upload(self, path, query):
        """POST a file as the body of /jobs?<query>, streamed from disk with
        its Content-Length, as `curl -T` does. Like curl it asks first
        (Expect: 100-continue): the service refuses a file it will not take
        -- slot full, too large, no disk -- before a byte of it is sent."""
        u = urllib.parse.urlsplit(self.url)
        tls = u.scheme == "https"                   # no peeking into a TLS socket: just send
        cls = http.client.HTTPSConnection if tls else http.client.HTTPConnection
        conn = cls(u.netloc, timeout=UPLOAD_TIMEOUT_S)
        try:
            with open(path, "rb") as f:
                conn.putrequest("POST", f"{u.path}/jobs?{query}")
                conn.putheader("Authorization", "Bearer " + self.token)
                conn.putheader("Content-Type", "application/octet-stream")
                conn.putheader("Content-Length", str(os.fstat(f.fileno()).st_size))
                if not tls:
                    conn.putheader("Expect", "100-continue")
                conn.endheaders()
                if tls or _may_send(conn.sock):
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        conn.send(chunk)
            r = conn.getresponse()
            return r.status, _parse(r.read())
        except (OSError, http.client.HTTPException) as e:
            raise Unreachable(f"{self.url}: upload of {path}: {e}")
        finally:
            conn.close()


# -- commands -----------------------------------------------------------------

def cmd_health(api, args):
    status, health = api.json("GET", "/healthz")
    if status != 200:
        raise Stop(explain(status, health))
    print(json.dumps(health), flush=True)
    return EXIT_OK if health.get("ready") else EXIT_FAILED


def cmd_kill(api, args):
    status, job = api.json("POST", f"/jobs/{args.job_id}/kill", timeout=KILL_TIMEOUT_S)
    if status not in (200, 202):
        raise Stop(explain(status, job), EXIT_FAILED if status in (404, 409) else EXIT_UNREACHABLE)
    if status == 202:
        say(f"kill taken; the service is still cleaning up: flight.py watch {args.job_id}")
    print(json.dumps({"job_id": args.job_id, "state": job.get("state"),
                      "reason": job.get("reason")}), flush=True)
    return EXIT_OK


# -- command line -------------------------------------------------------------

COMMANDS = {"health": cmd_health, "kill": cmd_kill}


def parser():
    p = argparse.ArgumentParser(prog="flight.py", description="Submit one image to "
                                "flight-service, follow the flight, fetch the results.")
    p.add_argument("--url", default=os.environ.get("FLIGHT_URL", DEFAULT_URL),
                   help="the service (default: $FLIGHT_URL or %s)" % DEFAULT_URL)
    p.add_argument("--token", default=os.environ.get("RUNNER_TOKEN", ""),
                   help="bearer token (default: $RUNNER_TOKEN)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="can the service take a job now?")
    kill = sub.add_parser("kill", help="stop a job")
    kill.add_argument("job_id")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.cmd != "health" and not args.token:
            raise Stop("no token: export RUNNER_TOKEN=... (the service's .env) or pass --token")
        return COMMANDS[args.cmd](Api(args.url, args.token), args)
    except Stop as e:
        say(str(e))
        return e.code
    except Unreachable as e:
        say(f"cannot reach the service: {e}")
        return EXIT_UNREACHABLE
    except KeyboardInterrupt:
        say("interrupted")
        return EXIT_INTERRUPTED


def _terminate(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)       # a supervisor's stop = Ctrl-C
    sys.exit(main())
```

```bash
chmod +x scripts/flight.py
```

- [ ] **Step 4: รันให้เห็นว่าผ่าน**

Run: `conda run -n drone python -m pytest -q tests/test_flight_client.py`
Expected: `10 passed`

Run: `conda run -n drone python -m pytest -q 2>&1 | tail -1`
Expected: `221 passed`

Run: `python3 scripts/flight.py --help` (ไม่ติดต่อ service)
Expected: usage ที่มี `{health,kill}`

- [ ] **Step 5: Commit**

```bash
git add scripts/flight.py tests/test_flight_client.py
git commit -m "feat: flight.py client talks to the service (health, kill, upload, SSE reader)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01U58PizJ3sdz11yCZuVzp47"
```

---

### Task 4: `flight.py run` / `watch`

**Files:**
- Modify: `scripts/flight.py` (แทนที่ตั้งแต่บรรทัด `# -- command line ---` จนจบไฟล์)
- Modify: `tests/test_flight_client.py` (import ด้านบน + ต่อท้ายไฟล์)
- Modify: `.gitignore`, `docs/progress.md`

**Interfaces:**
- Consumes: ทุกอย่างในหัวข้อ Produces ของ Task 3 · `stream` ของ service จริงจาก Task 2 (ในเทสต์ `test_real_service_watch_replays_a_flown_job`)
- Produces:
  - `flight.py run IMAGE [--timeout S] [--out DIR] [--wait S]` · `flight.py run --file F --kind image|bundle --name N [...]` · `flight.py watch JOB_ID [--out DIR]`
  - stdout: หนึ่งบรรทัด JSON `{"job_id","state","reason","score","out_dir","not_downloaded"}` ทุกครั้งที่รู้ `job_id` แล้ว · ไม่มี `job_id` = stdout ว่าง
  - ไฟล์: `<out>/<job_id>/job.json` (คำตอบของ `GET /jobs/{id}` หลังจบ) + ทุกไฟล์ใน `result.files`
  - ฟังก์ชัน: `wait_ready(api, deadline, waited)`, `submit(api, args) -> (status, body)`, `follow(api, job_id, progress) -> bool`, `poll(api, job_id, progress)`, `collect(api, job_id, out_root) -> (job, out, failed)`, `report(...)`, `track(api, job_id, out_root) -> int`, `cmd_run`, `cmd_watch`, `class Progress`

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

ใน `tests/test_flight_client.py` แก้ import ด้านบน จาก

```python
import os
import socket
import sys
```

เป็น

```python
import os
import signal
import socket
import subprocess
import sys
```

แล้วต่อท้ายไฟล์ (เว้นสองบรรทัดว่างจากของเดิม):

```python
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
    assert headers["authorization"] == f"Bearer {TOKEN}" and headers["content-type"] == "application/json"
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
    (401, {"detail": "missing or wrong bearer token"}, "HTTP 401 (token wrong or missing)")])
def test_a_refused_job_shows_what_the_service_said(flight, capsys, service, status, body, says):
    svc = service(flown(**{"POST /jobs": [(status, body)]}))
    code, lines, err = run(flight, capsys, svc.url, "run", "perkiepai/x:1")
    assert (code, lines) == (2, []) and says in err
    assert svc.calls() == ["GET /healthz", "POST /jobs"]              # asked once, followed nothing


def test_run_needs_exactly_one_of_image_and_file(flight, capsys, tmp_path):
    for argv in (["run"], ["run", "perkiepai/x:1", "--file", "x.tar", "--kind", "image", "--name", "x"],
                 ["run", "--file", "x.tar"], ["run", "--file", "x.tar", "--kind", "zip", "--name", "x"]):
        with pytest.raises(SystemExit) as e:
            flight.main(["--url", closed_port(), "--token", TOKEN, *argv])
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
    assert headers["authorization"] == f"Bearer {TOKEN}" and body == archive.read_bytes()


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
                            env={**os.environ, "FLIGHT_URL": svc.url, "RUNNER_TOKEN": TOKEN, **env})


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
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `conda run -n drone python -m pytest -q tests/test_flight_client.py 2>&1 | tail -3`
Expected: เทสต์ใหม่ของ `run` / `watch` ล้ม ส่วนใหญ่ด้วย `SystemExit: 2` (argparse: `invalid choice: 'run'`) · 10 ตัวของ Task 3 กับ `test_a_terminal_that_is_not_utf8_does_not_break_the_client` (ใช้แค่ `health`) ยังผ่าน

- [ ] **Step 3: เพิ่ม `run` / `watch` ใน `scripts/flight.py`**

ลบตั้งแต่บรรทัด `# -- command line -------------------------------------------------------------` จนจบไฟล์ (เหลือบรรทัดสุดท้ายเป็น `    return EXIT_OK` ของ `cmd_kill`) แล้วเว้นสองบรรทัดว่าง ต่อท้ายด้วย:

```python
# -- run / watch --------------------------------------------------------------

class Progress:
    """What the flight looks like on stderr: one line per state change and
    one position line every SHOW_EVERY_S. Remembers the last state seen."""

    def __init__(self):
        self.state, self._shown = None, None

    def on_state(self, state, reason=None):
        if state != self.state:
            self.state = state
            say(f"state {state}" + (f" ({reason})" if reason else ""))

    def on_telemetry(self, t):
        now = time.monotonic()
        if self._shown is not None and now - self._shown < SHOW_EVERY_S:
            return
        self._shown = now
        agent = t.get("agent_state") or (t.get("agent") or {}).get("state")
        alt = t.get("alt_m")
        alt = round(alt, 1) if isinstance(alt, (int, float)) else alt
        say(f"{self.state} alt={alt} lat={t.get('lat')} lon={t.get('lon')} "
            f"mode={t.get('mode')} agent={agent}")


def wait_ready(api, deadline, waited):
    """Return once /healthz says ready. Degraded: stop now, waiting cannot
    fix it. Still busy at `deadline`: stop."""
    told = False
    while True:
        status, health = api.json("GET", "/healthz")
        if status != 200:
            raise Stop(explain(status, health))
        if health.get("ok") is False:
            raise Stop(f"service degraded (phase {health.get('phase')}): someone has to fix "
                       "the machine first (the service README says how)")
        if health.get("ready"):
            return
        if time.monotonic() >= deadline:
            raise Stop(f"service still busy after {waited:g}s (phase {health.get('phase')}, "
                       f"pending {health.get('pending')}): try again later or raise --wait")
        if not told:
            say(f"service busy (phase {health.get('phase')}, pending {health.get('pending')}); waiting")
            told = True
        sleep(READY_POLL_S)


def submit(api, args):
    """(status, body) of POST /jobs for an image name or a file."""
    if args.file:
        query = {"kind": args.kind, "name": args.name}
        if args.timeout is not None:
            query["flight_timeout_s"] = args.timeout
        say(f"uploading {args.file} ({os.path.getsize(args.file)} bytes)")
        return api.upload(args.file, urllib.parse.urlencode(query))
    body = {"image": args.image}
    if args.timeout is not None:
        body["flight_timeout_s"] = args.timeout
    return api.json("POST", "/jobs", body)


def follow(api, job_id, progress):
    """True once the stream delivered the job's `end`. False when there is
    no stream to be had (an older service, events this client cannot read,
    nothing for STREAM_GIVE_UP_S): the caller polls instead. A broken line
    is reconnected from the last telemetry line that arrived whole."""
    last_id, backoff, down_since = 0, BACKOFF_S, None
    while True:
        try:
            for event, data, eid in api.stream(job_id, last_id):
                backoff, down_since = BACKOFF_S, None
                data = json.loads(data)
                if event == "telemetry":
                    last_id = int(eid)
                    progress.on_telemetry(data)
                elif event == "state":
                    progress.on_state(data.get("state"), data.get("reason"))
                elif event == "end":
                    progress.on_state(data.get("state"), data.get("reason"))
                    return True
            why = "the service closed the stream"
        except HttpError as e:
            if e.status == 401:
                raise Stop(str(e))
            if e.status in (404, 405, 501):         # no such endpoint, or no such job:
                return False                        # the poll's own answer tells which
            why = str(e)
        except Unreachable as e:
            why = str(e)
        except (ValueError, TypeError) as e:        # an event this client cannot read:
            say(f"unreadable stream event ({e})")   # reconnecting would only bring it again
            return False
        now = time.monotonic()
        down_since = now if down_since is None else down_since
        if now - down_since >= STREAM_GIVE_UP_S:
            say(f"no stream for {STREAM_GIVE_UP_S:g}s ({why})")
            return False
        say(f"stream lost ({why}); reconnecting in {backoff:g}s after line {last_id}")
        sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX_S)


def poll(api, job_id, progress):
    """GET /jobs/{id} every POLL_S until the job ended."""
    down_since = None
    while True:
        try:
            status, job = api.json("GET", f"/jobs/{job_id}")
            if status >= 500:                       # a proxy in front of a restarting service
                raise Unreachable(explain(status, job))
        except Unreachable as e:
            now = time.monotonic()
            down_since = now if down_since is None else down_since
            if now - down_since >= POLL_GIVE_UP_S:
                raise Stop(f"cannot reach the service for {POLL_GIVE_UP_S:g}s: {e}")
            sleep(POLL_S)
            continue
        down_since = None
        if status != 200:
            raise Stop(explain(status, job))
        progress.on_state(job.get("state"), job.get("reason"))
        if job.get("state") in TERMINAL:
            return
        if job.get("telemetry"):
            progress.on_telemetry(job["telemetry"])
        sleep(POLL_S)


def collect(api, job_id, out_root):
    """The ended job's record and every file it lists, into <out>/<job_id>/.
    (job, folder, names that could not be fetched)."""
    status, job = api.json("GET", f"/jobs/{job_id}")
    if status != 200:
        raise Stop(explain(status, job))
    out = os.path.join(out_root, job_id)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "job.json.part"), "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=1)
    os.replace(os.path.join(out, "job.json.part"), os.path.join(out, "job.json"))
    result = job.get("result") or {}
    failed = []
    for name, path in sorted((result.get("files") or {}).items()):
        plain = name == os.path.basename(name) and name not in ("", ".", "..", "job.json")
        if not plain or not api.download(path, os.path.join(out, name)):
            say(f"could not download {name}")
            failed.append(name)
    for name in result.get("missing") or []:            # the service's own word: no guessing
        say(f"missing {name}: the service has no such file for this job")
    return job, out, failed


def report(job_id, state, reason=None, score=None, out_dir=None, not_downloaded=()):
    """The one stdout line a calling program reads."""
    print(json.dumps({"job_id": job_id, "state": state, "reason": reason, "score": score,
                      "out_dir": out_dir, "not_downloaded": list(not_downloaded)}), flush=True)


def track(api, job_id, out_root):
    """Follow a job to its end, fetch what it left, report. The exit code."""
    progress = Progress()
    try:
        if not follow(api, job_id, progress):
            say(f"polling every {POLL_S:g}s instead")
            poll(api, job_id, progress)
        job, out, failed = collect(api, job_id, out_root)
    except KeyboardInterrupt:
        say(f"interrupted. Job {job_id} was NOT killed and keeps running on the service.")
        say(f"  follow it again:  flight.py watch {job_id}")
        say(f"  stop it:          flight.py kill {job_id}")
        report(job_id, progress.state)
        return EXIT_INTERRUPTED
    except (Stop, Unreachable) as e:
        say(str(e) if isinstance(e, Stop) else f"cannot reach the service: {e}")
        if progress.state is not None:              # the job is real: say how to get back to it
            say(f"job {job_id} was last seen {progress.state}:  flight.py watch {job_id}")
        report(job_id, progress.state)
        return e.code if isinstance(e, Stop) else EXIT_UNREACHABLE
    result = job.get("result") or {}
    score = (result.get("score") or {}).get("score")
    say(f"{job['state']}" + (f" ({job.get('reason')}: {job.get('detail')})" if job.get("reason") else "")
        + f"; score {score}; flew {result.get('flight_s')}s; files in {out}")
    report(job_id, job["state"], job.get("reason"), score, out, failed)
    if failed:
        return EXIT_UNREACHABLE
    return EXIT_OK if job["state"] == "done" else EXIT_FAILED


def cmd_run(api, args):
    if args.file and not os.path.isfile(args.file):
        raise Stop(f"no such file: {args.file}")
    deadline = time.monotonic() + args.wait
    while True:
        wait_ready(api, deadline, args.wait)
        status, body = submit(api, args)
        if status == 202:
            break
        if status != 409:
            raise Stop(explain(status, body))
        if time.monotonic() >= deadline:
            raise Stop(f"{explain(status, body)}; still so after {args.wait:g}s")
        say("someone else took the pending slot first; waiting for ready again")
        sleep(READY_POLL_S)
    say(f"job {body['job_id']} accepted")
    return track(api, body["job_id"], args.out)


def cmd_watch(api, args):
    return track(api, args.job_id, args.out)


# -- command line -------------------------------------------------------------

COMMANDS = {"health": cmd_health, "run": cmd_run, "watch": cmd_watch, "kill": cmd_kill}


def parser():
    p = argparse.ArgumentParser(prog="flight.py", description="Submit one image to "
                                "flight-service, follow the flight, fetch the results.")
    p.add_argument("--url", default=os.environ.get("FLIGHT_URL", DEFAULT_URL),
                   help="the service (default: $FLIGHT_URL or %s)" % DEFAULT_URL)
    p.add_argument("--token", default=os.environ.get("RUNNER_TOKEN", ""),
                   help="bearer token (default: $RUNNER_TOKEN)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="can the service take a job now?")
    run = sub.add_parser("run", help="submit an image, follow the flight, fetch the results")
    run.add_argument("image", nargs="?", help="image on a registry, e.g. perkiepai/truck-detector:TAG")
    run.add_argument("--file", help="send this file instead of an image name")
    run.add_argument("--kind", choices=("image", "bundle"),
                     help="what --file is: a `docker save` archive or a build bundle")
    run.add_argument("--name", help="name for the image made from --file")
    run.add_argument("--timeout", type=int, metavar="S", help="flight time limit (flight_timeout_s)")
    run.add_argument("--wait", type=float, default=60, metavar="S",
                     help="how long to wait for the service to be ready (default 60)")
    watch = sub.add_parser("watch", help="follow a job that is already there, fetch its results")
    watch.add_argument("job_id")
    for cmd in (run, watch):
        cmd.add_argument("--out", default="flight-out", metavar="DIR",
                         help="results go to DIR/<job_id>/ (default flight-out)")
    kill = sub.add_parser("kill", help="stop a job")
    kill.add_argument("job_id")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.cmd == "run":
        if bool(args.image) == bool(args.file):
            p.error("run takes an IMAGE or --file, one of them")
        if args.file and not (args.kind and args.name):
            p.error("--file needs --kind image|bundle and --name")
    try:
        if args.cmd != "health" and not args.token:
            raise Stop("no token: export RUNNER_TOKEN=... (the service's .env) or pass --token")
        return COMMANDS[args.cmd](Api(args.url, args.token), args)
    except Stop as e:
        say(str(e))
        return e.code
    except Unreachable as e:
        say(f"cannot reach the service: {e}")
        return EXIT_UNREACHABLE
    except KeyboardInterrupt:
        say("interrupted before a job was accepted (if the service did take one, it is in GET /jobs)")
        return EXIT_INTERRUPTED


def _terminate(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)       # a supervisor's stop = Ctrl-C
    sys.exit(main())
```

สิ่งที่ต้องคงไว้:
- `track()` เป็นที่เดียวที่จับ `KeyboardInterrupt` หลังรู้ `job_id` และ**ไม่มีการเรียก `/kill`** ที่นั่น
- `signal.signal(SIGTERM, ...)` อยู่ใต้ `if __name__ == "__main__":` เท่านั้น (เทสต์ import ไฟล์นี้เป็น module ในโปรเซสของ pytest)
- `follow()` คืน `False` ทันทีเมื่ออ่าน event ไม่ออก: ต่อใหม่จะได้ event เดิมซ้ำไม่จบ เพราะ event `state` ที่มาก่อนทุกครั้งทำให้ตัวนับ "ไม่ได้ stream มานานเท่าไร" ถูกล้าง

- [ ] **Step 4: รันให้เห็นว่าผ่าน**

Run: `conda run -n drone python -m pytest -q tests/test_flight_client.py`
Expected: `38 passed`

Run: `conda run -n drone python -m pytest -q 2>&1 | tail -1`
Expected: `249 passed`

Run: `python3 scripts/flight.py run 2>&1 | tail -1; echo "exit=${PIPESTATUS[0]}"` (ไม่ติดต่อ service: argparse ปฏิเสธก่อน · `$?` หลัง pipe เป็นของ `tail` จึงใช้ `PIPESTATUS`)
Expected: `flight.py: error: run takes an IMAGE or --file, one of them` และ `exit=2`

- [ ] **Step 5: `.gitignore`**

เพิ่มบรรทัด `flight-out/` ใต้บรรทัด `mock-out/`

- [ ] **Step 6: อัปเดตแถว C ใน `docs/progress.md`**

คอลัมน์สถานะ → `🟡 server + client เสร็จ (Task 1–4 · 249 tests) · ⛔ รออนุมัติก่อนรันจริง (Task 5)`
ในโครงโฟลเดอร์: บรรทัด `├── scripts/                  run-service.sh · stop-service.sh · mock-caller.sh` → `├── scripts/                  run-service.sh · stop-service.sh · flight.py (client) · mock-caller.sh`

- [ ] **Step 7: Commit**

```bash
git add scripts/flight.py tests/test_flight_client.py .gitignore docs/progress.md
git commit -m "feat: flight.py run/watch follow a job live and fetch its results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01U58PizJ3sdz11yCZuVzp47"
```

- [ ] **Step 8: ⛔ ประตูอนุมัติ (client + เทสต์)** สรุปผู้ใช้: จำนวนเทสต์ (249), ตาราง exit code, รายการสิ่งที่เติมจาก spec หัวข้อ 4 · ขออนุมัติรันจริงบน sim (Task 5: บิน 1 งาน ~10 นาที ใช้ GPU + อัปโหลดไฟล์ 2 GB ที่ไม่เปิด sim) · รออนุมัติก่อน Task 5

---

### Task 5: รันจริงหนึ่งงาน + อัปโหลดไฟล์ใหญ่

**Files:**
- Create: `docs/evidence/verification-sse-preflight.log`, `docs/evidence/verification-sse-run1a.{json,log}`, `docs/evidence/verification-sse-run1b.{json,log}`, `docs/evidence/verification-sse-run2.{json,log}`, `docs/evidence/verification-sse-stream-sample.txt`
- Modify: `docs/verification.md`, `docs/progress.md`

**Interfaces:**
- Consumes: `scripts/flight.py` (Task 3–4), route stream (Task 2), `scripts/run-service.sh`, `scripts/stop-service.sh`, `scripts/preflight.sh`
- Produces: หลักฐานว่า client กับ stream ทำงานกับ sim จริง · ไม่มีโค้ดใหม่

เกณฑ์ผ่านของ Task นี้คือ **client เล่าเรื่องเดียวกับ service** (event ครบ, ไฟล์ตรง, exit code ตรงกับ state) ไม่ใช่ "บินจบ done" · งานจริงล่าสุดบนเครื่องนี้จบ `failed / arming_timeout` ถ้ารอบนี้จบแบบเดียวกัน client ต้องออก 1 พร้อมไฟล์ครบ แล้วรายงานผู้ใช้ **ห้ามไปแก้ sim ในแผนนี้**

- [ ] **Step 1: ตรวจก่อนรัน (อ่านอย่างเดียว)**

```bash
cd ~/pai/flight-service
./scripts/preflight.sh | tee docs/evidence/verification-sse-preflight.log     # ต้องไม่มีข้อที่ไม่ผ่าน (exit 0)
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv
df -h /var/lib/docker data | tail -2                                  # ว่าง ≥ 45 GB (40 ของ MIN_FREE_GB + 2 × ไฟล์ 2 GB)
curl -s -m 2 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/  # 000 = sim ไม่ได้เปิด
curl -s -m 2 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8090/  # 000 = เว็บ drone-sitl ไม่ได้เปิด
curl -s -m 2 http://127.0.0.1:8095/healthz                            # ถ้า service เปิดอยู่: ต้อง "phase":"idle","pending":0
```

ถ้า service มีงานค้าง (`phase` ไม่ใช่ `idle` หรือ `pending` ไม่ใช่ 0) หรือ sim เปิดอยู่: หยุดถามผู้ใช้ ห้าม restart ทับงานของคนอื่น

- [ ] **Step 2: restart service ให้ใช้โค้ดใหม่**

```bash
./scripts/stop-service.sh
./scripts/run-service.sh                       # run-service: up (pid ...)
set -a; source .env; set +a
export FLIGHT_URL="http://${RUNNER_HOST:-127.0.0.1}:${RUNNER_PORT:-8095}"
A="Authorization: Bearer $RUNNER_TOKEN"
python3 scripts/flight.py health; echo "exit=$?"
```

Expected: `{"ok": true, "ready": true, "phase": "idle", "pending": 0}` และ `exit=0`

- [ ] **Step 3: รอบ 1a: ส่งงาน ตามสด แล้วหยุด client กลางบินด้วย SIGTERM**

```bash
python3 scripts/flight.py run perkiepai/truck-detector:20260929-214240 --timeout 600 --out flight-out \
    > docs/evidence/verification-sse-run1a.json 2> docs/evidence/verification-sse-run1a.log &
CLIENT=$!
until grep -q "flying alt=" docs/evidence/verification-sse-run1a.log; do
    kill -0 $CLIENT 2>/dev/null || { echo "client ended before flying"; break; }
    sleep 2
done
sleep 30                                        # ให้ได้ตำแหน่งสัก 6 บรรทัด
kill -TERM $CLIENT; wait $CLIENT; echo "exit=$?"
cat docs/evidence/verification-sse-run1a.json
JOB=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["job_id"])' docs/evidence/verification-sse-run1a.json)
curl -s "$FLIGHT_URL/jobs/$JOB" -H "$A" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])'
```

ใช้ `SIGTERM` ไม่ใช่ `SIGINT`: shell ที่ไม่ interactive ตั้ง SIGINT ของโปรเซสเบื้องหลังเป็น ignore และ `SIGTERM` คือสิ่งที่ระบบของผู้เรียกจะส่งจริง

Expected:
- log มี `state pulling` → `state booting` → `state flying` → บรรทัด `flying alt=... lat=... lon=... mode=... agent=...` ทุก ~5 s
- `exit=3` · JSON = `{"job_id": "j-...", "state": "flying", "reason": null, "score": null, "out_dir": null, "not_downloaded": []}`
- log ลงท้ายด้วย `interrupted. Job j-... was NOT killed ...` และวิธี `watch` / `kill`
- คำสั่งสุดท้ายพิมพ์ `flying` = **งานยังบินอยู่หลัง client ตาย**

ถ้า client จบก่อนถึง `flying` (ลูปพิมพ์ `client ended before flying`): อ่าน log กับ JSON · ถ้างาน fail ก่อนบิน (เช่น `sim_boot_timeout`) ให้ไป Step 6 เลยด้วยงานนั้น แล้วรายงานผู้ใช้

- [ ] **Step 4: ระหว่างงานยังบิน: เก็บตัวอย่าง stream ดิบ**

```bash
timeout 4 curl -sN "$FLIGHT_URL/jobs/$JOB/stream" -H "$A" | head -c 4000 > docs/evidence/verification-sse-stream-sample.txt
head -c 600 docs/evidence/verification-sse-stream-sample.txt
```

Expected: ขึ้นต้นด้วย `event: state` + `data: {"state":"flying",...}` ตามด้วย `id: 1` / `event: telemetry` / `data: {...}`

- [ ] **Step 5: รอบ 1b: `watch` ต่อจนจบ**

```bash
python3 scripts/flight.py watch "$JOB" --out flight-out \
    > docs/evidence/verification-sse-run1b.json 2> docs/evidence/verification-sse-run1b.log; echo "exit=$?"
cat docs/evidence/verification-sse-run1b.json; tail -4 docs/evidence/verification-sse-run1b.log
```

Expected: บรรทัดตำแหน่งทุก ~5 s จนจบ → `state done` (หรือ `failed`) → บรรทัดสรุป `...; score ...; flew ...s; files in flight-out/j-...` · `exit=0` เมื่อ JSON มี `"state": "done"` · `exit=1` เมื่อ `failed` / `killed` · `"not_downloaded": []`

- [ ] **Step 6: เทียบกับของจริงบน service**

```bash
RUN=data/runs/$JOB
for f in flight-out/$JOB/*; do n=$(basename "$f"); [ "$n" = job.json ] && continue
    cmp -s "$f" "$RUN/$n" && echo "same  $n" || echo "DIFF  $n"; done
ls flight-out/$JOB | grep -c '\.part$'                                # 0
python3 -c 'import json,sys; j=json.load(open(sys.argv[1])); r=j["result"]; print(j["state"], j["reason"], sorted(r["files"]), r["missing"])' flight-out/$JOB/job.json
curl -sN "$FLIGHT_URL/jobs/$JOB/stream" -H "$A" | grep -c '^event: telemetry'
wc -l < "$RUN/telemetry.jsonl"
curl -sN "$FLIGHT_URL/jobs/$JOB/stream" -H "$A" -H 'Last-Event-ID: 100' | grep -m1 '^id:'
curl -s "$FLIGHT_URL/healthz"
curl -s -m 2 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
```

Expected: ทุกไฟล์ `same` ไม่มี `DIFF` · ไม่มี `.part` · จำนวน event `telemetry` ของ stream ทั้งสาย **เท่ากับ**จำนวนบรรทัดของ `telemetry.jsonl` · ต่อด้วย `Last-Event-ID: 100` ได้บรรทัดแรกเป็น `id: 101` · `/healthz` กลับเป็น `idle` / `ready: true` · sim ปิดแล้ว (`000`)

- [ ] **Step 7: รอบ 2: อัปโหลดไฟล์ใหญ่ (ไม่เปิด sim)**

ไฟล์ศูนย์ล้วน 2 GB เป็น tar ว่างที่ถูกต้อง แต่ไม่มี `manifest.json` → service รับไฟล์ครบแล้วงาน `failed / archive_rejected` ก่อนแตะ sim · สิ่งที่วัดคือการส่งไฟล์ใหญ่ของ client

```bash
truncate -s 2G /tmp/flight-junk.tar
/usr/bin/time -v python3 scripts/flight.py run --file /tmp/flight-junk.tar --kind image --name junk --out flight-out \
    > docs/evidence/verification-sse-run2.json 2> docs/evidence/verification-sse-run2.log; echo "exit=$?"
cat docs/evidence/verification-sse-run2.json
grep -E "uploading|state |Maximum resident set size|Elapsed \(wall clock\)" docs/evidence/verification-sse-run2.log
rm -f /tmp/flight-junk.tar
ls data/uploads/ | wc -l                                              # 0: service ลบไฟล์ที่รับมาแล้ว
curl -s "$FLIGHT_URL/healthz"
```

Expected: `exit=1` · JSON `"state": "failed", "reason": "archive_rejected"` · `Maximum resident set size` ต่ำกว่า 100,000 kB (client ส่งทีละ 1 MB ไม่โหลดทั้งไฟล์เข้า RAM) · `/healthz` เป็น `idle`

- [ ] **Step 8: บันทึกผลใน `docs/verification.md`**

ต่อท้ายไฟล์ด้วยหัวข้อใหม่ ใส่ค่าจริงจากไฟล์ `docs/evidence/verification-sse-*` แทนทุก `<...>` (ห้ามใส่ค่าที่ไม่ได้วัด ถ้าขั้นไหนไม่ผ่านให้เขียนว่าไม่ผ่านพร้อมข้อความจริง):

```markdown
## Stream สด (SSE) + client `flight.py` · 2026-10-06

> **สรุป: <ผ่าน / ไม่ผ่าน ข้อไหน>** · flight-service `feat/sse-client` @ `<git rev-parse --short HEAD>` · ผู้เรียก: `scripts/flight.py` บนเครื่องเดียวกัน · log ดิบ: `docs/evidence/verification-sse-*`

| รอบ | ทำอะไร | ผล |
|---|---|---|
| 1a | `flight.py run perkiepai/truck-detector:20260929-214240` แล้ว `SIGTERM` client หลังบิน 30 s | exit `<n>` · JSON `state: <...>` · งานบน service ยัง `<state>` หลัง client ตาย |
| 1b | `flight.py watch <job_id>` ต่อจนจบ | exit `<n>` · `<state>` / `<reason>` · score `<...>` · บิน `<...>` s · ไฟล์ `<จำนวน>` ตัว ตรงกับ `data/runs/` ทุกตัว · `not_downloaded: []` |
| 1 | stream ทั้งสายหลังจบ | event `telemetry` `<n>` ตัว = `telemetry.jsonl` `<n>` บรรทัด · `Last-Event-ID: 100` → เริ่มที่ `id: 101` |
| 2 | `flight.py run --file` ไฟล์ 2 GB | exit `<n>` · `<state>` / `<reason>` · ใช้เวลา `<...>` · RAM สูงสุดของ client `<...>` MB |

**ตรวจหลังทุกรอบ:** `/healthz` = `<...>` · sim ปิด (`:8080` ไม่ตอบ) · `data/uploads/` ว่าง

**สิ่งที่พบ:** <ข้อที่ต่างจากที่คาด หรือ "ไม่มี">
```

- [ ] **Step 9: อัปเดตแถว C ใน `docs/progress.md` แล้ว commit**

คอลัมน์สถานะ → `🟡 รันจริงแล้ว (<ผ่าน / ไม่ผ่าน>: docs/verification.md) · ⛔ รออนุมัติก่อน Task 6`

```bash
git add docs/verification.md docs/progress.md docs/evidence/verification-sse-preflight.log docs/evidence/verification-sse-stream-sample.txt \
        docs/evidence/verification-sse-run1a.json docs/evidence/verification-sse-run1a.log docs/evidence/verification-sse-run1b.json \
        docs/evidence/verification-sse-run1b.log docs/evidence/verification-sse-run2.json docs/evidence/verification-sse-run2.log
git commit -m "docs: real run of the SSE stream and flight.py

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01U58PizJ3sdz11yCZuVzp47"
```

- [ ] **Step 10: ⛔ ประตูอนุมัติ (รันจริง)** สรุปผู้ใช้ด้วยตารางใน `docs/verification.md` + สิ่งที่พบ · service ตัวจริงตอนนี้รันโค้ดของ `feat/sse-client` (บอกผู้ใช้ให้ชัด) · รออนุมัติก่อน Task 6

---

### Task 6: README + งานที่เลื่อน

**Files:**
- Modify: `README.md`, `docs/followups.md`, `docs/progress.md`

**Interfaces:**
- Consumes: ผลของ Task 5 (คำสั่งใน README ต้องเป็นคำสั่งที่รันผ่านจริงใน Task 5)
- Produces: เอกสารอย่างเดียว

- [ ] **Step 1: `README.md` ตาราง endpoint และตัวอย่าง curl**

ในตารางใต้หัวข้อ "เรียก API" เพิ่มแถวนี้ใต้แถว `GET /jobs/{id}`:

```markdown
| `GET` | `/jobs/{id}/stream` | ติดตามสด (Server-Sent Events) |
```

ในบล็อก curl ถัดลงมา เพิ่มบรรทัดนี้ใต้บรรทัด `curl -s $R/jobs/j-20261005-033950-b5fa -H "$H"                  # poll ทุก 1–5 s`:

```bash
curl -sN $R/jobs/j-20261005-033950-b5fa/stream -H "$H"          # หรือติดตามสด: event state / telemetry / end (docs/api.md)
```

- [ ] **Step 2: `README.md` หัวข้อ client**

แทนที่ย่อหน้า `ทดลองครบวงจรด้วยสคริปต์ที่ทำตัวเป็นผู้เรียก: \`./scripts/mock-caller.sh <image> [flight_timeout_s]\` (ผลอยู่ใน \`mock-out/<job_id>/\` · \`KILL_AFTER_S=90\` = kill หลังบิน 90 s)` ด้วย:

````markdown
### client สำเร็จรูป: `scripts/flight.py`

ไฟล์เดียว ใช้แค่ Python 3.8+ (ไม่ต้องติดตั้งอะไร) copy ไปเครื่องผู้เรียกได้เลย · ส่งงาน → ตามสดทาง stream → ดึงไฟล์ผล → บอกผลด้วย exit code

```bash
export FLIGHT_URL=http://127.0.0.1:8095 RUNNER_TOKEN=<token ใน .env ของ service>

scripts/flight.py health                                   # {"ok": true, "ready": true, ...}  exit 0 = ส่งงานได้
scripts/flight.py run perkiepai/truck-detector:20260929-214240 --timeout 600 --out results
scripts/flight.py run --file agent.tar --kind image --name my-agent      # ส่งไฟล์แทนชื่อ image (bundle: --kind bundle)
scripts/flight.py watch j-20261005-033950-b5fa --out results             # กลับมาตามงานเดิม เช่นหลัง client ถูกปิด
scripts/flight.py kill j-20261005-033950-b5fa
```

| exit code ของ `run` / `watch` | ความหมาย |
|---|---|
| `0` | งานจบ `done` และไฟล์ผลอยู่ครบใน `<out>/<job_id>/` |
| `1` | งานจบ `failed` หรือ `killed` (ไฟล์เท่าที่มีอยู่ในโฟลเดอร์เดียวกัน) |
| `2` | ติดต่อ service ไม่ได้ / service ไม่รับงาน (ไม่ ready เกิน `--wait`, degraded, 4xx) / ดึงไฟล์ผลไม่ครบ |
| `3` | client ถูกขัดจังหวะ (Ctrl-C, SIGTERM) · **งานไม่ถูก kill** ยังรันต่อบน service ใช้ `watch` กลับมาตาม หรือ `kill` ถ้าจะหยุด |

- ความคืบหน้าพิมพ์ทาง stderr · stdout มีบรรทัดเดียวเป็น JSON ให้โปรแกรมอ่าน: `{"job_id", "state", "reason", "score", "out_dir", "not_downloaded"}` (พิมพ์ทุกครั้งที่ได้ `job_id` แล้ว รวมตอน exit 2 และ 3)
- `run` รอ `ready` ให้เอง (default 60 s ปรับด้วย `--wait`) · คิวจริงยังเป็นของผู้เรียก
- สายขาด: ต่อใหม่เองจากบรรทัดล่าสุดที่ได้ · ไม่ได้ stream เกิน 60 s หรือ service รุ่นเก่า: เปลี่ยนไป poll เอง
- ไฟล์ผล: `<out>/<job_id>/job.json` + ทุกไฟล์ในหัวข้อ "ผลที่ได้" ด้านล่าง

`scripts/mock-caller.sh` (สคริปต์ทดสอบรุ่นแรก ใช้ poll) ยังอยู่: `./scripts/mock-caller.sh <image> [flight_timeout_s]` ผลอยู่ใน `mock-out/<job_id>/`
````

ตรวจว่าทุกคำสั่งในบล็อกนี้ตรงกับที่รันผ่านใน Task 5 (ชื่อ flag, ชื่อ image) ถ้า Task 5 พบว่าต้องใช้ต่างไป ให้แก้ README ตามของจริง

- [ ] **Step 3: `docs/followups.md`**

ในหัวข้อ "ข้อเล็กที่ยังไม่แก้" แก้บรรทัด `- mock-caller.sh tracebacks on 409 instead of waiting for ready` เป็น:

```markdown
- ~~mock-caller.sh tracebacks on 409 instead of waiting for ready~~ ใช้ `scripts/flight.py` แทน (รอ `ready` และลองใหม่หลัง 409 เอง) · `mock-caller.sh` ลบได้เมื่อเจ้าของบอก
```

ต่อท้ายไฟล์:

```markdown

## เลื่อนไว้จากงาน stream + client (2026-10-06)

- **ความพร้อมของเครื่องใน `/healthz`:** ตอนนี้ `ready` บอกแค่ว่าช่องรอว่าง ไม่ได้บอกว่าเครื่องบินได้ (GPU, Isaac, ไฟล์แผนที่) · ฐานที่มีแล้ว: `scripts/preflight.sh` / `flight_service/preflight.py` · ผู้ใช้แยกไว้ทำทีหลัง
- SSE ผ่าน reverse proxy จริง (nginx / Caddy) ยังไม่ได้ลอง: ส่ง `X-Accel-Buffering: no` และ `: ping` ทุก 15 s แล้ว แต่ต้องตั้ง `proxy_read_timeout` ให้เกิน 15 s เอง
- `flight.py` อัปโหลดผ่าน `https://` ไม่ถามก่อน (`Expect: 100-continue` ใช้เฉพาะ `http://`) จึงส่งทั้งไฟล์แม้ service จะปฏิเสธ · อัปโหลดไม่ใช้ `http_proxy` จาก env
- stream ไม่มี log ของ agent และ detections (ทาง B): ถ้าผู้เรียกต้องการ ให้เพิ่มเป็น event ใหม่ที่มี `id` ของตัวเองแยกจาก telemetry
- ไม่จำกัดจำนวน stream ต่อ job: แต่ละสายเปิดไฟล์ 1 ตัวและวนทุก 0.2 s
- `flight.py` ไม่มี `list` / `get` (ใช้ curl) และไม่มี `KILL_AFTER_S` แบบ `mock-caller.sh`
```

- [ ] **Step 4: `docs/progress.md`**

คอลัมน์สถานะของแถว C → `✅ server + client + รันจริง + README · 249 tests · branch \`feat/sse-client\` เก็บไว้ให้เจ้าของ merge เอง`

- [ ] **Step 5: รันเทสต์ทั้งชุดอีกครั้งแล้ว commit**

Run: `conda run -n drone python -m pytest -q 2>&1 | tail -1`
Expected: `249 passed`

```bash
git add README.md docs/followups.md docs/progress.md
git commit -m "docs: README for flight.py and the stream; deferred items

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01U58PizJ3sdz11yCZuVzp47"
git status --short            # เหลือแต่ไฟล์ untracked ของงาน vendor ที่มีอยู่ก่อนแล้ว
```

- [ ] **Step 6: ⛔ ประตูอนุมัติ (เอกสาร)** สรุปผู้ใช้: commit ทั้งหมดบน `feat/sse-client` (`git log --oneline feat/vendor-drone-sitl..HEAD`) · branch เก็บไว้ ไม่ merge ไม่ push
