# flight-service

รับ docker image ของผู้แข่ง (ชื่อบน registry หรือไฟล์ `docker save` / build bundle) ด้วย curl ครั้งเดียว → บินใน sim (Isaac Sim + PX4 ผ่านสำเนา drone-sitl ใน `vendor/drone-sitl`) อัตโนมัติ → คืนสถานะ ข้อมูลการบิน คลิป MP4 และ detection score
ทำทีละ 1 งาน (+ ช่องรอ 1 งาน) · คิวหลักอยู่ที่ระบบของผู้เรียก · ทุกข้อมูลเขียนเป็น journal ทันทีที่ได้ จบทางไหน (รวม kill) ก็ได้ผลรูปแบบเดียว
ทุกงานบูต sim ใหม่และปิดเมื่อจบ ลบ image/container ที่งานนำเข้ามา แต่เก็บข้อมูลไว้ดูย้อนหลัง (≤ 10 GB)

เอกสารละเอียด: [docs/design.md](docs/design.md) (design + API + diagram) · [docs/progress.md](docs/progress.md) · งานค้าง: [docs/followups.md](docs/followups.md) · log การรันจริง: [docs/evidence/](docs/evidence/) · compose ของ submission เทียบกับของจริง: [docs/reference/](docs/reference/) · แผนและสเปกเก่าที่ทำเสร็จแล้ว: [docs/archive/](docs/archive/)

**หัวข้อ**

- [ติดตั้ง (ครั้งแรก)](#ติดตั้ง-ครั้งแรก)
  - [ย้ายไปเครื่องใหม่](#ย้ายไปเครื่องใหม่)
- [เปิด / ปิด](#เปิด--ปิด)
- [เรียก API](#เรียก-api)
  - [1. เช็กว่าส่งงานได้ไหม](#1-เช็กว่าส่งงานได้ไหม)
  - [2. ส่งงานจากชื่อ image (registry)](#2-ส่งงานจากชื่อ-image-registry)
  - [3. ส่งไฟล์ image แทนชื่อ image](#3-ส่งไฟล์-image-แทนชื่อ-image)
  - [4. ดูสถานะ / กลับมาตามงานเดิม](#4-ดูสถานะ--กลับมาตามงานเดิม)
  - [5. ติดตามสด (Server-Sent Events)](#5-ติดตามสด-server-sent-events)
  - [6. หยุดงาน (kill)](#6-หยุดงาน-kill)
  - [7. โหลดไฟล์ผล](#7-โหลดไฟล์ผล)
  - [รายละเอียดของ `scripts/flight.py`](#รายละเอียดของ-scriptsflightpy)
  - [state ของงาน](#state-ของงาน)
  - [ผลที่ได้](#ผลที่ได้)
- [ข้อมูลย้อนหลัง](#ข้อมูลย้อนหลัง)
- [ความปลอดภัยและข้อจำกัด](#ความปลอดภัยและข้อจำกัด)
- [แก้ปัญหา](#แก้ปัญหา)
- [เทสต์](#เทสต์)

## ติดตั้ง (ครั้งแรก)

ต้องมี: conda env `drone` (`requirements-drone.txt`) · Docker + nvidia-container-toolkit · Isaac Sim 6 · PegasusSimulator + PX4-Autopilot (build `px4_sitl_default`) · ffmpeg — ตรวจทั้งหมดด้วย `./scripts/preflight.sh`

```bash
cd ~/pai/flight-service
cp .env.example .env
```

ค่าใน `.env` ที่ใช้บ่อย (ดูทั้งหมดใน `flight_service/config.py`):

| ค่า | default | ความหมาย |
|---|---|---|
| `RUNNER_HOST` / `RUNNER_PORT` | `127.0.0.1` / `8095` | **service ไม่มี login** ใครถึง port ได้ก็สั่งบินและอัปโหลดไฟล์ได้ จึงคง `127.0.0.1` ไว้ · เปิดให้เครื่องอื่นเรียก: ตั้ง host เป็น IP ของเครื่อง (ควรอยู่หลัง VPN/reverse proxy เพราะไม่มี TLS และไม่มี login) |
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
4. `cp .env.example .env` (แก้ path ข้างบนถ้าไม่ตรง default)
5. `./scripts/preflight.sh` จนขึ้น `preflight: ready` (ทุกข้อที่ไม่ผ่านมีบรรทัด `fix:` บอกวิธี)
6. `./scripts/run-service.sh` แล้วลองด้วย `./scripts/flight.py run <image>` (ดูหัวข้อ client)

## เปิด / ปิด

```bash
./scripts/run-service.sh      # เปิดเบื้องหลัง · pid → run/service.pid · log → logs/service.console
./scripts/stop-service.sh     # ปิดด้วย pid (SIGTERM)
```

- ปิดระหว่างมีงานบินอยู่ได้ งานนั้นจะไม่ถูกนับเป็น kill ตอนเปิดใหม่ service จะสร้างผลจาก journal ให้ (`failed / runner_restarted`, `partial: true`) และปิด sim ที่ค้างไว้
- service ไม่ยุ่งกับ sim ที่คนอื่นเปิดค้างไว้ ถ้ามีงานเข้ามาตอนนั้นจะ fail เป็น `sim_busy`

## เรียก API

ตัวอย่างทั้งหมดเรียกที่ `http://192.168.20.141:8095` (ต้องตั้ง `RUNNER_HOST` ให้ service ฟังที่ IP นี้ ดูหัวข้อติดตั้ง · เรียกจากเครื่องเดียวกับ service ใช้ `127.0.0.1` แทนได้) · copy ไปวางได้เลย

| method | path | หน้าที่ |
|---|---|---|
| `GET` | `/healthz` | รับงานได้ไหม |
| `POST` | `/jobs` | เริ่มงาน |
| `GET` | `/jobs` | ประวัติงาน 50 งานล่าสุด |
| `GET` | `/jobs/{id}` | สถานะ + ข้อมูลสด + ผล |
| `GET` | `/jobs/{id}/stream` | ติดตามสด (Server-Sent Events) |
| `POST` | `/jobs/{id}/kill` | หยุดงาน แล้วตอบด้วยข้อมูลที่เก็บได้ |
| `POST` | `/kill` | เหมือนข้างบนแต่ไม่ต้องระบุ id: หยุดงานที่กำลังบิน (ไม่มี → งานที่รอคิวถัดไป · ไม่มีเลย → `409`) ไม่แตะงานอื่นในคิว |
| `GET` | `/jobs/{id}/files/{name}` | ดาวน์โหลดไฟล์ผล |

เรียกได้ 2 วิธี ผลเหมือนกัน: **curl** ยิงทีละ endpoint ตรง ๆ · **`scripts/flight.py`** (ไฟล์เดียว ใช้แค่ Python 3.8+ copy ไปเครื่องผู้เรียกได้เลย) ทำหลายขั้นให้ในคำสั่งเดียว ด้านล่างเขียนคู่กันทีละงาน พร้อมผลตอนสำเร็จ (ผลจริงจากงาน `j-20261006-083909-c92b` · `...` = ย่อบรรทัดที่ยาว)

### 1. เช็กว่าส่งงานได้ไหม

| curl | flight.py |
|---|---|
| `curl http://192.168.20.141:8095/healthz` | `scripts/flight.py health` |

```
{"ok":true,"ready":true,"phase":"idle","pending":0}        ← curl      ready = POST ตอนนี้จะถูกรับ
{"ok": true, "ready": true, "phase": "idle", "pending": 0}  ← flight.py  exit 0 = ส่งงานได้
```

### 2. ส่งงานจากชื่อ image (registry)

**curl**: ส่งงานอย่างเดียว ได้ `job_id` กลับมา ที่เหลือ (ตามผล, โหลดไฟล์) ต้องยิงเองตามข้อ 3–6

```bash
curl -X POST http://192.168.20.141:8095/jobs -H 'Content-Type: application/json' \
     -d '{"image":"perkiepai/truck-detector:20260929-214240","flight_timeout_s":600}'
```
```
202 {"job_id":"j-20261006-083909-c92b","state":"queued","source":"registry"}
409 {"detail":"busy","current_job":"...","pending":["..."]}   ช่องรอเต็ม → เก็บไว้ในคิวของคุณ รอ ready แล้วส่งใหม่
503 {"detail":"degraded"}                                      ต้องมีคนแก้ (ดูหัวข้อแก้ปัญหา)
```

**flight.py**: รอ `ready` → ส่งงาน → ตามสดจนจบ → โหลดไฟล์ผลลง `flight-out/<job_id>/` ในคำสั่งเดียว (เปลี่ยนที่เก็บด้วย `--out DIR`)

```bash
scripts/flight.py run perkiepai/truck-detector:20260929-214240 --timeout 600
```
ความคืบหน้าออกทาง stderr:
```
08:39:09 job j-20261006-083909-c92b accepted
08:39:09 state pulling
08:39:16 state booting
08:39:49 state flying
08:39:49 flying alt=0.0 lat=14.0283445 lon=100.4364646 mode=AUTO.LOITER agent=idle
08:40:04 flying alt=4.4 lat=14.0283442 lon=100.4364649 mode=OFFBOARD agent=running
...
08:48:03 state done
08:48:03 done; score 97.0; flew 487.46s; files in flight-out/j-20261006-083909-c92b
```
stdout บรรทัดเดียวเป็น JSON ให้โปรแกรมอ่าน · exit code `0` = `done`:
```
{"job_id": "j-20261006-083909-c92b", "state": "done", "reason": null, "score": 97.0, "out_dir": "flight-out/j-20261006-083909-c92b", "not_downloaded": []}
```

### 3. ส่งไฟล์ image แทนชื่อ image

endpoint เดียวกับข้อ 2 (`POST /jobs`) ส่งเป็นไฟล์ด้วย `curl -T` (stream ไม่โหลดเข้า RAM · ห้ามใช้ `--data-binary`) พร้อม `?kind=&name=` · ผลเมื่อรับแล้วเหมือนข้อ 2 (`202`, `"source":"upload"`)

| curl | flight.py |
|---|---|
| `curl -X POST -T agent.tar "http://192.168.20.141:8095/jobs?kind=image&name=my-agent&flight_timeout_s=600"` | `scripts/flight.py run --file agent.tar --kind image --name my-agent --timeout 600` |
| `curl -X POST -T bundle.tar "http://192.168.20.141:8095/jobs?kind=bundle&name=my-agent"` | `scripts/flight.py run --file bundle.tar --kind bundle --name my-agent` |

- `kind=image`: ผลของ `docker save my-agent:1 -o agent.tar` (`.tar` หรือ `.tar.gz`) · ≤ 16 GB · ชื่อ image ในไฟล์ต้องยังไม่มีบนเครื่อง
- `kind=bundle`: tar ที่มี `Dockerfile` (FROM competition-base) + โค้ด · ≤ 200 MB · ไฟล์ธรรมดาเท่านั้น (ไม่มี symlink)
- ไม่ผ่าน: `409` ช่องรอเต็ม (ไม่รับไฟล์) · `411` ไม่มี Content-Length · `413` ใหญ่เกิน · `507` ดิสก์ไม่พอ · `408` ไม่มีข้อมูลเข้ามา 60 s · ไฟล์ผิดรูปแบบ/ชื่อชน/มี link → งาน `failed` ด้วย `archive_rejected`

### 4. ดูสถานะ / กลับมาตามงานเดิม

| curl | flight.py |
|---|---|
| `curl http://192.168.20.141:8095/jobs/j-20261006-083909-c92b` (poll ทุก 1–5 s) | `scripts/flight.py watch j-20261006-083909-c92b` |

curl ตอบ JSON ครั้งเดียว (ย่อ):
```
{"job_id":"j-20261006-083909-c92b","state":"done","source":"registry","image":"perkiepai/truck-detector:20260929-214240",
 "created_at":"2026-10-06T08:39:09+0700","state_since":"2026-10-06T08:48:03+0700","failed_in":null,"reason":null,
 "detail":"DONE logged; runner stopped the agent","score_live":{"rows":1263,"trucks_found":3,"trucks_total":3},
 "result":{"ended_by":"agent","partial":false,"outcome":"done","flight_s":487.46,"distance_m":560.2,"max_alt_m":40.2,
          "score":{"version":"v0","score":97.0,"recall":1.0,"precision":0.941,"trucks_found":3,"trucks_total":3},"files":{...},"missing":[]},...}
```
flight.py ตามงานต่อ (งานที่ยังบินอยู่จะเห็นบรรทัดความคืบหน้าต่อเนื่องเหมือนข้อ 2) แล้วโหลดไฟล์ให้ ถ้างานจบแล้วได้ทันที:
```
13:34:16 state done
13:34:16 done; score 97.0; flew 487.46s; files in flight-out/j-20261006-083909-c92b
{"job_id": "j-20261006-083909-c92b", "state": "done", "reason": null, "score": 97.0, "out_dir": "flight-out/j-20261006-083909-c92b", "not_downloaded": []}
```

### 5. ติดตามสด (Server-Sent Events)

**curl**: `curl -N http://192.168.20.141:8095/jobs/j-20261006-083909-c92b/stream` · ต่อใหม่หลังสายขาด: เพิ่ม `-H 'Last-Event-ID: <เลขบรรทัดล่าสุดที่ได้>'`
**flight.py**: ไม่มีคำสั่งแยก `run` และ `watch` ใช้ stream นี้เอง ต่อใหม่จากบรรทัดล่าสุดเอง และเปลี่ยนไป poll เมื่อ stream ใช้ไม่ได้

```
event: state
data: {"state":"done","since":"2026-10-06T08:48:03+0700","reason":null}

id: 1
event: telemetry
data: {"connected":true,"armed":false,"mode":"AUTO.LOITER","alt_m":0.0071,"lat":14.0283445,"lon":100.4364646,...}

...                                                   (หนึ่ง event ต่อหนึ่งบรรทัดของ telemetry.jsonl · 5 Hz)

event: end
data: {"job_id":"j-20261006-083909-c92b","state":"done","failed_in":null,"reason":null,"detail":"DONE logged; runner stopped the agent","result":{...}}
```
(ตอนงานยังบินอยู่ event แรกคือ `"state":"flying"` · server ปิดสายหลัง `end`)

### 6. หยุดงาน (kill)

| curl | flight.py |
|---|---|
| `curl -X POST http://192.168.20.141:8095/kill` (งานที่กำลังบิน · ไม่ต้องรู้ id) | `scripts/flight.py kill` |
| `curl -X POST http://192.168.20.141:8095/jobs/j-20261006-083909-c92b/kill` | `scripts/flight.py kill j-20261006-083909-c92b` |

`200` = จบแล้วพร้อมผล · `202` = ยังเก็บกวาดอยู่ ให้ poll ต่อ · `409` = ไม่มีงานให้หยุด / งานจบไปแล้ว

curl ตอบงานทั้งก้อน (ย่อ · ตัวอย่างจริงตอน kill ระหว่างบิน):
```
{"state":"killed","failed_in":"flying","reason":"killed","detail":"killed while flying",
 "result":{"ended_by":"kill","partial":true,"flight_s":91.6,"distance_m":25.5,"score":{"version":"v0","score":79.8,...},"missing":[]},...}
```
flight.py พิมพ์บรรทัดเดียว: `{"job_id": "<id>", "state": "killed", "reason": "killed"}`

### 7. โหลดไฟล์ผล

| curl | flight.py |
|---|---|
| `curl -o clip.mp4 http://192.168.20.141:8095/jobs/j-20261006-083909-c92b/files/detections.mp4` (ทีละไฟล์) | ไม่ต้องทำ: `run` / `watch` โหลดให้ทุกไฟล์ |

หลัง `run` / `watch` สำเร็จ `ls flight-out/j-20261006-083909-c92b`:
```
analysis.txt  detections.jsonl  detections.mp4  events.jsonl  job.json  meta.json  panel.log  result.json  score.json  telemetry.jsonl  track.jsonl
```
งานที่ยังบินอยู่ดึงได้เฉพาะ journal (`telemetry.jsonl`, `events.jsonl`, `detections.jsonl`) ที่เหลือมีหลังจบ · รายละเอียดไฟล์ดูหัวข้อ "ผลที่ได้"

### รายละเอียดของ `scripts/flight.py`

```bash
export FLIGHT_URL=http://192.168.20.141:8095     # ถ้าไม่ตั้ง ใช้ http://127.0.0.1:8095 (เรียกจากเครื่องเดียวกับ service) · หรือส่ง --url ต่อคำสั่ง
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

`scripts/mock-caller.sh` (สคริปต์ทดสอบรุ่นแรก ใช้ poll · `flight.py` ใช้แทนได้ทั้งหมด เก็บไว้จนกว่าเจ้าของบอกให้ลบ) ยังอยู่: `./scripts/mock-caller.sh <image> [flight_timeout_s]` ผลอยู่ใน `mock-out/<job_id>/`

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

`partial: true` = งานไม่ได้จบเอง (kill, timeout, error, runner restart) · score v0 = 100 × F1 ของ "เจอรถจริงกี่คัน" กับ "กล่องที่ขึ้นตอนอยู่ใกล้รถจริง" (docs/design.md หัวข้อ 5)

## สเปกโดรน

ตั้งครั้งเดียวใน `.env` ใช้กับ**ทุกงาน** (ยังเลือกเป็นรายงานไม่ได้) แล้ว restart service · ค่าเป็น Python literal ส่งต่อถึง `drone_setup_px4_cesium.py` ทาง `DRONE_SETUP_<ชื่อ>` · ค่าที่ตั้งได้และค่าปัจจุบันอยู่ใน `.env.example` หมวด "สเปกโดรน"

| เปลี่ยนผ่าน `.env` ได้ | ต้องทำ vendor patch (`vendor/README.md`) |
|---|---|
| ลม (`ADD_WIND` `WIND_*`) · จุดขึ้นบินและทิศ (`SPAWN_XYZ` `HEADING_DEG`) · ความละเอียดคลิป (`REC_W/H/FPS`) · การยึดกล้องล่าง (`DOWN_Z_OFFSET` `DOWN_VIB_DAMP`) | เลนส์/เซนเซอร์กล้อง (ZED X One GS 2.2 mm) · ความสูง takeoff 5 m และความเร็วสูงสุด 3 m/s (`joystick-server.py`) · ฟิสิกส์โดรน (Pegasus `MultirotorConfig`) · airframe PX4 (`gazebo-classic_iris`) |

- เช็กว่าค่าถูกใช้จริง: `vendor/drone-sitl/logs/launch-sitl.console` มีบรรทัด `>>> override <ชื่อ> = <ค่า>` · ชื่อผิดจะขึ้น `no tunable named ...` แล้วข้ามไป
- agent ของทีมเปลี่ยนสเปกเองไม่ได้ (สั่งได้แค่ความเร็ว/เส้นทางผ่าน `competition/commands.py`)
- **ทุกทีมต้องบินสเปกเดียวกัน** ไม่งั้นคะแนนเทียบกันไม่ได้ (โดยเฉพาะกล้อง) · ถ้าเปิดลมให้ตั้ง `WIND_SEED` เพื่อให้ลมเหมือนกันทุกรอบ

## ข้อมูลย้อนหลัง

`data/runs/<job_id>/` เก็บทุกไฟล์ข้างบน + `job.json` · เปิดดูผ่าน `GET /jobs` และ `/files/*` · เกิน `DATA_RETENTION_GB` จะลบงานที่จบแล้วเก่าสุดก่อน (ไม่แตะงานที่ยังไม่จบ)

## ความปลอดภัยและข้อจำกัด

- ไม่มี login (ผู้เรียกเป็นคนใน; service bind 127.0.0.1) · allowlist ของ image · จำกัดเวลาบิน · จำกัดขนาด image 16 GB และดิสก์ว่าง ≥ 40 GB
- container ของผู้แข่งรันด้วย `--memory 24g --pids-limit 1024 --cap-drop ALL --security-opt no-new-privileges -e TZ=Asia/Bangkok` (ผ่าน `DRONE_SITL_DOCKER_RUN_ARGS` ของ drone-sitl)
- **รับงานได้ทาง API นี้เท่านั้น:** ตอนที่ service เปิดเว็บ drone-sitl (`:8090`) การอัปโหลด/pull ที่หน้าเว็บนั้นตรง ๆ ได้ `403` (ใช้ token ที่ service สุ่มใหม่ทุกครั้งที่เริ่ม)
- **ยังเสี่ยง:** container ใช้ `--network host` จึงเข้าถึง service อื่นบนเครื่องได้ (docs/design.md หัวข้อ 7) · ไม่มี TLS
- ถ้า service ถูกปิดกลางบิน คลิป MP4 ของงานนั้นอาจไม่มี (journal ครบ) · kill/timeout ระหว่าง pull: service หยุด `docker pull` ที่ค้างและลบสิ่งที่ pull มาให้ · `/ws` หลุดชั่วคราว: ต่อใหม่ภายใน 10 s แล้วติดตามการบินต่อ

## แก้ปัญหา

| อาการ | ทำ |
|---|---|
| งาน fail `sim_busy` | มี sim/เว็บค้าง: `vendor/drone-sitl/sim/stop-website.sh` แล้วส่งใหม่ |
| `/healthz` → `ok:false, phase:degraded` (POST ได้ 503) | cleanup ปิด sim ไม่ได้: รัน `vendor/drone-sitl/sim/stop-website.sh` เอง เช็ก `:8080`/`:8090` ว่าไม่ตอบ แล้ว `./scripts/stop-service.sh && ./scripts/run-service.sh` |
| `run-service.sh` บอก not answering | ดู `logs/service.console` (ไม่มี `.env` / port ถูกใช้) |
| งาน fail `sim_boot_timeout` / `px4_not_ready` | ดู `vendor/drone-sitl/logs/launch-sitl.console` · GPU ถูกใช้อยู่ไหม (`nvidia-smi`) |

## เทสต์

```bash
conda run -n drone python -m pytest -q          # ใช้ของปลอมทั้งหมด ไม่เปิด sim ~30 s
```
