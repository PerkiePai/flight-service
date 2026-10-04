# แก้ drone-sitl ที่อนุมัติแล้ว — 2026-10-05: `DRONE_SITL_DOCKER_RUN_ARGS` สำหรับ `docker run` ของ agent

- **หลักฐานฝั่ง drone-sitl:** `~/pai/drone-sitl/docs/changes/2026-10-05-docker-run-args.md` (commit `ed5f998` + เอกสารนี้)
- **อนุมัติโดย:** เจ้าของ flight-service, 2026-10-05 (`~/pai/flight-service/docs/design.md` หัวข้อ 8 และ 11 ข้อ 5)
- **ทำไม:** flight-service รัน image ของคนอื่นแบบอัตโนมัติ ต้องจำกัด memory/pids และตัด capability ของ container ได้ โดยพฤติกรรมเดิมของเว็บไม่เปลี่ยน
- **แก้อะไร:** `joystick-server.py` `AgentRun._spawn` อ่าน env `DRONE_SITL_DOCKER_RUN_ARGS` (`shlex.split`) ใส่ต่อหลัง `--gpus all` ก่อน `--name` · ไม่ตั้ง env = command line เดิมทุกตัว
- **ค่าที่ flight-service ส่ง:** `--memory 24g --memory-swap 24g --pids-limit 1024 --cap-drop ALL --security-opt no-new-privileges` (`flight_service/config.py` `DEFAULT_RUN_ARGS`)
- **เทสต์:** `streaming/tests/test_web_ui.py::test_agent_run_docker_appends_extra_run_args_from_env` (ใหม่ · เห็น FAIL ก่อนแก้ แล้ว PASS หลังแก้) · ทั้งชุด `pytest streaming/tests competition/tests examples/competition-submission` → **255 passed**
- **commit:** `ed5f998` บน `feat/website-usd-map-testgs` (ก่อนแก้ HEAD = `326290e`) · ยังไม่ push
- **ย้อนกลับ:** `git revert ed5f998` หรือไม่ตั้ง env (ผลเหมือนก่อนแก้)
- **ยังต้องยืนยันตอนบินจริง (flight-service Task 13):** `--cap-drop ALL` ไม่ทำให้ GPU/agent ใน container พัง

## diff

```diff
diff --git a/joystick-server.py b/joystick-server.py
index 7e11706..e3393de 100644
--- a/joystick-server.py
+++ b/joystick-server.py
@@ -20,6 +20,7 @@ import json
 import math
 import os
 import queue
+import shlex
 import shutil
 import subprocess
 import sys
@@ -557,8 +558,12 @@ class AgentRun:
             # box). shutil.which is what --gpus actually needs present.
             gpu_flags = (["--gpus", "all"]
                         if shutil.which("nvidia-container-runtime") else [])
+            # Extra `docker run` flags from whoever started this server --
+            # flight-service passes resource limits and --cap-drop ALL for
+            # images it pulled. Unset = exactly the old command line.
+            extra = shlex.split(os.environ.get("DRONE_SITL_DOCKER_RUN_ARGS", ""))
             self._proc = subprocess.Popen(
-                ["docker", "run", "--rm", "--network", "host", *gpu_flags,
+                ["docker", "run", "--rm", "--network", "host", *gpu_flags, *extra,
                  "--name", self._container_name, self.file],
                 cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                 text=True, bufsize=1)
```

---

# แก้ drone-sitl ครั้งที่ 2 — 2026-10-05: race ใน `sim/run-website.sh`

- **หลักฐานฝั่ง drone-sitl:** `~/pai/drone-sitl/docs/changes/2026-10-05-run-website-race.md` (commit `bda585c` โค้ด + เทสต์, ตามด้วยเอกสาร)
- **อนุมัติโดย:** เจ้าของ flight-service, 2026-10-05 (หลังขั้น 4)
- **อาการ:** ขั้น 4 รอบ 1 ครั้งแรก (`j-20261005-033711-4616`) ล้ม `sim_boot_timeout` ภายใน 70 ms เพราะ `run-website.sh` เช็ก process `bootstrap.py` ก่อน `launch-sitl.sh` จะ exec มัน แล้วคืนค่าทันที (docs/verification.md "ปัญหาที่เจอ" ข้อ 1)
- **แก้:** นับว่า Isaac ตายเฉพาะเมื่อผ่าน `ISAAC_START_GRACE_S` (default 30 s) แล้วไม่มี process
- **เทสต์ใหม่ใน drone-sitl:** `streaming/tests/test_run_website.py` (RED → GREEN) · ทั้งชุด 257 passed
- flight-service ไม่ต้องพึ่งการแก้นี้ (`c070270` รอ :8080 เองอยู่แล้ว)

---

# แก้ drone-sitl ครั้งที่ 3 — 2026-10-05: `DRONE_SITL_UPLOAD_TOKEN`

- **หลักฐานฝั่ง drone-sitl:** `~/pai/drone-sitl/docs/changes/2026-10-05-upload-token.md` (commit `205eaff` โค้ด + เทสต์, ตามด้วยเอกสาร)
- **อนุมัติโดย:** เจ้าของ flight-service, 2026-10-05: ให้เข้าได้แค่ทาง curl / ระบบพี่ต้น ไม่ใช้ร่วมกับหน้าเว็บ drone-sitl
- **แก้:** ตอนที่ flight-service เปิดเว็บ drone-sitl จะส่ง token ที่สุ่มใหม่ทุกครั้งที่ service เริ่ม (`Settings.sitl_upload_token`) · `/agent/upload`, `/agent/upload-docker`, `/agent/pull-docker` ตอบ `403` ถ้าไม่มี `X-Upload-Token` ที่ตรงกัน · flight-service แนบ header เองตอน pull / ส่ง bundle (`7f85902`)
- **ทดสอบจริง:** ยิง `:8090` ตรงระหว่างบิน → `403` ทั้ง 3 endpoint · pull และ bundle ของ flight-service ผ่าน

