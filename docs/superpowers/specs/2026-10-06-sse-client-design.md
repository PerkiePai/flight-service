# Stream สด (SSE) + client `flight.py`: design (2026-10-06)

> รวม design ส่วนที่ 1–3 ที่เสนอและอนุมัติในแชตเมื่อ 2026-10-06 · หัวข้อ 4 คือสิ่งที่ยืนยันหรือเติมตอนเขียนแผน **ซึ่งยังไม่ได้รับอนุมัติแยก** ให้อ่านก่อน
> แผนลงมือ: [`../plans/2026-10-06-sse-client.md`](../plans/2026-10-06-sse-client.md) · บริบทเดิม: `docs/design.md` (หัวข้อ 3, 5, 9, 13), `docs/api.md`

**เป้าหมาย:** ผู้เรียก (ระบบของพี่ต้น) ติดตามการบินได้สดโดยไม่ต้อง poll และมี client ไฟล์เดียวที่ส่งงาน ติดตาม ดึงไฟล์ผล แล้วบอกผลด้วย exit code
**ทางที่เลือก:** B = stream เฉพาะ telemetry + state + ผลตอนจบ (ไม่ส่ง log ของ agent ไม่ส่ง detections) · "ความพร้อมของเครื่องใน `/healthz`" แยกไปทำทีหลัง

## 1. ฝั่ง server: `GET /jobs/{id}/stream`

Bearer token เหมือน endpoint อื่น · ไม่มี job ตอบ `404` ก่อนเปิดสาย · โค้ดอยู่ในไฟล์ใหม่ `flight_service/stream.py` และ `app.py` เพิ่ม route เดียว

| event | ส่งเมื่อ | data |
|---|---|---|
| `telemetry` | มีบรรทัดใหม่ใน `telemetry.jsonl` (5 Hz, บรรทัดละ ~1.3 KB) | บรรทัด JSON นั้นตามที่ journal ไว้ ทุกฟิลด์ |
| `state` | ตอนต่อเข้ามาหนึ่งครั้ง (สถานะปัจจุบัน) และทุกครั้งที่สถานะเปลี่ยน | `{"state","since","reason"}` |
| `end` | งานเป็น `done` / `failed` / `killed` และส่ง telemetry หมดแล้ว | `{"job_id","state","failed_in","reason","detail","result"}` |

หลัง `end` server ปิดสาย

กลไก:

1. **ต่อใหม่ไม่หาย ไม่ซ้ำ:** `telemetry` เท่านั้นที่มี `id` = เลขบรรทัดในไฟล์ (เริ่มที่ 1) · client ต่อใหม่พร้อม `Last-Event-ID: n` → server ข้าม n บรรทัดแรก และส่ง `state` ปัจจุบันก่อนเสมอ · นับบรรทัดใหม่ทุกครั้งที่ต่อ (ไฟล์ ~3,000 บรรทัด)
2. **ส่งเฉพาะบรรทัดที่ครบ:** บรรทัดสุดท้ายที่ยังไม่มี `\n` ถูกถือไว้จนกว่าจะครบ
3. **สถานะมาจาก `job.state` ในหน่วยความจำ** ไม่ใช่จาก `events.jsonl` · state จบถูกตั้งหลัง finalize + cleanup (design 5) ดังนั้นเมื่อเห็น state จบ journal ปิดแล้วและ `result` พร้อม
4. วนอ่านทุก 0.2 s ด้วย asyncio ไม่ block worker
5. **keepalive:** บรรทัดคอมเมนต์ `: ping` ทุก 15 s ตอนที่ไม่มีอะไรจะส่ง (pulling, booting, finalize, cleanup)
6. **header:** `Content-Type: text/event-stream` · `Cache-Control: no-cache` · `X-Accel-Buffering: no`
7. client ตัดสาย → Starlette ยกเลิก generator → ปิด file handle
8. service restart กลางบิน → สายขาด · client ต่อใหม่ได้ `end` พร้อม `failed` / `runner_restarted` จาก finalize เดิม

ไม่ทำ (YAGNI): จำกัดจำนวน stream ต่อ job · ส่ง log ของ agent หรือ detections · ตัดฟิลด์ของ telemetry

## 2. client: `scripts/flight.py`

ไฟล์เดียว ใช้แค่ standard library (Python 3.8+) ไม่ import อะไรจาก `flight_service/` · copy ไปที่ไหนก็รันได้
ตั้งค่า: `--url` / `FLIGHT_URL` (default `http://127.0.0.1:8095`) · `--token` / `RUNNER_TOKEN` (ไม่ตั้งก็แจ้งแล้วจบ ยกเว้น `health`)

| คำสั่ง | ทำอะไร |
|---|---|
| `flight.py health` | เรียก `/healthz` พิมพ์คำตอบ · exit 0 = ready, 1 = ไม่ ready, 2 = ติดต่อไม่ได้ |
| `flight.py run IMAGE [--timeout S] [--out DIR] [--wait S]` | ส่งงานจาก registry ติดตามจนจบ ดึงไฟล์ผลลง `DIR/<job_id>/` |
| `flight.py run --file X.tar --kind image\|bundle --name N` | ส่งงานจากไฟล์ (stream จากดิสก์พร้อม `Content-Length` เหมือน `curl -T`) |
| `flight.py watch JOB_ID [--out DIR]` | ต่อเข้าไปดูงานที่มีอยู่แล้ว แล้วดึงไฟล์ผล |
| `flight.py kill JOB_ID` | หยุดงาน |

ลำดับของ `run`:

1. `health`: `ready:false` → รอ (default 60 s, `--wait`) · `ok:false` (degraded) → เลิกทันที · ติดต่อไม่ได้ → แจ้งตรง ๆ
2. `POST /jobs`: `202` ไปต่อ · `409` กลับไปข้อ 1 · อย่างอื่นพิมพ์ `detail` ของ server แล้วจบ
3. เปิด `GET /jobs/{id}/stream` พิมพ์บรรทัดสรุปต่อ event (state ทุกครั้งที่เปลี่ยน, ตำแหน่งทุก 5 s)
4. ได้ `end` → `GET /jobs/{id}` เก็บเป็น `job.json` แล้วดึงทุกไฟล์ใน `result.files` (เขียนเป็น `.part` แล้วเปลี่ยนชื่อ) พิมพ์สรุป
5. สายขาด → ต่อใหม่ด้วย `Last-Event-ID` รอ 1, 2, 4, 8, 10 s · ไม่ได้ stream ต่อเนื่อง 60 s หรือ server ไม่มี endpoint นี้ → poll `GET /jobs/{id}` ทุก 3 s แล้วไปจบที่ข้อ 4
6. **Ctrl-C ไม่ kill งาน:** พิมพ์ `job_id` พร้อมวิธี `watch` / `kill` แล้วออก (งานเป็นของ service)

exit code ของ `run` / `watch`: `0` done · `1` failed หรือ killed · `2` ติดต่อ/ส่งงานไม่ได้ · `3` ถูกขัดจังหวะ
ผลลัพธ์: ข้อความระหว่างทางไป stderr · บรรทัดเดียวบน stdout เป็น JSON (`job_id`, `state`, `reason`, `score`, `out_dir`, `not_downloaded`)
`mock-caller.sh` เก็บไว้ จนกว่า `flight.py` ผ่านการรันจริงหนึ่งงาน

ไม่ทำ (YAGNI): `requests`/`aiohttp` · หลายงานพร้อมกัน · ไฟล์ config · สี/progress bar · `KILL_AFTER_S` · คำสั่ง `list` / `get`

## 3. Error, ทดสอบ, เอกสาร

Server:

| กรณี | พฤติกรรม |
|---|---|
| job ไม่มี / token ผิด | `404` / `401` ก่อนเปิดสาย |
| `Last-Event-ID` ไม่ใช่เลขบรรทัด (ตัวอักษร, ติดลบ, ยาวเกิน) | ถือเป็น 0 ส่งตั้งแต่ต้น |
| `telemetry.jsonl` ยังไม่มี (queued, pulling) | ถือว่าว่าง รอต่อ |
| บรรทัดที่อ่านเป็น JSON ไม่ได้ | ข้าม แต่ยังนับเลขบรรทัด |
| exception ระหว่าง stream | ปิดสาย ไม่ส่ง event ปลอม |

Client: แปลง `401` / `409` / `503` เป็นข้อความที่คนอ่านรู้เรื่อง พร้อม `detail` จาก server ตามจริง · ไฟล์ที่ server บอกว่า `missing` พิมพ์ตามนั้น ไม่เดา

ทดสอบ (pytest ของปลอมทั้งหมด ไม่เปิด sim): `tests/test_stream.py` (generator กับไฟล์ใน tmp) · `tests/test_app.py` เพิ่ม (route จริงบน uvicorn) · `tests/test_flight_client.py` (client กับ server ปลอมบน socket จริง และกับ app จริง) · แล้วรันจริงหนึ่งงานบน sim (ขออนุมัติก่อนทุกครั้ง)

เอกสารที่แก้ตาม: `docs/design.md` หัวข้อ 3 (6 → 7 endpoint) · `docs/api.md` · `README.md` · docstring หัว `app.py` · `docs/progress.md` · `docs/followups.md`

## 4. สิ่งที่ยืนยันหรือเติมตอนเขียนแผน (ขอให้อ่าน)

ยืนยันจากโค้ดและจากต้นแบบที่รันใน scratchpad (ไม่ได้แตะ repo):

- `events.jsonl` มี state ก่อนบิน (`pulling`, `booting`, `flying`) แต่ไม่มี `queued` และไม่มี state จบ → ใช้ `job.state` ตามข้อ 1.3 ถูกแล้ว
- uvicorn 0.52 ประกาศ ASGI spec 2.3 → Starlette 1.3.1 ยกเลิก generator เมื่อ client ตัดสาย (ข้อ 1.7 จริง มีเทสต์)
- บรรทัด telemetry จริงยาว 1.3–1.4 KB ที่ 4.99 Hz → ~6.5 KB/s ต่อหนึ่งสาย

เติมเพราะ design เงียบ (ถ้าไม่เห็นด้วย แก้ในแผนก่อนลงมือ):

| # | เรื่อง | ที่ใส่ในแผน | เหตุผล |
|---|---|---|---|
| a | upload ไฟล์ | client ส่ง `Expect: 100-continue` แล้วรอคำตอบก่อนส่งเนื้อไฟล์ (เฉพาะ `http://`) | server ปฏิเสธ (409 / 413 / 507) ก่อนอ่านไฟล์อยู่แล้ว ถ้าไม่ถามก่อน client จะส่งไฟล์ 16 GB ทั้งก้อนแล้วค่อยรู้ · `curl -T` ทำแบบเดียวกัน |
| b | poll แล้ว server ยังเงียบ | เลิกหลังติดต่อไม่ได้ต่อเนื่อง 300 s → exit 2 พร้อมบอก `flight.py watch <id>` | ระบบอัตโนมัติไม่ควรค้างตลอดไป · 300 s เผื่อ service restart + recover |
| c | ไฟล์ผลดาวน์โหลดไม่สำเร็จ | ไม่เหลือไฟล์ครึ่ง · ชื่ออยู่ใน `not_downloaded` ของบรรทัด JSON · exit 2 | exit 0 ควรแปลว่า "จบ done และไฟล์อยู่ครบบนดิสก์" |
| d | SIGTERM | ทำเหมือน Ctrl-C (exit 3 ไม่ kill) | ตัวคุม process ส่ง SIGTERM ไม่ใช่ SIGINT |
| e | `--wait` | นับรวมทั้งรอ `ready` และการลองใหม่หลัง `409` | กันวนไม่จบเมื่อ `ready:true` แต่ `POST` ได้ 409 ซ้ำ |
| f | บรรทัด JSON บน stdout | พิมพ์ทุกครั้งที่รู้ `job_id` แล้ว (รวม exit 2 และ 3) · ก่อนมี `job_id` stdout ว่าง | ผู้เรียกต้องได้ `job_id` ไปใช้ `watch` / `kill` |
| g | event ที่ client อ่านไม่ออก | เปลี่ยนไป poll ทันที ไม่ต่อใหม่ | ต่อใหม่จะได้ event เดิมซ้ำไม่จบ |
| h | `kill` | exit 0 = รับ (200 / 202) · 1 = ไม่มีอะไรให้หยุด (404 / 409) · 2 = ติดต่อไม่ได้ | design ไม่ได้ระบุ |
| i | stderr ที่ไม่ใช่ UTF-8 | ตัวอักษรที่พิมพ์ไม่ได้กลายเป็น `\uXXXX` · ข้อความของ client เป็นอังกฤษ ASCII | `detail` ของ server อาจเป็นภาษาไทย และ client อาจรันใต้ `LANG=C` |
| j | ค่าคงที่ของ stream | อยู่ใน `stream.py` (`POLL_S`, `PING_S`) ไม่เพิ่ม env | ยังไม่มีใครต้องปรับ |
| k | `--out` | default `flight-out/` (เพิ่มใน `.gitignore`) | `mock-out/` เป็นของ `mock-caller.sh` |

ข้อจำกัดที่รู้: upload ผ่าน `https://` ไม่ถามก่อน (อ่าน TLS socket ล่วงหน้าไม่ได้) จึงส่งทั้งไฟล์เสมอ · upload ไม่ใช้ `http_proxy` จาก env (คำสั่งอื่นใช้ตาม `urllib`) · ยังไม่ได้ลอง SSE ผ่าน reverse proxy จริง
