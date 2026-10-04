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

