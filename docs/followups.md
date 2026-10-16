# งานค้าง (follow-ups) · อัปเดต 2026-10-09

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
- JSON body size checked after reading the whole body (anyone who can reach the port)
- new_lines drops a line identical to a full 40-line identical window (panel.log loses repeats)
- telemetry.jsonl also stores docker_build.log + detrec every frame (~MBs/run)
- elapsed_s keeps growing after a terminal state
- flight_timeout_s 0 silently becomes 600 instead of 400
- MAX_PENDING=0 blocks every job — require >= 1
- run-service.sh waits only 20 s; startup recovery can take minutes
- sim_busy misses someone else's Isaac that is still booting (not yet answering :8080)
- pulling a mutable tag that already exists moves it and the new image is never removed
- malformed DRONE_SITL_DOCKER_RUN_ARGS makes shlex.split raise inside drone-sitl tick() → ws_lost; validate in Settings.from_env
- failed rmi results are ignored — record them in events.jsonl
- test gaps — no API test against the real Worker; no kill during pulling/booting/finishing/cleanup; run_forever survival when run_job raises
- `/healthz` ยังไม่บอกความพร้อมของเครื่อง (ฐานคือ `scripts/preflight.sh`) แยกไปทำทีหลัง (ตัดสินใจ 2026-10-06)
- sim ของโปรเจกต์อื่นเปิดทับระหว่างบิน: `~/friend/.../run_ardu_isaac.sh` ใช้ `kill -9` กับทุก Isaac streaming ฆ่า sim ของเรากลางบินได้ (รอบ 0 ของ vendor, `arming_timeout`) · `sim_busy` กันได้แค่ตอนเริ่มงาน · ต้องตกลงกับเจ้าของสคริปต์หรือแยกเครื่อง

## ข้อเล็กอื่น (M2–M7 จาก review ส่วน B)

- M2 load-time disk check undercounts docker load peak (~3x) and is not re-checked when a queued upload starts
- M3 failure between receive and submit leaves a QUEUED job holding the slot (needs a restart)
- M4 drone-sitl keeps every bundle in logs/docker-agents forever; Dockerfile FROM can pull an untracked base image; a killed bundle build may tag later
- M5 drone-sitl test_run_website leaves its fake bootstrap sleep (8 s) running after the test
- M6 upload chunks are written synchronously on the event loop
- M7 no test for a client disconnect mid-upload releasing the slot
- ~~mock-caller.sh tracebacks on 409 instead of waiting for ready~~ ใช้ `scripts/flight.py` แทน (รอ `ready` และลองใหม่หลัง 409 เอง) · `mock-caller.sh` ลบได้เมื่อเจ้าของบอก
