# 1000 Vocab – Streamlit

## รัน
    python -m pip install -r requirements.txt
    python -m streamlit run app.py --server.address 0.0.0.0
(หรือดับเบิลคลิก run.bat) · มือถือ: http://<IP คอม>:8501

## อัปเดตจากเวอร์ชันก่อน
คัดลอกไฟล์ใหม่ทับได้เลย แต่ **อย่าทับ vocab.db** (ความคืบหน้าอยู่ในไฟล์นี้)
ตารางใหม่ (ladder, ta_scores) จะถูกสร้างให้อัตโนมัติ

## ไฟล์
- app.py – หน้า Today / ฝึก / คำศัพท์ / ตั้งค่า
- practice.py – โหมดฝึก 9 โหมด
- srs.py – ระบบทวนแบบเว้นระยะ
- db.py – SQLite
- ui.py – CSS, ไฮไลต์, ปุ่มเสียง
- vocab_1000.xlsx – คำศัพท์
- parse_vocab_pdf.py – สคริปต์แปลง PDF → Excel
