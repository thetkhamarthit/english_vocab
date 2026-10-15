"""SQLite storage: vocab, SRS state, stars, review log, settings, practice data."""
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

REQUIRED = ["id", "lesson", "word", "meaning_th", "example_en", "example_th", "target_in_sentence"]
DEFAULTS = {"new_per_day": 20, "max_reviews": 200, "direction": "EN→TH", "tts_rate": 0.9,
            "practice_srs": True}
SQLITE_MAGIC = b"SQLite format 3\x00"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vocab(
    id INTEGER PRIMARY KEY, lesson INTEGER, word TEXT, meaning_th TEXT,
    example_en TEXT, example_th TEXT, target TEXT);
CREATE TABLE IF NOT EXISTS srs_state(
    word_id INTEGER PRIMARY KEY, ease REAL, interval_days INTEGER, due_date TEXT,
    reps INTEGER, lapses INTEGER, first_seen TEXT, last_review TEXT);
CREATE TABLE IF NOT EXISTS starred(word_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS review_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, word_id INTEGER, mode TEXT,
    rating TEXT, correct INTEGER, response_sec REAL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS ladder(word_id INTEGER PRIMARY KEY, level INTEGER);
CREATE TABLE IF NOT EXISTS ta_scores(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, scope TEXT, correct INTEGER, wrong INTEGER);
CREATE INDEX IF NOT EXISTS ix_due ON srs_state(due_date);
CREATE INDEX IF NOT EXISTS ix_log_ts ON review_log(ts);
CREATE INDEX IF NOT EXISTS ix_log_word ON review_log(word_id, rating);
"""


def connect(path):
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


# ---------- backup / restore ----------
def snapshot_bytes(con, work_dir: Path) -> bytes:
    """Consistent copy of the live DB (SQLite backup API)."""
    tmp = Path(work_dir) / ".backup_tmp.db"
    tmp.unlink(missing_ok=True)
    dst = sqlite3.connect(str(tmp))
    try:
        con.backup(dst)
    finally:
        dst.close()
    data = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    return data


def inspect_backup(data: bytes, work_dir: Path):
    """Validate an uploaded backup. Returns summary dict or raises ValueError."""
    if not data.startswith(SQLITE_MAGIC):
        raise ValueError("ไฟล์นี้ไม่ใช่ไฟล์ vocab.db (ไม่ใช่ฐานข้อมูล SQLite)")
    tmp = Path(work_dir) / ".restore_check.db"
    tmp.write_bytes(data)
    try:
        c = sqlite3.connect(str(tmp))
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"vocab", "srs_state", "review_log"} <= tables:
            raise ValueError("ไฟล์นี้ไม่ใช่ข้อมูลของแอปนี้ (ไม่พบตาราง vocab / srs_state / review_log)")
        cols = {r[1] for r in c.execute("PRAGMA table_info(srs_state)")}
        if not {"word_id", "due_date", "interval_days"} <= cols:
            raise ValueError("ไฟล์นี้ไม่ใช่ข้อมูลของแอปนี้ (โครงสร้างตารางไม่ตรง)")
        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("ไฟล์เสียหาย")
        info = dict(
            words=c.execute("SELECT COUNT(*) FROM vocab").fetchone()[0],
            learned=c.execute("SELECT COUNT(*) FROM srs_state").fetchone()[0],
            reviews=c.execute("SELECT COUNT(*) FROM review_log").fetchone()[0],
            last=c.execute("SELECT MAX(ts) FROM review_log").fetchone()[0],
        )
        c.close()
        return info
    except sqlite3.DatabaseError as e:
        raise ValueError(f"เปิดไฟล์ไม่ได้: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)


def restore_bytes(con, data: bytes, work_dir: Path):
    """Replace the live DB contents with an uploaded backup (same connection stays valid)."""
    inspect_backup(data, work_dir)
    tmp = Path(work_dir) / ".restore_src.db"
    tmp.write_bytes(data)
    try:
        src = sqlite3.connect(str(tmp))
        src.backup(con)
        src.close()
    finally:
        tmp.unlink(missing_ok=True)
    con.executescript(SCHEMA)          # older backups: add tables that are new in this version


def summary(con):
    return dict(
        learned=con.execute("SELECT COUNT(*) FROM srs_state").fetchone()[0],
        reviews=con.execute("SELECT COUNT(*) FROM review_log").fetchone()[0],
        last=con.execute("SELECT MAX(ts) FROM review_log").fetchone()[0],
    )


# ---------- vocab ----------
def import_excel(con, src):
    """Upsert vocab from Excel (sheet 'vocab'). SRS progress is kept."""
    df = pd.read_excel(src, sheet_name="vocab", dtype={"id": int}).fillna("")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"ไม่พบคอลัมน์: {', '.join(missing)}")
    if df["id"].duplicated().any():
        raise ValueError("พบ id ซ้ำในไฟล์")
    rows = [(int(r.id), int(r.lesson), str(r.word).strip(), str(r.meaning_th).strip(),
             str(r.example_en).strip(), str(r.example_th).strip(),
             str(r.target_in_sentence).strip() or str(r.word).strip())
            for r in df.itertuples()]
    with con:
        con.executemany("INSERT OR REPLACE INTO vocab VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


def vocab_count(con):
    return con.execute("SELECT COUNT(*) FROM vocab").fetchone()[0]


def vocab_rows(con):
    return {r["id"]: dict(r) for r in con.execute("SELECT * FROM vocab")}


def get_word(con, wid):
    r = con.execute("SELECT * FROM vocab WHERE id=?", (wid,)).fetchone()
    return dict(r) if r else None


def lessons(con):
    return [r[0] for r in con.execute("SELECT DISTINCT lesson FROM vocab ORDER BY lesson")]


# ---------- SRS ----------
def get_state(con, wid):
    r = con.execute("SELECT * FROM srs_state WHERE word_id=?", (wid,)).fetchone()
    return dict(r) if r else None


def save_state(con, wid, s):
    with con:
        con.execute("""INSERT OR REPLACE INTO srs_state
            (word_id, ease, interval_days, due_date, reps, lapses, first_seen, last_review)
            VALUES (?,?,?,?,?,?,?,?)""",
                    (wid, s["ease"], s["interval_days"], s["due_date"], s["reps"],
                     s["lapses"], s["first_seen"], s["last_review"]))


def log_review(con, wid, mode, rating, sec):
    with con:
        con.execute("INSERT INTO review_log(ts, word_id, mode, rating, correct, response_sec) "
                    "VALUES (?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), wid, mode, rating,
                     int(rating != "again"), round(sec, 1)))


def due_ids(con, today, limit):
    return [r[0] for r in con.execute(
        "SELECT word_id FROM srs_state WHERE due_date<=? ORDER BY due_date, word_id LIMIT ?",
        (today, limit))]


def new_ids(con, limit):
    return [r[0] for r in con.execute(
        "SELECT id FROM vocab WHERE id NOT IN (SELECT word_id FROM srs_state) "
        "ORDER BY id LIMIT ?", (limit,))]


def new_seen_today(con, today):
    return con.execute("SELECT COUNT(*) FROM srs_state WHERE first_seen=?", (today,)).fetchone()[0]


def reviewed_today(con, today):
    return con.execute("SELECT COUNT(*) FROM review_log WHERE ts LIKE ?", (today + "%",)).fetchone()[0]


def status_counts(con, mastered_days):
    total = vocab_count(con)
    seen, mastered = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(interval_days>=?),0) FROM srs_state", (mastered_days,)).fetchone()
    return {"new": total - seen, "learning": seen - mastered, "mastered": mastered, "total": total}


def streak(con, today: date):
    days = {r[0] for r in con.execute("SELECT DISTINCT substr(ts,1,10) FROM review_log")}
    d = today if today.isoformat() in days else today - timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


# ---------- stars ----------
def is_starred(con, wid):
    return con.execute("SELECT 1 FROM starred WHERE word_id=?", (wid,)).fetchone() is not None


def set_star(con, wid, on):
    with con:
        if on:
            con.execute("INSERT OR IGNORE INTO starred VALUES (?)", (wid,))
        else:
            con.execute("DELETE FROM starred WHERE word_id=?", (wid,))


# ---------- word list ----------
def word_table(con):
    return pd.read_sql_query("""
        SELECT v.*, s.interval_days, s.due_date, s.reps, s.lapses,
               (st.word_id IS NOT NULL) AS starred,
               (SELECT COUNT(*) FROM review_log l WHERE l.word_id=v.id AND l.rating='again') AS wrong
        FROM vocab v
        LEFT JOIN srs_state s ON s.word_id=v.id
        LEFT JOIN starred st ON st.word_id=v.id
        ORDER BY v.id""", con)


# ---------- practice ----------
def scope_ids(con, kind, lesson_list=()):
    sql = {
        "all": "SELECT id FROM vocab",
        "learned": "SELECT word_id FROM srs_state",
        "starred": "SELECT word_id FROM starred",
        "wrong": "SELECT word_id FROM review_log WHERE rating='again' "
                 "GROUP BY word_id HAVING COUNT(*)>=2",
    }
    if kind == "lessons":
        if not lesson_list:
            return []
        q = f"SELECT id FROM vocab WHERE lesson IN ({','.join('?' * len(lesson_list))}) ORDER BY id"
        return [r[0] for r in con.execute(q, list(lesson_list))]
    return sorted(r[0] for r in con.execute(sql[kind]))


def wrong_counts(con, since=None):
    q, args = "SELECT word_id, COUNT(*) FROM review_log WHERE rating='again'", []
    if since:
        q += " AND ts>=?"
        args.append(since)
    return {r[0]: r[1] for r in con.execute(q + " GROUP BY word_id", args)}


def ladder_levels(con):
    return {r[0]: r[1] for r in con.execute("SELECT word_id, level FROM ladder")}


def set_ladder(con, wid, level):
    with con:
        con.execute("INSERT OR REPLACE INTO ladder VALUES (?,?)", (wid, level))


def save_ta(con, scope, correct, wrong):
    with con:
        con.execute("INSERT INTO ta_scores(ts, scope, correct, wrong) VALUES (?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), scope, correct, wrong))


def ta_best(con, scope):
    return con.execute("SELECT COALESCE(MAX(correct),0) FROM ta_scores WHERE scope=?",
                       (scope,)).fetchone()[0]


# ---------- settings ----------
def get_settings(con):
    s = dict(DEFAULTS)
    for k, v in con.execute("SELECT key, value FROM settings"):
        s[k] = json.loads(v)
    return s


def set_setting(con, key, value):
    with con:
        con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
