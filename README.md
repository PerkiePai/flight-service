# flight-service

รับ docker image ของผู้แข่ง (ชื่อบน registry หรือไฟล์ `docker save` / build bundle) ด้วย curl ครั้งเดียว → บินใน sim (Isaac Sim + PX4 ผ่านสำเนา drone-sitl ใน `vendor/drone-sitl`) อัตโนมัติ → คืนสถานะ ข้อมูลการบิน คลิป MP4 และ detection score
ทำทีละ 1 งาน (+ ช่องรอ 1 งาน) · คิวหลักอยู่ที่ระบบของผู้เรียก · ทุกข้อมูลเขียนเป็น journal ทันทีที่ได้ จบทางไหน (รวม kill) ก็ได้ผลรูปแบบเดียว
ทุกงานบูต sim ใหม่และปิดเมื่อจบ ลบ image/container ที่งานนำเข้ามา แต่เก็บข้อมูลไว้ดูย้อนหลัง (≤ 10 GB)

เอกสารละเอียด: [docs/api.md](docs/api.md) (API + diagram) · [docs/design.md](docs/design.md) · [docs/verification.md](docs/verification.md) (ผลทดสอบจริง)

## ติดตั้ง (ครั้งแรก)

ต้องมี: conda env `drone` (`requirements-drone.txt`) · Docker + nvidia-container-toolkit · Isaac Sim 6 · PegasusSimulator + PX4-Autopilot (build `px4_sitl_default`) · ffmpeg — ตรวจทั้งหมดด้วย `./scripts/preflight.sh`

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
| `GET` | `/jobs/{id}/stream` | ติดตามสด (Server-Sent Events) |
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
curl -sN $R/jobs/j-20261005-033950-b5fa/stream -H "$H"          # หรือติดตามสด: event state / telemetry / end (docs/api.md)
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
- **รับงานได้ทาง API นี้เท่านั้น:** ตอนที่ service เปิดเว็บ drone-sitl (`:8090`) การอัปโหลด/pull ที่หน้าเว็บนั้นตรง ๆ ได้ `403` (ใช้ token ที่ service สุ่มใหม่ทุกครั้งที่เริ่ม)
- **ยังเสี่ยง:** container ใช้ `--network host` จึงเข้าถึง service อื่นบนเครื่องได้ (design 8) · ไม่มี TLS
- ถ้า service ถูกปิดกลางบิน คลิป MP4 ของงานนั้นอาจไม่มี (journal ครบ) · kill/timeout ระหว่าง pull: service หยุด `docker pull` ที่ค้างและลบสิ่งที่ pull มาให้ · `/ws` หลุดชั่วคราว: ต่อใหม่ภายใน 10 s แล้วติดตามการบินต่อ

## แก้ปัญหา

| อาการ | ทำ |
|---|---|
| งาน fail `sim_busy` | มี sim/เว็บค้าง: `vendor/drone-sitl/sim/stop-website.sh` แล้วส่งใหม่ |
| `/healthz` → `ok:false, phase:degraded` (POST ได้ 503) | cleanup ปิด sim ไม่ได้: รัน `vendor/drone-sitl/sim/stop-website.sh` เอง เช็ก `:8080`/`:8090` ว่าไม่ตอบ แล้ว `./scripts/stop-service.sh && ./scripts/run-service.sh` |
| `run-service.sh` บอก not answering | ดู `logs/service.console` (ไม่มี `.env` / token สั้นเกิน / port ถูกใช้) |
| งาน fail `sim_boot_timeout` / `px4_not_ready` | ดู `vendor/drone-sitl/logs/launch-sitl.console` · GPU ถูกใช้อยู่ไหม (`nvidia-smi`) |

## เทสต์

```bash
conda run -n drone python -m pytest -q          # ใช้ของปลอมทั้งหมด ไม่เปิด sim ~30 s
```
