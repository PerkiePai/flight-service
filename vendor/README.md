# vendor/ — drone-sitl ที่ flight-service ใช้ (สำเนา)

flight-service รันสคริปต์และเว็บ `:8090` ของ drone-sitl จากโฟลเดอร์นี้ จึงไม่ต้องมี `~/pai/drone-sitl` บนเครื่อง (ตัดสินใจ 2026-10-06 ทาง A · `docs/progress.md`)

| path | คืออะไร | เข้า git |
|---|---|---|
| `drone-sitl/` | ไฟล์ตาม `drone-sitl.manifest` จาก commit เดียว + patch ใน `patches/drone-sitl/` · ต้นทางอยู่ใน `drone-sitl/VENDORED` | ✅ ยกเว้นของที่เกิดตอนรัน: `logs/ recordings/ .cache/ sim/secrets.env` |
| `maps/nt-testgs/` | แผนที่ site `nt-testgs` (map_setup_tool) + layer ที่มันอ้างถึง วางแบนในโฟลเดอร์เดียว · `SHA256SUMS` | ✅ ไฟล์เล็ก · ❌ `nt_testgs.usdc` (228 MB) · `Truck2.usd` (64 MB) |

## กฎ

- **ห้ามแก้ไฟล์ใน `drone-sitl/` ตรงๆ** ซิงก์ครั้งหน้าจะทับ · ต้องแก้ → เพิ่ม `patches/drone-sitl/NNNN-<เรื่อง>.patch` (`diff -u a/<path> b/<path>`) แล้วรันสคริปต์ซิงก์
- patch ที่มี: `0001-sites-nt-testgs-map-in-repo.patch` ชี้ `stage_usd` ของ `nt-testgs` ไปที่ `../maps/nt-testgs/drone_map.usda` (เดิมเป็น path ตายตัวใน home ของเครื่องเดิม)

## ซิงก์จาก drone-sitl ต้นทาง

1. ปิด sim/เว็บก่อน (`./scripts/stop-service.sh` และ `vendor/drone-sitl/sim/stop-website.sh`)
2. `./scripts/vendor-drone-sitl.sh ~/pai/drone-sitl <commit>` (ไม่ใส่ commit = HEAD · ใช้เฉพาะของที่ commit แล้ว)
3. ต้นทาง import ไฟล์ใหม่ → เพิ่มใน `drone-sitl.manifest` (`pytest tests/test_vendored.py` ฟ้องถ้า import หาไม่เจอในสำเนา)
4. patch ใช้ไม่ได้ → สคริปต์หยุดก่อนแตะโฟลเดอร์ · แก้ patch แล้วรันใหม่
5. `pytest` → `git diff --stat vendor/` → commit โดยบอก commit ต้นทาง

## map

- สร้าง/อัปเดต: `./scripts/vendor-map.sh nt-testgs ~/Tiger/map_setup_output_nt_testgs` (ทุกไฟล์ในโฟลเดอร์ + ไฟล์ที่ `drone_map.usda` อ้างถึง แล้วเขียน ref เป็น `./<ชื่อ>`)
- ตรวจว่าไม่มี layer ซ้อนที่หลุดออกนอกโฟลเดอร์ ด้วย pxr ของ Isaac (ต้องได้ 4 layer ในโฟลเดอร์นี้ · `unresolved []`):
  ```bash
  E="$(ls -d "$HOME"/isaac-sim6/extscache/omni.usd.libs-*/ | head -1)"
  env -u CONDA_PREFIX -u CONDA_DEFAULT_ENV PYTHONPATH="$E" LD_LIBRARY_PATH="$E/bin" \
    "$HOME/isaac-sim6/kit/python/bin/python3" -c "
  from pxr import UsdUtils, Sdf
  layers, assets, unresolved = UsdUtils.ComputeAllDependencies(Sdf.AssetPath('$PWD/vendor/maps/nt-testgs/drone_map.usda'))
  print(*sorted(l.realPath for l in layers), sep='\n'); print('assets', assets, 'unresolved', unresolved)"
  ```
- ย้ายเครื่อง: ไฟล์ใหญ่ 2 ตัวไม่อยู่ใน git → เครื่องเดิม `tar -C vendor/maps -cf nt-testgs-map.tar nt-testgs` → เครื่องใหม่ `tar -C vendor/maps -xf nt-testgs-map.tar` → `./scripts/preflight.sh` ตรวจ `SHA256SUMS`
