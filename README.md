# flight-service

รับ docker image ของผู้แข่ง (ชื่อบน registry หรือไฟล์ `docker save` / build bundle) ด้วย curl ครั้งเดียว → บินใน sim (Isaac Sim + PX4 ผ่าน `~/pai/drone-sitl`) อัตโนมัติ → คืนสถานะ ข้อมูลการบิน คลิป MP4 และ detection score
ทำทีละ 1 งาน (+ ช่องรอ 1 งาน) · คิวหลักอยู่ที่ระบบของผู้เรียก · ทุกข้อมูลเขียนเป็น journal ทันทีที่ได้ จบทางไหน (รวม kill) ก็ได้ผลรูปแบบเดียว
ทุกงานบูต sim ใหม่และปิดเมื่อจบ ลบ image/container ที่งานนำเข้ามา แต่เก็บข้อมูลไว้ดูย้อนหลัง (≤ 10 GB)

เอกสารละเอียด: [docs/api.md](docs/api.md) (API + diagram) · [docs/design.md](docs/design.md) · [docs/verification.md](docs/verification.md) (ผลทดสอบจริง)

## ติดตั้ง (ครั้งแรก)

ต้องมี: conda env `drone` (FastAPI, uvicorn, websockets — env เดียวกับ drone-sitl) · Docker · `~/pai/drone-sitl` ที่รัน `sim/run-website.sh` ได้

```bash
cd ~/pai/flight-service
cp .env.example .env
sed -i "s/^RUNNER_TOKEN=.*/RUNNER_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')/" .env
chmod 600 .env
```

ค่าใน `.env` ที่ใช้บ่อย (ดูทั้งหมดใน `flight_service/config.py`):

| ค่า | default | ความหมาย |
|---|---|---|
| `RUNNER_TOKEN` | — (ต้องตั้ง ≥ 32 ตัว) | Bearer token ของทุก endpoint ยกเว้น `/healthz` |
| `RUNNER_HOST` / `RUNNER_PORT` | `127.0.0.1` / `8095` | เปิดให้เครื่องอื่นเรียก: ตั้ง host เป็น IP ของเครื่อง (ควรอยู่หลัง VPN/reverse proxy เพราะไม่มี TLS) |
| `ALLOWED_IMAGES` | `^(docker\.io/)?perkiepai/...` | regex ของ image ที่ยอมให้ pull (คั่นด้วยช่องว่าง) |
| `DATA_RETENTION_GB` | `10` | เก็บข้อมูลย้อนหลังรวมไม่เกินนี้ (ลบงานเก่าสุดก่อน · `0` = ไม่ลบ) |
| `MAX_PENDING` | `1` | งานที่รอได้ต่อจากงานที่กำลังทำ |
| `DEFAULT_FLIGHT_S` / `MAX_FLIGHT_S` | `600` / `900` | เวลาบินสูงสุดต่องาน |
| `KEEP_IMAGE` | `0` | `1` = ไม่ลบ image หลังจบ (ใช้ตอน debug) |

## เปิด / ปิด

```bash
./scripts/run-service.sh      # เปิดเบื้องหลัง · pid → run/service.pid · log → logs/service.console
./scripts/stop-service.sh     # ปิดด้วย pid (SIGTERM)
```

- ปิดระหว่างมีงานบินอยู่ได้ งานนั้นจะไม่ถูกนับเป็น kill ตอนเปิดใหม่ service จะสร้างผลจาก journal ให้ (`failed / runner_restarted`, `partial: true`) และปิด sim ที่ค้างไว้
- service ไม่ยุ่งกับ sim ที่คนอื่นเปิดค้างไว้ ถ้ามีงานเข้ามาตอนนั้นจะ fail เป็น `sim_busy`

## เรียก API

```bash
export R=http://127.0.0.1:8095 H="Authorization: Bearer $RUNNER_TOKEN"
```

| method | path | หน้าที่ |
|---|---|---|
| `GET` | `/healthz` | รับงานได้ไหม (ไม่ต้องใช้ token) |
| `POST` | `/jobs` | เริ่มงาน |
| `GET` | `/jobs` | ประวัติงาน 50 งานล่าสุด |
| `GET` | `/jobs/{id}` | สถานะ + ข้อมูลสด + ผล |
| `POST` | `/jobs/{id}/kill` | หยุดงาน แล้วตอบด้วยข้อมูลที่เก็บได้ |
| `GET` | `/jobs/{id}/files/{name}` | ดาวน์โหลดไฟล์ผล |

```bash
curl -s $R/healthz
# {"ok":true,"ready":true,"phase":"idle","pending":0}     ready = POST ตอนนี้จะถูกรับ

curl -s -X POST $R/jobs -H "$H" -H 'Content-Type: application/json' \
     -d '{"image":"perkiepai/truck-detector:20260929-214240","flight_timeout_s":600}'
# 202 {"job_id":"j-20261005-033950-b5fa","state":"queued","source":"registry"}
# 409 {"detail":"busy","current_job":"...","pending":["..."]}   ช่องรอเต็ม → เก็บไว้ในคิวของคุณ รอ ready แล้วส่งใหม่
# 503 {"detail":"degraded"}                                      ต้องมีคนแก้ (ดูหัวข้อแก้ปัญหา)

curl -s $R/jobs/j-20261005-033950-b5fa -H "$H"                  # poll ทุก 1–5 s
curl -s -X POST $R/jobs/j-20261005-033950-b5fa/kill -H "$H"     # 200 = จบแล้วพร้อมผล · 202 = ยังเก็บกวาดอยู่ ให้ poll ต่อ
curl -s -o clip.mp4 $R/jobs/j-20261005-033950-b5fa/files/detections.mp4 -H "$H"
```

### ส่งไฟล์ image แทนชื่อ image

endpoint เดียวกัน (`POST /jobs`) ส่งเป็นไฟล์ด้วย `curl -T` (stream ไม่โหลดเข้า RAM · ห้ามใช้ `--data-binary`) พร้อม `?kind=&name=`

```bash
# ผลของ docker save (.tar หรือ .tar.gz) · ≤ 16 GB · ชื่อ image ในไฟล์ต้องยังไม่มีบนเครื่อง
docker save my-agent:1 -o agent.tar
curl -s -X POST -T agent.tar -H "$H" "$R/jobs?kind=image&name=my-agent&flight_timeout_s=600"

# build bundle: tar ที่มี Dockerfile (FROM competition-base) + โค้ด · ≤ 200 MB · ไฟล์ธรรมดาเท่านั้น (ไม่มี symlink)
curl -s -X POST -T bundle.tar -H "$H" "$R/jobs?kind=bundle&name=my-agent"
```

ไม่ผ่าน: `409` ช่องรอเต็ม (ไม่รับไฟล์) · `411` ไม่มี Content-Length · `413` ใหญ่เกิน · `507` ดิสก์ไม่พอ · `408` ไม่มีข้อมูลเข้ามา 60 s · ไฟล์ผิดรูปแบบ/ชื่อชน/มี link → งาน `failed` ด้วย `archive_rejected`

ทดลองครบวงจรด้วยสคริปต์ที่ทำตัวเป็นผู้เรียก: `./scripts/mock-caller.sh <image> [flight_timeout_s]` (ผลอยู่ใน `mock-out/<job_id>/` · `KILL_AFTER_S=90` = kill หลังบิน 90 s)

### state ของงาน

`queued` → `pulling` (หรือ `loading` เมื่อส่งไฟล์) → `booting` → `flying` → `done` · ผิดพลาด → `failed` (มี `failed_in`, `reason`, `detail`) · สั่งหยุด → `killed`
**state จบ (`done`/`failed`/`killed`) = finalize + cleanup เสร็จแล้ว** ส่งงานถัดไปได้ทันที

| reason | ความหมาย |
|---|---|
| `pull_failed` · `disk_low` · `image_too_large` | ดึง image ไม่ได้ / ดิสก์ไม่พอ / image ใหญ่เกิน 16 GB |
| `archive_rejected` · `load_failed` | ไฟล์ที่ส่งมาไม่ปลอดภัยหรือชื่อชน / `docker load` หรือ build ล้ม |
| `sim_busy` | มี sim หรือเว็บที่ service ไม่ได้เปิดเองรันอยู่ |
| `web_start_failed` · `sim_boot_timeout` · `px4_not_ready` | เปิดเว็บ drone-sitl ไม่ได้ / Isaac ไม่ขึ้นใน 420 s / PX4 ไม่พร้อมใน 180 s |
| `run_refused` · `arming_timeout` | agent ไม่เริ่ม / ค้างที่ arming เกิน 90 s |
| `agent_crashed` · `flight_timeout` · `ws_lost` | agent ตาย / บินเกินเวลา / ขาดการติดต่อกับ drone-sitl |
| `runner_restarted` · `runner_degraded` · `unsupported_source` · `internal_error` | service ถูกปิดกลางงาน / service อยู่ในสถานะ degraded / ชนิดงานที่ไม่รองรับ / บั๊กของ service |

### ผลที่ได้

ระหว่างบิน `GET /jobs/{id}` มี `telemetry` ล่าสุด (lat, lon, alt_m, heading, roll, pitch, gs, vz, mode, armed), `log_tail` 20 บรรทัด และ `score_live` · ตอนจบมี `result`:

```json
{"ended_by":"agent","partial":false,"outcome":"done","flight_s":484.8,"distance_m":556.2,"max_alt_m":40.6,
 "score":{"version":"v0","score":95.6,"recall":1.0,"precision":0.916,"trucks_found":3,"trucks_total":3},
 "files":{"track.jsonl":"/jobs/<id>/files/track.jsonl","detections.mp4":"...","...":"..."},"missing":[]}
```

| ไฟล์ | เนื้อหา | ได้เมื่อ |
|---|---|---|
| `telemetry.jsonl` | ทุกเฟรม 5 Hz ทุกฟิลด์จาก PX4 | ระหว่างบิน (โตขึ้นเรื่อย ๆ) |
| `events.jsonl` | state ของงาน/agent + log ของ agent ทุกบรรทัด | ระหว่างบิน |
| `detections.jsonl` | กล่อง detection + ตำแหน่งโดรน | ระหว่างบิน |
| `track.jsonl` · `panel.log` | track แบบย่อ · log ของ agent | ตอนจบ |
| `detections.mp4` · `meta.json` | คลิปกล้องของ agent พร้อมกล่อง | ตอนจบ |
| `score.json` · `result.json` · `analysis.txt` | score v0 ละเอียด · ผลสรุป · ผลตรวจเทียบรถจริง | ตอนจบ |

`partial: true` = งานไม่ได้จบเอง (kill, timeout, error, runner restart) · score v0 = 100 × F1 ของ "เจอรถจริงกี่คัน" กับ "กล่องที่ขึ้นตอนอยู่ใกล้รถจริง" (design 9.1)

## ข้อมูลย้อนหลัง

`data/runs/<job_id>/` เก็บทุกไฟล์ข้างบน + `job.json` · เปิดดูผ่าน `GET /jobs` และ `/files/*` · เกิน `DATA_RETENTION_GB` จะลบงานที่จบแล้วเก่าสุดก่อน (ไม่แตะงานที่ยังไม่จบ)

## ความปลอดภัยและข้อจำกัด

- token ทุก endpoint ยกเว้น `/healthz` · allowlist ของ image · จำกัดเวลาบิน · จำกัดขนาด image 16 GB และดิสก์ว่าง ≥ 40 GB
- container ของผู้แข่งรันด้วย `--memory 24g --pids-limit 1024 --cap-drop ALL --security-opt no-new-privileges` (ผ่าน `DRONE_SITL_DOCKER_RUN_ARGS` ของ drone-sitl)
- **ยังเสี่ยง:** container ใช้ `--network host` จึงเข้าถึง service อื่นบนเครื่องได้ (design 8) · ไม่มี TLS
- ถ้า service ถูกปิดกลางบิน คลิป MP4 ของงานนั้นอาจไม่มี (journal ครบ) · kill ระหว่าง pull อาจทิ้ง image ไว้บนดิสก์

## แก้ปัญหา

| อาการ | ทำ |
|---|---|
| งาน fail `sim_busy` | มี sim/เว็บค้าง: `cd ~/pai/drone-sitl && ./sim/stop-website.sh` แล้วส่งใหม่ |
| `/healthz` → `ok:false, phase:degraded` (POST ได้ 503) | cleanup ปิด sim ไม่ได้: รัน `~/pai/drone-sitl/sim/stop-website.sh` เอง เช็ก `:8080`/`:8090` ว่าไม่ตอบ แล้ว `./scripts/stop-service.sh && ./scripts/run-service.sh` |
| `run-service.sh` บอก not answering | ดู `logs/service.console` (ไม่มี `.env` / token สั้นเกิน / port ถูกใช้) |
| งาน fail `sim_boot_timeout` / `px4_not_ready` | ดู `~/pai/drone-sitl/logs/launch-sitl.console` · GPU ถูกใช้อยู่ไหม (`nvidia-smi`) |

## เทสต์

```bash
conda run -n drone python -m pytest -q          # ใช้ของปลอมทั้งหมด ไม่เปิด sim ~30 s
```
