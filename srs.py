"""Spaced repetition (SM-2 variant) with Again / Hard / Good / Easy ratings."""
from datetime import date, timedelta

RATINGS = ["again", "hard", "good", "easy"]
RATING_TH = {"again": "ไม่ได้", "hard": "ยาก", "good": "ได้", "easy": "ง่าย"}
MIN_EASE, START_EASE, MASTERED_DAYS = 1.3, 2.5, 21


def _intervals(state):
    """Return {rating: interval_days} for a card state (None = new card)."""
    if not state or state["reps"] == 0:
        return {"again": 0, "hard": 1, "good": 2, "easy": 4}
    i, e = max(1, state["interval_days"]), state["ease"]
    hard = max(i + 1, round(i * 1.2)) if i > 1 else 2
    good = max(hard + 1, round(i * e))
    easy = max(good + 1, round(i * e * 1.3))
    return {"again": 0, "hard": hard, "good": good, "easy": easy}


def schedule(state, rating, today: date):
    """Apply a rating and return the new state dict."""
    s = dict(state) if state else {
        "ease": START_EASE, "interval_days": 0, "reps": 0, "lapses": 0,
        "first_seen": today.isoformat(), "last_review": None,
    }
    ivl = _intervals(state)[rating]
    same_day_retry = s["reps"] == 0 and s["last_review"] == today.isoformat()

    if rating == "again":
        if not same_day_retry:              # penalise only once per day
            s["ease"] = max(MIN_EASE, s["ease"] - 0.2)
            if s["reps"] > 0:
                s["lapses"] += 1
        s["reps"] = 0
    else:
        s["ease"] = max(MIN_EASE, s["ease"] + {"hard": -0.15, "good": 0, "easy": 0.15}[rating])
        s["reps"] += 1

    s["interval_days"] = ivl
    s["due_date"] = (today + timedelta(days=ivl)).isoformat()
    s["last_review"] = today.isoformat()
    return s


def preview(state):
    return {r: label(d) for r, d in _intervals(state).items()}


def label(days):
    if days == 0:
        return "ทวนซ้ำวันนี้"
    if days < 30:
        return f"{days} วัน"
    if days < 365:
        return f"{days / 30:.1f} เดือน".replace(".0 ", " ")
    return f"{days / 365:.1f} ปี".replace(".0 ", " ")


def status(state):
    if not state:
        return "new"
    return "mastered" if state["interval_days"] >= MASTERED_DAYS else "learning"
