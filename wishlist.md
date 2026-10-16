1. remove RUNNER TOKEN since it no need. the person call flight.py is only insider. — ✅ 2026-10-09
2. i want to know how we manage docker image and output file — ✅ 2026-10-16 (`docs/design.md` หัวข้อ 5 "Docker image และไฟล์ ใครสร้าง ใครลบ")
3. move pulled image into this repo
4. in the future each job's result will be linked to a competitor team, so we must keep each team's result data and logs (data/runs/<job>/ + the client copy in results/) and not lose them: retention (10 GB cap) must not delete them, and the container needs no volume since the agent writes nothing itself — ⏸ พัก 2026-10-16: เลือก B (service ไม่รู้จักทีม) แล้ว · วิธีลบยังไม่ตัดสิน (ดู progress.md)
5. can this change drone spec? 