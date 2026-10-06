# flight-service: design (ขั้นที่ 1)

> สถานะ: **อนุมัติแล้ว 2026-10-05** (ตอบคำถามครบ ดูหัวข้อ 11) · มีจุดเปลี่ยน 1 จุดหลังอนุมัติ: หัวข้อ 10 (ใช้ `/ws` ตรง แทน import `fly()`)
> ขอบเขต: API รับ docker image ref → pull → เปิด sim → บิน agent อัตโนมัติ → คืนผล
> อ้างอิง: `~/pai/drone-sitl` commit `326290e` (ตอนนี้ checkout อยู่ที่ branch `feat/website-usd-map-testgs` ซึ่งเป็น branch เดียวที่มี commit นี้)

---

## 1. สรุป

- เซอร์วิสใหม่ **แยกโฟลเดอร์** `~/pai/flight-service/` (FastAPI, env `drone`, port **8095**)
- **ไม่ copy โค้ด drone-sitl** ทุกขั้นเรียกของเดิม: สคริปต์ `sim/*.sh`, HTTP/WS ของ `:8090`, และ `import` ผ่าน `DRONE_SITL_DIR`
- แก้ drone-sitl **จุดเดียวที่อนุมัติแล้ว**: env `DRONE_SITL_DOCKER_RUN_ARGS` (หัวข้อ 8) มีหลักฐานทั้งสองโปรเจกต์
- **รับ image ได้ 2 ทาง:** (1) ชื่อ image บน registry แล้วให้เรา pull (ทำรอบนี้) (2) **อัปโหลดไฟล์ image ตรงด้วย curl** (เผื่อไว้ หัวข้อ 12 โครงโค้ดรองรับตั้งแต่รอบนี้)
- **รันได้ทีละงาน · คิวหลักอยู่ที่ระบบพี่ต้น** ฝั่งเรามีช่องรอเล็ก 1 งาน (`MAX_PENDING=1`) ไว้กันจังหวะชน ช่องรอเต็มตอบ `409 busy` · สรุป API + sequence diagram: [api.md](api.md)
- **ทุกงานบูต sim ใหม่และปิดเมื่อจบ** เพื่อให้โดรนเริ่มจากแท่นเสมอ (แลกกับเวลาบูต 2–5 นาทีต่องาน)
- ทุกขั้นมี timeout งานจึงจบเป็น `done` หรือ `failed` พร้อม `reason` เสมอ ไม่ค้างเงียบ
- **ทุกข้อมูลเขียนเป็น journal ทันทีที่ได้ และทุกทางจบ (รวม kill) สร้างผลด้วย finalize ตัวเดียว** หัวข้อ 13 (แทนส่วนเก็บผลในหัวข้อ 2, 5, 7, 10)
- ผลรวม **score การ detect v0** (0–100 เทียบกับตำแหน่งรถจริง) หัวข้อ 9.1
- **ข้อ d: แบบ A (poll) + ลิงก์ MP4 หลังบินจบ** (หัวข้อ 9)
- รอบนี้ **ทดสอบบนเครื่องตัวเอง** ด้วยสคริปต์ที่ทำตัวเป็นพี่ต้น (bind `127.0.0.1`)

---

## 2. Flow

```
curl POST /jobs ──► (ช่องรอเต็ม → 409) ──► [queued ≤ 1] ──► worker (ทีละงาน)
                                   │
   1 precheck   sim ว่างไหม (sim_busy) · ตรวจ allowlist · ตรวจที่ว่างดิสก์ · ดูขนาด image จาก manifest
   2 pulling    เปิด web อย่างเดียว (SKIP_SIM=1 run-website.sh)         ← image จาก registry
     loading    (หรือ) docker load ไฟล์ที่อัปโหลดมา แล้ว retag            ← image จากไฟล์ (หัวข้อ 12)
                → POST :8090/agent/pull-docker?ref=<ref>  (DockerBuild.pull → retag submission-<stem>-<ts>)
                → ตรวจขนาดจริงหลัง pull
   3 booting    ./sim/run-website.sh  (บูต Isaac + PX4, เว็บเปิดอยู่แล้ว)
                → รอจนบรรทัด "Ready for takeoff" ขึ้นใน logs/launch-sitl.console      [กับดัก 1]
   4 flying     ต่อ /ws ค้างไว้ตลอด → ส่ง {"type":"agent","action":"run","kind":"docker",...} [กับดัก 2]
                → เก็บ telemetry 5 Hz + panel log · เฝ้า arming timeout + flight timeout
   5 collecting copy คลิป/กล่อง/log จาก drone-sitl เข้า jobs/<id>/ · สรุปผล
   6 cleanup    stop agent → ./sim/stop-website.sh → docker rmi เฉพาะ tag ของงานนี้      [กับดัก 3,5,6]
                → worker ว่าง รับงานถัดไป
```

**ทำไม pull ก่อนบูต sim:** pull image 12.5 GB อาจใช้เวลาเป็น 10 นาที ถ้าบูต sim ก่อน GPU จะถูกจองไว้ทั้งที่ไม่ได้ใช้ และ Isaac อาจ time out ระหว่างรอ `run-website.sh` ทำงานแบบ idempotent
จึงเปิดเว็บอย่างเดียวก่อนได้ (`SKIP_SIM=1`) แล้วค่อยเรียกซ้ำให้บูต Isaac
⚠️ ต้องยืนยันในขั้นที่ 3 ว่า joystick-server ที่เปิดก่อน PX4 ยังจับลิงก์ MAVLink ได้ ถ้าไม่ได้ fallback คือ `stop-website` แล้ว `run-website` ใหม่หลัง pull เสร็จ

---

## 3. API (ฉบับรวม 2026-10-05 · 7 endpoint, ตัวละหนึ่งหน้าที่ ไม่ซ้ำกัน · เพิ่ม stream 2026-10-06)

ทุก endpoint ยกเว้น `/healthz` ต้องมี `Authorization: Bearer <RUNNER_TOKEN>`

| method | path | หน้าที่เดียวของมัน | ไม่ทำอะไร (กันซ้ำ) |
|---|---|---|---|
| `POST` | `/jobs` | **สร้างงาน** ส่งมาเป็น JSON = ชื่อ image บน registry · ส่งมาเป็นไฟล์ = อัปโหลด image (หัวข้อ 12) | ไม่มี `/jobs/upload` แยก: "สร้างงาน" มีทางเดียว ต่างกันแค่ `Content-Type` |
| `GET` | `/jobs` | **ประวัติงาน** ล่าสุด 50 งาน (สรุปสั้น: id, state, image, เวลา, reason) | ไม่มีรายละเอียด telemetry/result (อยู่ใน `GET /jobs/{id}`) |
| `GET` | `/jobs/{id}` | **สถานะ + ข้อมูลสด + ผล** ของงานเดียว | ไม่มีเนื้อไฟล์ (ให้ลิงก์ใน `result.files`) |
| `GET` | `/jobs/{id}/stream` | **ติดตามสด** เป็น Server-Sent Events: state, telemetry ทุกบรรทัด, ผลตอนจบ (หัวข้อ 3.1) | ไม่ส่ง log ของ agent หรือ detections (อยู่ใน `GET /jobs/{id}` และ `/files/*`) |
| `POST` | `/jobs/{id}/kill` | **หยุดงานที่กำลังทำ** แล้วตอบด้วยผลที่เก็บได้ (หัวข้อ 13.5) | ไม่มี `/cancel` หรือ `/jobs/current/kill` ซ้ำ ให้หา id จาก `GET /jobs` |
| `GET` | `/jobs/{id}/files/{name}` | **ดาวน์โหลดไฟล์** ของงาน (ทั้งระหว่างบินและหลังจบ) | ไม่ list ไฟล์ (list อยู่ใน `result.files`) |
| `GET` | `/healthz` | **พร้อมรับงานไหม** `{"ok":true,"ready":true,"phase":"idle","pending":0}` ไม่ต้องใช้ token (ระบบคิวของพี่ต้นใช้ตัวนี้ตัดสินใจส่งงาน) | ไม่บอก id หรือรายละเอียดงาน (กันข้อมูลรั่วโดยไม่มี token) |

ไฟล์ที่ดาวน์โหลดได้ (หัวข้อ 13.4): `telemetry.jsonl`, `events.jsonl`, `detections.jsonl`, `track.jsonl`, `panel.log`, `detections.mp4`, `meta.json`, `score.json`, `result.json`, `analysis.txt`
ระหว่างบิน journal (`telemetry.jsonl`, `events.jsonl`, `detections.jsonl`) โหลดได้ตลอด ไฟล์อื่นจะมีหลัง finalize

### ตัวอย่าง

```bash
export R=http://127.0.0.1:8095  H="Authorization: Bearer $TOKEN"

# สร้างงานจาก registry
curl -s -X POST $R/jobs -H "$H" -H 'Content-Type: application/json' \
  -d '{"image": "perkiepai/truck-detector:20260929-214240", "flight_timeout_s": 600}'
# → 202 {"job_id":"j-20261005-142233-a1b2","state":"queued","source":"registry"}
# → 409 {"detail":"busy","current_job":"j-...","pending":["j-..."]}  ถ้าช่องรอเต็ม

# สร้างงานจากไฟล์ (หัวข้อ 12): -T = stream ไฟล์ ไม่โหลดเข้า RAM
curl -s -X POST -T truck.tar $R/'jobs?kind=image&name=truck-detector&flight_timeout_s=600' -H "$H"

curl -s $R/jobs -H "$H"                                     # รายการ
curl -s $R/jobs/j-20261005-142233-a1b2 -H "$H"              # ติดตาม
curl -s -X POST $R/jobs/j-20261005-142233-a1b2/kill -H "$H" # หยุด → ได้ผลที่เก็บมา
curl -s -o clip.mp4 $R/jobs/j-20261005-142233-a1b2/files/detections.mp4 -H "$H"
```

`GET /jobs/{id}` ระหว่างบิน:
```json
{"job_id":"j-20261005-142233-a1b2","state":"flying","source":"registry","image":"perkiepai/truck-detector:20260929-214240",
 "created_at":"2026-10-05T14:22:33+0700","state_since":"2026-10-05T14:31:02+0700","elapsed_s":812,
 "telemetry":{"lat":14.0291,"lon":100.4361,"alt_m":40.1,"heading_deg":92.0,"roll_deg":0.4,"pitch_deg":-5.1,
              "gs":3.0,"vz":0.0,"mode":"OFFBOARD","armed":true,"agent_state":"running"},
 "log_tail":["[ 141.0s] DETECT ... new #2 at 14.0290, 100.4359", "..."],
 "score_live":{"rows":212,"trucks_found":1,"trucks_total":3},
 "result":null}
```

เมื่อจบ (`done`, `failed`, `killed` ใช้รูปแบบเดียวกัน):
```json
{"job_id":"...","state":"done","failed_in":null,"reason":null,
 "result":{"ended_by":"agent","partial":false,"outcome":"done","done_line":true,
           "flight_s":438.4,"distance_m":1712.0,"max_alt_m":40.6,"track_points":2192,
           "score":{"version":"v0","score":90.7,"recall":1.0,"precision":0.83,"trucks_found":3,"trucks_total":3},
           "files":{"track.jsonl":"/jobs/<id>/files/track.jsonl","detections.mp4":"/jobs/<id>/files/detections.mp4","...":"..."},
           "missing":[]}}
```

ล้มเหลว:
```json
{"job_id":"...","state":"failed","failed_in":"booting","reason":"px4_not_ready",
 "detail":"no 'Ready for takeoff' in launch-sitl.console after 180 s","result":{"ended_by":"error","partial":true,"...":"..."}}
```

ข้อผิดพลาดตอนสร้างงาน (ไม่สร้าง job): `401` token · `400` request ผิดรูปแบบ · `403` image ไม่อยู่ใน allowlist · `411` ไฟล์ไม่มี Content-Length · `413` ใหญ่เกิน · `415` Content-Type ไม่รองรับ · `409` ช่องรอเต็ม · `503` runner degraded · `507` ดิสก์ไม่พอ
ข้อผิดพลาดอื่น: `404` ไม่มีงาน/ไฟล์ · `409` kill งานที่จบไปแล้ว

### 3.1 Stream สด: `GET /jobs/{id}/stream` (เพิ่ม 2026-10-06)

Server-Sent Events บน HTTP ธรรมดา · token เดียวกับ endpoint อื่น · `404` / `401` ตอบก่อนเปิดสาย · รายละเอียดและเหตุผล: `docs/superpowers/specs/2026-10-06-sse-client-design.md`

| event | ส่งเมื่อ | data |
|---|---|---|
| `state` | ตอนต่อเข้ามาหนึ่งครั้ง และทุกครั้งที่ state เปลี่ยน | `{"state","since","reason"}` |
| `telemetry` | มีบรรทัดใหม่ใน `telemetry.jsonl` (5 Hz) · มี `id` = เลขบรรทัด | บรรทัด JSON นั้น ทุกฟิลด์ |
| `end` | state จบ และ telemetry ส่งครบแล้ว จากนั้น server ปิดสาย | `{"job_id","state","failed_in","reason","detail","result"}` |

- ต่อใหม่พร้อม header `Last-Event-ID: n` → ได้บรรทัดที่ n+1 เป็นต้นไป ไม่หาย ไม่ซ้ำ (ค่าที่ไม่ใช่เลขบรรทัด = ส่งตั้งแต่ต้น)
- ช่วงที่ไม่มีอะไรจะส่ง (pulling, booting, finalize, cleanup) มีบรรทัดคอมเมนต์ `: ping` ทุก 15 s
- สถานะมาจาก job ในหน่วยความจำ ไม่ใช่ `events.jsonl` · state จบถูกตั้งหลัง cleanup (หัวข้อ 5) ดังนั้น `end` = journal ปิดแล้ว ผลพร้อม ส่งงานถัดไปได้
- service restart กลางบิน: สายขาด ต่อใหม่ได้ `end` พร้อม `failed` / `runner_restarted`
- ไม่ทำ: จำกัดจำนวนสายต่อ job · log ของ agent / detections ใน stream · ตัดฟิลด์ telemetry

---

## 4. State ของงาน

```
POST /jobs → queued → pulling ─┬→ booting → flying → done
             loading ─┘     │         │
                │           │         │
                └───────────┴─────────┴──► failed   (มี failed_in + reason + detail)
                └──────── POST kill ──────► killed
```

- `pulling` รวม precheck · `loading` ใช้แทน `pulling` เมื่อ image มาจากไฟล์อัปโหลด · `booting` รวมการรอ `Ready for takeoff`
- job มีฟิลด์ `source` = `registry` | `upload` บอกว่า image มาทางไหน
- `flying` เริ่มเมื่อส่ง RUN ส่วน `agent.state` (arming/running) อยู่ใน `telemetry.agent_state`
- **`done` = agent จบเอง** (container exit 0 หรือ panel มีบรรทัด `] DONE`) แล้วเก็บผลครบ
  - `DONE` ไม่อยู่ในสัญญา `competition-api.md` เป็นแค่ธรรมเนียมของตัวอย่าง จึงไม่ใช้เป็นเงื่อนไขหลัก และรายงานเป็น `result.done_line`
- งานจะเป็น `done`/`failed`/`killed` **หลัง finalize และ cleanup เสร็จ** (2026-10-05) พี่ต้นจึงใช้ "state จบ" เป็นสัญญาณส่งงานถัดไปได้เลย · ภาพ: [api.md](api.md) หัวข้อ 2

### reason ที่เป็นไปได้

| reason | เกิดใน | เมื่อไร |
|---|---|---|
| `disk_low` | pulling | ที่ว่างน้อยกว่า `MIN_FREE_GB` หรือน้อยกว่า 2× ขนาด image |
| `image_too_large` | pulling | ขนาด (manifest หรือหลัง pull) เกิน `MAX_IMAGE_GB` |
| `pull_failed` | pulling | `/agent/pull-docker` ตอบ 4xx/5xx (แนบ log ท้ายๆ) หรือเกิน `PULL_TIMEOUT_S` |
| `sim_busy` | pulling/loading (ตรวจก่อนทำอะไร) | มี sim/เว็บที่ runner ไม่ได้เปิดรันอยู่ (ดูคำถามข้อ 3) |
| `sim_boot_timeout` | booting | `:8080` ไม่ตอบภายใน `BOOT_TIMEOUT_S` หรือ Isaac ตาย |
| `px4_not_ready` | booting | ไม่มี `Ready for takeoff` ภายใน `PX4_READY_TIMEOUT_S` |
| `run_refused` | flying | AgentRun ตอบ `RUN refused...` / state=error ก่อน arming |
| `arming_timeout` | flying | ค้างใน `arming` เกิน `ARMING_TIMEOUT_S` (ตัวกันกับดัก 1 ชั้นที่ 2) |
| `agent_crashed` | flying | agent state=error / container exit ≠ 0 |
| `flight_timeout` | flying | บินเกิน `flight_timeout_s` → stop agent แล้วเก็บผลที่มี (ไฟล์ยังได้) |
| `load_failed` / `archive_rejected` | loading | (หัวข้อ 12) `docker load` ล้ม / tag ในไฟล์ไม่อยู่ใน allowlist หรือทับ image ที่มีอยู่ |
| `ws_lost` | flying | ต่อ `/ws` ไม่ได้ หรือหลุดแล้วต่อใหม่ไม่ได้ใน 10 s |
| `runner_restarted` | ใดๆ | runner ถูก restart ระหว่างงาน → ตอนเริ่มใหม่ปิด sim และตั้งงานค้างเป็น failed |

---

## 5. คิว → คิวหลักอยู่ที่ระบบของพี่ต้น · ฝั่งเรามีช่องรอเล็ก (เปลี่ยน 2026-10-05)

- worker มี **ช่องรอ `MAX_PENDING=1`**: รับงานรอต่อจากงานที่กำลังทำได้ 1 งาน กันจังหวะที่ระบบพี่ต้นส่งงานถัดไปเร็วกว่าที่เรา cleanup เสร็จ และพี่ต้นตรวจเทียบกับคิวของตัวเองได้จาก `GET /jobs` (งานรอเป็น `queued`) และ `GET /healthz` (`pending`)
- `POST /jobs`: ช่องว่าง = `202` · ช่องรอเต็ม = `409 busy` (บอก `current_job` และ `pending`) · degraded = `503`
- ช่องรอเป็นของชั่วคราว: runner restart → งานที่รออยู่เป็น `failed/runner_restarted` (ไม่รันต่อเอง) ให้ระบบพี่ต้นส่งใหม่
- การจองตัว runner ทำใน request เดียวกันก่อน `await` ใด ๆ จึงไม่มีทางรับ 2 งานซ้อนแม้ยิงพร้อมกัน · การอัปโหลดไฟล์ตรวจว่าว่างก่อนรับไฟล์ (ไม่เปลืองแบนด์วิดท์)
- พี่ต้นรู้ว่าส่งได้: `GET /healthz` → `ready: true` (ช่องรอว่าง) · state จบของงาน = cleanup เสร็จแล้ว
- เก็บ job เป็น `data/runs/<id>/job.json` (atomic) · runner restart → งานที่ค้างถูก finalize จาก journal แล้วเป็น `failed/runner_restarted` (หัวข้อ 13) · ส่งซ้ำหรือไม่ พี่ต้นตัดสินใจเอง

---

## 6. Timeout (ตั้งผ่าน env, ค่าเริ่มต้น)

| ค่า | default | หมายเหตุ |
|---|---|---|
| `PULL_TIMEOUT_S` | 1800 | image 12.5 GB |
| `BOOT_TIMEOUT_S` | 420 | `ISAAC_WAIT_S` ของ run-website = 360 |
| `PX4_READY_TIMEOUT_S` | 180 | นับหลัง `:8080` ตอบ |
| `ARMING_TIMEOUT_S` | 90 | arm → takeoff → offboard ปกติใช้ < 30 s |
| `flight_timeout_s` | 600 (สูงสุด `MAX_FLIGHT_S` = 900) | ส่งมากับ request ได้ · drone-sitl ไม่มีลิมิตเอง (`AGENT_TIME_LIMIT_S = None`) |
| `CLEANUP_TIMEOUT_S` | 120 | ถ้า stop-website ไม่จบ → log + `healthz` ขึ้น degraded ไม่รับงานต่อ |

---

## 7. Cleanup (ทำทุกงาน ไม่ว่าสำเร็จหรือล้มเหลว · ใช้ `try/finally`)

1. ส่ง `{"type":"agent","action":"stop"}` ทาง `/ws` (ถ้ายังต่ออยู่)
2. ถ้ายังมี container ของ image งานนี้ → `docker rm -f <ชื่อ>` (หาด้วย `docker ps --filter ancestor=<tag>` ไม่ใช่ pattern กว้าง)
3. `./sim/stop-website.sh` (kill ด้วย PID ตาม signature ของ repo เองอยู่แล้ว **runner ไม่เรียก `pkill -f` เอง**) [กับดัก 5]
4. ยืนยันว่า `:8080`/`:8090` ไม่ตอบแล้ว
5. `docker rmi` **เฉพาะ** `submission-<stem>-<ts>` ที่ pull มาในงานนี้ และ ref ต้นฉบับ **ถ้าก่อน pull ยังไม่มีบนเครื่อง** (จดไว้ตอน precheck) · **ไม่ใช้ `docker image prune`** [กับดัก 6]
6. ตั้ง `KEEP_IMAGE=1` ได้ตอน debug

---

## 8. ความปลอดภัย

**ความเสี่ยงหลัก:** รับ ref → `docker pull` → `docker run --network host --gpus all` คือการรันโค้ดของคนอื่นบนเครื่องนี้ โดยเห็น localhost ทุก service

| ชั้น | มาตรการ |
|---|---|
| ยืนยันตัวตน | Bearer token จาก env `RUNNER_TOKEN` (≥ 32 ตัวอักษร) เทียบด้วย `hmac.compare_digest` · ไม่เขียน token ลง log · ไม่มี token = runner ไม่ยอมเริ่ม |
| allowlist | regex ใน `ALLOWED_IMAGES` เช่น `^(docker\.io/)?perkiepai/[a-z0-9][a-z0-9_.-]*(:\w[\w.-]{0,127}\|@sha256:[0-9a-f]{64})$` · ต้องมี namespace ชัดเจน · ไม่รับชื่อ local เปล่าๆ (กัน `competition-base`, `postgres:15.4` ฯลฯ) |
| ขนาด | ก่อน pull: `docker manifest inspect` รวมขนาด layer · หลัง pull: `docker image inspect .Size` ≤ `MAX_IMAGE_GB` (default 16) ถ้าเกิน → rmi + `image_too_large` |
| ดิสก์ | ว่าง ≥ `MIN_FREE_GB` (default 40) และ ≥ 2× ขนาด image (ตอนนี้ว่าง 115 GB, 94% ใช้แล้ว) |
| เวลา | flight timeout + timeout ทุกขั้น (หัวข้อ 6) |
| ปริมาณ | ทำทีละ 1 งาน + ช่องรอ 1 งาน · JSON body ≤ 4 KB |
| container | runner เปิดเว็บด้วย `DRONE_SITL_DOCKER_RUN_ARGS="--memory 24g --memory-swap 24g --pids-limit 1024 --cap-drop ALL --security-opt no-new-privileges"` → AgentRun ใส่ flag เหล่านี้ให้ `docker run` |
| เครือข่าย | รอบนี้ bind `127.0.0.1:8095` เท่านั้น (ทดสอบบนเครื่อง) · เปิดให้พี่ต้นภายหลังด้วย `RUNNER_HOST` เมื่อรู้ว่าเรียกจากไหน · ไม่มี TLS ในตัว ถ้าข้ามเน็ตต้องอยู่หลัง VPN/reverse proxy |

**แก้ drone-sitl (อนุมัติ 2026-10-05):** `AgentRun._spawn` อ่าน env `DRONE_SITL_DOCKER_RUN_ARGS` (แยกด้วย `shlex.split`) แล้วใส่ต่อหลัง `--gpus` ก่อน `--name` · ไม่ตั้ง env = พฤติกรรมเดิมทุกอย่าง
หลักฐาน: `drone-sitl/docs/changes/2026-10-05-docker-run-args.md` + `flight-service/docs/drone-sitl-changes.md` (diff, เหตุผล, ผลเทสต์, commit)

**ความเสี่ยงที่ยังเหลือ:** `--network host` ยังทำให้ container เข้าถึง postgres `:5433`, ollama `:11434` ฯลฯ บนเครื่องนี้ได้ (เลิกใช้ต้อง redesign competition-base แยกเป็นงานต่างหาก) · `--read-only`/`--user` ยังไม่ใส่ เพราะ torch/rfdetr เขียน cache ลงดิสก์ ต้องทดสอบก่อน
ถ้า `--cap-drop ALL` ทำให้ GPU ใน container ใช้ไม่ได้ (ตรวจในขั้น 4) จะเอา flag นี้ออกแล้วบันทึกไว้

---

## 9. ข้อ d: วิธีส่งข้อมูลกลับ → **เลือก A + MP4 หลังจบ**

> **2026-10-06:** เพิ่ม stream สดแบบ SSE (หัวข้อ 3.1) เป็นทางเสริมของ A · poll ยังใช้ได้เหมือนเดิม · ต่างจากทาง C ตรงที่เป็น HTTP ขาเดียว ไม่มีภาพสด และไม่ต้องเปิดพอร์ตเพิ่ม

### ข้อมูลอะไร ส่งตอนไหน

| ข้อมูล | ระหว่างบิน | ตอนจบ |
|---|---|---|
| state + reason | ✅ | ✅ |
| ตำแหน่ง/ท่าทาง (lat, lon, alt, heading, roll, pitch, gs, vz, mode, armed) | ✅ ค่าล่าสุด หรือ stream 1–5 Hz | ✅ `track.jsonl` ครบ 5 Hz |
| Agent panel log | ✅ 20 บรรทัดท้าย | ✅ `panel.log` ครบ |
| กล่อง detection | ✅ จำนวนสะสม | ✅ `detections.jsonl` (กล่อง + ตำแหน่งโดรนทุกเฟรม) |
| ภาพกล้อง | ⚠️ เฉพาะแบบ C | ✅ `detections.mp4` (กล้อง agent + กล่อง + HUD) + `meta.json` |
| **score การ detect** | ✅ ค่าชั่วคราว (นับกล่อง + รถที่เจอแล้ว) | ✅ `score.json` ฉบับเต็ม (หัวข้อ 9.1) |
| สรุปผล | — | ✅ `result.json` (ระยะเวลา, ระยะทาง, alt สูงสุด, exit, done_line, score) |

> "ข้อมูลทุกอย่างจาก PX4": ที่ drone-sitl เปิดออกมาคือ telemetry ใน `/ws` (ตารางบน) ซึ่ง runner เก็บครบทุกฟิลด์ ส่วน PX4 ulog (`.ulg`) ไม่พบบนเครื่องตอนนี้ ถ้าต้องการต้องเปิด SDLOG ใน PX4 ซึ่งเป็นงานแยก

### ทางเลือก

| | **A. ให้ฝั่งนั้นดึงเอง (poll)** | **B. callback (push)** | **C. stream สด (WebSocket + MJPEG)** |
|---|---|---|---|
| ทำงานยังไง | `GET /jobs/{id}` ทุก 1–5 s · จบแล้วโหลดไฟล์จาก `/files/*` | ส่ง `callback_url` มากับ request · runner POST เมื่อ state เปลี่ยน + ตำแหน่ง batch ทุก 1 s + ผลสรุปตอนจบ | `WS /jobs/{id}/stream` ส่ง telemetry 5 Hz + log + event · `GET /jobs/{id}/live/{down,detect,chase}` proxy MJPEG |
| ข้อดี | ง่ายสุด ใช้ curl ได้ · ฝั่งนั้นไม่ต้องมีเซิร์ฟเวอร์ · ฝั่งไหนหลุดก็ไม่เสียข้อมูล (ไฟล์อยู่ครบ) · เทสต์ง่าย | real-time โดยไม่ต้อง poll · เหมาะถ้าฝั่งนั้นมีระบบรับอยู่แล้ว | real-time ที่สุด ดูภาพสดได้ |
| ข้อเสีย | latency เท่ารอบ poll · ไม่มีภาพสด | ฝั่งนั้นต้องมี URL ที่เครื่องเราเข้าถึงได้ · ต้องทำ retry/ลายเซ็น HMAC · เสี่ยง SSRF (ต้องมี allowlist ของ URL) · ถ้าปลายทางล่มข้อมูลระหว่างบินหาย | โค้ดเยอะสุด · ต้องต่อค้างไว้ · MJPEG กินแบนด์วิดท์ (~1–3 Mbps ต่อช่อง) และต้องเปิด `:8080` ผ่าน proxy |
| งานเพิ่ม | น้อย (endpoint ที่มีในหัวข้อ 3 ก็พอ) | ปานกลาง | มาก |

### 9.1 Detection score v0 (เริ่มแบบง่าย ปรับทีหลัง)

**ใช้แค่ข้อมูลตามสัญญา** คือ `detections.jsonl` (กล่อง `class_name`/`confidence`/`bbox` + ตำแหน่งโดรนทุกแถว) กับตำแหน่งรถจริงของแผนที่
(`fly_headless.load_truth("nt-testgs")` → `drone_map_vehicles.json`) **ไม่อ่าน log ของผู้แข่ง** เพราะรูปแบบ log ไม่อยู่ในสัญญา

| ส่วน | วิธีคิด |
|---|---|
| สถิติกล่อง | จำนวนแถวที่มีกล่อง, จำนวนกล่องรวม, แยกตาม class: count / conf เฉลี่ย / conf สูงสุด |
| แถว "ถูก" | ระยะแนวราบจากโดรนถึงรถจริงคันที่ใกล้สุด ≤ `max(alt_m, 10)` m (ประมาณว่ารถอยู่ในภาพ) |
| `trucks_found` | รถจริงที่มีแถว "ถูก" อย่างน้อย 1 แถว |
| `recall` | `trucks_found / trucks_total` |
| `precision` | `แถวถูก / แถวที่มีกล่องทั้งหมด` |
| **`score`** | `100 × F1(recall, precision)` (0–100) |

```json
{"version":"v0","site":"nt-testgs",
 "boxes":{"rows":1091,"total":1130,"by_class":{"Truck":{"count":1130,"conf_mean":0.71,"conf_max":0.93}}},
 "truth":{"trucks_total":3,"trucks_found":3,"rows_near_truck":902,"recall":1.0,"precision":0.83},
 "score":90.7}
```

- **ระหว่างบิน:** `GET /jobs/{id}` มี `score_live` = สถิติกล่อง + `trucks_found` ณ ตอนนั้น · **ตอนจบ:** `score.json` เต็ม และใส่ไว้ใน `result.score`
- **ข้อจำกัดที่รู้อยู่ (ไว้ปรับรอบหน้า):** ไม่ได้ฉายกล่องลงพื้น (ต้องใช้ intrinsics + ท่าทางกล้อง) และกล้องเฉียงมองไปข้างหน้า ระยะ "ถูก" จึงเป็นค่าประมาณ ส่วนกล่องหลอกที่ (−77, 28) ซึ่งอยู่ไกลรถจะถูกนับเป็นแถวผิด (ถูกต้องตามที่ควร)
- โบนัส: ถ้า log ของ agent มีบรรทัด `DETECT ... new #` จะแนบผล `fly_headless.analyze()` เป็น `analysis.txt` ไว้ให้คนอ่าน แต่ไม่นำมาคิดคะแนน

**วิดีโอ:** ลิงก์ MP4 หลังจบ (ได้ฟรีจาก `det_recorder` อยู่แล้ว) **หรือ** สตรีมสด (ต้องใช้แบบ C)

**ตัดสินใจ: A + MP4 หลังจบ** (2026-10-05) ทำ B หรือ C เพิ่มทีหลังได้โดยไม่ต้องรื้อ เพราะใช้ข้อมูลชุดเดียวกัน

---

## 10. วิธีใช้ของเดิมจาก drone-sitl (ไม่ copy)

| ต้องการ | ใช้ |
|---|---|
| เปิด/ปิด sim + เว็บ | `subprocess` → `$DRONE_SITL_DIR/sim/run-website.sh` (+ `SKIP_SIM=1`), `stop-website.sh` |
| pull + retag | `POST :8090/agent/pull-docker?ref=` |
| สั่งบิน + สถานะสด | **ต่อ `/ws` ที่มีอยู่โดยตรง** (`flightsession.py`): ส่ง `agent run` แล้วอ่าน telemetry 5 Hz เก็บเป็น `track.jsonl` (ฟิลด์เดียวกับ `fly_headless` เพื่อให้ `analyze()` อ่านได้) |
| panel.log ฉบับเต็ม | จากโฟลเดอร์คลิปของ `det_recorder` (เขียนทุกบรรทัดที่ AgentRun note ไว้) |
| คลิป | `GET :8090/detrec/status` → `last` = path ของ mp4 → รอ `meta.json` → copy ทั้งโฟลเดอร์เข้า `jobs/<id>/` |
| กล่อง | `logs/detections/<tag>-<ts>.jsonl` (ไฟล์ที่ mtime หลังเวลา RUN) |
| ตำแหน่งรถจริง (score) | `import fly_headless` ผ่าน `DRONE_SITL_DIR` → `load_truth("nt-testgs")` |
| ตรวจกับรถจริง (โบนัส) | `fly_headless.analyze(out_dir, "nt-testgs")` → `analysis.txt` |
| PX4 พร้อม | อ่าน `logs/launch-sitl.console` หา `Ready for takeoff` (มีโค้ดสี ANSI ปน ใช้ substring) และไฟล์ต้องถูกแก้หลังเวลาที่เริ่มบูต (กันอ่านเจอของรอบก่อน) |

**เปลี่ยนจากร่างแรก (ไม่ import `fly()` แล้ว):** ตอนวางแผนพบว่า `fly()` เขียน `track.jsonl`/`panel.log` แบบมี buffer (ไม่ flush)
สถานะสดจึงช้าหลายวินาทีถึงหลายนาที และถ้า RUN ถูกปฏิเสธ ข้อความนั้นจะถูกนับเป็น "log ของรอบก่อน" แล้ววนจนหมดเวลา
ข้อกำหนดเดิมอนุญาตให้ "เรียกใช้ผ่าน WebSocket ที่มีอยู่" ไว้แล้ว runner จึงเขียน client ของ `/ws` เองแบบสั้นๆ (ไม่ต้องตัดบรรทัด log ซ้ำ เพราะ log เต็มได้จาก det_recorder) ส่วน `fly_headless` ยังใช้สำหรับ `load_truth` และ `analyze`

---

## 11. คำตอบ (2026-10-05)

1. **ข้อ d:** A + ลิงก์ MP4 หลังบินจบ · score v0 ตามหัวข้อ 9.1 ใช้เป็นรอบแรก
2. **image ทดสอบ:** push ขึ้น Docker Hub `perkiepai/...` (login `perkiepai` อยู่แล้วบนเครื่องนี้) · ⚠️ ก่อน push ต้องยืนยันอีกครั้งว่าจะให้ repo เป็น **private หรือ public** เพราะใน image มี weights ของโมเดล
3. **sim เปิดค้างอยู่:** งาน fail เป็น `sim_busy` runner ไม่ปิดของคนอื่น · ตอน runner restart ก็จะเรียก `stop-website.sh` เฉพาะเมื่องานที่ค้างเป็นคนเปิด sim เอง (บันทึก `owns_sim` ไว้ใน job.json)
4. **พี่ต้นเรียกจากไหน:** ยังไม่รู้ รอบนี้ทดสอบบนเครื่องตัวเอง bind `127.0.0.1` + `scripts/mock-caller.sh` ทำตัวเป็นพี่ต้น (curl ส่งงาน → poll → โหลดผล)
5. **แก้ drone-sitl:** อนุมัติ พร้อมเขียนหลักฐานทั้งสองโปรเจกต์ (หัวข้อ 8)

---

## 12. รับไฟล์ image ผ่าน curl (เผื่อไว้ · 2026-10-05)

**ทำไม:** ระบบของพี่ต้นอาจไม่มี registry ให้ pull การให้ส่งไฟล์มากับ curl ได้เลยจึงเป็นอีกช่องทางหนึ่ง

### ไฟล์แบบไหน (ต้องเลือก)

| แบบ | คืออะไร | ขนาด (ตัวอย่างรถบรรทุก) | ใช้ของเดิมได้ไหม |
|---|---|---|---|
| **image archive** | ผลของ `docker save <image> \| gzip` | ~5–12.5 GB | ❌ drone-sitl ไม่มี ต้องให้ runner `docker load` เอง |
| **build bundle** | tar ที่มี `Dockerfile` (`FROM competition-base`) + โค้ด + weights | ~129 MB | ✅ `POST :8090/agent/upload-docker` (build + tag `submission-<stem>-<ts>`) แต่ตอน build จะรัน `pip install` จากเน็ต |

คำว่า "ไฟล์ docker image" น่าจะหมายถึง **image archive** design นี้รองรับทั้งสองแบบผ่านพารามิเตอร์ `kind`

### API

```bash
# image archive (stream ไฟล์ด้วย -T ห้ามใช้ --data-binary เพราะ curl จะโหลดทั้งไฟล์เข้า RAM)
docker save perkiepai/truck-detector:20260929 | gzip > truck.tar.gz
curl -s -X POST -T truck.tar.gz -H "Authorization: Bearer $TOKEN" \
  "$R/jobs?kind=image&name=truck-detector&flight_timeout_s=600"
# → 202 {"job_id":"...","state":"queued","source":"upload"}

# build bundle
curl -s -X POST -T truck-detector.tar -H "Authorization: Bearer $TOKEN" "$R/jobs?kind=bundle&name=truck-detector"
```
endpoint เดียวกับการส่งชื่อ image (`POST /jobs`) แยกกันด้วย `Content-Type`: JSON = registry, อย่างอื่น (`curl -T` ส่ง `application/octet-stream`) = ไฟล์ · ติดตามผลด้วย endpoint เดิมทุกอย่าง

### Flow

1. **รับไฟล์ระหว่าง request:** ต้องมี `Content-Length` · ตรวจว่า ≤ `MAX_UPLOAD_GB` (default 16) และดิสก์ว่าง ≥ `MIN_FREE_GB` + 2× ขนาดไฟล์ **ก่อน**รับ · เขียนแบบ stream ลง `data/uploads/` (นอก `data/runs/` เพื่อไม่ให้ retention นับ) นับ byte ถ้าเกินหรือขาด → ลบไฟล์ + `413`/`400` · ไม่มีข้อมูลเข้ามา 60 s → `408` · ไฟล์ที่กำลังเข้าจองช่องรอ และ `/healthz` นับรวมใน `pending`
2. ตรวจช่องรอ**ก่อน**รับไฟล์ (เต็ม → `409` โดยไม่รับไฟล์) · ไฟล์ที่กำลังส่งเข้ามาจองช่องรอไว้ · ได้ไฟล์ครบแล้วจึงสร้าง job (`source=upload`)
3. **loading** (แทน pulling):
   - `kind=image`: อ่าน metadata ในไฟล์**ก่อน load** ทั้ง `manifest.json` (RepoTags) **และ `index.json`** (annotation `io.containerd.image.name` ซึ่ง Docker 29 + containerd image store ใช้ตั้งชื่อตอน load จริง) ต้องเป็น image เดียว และทุกชื่อต้อง**ยังไม่มีบนเครื่อง** ถ้าไม่ผ่าน → `archive_rejected` · หลัง load ตรวจซ้ำว่าชื่อที่ได้ตรงกับที่ตรวจไว้ ไม่ตรง → `archive_rejected` + runner `degraded` (อาจมี tag ถูกทับ ต้องให้คนตรวจ) · อ่านทีละ member จำกัด 100k member และ metadata ≤ 1 MB
     (ไม่บังคับ allowlist ของ registry กับไฟล์อัปโหลด เพราะผู้ส่งยืนยันตัวด้วย token แล้ว และสิ่งที่อันตรายจริงคือการทับ tag ที่มีอยู่)
     (กันไฟล์ที่ติด tag `competition-base:latest` หรือ `postgres:15.4` มาแล้วทับ image ของเรา) → `docker load -i` → retag เป็น `submission-<name>-<ts>` → ลบ tag เดิมที่มากับไฟล์
   - `kind=bundle`: ตรวจก่อนส่งต่อ ต้องมีแต่ไฟล์ธรรมดา/โฟลเดอร์ ไม่มี symlink/hardlink ไม่มี `..` และมี `Dockerfile` (เพราะตัวแตกไฟล์ของ drone-sitl ตามลิงก์ออกนอกโฟลเดอร์ได้) → เปิดเว็บแบบ `SKIP_SIM=1` → `POST :8090/agent/upload-docker?name=<name>.tar` (ส่งไฟล์ต่อแบบ stream) → ได้ `image_tag`
   - ตรวจขนาด image หลัง load/build ≤ `MAX_IMAGE_GB` · **ลบ `upload.tar` ทันทีหลัง load** (ไม่ต้องรอจบงาน)
4. จากนั้น booting → flying → collecting → cleanup เหมือนเดิม (cleanup `rmi` tag ของงานนี้ทุกครั้ง เพราะ image จากไฟล์ไม่เคยมีบนเครื่องมาก่อน)

### ความปลอดภัยเพิ่มเติม

- ไฟล์ที่อัปโหลด = โค้ดที่ไม่รู้ที่มา เหมือนการ pull จึงใช้ token, timeout และ limit ของ container ชุดเดียวกัน
- `name` ต้องตรง `^[a-z0-9][a-z0-9_-]{0,63}$` (ทั้งสองแบบ) · bundle ใหญ่ได้ไม่เกิน 200 MB (ลิมิตของ drone-sitl `AGENT_DOCKER_MAX_BYTES`)
- ไม่มีการแตกไฟล์ลงดิสก์เอง อ่านแค่ metadata ใน tar · **`_safe_extract` ของ drone-sitl กันชื่อไฟล์ `../` ได้แต่ไม่กัน symlink** (review 2026-10-05) flight-service จึงตรวจ bundle เองก่อนส่ง · **และปิดทางเข้าตรง:** ตอน flight-service เปิดเว็บ drone-sitl การอัปโหลด/pull ที่ `:8090` ต้องมี token ที่ flight-service สุ่มไว้ (`DRONE_SITL_UPLOAD_TOKEN`, ตัดสินใจ 2026-10-05: รับงานได้แค่ทาง curl / ระบบพี่ต้น)
- ⚠️ อ่าน manifest ในไฟล์ `.gz` ต้องคลายไฟล์ทั้งไฟล์ (หลายนาทีสำหรับ 12 GB) ถ้าเป็น `.tar` ธรรมดาจะเร็วกว่ามาก

### ทำเมื่อไร

- **ส่วน A:** registry ก่อน (ใส่ `source` ใน job และแยก `_acquire()` ใน worker ไว้แล้ว)
- **ส่วน B:** รับไฟล์**ทั้งสองแบบ** (ตัดสินใจ 2026-10-05) ทำต่อจากส่วน A แยก gate ของตัวเอง

---

## 13. Kill API + ระบบเก็บข้อมูลแบบ journal (อนุมัติ 2026-10-05: POST, ลบเฉพาะของที่งานนำเข้ามา, เก็บย้อนหลัง 10 GB)

### 13.1 ปัญหาของ design เดิม

| เรื่อง | design เดิม | ผล |
|---|---|---|
| cancel ระหว่างบิน | ข้ามขั้น collect ทั้งหมด | ได้ `cancelled` แต่ไม่มี `result` ข้อมูลที่บินมาแล้วหาย |
| runner ตาย (SIGKILL/ไฟดับ) | recover ตั้งเป็น `failed` | track ยังอยู่บนดิสก์แต่ไม่มี `result.json` |
| panel log | ได้จาก det_recorder **ตอนจบเท่านั้น** | ถ้า joystick-server ตายก่อน log หายทั้งหมด |
| สร้าง result | มีทางเดียวคือตอนจบปกติ | จบแบบปกติ / kill / timeout / crash ได้ไฟล์ไม่เหมือนกัน |
| ข้อมูลเก่า | ไม่มีการจำกัด | ดิสก์ใช้ไปแล้ว 94% และแต่ละรอบ ~35 MB (คลิป 34 MB) |

### 13.2 แนวคิด: journal + finalize

1. **Journal (append-only, JSON Lines):** ทุกครั้งที่ได้ข้อมูลใหม่ ต่อท้ายไฟล์ 1 บรรทัด → `flush` ทันที → `fsync` ทุก 1 s ไฟล์**ไม่เคยถูกเขียนทับ** ถ้า process ตายกลางทาง จะเสียได้มากสุดแค่บรรทัดสุดท้ายที่เขียนไม่ครบ ซึ่งตัวอ่านข้ามได้
2. **Snapshot (atomic replace):** `job.json` เก็บสถานะล่าสุด เขียนลงไฟล์ `.tmp` ก่อนแล้ว `os.replace` จึงไม่มีทางเห็นไฟล์ที่เขียนไปครึ่งเดียว (มีอยู่แล้วใน design)
3. **Finalize (ฟังก์ชันเดียว, รันซ้ำได้):** สร้าง `result.json` และ `score.json` **จาก journal บนดิสก์เท่านั้น** ทุกทางจบเรียกฟังก์ชันนี้ ได้แก่ จบปกติ, kill, timeout, agent crash และ recover หลัง runner ตาย ผลจึงมีรูปแบบเดียวกันเสมอ ต่างกันที่ `partial: true/false` และ `ended_by`

**ทำไมเขียนลงโฟลเดอร์ของรอบนั้นตรงๆ แทนไฟล์ชั่วคราว:** journal ทนการตายกลางทางได้อยู่แล้ว ถ้าเขียนลงไฟล์ชั่วคราวก่อน ตอนโดน kill ก็ต้องย้ายไฟล์เหล่านั้นอยู่ดี
ไฟล์ "ชั่วคราว" จึงคือ journal ในโฟลเดอร์รอบนั้น โดยมี marker `RUNNING` บอกว่ายังไม่ finalize

### 13.3 โมดูลกลาง `journal.py` (ใช้ซ้ำได้ทุกที่)

ไม่พึ่งอะไรใน flight-service จะ copy ไปใช้กับโปรเจกต์อื่นหรือ service ตัวถัดไปได้ทั้งไฟล์

```python
j = Journal(run_dir / "telemetry.jsonl", fsync_every_s=1.0)
j.append({"t": 12.4, "lat": ..., ...})        # 1 บรรทัด + flush
j.close()
rows = list(read_jsonl(path))                 # ข้ามบรรทัดท้ายที่เขียนไม่ครบ
write_atomic(run_dir / "job.json", data)      # tmp + os.replace
```

### 13.4 ไฟล์ของแต่ละรอบ (`data/runs/<job_id>/`)

| ไฟล์ | ชนิด | เขียนเมื่อ | มาจาก |
|---|---|---|---|
| `RUNNING` | marker | สร้างตอนเริ่ม ลบตอน finalize | runner |
| `job.json` | snapshot | ทุกครั้งที่ state เปลี่ยน + ทุก 5 s | runner |
| `telemetry.jsonl` | journal | ทุกเฟรม 5 Hz (**เก็บทุกฟิลด์ที่ /ws ส่งมา** ไม่ใช่แค่บางฟิลด์) | `/ws` |
| `events.jsonl` | journal | state เปลี่ยน, บรรทัด log ใหม่ของ agent, kill, error, timeout | runner + `/ws` |
| `detections.jsonl` | journal | ทุกเฟรมที่มีกล่อง (กล่อง + ตำแหน่งโดรน) | `/ws` (runner เก็บเองระหว่างบิน) |
| `detections.mp4`, `meta.json` | ไฟล์ | ตอน finalize (copy จาก det_recorder ถ้ามี) | drone-sitl |
| `score.json`, `result.json`, `analysis.txt` | ไฟล์ | finalize | runner |

- `track.jsonl` และ `panel.log` เดิม → **สร้างจาก journal ตอน finalize** (ให้ `fly_headless.analyze()` ใช้ได้ต่อ)
- score v0 คิดจาก `detections.jsonl` ที่ runner เก็บเอง จึงไม่ต้องพึ่งไฟล์ของ drone-sitl อีก

### 13.5 Kill API

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" $R/jobs/<id>/kill        # id หาได้จาก GET /jobs
# → 200 {...job, "state":"killed", "result":{"partial":true,"ended_by":"kill", ..., "files":{...}}}
```

| state ตอนสั่ง | ทำอะไร | ได้อะไรกลับ |
|---|---|---|
| `pulling` / `booting` | หยุดขั้นนั้น → cleanup | `killed` + events.jsonl (ยังไม่ได้บิน) |
| `flying` | ส่ง stop ให้ agent → รอ det_recorder ปิดคลิป (≤ 30 s) → finalize → cleanup | `killed` + **ข้อมูลทั้งหมดที่บินมาถึงตอนนั้น** |
| จบไปแล้ว | — | `409` |

- **ตอบกลับหลัง finalize เสร็จ** (รอไม่เกิน `KILL_WAIT_S`=60 s) ข้อมูลที่เก็บมาจึง "ส่งกลับ" ไปใน response ของ kill เลย ไม่ต้องยิง GET ซ้ำ ถ้าเกินเวลาตอบ `202` แล้วให้ poll ต่อ
- **หยุดแบบนุ่มก่อน แล้วค่อยแรงขึ้นตามเวลา:** stop agent (รอ 10 s) → `docker rm -f` → `stop-website.sh` ทั้งนี้เพื่อให้ det_recorder ปิดไฟล์ mp4 ได้ทัน เพราะ mp4 ที่ไม่ได้ปิดไฟล์จะเล่นไม่ได้
- state ใหม่ `killed` แยกจาก `failed` เพื่อให้รู้ว่าคนสั่งหยุดเอง ไม่ใช่ระบบพัง (มาแทน `cancelled` เดิม)
- **POST ไม่ใช่ GET** (ตัดสินใจ 2026-10-05): ตามมาตรฐาน HTTP GET ต้องไม่เปลี่ยนสถานะระบบ proxy และระบบแชต (preview ลิงก์) จึงยิง GET เองได้ ถ้าใช้ GET อาจ kill งานโดยไม่ตั้งใจ
- ไม่มี `/jobs/current/kill` เพราะซ้ำกับ `/jobs/{id}/kill` และการระบุ id ชัดเจนกันการ kill ผิดงานถ้างานเปลี่ยนไปแล้ว

### 13.6 ทุกครั้งที่รันเสร็จ: ลบ image + container แต่เก็บ data

- **ลบเสมอ** (ทุกทางจบ รวม kill และ crash): container ของงานนั้น, tag `submission-*` ที่ retag, และ ref ที่ pull มาในงานนั้น
- **ข้อยกเว้นเดียว:** ref ที่**มีบนเครื่องอยู่แล้วก่อนเริ่มงาน** จะไม่ลบ เพราะไม่ใช่ของงานนี้ (กับดัก 6: อาจเป็นของคนอื่น)
- **เก็บ data:** `data/runs/<id>/` ไม่ลบหลังจบ ดูย้อนหลังได้ด้วย `GET /jobs` และ `/jobs/{id}/files/*`
- **retention:** เก็บรวมไม่เกิน `DATA_RETENTION_GB` (default 10 GB ≈ 280 รอบ) เกินแล้วลบรอบที่เก่าที่สุดก่อน และลบเฉพาะใน `data/runs/` ถ้าไม่อยากให้ลบเองเลย ตั้งเป็น 0

### 13.7 ข้อจำกัด

- runner ตายแบบ SIGKILL ระหว่างบิน: journal ทุกไฟล์ยังครบ แต่ mp4 อาจเล่นไม่ได้ เพราะ det_recorder ใช้ `+faststart` ซึ่งเขียน index ตอนปิดไฟล์
  แก้ได้ด้วย fragmented MP4 แต่ต้องแก้ drone-sitl จึงยังไม่ทำ · ตอน recover จะ finalize ให้อัตโนมัติและระบุ `partial: true, ended_by: "runner_restarted"`
- ไฟดับ: เสียข้อมูลได้มากสุด ~1 s สุดท้าย (รอบ `fsync`)

### 13.8 ชื่อเรียกทาง technical

| สิ่งที่ขอ | ชื่อ |
|---|---|
| ไฟล์ที่ต่อท้ายทุกครั้งที่มีข้อมูลใหม่ | **append-only log / journaling** (หลักเดียวกับ **write-ahead log, WAL** ของ database) · รูปแบบไฟล์ **JSON Lines (NDJSON)** |
| เขียนแล้วไม่หายถ้าเครื่องดับ | **durability** (`flush`/`fsync`) · ระบบแบบนี้เรียก **crash-safe / crash-consistent** |
| ไฟล์สถานะล่าสุดที่ไม่มีวันอ่านเจอครึ่งไฟล์ | **atomic write** (write-temp-then-rename) · ไฟล์แบบนี้เรียก **snapshot** |
| journal + snapshot | แนวคิดเบาๆ ของ **event sourcing** |
| โดน kill แล้วยังได้ข้อมูลที่เก็บมา | **graceful shutdown/termination** + **partial results** · ขั้นสร้างผลเรียก **finalizer** ซึ่งต้อง **idempotent** (รันซ้ำได้ ผลเท่าเดิม) |
| stop นุ่ม → แรงตามเวลา | **timeout escalation** (เหมือน SIGTERM แล้วตามด้วย SIGKILL) |
| เปิดใหม่แล้วกู้งานที่ค้าง | **crash recovery on startup** |
| ลบ image/container แต่เก็บ data | **ephemeral compute, persistent artifacts** · การลบเรียก **teardown / resource cleanup** · การเก็บเรียก **artifact retention** (+ **retention policy**) |
| ระบบรวมทั้งหมด | **job runner + artifact store** แบบเดียวกับ CI (GitHub Actions, GitLab Runner) |
