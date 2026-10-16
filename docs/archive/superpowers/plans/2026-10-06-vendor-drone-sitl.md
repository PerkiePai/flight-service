> **ประวัติ ไม่ใช่สถานะปัจจุบัน:** เอกสารนี้เก็บไว้เป็นหลักฐานของงานที่ทำเสร็จแล้ว ไม่ได้อัปเดตตามโค้ด (เช่นยังพูดถึง `RUNNER_TOKEN` ที่ถอดแล้ว) สถานะจริงดู [../design.md](../../../design.md) และ [../progress.md](../../../progress.md)

# vendor drone-sitl: ย้าย flight-service ไปเครื่องอื่นได้ Implementation Plan (2026-10-06)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **ประตูอนุมัติ (ตามวิธีทำงานของโปรเจกต์นี้):** หยุดรออนุมัติหลัง Task 5 (โค้ด + เทสต์), หลัง Task 6 (บินจริง) และหลัง Task 7 (README) · ห้ามเริ่มขั้นถัดไปเพราะ "น่าจะโอเค"

**Goal:** flight-service รันบนเครื่องอื่นที่ติดตั้ง Isaac Sim / Pegasus / PX4 เองได้ โดยไม่ต้องมี checkout `~/pai/drone-sitl` ข้างๆ และบอกได้ว่าเครื่องใหม่ยังขาดอะไร

**Architecture:** คัดลอกเฉพาะไฟล์ drone-sitl ที่ service รันจริงจาก commit เดียว (ด้วย `git archive` ตามรายการใน `vendor/drone-sitl.manifest`) ลง `vendor/drone-sitl/` โดยรักษาโครงสร้างเดิม เพราะสคริปต์ของมันหากันด้วย path เทียบกับ root · การแก้ทุกอย่างในสำเนาทำเป็นไฟล์ patch ที่สคริปต์ซิงก์ apply ทุกครั้ง · แผนที่ `nt-testgs` กับ layer ที่มันอ้างถึงคัดลอกแบนไว้ใน `vendor/maps/nt-testgs/` (ไฟล์ใหญ่ 2 ตัวไม่เข้า git และตรวจด้วย `SHA256SUMS`) · `DRONE_SITL_DIR` default ชี้สำเนานี้ · `scripts/preflight.sh` ตรวจของที่ repo พกไปไม่ได้

**Tech Stack:** bash (`git archive`, `rsync`, `patch`, `sha256sum`), Python 3.11 (conda env `drone`), pytest 9 · ไม่ติดตั้ง package เพิ่ม

**Spec:** ไม่มีไฟล์ spec แยก: ผู้ใช้เลือกทาง A ("สแนปช็อตใน vendor/ + ตัวตรวจเครื่อง") เมื่อ 2026-10-06 เพื่อ "เอา flight-service ไปรันบนเครื่องอื่น" · ข้อเท็จจริงที่แผนนี้อิงอยู่ในหัวข้อ "สิ่งที่ตรวจแล้ว" ด้านล่าง · บริบทเดิม: `docs/design.md`, `docs/progress.md`, `docs/drone-sitl-changes.md`

## สิ่งที่ตรวจแล้ว (2026-10-06 อ่านอย่างเดียว)

- ต้นทาง: `~/pai/drone-sitl` branch `feat/website-usd-map-testgs` HEAD `2945783` (working tree สะอาด) ซึ่งรวมการแก้ 3 ครั้งที่อนุมัติแล้ว (`ed5f998`, `bda585c`, `205eaff`)
- import ภายในของสคริปต์ที่รันจริง (หาด้วย `modulefinder`):
  - `joystick-server.py` → `streaming/{agent_control,det_recorder,detections,docker_build,offboard,waypoints}.py` + `competition/{__init__,agent,commands,frames}.py` · เสิร์ฟ `web/`
  - `agent_runner.py` (อยู่ใน image `competition-base`) → `competition/*.py` ทั้ง 6 ไฟล์
  - `sim/bootstrap.py` → `sim/sites.py`, `sim/stage_builder.py` · `launch-sitl.sh` exec `drone_setup_px4_cesium.py`
  - `examples/competition-submission/fly_headless.py` → `sim/sites.py` (flight-service ใช้ `load_truth`/`analyze`)
  - `docker/competition-base/Dockerfile` COPY `competition/` + `agent_runner.py`
- **แผนที่ไม่ได้มีแค่ 252 KB:** `drone_map.usda` อ้างถึง `../nt_testgs.usdc` (228 MB) และ `../../Downloads/Truck2.usd` (64 MB, 3 ที่) · ตรวจด้วย `pxr.UsdUtils.ComputeAllDependencies` ได้ 4 layer พอดี ไม่มี asset อื่น ไม่มีที่หาไม่เจอ · รวม ~292 MB
- `load_truth` อ่าน `drone_map_vehicles.json` + `drone_map_report.json["terrain"]` ข้างไฟล์ stage (path เต็มใน report ไม่ได้ใช้)
- **site `nt-testgs` ไม่ใช้ Cesium** (`stage_usd` ตั้งไว้ → `uses_cesium=False`): เครื่องใหม่ไม่ต้องมี Cesium build หรือ token สำหรับ site นี้
- ไฟล์ในรายการที่มี `/home/...` ตายตัว: `sim/sites.py` เท่านั้น (`stage_usd`) · ที่อื่นใช้ `$HOME` หรือ env ได้อยู่แล้ว: `ISAAC_DIR`, `PEGASUS_EXTS`, `CESIUM_EXTS`, `CONDA_ENV`, `DRONE_SETUP_REC_DIR` (แทน `~/flight_recordings`)
- PX4: Pegasus อ่านจาก `~/PegasusSimulator/extensions/pegasus.simulator/config/configs.yaml` → `px4_dir: /home/innovation/PX4-Autopilot` → `build/px4_sitl_default/bin/px4`
- env `drone`: Python 3.11.15 · fastapi 0.141.1 · uvicorn 0.52.0 · pydantic 2.13.4 · websockets 17.0 · pymavlink 2.4.49 · numpy 2.4.4 · pillow 12.2.0 · opencv-python 4.13.0.92 · pytest 9.1.1 · `ffmpeg` 6.1.1 จาก apt
- เทสต์ flight-service ตอนนี้: **153 passed**

## Global Constraints

- branch ใหม่ `feat/vendor-drone-sitl` แตกจาก `feat/ver2` · ไม่ merge/push (เจ้าของจัดการเอง)
- ต้นทางที่คัดลอก: `~/pai/drone-sitl` commit `2945783` เท่านั้น ผ่าน `scripts/vendor-drone-sitl.sh` (ห้าม `cp` เอง) · **ห้ามแก้ `~/pai/drone-sitl`** ในแผนนี้
- ห้ามแก้ไฟล์ใน `vendor/drone-sitl/` ตรงๆ: การแก้ทุกอย่างเป็น `vendor/patches/drone-sitl/NNNN-*.patch`
- แผนที่: `vendor/maps/nt-testgs/` · **`nt_testgs.usdc` (228 MB) และ `Truck2.usd` (64 MB) ห้ามเข้า git** · ทุกไฟล์มีใน `SHA256SUMS`
- `DRONE_SITL_DIR` default = `vendor/drone-sitl` (เทียบกับ root ของ flight-service) · ตั้งเป็น path เต็มของ checkout อื่นยังทำงานเหมือนเดิม
- กฎเดิมยังอยู่: ห้าม `pkill -f` · ห้าม `docker image prune` · bind `127.0.0.1:8095` · รันด้วย conda env `drone`
- กฎ "ห้าม copy โค้ด drone-sitl" (plan v3) **ถูกแทนด้วยการตัดสินใจ 2026-10-06 ทาง A** · บันทึกใน `docs/progress.md`
- commit ใช้ author ที่ตั้งใน repo แล้ว · ท้าย message ทุก commit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017NmdMU3j35NBqncBRrRsWk
  ```
- รันเทสต์ด้วย `conda run -n drone python -m pytest -q` · ทุกขั้นต้องผ่านทั้งชุด

## Review Focus

1. **`DRONE_SITL_DIR` แบบ relative ใน `.env`** (เช่น `vendor/drone-sitl`) ต้องเทียบกับ root ของ flight-service ไม่ใช่ CWD ตอนเริ่ม service: `sim.py` ใช้ path นี้ทั้ง `cwd`, ไฟล์ console และ `pgrep -f <dir>/sim/bootstrap.py` ถ้าเพี้ยน → นับว่า Isaac ตายทั้งที่ยังบูต · ทดสอบใน Task 4
2. **clone ใหม่ที่ยังไม่มีไฟล์แผนที่ใหญ่:** ต้องได้ข้อความจาก preflight ว่าขาดไฟล์ไหนและเอามาจากไหน ไม่ใช่ Isaac ค้างตอนบูต และเทสต์ของ repo ต้องไม่ล้มเพราะไฟล์ที่ตั้งใจไม่เข้า git · ทดสอบใน Task 3 (`test_small_map_files_match_and_big_ones_are_ignored`) และ Task 5 (`test_map_reports_missing_and_changed_files`)
3. **bit executable หาย** ระหว่าง archive/rsync/clone → `run-website.sh: Permission denied` ตอนงานแรก · ทดสอบใน Task 1 และ Task 3
4. **ซิงก์ซ้ำแล้วลบของที่เกิดตอนรัน** (`logs/launch-sitl.console` ที่ `sim.py` อ่าน, `sim/secrets.env`, `recordings/`) หรือ patch ที่ใช้ไม่ได้แล้วทำให้สำเนาเหลือครึ่งๆ · ทดสอบใน Task 1
5. **`SITE` ที่ไม่รู้จัก / site ที่ใช้ Cesium บนเครื่องใหม่:** preflight ต้องรายงานเป็นข้อที่ไม่ผ่านพร้อมวิธีแก้ ไม่ใช่ traceback · ทดสอบใน Task 5

## ไฟล์

| ไฟล์ | หน้าที่ | Task |
|---|---|---|
| `scripts/vendor-drone-sitl.sh` | คัดลอกตาม manifest จาก commit + apply patch + เขียน `VENDORED` + rsync ทับ (เก็บของตอนรัน) | 1 |
| `tests/test_vendor_script.py` | เทสต์สคริปต์ด้านบนกับ git repo ปลอม | 1 |
| `scripts/vendor-map.sh` | คัดลอกแผนที่ + layer ที่อ้างถึงแบบแบน เขียน ref เป็น `./<ชื่อ>` + `SHA256SUMS` | 2 |
| `tests/test_vendor_map.py` | เทสต์สคริปต์แผนที่กับโฟลเดอร์ปลอม | 2 |
| `vendor/drone-sitl.manifest` | รายการ path ที่คัดลอก | 3 |
| `vendor/patches/drone-sitl/0001-sites-nt-testgs-map-in-repo.patch` | `stage_usd` → `../maps/nt-testgs/drone_map.usda` | 3 |
| `vendor/drone-sitl/**` · `vendor/maps/nt-testgs/*` | ผลจากสคริปต์ (สร้างโดยสคริปต์เท่านั้น) | 3 |
| `vendor/README.md` | อะไรอยู่ใน vendor, กฎ, วิธีซิงก์, วิธีย้ายแผนที่ | 3 |
| `tests/test_vendored.py` | สำเนาครบ, import หาเจอในสำเนา, แผนที่อยู่ในโฟลเดอร์, ไม่มี `/home/...` | 3 |
| `tests/test_score.py` | ย้ายเทสต์ `load_truth` ไปใช้สำเนา (ไม่ skip อีก) | 3 |
| `.gitignore` | ของตอนรันใน vendor + ไฟล์แผนที่ใหญ่ | 3 |
| `flight_service/config.py` · `tests/test_config.py` · `.env.example` | default `vendor/drone-sitl` + relative เทียบ root | 4 |
| `flight_service/preflight.py` · `scripts/preflight.sh` · `tests/test_preflight.py` | ตรวจเครื่อง | 5 |
| `requirements-drone.txt` | package ของ env `drone` ตามเวอร์ชันที่ใช้จริง | 5 |
| `docs/verification.md` · `docs/evidence/verification-vendor-*.log` | ผลบินจริงบนสำเนา | 6 |
| `README.md` · `docs/progress.md` · `docs/drone-sitl-changes.md` | เอกสาร | 3, 6, 7 |

---

### Task 0: branch

- [ ] **Step 1: แตก branch และเช็กว่าเริ่มจากของสะอาด**

```bash
cd ~/pai/flight-service
git status --short          # ต้องว่าง
git switch -c feat/vendor-drone-sitl feat/ver2
git -C ~/pai/drone-sitl rev-parse HEAD   # ต้องขึ้นต้นด้วย 2945783 (ถ้าไม่ใช่ หยุดถามผู้ใช้)
conda run -n drone python -m pytest -q 2>&1 | tail -1   # 153 passed
```

---

### Task 1: `scripts/vendor-drone-sitl.sh`

**Files:**
- Create: `scripts/vendor-drone-sitl.sh`
- Test: `tests/test_vendor_script.py`

**Interfaces:**
- Consumes: ไม่มี
- Produces: `scripts/vendor-drone-sitl.sh <drone-sitl checkout> [commit]` · env `VENDOR_DIR` (default `vendor/drone-sitl`), `VENDOR_MANIFEST` (default `vendor/drone-sitl.manifest`), `VENDOR_PATCHES` (default `vendor/patches/drone-sitl`) · เขียน `<VENDOR_DIR>/VENDORED` เป็นบรรทัด `key=value`: `source_commit` (40 hex), `source_subject`, `vendored_at`, `patches` (ชื่อไฟล์คั่นช่องว่าง) · exit ≠ 0 แล้วไม่แตะ `VENDOR_DIR` เมื่อ commit ไม่มี / path ใน manifest ไม่มีใน commit / patch ใช้ไม่ได้

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

`tests/test_vendor_script.py`:

```python
"""scripts/vendor-drone-sitl.sh against a throwaway drone-sitl git repo."""
import difflib
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vendor-drone-sitl.sh"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
SITES_V1 = 'STAGE = "/home/someone/map.usda"\n'


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


def commit(repo, files, msg):
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if name.endswith(".sh"):
            p.chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD")


def patch(path, old, new):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"a/{path}", f"b/{path}"))


def files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def record(dest):
    return dict(line.split("=", 1) for line in (dest / "VENDORED").read_text().splitlines())


@pytest.fixture
def src(tmp_path):
    repo = tmp_path / "drone-sitl"
    repo.mkdir()
    git(repo, "init", "-q")
    commit(repo, {"sim/run.sh": "#!/bin/sh\necho run\n", "sim/sites.py": SITES_V1,
                  "web/index.html": "<html></html>\n", "logs/old.console": "not wanted\n",
                  "examples/huge.bin": "not wanted\n"}, "one")
    return repo


@pytest.fixture
def vendor(tmp_path):
    """vendor(src, *args, manifest=..., patches={name: text}) -> (CompletedProcess, dest)"""
    dest = tmp_path / "vendor" / "drone-sitl"
    pdir = tmp_path / "patches"
    pdir.mkdir()

    def run(src, *args, manifest="# what we run\n\nsim/run.sh\nsim/sites.py\nweb\n", patches=None):
        (tmp_path / "manifest").write_text(manifest)
        for f in pdir.iterdir():
            f.unlink()
        for name, text in (patches or {}).items():
            (pdir / name).write_text(text)
        env = {**os.environ, **GIT_ENV, "VENDOR_DIR": str(dest),
               "VENDOR_MANIFEST": str(tmp_path / "manifest"), "VENDOR_PATCHES": str(pdir)}
        r = subprocess.run(["bash", str(SCRIPT), str(src), *args], env=env,
                           capture_output=True, text=True)
        return r, dest
    return run


def test_copies_only_manifest_paths_and_records_the_commit(src, vendor):
    r, dest = vendor(src)
    assert r.returncode == 0, r.stderr
    assert files(dest) == ["VENDORED", "sim/run.sh", "sim/sites.py", "web/index.html"]
    assert os.access(dest / "sim" / "run.sh", os.X_OK)
    assert record(dest)["source_commit"] == git(src, "rev-parse", "HEAD")
    assert record(dest)["patches"] == ""


def test_takes_the_commit_not_the_working_tree(src, vendor):
    old = git(src, "rev-parse", "HEAD")
    commit(src, {"sim/sites.py": 'STAGE = "v2"\n'}, "two")
    (src / "sim" / "sites.py").write_text("uncommitted\n")
    r, dest = vendor(src, old)
    assert r.returncode == 0, r.stderr
    assert (dest / "sim" / "sites.py").read_text() == SITES_V1
    assert record(dest)["source_commit"] == old


def test_an_unknown_commit_fails_before_copying(src, vendor):
    r, dest = vendor(src, "no-such-rev")
    assert r.returncode != 0 and "no-such-rev" in r.stderr and not dest.exists()


def test_applies_patches_in_name_order(src, vendor):
    mid = 'STAGE = "../maps/m/drone_map.usda"\n'
    r, dest = vendor(src, patches={
        "0002-more.patch": patch("sim/sites.py", mid, mid + "EXTRA = 1\n"),
        "0001-map.patch": patch("sim/sites.py", SITES_V1, mid)})
    assert r.returncode == 0, r.stderr
    assert (dest / "sim" / "sites.py").read_text() == mid + "EXTRA = 1\n"
    assert record(dest)["patches"].split() == ["0001-map.patch", "0002-more.patch"]
    assert not list(dest.rglob("*.orig")) and not list(dest.rglob("*.rej"))


def test_a_patch_that_no_longer_applies_leaves_the_copy_alone(src, vendor):
    _, dest = vendor(src)
    before = {f: (dest / f).read_text() for f in files(dest)}
    r, _ = vendor(src, patches={"0001-x.patch": patch("sim/sites.py", "something else\n", "y\n")})
    assert r.returncode != 0 and "0001-x.patch" in r.stderr
    assert {f: (dest / f).read_text() for f in files(dest)} == before


def test_a_manifest_path_missing_from_the_commit_fails_before_copying(src, vendor):
    r, dest = vendor(src, manifest="sim/run.sh\nsim/gone.py\n")
    assert r.returncode != 0 and not dest.exists()


def test_resync_keeps_runtime_output_and_drops_what_left_the_manifest(src, vendor):
    _, dest = vendor(src)
    for keep in ("logs/launch-sitl.console", "recordings/a.mp4", "sim/secrets.env"):
        (dest / keep).parent.mkdir(parents=True, exist_ok=True)
        (dest / keep).write_text("keep\n")
    r, dest = vendor(src, manifest="sim/run.sh\nsim/sites.py\n")
    assert r.returncode == 0, r.stderr
    assert files(dest) == ["VENDORED", "logs/launch-sitl.console", "recordings/a.mp4",
                           "sim/run.sh", "sim/secrets.env", "sim/sites.py"]
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `conda run -n drone python -m pytest tests/test_vendor_script.py -q`
Expected: FAIL ทุกข้อ (`bash: .../vendor-drone-sitl.sh: No such file or directory` → returncode 127)

- [ ] **Step 3: เขียนสคริปต์**

`scripts/vendor-drone-sitl.sh` (แล้ว `chmod +x`):

```bash
#!/usr/bin/env bash
# vendor-drone-sitl.sh -- copy the drone-sitl files flight-service runs on
# into vendor/drone-sitl/, from one commit of a drone-sitl checkout.
#
#   ./scripts/vendor-drone-sitl.sh <drone-sitl checkout> [commit]    (default HEAD)
#
# Takes only the paths in vendor/drone-sitl.manifest, from the commit (never
# the working tree), applies vendor/patches/drone-sitl/*.patch in name order,
# writes VENDORED (source commit + patches), then syncs the result over the
# copy. Runtime output inside the copy -- logs/, recordings/, .cache/,
# sim/secrets.env -- is kept. Nothing changes if any step fails.
# VENDOR_DIR, VENDOR_MANIFEST, VENDOR_PATCHES move the inputs (tests).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USAGE="usage: vendor-drone-sitl.sh <drone-sitl checkout> [commit]"
SRC="${1:?$USAGE}"
REV="${2:-HEAD}"
DEST="${VENDOR_DIR:-$DIR/vendor/drone-sitl}"
MANIFEST="${VENDOR_MANIFEST:-$DIR/vendor/drone-sitl.manifest}"
PATCHES="${VENDOR_PATCHES:-$DIR/vendor/patches/drone-sitl}"
say() { echo "vendor-drone-sitl: $*"; }
die() { echo "vendor-drone-sitl: $*" >&2; exit 1; }

COMMIT="$(git -C "$SRC" rev-parse --verify --quiet "$REV^{commit}")" \
    || die "no commit '$REV' in $SRC"
mapfile -t PATHS < <(grep -vE '^[[:space:]]*(#|$)' "$MANIFEST")
(( ${#PATHS[@]} )) || die "nothing listed in $MANIFEST"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git -C "$SRC" archive "$COMMIT" -- "${PATHS[@]}" | tar -x -C "$TMP" \
    || die "git archive failed -- is every path in $MANIFEST in ${COMMIT:0:7}?"

# patch(1), not git apply: $TMP is not a repo, and git apply would look for one.
APPLIED=()
shopt -s nullglob
for p in "$PATCHES"/*.patch; do
    patch -p1 --batch --forward --fuzz=0 --no-backup-if-mismatch -s -d "$TMP" -i "$p" \
        || die "$(basename "$p") does not apply to ${COMMIT:0:7} -- update the patch first"
    APPLIED+=("$(basename "$p")")
done

{
    echo "source_commit=$COMMIT"
    echo "source_subject=$(git -C "$SRC" log -1 --format=%s "$COMMIT")"
    echo "vendored_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "patches=${APPLIED[*]}"
} > "$TMP/VENDORED"

mkdir -p "$DEST"
rsync -a --delete --exclude=/logs/ --exclude=/recordings/ --exclude=/.cache/ \
    --exclude=/sim/secrets.env --exclude=__pycache__/ --exclude='/NvStreamer-*.etli' \
    "$TMP/" "$DEST/"
say "$DEST <- ${COMMIT:0:7} (${#PATHS[@]} paths, ${#APPLIED[@]} patches)"
```

- [ ] **Step 4: รันให้ผ่าน**

Run: `chmod +x scripts/vendor-drone-sitl.sh && conda run -n drone python -m pytest tests/test_vendor_script.py -q`
Expected: `7 passed`

- [ ] **Step 5: ทั้งชุด + commit**

```bash
conda run -n drone python -m pytest -q 2>&1 | tail -1     # 160 passed
git add scripts/vendor-drone-sitl.sh tests/test_vendor_script.py
git commit -m "feat: vendor-drone-sitl.sh copies drone-sitl's files from one commit

Only the manifest's paths, from the commit (not the working tree), with
our patches on top; a failed step leaves the copy as it was and a resync
keeps logs/, recordings/ and sim/secrets.env.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017NmdMU3j35NBqncBRrRsWk"
```

---

### Task 2: `scripts/vendor-map.sh`

**Files:**
- Create: `scripts/vendor-map.sh`
- Test: `tests/test_vendor_map.py`

**Interfaces:**
- Consumes: ไม่มี
- Produces: `scripts/vendor-map.sh <site> <map_setup_output_dir>` · env `VENDOR_MAPS_DIR` (default `vendor/maps`) · ผล: `<VENDOR_MAPS_DIR>/<site>/` มีทุกไฟล์ในโฟลเดอร์ต้นทาง + ทุกไฟล์ที่ `drone_map.usda` อ้างถึง (แบน) · ทุก ref ใน `drone_map.usda` เป็น `@./<ชื่อไฟล์>@` · `SHA256SUMS` รูปแบบ `sha256sum` (`<hex>  <ชื่อ>`) ครบทุกไฟล์ยกเว้นตัวเอง · ล้ม → exit ≠ 0 และโฟลเดอร์ปลายทางเดิมไม่เปลี่ยน

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

`tests/test_vendor_map.py`:

```python
"""scripts/vendor-map.sh against a fake map_setup_tool output."""
import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vendor-map.sh"
STAGE = """#usda 1.0
(
    customLayerData = { string input = "/home/someone/Tiger/base.usdc" }
    subLayers = [
        @./drone_map_physics.usdc@,
        @../base.usdc@
    ]
)
def "A" ( prepend payload = @../../Downloads/Truck.usd@ ) {}
def "B" ( prepend payload = @../../Downloads/Truck.usd@ ) {}
"""


@pytest.fixture
def src(tmp_path):
    out = tmp_path / "Tiger" / "out"
    out.mkdir(parents=True)
    (out / "drone_map.usda").write_text(STAGE)
    (out / "drone_map_physics.usdc").write_bytes(b"physics")
    (out / "drone_map_vehicles.json").write_text('{"trucks": []}')
    (tmp_path / "Tiger" / "base.usdc").write_bytes(b"base")
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "Truck.usd").write_bytes(b"truck")
    return out


def vendor_map(tmp_path, src, site="m"):
    env = {**os.environ, "VENDOR_MAPS_DIR": str(tmp_path / "maps")}
    r = subprocess.run(["bash", str(SCRIPT), site, str(src)], env=env,
                       capture_output=True, text=True)
    return r, tmp_path / "maps" / site


def test_copies_the_folder_and_every_referenced_layer_flat(tmp_path, src):
    r, dest = vendor_map(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in dest.iterdir()) == [
        "SHA256SUMS", "Truck.usd", "base.usdc", "drone_map.usda",
        "drone_map_physics.usdc", "drone_map_vehicles.json"]
    assert (dest / "Truck.usd").read_bytes() == b"truck"


def test_references_point_inside_the_folder(tmp_path, src):
    _, dest = vendor_map(tmp_path, src)
    refs = re.findall(r"@([^@]+)@", (dest / "drone_map.usda").read_text())
    assert sorted(set(refs)) == ["./Truck.usd", "./base.usdc", "./drone_map_physics.usdc"]
    assert all((dest / r).is_file() for r in refs)


def test_sha256sums_covers_every_file_and_verifies(tmp_path, src):
    _, dest = vendor_map(tmp_path, src)
    names = [line.split(None, 1)[1] for line in (dest / "SHA256SUMS").read_text().splitlines()]
    assert sorted(names) == sorted(p.name for p in dest.iterdir() if p.name != "SHA256SUMS")
    assert subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=dest).returncode == 0


def test_a_missing_layer_fails_and_keeps_the_old_copy(tmp_path, src):
    _, dest = vendor_map(tmp_path, src)
    (tmp_path / "Tiger" / "base.usdc").unlink()
    r, dest = vendor_map(tmp_path, src)
    assert r.returncode != 0 and "base.usdc" in r.stderr
    assert (dest / "base.usdc").read_bytes() == b"base"
    assert [p.name for p in dest.parent.iterdir()] == ["m"]          # no temp dir left


def test_two_different_layers_with_one_name_fail(tmp_path, src):
    (tmp_path / "Other").mkdir()
    (tmp_path / "Other" / "base.usdc").write_bytes(b"different")
    (src / "drone_map.usda").write_text(STAGE.replace("@./drone_map_physics.usdc@",
                                                      "@../../Other/base.usdc@"))
    r, dest = vendor_map(tmp_path, src)
    assert r.returncode != 0 and "base.usdc" in r.stderr and not dest.exists()


def test_the_copy_is_readable_by_others(tmp_path, src):
    _, dest = vendor_map(tmp_path, src)
    assert dest.stat().st_mode & 0o755 == 0o755
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `conda run -n drone python -m pytest tests/test_vendor_map.py -q`
Expected: FAIL ทุกข้อ (ไม่มีสคริปต์)

- [ ] **Step 3: เขียนสคริปต์**

`scripts/vendor-map.sh` (แล้ว `chmod +x`):

```bash
#!/usr/bin/env bash
# vendor-map.sh -- copy a map_setup_tool stage into vendor/maps/<site>/ so it
# needs nothing outside that folder: every file in the output dir, plus every
# file drone_map.usda points at (@...@), flat, with those references rewritten
# to ./<name>. Writes SHA256SUMS (scripts/preflight.sh checks it).
#
#   ./scripts/vendor-map.sh <site> <map_setup_output_dir>
#   ./scripts/vendor-map.sh nt-testgs ~/Tiger/map_setup_output_nt_testgs
#
# Only drone_map.usda's own references are followed; check the copy has no
# deeper ones with Isaac's pxr (vendor/README.md, "map").
# VENDOR_MAPS_DIR moves the target (tests).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USAGE="usage: vendor-map.sh <site> <map_setup_output_dir>"
SITE="${1:?$USAGE}"
SRC="$(realpath -e "${2:?$USAGE}")"
MAPS="${VENDOR_MAPS_DIR:-$DIR/vendor/maps}"
DEST="$MAPS/$SITE"
STAGE="drone_map.usda"
say() { echo "vendor-map: $*"; }
die() { echo "vendor-map: $*" >&2; exit 1; }

[[ -f "$SRC/$STAGE" ]] || die "no $STAGE in $SRC"
mkdir -p "$MAPS"
TMP="$(mktemp -d "$MAPS/.$SITE.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
find "$SRC" -maxdepth 1 -type f -exec cp -p {} "$TMP/" \;

mapfile -t REFS < <(grep -oE '@[^@]+@' "$SRC/$STAGE" | tr -d @ | sort -u)
for ref in "${REFS[@]}"; do
    [[ "$ref" == /* ]] && from="$ref" || from="$SRC/$ref"
    from="$(realpath -e "$from" 2>/dev/null)" || die "$STAGE points at $ref, which does not exist"
    [[ "$(dirname "$from")" == "$SRC" ]] && continue            # copied with the folder
    name="$(basename "$from")"
    if [[ -e "$TMP/$name" ]]; then
        cmp -s "$from" "$TMP/$name" && continue                 # same file, another path
        die "two different layers named $name -- cannot put them in one folder"
    fi
    cp -p "$from" "$TMP/$name"
done
sed -i -E 's#@([^@]*/)?([^/@]+)@#@./\2@#g' "$TMP/$STAGE"
(cd "$TMP" && find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\n' \
    | LC_ALL=C sort | xargs -d '\n' sha256sum > SHA256SUMS)

chmod 755 "$TMP"                    # mktemp -d makes it 700
rm -rf "$DEST"
mv "$TMP" "$DEST"
trap - EXIT
say "$DEST <- $SRC ($(ls "$DEST" | wc -l) files, $(du -sh "$DEST" | cut -f1))"
```

- [ ] **Step 4: รันให้ผ่าน**

Run: `chmod +x scripts/vendor-map.sh && conda run -n drone python -m pytest tests/test_vendor_map.py -q`
Expected: `6 passed`

- [ ] **Step 5: ทั้งชุด + commit**

```bash
conda run -n drone python -m pytest -q 2>&1 | tail -1     # 166 passed
git add scripts/vendor-map.sh tests/test_vendor_map.py
git commit -m "feat: vendor-map.sh copies a map stage and the layers it points at

Flat into vendor/maps/<site>/, references rewritten to ./<name>, with
SHA256SUMS so a copy on another machine can be checked.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017NmdMU3j35NBqncBRrRsWk"
```

---

### Task 3: สำเนาจริงใน `vendor/`

**Files:**
- Create: `vendor/drone-sitl.manifest`, `vendor/patches/drone-sitl/0001-sites-nt-testgs-map-in-repo.patch`, `vendor/README.md`, `tests/test_vendored.py`
- Create (โดยสคริปต์เท่านั้น): `vendor/drone-sitl/**`, `vendor/maps/nt-testgs/*`
- Modify: `.gitignore`, `tests/test_score.py:1-7,58-64`, `docs/progress.md` (บันทึกการตัดสินใจ), `docs/drone-sitl-changes.md` (หัวไฟล์)

**Interfaces:**
- Consumes: `scripts/vendor-drone-sitl.sh` (Task 1), `scripts/vendor-map.sh` (Task 2), `flight_service.score.load_truth(drone_sitl_dir, site) -> ((lat, lon), {name: (east, north)})`
- Produces: `vendor/drone-sitl/` ที่มีทุก path ใน manifest + `VENDORED` · `vendor/maps/nt-testgs/{drone_map.usda, drone_map_physics.usdc, drone_map_vehicles.json, drone_map_report.json, spawn_actual.json, nt_testgs.usdc, Truck2.usd, SHA256SUMS}` · ใน `vendor/drone-sitl/sim/sites.py`: `get_site("nt-testgs").resolved_stage_path() == <root>/vendor/maps/nt-testgs/drone_map.usda`

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

`tests/test_vendored.py`:

```python
"""The vendored drone-sitl copy and map: complete, self-contained, and what
flight-service expects (vendor/README.md)."""
import hashlib
import importlib.util
import modulefinder
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from flight_service.score import load_truth

ROOT = Path(__file__).resolve().parent.parent
SITL = ROOT / "vendor" / "drone-sitl"
MAP = ROOT / "vendor" / "maps" / "nt-testgs"
BIG = ("nt_testgs.usdc", "Truck2.usd")       # not in git: copied across by hand
LOCAL = {"offboard", "waypoints", "agent_control", "docker_build", "detections",
         "det_recorder", "competition", "competition.agent", "competition.commands",
         "competition.frames", "competition.harness", "competition.state",
         "sites", "stage_builder"}


def manifest():
    lines = (ROOT / "vendor" / "drone-sitl.manifest").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def sums():
    """{file name: sha256} from SHA256SUMS."""
    pairs = (ln.split(None, 1) for ln in (MAP / "SHA256SUMS").read_text().splitlines() if ln.strip())
    return {name: digest for digest, name in pairs}


def test_every_manifest_path_is_in_the_copy():
    assert [p for p in manifest() if not (SITL / p).exists()] == []


def test_the_copy_records_its_source_and_patch():
    rec = dict(ln.split("=", 1) for ln in (SITL / "VENDORED").read_text().splitlines())
    assert re.fullmatch(r"[0-9a-f]{40}", rec["source_commit"])
    assert rec["patches"].split() == ["0001-sites-nt-testgs-map-in-repo.patch"]


def test_the_scripts_flight_service_runs_are_executable():
    for name in ("run-website.sh", "stop-website.sh", "launch-sitl.sh"):
        assert os.access(SITL / "sim" / name, os.X_OK), name


@pytest.mark.parametrize("script", ["joystick-server.py", "agent_runner.py", "sim/bootstrap.py",
                                    "examples/competition-submission/fly_headless.py"])
def test_local_imports_resolve_inside_the_copy(script):
    mf = modulefinder.ModuleFinder(path=[str(SITL / d) for d in ("", "streaming", "sim")] + sys.path)
    mf.run_script(str(SITL / script))
    assert sorted(LOCAL & set(mf.badmodules)) == []
    outside = [m.__file__ for n, m in mf.modules.items()
               if n in LOCAL and not Path(m.__file__).is_relative_to(SITL)]
    assert outside == []


def test_vendored_code_names_no_home_directory():
    hits = [str(p.relative_to(SITL)) for p in SITL.rglob("*")
            if p.is_file() and p.suffix in {".py", ".sh"}
            and re.search(r"/home/\w", p.read_text(errors="replace"))]
    assert hits == []


def test_site_stage_is_the_vendored_map(monkeypatch):
    spec = importlib.util.spec_from_file_location("_vendored_sites", SITL / "sim" / "sites.py")
    sites = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, sites)   # dataclasses look the module up
    spec.loader.exec_module(sites)
    site = sites.get_site("nt-testgs")
    assert site.resolved_stage_path() == MAP / "drone_map.usda"
    assert site.uses_cesium is False


def test_map_references_stay_inside_its_folder():
    refs = set(re.findall(r"@([^@]+)@", (MAP / "drone_map.usda").read_text()))
    assert refs == {"./drone_map_physics.usdc", "./nt_testgs.usdc", "./Truck2.usd"}
    assert {r[2:] for r in refs} <= set(sums())


def test_small_map_files_match_and_big_ones_are_ignored():
    for name, digest in sums().items():
        f = MAP / name
        if name in BIG and not f.exists():
            continue                                  # fresh clone: preflight reports it
        assert hashlib.sha256(f.read_bytes()).hexdigest() == digest, name
    for name in BIG:                                  # check-ignore is 0 if ANY path is ignored
        ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(MAP / name)])
        assert ignored.returncode == 0, name


def test_load_truth_reads_the_vendored_map():
    origin, trucks = load_truth(SITL, "nt-testgs")
    assert origin == pytest.approx((14.028519616, 100.43642032))
    assert sorted(trucks) == ["Vehicle_01", "Vehicle_02", "Vehicle_03"]
    import fly_headless
    assert Path(fly_headless.__file__).is_relative_to(SITL)
```

แก้ `tests/test_score.py`: ลบเทสต์ `test_load_truth_from_drone_sitl` และค่าคงที่ `DRONE_SITL` (บรรทัด 58-64 เดิม) ซึ่งย้ายไปเป็น `test_load_truth_reads_the_vendored_map` แล้ว · ลบ import ที่ไม่มีใครใช้แล้ว: `from pathlib import Path` และ `load_truth` จากบรรทัด import (`from flight_service.score import ScoreV0, enu, score_file`)

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `conda run -n drone python -m pytest tests/test_vendored.py -q`
Expected: FAIL / ERROR ทุกข้อ (`FileNotFoundError: .../vendor/drone-sitl.manifest`)

- [ ] **Step 3: manifest**

`vendor/drone-sitl.manifest`:

```
# Files flight-service runs from drone-sitl. scripts/vendor-drone-sitl.sh copies
# exactly these from one commit into vendor/drone-sitl/, keeping drone-sitl's
# layout: its scripts find each other relative to the repo root.
#
# Web server :8090 (pull/upload/build, AgentRun, /ws, detections) and its imports
joystick-server.py
web
streaming/agent_control.py
streaming/det_recorder.py
streaming/detections.py
streaming/docker_build.py
streaming/offboard.py
streaming/waypoints.py
competition/__init__.py
competition/agent.py
competition/commands.py
competition/frames.py
competition/harness.py
competition/state.py
# competition-base image (bundle uploads build FROM it) copies agent_runner.py + competition/
agent_runner.py
docker/competition-base/Dockerfile
# Isaac Sim + PX4 bring-up
sim/run-website.sh
sim/stop-website.sh
sim/launch-sitl.sh
sim/bootstrap.py
sim/sites.py
sim/stage_builder.py
sim/secrets.env.example
drone_setup_px4_cesium.py
# Truck truth + flight checker (flight_service/score.py, finalize.py)
examples/competition-submission/fly_headless.py
```

- [ ] **Step 4: patch 0001**

สร้างจากไฟล์ต้นทางที่ commit นั้น (อย่าพิมพ์ hunk เอง เพราะบรรทัด context ว่างต้องมีช่องว่างนำหน้าหนึ่งตัว):

```bash
mkdir -p vendor/patches/drone-sitl
T="$(mktemp -d)"; mkdir -p "$T/a/sim" "$T/b/sim"
git -C ~/pai/drone-sitl show 2945783:sim/sites.py > "$T/a/sim/sites.py"
python3 - "$T" <<'EOF'
import pathlib, sys
t = pathlib.Path(sys.argv[1])
src = (t / "a/sim/sites.py").read_text()
old = '    stage_usd="/home/innovation/Tiger/map_setup_output_nt_testgs/drone_map.usda",\n'
new = ('    # flight-service vendor patch 0001: the map ships beside this copy\n'
       "    # (vendor/maps/nt-testgs, see vendor/README.md), not in one machine's home.\n"
       '    stage_usd="../maps/nt-testgs/drone_map.usda",\n')
assert src.count(old) == 1
(t / "b/sim/sites.py").write_text(src.replace(old, new))
EOF
(cd "$T" && diff -u a/sim/sites.py b/sim/sites.py) | sed '1,2s/\t.*//' \
    > vendor/patches/drone-sitl/0001-sites-nt-testgs-map-in-repo.patch
rm -rf "$T"
cat vendor/patches/drone-sitl/0001-sites-nt-testgs-map-in-repo.patch
```

Expected (ตรวจด้วยตา):

```diff
--- a/sim/sites.py
+++ b/sim/sites.py
@@ -150,7 +150,9 @@
     spawn_xy=(4.7762, -19.3996),
     spawn_agl_m=0.5,               # -> spawn_z = 6.4826
     heading_deg=0.0,
-    stage_usd="/home/innovation/Tiger/map_setup_output_nt_testgs/drone_map.usda",
+    # flight-service vendor patch 0001: the map ships beside this copy
+    # (vendor/maps/nt-testgs, see vendor/README.md), not in one machine's home.
+    stage_usd="../maps/nt-testgs/drone_map.usda",
 )
 
 SITES: dict[str, Site] = {s.name: s for s in (BANGKOK_SURVEY_040, NT_TESTGS)}
```

- [ ] **Step 5: `.gitignore` (ก่อนสร้างสำเนา เพื่อไม่ให้ไฟล์ใหญ่หลุดเข้า stage)**

ต่อท้าย `.gitignore`:

```
# vendored drone-sitl: runtime output it writes inside its own folder
vendor/drone-sitl/logs/
vendor/drone-sitl/recordings/
vendor/drone-sitl/.cache/
vendor/drone-sitl/sim/secrets.env
vendor/drone-sitl/NvStreamer-*.etli
# map layers too big for git: copied across by hand (vendor/README.md), SHA256SUMS checks them
vendor/maps/nt-testgs/nt_testgs.usdc
vendor/maps/nt-testgs/Truck2.usd
```

- [ ] **Step 6: สร้างสำเนาจริง**

```bash
./scripts/vendor-drone-sitl.sh ~/pai/drone-sitl 2945783
./scripts/vendor-map.sh nt-testgs ~/Tiger/map_setup_output_nt_testgs
cat vendor/drone-sitl/VENDORED
du -sh vendor/drone-sitl vendor/maps/nt-testgs
```

Expected: `vendor-drone-sitl: ... <- 2945783 (25 paths, 1 patches)` · `vendor-map: ... (8 files, 292M)` · `VENDORED` มี `source_commit=2945783…` และ `patches=0001-sites-nt-testgs-map-in-repo.patch` · `vendor/drone-sitl` ไม่เกิน ~1 MB

- [ ] **Step 7: ตรวจ layer ของแผนที่ด้วย pxr ของ Isaac (หลักฐานว่าไม่มีอะไรหลุดออกนอกโฟลเดอร์)**

```bash
E="$(ls -d "$HOME"/isaac-sim6/extscache/omni.usd.libs-*/ | head -1)"
env -u CONDA_PREFIX -u CONDA_DEFAULT_ENV PYTHONPATH="$E" LD_LIBRARY_PATH="$E/bin" \
  "$HOME/isaac-sim6/kit/python/bin/python3" -c "
from pxr import UsdUtils, Sdf
layers, assets, unresolved = UsdUtils.ComputeAllDependencies(Sdf.AssetPath('$PWD/vendor/maps/nt-testgs/drone_map.usda'))
print(*sorted(l.realPath for l in layers), sep='\n'); print('assets', assets, 'unresolved', unresolved)"
```

Expected: 4 บรรทัด ทุกบรรทัดขึ้นต้นด้วย `$PWD/vendor/maps/nt-testgs/` (`Truck2.usd`, `drone_map.usda`, `drone_map_physics.usdc`, `nt_testgs.usdc`) · `assets [] unresolved []` · ถ้ามีบรรทัดที่อยู่นอกโฟลเดอร์ → หยุด รายงานผู้ใช้

- [ ] **Step 8: รันเทสต์ให้ผ่าน**

Run: `conda run -n drone python -m pytest tests/test_vendored.py tests/test_score.py -q`
Expected: `12 passed` ใน test_vendored (4 ข้อจาก parametrize) และ test_score ผ่านโดยไม่มี skip

- [ ] **Step 9: เอกสาร**

`vendor/README.md`:

````markdown
# vendor/ — drone-sitl ที่ flight-service ใช้ (สำเนา)

flight-service รันสคริปต์และเว็บ `:8090` ของ drone-sitl จากโฟลเดอร์นี้ จึงไม่ต้องมี `~/pai/drone-sitl` บนเครื่อง (ตัดสินใจ 2026-10-06 ทาง A · `docs/progress.md`)

| path | คืออะไร | เข้า git |
|---|---|---|
| `drone-sitl/` | ไฟล์ตาม `drone-sitl.manifest` จาก commit เดียว + patch ใน `patches/drone-sitl/` · ต้นทางอยู่ใน `drone-sitl/VENDORED` | ✅ ยกเว้นของที่เกิดตอนรัน: `logs/ recordings/ .cache/ sim/secrets.env` |
| `maps/nt-testgs/` | แผนที่ site `nt-testgs` (map_setup_tool) + layer ที่มันอ้างถึง วางแบนในโฟลเดอร์เดียว · `SHA256SUMS` | ✅ ไฟล์เล็ก · ❌ `nt_testgs.usdc` (228 MB) · `Truck2.usd` (64 MB) |

## กฎ

- **ห้ามแก้ไฟล์ใน `drone-sitl/` ตรงๆ** ซิงก์ครั้งหน้าจะทับ · ต้องแก้ → เพิ่ม `patches/drone-sitl/NNNN-<เรื่อง>.patch` (`diff -u a/<path> b/<path>`) แล้วรันสคริปต์ซิงก์
- patch ที่มี: `0001-sites-nt-testgs-map-in-repo.patch` ชี้ `stage_usd` ของ `nt-testgs` ไปที่ `../maps/nt-testgs/drone_map.usda` (เดิมเป็น path ตายตัวใน home ของเครื่องเดิม)

## ซิงก์จาก drone-sitl ต้นทาง

1. ปิด sim/เว็บก่อน (`./scripts/stop-service.sh` และ `vendor/drone-sitl/sim/stop-website.sh`)
2. `./scripts/vendor-drone-sitl.sh ~/pai/drone-sitl <commit>` (ไม่ใส่ commit = HEAD · ใช้เฉพาะของที่ commit แล้ว)
3. ต้นทาง import ไฟล์ใหม่ → เพิ่มใน `drone-sitl.manifest` (`pytest tests/test_vendored.py` ฟ้องถ้า import หาไม่เจอในสำเนา)
4. patch ใช้ไม่ได้ → สคริปต์หยุดก่อนแตะโฟลเดอร์ · แก้ patch แล้วรันใหม่
5. `pytest` → `git diff --stat vendor/` → commit โดยบอก commit ต้นทาง

## map

- สร้าง/อัปเดต: `./scripts/vendor-map.sh nt-testgs ~/Tiger/map_setup_output_nt_testgs` (ทุกไฟล์ในโฟลเดอร์ + ไฟล์ที่ `drone_map.usda` อ้างถึง แล้วเขียน ref เป็น `./<ชื่อ>`)
- ตรวจว่าไม่มี layer ซ้อนที่หลุดออกนอกโฟลเดอร์ ด้วย pxr ของ Isaac (ต้องได้ 4 layer ในโฟลเดอร์นี้ · `unresolved []`):
  ```bash
  E="$(ls -d "$HOME"/isaac-sim6/extscache/omni.usd.libs-*/ | head -1)"
  env -u CONDA_PREFIX -u CONDA_DEFAULT_ENV PYTHONPATH="$E" LD_LIBRARY_PATH="$E/bin" \
    "$HOME/isaac-sim6/kit/python/bin/python3" -c "
  from pxr import UsdUtils, Sdf
  layers, assets, unresolved = UsdUtils.ComputeAllDependencies(Sdf.AssetPath('$PWD/vendor/maps/nt-testgs/drone_map.usda'))
  print(*sorted(l.realPath for l in layers), sep='\n'); print('assets', assets, 'unresolved', unresolved)"
  ```
- ย้ายเครื่อง: ไฟล์ใหญ่ 2 ตัวไม่อยู่ใน git → เครื่องเดิม `tar -C vendor/maps -cf nt-testgs-map.tar nt-testgs` → เครื่องใหม่ `tar -C vendor/maps -xf nt-testgs-map.tar` → `./scripts/preflight.sh` ตรวจ `SHA256SUMS`
````

`docs/progress.md` ต่อท้ายตาราง "บันทึกการตัดสินใจ":

```
| 2026-10-06 | standalone | **ทาง A:** สำเนาไฟล์ drone-sitl ที่ใช้จริงใน `vendor/drone-sitl/` (จาก `2945783` ด้วย `scripts/vendor-drone-sitl.sh` + patch) · แผนที่ใน `vendor/maps/nt-testgs/` (ไฟล์ใหญ่ 2 ตัวไม่เข้า git · `SHA256SUMS`) · `scripts/preflight.sh` ตรวจเครื่องใหม่ · **แทนกฎเดิม "ห้าม copy โค้ด drone-sitl"** · แผน `docs/superpowers/plans/2026-10-06-vendor-drone-sitl.md` |
```

`docs/drone-sitl-changes.md` แทรกบนสุด (ก่อนหัวข้อแรก):

```markdown
> **ตั้งแต่ 2026-10-06** flight-service รันจากสำเนาใน `vendor/drone-sitl/` (commit `2945783` ซึ่งรวมการแก้ทั้ง 3 ครั้งด้านล่างแล้ว) · การแก้ drone-sitl ต้นทางหลังจากนี้มีผลกับ flight-service ก็ต่อเมื่อซิงก์เข้ามา (`vendor/README.md`)
```

- [ ] **Step 10: ทั้งชุด + ตรวจว่าไฟล์ใหญ่ไม่เข้า stage + commit**

```bash
conda run -n drone python -m pytest -q 2>&1 | tail -1     # 177 passed (166 + 12 − 1 ที่ย้าย)
git add .gitignore vendor tests/test_vendored.py tests/test_score.py docs/progress.md docs/drone-sitl-changes.md
git diff --cached --stat | tail -1
git diff --cached --name-only | grep -E 'nt_testgs\.usdc|Truck2\.usd|/logs/|secrets\.env$' ; echo "rc=$?"   # rc=1 = ไม่มี
du -ch $(git diff --cached --name-only) | tail -1          # ไม่เกิน ~2 MB
git commit -m "feat: vendor drone-sitl 2945783 and the nt-testgs map into vendor/

flight-service no longer needs a ~/pai/drone-sitl checkout: the 25 paths
it runs, one patch (nt-testgs stage path into the repo), and the map's
small files; the two big layers stay out of git, checked by SHA256SUMS.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017NmdMU3j35NBqncBRrRsWk"
```

---

### Task 4: `DRONE_SITL_DIR` default = สำเนาใน repo

**Files:**
- Modify: `flight_service/config.py:69` (และเพิ่ม helper เหนือ `class Settings`)
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `vendor/drone-sitl/` (Task 3)
- Produces: `Settings.from_env(env).drone_sitl_dir` เป็น path เต็มเสมอ: ไม่ตั้ง → `HERE / "vendor" / "drone-sitl"` · relative → `HERE / value` · `~` ขยายเป็น home

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

ต่อท้าย `tests/test_config.py` (และเพิ่ม `from pathlib import Path` กับ `HERE` ใน import: `from flight_service.config import DEFAULT_ALLOWED, HERE, Settings`):

```python
def test_drone_sitl_dir_defaults_to_the_vendored_copy():
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN})
    assert s.drone_sitl_dir == HERE / "vendor" / "drone-sitl"
    assert (s.drone_sitl_dir / "sim" / "run-website.sh").is_file()


def test_relative_drone_sitl_dir_is_relative_to_the_project_not_the_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN, "DRONE_SITL_DIR": "vendor/drone-sitl"})
    assert s.drone_sitl_dir == HERE / "vendor" / "drone-sitl" and s.drone_sitl_dir.is_absolute()


def test_drone_sitl_dir_expands_home(monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN, "DRONE_SITL_DIR": "~/pai/drone-sitl"})
    assert s.drone_sitl_dir == Path("/h/pai/drone-sitl")
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `conda run -n drone python -m pytest tests/test_config.py -q`
Expected: 3 FAIL (default ยังเป็น `~/pai/drone-sitl` · relative ได้ `vendor/drone-sitl` ไม่ใช่ path เต็ม · `~` ไม่ขยาย)

- [ ] **Step 3: แก้ config**

ใน `flight_service/config.py` เพิ่มเหนือ `@dataclass(frozen=True)`:

```python
def project_path(value):
    """A relative path is relative to this project, not to wherever the
    service was started: sim.py runs drone-sitl's scripts there and matches
    its processes by it."""
    p = Path(value).expanduser()
    return p if p.is_absolute() else HERE / p
```

แล้วเปลี่ยนบรรทัดใน `from_env`:

```python
            drone_sitl_dir=project_path(env.get("DRONE_SITL_DIR", "vendor/drone-sitl")),
```

`.env.example` แทนบรรทัด `DRONE_SITL_DIR=...` ด้วย:

```
# สำเนา drone-sitl ใน repo นี้ (vendor/README.md) · ชี้ checkout drone-sitl อื่นได้ด้วย path เต็ม
DRONE_SITL_DIR=vendor/drone-sitl
# ของที่ติดตั้งไว้ที่อื่นที่ไม่ใช่ค่า default ของ launch-sitl.sh (scripts/preflight.sh ตรวจให้)
#ISAAC_DIR=$HOME/isaac-sim6
#PEGASUS_EXTS=$HOME/PegasusSimulator/extensions
#CONDA_ENV=drone
```

- [ ] **Step 4: รันให้ผ่าน**

Run: `conda run -n drone python -m pytest tests/test_config.py -q`
Expected: ผ่านทั้งไฟล์ (`test_from_env_overrides` เดิมใช้ path เต็มจึงยังผ่าน)

- [ ] **Step 5: ทั้งชุด + commit**

```bash
conda run -n drone python -m pytest -q 2>&1 | tail -1     # 180 passed
git add flight_service/config.py tests/test_config.py .env.example
git commit -m "feat: DRONE_SITL_DIR defaults to the vendored copy

A relative value is taken from the project root, not the cwd: sim.py
runs drone-sitl's scripts there and pgreps for its bootstrap by it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017NmdMU3j35NBqncBRrRsWk"
```

---

### Task 5: `preflight` ตรวจเครื่อง

**Files:**
- Create: `flight_service/preflight.py`, `scripts/preflight.sh`, `requirements-drone.txt`
- Test: `tests/test_preflight.py`

**Interfaces:**
- Consumes: `flight_service.config.Settings.from_env` (Task 4: `drone_sitl_dir` เป็น path เต็ม, `site`) · `sites.py` ของสำเนา: `get_site(name)` → object ที่มี `.name`, `.uses_cesium`, `.resolved_stage_path() -> Path | None`
- Produces: `Check(name, ok, detail, fix="", required=True)` · `run_checks(env, run=subprocess.run, which=shutil.which) -> list[Check]` · `main(env=None, out=sys.stdout, run=..., which=...) -> int` (0 = ทุกข้อที่ required ผ่าน) · `check_sitl(sitl_dir) -> Check` · ชื่อ check: `token`, `drone-sitl`, `site`, `map`, `cesium`, `isaac sim`, `pegasus`, `px4 sitl`, `conda env`, `ffmpeg`, `docker`, `gpu runtime`, `competition-base`, `registry login` (ข้อสุดท้าย required=False) · บรรทัดผล: `ok   <name>`, `FAIL <name>`, `warn <name>` แล้ว `     fix: ...` · บรรทัดท้าย `preflight: ready` หรือ `preflight: N required check(s) failed`

- [ ] **Step 1: เขียนเทสต์ที่ล้ม**

`tests/test_preflight.py`:

```python
import hashlib
import io
import subprocess

import pytest

from flight_service import preflight
from flight_service.config import HERE

TOKEN = "t" * 32
FAKE_SITES = '''
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Site:
    name: str
    stage_usd: object

    @property
    def uses_cesium(self):
        return self.stage_usd is None

    def resolved_stage_path(self):
        if self.stage_usd is None:
            return None
        return (Path(__file__).resolve().parent.parent / self.stage_usd).resolve()


SITES = {"mapsite": Site("mapsite", "../maps/m/drone_map.usda"), "tiles": Site("tiles", None)}


def get_site(name):
    return SITES[name]
'''


class Machine:
    """A fake box on which everything preflight looks for is present."""

    def __init__(self, root):
        self.root, self.home = root, root / "home"
        isaac = self.home / "isaac-sim6" / "isaac-sim.streaming.sh"
        isaac.parent.mkdir(parents=True)
        isaac.write_text("#!/bin/sh\n")
        isaac.chmod(0o755)
        self.px4 = root / "px4" / "build" / "px4_sitl_default" / "bin" / "px4"
        self.px4.parent.mkdir(parents=True)
        self.px4.write_text("")
        cfg = self.home / "PegasusSimulator" / "extensions" / "pegasus.simulator" / "config" / "configs.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(f"ardupilot_dir: ~/ardupilot\npx4_dir: {root / 'px4'}\n")
        (self.home / ".docker").mkdir()
        (self.home / ".docker" / "config.json").write_text('{"auths": {"https://index.docker.io/v1/": {}}}')
        self.sitl = root / "drone-sitl"
        for f in preflight.SITL_FILES:
            (self.sitl / f).parent.mkdir(parents=True, exist_ok=True)
            (self.sitl / f).write_text("")
        (self.sitl / "sim" / "sites.py").write_text(FAKE_SITES)
        (self.sitl / "VENDORED").write_text("source_commit=" + "a" * 40 + "\npatches=\n")
        self.map = root / "maps" / "m"
        self.map.mkdir(parents=True)
        layers = {"drone_map.usda": b"#usda 1.0\n", "big.usdc": b"layer"}
        for name, data in layers.items():
            (self.map / name).write_bytes(data)
        (self.map / "SHA256SUMS").write_text(
            "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in layers.items()))
        self.env = {"HOME": str(self.home), "RUNNER_TOKEN": TOKEN,
                    "DRONE_SITL_DIR": str(self.sitl), "SITE": "mapsite"}
        self.fail = set()          # "conda run", "docker info", "docker image"
        self.missing = set()       # tool names which() does not find
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if " ".join(cmd[:2]) in self.fail else 0, "", "")

    def which(self, name):
        return None if name in self.missing else f"/usr/bin/{name}"

    def checks(self, **env):
        return {c.name: c for c in preflight.run_checks({**self.env, **env}, self.run, self.which)}

    def main(self, **env):
        out = io.StringIO()
        code = preflight.main({**self.env, **env}, out=out, run=self.run, which=self.which)
        return code, out.getvalue()


@pytest.fixture
def box(tmp_path):
    return Machine(tmp_path)


def test_a_ready_machine_passes_every_check(box):
    assert [n for n, c in box.checks().items() if not c.ok] == []
    code, out = box.main()
    assert code == 0 and "preflight: ready" in out


def test_missing_isaac_fails_and_says_where_it_looked(box):
    c = box.checks(ISAAC_DIR=str(box.root / "nowhere"))["isaac sim"]
    assert not c.ok and "nowhere" in c.detail and "ISAAC_DIR" in c.fix


def test_px4_is_found_through_the_pegasus_config(box):
    box.px4.unlink()
    c = box.checks()["px4 sitl"]
    assert not c.ok and str(box.px4) in c.detail and "make px4_sitl_default" in c.fix


def test_no_pegasus_fails_both_pegasus_and_px4(box):
    c = box.checks(PEGASUS_EXTS=str(box.root / "nowhere"))
    assert not c["pegasus"].ok and "PEGASUS_EXTS" in c["pegasus"].fix and not c["px4 sitl"].ok


def test_map_reports_missing_and_changed_files(box):
    (box.map / "big.usdc").unlink()
    (box.map / "drone_map.usda").write_bytes(b"edited")
    c = box.checks()["map"]
    assert not c.ok and "missing: big.usdc" in c.detail and "changed: drone_map.usda" in c.detail
    assert "vendor/README.md" in c.fix


def test_map_without_sha256sums_only_needs_the_stage_file(box):
    (box.map / "SHA256SUMS").unlink()
    assert box.checks()["map"].ok
    (box.map / "drone_map.usda").unlink()
    assert not box.checks()["map"].ok


def test_a_map_site_needs_no_cesium(box):
    c = box.checks()["cesium"]
    assert c.ok and "not needed" in c.detail


def test_a_cesium_site_needs_extensions_and_a_token(box):
    c = box.checks(SITE="tiles")
    assert not c["cesium"].ok and "CESIUM_EXTS" in c["cesium"].fix
    assert c["map"].ok                                   # tile sites have no stage file
    (box.home / "cesium-omniverse-6.0-build" / "exts").mkdir(parents=True)
    assert "CESIUM_ION_TOKEN" in box.checks(SITE="tiles")["cesium"].detail
    (box.sitl / "sim" / "secrets.env").write_text("export CESIUM_ION_TOKEN=abc\n")
    assert box.checks(SITE="tiles")["cesium"].ok


def test_an_unknown_site_is_a_failed_check_not_a_crash(box):
    c = box.checks(SITE="nope")
    assert not c["site"].ok and "nope" in c["site"].detail and "map" not in c


def test_a_conda_env_without_the_modules_fails_with_the_install_line(box):
    box.fail.add("conda run")
    c = box.checks()["conda env"]
    assert not c.ok and "requirements-drone.txt" in c.fix
    assert any("cv2" in " ".join(cmd) for cmd in box.calls)


def test_docker_gpu_runtime_and_base_image(box):
    box.missing.add("nvidia-container-runtime")
    box.fail.add("docker image")
    c = box.checks()
    assert not c["gpu runtime"].ok and "nvidia-container-toolkit" in c["gpu runtime"].fix
    assert not c["competition-base"].ok
    assert "docker/competition-base/Dockerfile" in c["competition-base"].fix


def test_commands_that_are_not_installed_are_failed_checks(box):
    def run(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    c = {c.name: c for c in preflight.run_checks(box.env, run, box.which)}
    assert not c["docker"].ok and not c["conda env"].ok


def test_no_registry_login_is_only_a_warning(box):
    (box.home / ".docker" / "config.json").unlink()
    code, out = box.main()
    assert code == 0 and "warn registry login" in out and "docker login" in out


def test_a_short_token_fails(box):
    code, out = box.main(RUNNER_TOKEN="short")
    assert code == 1 and "FAIL token" in out and "1 required check(s) failed" in out


def test_the_vendored_copy_passes_the_drone_sitl_check():
    c = preflight.check_sitl(HERE / "vendor" / "drone-sitl")
    assert c.ok and "vendored @" in c.detail
```

- [ ] **Step 2: รันให้เห็นว่าล้ม**

Run: `conda run -n drone python -m pytest tests/test_preflight.py -q`
Expected: ERROR `ImportError: cannot import name 'preflight' from 'flight_service'`

- [ ] **Step 3: เขียน `flight_service/preflight.py`**

```python
"""Is this machine ready to fly? Checks what the repo cannot carry -- Isaac
Sim, Pegasus + PX4, the conda env, Docker + GPU runtime, the base image,
the map's big layers -- and says how to fix each gap. Read-only.

    ./scripts/preflight.sh        (sources .env like run-service.sh)
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

# What flight-service runs from DRONE_SITL_DIR (sim.py, score.py, finalize.py).
SITL_FILES = ("joystick-server.py", "sim/run-website.sh", "sim/stop-website.sh",
              "sim/launch-sitl.sh", "sim/sites.py",
              "examples/competition-submission/fly_headless.py")
# joystick-server.py + streaming/ + this service share one env (requirements-drone.txt).
ENV_MODULES = ("fastapi", "uvicorn", "pydantic", "websockets", "pymavlink", "numpy", "PIL", "cv2")
BASE_IMAGE = "competition-base:latest"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    required: bool = True


def _succeeds(run, cmd, timeout=120):
    try:
        return run(cmd, capture_output=True, text=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def load_site(sitl_dir, name):
    """drone-sitl's own sites.get_site(name), loaded from the file without
    putting drone-sitl on sys.path."""
    spec = importlib.util.spec_from_file_location("_preflight_sites",
                                                  Path(sitl_dir) / "sim" / "sites.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # dataclasses look the module up while building Site
    try:
        spec.loader.exec_module(mod)
        return mod.get_site(name)
    finally:
        sys.modules.pop(spec.name, None)


def check_token(env):
    ok = len(env.get("RUNNER_TOKEN", "")) >= 32
    return Check("token", ok, "RUNNER_TOKEN set" if ok else "RUNNER_TOKEN missing or under 32 characters",
                 "python3 -c 'import secrets;print(secrets.token_urlsafe(32))' -> RUNNER_TOKEN= in .env")


def check_sitl(sitl_dir):
    missing = [f for f in SITL_FILES if not (sitl_dir / f).is_file()]
    if missing:
        return Check("drone-sitl", False, f"{sitl_dir}: missing {', '.join(missing)}",
                     "DRONE_SITL_DIR=vendor/drone-sitl (the copy in this repo) or a full drone-sitl checkout")
    origin = "checkout"
    rec = sitl_dir / "VENDORED"
    if rec.is_file():
        fields = dict(ln.split("=", 1) for ln in rec.read_text().splitlines() if "=" in ln)
        origin = f"vendored @ {fields.get('source_commit', '?')[:7]}"
    return Check("drone-sitl", True, f"{sitl_dir} ({origin})")


def check_map(site):
    stage = site.resolved_stage_path()
    if stage is None:
        return Check("map", True, f"site {site.name} streams Cesium tiles; no stage file")
    fix = "copy the map folder across (vendor/README.md, 'map'), or ./scripts/vendor-map.sh"
    sums = stage.parent / "SHA256SUMS"
    if not sums.is_file():
        return Check("map", stage.is_file(), f"{stage} (no SHA256SUMS: layers not verified)", fix)
    bad = []
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        f = stage.parent / name.lstrip("*")
        if not f.is_file():
            bad.append(f"missing: {f.name}")
        elif _sha256(f) != digest:
            bad.append(f"changed: {f.name}")
    if bad:
        return Check("map", False, f"{stage.parent}: {'; '.join(bad)}", fix)
    return Check("map", True, f"{stage.parent} (SHA256SUMS ok)")


def _cesium_token(env, sitl_dir):
    if env.get("CESIUM_ION_TOKEN"):
        return True
    secrets = Path(env.get("SECRETS_FILE") or Path(sitl_dir) / "sim" / "secrets.env")
    try:
        text = secrets.read_text()
    except OSError:
        return False
    return bool(re.search(r"^\s*(?:export\s+)?CESIUM_ION_TOKEN=['\"]?[^'\"\s]", text, re.M))


def check_cesium(site, env, home, sitl_dir):
    if not site.uses_cesium:
        return Check("cesium", True, f"not needed: site {site.name} is a map stage")
    exts = Path(env.get("CESIUM_EXTS") or home / "cesium-omniverse-6.0-build" / "exts")
    if not exts.is_dir():
        return Check("cesium", False, f"no Cesium extensions at {exts}",
                     "build cesium-omniverse there, or set CESIUM_EXTS= in .env")
    if not _cesium_token(env, sitl_dir):
        return Check("cesium", False, "CESIUM_ION_TOKEN not set",
                     f"cp {sitl_dir}/sim/secrets.env.example {sitl_dir}/sim/secrets.env and fill it in")
    return Check("cesium", True, f"{exts} + token")


def check_isaac(env, home):
    sh = Path(env.get("ISAAC_DIR") or home / "isaac-sim6") / "isaac-sim.streaming.sh"
    return Check("isaac sim", os.access(sh, os.X_OK), str(sh),
                 "install Isaac Sim 6 there, or set ISAAC_DIR= in .env")


def check_pegasus(env, home):
    exts = Path(env.get("PEGASUS_EXTS") or home / "PegasusSimulator" / "extensions")
    cfg = exts / "pegasus.simulator" / "config" / "configs.yaml"
    if not cfg.is_file():
        return [Check("pegasus", False, f"no {cfg}",
                      "install PegasusSimulator there, or set PEGASUS_EXTS= in .env"),
                Check("px4 sitl", False, "unknown: no Pegasus config to read px4_dir from",
                      "fix pegasus first")]
    m = re.search(r"^px4_dir:\s*(\S+)", cfg.read_text(), re.M)
    if not m:
        return [Check("pegasus", True, str(exts)),
                Check("px4 sitl", False, f"no px4_dir in {cfg}", f"set px4_dir: in {cfg}")]
    px4_dir = Path(m.group(1)).expanduser()
    px4 = px4_dir / "build" / "px4_sitl_default" / "bin" / "px4"
    return [Check("pegasus", True, str(exts)),
            Check("px4 sitl", px4.is_file(), str(px4),
                  f"cd {px4_dir} && make px4_sitl_default (or fix px4_dir in {cfg})")]


def check_conda(env, run):
    name = env.get("CONDA_ENV", "drone")
    ok = _succeeds(run, ["conda", "run", "-n", name, "python", "-c", "import " + ", ".join(ENV_MODULES)])
    return Check("conda env", ok, f"{name}: {' '.join(ENV_MODULES)}",
                 f"conda create -n {name} python=3.11 && conda run -n {name} pip install -r requirements-drone.txt")


def check_ffmpeg(which):
    path = which("ffmpeg")
    return Check("ffmpeg", bool(path), path or "not on PATH (detection clips need it)",
                 "sudo apt install ffmpeg")


def check_docker(run):
    return Check("docker", _succeeds(run, ["docker", "info", "--format", "{{.ServerVersion}}"], 30),
                 "daemon reachable as this user",
                 "install Docker and add this user to the docker group")


def check_gpu_runtime(which):
    path = which("nvidia-container-runtime")
    return Check("gpu runtime", bool(path),
                 path or "missing: drone-sitl would run agents without --gpus",
                 "install nvidia-container-toolkit and restart docker")


def check_base_image(run, sitl_dir):
    ok = _succeeds(run, ["docker", "image", "inspect", BASE_IMAGE], 30)
    return Check("competition-base", ok,
                 f"{BASE_IMAGE} {'present' if ok else 'missing'} (bundle uploads build FROM it)",
                 f"cd {sitl_dir} && docker build -t {BASE_IMAGE} -f docker/competition-base/Dockerfile .")


def check_registry_login(env, home):
    cfg = Path(env.get("DOCKER_CONFIG") or home / ".docker") / "config.json"
    try:
        conf = json.loads(cfg.read_text())
    except (OSError, ValueError):
        conf = {}
    ok = bool(conf.get("credsStore") or conf.get("credHelpers")
              or any("docker.io" in k for k in conf.get("auths", {})))
    return Check("registry login", ok, str(cfg) if ok else "no Docker Hub login found",
                 "docker login  (perkiepai/* images are private)", required=False)


def run_checks(env, run=subprocess.run, which=shutil.which):
    home = Path(env.get("HOME") or Path.home())
    s = Settings.from_env({**env, "RUNNER_TOKEN": "x" * 32})    # the token gets its own check
    checks = [check_token(env), check_sitl(s.drone_sitl_dir)]
    try:
        site = load_site(s.drone_sitl_dir, s.site)
    except Exception as e:                       # noqa: BLE001 -- any failure = no usable site
        checks.append(Check("site", False, f"{s.site}: {e!r}", "SITE= must name a site in sim/sites.py"))
    else:
        checks += [Check("site", True, s.site), check_map(site),
                   check_cesium(site, env, home, s.drone_sitl_dir)]
    checks += [check_isaac(env, home), *check_pegasus(env, home), check_conda(env, run),
               check_ffmpeg(which), check_docker(run), check_gpu_runtime(which),
               check_base_image(run, s.drone_sitl_dir), check_registry_login(env, home)]
    return checks


def main(env=None, out=sys.stdout, run=subprocess.run, which=shutil.which):
    checks = run_checks(dict(os.environ if env is None else env), run, which)
    for c in checks:
        mark = "ok  " if c.ok else ("FAIL" if c.required else "warn")
        print(f"{mark} {c.name:<17} {c.detail}", file=out)
        if not c.ok:
            print(f"     fix: {c.fix}", file=out)
    bad = [c for c in checks if c.required and not c.ok]
    print("\npreflight: " + ("ready" if not bad else f"{len(bad)} required check(s) failed"), file=out)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/preflight.sh` (แล้ว `chmod +x`):

```bash
#!/usr/bin/env bash
# preflight.sh -- is this machine ready to run flight-service? Read-only: lists
# what is missing and how to fix it. Exit 1 if a required check fails.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
# preflight itself needs only the standard library: fall back to python3 when
# the conda env is what is missing.
PY="$(conda run -n "${CONDA_ENV:-drone}" python -c 'import sys; print(sys.executable)' 2>/dev/null)" \
    || PY=python3
exec "$PY" -m flight_service.preflight
```

`requirements-drone.txt`:

```
# conda env "drone" (flight-service + vendor/drone-sitl's web server):
#   conda create -n drone python=3.11 && conda run -n drone pip install -r requirements-drone.txt
# Versions both were verified with on 2026-10-05/06. Isaac Sim brings its own Python.
fastapi==0.141.1
uvicorn==0.52.0
pydantic==2.13.4
websockets==17.0
pymavlink==2.4.49
numpy==2.4.4
pillow==12.2.0
opencv-python==4.13.0.92
pytest==9.1.1
```

- [ ] **Step 4: รันให้ผ่าน**

Run: `chmod +x scripts/preflight.sh && conda run -n drone python -m pytest tests/test_preflight.py -q`
Expected: `15 passed`

- [ ] **Step 5: ลองบนเครื่องนี้ (อ่านอย่างเดียว)**

Run: `./scripts/preflight.sh; echo "exit=$?"`
Expected: ทุกข้อ `ok` (`cesium` = `not needed`) · `preflight: ready` · `exit=0` · ถ้า `.env` ยังชี้ `~/pai/drone-sitl` บรรทัด `drone-sitl` จะขึ้น `(checkout)` ซึ่งถูกต้อง (`.env` เปลี่ยนใน Task 6) · ข้อใดไม่ผ่านบนเครื่องนี้ → หยุด รายงานผู้ใช้ ห้ามแก้เครื่อง

- [ ] **Step 6: ทั้งชุด + commit**

```bash
conda run -n drone python -m pytest -q 2>&1 | tail -1     # 195 passed
git add flight_service/preflight.py scripts/preflight.sh requirements-drone.txt tests/test_preflight.py
git commit -m "feat: preflight.sh says what a new machine still lacks

Isaac Sim, Pegasus + PX4 (via Pegasus's own px4_dir), Cesium only for
sites that stream tiles, the conda env, ffmpeg, Docker + GPU runtime,
competition-base, the map's layers against SHA256SUMS, and the token.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017NmdMU3j35NBqncBRrRsWk"
```

- [ ] **Step 7: ⛔ ประตูอนุมัติ (โค้ด + เทสต์)** สรุปผู้ใช้: จำนวนเทสต์, ขนาด `vendor/`, ผล pxr, ผล preflight · รออนุมัติก่อน Task 6

---

### Task 6: บินจริงบนสำเนา

**Files:**
- Modify: `.env` (ไม่อยู่ใน git) · `docs/verification.md` · `docs/progress.md`
- Create: `docs/evidence/verification-vendor-preflight.log`, `docs/evidence/verification-vendor-run1.log`, `docs/evidence/verification-vendor-bundle.log`, `docs/evidence/verification-vendor-proc.txt`

**Interfaces:**
- Consumes: ทุกอย่างจาก Task 1–5 · `scripts/run-service.sh`, `scripts/stop-service.sh`, `scripts/mock-caller.sh IMAGE [FLIGHT_TIMEOUT_S]`
- Produces: หลักฐานว่า service บินจบด้วยสำเนาโดยไม่แตะ `~/pai/drone-sitl`, `~/Tiger`, `~/Downloads`

- [ ] **Step 1: ไม่มีอะไรค้าง + ให้ `.env` ชี้สำเนา**

```bash
./scripts/stop-service.sh
for p in 8080 8090; do curl -sf -o /dev/null --max-time 3 http://127.0.0.1:$p/ && echo "BUSY :$p"; done   # ต้องไม่มี BUSY
sed -i 's#^DRONE_SITL_DIR=.*#DRONE_SITL_DIR=vendor/drone-sitl#' .env
grep '^DRONE_SITL_DIR' .env
./scripts/preflight.sh | tee docs/evidence/verification-vendor-preflight.log    # preflight: ready · drone-sitl (vendored @ 2945783)
./scripts/run-service.sh
```

ถ้ามี BUSY → หยุด ถามผู้ใช้ (อาจเป็น sim ของคนอื่น · ห้ามปิดเอง)

- [ ] **Step 2: บินด้วย image บน registry (เทียบกับขั้น 4 เดิม: score 95.6, รถ 3/3)**

```bash
./scripts/mock-caller.sh perkiepai/truck-detector:20260929-214240 600 2>&1 | tee docs/evidence/verification-vendor-run1.log
```

Expected: state จบ `done` · `trucks 3/3` · score ใกล้ค่าเดิม (≥ 90) · ไฟล์ครบใน `mock-out/<job_id>/` (`score.json`, `result.json`, `analysis.txt`, MP4)

- [ ] **Step 3: ระหว่างที่ state = `flying` (อีก shell) เก็บหลักฐานว่าทุก process มาจากสำเนา**

```bash
cd ~/pai/flight-service
{
  echo "## bootstrap (ต้องมี: path ใน vendor)"; pgrep -af "$PWD/vendor/drone-sitl/sim/bootstrap\.py" | cut -c1-200
  echo "## อะไรจาก checkout เดิม (ต้องว่าง)"; pgrep -af "pai/drone-sit[l]/" ; echo "rc=$?"
  echo "## cwd ของ joystick-server (ต้องเป็น vendor/drone-sitl)"
  for p in $(pgrep -f "python -u joystick-server\.py"); do readlink /proc/$p/cwd; done
  echo "## layer ที่ Isaac map ไว้ (ถ้ามี ต้องอยู่ใน vendor/maps)"
  K="$(pgrep -f "$PWD/vendor/drone-sitl/sim/bootstrap\.py" | head -1)"
  grep -ohE "/[^ ]*(nt_testgs|Truck2|drone_map)[^ ]*" /proc/$K/maps | sort -u
} 2>&1 | tee docs/evidence/verification-vendor-proc.txt
```

Expected: ส่วนแรกมีบรรทัด · ส่วนสอง `rc=1` · ส่วนสามเป็น `.../flight-service/vendor/drone-sitl` · ส่วนสุดท้ายว่างได้ (Isaac อาจไม่ mmap layer) ถ้าว่างให้บันทึกว่า "ตรวจไม่ได้ทางนี้" แล้วอ้างผล pxr ใน Task 3 Step 7 + `test_site_stage_is_the_vendored_map` · ถ้าเจอ path นอก `vendor/` → หยุด รายงานผู้ใช้

- [ ] **Step 4: บินแบบ bundle (ใช้ `docker_build.py` + `competition-base` จากสำเนา)**

```bash
set -a; source .env; set +a
R="http://127.0.0.1:${RUNNER_PORT:-8095}"; H="Authorization: Bearer $RUNNER_TOKEN"
id="$(curl -s -X POST -T ~/pai/drone-sitl/examples/competition-submission/truck-detector.tar -H "$H" \
      "$R/jobs?kind=bundle&name=truck-detector&flight_timeout_s=600" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
echo "job $id"
until s="$(curl -s "$R/jobs/$id" -H "$H" | python3 -c 'import json,sys; j=json.load(sys.stdin); print(j["state"], (j.get("result") or {}).get("score"))')"; \
      echo "$(date +%T) $s"; [[ "$s" =~ ^(done|failed|killed) ]]; do sleep 15; done 2>&1 | tee docs/evidence/verification-vendor-bundle.log
```

Expected: `done` · score มีค่า (รอบเดิม 97.6, 3/3) · ไฟล์ input เป็นแค่ข้อมูลเข้า ไม่ใช่การพึ่ง checkout

- [ ] **Step 5: ตรวจหลังจบ**

```bash
for p in 8080 8090; do curl -sf -o /dev/null --max-time 3 http://127.0.0.1:$p/ && echo "STILL UP :$p"; done   # ต้องไม่มี
curl -s http://127.0.0.1:8095/healthz; echo                                  # ready:true
git status --short vendor/                                                     # ว่าง: ของตอนรันถูก ignore
ls vendor/drone-sitl/logs/launch-sitl.console
```

- [ ] **Step 6: บันทึก + commit**

`docs/verification.md` ต่อท้าย:

```markdown
---

# vendor drone-sitl: บินจริงบนสำเนา · 2026-10-06

> **สรุป: <ผ่าน/ไม่ผ่าน>** service รันจาก `vendor/drone-sitl` (`2945783` + patch 0001) และ `vendor/maps/nt-testgs` · ไม่มี process จาก `~/pai/drone-sitl`

| รอบ | ผล |
|---|---|
| preflight | <ทุกข้อ ok / ข้อที่ไม่ผ่าน> (`docs/evidence/verification-vendor-preflight.log`) |
| registry `perkiepai/truck-detector:20260929-214240` | `<state>` score <x> (<n>/3) · `<job_id>` (`docs/evidence/verification-vendor-run1.log`) |
| bundle `truck-detector.tar` | `<state>` score <x> (<n>/3) · `<job_id>` (`docs/evidence/verification-vendor-bundle.log`) |
| process | bootstrap จาก `vendor/` · joystick-server cwd `vendor/drone-sitl` · ไม่มีจาก checkout เดิม · layer ใน `/proc/<pid>/maps`: <ผล> (`docs/evidence/verification-vendor-proc.txt`) |
| หลังจบ | sim ปิด · `/healthz` ready · `git status vendor/` ว่าง |
```

(แทน `<...>` ด้วยค่าจริงจาก log ทุกช่อง · ผลไม่ผ่านให้เขียนตามจริง)

`docs/progress.md` เพิ่มแถวในตารางขั้น:

```
| V | standalone (vendor drone-sitl) | แผน `docs/superpowers/plans/2026-10-06-vendor-drone-sitl.md` · `vendor/` · `scripts/preflight.sh` | <สถานะจริง> · ⛔ รออนุมัติ README |
```

```bash
git add docs/verification.md docs/progress.md docs/evidence/verification-vendor-*.log docs/evidence/verification-vendor-proc.txt
git commit -m "docs: verify a real flight on the vendored drone-sitl copy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017NmdMU3j35NBqncBRrRsWk"
```

- [ ] **Step 7: ⛔ ประตูอนุมัติ (บินจริง)** สรุปผล + ลิงก์ log · รออนุมัติก่อน Task 7

---

### Task 7: README + ย้ายเครื่อง

**Files:**
- Modify: `README.md` (บรรทัด 3, 11, 141, 142, 144 + หัวข้อใหม่), `docs/progress.md`

**Interfaces:**
- Consumes: `scripts/preflight.sh`, `vendor/README.md`, `requirements-drone.txt`
- Produces: เอกสารที่คนทำตามบนเครื่องใหม่ได้

- [ ] **Step 1: แก้ path เดิมใน README**

- บรรทัด 3: `ผ่าน \`~/pai/drone-sitl\`` → `ผ่านสำเนา drone-sitl ใน \`vendor/drone-sitl\``
- บรรทัด 11 (ต้องมี): `conda env \`drone\` (\`requirements-drone.txt\`) · Docker + nvidia-container-toolkit · Isaac Sim 6 · PegasusSimulator + PX4-Autopilot (build \`px4_sitl_default\`) · ffmpeg — ตรวจทั้งหมดด้วย \`./scripts/preflight.sh\``
- บรรทัด 141, 142: `~/pai/drone-sitl/sim/stop-website.sh` และ `cd ~/pai/drone-sitl && ./sim/stop-website.sh` → `vendor/drone-sitl/sim/stop-website.sh`
- บรรทัด 144: `~/pai/drone-sitl/logs/launch-sitl.console` → `vendor/drone-sitl/logs/launch-sitl.console`
- ตรวจ: `grep -n "pai/drone-sitl" README.md` → เหลือเฉพาะที่พูดถึงการซิงก์ (ถ้ามี)

- [ ] **Step 2: เพิ่มหัวข้อ "ย้ายไปเครื่องใหม่" (ต่อจากหัวข้อติดตั้งเดิม)**

````markdown
### ย้ายไปเครื่องใหม่

repo นี้พก drone-sitl ส่วนที่ใช้มาด้วยแล้ว (`vendor/README.md`) · ที่ต้องมีบนเครื่องใหม่เอง:

| ของ | ที่ default | ตั้งที่อื่นได้ด้วย (`.env`) |
|---|---|---|
| Isaac Sim 6 (~50 GB) | `~/isaac-sim6` | `ISAAC_DIR` |
| PegasusSimulator | `~/PegasusSimulator/extensions` | `PEGASUS_EXTS` |
| PX4-Autopilot build `px4_sitl_default` | ตาม `px4_dir` ใน `pegasus.simulator/config/configs.yaml` | แก้ใน configs.yaml |
| conda env `drone` | `conda create -n drone python=3.11 && conda run -n drone pip install -r requirements-drone.txt` | `CONDA_ENV` |
| Docker + nvidia-container-toolkit + ffmpeg | apt | — |
| `docker login` (image `perkiepai/*` เป็น private) | `~/.docker/config.json` | — |
| Cesium build + token | **ไม่ต้องใช้กับ site `nt-testgs`** (เป็น map stage) | `CESIUM_EXTS`, `vendor/drone-sitl/sim/secrets.env` |

1. คัดลอก repo ไป (git clone หรือ copy ทั้งโฟลเดอร์)
2. ไฟล์แผนที่ใหญ่ที่ไม่อยู่ใน git: เครื่องเดิม `tar -C vendor/maps -cf nt-testgs-map.tar nt-testgs` → เครื่องใหม่ `tar -C vendor/maps -xf nt-testgs-map.tar`
3. image ฐานของ bundle: `cd vendor/drone-sitl && docker build -t competition-base:latest -f docker/competition-base/Dockerfile .`
4. `cp .env.example .env` → ตั้ง `RUNNER_TOKEN` (และ path ข้างบนถ้าไม่ตรง default)
5. `./scripts/preflight.sh` จนขึ้น `preflight: ready` (ทุกข้อที่ไม่ผ่านมีบรรทัด `fix:` บอกวิธี)
6. `./scripts/run-service.sh` แล้วลองด้วย `./scripts/mock-caller.sh <image>`
````

- [ ] **Step 3: progress + commit**

`docs/progress.md` แถว V: สถานะ → `✅ ... README หัวข้อ "ย้ายไปเครื่องใหม่"`

```bash
conda run -n drone python -m pytest -q 2>&1 | tail -1     # 195 passed
git add README.md docs/progress.md
git commit -m "docs: README runs from the vendored copy and covers a new machine

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017NmdMU3j35NBqncBRrRsWk"
```

- [ ] **Step 4: ⛔ ประตูอนุมัติ (README)** · branch `feat/vendor-drone-sitl` เก็บไว้ให้เจ้าของ merge เอง
