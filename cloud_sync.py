"""Keep vocab.db in a private GitHub repo (for Streamlit Community Cloud).

Cloud disk is wiped on every reboot/sleep, so:
- on start: download vocab.db from GitHub (if it exists there)
- while running: a background thread uploads a snapshot when data changed
  (at most every PUSH_EVERY seconds, or right away when force_sync() is called)

Turned on only when .streamlit/secrets.toml (or Cloud "Secrets") has:
    [github]
    token = "github_pat_..."
    repo = "USERNAME/vocab-data"
    # optional: branch = "main", path = "vocab.db"
Without secrets the app works locally exactly as before.
"""
import base64
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import streamlit as st

API = "https://api.github.com"
PUSH_EVERY = 60          # seconds between automatic uploads while data keeps changing
CHECK_EVERY = 5          # background thread wake-up interval
SQLITE_MAGIC = b"SQLite format 3\x00"


class SyncError(Exception):
    pass


# ---------- config ----------
def config():
    try:
        g = st.secrets["github"]
        token, repo = g.get("token", ""), g.get("repo", "")
    except Exception:
        return None
    if not token or not repo:
        return None
    return dict(token=token, repo=repo.strip().strip("/"),
                branch=g.get("branch", "main"), path=g.get("path", "vocab.db"))


def enabled():
    return config() is not None


def db_path(base: Path) -> Path:
    """Cloud mode uses a separate file name, so a vocab.db accidentally committed
    to the app repo can never overwrite the synced progress."""
    return base / (".vocab_cloud.db" if enabled() else "vocab.db")


# ---------- GitHub REST ----------
def _req(cfg, method, url, body=None, raw=False):
    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "vocab-app",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _file_url(cfg):
    return f"{API}/repos/{cfg['repo']}/contents/{urllib.parse.quote(cfg['path'])}"


def _ref(cfg):
    return "?ref=" + urllib.parse.quote(cfg["branch"])


def _explain(e):
    if isinstance(e, urllib.error.HTTPError):
        return {401: "token ไม่ถูกต้องหรือหมดอายุ",
                403: "token ไม่มีสิทธิ์ (ต้องเป็น Contents: Read and write)",
                404: "ไม่พบ repo หรือ token ไม่มีสิทธิ์เข้าถึง repo นี้"}.get(e.code, f"HTTP {e.code}")
    return str(e)


def _remote_sha(cfg):
    try:
        return json.loads(_req(cfg, "GET", _file_url(cfg) + _ref(cfg)))["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


# ---------- shared state (one per server process) ----------
@st.cache_resource
def _state():
    return dict(lock=threading.Lock(), wake=threading.Event(), sha=None, pushed=0,
                last_try=0.0, last_ok=None, error="", thread=None, mode="local")


# ---------- restore on start ----------
def restore(path: Path):
    """Call once before opening the DB. Raises SyncError if GitHub can't be read,
    so an empty DB is never created and pushed over real progress."""
    cfg = config()
    s = _state()
    if not cfg:
        s["mode"] = "local"
        return "local"
    if path.exists():                      # same container still alive: local copy is newest
        try:
            s["sha"] = _remote_sha(cfg)
        except Exception:
            s["sha"] = None                # resolved later on first upload
        s["mode"] = "kept"
        return "kept"
    try:
        sha = _remote_sha(cfg)
        if sha is None:                    # no file yet: make sure the repo itself is reachable
            _req(cfg, "GET", f"{API}/repos/{cfg['repo']}")
            s.update(sha=None, mode="new")
            return "new"
        data = _req(cfg, "GET", _file_url(cfg) + _ref(cfg), raw=True)
    except Exception as e:
        raise SyncError(_explain(e)) from e
    if not data.startswith(SQLITE_MAGIC):
        raise SyncError(f"ไฟล์ {cfg['path']} บน GitHub ไม่ใช่ฐานข้อมูล SQLite")
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    s.update(sha=sha, mode="restored", last_ok=datetime.now())
    return "restored"


# ---------- upload ----------
def _snapshot(path: Path) -> bytes:
    """Consistent copy via SQLite backup API (own connection, safe from a thread)."""
    tmp = path.with_suffix(".snap")
    src = sqlite3.connect(str(path))
    dst = sqlite3.connect(str(tmp))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    data = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    return data


def _push(cfg, s, path, changes):
    data = _snapshot(path)
    body = dict(message=f"sync {datetime.now():%Y-%m-%d %H:%M:%S}",
                content=base64.b64encode(data).decode(), branch=cfg["branch"])
    if s["sha"]:
        body["sha"] = s["sha"]
    try:
        resp = _req(cfg, "PUT", _file_url(cfg), body)
    except urllib.error.HTTPError as e:
        if e.code not in (409, 422):       # sha out of date -> refresh once and retry
            raise
        sha = _remote_sha(cfg)
        body.pop("sha", None)
        if sha:
            body["sha"] = sha
        resp = _req(cfg, "PUT", _file_url(cfg), body)
    s["sha"] = json.loads(resp)["content"]["sha"]
    s["pushed"] = changes
    s["last_ok"] = datetime.now()
    s["error"] = ""


def _worker(cfg, s, con, path):
    while True:
        s["wake"].wait(CHECK_EVERY)
        force = s["wake"].is_set()
        s["wake"].clear()
        try:
            changes = con.total_changes
            if changes == s["pushed"]:
                continue
            if not force and time.time() - s["last_try"] < PUSH_EVERY:
                continue
            s["last_try"] = time.time()
            with s["lock"]:
                _push(cfg, s, path, changes)
        except Exception as e:             # keep running; retry next round
            s["error"] = _explain(e)


def start(con, path: Path):
    """Start the background uploader once per server process."""
    cfg = config()
    s = _state()
    if not cfg or (s["thread"] and s["thread"].is_alive()):
        return
    s["pushed"] = con.total_changes        # nothing new yet
    s["last_try"] = time.time()
    t = threading.Thread(target=_worker, args=(cfg, s, con, path), daemon=True)
    t.start()
    s["thread"] = t


def force_sync():
    if enabled():
        _state()["wake"].set()


def sync_now(con, path: Path):
    """Blocking upload (Settings button). Returns error text or ''."""
    cfg = config()
    if not cfg:
        return "ยังไม่ได้ตั้งค่า GitHub"
    s = _state()
    try:
        with s["lock"]:
            s["last_try"] = time.time()
            _push(cfg, s, path, con.total_changes)
        return ""
    except Exception as e:
        s["error"] = _explain(e)
        return s["error"]


def status(con):
    s = _state()
    cfg = config()
    return dict(enabled=cfg is not None, repo=cfg["repo"] if cfg else "",
                pending=con.total_changes != s["pushed"], last_ok=s["last_ok"],
                error=s["error"], mode=s["mode"])
