# แผนที่ public / private และกติกาการแข่ง (wishlist 6)

> สถานะ: **ร่าง รออนุมัติ** · 2026-10-16 · ผู้ใช้ข้ามคำถาม ข้อที่ไม่ได้มาจากผู้ใช้ติดป้าย **(เลือกเอง)**

## 1. ทำไม

ผู้แข่งจะได้ฝึกและวัดผลบน **test map (public)** แต่ผลแข่งจริงวัดบน **competition map (private)** ที่ทีมไม่เคยเห็น (ผู้ใช้กำหนด) · วันนี้ระบบมีแผนที่เดียว (`nt-testgs`) ตำแหน่งรถตายตัว ทีมจำพิกัดรถแล้วบินไปหาได้โดยไม่ต้องตรวจจับเก่ง · ส่วนอื่นที่ค้างจากการตอบ wishlist 6: agent ไม่รู้เวลาที่เหลือ และเอกสารผู้แข่งของ drone-sitl ไม่ตรงกับ package จริง

## 2. เป้าหมาย / ไม่ทำ / ห้ามเกิด

**เป้าหมาย**
- G1 ผู้เรียกเลือกได้ทีละงานว่าบิน `public` หรือ `private` · ไม่ระบุ = `public` (ผู้เรียกเดิมทำงานเหมือนเดิม)
- G2 ตำแหน่งรถของ private map ไม่หลุดถึงทีม: ไม่อยู่ใน git, ไม่อยู่ใน image, ไม่อ่านได้จากใน container ของ agent
- G3 agent รู้เวลาที่เหลือ (`state.time_remaining` ไม่เป็น `None`)
- G4 คู่มือผู้แข่งที่ตรงกับของจริง

**ไม่ทำ:** ระบบทีม (wishlist 4 เลือก B: ระบบพี่ต้นจับคู่ job ↔ ทีมและเลือก map เอง) · score v1 · เครื่องมือสร้างแผนที่ · สเปกโดรนรายงาน · เปลี่ยน allowlist

**ห้ามเกิด:** พิกัดรถ private อยู่ในไฟล์ที่ commit · ทีมรู้ตำแหน่งรถ private ระหว่างบินผ่าน API ของเรา · ผู้เรียกเดิมที่ไม่ส่ง `map` ได้ผลต่างจากวันนี้

## 3. Design

### 3.1 แผนที่อยู่ที่ไหน
- **public:** `vendor/maps/<name>/` ใน git เหมือน `nt-testgs` วันนี้
- **private:** `PRIVATE_MAPS_DIR` (default `maps-private/` ใน repo, อยู่ใน `.gitignore`) · ไฟล์ชุดเดียวกับ public (`drone_map.usda`, `drone_map_vehicles.json`, `drone_map_report.json`, USD) · ย้ายเครื่องด้วยมือเหมือนไฟล์ใหญ่ใน `vendor/README.md` **(เลือกเอง)**
- แต่ละแผนที่มี `site.json` ข้างไฟล์แผนที่ = ฟิลด์ของ `Site` ใน `sim/sites.py` (lat/lon/height, ground_z, spawn_xy, spawn_agl_m, heading_deg, stage_usd) **(เลือกเอง)**
- **vendor patch 0003:** `sites.py` โหลด site เพิ่มจาก `site.json` ในทุกโฟลเดอร์ที่ env `SITL_EXTRA_SITE_DIRS` (คั่นด้วย `:`) ชี้ · ชื่อชนกับ site ในไฟล์ = error · ไม่ตั้ง env = เหมือนเดิม
- `nt-testgs` ยังอยู่ใน `sites.py` ไม่ย้าย (patch 0001 คงไว้)

### 3.2 ตั้งค่า (`.env`)
- `PUBLIC_MAP=nt-testgs` (แทน `SITE` เดิม · `SITE` ที่ตั้งไว้ยังอ่านเป็นค่า `PUBLIC_MAP` ให้)
- `PRIVATE_MAP=` ชื่อ site ของ private · ว่าง = ปิด → งานที่ขอ `private` ได้ `400`
- ตอนเริ่ม service ตรวจว่า site ทั้งสองโหลดได้และมีไฟล์ truth ครบ · ไม่ครบ → ไม่เริ่ม (บอกเหตุผล)

### 3.3 API และ client
- `POST /jobs` JSON: ฟิลด์ใหม่ `map: "public" | "private"` (ไม่ใส่ = `public`) · ไฟล์: query `map=` · ค่าอื่น → `400`
- `flight.py run ... --map public|private`
- `Job` เก็บ `map` และ `site` · `GET /jobs/{id}`, `/jobs`, SSE `state`, `result.json` แสดง `map` · **ไม่แสดงชื่อ site ของ private** **(เลือกเอง)**
- ไฟล์ผลของงาน private ส่งให้ผู้เรียกครบเหมือน public · จะให้ทีมเห็นอะไร (mp4, track) เป็นเรื่องของระบบพี่ต้น · `result.json` ติด `map: "private"` ให้กรองได้ **(เลือกเอง)**

### 3.4 ต่องาน
- worker ส่ง `SITE=<site>` + `SITL_EXTRA_SITE_DIRS` ให้ `run-website.sh` / `launch-sitl.sh` ตอนบูตของงานนั้น
- truth ของ score โหลดตาม site ของงาน (cache ต่อ site) · `finalize` และ `analysis.txt` ใช้ site ของงาน
- truth โหลดใน process ของ service ผ่าน `fly_headless.load_truth` → `import sites` จึงต้องเห็น `SITL_EXTRA_SITE_DIRS` ด้วย: service ตั้งค่านี้ใน env ของตัวเองตอนเริ่ม (ก่อน import ครั้งแรก)
- `job.json` เก็บ `site` → งานที่กู้หลัง restart (`runner_restarted`) finalize ด้วย site ของงานนั้น ไม่ใช่ค่าปัจจุบันใน `.env`
- agent รู้ lat/lon ของจุดขึ้นบินจาก `arena.origin` อยู่แล้ว (เป็น GPS ปกติ ไม่ใช่ข้อมูลรั่ว) · พิกัดรถไม่ได้ส่งให้ agent ทางไหนเลย
- `sim_busy` และอื่น ๆ ไม่เปลี่ยน · sim ปิดหลังทุกงานอยู่แล้ว จึงสลับ map ระหว่างงานได้เลย

### 3.5 เวลาที่เหลือของ agent (G3)
- **vendor patch 0004:** `joystick-server.py` อ่าน `AGENT_TIME_LIMIT_S` จาก env (ไม่ตั้ง = `None` เหมือนเดิม)
- worker ตั้งค่านี้ต่องาน = `flight_timeout_s − 30` ให้ harness สั่ง hold ก่อน service ตัดงาน **(เลือกเอง: 30 s)**
- ถึงเวลาแล้ว harness ส่ง hold แต่ agent ไม่จบเอง → service ตัดที่ `flight_timeout_s` เหมือนเดิม (`flight_timeout`)

### 3.6 คู่มือผู้แข่ง (G4)
`docs/competitor-guide.md` เขียนจาก package ที่ vendor จริง: callback + งบเวลา, `flight()`/`Route`, `State`/`Arena`, `last_detections` (= สิ่งที่ถูกให้คะแนน), วิธีจบด้วย `] DONE`, เวลา, score v0, 3 วิธีส่ง image, public vs private · ระบุว่า `Inspect`, `request_roi`, `submit()` **ไม่มี** · template ใน `docs/reference/submission-template/` ชี้ไปที่คู่มือนี้

### 3.7 กันข้อมูลรั่วผ่าน API ⚠️ (ยังไม่ตัดสิน)
container ของ agent ใช้ `--network host` และ service ไม่มี login → **โค้ดของทีมเรียก API ของเราได้ระหว่างบิน:** `GET /jobs/{id}` มี `score_live.trucks_found` (รู้ทันทีว่าตอนนี้อยู่ใกล้รถ) และ `/jobs` + `/files/*` ของงาน private ก่อนหน้า (track/mp4 = ตำแหน่งรถ) · ต้องเลือกหนึ่งทาง ดูหัวข้อ 6

## 4. ทดสอบ
- unit (ของปลอมเหมือนเดิม): request `map` ถูก/ผิด/ไม่ใส่, private ปิดอยู่, env ที่ส่งให้ sim, truth ตาม site, `result.json`, ตรวจตอนเริ่ม, patch 0003/0004 ด้วยการซิงก์ลง scratch แล้วเทียบ
- บินจริง 2 รอบ: `public` (ต้องได้ผลเหมือนวันนี้) และ `private` ด้วย **สำเนา `nt-testgs` ลงทะเบียนชื่ออื่น** ใน `maps-private/` (ทดสอบท่อ ไม่ต้องรอแผนที่จริง) **(เลือกเอง)** · เช็ก `launch-sitl.console` ว่า site ถูก, `score.json` ใช้ truth ถูกไฟล์, log ของ agent เห็น `time_remaining` เป็นตัวเลข

## 5. ข้อที่ผมเลือกเอง (ตรวจได้)
`maps-private/` ใน repo แต่ ignore · `site.json` ต่อแผนที่ + patch โหลด · ไม่แสดงชื่อ site private · ผลงาน private ส่งครบ ให้ระบบพี่ต้นกรอง · time limit = timeout − 30 s · ทดสอบ private ด้วยสำเนา nt-testgs

## 6. ต้องให้ผู้ใช้ตัดสิน
1. **กันรั่วผ่าน API (3.7)** — (ก) token กลับมาทั้ง API แต่ใช้แค่ระบบพี่ต้น + `flight.py` · (ข) ซ่อน `score_live` และไฟล์ของงาน private ระหว่างมีงาน private บินอยู่ (รั่วผลงานก่อน ๆ ยังได้) · (ค) ย้าย container ออกจาก `--network host` ไป network ที่ถึงแค่ `:8080`/`:8090` (แก้ความเสี่ยงเดิมใน design 7 ด้วย แต่ต้องแก้ drone-sitl มากกว่า)
