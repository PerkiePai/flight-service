# flight-service: แผนงานและความคืบหน้า

> ทุกขั้นหยุดรออนุมัติก่อนเริ่มขั้นถัดไป · อัปเดตไฟล์นี้ทุกครั้งที่ขั้นเปลี่ยนสถานะ

| # | ขั้น | ส่งมอบ | สถานะ |
|---|---|---|---|
| 1 | Design | `docs/design.md` | ✅ อนุมัติ 2026-10-05 · เพิ่มหัวข้อ 12 (รับไฟล์ image) หลังอนุมัติ |
| 2 | โครงโฟลเดอร์ + แผน | `docs/plan.md` v3 (Task 1–14 + ส่วน B1–B4) · สรุป API + diagram 8 ภาพ: `docs/api.md` | ✅ อนุมัติ 2026-10-05 |
| 3 | โค้ด + เทสต์ (ของปลอม ไม่เปิด sim) | plan Task 1–12 · pytest ผ่าน · แก้ drone-sitl + หลักฐาน | ✅ Task 1–12 เสร็จ · review ทั้ง branch แล้ว (แก้ Important 3 + docs routes ใน `234a650`) · drone-sitl 255 ผ่าน (`ed5f998`, `1b2ba82`) · smoke test ผ่าน · branch `feat/core` |
| 4 | ทดสอบจริง | plan Task 13 · บินเต็ม + kill + pull ล้ม + (เพิ่ม) ช่องรอ/ดาวน์โหลดระหว่างบิน/SIGTERM · `docs/verification.md` | ✅ ผ่านทุกรอบ · บินจบ score 95.6 รถ 3/3 · เจอ race ตอนบูตใน run-website.sh แก้ฝั่งเรา (`c070270`) · ⛔ รออนุมัติขั้น 5 |
| 5 | README | plan Task 14 | ✅ `README.md` (ทำตามจริง 1 รอบ) |
| B | รับไฟล์ image ผ่าน curl (archive + bundle) | design 12 · plan B1–B4 | ✅ โค้ด + review (แก้ Critical 3 + Important 3 ใน `5d368b6`) · บินจริงทั้งสองแบบ `done` · 145 tests ผ่าน |

## โครงโฟลเดอร์ (สร้างใน Task 1)

```
flight-service/
├── README.md                 ขั้น 5
├── pytest.ini · .gitignore · .env.example
├── flight_service/           หนึ่งไฟล์ = หนึ่งหน้าที่
│   ├── __main__.py           python -m flight_service
│   ├── config.py             env → Settings (timeout/limit ทั้งหมด)
│   ├── jobs.py               Job, JobStore (jobs/<id>/job.json), state
│   ├── policy.py             allowlist, ขนาด image, ดิสก์
│   ├── dockerctl.py          docker CLI (เฉพาะ tag/container ของงาน)
│   ├── sim.py                run/stop-website.sh, รอ "Ready for takeoff"
│   ├── sitl.py               HTTP :8090 (pull-docker, detrec)
│   ├── flightsession.py      บินผ่าน /ws + timeout
│   ├── score.py              detection score v0
│   ├── journal.py            journal กลาง (ใช้ซ้ำได้)
│   ├── runlog.py · finalize.py · retention.py
│   ├── uploads.py · archive.py      (ส่วน B)
│   ├── worker.py             คิว + pipeline + kill + recover
│   └── app.py                HTTP API 6 endpoint + token
├── scripts/                  run-service.sh · stop-service.sh · mock-caller.sh
├── tests/                    fakes.py + test_<module>.py (ไม่เปิด sim)
├── docs/                     design · plan · progress · drone-sitl-changes · verification
└── data/runs/ data/uploads/ logs/ run/ mock-out/   (runtime, ไม่เข้า git)
```

## บันทึกการตัดสินใจ

| วันที่ | เรื่อง | ตัดสินใจ |
|---|---|---|
| 2026-10-05 | ที่ตั้งโปรเจกต์ | `~/pai/flight-service/` (เดิม `drone-sitl-runner` ลบแล้ว) |
| 2026-10-05 | ข้อ d | A (poll) + ลิงก์ MP4 หลังจบ · detection score v0 |
| 2026-10-05 | image ทดสอบ | push ขึ้น Docker Hub `perkiepai/...` (private/public ยืนยันก่อน push) |
| 2026-10-05 | sim เปิดค้างอยู่ | `sim_busy` ไม่ยึดของคนอื่น |
| 2026-10-05 | ผู้เรียก | ยังไม่รู้ ทดสอบบนเครื่องตัวเอง bind 127.0.0.1 + mock-caller |
| 2026-10-05 | แก้ drone-sitl | อนุมัติ `DRONE_SITL_DOCKER_RUN_ARGS` + หลักฐานทั้งสองโปรเจกต์ |
| 2026-10-05 | รับไฟล์ image | เผื่อไว้ใน design 12 โครงโค้ดรองรับ ทำจริงในส่วน B |
| 2026-10-05 | kill + เก็บข้อมูล | design 13 อนุมัติ: journal + finalize ตัวเดียว · kill ใช้ **POST** · ลบ**เฉพาะสิ่งที่งานนำเข้ามา** · เก็บ data ย้อนหลัง **10 GB** |
| 2026-10-05 | API | รวมเหลือ 6 endpoint ไม่ซ้ำกัน (design 3): ไม่มี `/jobs/upload`, `/cancel`, `/jobs/current/kill` · `/healthz` ไม่บอกข้อมูลงาน |
| 2026-10-05 | วิธีลงมือ | Native · commit drone-sitl บน `feat/website-usd-map-testgs` · ส่วน B ทำทั้ง archive และ bundle · ผู้เรียกชื่อ "พี่ต้น" |
| 2026-10-05 | สั่งบิน | ต่อ `/ws` เอง ไม่ import `fly()` (เหตุผลใน design 10) |
| 2026-10-05 | คิว | **คิวหลักอยู่ที่ระบบพี่ต้น** · worker มีช่องรอเล็ก `MAX_PENDING=1` ไว้กันจังหวะชน/ตรวจเทียบ · เต็ม → `409` · degraded → `503` · `/healthz` = `ready`+`pending` · state จบตั้งหลัง cleanup · ตัดเทสต์คิวใหญ่เดิมออก (design 5, plan v3) |
| 2026-10-05 | Docker Hub | `perkiepai/truck-detector` สร้างเป็น **private** ก่อน push (ตามที่สั่ง) |
\n| 2026-10-05 | drone-sitl race | แก้ `run-website.sh` ที่ต้นทาง (`bda585c`) ตามที่อนุมัติ + หลักฐานทั้งสองโปรเจกต์ |\n