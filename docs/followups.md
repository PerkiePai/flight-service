# งานค้าง (follow-ups) · 2026-10-05

ข้อเล็กที่ reviewer พบและยังไม่ได้แก้ (ทั้งหมดจัดเป็น Minor ตามผลกระทบ) · ข้อ Critical/Important แก้แล้วทั้งหมด (`234a650`, `5d368b6`)
รายละเอียดเต็มของแต่ละข้ออยู่ในรายงานรีวิว ส่วนที่นี่คือรายการสำหรับวางแผนต่อ

## รอการตัดสินใจ

- **drone-sitl `_safe_extract`** (`streaming/docker_build.py`) กันชื่อ `../` แต่ไม่กัน symlink/hardlink → ใครอัปโหลด bundle ผ่านเว็บ drone-sitl ตรง ๆ ยังเขียนไฟล์นอกโฟลเดอร์ build ได้ · flight-service ตรวจ bundle เองก่อนส่งแล้ว (ทางของเราปลอดภัย) · ทางแก้ต้นทาง: `tar.extractall(dest, filter="data")` — **ต้องขออนุมัติแก้ drone-sitl**

## ข้อเล็กที่ยังไม่แก้

- cancelling/timing out a pull may leave the pulled image behind (no image_tag yet) — check in Task 13 by killing during a pull
- no /ws reconnect; design 4 says ws_lost = could not reconnect within 10 s — one dropped socket ends the job (localhost, rare)
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
- mock-caller.sh tracebacks on 409 instead of waiting for ready
- M2 load-time disk check undercounts docker load peak (~3x) and is not re-checked when a queued upload starts
- M3 failure between receive and submit leaves a QUEUED job holding the slot (needs a restart)
- M4 drone-sitl keeps every bundle in logs/docker-agents forever; Dockerfile FROM can pull an untracked base image; a killed bundle build may tag later
- M5 drone-sitl test_run_website leaves its fake bootstrap sleep (8 s) running after the test
- M6 upload chunks are written synchronously on the event loop
- M7 no test for a client disconnect mid-upload releasing the slot
