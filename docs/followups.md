# งานค้าง (follow-ups) · 2026-10-05

ข้อเล็กที่ reviewer พบและยังไม่ได้แก้ (ทั้งหมดจัดเป็น Minor ตามผลกระทบ) · ข้อ Critical/Important แก้แล้วทั้งหมด (`234a650`, `5d368b6`)
รายละเอียดเต็มของแต่ละข้ออยู่ในรายงานรีวิว ส่วนที่นี่คือรายการสำหรับวางแผนต่อ

## ตัดสินใจแล้ว

- **drone-sitl `_safe_extract`** กันชื่อ `../` แต่ไม่กัน symlink/hardlink · ตัดสินใจ (2026-10-05): **ไม่แก้ตัวแตกไฟล์ แต่ปิดทางเข้าตรง** ตอน flight-service เปิดเว็บ drone-sitl การอัปโหลด/pull ที่ `:8090` ต้องมี token ของ flight-service (drone-sitl `205eaff`, flight-service `7f85902`) · **ยังเสี่ยงเฉพาะตอนเปิดเว็บ drone-sitl ด้วยมือ** (ไม่มี token) แล้วอัปโหลด bundle ที่ไม่น่าไว้ใจผ่านหน้าเว็บ

## ข้อเล็กที่ยังไม่แก้

- ~~cancelling/timing out a pull may leave the pulled image behind~~ **แก้แล้ว** (`2f598f9`, ทดสอบจริงด้วย pytorch 3 GB)
- ~~no /ws reconnect~~ **แก้แล้ว** (`e57553b`) ต่อใหม่ภายใน 10 s ตาม design 4
- run_job prologue (RUNNING touch, RunLog open) outside try — an OSError there leaves phase=running → every POST 409
- kill landing between create_task and run_job start: job marked killed then still runs — re-check QUEUED at top of run_job
- finalize/wait_clip raising leaves result=None and a RUNNING marker retention never deletes
- JSON body size checked after reading the whole body (token holders only)
- new_lines drops a line identical to a full 40-line identical window (panel.log loses repeats)
- telemetry.jsonl also stores docker_build.log + detrec every frame (~MBs/run)
- RUNNER_TOKEN inherited by drone-sitl processes (not by the agent container) — strip from env
- elapsed_s keeps growing after a terminal state
- flight_timeout_s 0 silently becomes 600 instead of 400
- MAX_PENDING=0 blocks every job — require >= 1
- run-service.sh waits only 20 s; startup recovery can take minutes
- sim_busy misses someone else's Isaac that is still booting (not yet answering :8080)
- pulling a mutable tag that already exists moves it and the new image is never removed
- malformed DRONE_SITL_DOCKER_RUN_ARGS makes shlex.split raise inside drone-sitl tick() → ws_lost; validate in Settings.from_env
- failed rmi results are ignored — record them in events.jsonl
- api.md reason list lacks web_start_failed, runner_degraded, unsupported_source
- test gaps — no API test against the real Worker; no kill during pulling/booting/finishing/cleanup; run_forever survival when run_job raises
### client สำเร็จรูป: `scripts/flight.py`

ไฟล์เดียว ใช้แค่ Python 3.8+ (ไม่ต้องติดตั้งอะไร) copy ไปเครื่องผู้เรียกได้เลย · ส่งงาน → ตามสดทาง stream → ดึงไฟล์ผล → บอกผลด้วย exit code

```bash
export FLIGHT_URL=http://127.0.0.1:8095 RUNNER_TOKEN=<token ใน .env ของ service>

scripts/flight.py health                                   # {"ok": true, "ready": true, ...}  exit 0 = ส่งงานได้
scripts/flight.py run perkiepai/truck-detector:20260929-214240 --timeout 600 --out results
scripts/flight.py run --file agent.tar --kind image --name my-agent      # ส่งไฟล์แทนชื่อ image (bundle: --kind bundle)
scripts/flight.py watch j-20261005-033950-b5fa --out results             # กลับมาตามงานเดิม เช่นหลัง client ถูกปิด
scripts/flight.py kill j-20261005-033950-b5fa
- M2 load-time disk check undercounts docker load peak (~3x) and is not re-checked when a queued upload starts
- M3 failure between receive and submit leaves a QUEUED job holding the slot (needs a restart)
- M4 drone-sitl keeps every bundle in logs/docker-agents forever; Dockerfile FROM can pull an untracked base image; a killed bundle build may tag later
- M5 drone-sitl test_run_website leaves its fake bootstrap sleep (8 s) running after the test
- M6 upload chunks are written synchronously on the event loop
- M7 no test for a client disconnect mid-upload releasing the slot
- ~~mock-caller.sh tracebacks on 409 instead of waiting for ready~~ ใช้ `scripts/flight.py` แทน (รอ `ready` และลองใหม่หลัง 409 เอง) · `mock-caller.sh` ลบได้เมื่อเจ้าของบอก
