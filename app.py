"""1000 Vocab review app: Today (SRS flashcards) + Practice modes + Word List + Settings."""
import html
import random
import time
from datetime import date
from pathlib import Path

import streamlit as st

import db
import practice
import srs
from ui import WIDE, card_back_html, inject_css, speak_buttons

BASE = Path(__file__).parent
DB_PATH = BASE / "vocab.db"
XLSX_PATH = BASE / "vocab_1000.xlsx"

st.set_page_config(page_title="1000 Vocab", page_icon="📚", layout="centered")
inject_css()


@st.cache_resource
def get_con():
    return db.connect(str(DB_PATH))


con = get_con()
today_d = date.today()
TODAY = today_d.isoformat()
S = db.get_settings(con)
STATUS_TH = {"new": "🆕 ใหม่", "learning": "📘 กำลังเรียน", "mastered": "✅ จำได้แล้ว"}


# ---------- first run: load vocab ----------
if db.vocab_count(con) == 0:
    st.title("📚 1000 Vocab")
    if XLSX_PATH.exists():
        n = db.import_excel(con, XLSX_PATH)
        st.success(f"นำเข้าคำศัพท์ {n} คำ จาก {XLSX_PATH.name}")
        st.rerun()
    up = st.file_uploader("อัปโหลด vocab_1000.xlsx", type="xlsx")
    if up:
        try:
            st.success(f"นำเข้าคำศัพท์ {db.import_excel(con, up)} คำ")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    st.stop()


# ---------- review session ----------
def start_session():
    due = db.due_ids(con, TODAY, S["max_reviews"])
    new_left = max(0, S["new_per_day"] - db.new_seen_today(con, TODAY))
    new = db.new_ids(con, new_left)
    q = due + new
    st.session_state.update(queue=q, revealed=False, t0=time.time(), done=0, total=len(q), dirs={})


def card_direction(wid):
    d = st.session_state.dirs
    if wid not in d:
        mode = S["direction"]
        d[wid] = random.choice(["EN→TH", "TH→EN"]) if mode == "สุ่ม" else mode
    return d[wid]


def reveal():
    st.session_state.revealed = True


def rate(wid, rating, direction):
    state = db.get_state(con, wid)
    db.save_state(con, wid, srs.schedule(state, rating, today_d))
    db.log_review(con, wid, f"flashcard {direction}", rating, time.time() - st.session_state.t0)
    q = st.session_state.queue
    q.pop(0)
    if rating == "again":
        q.insert(min(len(q), 4), wid)          # show again after a few cards
    else:
        st.session_state.done += 1
    st.session_state.revealed = False
    st.session_state.t0 = time.time()


def end_session():
    st.session_state.pop("queue", None)


def review_view():
    q = st.session_state.queue
    if not q:
        st.balloons()
        st.success(f"🎉 ทวนครบแล้ว {st.session_state.done} คำ")
        st.button("กลับหน้าแรก", on_click=end_session, **WIDE)
        return

    wid = q[0]
    w = db.get_word(con, wid)
    state = db.get_state(con, wid)
    direction = card_direction(wid)
    left = len(q)
    st.progress(st.session_state.done / max(1, st.session_state.done + left),
                text=f"เหลือ {left} ใบ · ทวนแล้ว {st.session_state.done}")

    tag = STATUS_TH[srs.status(state)]
    sub = f"<div class='sub'><span class='pill'>บทที่ {w['lesson']}</span><span class='pill'>{tag}</span>"
    if db.is_starred(con, wid):
        sub += "<span class='pill'>★</span>"
    sub += "</div>"
    front = (f"<div class='front'>{html.escape(w['word'])}</div>" if direction == "EN→TH"
             else f"<div class='front th'>{html.escape(w['meaning_th'])}</div>")

    if not st.session_state.revealed:
        st.markdown(f"<div class='card'>{sub}{front}</div>", unsafe_allow_html=True)
        if direction == "EN→TH":
            speak_buttons(w["word"], w["example_en"], S["tts_rate"])
        st.button("👀 แสดงคำตอบ", type="primary", on_click=reveal, **WIDE)
    else:
        answer = w["meaning_th"] if direction == "EN→TH" else w["word"]
        st.markdown(f"<div class='card'>{sub}{front}<div class='ans'>{html.escape(answer)}</div>"
                    f"<hr>{card_back_html(w)}</div>", unsafe_allow_html=True)
        speak_buttons(w["word"], w["example_en"], S["tts_rate"])
        pv = srs.preview(state)
        labels = {"again": "❌ ไม่ได้", "hard": "😓 ยาก", "good": "🙂 ได้", "easy": "😎 ง่าย"}
        c1, c2 = st.columns(2)
        c3, c4 = st.columns(2)
        for col, r in zip((c1, c2, c3, c4), srs.RATINGS):
            col.button(f"{labels[r]}  ·  {pv[r]}", key=f"rate_{r}", on_click=rate,
                       args=(wid, r, direction), type="primary" if r == "good" else "secondary", **WIDE)

    star = st.toggle("★ ติดดาวคำนี้", value=db.is_starred(con, wid), key=f"star_rev_{wid}")
    if star != db.is_starred(con, wid):
        db.set_star(con, wid, star)
    st.button("⏹ จบการทวน", on_click=end_session, **WIDE)


# ---------- pages ----------
def page_today():
    if "queue" in st.session_state:
        review_view()
        return
    st.subheader(f"📅 วันนี้ · {today_d:%d/%m/%Y}")
    due_n = len(db.due_ids(con, TODAY, 10_000))
    new_left = max(0, S["new_per_day"] - db.new_seen_today(con, TODAY))
    new_left = min(new_left, db.status_counts(con, srs.MASTERED_DAYS)["new"])
    c1, c2, c3 = st.columns(3)
    c1.metric("ต้องทวน", min(due_n, S["max_reviews"]))
    c2.metric("คำใหม่", new_left)
    c3.metric("🔥 Streak", f"{db.streak(con, today_d)} วัน")

    if due_n + new_left:
        st.button("▶️ เริ่มทวน", type="primary", on_click=start_session, **WIDE)
    else:
        st.success("วันนี้ไม่มีคำค้างทวนแล้ว 🎉 ไปฝึกต่อที่แท็บ 🎯 ฝึก ได้")

    cnt = db.status_counts(con, srs.MASTERED_DAYS)
    st.markdown("#### ความคืบหน้า")
    st.progress((cnt["learning"] + cnt["mastered"]) / cnt["total"],
                text=f"เริ่มเรียนแล้ว {cnt['learning'] + cnt['mastered']} / {cnt['total']} คำ")
    a, b, c = st.columns(3)
    a.metric(STATUS_TH["new"], cnt["new"])
    b.metric(STATUS_TH["learning"], cnt["learning"])
    c.metric(STATUS_TH["mastered"], cnt["mastered"])
    st.caption(f"ตอบไปแล้ววันนี้ {db.reviewed_today(con, TODAY)} ครั้ง (รวมโหมดฝึก) · "
               f"'จำได้แล้ว' = ช่วงทวนถัดไป ≥ {srs.MASTERED_DAYS} วัน")


def page_words():
    df = db.word_table(con)
    df["status"] = df["interval_days"].apply(
        lambda i: "new" if i != i else ("mastered" if i >= srs.MASTERED_DAYS else "learning"))

    q = st.text_input("🔍 ค้นหา (อังกฤษ / ไทย)", placeholder="เช่น posh หรือ หรูหรา")
    c1, c2 = st.columns(2)
    lesson = c1.selectbox("บท", ["ทั้งหมด"] + db.lessons(con))
    status = c2.selectbox("สถานะ", ["ทั้งหมด", "new", "learning", "mastered", "★ ติดดาว", "ตอบผิดบ่อย (≥2)"],
                          format_func=lambda x: STATUS_TH.get(x, x))
    if q:
        ql = q.strip().lower()
        df = df[df["word"].str.lower().str.contains(ql, regex=False)
                | df["meaning_th"].str.contains(q.strip(), regex=False)]
    if lesson != "ทั้งหมด":
        df = df[df["lesson"] == lesson]
    if status in ("new", "learning", "mastered"):
        df = df[df["status"] == status]
    elif status == "★ ติดดาว":
        df = df[df["starred"] == 1]
    elif status.startswith("ตอบผิด"):
        df = df[df["wrong"] >= 2].sort_values("wrong", ascending=False)

    per = 20
    pages = max(1, -(-len(df) // per))
    p = st.number_input(f"หน้า (ทั้งหมด {pages} หน้า)", 1, pages, 1) if pages > 1 else 1
    st.caption(f"พบ {len(df)} คำ")
    for r in df.iloc[(p - 1) * per: p * per].itertuples():
        star = "★ " if r.starred else ""
        with st.expander(f"{star}{r.id}. {r.word} — {r.meaning_th}"):
            w = dict(example_en=r.example_en, target=r.target, example_th=r.example_th,
                     meaning_th=r.meaning_th)
            st.markdown(f"<div class='card'>{card_back_html(w)}</div>", unsafe_allow_html=True)
            info = f"บทที่ {r.lesson} · {STATUS_TH[r.status]}"
            if r.status != "new":
                info += f" · ทวนครั้งถัดไป {r.due_date}"
            info += f" · ตอบผิด {r.wrong} ครั้ง"
            st.caption(info)
            speak_buttons(r.word, r.example_en, S["tts_rate"])
            on = st.toggle("★ ติดดาว", value=bool(r.starred), key=f"star_{r.id}")
            if on != bool(r.starred):
                db.set_star(con, r.id, on)
                st.rerun()


def page_settings():
    st.subheader("⚙️ ตั้งค่า")
    with st.form("settings"):
        n = st.slider("คำใหม่ต่อวัน", 0, 60, int(S["new_per_day"]), 5, help="20 คำ = 1 บท")
        m = st.slider("จำนวนทวนสูงสุดต่อวัน", 20, 500, int(S["max_reviews"]), 10)
        d = st.radio("ทิศทางการ์ด", ["EN→TH", "TH→EN", "สุ่ม"], horizontal=True,
                     index=["EN→TH", "TH→EN", "สุ่ม"].index(S["direction"]))
        r = st.slider("ความเร็วเสียงอ่าน", 0.5, 1.5, float(S["tts_rate"]), 0.1)
        ps = st.toggle("นำผลจากโหมดฝึกไปอัปเดตระบบทวน", value=bool(S["practice_srs"]),
                       help="ตอบผิด → คำนั้นกลับมาทวนวันนี้ · ตอบถูก → นับเป็นการทวนเฉพาะคำที่ถึงกำหนด")
        if st.form_submit_button("💾 บันทึก", type="primary", **WIDE):
            for k, v in dict(new_per_day=n, max_reviews=m, direction=d, tts_rate=r,
                             practice_srs=ps).items():
                db.set_setting(con, k, v)
            st.success("บันทึกแล้ว")
            st.rerun()

    st.markdown("#### ข้อมูล")
    up = st.file_uploader("นำเข้า Excel ที่แก้ไขแล้ว (ความคืบหน้าเดิมยังอยู่)", type="xlsx")
    if up and st.button("📥 นำเข้า", **WIDE):
        try:
            st.success(f"อัปเดตคำศัพท์ {db.import_excel(con, up)} คำ")
        except ValueError as e:
            st.error(str(e))
    if DB_PATH.exists():
        st.download_button("💾 สำรองข้อมูล (vocab.db)", DB_PATH.read_bytes(),
                           file_name=f"vocab_backup_{TODAY}.db", **WIDE)


def page_practice():
    practice.render(con, S, today_d)


# ---------- navigation ----------
PAGES = {"🏠 Today": page_today, "🎯 ฝึก": page_practice,
         "📖 คำศัพท์": page_words, "⚙️ ตั้งค่า": page_settings}
busy = "queue" in st.session_state or "ps" in st.session_state
page = st.radio("menu", list(PAGES), horizontal=True, label_visibility="collapsed", key="page",
                disabled=busy)
PAGES[page]()
