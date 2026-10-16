# submission-run.compose.yml เทียบกับที่ flight-service รันจริง

ไฟล์อ้างอิง: [`submission-run.compose.yml`](submission-run.compose.yml) (ไม่ได้ถูกใช้โดยโค้ด)
เทียบกับ `docker inspect` ของ container จริง `submission-run-20261006-112754` (2026-10-06)
ที่ service เปิดผ่าน `AgentRun` ของ drone-sitl + `DRONE_SITL_DOCKER_RUN_ARGS` (`flight_service/config.py`)

| ใน compose | ของจริง | หมายเหตุ |
|---|---|---|
| `entrypoint python agent_runner.py --file full_flight_agent.py` | ตรง | อยู่ใน image (`Config.Entrypoint`) |
| `working_dir /competition` | ตรง | อยู่ใน image (`Config.WorkingDir`) |
| `network_mode host` | ตรง | |
| `memory 24G` | ตรง (`25769803776`) | |
| `no-new-privileges` | ตรง | |
| GPU ทุกตัว | ตรง (`Count -1`) | |
| `shm_size 64m` | ตรง (`ShmSize 67108864`) | เป็นค่า default ของ docker ไม่ต้องใส่ flag |
| `TZ=Asia/Bangkok` | ✅ เพิ่มแล้ว (`-e TZ=Asia/Bangkok` ใน `DEFAULT_RUN_ARGS`) | ก่อนหน้านี้ไม่มีใน `Env` ของ container |
| volume `/home/droneuser/sim:/competition/sim` | **ไม่มี** (`Binds null`, `Mounts []`) | ไม่มีโฟลเดอร์นี้ใน image และ agent ไม่เขียนไฟล์เอง — ไม่จำเป็น |
| `container_name drone-sim` | ✅ ตรงแล้ว (vendor patch `0002`, 2026-10-16) | ก่อนหน้านี้ชื่อ `submission-run-<เวลา>` (drone-sitl ตั้ง) |
| — | `--cap-drop ALL`, `--pids-limit 1024`, `--memory-swap 24g` | เรามีเพิ่ม compose ไม่มี |
| — | `AutoRemove true` | container ถูกลบเองตอนจบ |

## ข้อมูลไม่หายตอนลบ container

agent ไม่เขียนไฟล์ ผลทั้งหมดเกิดฝั่ง service/sim แล้วเก็บบน host ที่ `data/runs/<job>/`
(`detections.mp4`, `telemetry.jsonl`, `score.json`, `result.json`, `panel.log` ฯลฯ)
และสำเนาฝั่ง client ที่ `results/<job>/` — จึงไม่ต้องใช้ volume
ข้อควรระวัง: retention (เพดาน 10 GB) ลบ `data/runs/` เก่าได้ → ดู `wishlist.md` ข้อ 4
