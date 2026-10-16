> **ประวัติ ไม่ใช่สถานะปัจจุบัน:** เอกสารนี้เก็บไว้เป็นหลักฐานของงานที่ทำเสร็จแล้ว ไม่ได้อัปเดตตามโค้ด (เช่นยังพูดถึง `RUNNER_TOKEN` ที่ถอดแล้ว) สถานะจริงดู [../design.md](../../../design.md) และ [../progress.md](../../../progress.md)

# Remove RUNNER_TOKEN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** flight-service and `scripts/flight.py` stop using the `RUNNER_TOKEN` bearer token entirely; the only people who call the service are insiders on the same machine (or network), so there is no login.

**Architecture:** Delete the `auth` dependency from `app.py`, the `token` field and its ≥ 32-char check from `Settings`, the `token` preflight check, and the `--token` / `RUNNER_TOKEN` handling plus the `Authorization` header from `flight.py`. The service keeps binding `127.0.0.1` by default (`RUNNER_HOST`), which is now the only gate. The unrelated `sitl_upload_token` (runner ↔ drone-sitl web server) stays.

**Tech Stack:** Python 3.8+ (flight.py, stdlib only), FastAPI + uvicorn (service), pytest. Run tests with `conda run -n drone python -m pytest -q` (baseline before this plan: **253 passed**).

**Spec:** wishlist item 1 (`wishlist.md`: "remove RUNNER TOKEN since it no need. the person call flight.py is only insider") plus the chat design approved 2026-10-09: remove everywhere, **no** `RUNNER_ALLOW_REMOTE` guard (explicitly declined), warn about `RUNNER_HOST` in docs instead.

## Global Constraints

- Do **not** add a `RUNNER_ALLOW_REMOTE` switch or any other host guard. User said to leave it out.
- `RUNNER_HOST` default stays `127.0.0.1`.
- Keep `sitl_upload_token` / `DRONE_SITL_UPLOAD_TOKEN` / `X-Upload-Token` exactly as they are (`config.py`, `sim.py`, `sitl.py`, their tests).
- `/healthz` behaviour unchanged. The seven endpoints keep their paths, statuses and bodies; only the 401 case goes away.
- Do not edit history: `docs/plan.md`, `docs/superpowers/plans/2026-10-06-*.md`, `docs/superpowers/specs/*`, `docs/verification*.log` keep their `RUNNER_TOKEN` mentions.
- `.env` (the user's real file) is not edited or deleted. Its old `RUNNER_TOKEN=` line becomes an ignored variable.
- Replies and doc prose to the user are Thai, conclusion first; code and test names are English like the surrounding code.
- **Commits:** `flight_service/config.py`, `tests/test_config.py`, `README.md` and several `docs/*` files already carry the user's uncommitted vendoring work. Do **not** run `git add -A` and do **not** commit those mixed files. This plan makes no commits; at the end, show `git status` / `git diff --stat` and ask the user how they want to commit.
- Stop for the user's approval after each task (approval-gates rule).

## Review Focus

1. A client that still sends `Authorization: Bearer <old token>` (old scripts, old `.env`) must keep working: the header is ignored, not rejected. (Task 1 test `test_a_leftover_authorization_header_is_ignored`.)
2. A `.env` that still contains `RUNNER_TOKEN=...`, or an environment with it set, must not crash or warn the service, `run-service.sh`, `preflight.sh` or `flight.py`. (Task 1 `test_from_env_needs_no_token`, Task 2 `test_a_leftover_runner_token_variable_is_ignored`.)
3. A missing/empty `.env` token must no longer stop `run-service.sh`; only a missing `.env` file may. (Task 1 step 7 manual check.)
4. `flight.py --token X` (old invocation in someone's script) now exits 2 with argparse's "unrecognized arguments" rather than silently working; this is intended and documented. (Task 2 `test_the_token_option_is_gone`.)
5. `flight.py health` and `kill` against a service that answers 401 for some other reason (e.g. a reverse proxy) must still print the service's message and exit 2 instead of crashing on the removed `WHAT[401]` entry. (Task 2 step 1 items 6-7: the existing 401 cases in `test_kill` and `test_a_refused_job_shows_what_the_service_said` now expect the generic `HTTP 401: ...` text.)

---

## File Structure

| File | Change |
|---|---|
| `flight_service/app.py` | remove `auth`, `expected`, `hmac`/`Depends` imports, `dependencies=[Depends(auth)]` on 6 routes, docstring |
| `flight_service/config.py` | remove `token` field and the `RUNNER_TOKEN` check |
| `flight_service/preflight.py` | remove `check_token`, its call, and the `RUNNER_TOKEN` placeholder in `run_checks` |
| `scripts/flight.py` | remove `--token`, `Api.token`, both `Authorization` headers, the "no token" stop, `WHAT[401]`, doc lines |
| `scripts/run-service.sh`, `scripts/mock-caller.sh`, `.env.example` | drop token wording / header |
| `tests/conftest.py`, `test_app.py`, `test_config.py`, `test_preflight.py`, `test_sim.py`, `test_worker.py`, `test_flight_client.py` | follow the code |
| `README.md`, `docs/api.md`, `docs/design.md`, `docs/SUMMARY.md`, `docs/followups.md`, `docs/progress.md` | prose follows the code; decision log row |

Task 1 = the service side. Task 2 = the client. Task 3 = docs + one real run. Task 1 and 2 are independent (an old client against the new service still works because the header is ignored).

---

### Task 1: Service stops checking a token

**Files:**
- Modify: `flight_service/app.py:1-2,10-13,45-51,161,168,172,176,186,198-201`
- Modify: `flight_service/config.py:29,70-72,78`
- Modify: `flight_service/preflight.py:67-70,210-211`
- Modify: `scripts/run-service.sh:12`, `scripts/mock-caller.sh:9,14,20,40,45`, `.env.example:1-2`
- Test: `tests/conftest.py:37-42`, `tests/test_app.py`, `tests/test_config.py`, `tests/test_preflight.py:10,71,184-186`, `tests/test_sim.py:13`, `tests/test_worker.py:19`

**Interfaces:**
- Produces: `Settings(drone_sitl_dir, runs_dir, host=..., ...)` — **no** `token` field, so the first positional field is now `drone_sitl_dir`. `create_app(settings, store, worker)` unchanged. `conftest.http(method, url, body=None, raw=False, ctype=None)` — the `token` parameter is gone, so the body is now the 3rd positional argument. `preflight.run_checks(env, run, which)` returns the same list minus the `token` check.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Change the tests first (they must fail against the old code)**

`tests/conftest.py` — `http()` loses `token`:

```python
def http(method, url, body=None, raw=False, ctype=None):
    """(status, parsed JSON | bytes)."""
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype or "application/json")
```

(delete the two lines `if token:` / `req.add_header("Authorization", ...)`; the rest of the function is unchanged.)

`tests/test_app.py`:

```bash
cd ~/pai/flight-service
# every call that passed TOKEN as the 3rd argument of http(): drop it
sed -i -E '/http\(/ s/, TOKEN//' tests/test_app.py
```

Then edit by hand:

1. Delete the line `TOKEN = "k" * 40` (line 13) and the blank line pair it leaves behind (keep two blank lines before `class StubWorker`).
2. `make()`: `s = Settings(token=TOKEN, drone_sitl_dir=tmp_path, runs_dir=tmp_path / "runs", **kw)` → `s = Settings(drone_sitl_dir=tmp_path, runs_dir=tmp_path / "runs", **kw)`
3. Replace `test_everything_else_needs_the_token` with:

```python
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
```

4. The big-file test (around line 141): remove the `headers={"Authorization": f"Bearer {TOKEN}"}` argument so it reads
   `req = urllib.request.Request(f"{url}/jobs/{jid}/files/telemetry.jsonl")`
5. `open_stream`:

```python
def open_stream(url, jid, last_id=None):
    req = urllib.request.Request(f"{url}/jobs/{jid}/stream")
    if last_id is not None:
        req.add_header("Last-Event-ID", str(last_id))
    return urllib.request.urlopen(req, timeout=10)
```

6. Replace `test_stream_needs_the_token_and_a_job` with:

```python
def test_stream_needs_a_job(tmp_path, serve):
    url, store, _ = make(tmp_path, serve)
    jid = flown(store).id
    assert http("GET", f"{url}/jobs/nope/stream") == (404, {"detail": "no such job"})
    assert http("POST", f"{url}/jobs/{jid}/stream")[0] == 405
```

7. Check nothing is left: `grep -n "TOKEN\|token\|Bearer" tests/test_app.py` must print nothing. (If a `http("...", token=` call or an `open_stream(..., token=...)` call survived the sed, fix it the same way.)

`tests/test_config.py`:

```bash
sed -i -E 's/\{"RUNNER_TOKEN": TOKEN\}/{}/; s/"RUNNER_TOKEN": TOKEN, //' tests/test_config.py
sed -i '/^TOKEN = "t" \* 32$/d' tests/test_config.py
sed -i '/assert a.sitl_upload_token != a.token/d' tests/test_config.py
```

then replace `test_from_env_requires_a_long_token` with (and re-align the continuation line of the `test_from_env_overrides` call under its opening `{`):

```python
def test_from_env_needs_no_token():
    s = Settings.from_env({})
    assert not hasattr(s, "token")
    Settings.from_env({"RUNNER_TOKEN": "left-over-from-an-old-env"})      # ignored, not an error
```

Also tidy the blank lines left where the `TOKEN` constant was (two blank lines after the imports).

`tests/test_sim.py:13` and `tests/test_worker.py:19`:

```bash
sed -i 's/Settings(token="t" \* 32, /Settings(/' tests/test_sim.py tests/test_worker.py
```

`tests/test_preflight.py`: delete `TOKEN = "t" * 32` (line 10); the env at line 71 becomes

```python
        self.env = {"HOME": str(self.home),
                    "DRONE_SITL_DIR": str(self.sitl), "SITE": "mapsite"}
```

and replace `test_a_short_token_fails` with:

```python
def test_there_is_no_token_check(box):
    assert "token" not in box.checks()
    code, out = box.main(RUNNER_TOKEN="left-over")          # an old .env is harmless
    assert code == 0 and "token" not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n drone python -m pytest tests/test_app.py tests/test_config.py tests/test_preflight.py tests/test_sim.py tests/test_worker.py -q 2>&1 | tail -15`
Expected: many failures/errors — `TypeError: Settings.__init__() missing 1 required positional argument: 'token'` and `401 != 200` / `"token" in checks`. (If everything passes, a sed did not apply — stop and re-check.)

- [ ] **Step 3: Remove the token from the service**

`flight_service/app.py`:

- Docstring (lines 1-2) becomes
  ```python
  """HTTP API (design 3): seven endpoints, one job each. No login: whoever can
  reach the port is an insider (the service binds 127.0.0.1)."""
  ```
- Delete `import hmac` (line 3); change `from fastapi import Depends, FastAPI, HTTPException, Request` → `from fastapi import FastAPI, HTTPException, Request`
- Delete these lines at the top of `create_app` (lines 45-51 region):
  ```python
      expected = f"Bearer {settings.token}".encode()

      def auth(request: Request):
          if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected):
              raise HTTPException(401, "missing or wrong bearer token")

  ```
- Comment above `app = FastAPI(...)`: `# The seven endpoints of design 3 only: no unauthenticated /docs, /redoc, /openapi.json.` → `# The seven endpoints of design 3 only: no /docs, /redoc, /openapi.json.`
- Remove `, dependencies=[Depends(auth)]` from the six route decorators (`/jobs` POST and GET, `/jobs/{job_id}` GET, `/kill` POST, `/files/{name}` GET, `/stream` GET). E.g. `@app.post("/jobs", status_code=202)`, `@app.get("/jobs")`.
- In `stream_job`'s docstring: `404 and 401 are answered before the stream opens` → `404 is answered before the stream opens`.

`flight_service/config.py`: delete the `token: str` line of `Settings`; in `from_env` delete

```python
        token = env.get("RUNNER_TOKEN", "")
        if len(token) < 32:
            raise SystemExit("RUNNER_TOKEN must be set and at least 32 characters")

```

and the `token=token,` argument of `cls(...)`.

`flight_service/preflight.py`: delete `check_token` (lines 67-70 and the blank lines around it); in `run_checks`:

```python
    s = Settings.from_env(env)
    checks = [check_sitl(s.drone_sitl_dir)]
```

(replacing the `Settings.from_env({**env, "RUNNER_TOKEN": "x" * 32})` line and the `checks = [check_token(env), ...]` line.)

`scripts/run-service.sh:12`:

```bash
[[ -f .env ]] || { say "no .env -- cp .env.example .env" >&2; exit 1; }
```

`scripts/mock-caller.sh`: delete the `H="Authorization: Bearer $RUNNER_TOKEN"` line and the ` -H "$H"` that follows each `curl` (lines 14, 20, 40, 45 — `grep -n 'H"' scripts/mock-caller.sh` finds them all); keep `-H 'Content-Type: application/json'` on the POST. The header comment at the top is unchanged.

`.env.example`: remove the first two lines (`# cp .env.example .env แล้วตั้ง RUNNER_TOKEN: ...` and `RUNNER_TOKEN=`) and replace with `# cp .env.example .env` followed by a note:

```
# cp .env.example .env
# service ไม่มี login: ใครเข้าถึง port ได้ก็สั่งงานได้ → คง RUNNER_HOST=127.0.0.1 ไว้ (อย่าตั้งเป็น 0.0.0.0 บนเครือข่ายที่ไม่ไว้ใจ)
```

- [ ] **Step 4: Run the changed tests and then the whole suite**

Run: `conda run -n drone python -m pytest tests/test_app.py tests/test_config.py tests/test_preflight.py tests/test_sim.py tests/test_worker.py -q 2>&1 | tail -5`
Expected: all pass.

Then: `conda run -n drone python -m pytest -q 2>&1 | tail -5`
Expected: only `tests/test_flight_client.py` tests that use `test_app.TOKEN` / `real()` fail (`ImportError: cannot import name 'TOKEN' from 'test_app'`). Everything else passes. (Task 2 fixes those; this is the expected hand-off.)

- [ ] **Step 5: Leftovers check**

Run: `grep -rn "RUNNER_TOKEN\|settings.token\|compare_digest\|Depends(auth)" flight_service scripts/run-service.sh scripts/mock-caller.sh scripts/preflight.sh .env.example`
Expected: no output.

- [ ] **Step 6: Report to the user and stop** (no commit; see Global Constraints). State: tests changed, count passing, the known `test_flight_client.py` failures waiting for Task 2.

---

### Task 2: `flight.py` stops sending a token

**Files:**
- Modify: `scripts/flight.py:13,53-54,150-158,230,492-493,524-526`
- Test: `tests/test_flight_client.py:131-134,160-176,178-183,186-200,213-247,308-318,364-368,376-380,496-503,534`

**Interfaces:**
- Produces: `flight.Api(url)` — one argument (was `Api(url, token)`). `flight.main(argv)` accepts `--url` only (no `--token`). `Api.upload(path, query)` unchanged.
- Consumes: from Task 1, `test_app.make(tmp_path, serve, **settings)` returning `(url, store, worker)` and **no** `TOKEN` constant in `tests/test_app.py`.

- [ ] **Step 1: Change the tests first**

In `tests/test_flight_client.py`:

1. Delete `TOKEN = "k" * 40` (line 18).
2. `run()` helper:

```python
def run(flight, capsys, url, *argv):
    """(exit code, stdout lines, stderr) of `flight.py --url .. <argv>`."""
    code = flight.main(["--url", url, *argv])
    out = capsys.readouterr()
    return code, out.out.splitlines(), out.err
```

3. `test_health_exit_codes`: drop `, token=""` and the comment `# no token needed` on the first assertion.
4. Replace `test_everything_else_needs_a_token` (lines ~172-175) with:

```python
def test_the_token_option_is_gone(flight, capsys):
    with pytest.raises(SystemExit) as e:
        flight.main(["--url", closed_port(), "--token", "x", "kill", "j-1"])
    assert e.value.code == 2 and "unrecognized arguments: --token" in capsys.readouterr().err
```

5. Replace `test_url_and_token_come_from_the_environment` with:

```python
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
```

6. `test_kill` (the `j-5` 401 case, lines ~190-199): keep it — it now proves a 401 from anything in front of the service is reported like any other status. Change the last assertion and rename the intent in a comment:

```python
    code, _, err = run(flight, capsys, svc.url, "kill", "j-5")      # a 401 from a proxy in front, say
    assert code == 2 and "HTTP 401: missing or wrong bearer token" in err
```

7. Same for the `(401, ...)` row of `test_a_refused_job_shows_what_the_service_said` (line ~367): expected text becomes `"HTTP 401: missing or wrong bearer token"`.
8. `real()` helper:

```python
def real(tmp_path, serve, **settings):
    from test_app import make
    return make(tmp_path / "svc", serve, **settings)
```

9. `flight.Api(url, TOKEN)` → `flight.Api(url)` (2 places, lines ~226 and ~242).
10. Line ~316 `assert headers["authorization"] == f"Bearer {TOKEN}" and headers["content-type"] == "application/json"` → `assert "authorization" not in headers and headers["content-type"] == "application/json"`
11. Line ~502 `assert headers["authorization"] == f"Bearer {TOKEN}" and body == archive.read_bytes()` → `assert "authorization" not in headers and body == archive.read_bytes()`
12. Line ~379: `flight.main(["--url", closed_port(), "--token", TOKEN, *argv])` → `flight.main(["--url", closed_port(), *argv])`
13. `spawn()` (line ~534): `env={**os.environ, "FLIGHT_URL": svc.url, "RUNNER_TOKEN": TOKEN, **env}` → `env={**os.environ, "FLIGHT_URL": svc.url, **env}`
14. Check: `grep -n "TOKEN\|token" tests/test_flight_client.py` should show only the new tests above (`test_the_token_option_is_gone`, `test_a_leftover_runner_token_variable_is_ignored`, `left-over...`, `"--token"` in the first, and the 401 message text).

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n drone python -m pytest tests/test_flight_client.py -q 2>&1 | tail -15`
Expected: failures — `unrecognized arguments` not raised / `Api() takes 2 positional arguments` / `no token: export RUNNER_TOKEN` appearing in stderr / `KeyError: 'authorization'`.

- [ ] **Step 3: Remove the token from `scripts/flight.py`**

- Module docstring lines 12-13: `Where and who: --url / FLIGHT_URL (default http://127.0.0.1:8095) and --token / RUNNER_TOKEN. Progress goes to stderr; stdout carries one JSON line for whatever called this.` →

```
Where: --url / FLIGHT_URL (default http://127.0.0.1:8095). There is no login:
the service is for insiders. Progress goes to stderr; stdout carries one JSON
line for whatever called this.
```

- `WHAT = {401: "token wrong or missing", 409: ...}` → `WHAT = {409: "pending slot full", 503: "service degraded: someone has to fix the machine"}` (keep the existing line break style).
- `class Api`:

```python
class Api:
    def __init__(self, url):
        self.url = url.rstrip("/")
```

  and in `_open` delete `if self.token:` / `req.add_header("Authorization", "Bearer " + self.token)`.
- In `upload()` delete `conn.putheader("Authorization", "Bearer " + self.token)`.
- In `parser()` delete the `--token` `add_argument` (2 lines).
- In `main()` delete

```python
        if args.cmd != "health" and not args.token:
            raise Stop("no token: export RUNNER_TOKEN=... (the service's .env) or pass --token")
```

  and call `COMMANDS[args.cmd](Api(args.url), args)`.
- `grep -n "token\|Token\|TOKEN\|Authorization" scripts/flight.py` must print nothing.

- [ ] **Step 4: Run the client tests and the whole suite**

Run: `conda run -n drone python -m pytest tests/test_flight_client.py -q 2>&1 | tail -5` → all pass.
Run: `conda run -n drone python -m pytest -q 2>&1 | tail -5` → everything passes. The count differs from the 253 baseline only by the tests this plan replaced or added; report the exact number.

- [ ] **Step 5: Report to the user and stop** (no commit).

---

### Task 3: Docs, decision log, and one real run

**Files:**
- Modify: `README.md:16,24,49,66,115,180,192`; `docs/api.md:16,25,29,98`; `docs/design.md:65,75,127,132,226,364,372`; `docs/SUMMARY.md:10,41,48`; `docs/followups.md:17,20,36`; `docs/progress.md:37` and a new row in the decision log (`## บันทึกการตัดสินใจ` table, last row)
- Modify: `wishlist.md` — mark item 1 done (append ` — ✅ 2026-10-09`)

**Interfaces:** none (prose only).

- [ ] **Step 1: README.md** (Thai prose, edit each spot)

  - Setup block (line ~16): delete the `sed -i "s/^RUNNER_TOKEN=...` line; keep `cp .env.example .env` and `chmod 600 .env`.
  - Table row (line ~24): delete the `RUNNER_TOKEN` row. Under the table add one sentence: `service ไม่มี login ใครเข้าถึง port ได้ก็สั่งงานได้ จึงคง RUNNER_HOST=127.0.0.1 (default) ไว้ — ถ้าตั้งเป็น 0.0.0.0 ทุกคนในเครือข่ายสั่งบินและอัปโหลดไฟล์ได้`
  - Line ~49: `` `cp .env.example .env` → ตั้ง `RUNNER_TOKEN` (และ path ข้างบนถ้าไม่ตรง default) `` → `` `cp .env.example .env` (แก้ path ข้างบนถ้าไม่ตรง default) ``
  - Line ~66: `export R=http://127.0.0.1:8095 H="Authorization: Bearer $RUNNER_TOKEN"` → `export R=http://127.0.0.1:8095`; then remove every ` -H "$H"` in the curl examples below it (`grep -n '"\$H"' README.md`).
  - Line ~115: `export FLIGHT_URL=http://127.0.0.1:8095 RUNNER_TOKEN=<token ใน .env ของ service>` → `export FLIGHT_URL=http://127.0.0.1:8095     # ไม่ตั้งก็ได้ถ้าเรียกจากเครื่องเดียวกับ service (default ตัวนี้)`
  - Line ~180: `- token ทุก endpoint ยกเว้น `/healthz` · allowlist ...` → `- ไม่มี login (ผู้เรียกเป็นคนใน; service bind 127.0.0.1) · allowlist ...`
  - Line ~192: in the troubleshooting row `(ไม่มี .env / token สั้นเกิน / port ถูกใช้)` → `(ไม่มี .env / port ถูกใช้)`

- [ ] **Step 2: the other docs**

  - `docs/api.md:16` `ตรวจ token → ช่องรอว่างไหม ...` → `ช่องรอว่างไหม → ...`; `:25` replace the line with `ไม่มี login: ไม่ต้องส่ง header ใด ๆ (service bind 127.0.0.1 — ผู้เรียกเป็นคนใน)`; `:29` drop `(ไม่ต้องใช้ token)`; `:98` delete the `401` row.
  - `docs/design.md:65` same sentence as api.md:25; `:75` drop `ไม่ต้องใช้ token` and the `(กันข้อมูลรั่วโดยไม่มี token)` clause; `:127` remove `` `401` token · ``; `:132` `token เดียวกับ endpoint อื่น · `404` / `401` ตอบก่อนเปิดสาย` → `` `404` ตอบก่อนเปิดสาย ``; `:226` replace the "ยืนยันตัวตน" table row with `| ยืนยันตัวตน | ไม่มี (ตัดสินใจ 2026-10-09: ผู้เรียก flight.py เป็นคนในทั้งหมด) · ด่านเดียวคือ bind `127.0.0.1` โดย default — ตั้ง `RUNNER_HOST` เป็นอย่างอื่นแล้วทุกคนที่ถึง port ได้สั่งงานได้ |`; `:364` `เพราะผู้ส่งยืนยันตัวด้วย token แล้ว` → `เพราะผู้ส่งเป็นคนใน`; `:372` `จึงใช้ token, timeout และ limit ของ container ชุดเดียวกัน` → `จึงใช้ timeout และ limit ของ container ชุดเดียวกัน`. Leave `:374` (the drone-sitl upload token) alone.
  - `docs/SUMMARY.md:10` `(ระบบของพี่ต้น หรือใครก็ตามที่มี token)` → `(ระบบของพี่ต้น หรือคนในที่เรียก flight.py)`; `:41` same export change as README:115; `:48` `(ทุกตัวยกเว้น `/healthz` ต้องมี `Authorization: Bearer <token>`)` → `(ไม่มี login)`.
  - `docs/followups.md:17` `(token holders only)` → `(anyone who can reach the port)`; `:20` **delete** the line `RUNNER_TOKEN inherited by drone-sitl processes ...` (the variable no longer exists); `:36` same export change.
  - `docs/progress.md:37`: `HTTP API 7 endpoint + token` → `HTTP API 7 endpoint`; add a final row to the decision log table:
    `| 2026-10-09 | RUNNER_TOKEN | ถอดทิ้งทั้งระบบ (wishlist ข้อ 1): ผู้เรียก flight.py เป็นคนใน · service ไม่มี login ด่านเดียวคือ bind 127.0.0.1 · **ไม่**ทำ guard `RUNNER_ALLOW_REMOTE` (ผู้ใช้ตัดออก) · `sitl_upload_token` (service↔drone-sitl) คงไว้ · แผน `docs/superpowers/plans/2026-10-09-remove-runner-token.md` |`
  - `wishlist.md` item 1: append ` — ✅ 2026-10-09`.

- [ ] **Step 3: Leftovers check**

Run: `grep -rn "RUNNER_TOKEN\|Bearer" README.md docs/api.md docs/design.md docs/SUMMARY.md docs/followups.md docs/progress.md flight_service scripts tests .env.example`
Expected: no `RUNNER_TOKEN` anywhere except the deliberate `left-over` tests in `tests/` (`test_config.py`, `test_preflight.py`, `test_flight_client.py`); `Bearer` only in the 401 test text and `"Bearer old-token"` in `test_app.py`; `docs/progress.md` may mention `RUNNER_TOKEN` in the new decision row.

- [ ] **Step 4: Real run (no mocks)**

  1. `conda run -n drone python -m pytest -q 2>&1 | tail -3` — all pass; report the number.
  2. With the user's existing `.env` untouched (it still has the old `RUNNER_TOKEN=` line, which must now be harmless): `./scripts/preflight.sh | head -20` — no `token` line, no FAIL caused by it.
  3. `./scripts/run-service.sh` — prints `up (pid ...)`.
  4. In a shell with **no** token and **no** `FLIGHT_URL`:
     ```bash
     env -u RUNNER_TOKEN -u FLIGHT_URL python3 scripts/flight.py health          # exit 0, {"ok": true, "ready": true, ...}
     curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8095/jobs          # 200 (was 401)
     curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8095/jobs/nope     # 404
     python3 scripts/flight.py --token x health                                    # exit 2: unrecognized arguments
     ```
  5. `./scripts/stop-service.sh`.
  6. A full flight (`flight.py run perkiepai/truck-detector:<tag>`) uses the GPU/Isaac Sim for several minutes. **Ask the user** whether to do one; do not start it unasked.

- [ ] **Step 5: Final report and stop.** Show `git status --short` and `git diff --stat`, list which files were already modified before this work (`config.py`, `test_config.py`, `README.md`, `docs/design.md`, `docs/progress.md`) so the user can decide how to commit, and say wishlist item 2 is next but not started.

---

## Self-Review (done while writing)

- **Spec coverage:** remove token from service (Task 1), from client (Task 2), docs + decision (Task 3), `RUNNER_ALLOW_REMOTE` excluded (Global Constraints), new `flight.py` command = no export needed (README change in Task 3 step 1). The `.env` is left alone as promised.
- **Placeholders:** none. Line numbers are from the tree at 2026-10-09 and approximate (`~`) where a preceding edit shifts them; every spot is also identified by its text.
- **Type consistency:** `Settings` without `token` is used in Task 1 tests (`test_app.make`, `test_sim`, `test_worker`) and Task 2's `real()` imports only `make`. `Api(url)` is used in both Task 2 test edits and the implementation. `conftest.http` signature change is applied to every caller by the `sed` in Task 1 step 1 and verified by the grep.
- **Review Focus** items each map to a named test or manual check above.
