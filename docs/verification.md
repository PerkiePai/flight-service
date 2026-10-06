# ขั้น 4: ทดสอบจริง (plan Task 13) · 2026-10-05

> **สรุป: ผ่าน** บินจบ `done` ได้ track + คลิป + score ครบ · kill ระหว่างบินได้ข้อมูลที่เก็บมา · pull ล้มได้ `failed` พร้อมเหตุผล · ทุกรอบปิด sim และลบ image ของงานนั้นแล้ว · เจอบั๊ก 1 จุดตอนบูต (แก้แล้ว `c070270`)

- เครื่อง: RTX 5090 · drone-sitl `feat/website-usd-map-testgs` @ `1b2ba82` (มี `DRONE_SITL_DOCKER_RUN_ARGS`) · flight-service `feat/core`
- image ทดสอบ: `perkiepai/truck-detector:20260929-214240` (digest `sha256:70360ee7…`) บน Docker Hub แบบ **private** (สร้าง repo ผ่าน API ด้วย `is_private: true` ก่อน push · เปิดดูโดยไม่ login ได้ 404)
- ผู้เรียก: `scripts/mock-caller.sh` ทำตัวเป็นพี่ต้น บนเครื่องเดียวกัน (`127.0.0.1:8095`) · log ดิบ: `docs/verification-run*.log`

## ก่อนรัน

| ตรวจ | ผล |
|---|---|
| ดิสก์ว่าง | 112 GB (ใช้ไป 94%) |
| sim / เว็บ (:8080 / :8090) | ไม่ได้เปิด |
| GPU | RTX 5090 ใช้อยู่ 971 MiB / 32607 MiB · 0% |

## รอบ 1: บินเต็ม ✅ (`j-20261005-033950-b5fa`)

| state | เวลา (นับจาก POST) |
|---|---|
| `queued` → `pulling` | 0 s |
| `booting` | 20 s (image อยู่บนเครื่องแล้ว pull จึงเร็ว) |
| `flying` | 55 s (Isaac + PX4 บูต ~35 s) |
| `done` | 547 s (agent log `DONE sweep complete (6/6 waypoints)`) |

- **result:** `ended_by: agent` · `partial: false` · บิน 484.8 s · ระยะ 556.2 m · **score v0 = 95.6** (recall 1.0, precision 0.916, รถ 3/3) · `missing: []`
- **ไฟล์ที่พี่ต้นโหลดได้ (10 ตัวครบ):** `detections.mp4` 34.5 MB (h264 640×480, 487.5 s, 4875 เฟรม, ffprobe เปิดได้) · `telemetry.jsonl` 3.4 MB (2413 เฟรม) · `track.jsonl` · `detections.jsonl` · `events.jsonl` · `panel.log` · `meta.json` · `score.json` · `result.json` · `analysis.txt`
- **analysis.txt (เทียบรถจริงด้วยตัวตรวจของ drone-sitl):** DETECT 3 ครั้งห่างรถจริง 0.9 / 1.2 / 3.6 m · บินอยู่ในแผนที่ · DETECT ครั้งที่ 4 คือกล่องหลอกที่ (−77, 28) ที่รู้อยู่แล้ว
- **resource limit ของ container ตอนบิน:** `memory=24 GiB · pids=1024 · CapDrop=[ALL] · no-new-privileges · GPU requested` → **`--cap-drop ALL` ไม่ทำให้ GPU/agent พัง** (agent ตรวจจับรถได้ตามปกติ)
- **เว็บที่เปิดก่อน PX4 (`SKIP_SIM=1`) ยังได้ลิงก์ MAVLink** → ไม่ต้องใช้ทางสำรองใน plan

## รอบ 2: kill ระหว่างบิน ✅ (`j-20261005-034925-8cfb`)

- `KILL_AFTER_S=90` → `POST /jobs/{id}/kill` ตอบ **200** (จบรวม cleanup ใน ~7 s ไม่ต้องรอแบบ 202)
- **response:** `state: killed` · `failed_in: flying` · `ended_by: kill` · `partial: true` · มีข้อมูล 91.6 s · score 79.8 (เจอรถ 2/3 ก่อนถูก kill) · `missing: []`
- คลิปที่ปิดไฟล์กลางทาง `detections.mp4` 7.8 MB ยาว 94.4 s เล่นได้

## รอบ 3: pull ล้ม ✅ (`j-20261005-035201-32ab`)

- `perkiepai/does-not-exist:0` → `failed` · `failed_in: pulling` · `reason: pull_failed` · detail มีข้อความจาก Docker (`failed to resolve reference …`) · จบใน 10 s
- เว็บที่เปิดไว้สำหรับ pull ถูกปิดแล้ว

## รอบ 4 (เพิ่มตามคำแนะนำของ reviewer): ช่องรอ, ดาวน์โหลดระหว่างบิน, SIGTERM ✅

| ทดสอบ | ผล |
|---|---|
| ระหว่างงาน A บิน ส่งงาน B | `202 queued` (เข้าช่องรอ) |
| ส่งงาน C | `409 {"detail":"busy","current_job":A,"pending":[B]}` · `/healthz` → `ready:false, pending:1` |
| โหลด `telemetry.jsonl` ระหว่างบิน 3 ครั้ง | `200` · ขนาดที่ได้ = `Content-Length` ทุกครั้ง |
| `stop-service.sh` (SIGTERM) กลางบิน | service ปิดทันที · A ยังเป็น `flying` (ไม่ถูกบันทึกเป็น killed) · RUNNING marker อยู่ · sim ยังเปิด |
| `run-service.sh` เปิดใหม่ | ตอบใน 4 s · A → `failed / runner_restarted` (`partial`, ข้อมูล 58 s) · B → `failed / runner_restarted` (ไม่ถูกเริ่ม) · sim ถูกปิด · container/tag ถูกลบ |

- คลิปของ A หาย (`missing: detections.mp4`) ตามข้อจำกัดที่ระบุใน design 13.7: det_recorder ปิดไฟล์ไม่ทันเพราะ sim ถูกปิดตอน recovery

## ตรวจหลังทุกรอบ

| ตรวจ | ผล |
|---|---|
| `/healthz` | `{"ok":true,"ready":true,"phase":"idle","pending":0}` ทุกรอบ |
| :8080 / :8090 | ไม่ตอบ (sim + เว็บถูกปิด) |
| `docker ps -a \| grep submission-run` | ว่าง |
| image | เหลือแค่ `submission-truck-detector-20260929-214240` และ `perkiepai/truck-detector:20260929-214240` ที่มีอยู่ก่อนเริ่ม · tag `submission-truck-detector-20261005-*` ของแต่ละงานถูกลบหมด |
| `data/runs/` | 6 งาน รวม 47 MB (เก็บไว้ดูย้อนหลัง) |

## ปัญหาที่เจอ

1. **รอบ 1 ครั้งแรกล้มด้วย `sim_boot_timeout` ใน 70 ms หลังเริ่ม `booting`** (`j-20261005-033711-4616`, log `verification-run1-attempt1.log`)
   - **ต้นเหตุ (race ใน drone-sitl `sim/run-website.sh`):** ลูปรอ Isaac เช็ก `isaac_running` (หา process `sim/bootstrap.py`) รอบแรกทันทีโดยไม่ sleep ก่อน ตอนนั้น `launch-sitl.sh` ยังไม่ `--exec` bootstrap.py สคริปต์จึงพิมพ์ "Isaac Sim exited before coming up" แล้วคืนค่าทันที ทั้งที่ Isaac ยังบูตอยู่ (log ของ Isaac บูตต่ออีก ~11 s จน cleanup ปิด)
   - **แก้ฝั่ง flight-service (`c070270`):** `SimControl.start_sim` รอ `:8080` เองจนครบ `BOOT_TIMEOUT_S` และ fail เร็วเฉพาะเมื่อผ่าน 30 s แล้ว process Isaac หายไปจริง · เทสต์ใหม่ 2 ตัว (RED → GREEN) · ชุดเทสต์ 96/96
   - **drone-sitl ไม่ได้แก้** (ต้องขออนุมัติ) · ถ้าจะแก้ต้นทาง: ให้ลูปใน `run-website.sh` `sleep` ก่อนเช็ก `isaac_running` หรือให้เวลาผ่อนผันสัก 10–30 s
   - cleanup ของรอบที่ล้มถูกต้อง: sim ปิด, tag ของงานถูกลบ, image ต้นทางยังอยู่
2. **ยังไม่ได้ทดสอบ: kill ระหว่าง pull** (reviewer แนะนำ) · image อยู่บนเครื่องแล้ว pull จึงจบใน ~5 s จับจังหวะไม่ได้ · ความเสี่ยงที่ image ค้างยังอยู่ในรายการ deferred

---

# ส่วน B4: ทดสอบจริงแบบอัปโหลดไฟล์ · 2026-10-05

> **สรุป: ผ่าน** ทั้งสองแบบบินจบ `done` · หลังแก้ตามรีวิวรอบ B ทดสอบซ้ำบนของจริง: archive ปกติผ่าน, archive ที่ชื่อชนของเดิมถูกปฏิเสธก่อน load · drone-sitl `run-website.sh` ที่แก้ race (`bda585c`) ใช้บูตทุกรอบ ไม่มี boot ล้มอีก

| รอบ | ไฟล์ | ผล |
|---|---|---|
| archive (`docker save`) | 4.4 GB (`truck-upload-test:1` ชั่วคราว) | `curl -T` 4.7 s → `202` · `loading` ~10 s · บิน 507 s · **`done` score 94.6 (3/3)** · ไฟล์ครบ (`j-20261005-040637-9b2e`) |
| bundle (Dockerfile + โค้ด) | 128 MB (`truck-detector.tar`) | `202` ใน 0.08 s · drone-sitl build ~4.7 นาที · บิน 484 s · **`done` score 97.6 (3/3)** · ไฟล์ครบ (`j-20261005-041618-4526`) |
| **หลังแก้รีวิว:** archive ชื่อชน | `docker save hello-world` (index.json ตั้งชื่อ `docker.io/library/hello-world:latest` ซึ่งมีอยู่แล้ว) | `failed / loading / archive_rejected` ก่อน `docker load` · image เดิม ID ไม่เปลี่ยน · ไฟล์อัปโหลดถูกลบ (`j-20261005-043015-9deb`) |
| **หลังแก้รีวิว:** archive ปกติ + kill | 4.4 GB | ชื่อจาก `manifest.json` และ `index.json` รวมเป็น `docker.io/library/truck-upload-test:1` ชื่อเดียว · ชื่อหลัง load ตรงกับที่ตรวจ · ระหว่างบินเหลือแค่ tag `submission-truck-detector-20261005-043118` · kill → `200 killed` (`j-20261005-043109-3d64`) |

**ตรวจหลังทุกรอบ:** sim ปิด · `/healthz` idle · tag ชั่วคราวและ tag `submission-…` ของแต่ละงานถูกลบ · `data/uploads/` ว่าง · image ต้นทางที่มีอยู่ก่อนไม่ถูกแตะ · ดิสก์ว่าง 111 GB

**ข้อสังเกต:** drone-sitl เก็บสำเนา bundle ทุกไฟล์ไว้ใน `logs/docker-agents/` (ไฟล์ละ 128 MB) ตามพฤติกรรมเดิมของมัน · บันทึกเป็น minor (M4)

---

# แก้ข้อเล็ก 2 ข้อ · 2026-10-05

| ข้อ | แก้ | ทดสอบ |
|---|---|---|
| **kill ระหว่าง pull ทิ้ง image ไว้** · ต้นเหตุ: `docker pull` รันใน process ของเว็บ drone-sitl การยกเลิก request ของเราไม่หยุดมัน และ `stop-website.sh` ก็ไม่ปิด process ลูกนี้ | cleanup ของงานที่ pull ยังไม่จบ ส่ง SIGTERM ให้ `docker pull <ref>` (หาด้วย argv ตรงตัว ตาม PID ไม่ใช้ pattern) แล้วลบ tag `submission-<ชื่อ>-<เวลา>` ที่เกิดหลังเริ่ม pull และ ref ที่ไม่ได้มีอยู่ก่อน (`2f598f9`) | **ของจริง:** pull `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime` (~3 GB, เพิ่มใน allowlist ชั่วคราวผ่าน env) · 8 s หลังเริ่มมี `docker pull` pid 864163 · kill → `killed / pulling` · หลังจากนั้นไม่มี `docker pull` ค้าง ไม่มี image/tag pytorch · log: `stopped the docker pull left running (pids [864163])` (`j-20261005-100420-3d2c`) · เปิด service กลับเป็น allowlist ปกติแล้ว (pytorch → 403) |
| **`/ws` หลุดแล้วงานจบทันที** | ต่อใหม่ภายใน `RECONNECT_S` = 10 s โดยไม่ส่ง RUN ซ้ำ สถานะการติดตาม (เวลาบิน, arming, DONE) คงอยู่ · นับว่ากลับมาเมื่อได้ telemetry จริงเท่านั้น (กัน server ที่รับ connection แต่เงียบ) · บันทึก `ws_lost`/`ws_reconnected` ใน events.jsonl (`e57553b`) | เทสต์: หลุดแล้วต่อได้ → บินต่อจนจบ, RUN ครั้งเดียว · ต่อครั้งแรกไม่ติดแล้วลองใหม่ · ต่อไม่ได้ใน 10 s → `ws_lost` · (ทดสอบจริงทำได้ยากเพราะต้องตัด TCP socket กลางทางซึ่งต้องใช้สิทธิ์ root) |


---

# vendor drone-sitl: บินจริงบนสำเนา · 2026-10-06

> **สรุป: ผ่าน** service รันจาก `vendor/drone-sitl` (`2945783` + patch 0001) และ `vendor/maps/nt-testgs` · ไม่มี process จาก `~/pai/drone-sitl` · รอบแรกถูกสคริปต์ของโปรเจกต์อื่นฆ่า Isaac กลางบิน (บันทึกไว้ด้านล่าง) จึงบินใหม่

| รอบ | ผล |
|---|---|
| preflight | ทุกข้อ ok · `drone-sitl (vendored @ 2945783)` · `map … (SHA256SUMS ok)` (`docs/verification-vendor-preflight.log`) |
| รอบ 0: registry `perkiepai/truck-detector:20260929-214240` | **ล้ม** `arming_timeout` (`j-20261006-022911-a24b`) score 0.0 0/3 · สาเหตุที่สอดคล้องกับหลักฐาน: `~/friend/scene/scenev2/ardu/run_ardu_isaac.sh` (บรรทัด 39–40 `kill -9` ทุก `isaacsim.exp.full.streaming.kit`) เริ่มทำงานกลางเที่ยวบิน · ยังไม่ได้พิสูจน์ตรงๆ · สำเนา vendor บูต โหลดแผนที่ ต่อ PX4 และ takeoff ได้ก่อนถูกฆ่า (`docs/verification-vendor-run0-killed*.{log,txt}`) |
| รอบ 1: registry เดิม (บินใหม่ ตอนไม่มี sim อื่น) | `done` score **94.4** (3/3) · `j-20261006-075228-1529` (`docs/verification-vendor-run1.log`) · รอบเดิมก่อน vendor: 95.6 |
| รอบ 2: bundle `truck-detector.tar` | `done` score **96.8** (3/3, recall 1.0, precision 0.938) · `j-20261006-080241-fbb3` (`docs/verification-vendor-bundle.log`) · รอบเดิมก่อน vendor: 97.6 |
| process (ระหว่างรอบ 1) | Isaac kit รันด้วย `--exec …/vendor/drone-sitl/sim/bootstrap.py` · cwd ของ kit และ joystick-server = `vendor/drone-sitl` · process ที่มี `pai/drone-sitl/` ในคำสั่ง 0 ตัว · layer ใน `/proc/<pid>/maps` ทั้ง 3 อยู่ใน `vendor/maps/nt-testgs/` (`docs/verification-vendor-proc.txt`) |
| หลังจบ | พอร์ต 8080/8090 ปิด · `/healthz` ready · `git status vendor/` ว่าง · `vendor/drone-sitl/logs/launch-sitl.console` อยู่ (ถูก ignore) |

ข้อจำกัด: หลักฐาน process เก็บเฉพาะรอบ 1 (ไม่ได้เก็บซ้ำรอบ bundle) · ไฟล์ input ของรอบ bundle (`truck-detector.tar`) อ่านจาก `~/pai/drone-sitl/examples/` เป็นแค่ข้อมูลเข้า ไม่ใช่การพึ่ง checkout · สคริปต์เก็บหลักฐานรวมในแผนถูก hook เขียนทับ จึงรันทีละคำสั่งแทน ผลเหมือนกัน · ความต่างของ score จากรอบเดิม (−1.2 และ −0.8) ไม่ได้สืบหาสาเหตุ (เส้นทางบิน/ตรวจจับมีความสุ่ม)

## Stream สด (SSE) + client `flight.py` · 2026-10-06

> **สรุป: ผ่านทุกรอบ** · flight-service `feat/sse-client` @ `f85ef88` · ผู้เรียก: `scripts/flight.py` บนเครื่องเดียวกัน · log ดิบ: `docs/verification-sse-*`

| รอบ | ทำอะไร | ผล |
|---|---|---|
| 1a | `flight.py run perkiepai/truck-detector:20260929-214240` แล้ว `SIGTERM` client หลังบิน 30 s | exit `3` · JSON `state: flying` · งานบน service ยัง `flying` หลัง client ตาย (`j-20261006-083909-c92b`) · log จบด้วย `interrupted. Job ... was NOT killed` + วิธี `watch` / `kill` |
| 1b | `flight.py watch j-20261006-083909-c92b` ต่อจนจบ | exit `0` · `done` / `null` · score `97.0` · บิน `487.46` s · ไฟล์ `10` ตัว ตรงกับ `data/runs/` ทุกตัว (`cmp` same ครบ ไม่มี `.part`) · `not_downloaded: []` |
| 1 | stream ทั้งสายหลังจบ | event `telemetry` `2426` ตัว = `telemetry.jsonl` `2426` บรรทัด · `Last-Event-ID: 100` → เริ่มที่ `id: 101` |
| 2 | `flight.py run --file` ไฟล์ 2 GB (`truncate -s 2G`, ไม่เปิด sim) | exit `1` · `failed` / `archive_rejected` · ใช้เวลา `1.27` s · RAM สูงสุดของ client `26,920` kB (~27 MB) |

**ตรวจหลังทุกรอบ:** `/healthz` = `{"ok":true,"ready":true,"phase":"idle","pending":0}` · sim ปิด (`:8080` → `000`) · `data/uploads/` ว่าง (0 ไฟล์)

**ตัวอย่าง stream ดิบ:** `docs/verification-sse-stream-sample.txt` ขึ้นต้น `event: state` + `data: {"state":"flying",...}` ตามด้วย `id: 1` / `event: telemetry`

**สิ่งที่พบ:** ไม่มีข้อที่ต่างจากที่คาด · งานบินจบ `done` (ต่างจากงานก่อนหน้าที่จบ `arming_timeout`: รอบนี้ไม่มีใครเปิด sim ทับ) · ไฟล์ทดสอบ 2 GB วางไว้ใน scratchpad ของ session แทน `/tmp` ตามแผน แล้วลบทิ้งหลังรัน · service ตัวจริงบน `:8095` ตอนนี้รันโค้ดของ `feat/sse-client`
