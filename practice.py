"""🎯 Practice modes.

Level 1: cloze (type inflected form), TH→EN typing, meaning-in-context
Level 2: sentence ordering, dictation, sentence translation (self-graded)
Level 3: Time Attack, Boss (frequent mistakes), Mastery Ladder

Results feed the SRS automatically (see apply_rating).
"""
import difflib
import html
import random
import re
import time
from datetime import timedelta

import streamlit as st

import db
import srs
from ui import WIDE, card_back_html, hl_en, hl_th, speak_row

TA_SECONDS = 60
BOSS_WIN = 3
BOSS_DAYS = 30
LADDER = ["mc", "type", "cloze", "dictation"]
LADDER_NAME = ["1 เลือกคำแปล", "2 พิมพ์คำ", "3 เติมคำ", "4 ฟังแล้วพิมพ์", "🏆 ผ่าน"]
SLOW = {"mc": 8, "context": 10, "type": 15, "cloze": 15, "order": 30, "dictation": 40}
TYPE_NAME = {"mc": "เลือกคำแปล", "context": "ความหมายตามบริบท", "type": "แปลไทย → อังกฤษ",
             "cloze": "เติมคำ", "order": "เรียงประโยค", "dictation": "ฟังแล้วพิมพ์",
             "translate": "แปลประโยค"}

MODES = {
    "cloze": ("✍️ เติมคำในประโยค", "พิมพ์รูปคำที่ถูกต้องลงในช่องว่าง เช่น argue → arguing"),
    "type": ("⌨️ แปลไทย → อังกฤษ", "เห็นคำแปลไทย แล้วพิมพ์คำศัพท์ภาษาอังกฤษ (ผิด 1 ตัวอักษร = เกือบถูก)"),
    "context": ("🧭 ความหมายตามบริบท", "เลือกความหมายที่ตรงกับประโยค คำที่มีหลายความหมายจะใช้ความหมายอื่นเป็นตัวหลอก"),
    "order": ("🧩 เรียงประโยค", "แตะคำเรียงให้เป็นประโยคที่ถูกต้อง"),
    "dictation": ("🎧 ฟังแล้วพิมพ์", "ฟังประโยคแล้วพิมพ์ตาม ระบบให้คะแนนเป็น % คำที่ถูก"),
    "translate": ("📝 แปลประโยค ไทย → อังกฤษ", "แปลประโยคไทยเป็นอังกฤษ ดูความต่างจากเฉลย แล้วให้คะแนนตัวเอง"),
    "time": ("⏱ Time Attack", f"เลือกคำแปลให้ถูกมากที่สุดใน {TA_SECONDS} วินาที"),
    "boss": ("👹 Boss: คำที่ผิดบ่อย",
             f"คำที่ตอบผิด ≥2 ครั้งใน {BOSS_DAYS} วันล่าสุด ต้องตอบถูกติดกัน {BOSS_WIN} ครั้งจึงจะผ่าน"),
    "ladder": ("🪜 ไต่ระดับ", "แต่ละคำต้องผ่าน 4 ขั้น: เลือกคำแปล → พิมพ์คำ → เติมคำ → ฟังแล้วพิมพ์"),
}
STANDARD = ("cloze", "type", "context", "order", "dictation", "translate")
SCOPES = {"all": "ทุกบท", "lessons": "เลือกบท", "learned": "คำที่เริ่มเรียนแล้ว",
          "starred": "★ ติดดาว", "wrong": "ตอบผิดบ่อย (≥2)"}
RESULT_TH = {"correct": "✅ ถูกต้อง", "near": "🟡 เกือบถูก", "wrong": "❌ ยังไม่ถูก"}


# ---------- context (stored per session, safe for multiple devices) ----------
def X():
    return st.session_state["_ctx"]


def PS():
    return st.session_state["ps"]


def parts(m):
    return {p.strip() for p in m.split("/") if p.strip()}


# ---------- text helpers ----------
def norm(s):
    s = s.lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"[^\w'%\- ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def lev(a, b):
    if abs(len(a) - len(b)) > 2:
        return 3
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def grade_word(answer, accepted):
    a = norm(answer)
    acc = [norm(x) for x in accepted]
    if a in acc:
        return "correct", a
    for x in acc:
        d = lev(a, x)
        if (d == 1 and len(x) >= 4) or (d == 2 and len(x) >= 8):
            return "near", x
    return "wrong", None


def find_target(sentence, target):
    return re.search(r"(?<![A-Za-z])" + re.escape(target) + r"(?![A-Za-z])", sentence, re.I)


def tok(t):
    return re.sub(r"[^\w%]", "", t.lower())      # apostrophes ignored: dont = don't


def diff_html(ref, ans):
    """Word-level diff. Returns (score 0-1, html)."""
    rt, at = ref.split(), ans.split()
    rn, an = [tok(t) for t in rt], [tok(t) for t in at]
    sm = difflib.SequenceMatcher(a=rn, b=an, autojunk=False)
    out, match = [], 0
    esc = html.escape
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out += [f"<span class='ok'>{esc(t)}</span>" for t in rt[i1:i2]]
            match += i2 - i1
        else:
            out += [f"<span class='bad'>{esc(t)}</span>" for t in at[j1:j2]]
            out += [f"<span class='miss'>{esc(t)}</span>" for t in rt[i1:i2]]
    return match / max(1, len(rt)), " ".join(out)


DIFF_LEGEND = ("<span class='ok'>เขียว</span> = ถูก · <span class='miss'>ขีดเส้นใต้</span> = "
               "คำที่ขาด/ควรเป็น · <span class='bad'>ขีดฆ่า</span> = คำที่เกิน/ผิด")


# ---------- question building ----------
def distractors(w, prefer=(), n=3):
    own = parts(w["meaning_th"])
    out = []

    def ok(m):
        return m not in out and m != w["meaning_th"] and not (parts(m) & own)

    for m in prefer:
        if len(out) < n and ok(m):
            out.append(m)
    pool = list(X()["V"].values())
    random.shuffle(pool)
    pool.sort(key=lambda x: x["lesson"] != w["lesson"])      # same lesson first
    for x in pool:
        if len(out) >= n:
            break
        if ok(x["meaning_th"]):
            out.append(x["meaning_th"])
    return out


def make_q(wid, typ):
    V = X()["V"]
    w = V[wid]
    st.session_state["qn"] = st.session_state.get("qn", 0) + 1
    q = dict(wid=wid, type=typ, n=st.session_state["qn"])
    if typ == "cloze":
        m = find_target(w["example_en"], w["target"]) or find_target(w["example_en"], w["word"])
        if not m:
            typ = q["type"] = "type"
        else:
            q.update(pre=w["example_en"][:m.start()], ans=m.group(0), post=w["example_en"][m.end():])
    if typ in ("mc", "context"):
        prefer = []
        if typ == "context":
            prefer = [x["meaning_th"] for x in V.values()
                      if x["word"].lower() == w["word"].lower() and x["id"] != wid]
        opts = [w["meaning_th"]] + distractors(w, prefer)
        random.shuffle(opts)
        q.update(opts=opts, ans=w["meaning_th"])
    if typ == "type":
        acc = {w["word"]}
        for p in parts(w["meaning_th"]):
            acc |= X()["by_part"].get(p, set())
        q.update(acc=sorted(acc), ans=w["word"])
    if typ in ("order", "dictation", "translate"):
        q["ans"] = w["example_en"]
    if typ == "order":
        toks = w["example_en"].split()
        order = list(range(len(toks)))
        for _ in range(10):
            random.shuffle(order)
            if len(toks) < 2 or [toks[i] for i in order] != toks:
                break
        q.update(toks=toks, order=order, picked=[])
    return q


# ---------- session flow ----------
def start(mode, ids, n, scope_label):
    ps = dict(mode=mode, results=[], fb=None, hint=False, q=None, scope=scope_label,
              ids=list(ids), n=n, i=-1, warn="")
    if mode in STANDARD:
        ps["items"] = random.sample(ids, min(n, len(ids)))
    elif mode == "ladder":
        lv = db.ladder_levels(X()["con"])
        cand = sorted((i for i in ids if lv.get(i, 0) < len(LADDER)), key=lambda i: (-lv.get(i, 0), i))
        ps["items"] = cand[:n]
    elif mode == "boss":
        ps["hp"] = {i: 0 for i in boss_pool(ids)[:n]}
        ps["last"] = None
    elif mode == "time":
        ps.update(start=time.time(), correct=0, wrong=0, wrong_ids=[], over=False, saved=False,
                  recent=[], last_msg="")
    st.session_state["ps"] = ps
    next_q()


def boss_pool(ids):
    since = (X()["today"] - timedelta(days=BOSS_DAYS)).isoformat()
    wc = db.wrong_counts(X()["con"], since)
    return sorted((i for i in ids if wc.get(i, 0) >= 2), key=lambda i: (-wc[i], i))


def next_q():
    ps = PS()
    m = ps["mode"]
    ps.update(fb=None, hint=False, q=None, warn="")
    if m in STANDARD or m == "ladder":
        ps["i"] += 1
        if ps["i"] >= len(ps["items"]):
            return
        wid = ps["items"][ps["i"]]
        typ = m if m in STANDARD else LADDER[min(db.ladder_levels(X()["con"]).get(wid, 0), 3)]
    elif m == "boss":
        alive = [i for i, h in ps["hp"].items() if h < BOSS_WIN]
        if not alive:
            return
        choices = [i for i in alive if i != ps["last"]] or alive
        wid = random.choice(choices)
        ps["last"] = wid
        typ = random.choice(["mc", "context", "type", "cloze"])
    else:  # time
        rec = ps["recent"]
        choices = [i for i in ps["ids"] if i not in rec] or ps["ids"]
        wid = random.choice(choices)
        rec.append(wid)
        del rec[:-10]
        typ = "mc"
    ps["q"] = make_q(wid, typ)
    ps["t0"] = time.time()


def apply_rating(wid, rating, typ, sec):
    """Log every answer. Update SRS only for words already being learned:
    - wrong  -> Again (word comes back in today's review)
    - correct/near -> rating applied only when the word is due today (no early interval boost)
    New words are never pulled into SRS from practice, so the daily new-word quota is untouched."""
    x = X()
    db.log_review(x["con"], wid, f"practice:{typ}", rating, sec)
    if not x["S"].get("practice_srs", True):
        return
    s = db.get_state(x["con"], wid)
    if s and (rating == "again" or s["due_date"] <= x["today"].isoformat()):
        db.save_state(x["con"], wid, srs.schedule(s, rating, x["today"]))


def finish(result, detail="", rating=None):
    ps = PS()
    q = ps["q"]
    if q is None:
        return
    m = ps["mode"]
    if m == "time" and time.time() - ps["start"] > TA_SECONDS:
        ps["over"] = True
        return
    sec = time.time() - ps["t0"]
    if rating is None:
        if result == "wrong":
            rating = "again"
        elif result == "near" or ps["hint"] or sec > SLOW.get(q["type"], 15):
            rating = "hard"
        else:
            rating = "good"
    apply_rating(q["wid"], rating, q["type"], sec)
    ps["results"].append(dict(wid=q["wid"], type=q["type"], result=result))
    extra = ""
    if m == "boss":
        h = ps["hp"]
        h[q["wid"]] = 0 if result == "wrong" else h[q["wid"]] + (result == "correct")
    elif m == "ladder":
        con = X()["con"]
        lv = db.ladder_levels(con).get(q["wid"], 0)
        new = lv + 1 if result == "correct" else (max(0, lv - 1) if result == "wrong" else lv)
        db.set_ladder(con, q["wid"], new)
        if new != lv:
            extra = f"ระดับ {LADDER_NAME[lv]} → {LADDER_NAME[new]}"
    elif m == "time":
        w = X()["V"][q["wid"]]
        if result == "wrong":
            ps["wrong"] += 1
            ps["wrong_ids"].append(q["wid"])
            ps["last_msg"] = f"❌ {w['word']} = {w['meaning_th']}"
        else:
            ps["correct"] += 1
            ps["last_msg"] = f"✅ {w['word']} = {w['meaning_th']}"
        next_q()
        return
    ps["fb"] = dict(result=result, rating=rating, detail=detail, sec=sec, extra=extra, graded=True)


# ---------- callbacks ----------
def cb_choice(i):
    q = PS()["q"]
    finish("correct" if q["opts"][i] == q["ans"] else "wrong", detail=q["opts"][i])


def cb_text():
    ps = PS()
    q = ps["q"]
    val = st.session_state.get(f"in_{q['n']}", "")
    if not val.strip():
        ps["warn"] = "พิมพ์คำตอบก่อน หรือกด 🤷 ไม่รู้"
        return
    if q["type"] == "dictation":
        score, dh = diff_html(q["ans"], val)
        res = "correct" if score >= 0.999 else "near" if score >= 0.8 else "wrong"
        finish(res, detail=f"<div class='diff'>{dh}</div><div>ได้ {score:.0%}</div>")
        return
    if q["type"] == "translate":
        score, dh = diff_html(q["ans"], val)
        w = X()["V"][q["wid"]]
        used = any(norm(t) in norm(val) for t in {w["word"], w["target"]})
        ps["fb"] = dict(graded=False, score=score, used=used,
                        detail=f"<div class='diff'>{dh}</div>")
        return
    accepted = q["acc"] if q["type"] == "type" else [q["ans"]]
    res, matched = grade_word(val, accepted)
    finish(res, detail=val.strip())


def cb_grade(rating):
    fb = PS()["fb"]
    finish("wrong" if rating == "again" else "correct", detail=fb["detail"], rating=rating)


def cb_dunno():
    finish("wrong", detail="")


def cb_hint():
    PS()["hint"] = True


def cb_pick(key, v=None):
    v = v if v is not None else st.session_state.get(key)
    if v is not None:
        PS()["q"]["picked"].append(v)


def cb_unpick(key, v=None):
    v = v if v is not None else st.session_state.get(key)
    q = PS()["q"]
    if v is not None and v in q["picked"]:
        q["picked"].remove(v)


def cb_order_undo():
    p = PS()["q"]["picked"]
    if p:
        p.pop()


def cb_order_clear():
    PS()["q"]["picked"].clear()


def cb_order_check():
    q = PS()["q"]
    built = " ".join(q["toks"][i] for i in q["picked"])
    finish("correct" if built == " ".join(q["toks"]) else "wrong", detail=built)


def cb_exit():
    st.session_state.pop("ps", None)


def cb_back_to_setup():
    st.session_state.pop("ps", None)


def cb_retry_wrong(mode, ids, scope):
    start(mode, ids, len(ids), scope)


# ---------- widgets ----------
def chips(options, fmt, key, cb):
    if not options:
        return
    if hasattr(st, "pills"):
        st.pills("chips", options, format_func=fmt, key=key, on_change=cb, args=(key,),
                 label_visibility="collapsed")
    else:
        cols = st.columns(3)
        for j, o in enumerate(options):
            cols[j % 3].button(fmt(o), key=f"{key}_{j}", on_click=cb, args=(key, o))


def answer_form(q, label, placeholder=""):
    with st.form(f"f_{q['n']}", border=False):
        st.text_input(label, key=f"in_{q['n']}", placeholder=placeholder, autocomplete="off")
        st.form_submit_button("✅ ตรวจคำตอบ", type="primary", on_click=cb_text, **WIDE)
    if PS()["warn"]:
        st.warning(PS()["warn"])


def help_buttons(q, hint_label="💡 คำใบ้"):
    c1, c2 = st.columns(2)
    c1.button(hint_label, key=f"h_{q['n']}", on_click=cb_hint, disabled=PS()["hint"], **WIDE)
    c2.button("🤷 ไม่รู้", key=f"d_{q['n']}", on_click=cb_dunno, **WIDE)


def letter_hint(ans):
    return " ".join(c if (i == 0 or not c.isalpha()) else "_" for i, c in enumerate(ans)) + \
        f" ({sum(c.isalpha() for c in ans)} ตัวอักษร)"


# ---------- question renderers ----------
def header(q, w):
    st.markdown(f"<span class='pill'>บทที่ {w['lesson']}</span>"
                f"<span class='pill'>{TYPE_NAME[q['type']]}</span>", unsafe_allow_html=True)


def r_mc(q, w):
    st.markdown(f"<div class='card'><div class='front'>{html.escape(w['word'])}</div></div>",
                unsafe_allow_html=True)
    speak_row([(w["word"], "🔊 ฟังคำ", X()["S"]["tts_rate"])])
    for i, o in enumerate(q["opts"]):
        st.button(o, key=f"op_{q['n']}_{i}", on_click=cb_choice, args=(i,), **WIDE)


def r_context(q, w):
    st.markdown(f"<div class='card'><div class='ex-en big'>{hl_en(w['example_en'], w['target'])}</div>"
                f"<div class='q'>คำว่า <b>{html.escape(w['target'])}</b> ในประโยคนี้หมายถึงอะไร</div></div>",
                unsafe_allow_html=True)
    for i, o in enumerate(q["opts"]):
        st.button(o, key=f"op_{q['n']}_{i}", on_click=cb_choice, args=(i,), **WIDE)


def r_type(q, w):
    hint = f"<div class='hint'>💡 {html.escape(letter_hint(w['word']))}</div>" if PS()["hint"] else ""
    st.markdown(f"<div class='card'><div class='front th'>{html.escape(w['meaning_th'])}</div>"
                f"<div class='ex-th' style='text-align:center;margin-top:8px'>บริบท: "
                f"{hl_th(w['example_th'], w['meaning_th'])}</div>{hint}</div>", unsafe_allow_html=True)
    answer_form(q, "พิมพ์คำศัพท์ภาษาอังกฤษ")
    help_buttons(q)


def r_cloze(q, w):
    hint = f"<div class='hint'>💡 {html.escape(letter_hint(q['ans']))}</div>" if PS()["hint"] else ""
    st.markdown(f"<div class='card'><div class='ex-en big'>{html.escape(q['pre'])}"
                f"<span class='blank'>?</span>{html.escape(q['post'])}</div>"
                f"<div class='ex-th'>{hl_th(w['example_th'], w['meaning_th'])}</div>{hint}</div>",
                unsafe_allow_html=True)
    answer_form(q, "คำที่หายไป (ผันรูปให้ถูกด้วย)")
    help_buttons(q)


def r_order(q, w):
    toks = q["toks"]
    hint = (f"<div class='hint'>💡 ขึ้นต้นด้วย: {html.escape(' '.join(toks[:3]))} …</div>"
            if PS()["hint"] else "")
    st.markdown(f"<div class='card'><div class='ex-th' style='font-size:1.15rem'>"
                f"{hl_th(w['example_th'], w['meaning_th'])}</div>{hint}</div>", unsafe_allow_html=True)
    picked = q["picked"]
    fmt = lambda i: toks[i]
    st.caption("ประโยคของคุณ (แตะคำเพื่อเอาออก)")
    if picked:
        chips(list(picked), fmt, f"up_{q['n']}_{len(picked)}", cb_unpick)
    else:
        st.markdown("&nbsp;")
    st.caption("แตะคำเพื่อเรียง")
    remaining = [i for i in q["order"] if i not in picked]
    chips(remaining, fmt, f"pk_{q['n']}_{len(picked)}", cb_pick)
    c1, c2, c3 = st.columns(3)
    c1.button("↩️ ย้อน", key=f"u_{q['n']}", on_click=cb_order_undo, disabled=not picked, **WIDE)
    c2.button("🔄 ล้าง", key=f"c_{q['n']}", on_click=cb_order_clear, disabled=not picked, **WIDE)
    c3.button("💡 ใบ้", key=f"h_{q['n']}", on_click=cb_hint, disabled=PS()["hint"], **WIDE)
    st.button("✅ ตรวจคำตอบ", key=f"chk_{q['n']}", type="primary", on_click=cb_order_check,
              disabled=len(picked) < len(toks), **WIDE)


def r_dictation(q, w):
    rate = X()["S"]["tts_rate"]
    hint = (f"<div class='hint'>💡 {hl_th(w['example_th'], w['meaning_th'])}</div>"
            if PS()["hint"] else "")
    st.markdown(f"<div class='card'><div class='q'>🎧 ฟังประโยคแล้วพิมพ์ตาม</div>{hint}</div>",
                unsafe_allow_html=True)
    speak_row([(w["example_en"], "🔊 ฟัง", rate), (w["example_en"], "🐢 ฟังช้า", 0.6)])
    answer_form(q, "พิมพ์ประโยคที่ได้ยิน")
    help_buttons(q, "💡 ดูคำแปลไทย")


def r_translate(q, w):
    hint = ""
    if PS()["hint"]:
        hint = f"<div class='hint'>💡 ขึ้นต้นด้วย: {html.escape(' '.join(w['example_en'].split()[:2]))} …</div>"
    st.markdown(f"<div class='card'><div class='ex-th' style='font-size:1.2rem;color:#1f2937'>"
                f"{html.escape(w['example_th'])}</div>"
                f"<div class='q'>ใช้คำว่า <b>{html.escape(w['word'])}</b> ({html.escape(w['meaning_th'])})</div>"
                f"{hint}</div>", unsafe_allow_html=True)
    answer_form(q, "แปลเป็นภาษาอังกฤษ")
    help_buttons(q)


RENDER = {"mc": r_mc, "context": r_context, "type": r_type, "cloze": r_cloze,
          "order": r_order, "dictation": r_dictation, "translate": r_translate}


# ---------- feedback ----------
def show_feedback(q, w):
    fb = PS()["fb"]
    rate = X()["S"]["tts_rate"]

    if not fb["graded"]:           # translate: self-grade step
        st.markdown(f"<div class='card'>{fb['detail']}<hr>"
                    f"<div class='ex-en'>เฉลย: {hl_en(w['example_en'], w['target'])}</div>"
                    f"<div style='font-size:.85rem;margin-top:8px'>{DIFF_LEGEND}</div></div>",
                    unsafe_allow_html=True)
        st.caption(f"ตรงกับเฉลย {fb['score']:.0%} · "
                   + ("✅ ใช้คำเป้าหมายแล้ว" if fb["used"] else f"⚠️ ยังไม่ได้ใช้คำว่า {w['word']}")
                   + " · ประโยคเดียวกันแปลได้หลายแบบ ให้คะแนนตามความหมายที่ถูก")
        speak_row([(w["example_en"], "🔊 ฟังเฉลย", rate)])
        labels = {"again": "❌ ผิด", "hard": "😓 พอใช้", "good": "🙂 ถูก", "easy": "😎 ง่ายมาก"}
        c1, c2 = st.columns(2)
        c3, c4 = st.columns(2)
        for col, r in zip((c1, c2, c3, c4), srs.RATINGS):
            col.button(labels[r], key=f"g_{q['n']}_{r}", on_click=cb_grade, args=(r,),
                       type="primary" if r == "good" else "secondary", **WIDE)
        return

    res = fb["result"]
    {"correct": st.success, "near": st.warning, "wrong": st.error}[res](RESULT_TH[res])
    typ = q["type"]
    body = ""
    if typ in ("mc", "context"):
        body = f"<div class='ans'>{html.escape(q['ans'])}</div>"
        if res == "wrong" and fb["detail"]:
            body = f"<div class='ex-th' style='text-align:center'>คุณเลือก: {html.escape(fb['detail'])}</div>" + body
    elif typ in ("type", "cloze"):
        mine = html.escape(fb["detail"]) or "—"
        body = (f"<div class='ex-th' style='text-align:center'>คำตอบของคุณ: {mine}</div>"
                f"<div class='ans'>{html.escape(q['ans'])}</div>")
        if typ == "type" and res == "correct" and norm(fb["detail"]) != norm(q["ans"]):
            body += f"<div class='q'>ถูกเช่นกัน · คำในบทนี้คือ <b>{html.escape(q['ans'])}</b></div>"
    elif typ == "order":
        body = (f"<div class='ex-th'>คุณเรียง: {html.escape(fb['detail'])}</div>" if res == "wrong" else "")
    elif typ in ("dictation", "translate"):
        body = fb["detail"] + (f"<div style='font-size:.85rem;margin-top:6px'>{DIFF_LEGEND}</div>"
                               if typ == "dictation" else "")
    st.markdown(f"<div class='card'>{body}<hr>"
                f"<div class='q' style='margin:0 0 8px'><b>{html.escape(w['word'])}</b> — "
                f"{html.escape(w['meaning_th'])}</div>{card_back_html(w)}</div>",
                unsafe_allow_html=True)
    speak_row([(w["word"], "🔊 คำศัพท์", rate), (w["example_en"], "🔊 ประโยค", rate)])
    info = f"ระบบทวน: {srs.RATING_TH[fb['rating']]} · {fb['sec']:.0f} วินาที"
    if PS()["hint"]:
        info += " · ใช้คำใบ้"
    if fb["extra"]:
        info += f" · {fb['extra']}"
    st.caption(info)
    st.button("ถัดไป ▶", type="primary", on_click=next_q, key=f"nx_{q['n']}", **WIDE)


# ---------- summaries ----------
def summary():
    ps = PS()
    con, V = X()["con"], X()["V"]
    res = ps["results"]
    m = ps["mode"]
    if m == "boss":
        st.balloons()
        st.success(f"👹 ปราบบอสครบ {len(ps['hp'])} คำ!")
    else:
        st.success(f"🎉 จบรอบ {MODES[m][0]}")
    c1, c2, c3 = st.columns(3)
    c1.metric("✅ ถูก", sum(r["result"] == "correct" for r in res))
    c2.metric("🟡 เกือบ", sum(r["result"] == "near" for r in res))
    c3.metric("❌ ผิด", sum(r["result"] == "wrong" for r in res))
    wrong = list(dict.fromkeys(r["wid"] for r in res if r["result"] != "correct"))
    if m == "ladder":
        lv = db.ladder_levels(con)
        st.markdown("#### ระดับล่าสุด")
        for wid in ps["items"]:
            st.markdown(f"- **{V[wid]['word']}** — {LADDER_NAME[lv.get(wid, 0)]}")
    elif wrong:
        st.markdown("#### คำที่ควรทวน")
        for wid in wrong:
            st.markdown(f"- **{V[wid]['word']}** — {V[wid]['meaning_th']}")
        if m in STANDARD:
            st.button("🔁 ฝึกเฉพาะคำนี้อีกรอบ", type="primary", on_click=cb_retry_wrong,
                      args=(m, wrong, ps["scope"]), **WIDE)
    st.button("🏁 กลับไปเลือกโหมด", on_click=cb_back_to_setup, **WIDE)


def ta_result():
    ps = PS()
    con, V = X()["con"], X()["V"]
    if not ps["saved"]:
        ps["prev_best"] = db.ta_best(con, ps["scope"])
        db.save_ta(con, ps["scope"], ps["correct"], ps["wrong"])
        ps["saved"] = True
    st.subheader("⏱ หมดเวลา!")
    if ps["correct"] > ps["prev_best"]:
        st.balloons()
        st.success(f"🏆 สถิติใหม่! (เดิม {ps['prev_best']})")
    c1, c2, c3 = st.columns(3)
    c1.metric("✅ ถูก", ps["correct"])
    c2.metric("❌ ผิด", ps["wrong"])
    c3.metric("🏆 ดีที่สุด", max(ps["correct"], ps["prev_best"]))
    st.caption(f"ขอบเขต: {ps['scope']}")
    if ps["wrong_ids"]:
        st.markdown("#### คำที่ตอบผิด")
        for wid in dict.fromkeys(ps["wrong_ids"]):
            st.markdown(f"- **{V[wid]['word']}** — {V[wid]['meaning_th']}")
    st.button("🔁 เล่นอีกครั้ง", type="primary", on_click=start,
              args=("time", ps["ids"], 0, ps["scope"]), **WIDE)
    st.button("🏁 กลับไปเลือกโหมด", on_click=cb_back_to_setup, **WIDE)


if hasattr(st, "fragment"):
    @st.fragment(run_every=1)
    def ta_timer():
        ps = st.session_state.get("ps")
        if not ps or ps.get("mode") != "time":
            return
        rem = TA_SECONDS - (time.time() - ps["start"])
        if rem <= 0 and not ps["over"]:
            ps["over"] = True
            st.rerun()
        st.progress(max(0.0, rem) / TA_SECONDS, text=f"⏱ {max(0, int(rem))} วินาที")
else:
    def ta_timer():
        ps = PS()
        rem = TA_SECONDS - (time.time() - ps["start"])
        st.progress(max(0.0, rem) / TA_SECONDS, text=f"⏱ เหลือประมาณ {max(0, int(rem))} วินาที")


# ---------- setup ----------
def keep(key, default):
    """Keep widget values after the setup screen is hidden during a session."""
    store = st.session_state.setdefault("_pset", {})
    if key not in st.session_state:
        st.session_state[key] = store.get(key, default)


def remember(*keys):
    store = st.session_state.setdefault("_pset", {})
    for k in keys:
        store[k] = st.session_state[k]


def setup():
    con = X()["con"]
    st.subheader("🎯 ฝึก")
    keep("p_mode", "cloze")
    keep("p_scope", "all")
    keep("p_lessons", [1])
    keep("p_n", 10)
    mode = st.selectbox("โหมด", list(MODES), format_func=lambda k: MODES[k][0], key="p_mode")
    st.caption(MODES[mode][1])
    scope = st.selectbox("ขอบเขตคำ", list(SCOPES), format_func=SCOPES.get, key="p_scope")
    lessons = []
    if scope == "lessons":
        lessons = st.multiselect("บท", db.lessons(con), key="p_lessons")
    ids = db.scope_ids(con, scope, lessons)
    label = SCOPES[scope] + (f" {','.join(map(str, sorted(lessons)))}" if scope == "lessons" else "")
    if mode != "time":
        st.slider("จำนวนบอสสูงสุด" if mode == "boss" else "จำนวนข้อ", 5, 30, step=5, key="p_n")
    n = st.session_state["p_n"]
    remember("p_mode", "p_scope", "p_lessons", "p_n")

    ok = bool(ids)
    msg = f"คำในขอบเขตนี้ {len(ids)} คำ"
    if mode == "boss":
        pool = boss_pool(ids)
        ok = bool(pool)
        msg += f" · บอส (ผิด ≥2 ครั้งใน {BOSS_DAYS} วัน) {len(pool)} คำ"
    elif mode == "ladder":
        lv = db.ladder_levels(con)
        cnt = [0] * (len(LADDER) + 1)
        for i in ids:
            cnt[lv.get(i, 0)] += 1
        msg += "\n\n" + " · ".join(f"{LADDER_NAME[k]}: {cnt[k]}" for k in range(len(cnt)))
        ok = cnt[-1] < len(ids)
    elif mode == "time":
        msg += f" · สถิติดีที่สุด {db.ta_best(con, label)} ข้อ"
    st.caption(msg)
    if not ids:
        st.info("ไม่มีคำในขอบเขตนี้")
    elif mode == "boss" and not ok:
        st.info("ยังไม่มีคำที่ตอบผิดบ่อย 👍")
    elif mode == "ladder" and not ok:
        st.success("ทุกคำในขอบเขตนี้ผ่านครบทุกขั้นแล้ว 🏆")
    st.button("▶️ เริ่ม", type="primary", disabled=not ok, on_click=start,
              args=(mode, ids, n, label), **WIDE)
    if X()["S"].get("practice_srs", True):
        st.caption("ผลจากโหมดฝึกจะอัปเดตระบบทวน: ตอบผิด → กลับมาทวนวันนี้ · "
                   "ตอบถูก → นับเป็นการทวนเฉพาะคำที่ถึงกำหนด (คำใหม่ไม่ถูกดึงเข้าระบบ)")


# ---------- entry ----------
def render(con, S, today):
    V = db.vocab_rows(con)
    by_part = {}
    for w in V.values():
        for p in parts(w["meaning_th"]):
            by_part.setdefault(p, set()).add(w["word"])
    st.session_state["_ctx"] = dict(con=con, S=S, today=today, V=V, by_part=by_part)

    ps = st.session_state.get("ps")
    if not ps:
        setup()
        return

    if ps["mode"] == "time":
        if ps["over"] or time.time() - ps["start"] >= TA_SECONDS:
            ps["over"] = True
            ta_result()
            return
        ta_timer()
        st.caption(f"✅ {ps['correct']} · ❌ {ps['wrong']}   {ps['last_msg']}")
    q = ps["q"]
    if q is None:
        summary()
        return
    w = V[q["wid"]]

    if ps["mode"] in STANDARD or ps["mode"] == "ladder":
        done = ps["i"] + (1 if ps["fb"] and ps["fb"]["graded"] else 0)
        st.progress(done / len(ps["items"]), text=f"ข้อ {ps['i'] + 1} / {len(ps['items'])}")
    elif ps["mode"] == "boss":
        hp = ps["hp"]
        dead = sum(h >= BOSS_WIN for h in hp.values())
        st.progress(dead / len(hp), text=f"👹 ปราบแล้ว {dead} / {len(hp)} · คำนี้ "
                    + "❤️" * hp[q["wid"]] + "🤍" * (BOSS_WIN - hp[q["wid"]]))
    header(q, w)
    if ps["fb"]:
        show_feedback(q, w)
    else:
        RENDER[q["type"]](q, w)
    st.button("⏹ จบการฝึก", key="p_exit", on_click=cb_exit, **WIDE)
