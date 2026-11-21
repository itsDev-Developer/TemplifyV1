"""SQLite persistence (stdlib): users + per-user settings, roles, channels, drafts (in-progress posters),
await-states, file_id cache, global settings, usage counters.

One connection guarded by a lock, WAL mode: every operation is sub-millisecond, which comfortably serves
thousands of users from a single instance. To run several instances, replace this module with a Postgres
implementation of the same functions (it is the only place that touches storage).
On hosts with an ephemeral disk the DB file is snapshotted to the storage channel (see logs.Archive)."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from . import config

PATH = Path(config.DATA_DIR) / "bot.db"
_lock = threading.RLock()
_db: sqlite3.Connection | None = None
on_change = None  # set by logs.Archive: called after writes that are worth backing up

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT, username TEXT, role TEXT DEFAULT 'user', banned INTEGER DEFAULT 0,
  settings TEXT DEFAULT '{}', created REAL, last_seen REAL, renders INTEGER DEFAULT 0, day TEXT, day_renders INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS channels(user_id INTEGER, chat_id INTEGER, title TEXT, PRIMARY KEY(user_id, chat_id));
CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, user_id INTEGER, data TEXT, updated REAL);
CREATE INDEX IF NOT EXISTS drafts_updated ON drafts(updated);
CREATE TABLE IF NOT EXISTS states(user_id INTEGER PRIMARY KEY, data TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, file_id TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS api_keys(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, owner INTEGER, hash TEXT UNIQUE, prefix TEXT,
  rpm INTEGER DEFAULT 30, daily INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created REAL, last_used REAL,
  calls INTEGER DEFAULT 0, day TEXT, day_calls INTEGER DEFAULT 0);
"""

# Schema versions (PRAGMA user_version). 1 = original tables, 2 = api_keys. Add ALTER statements here when a table changes:
# each entry runs once, in order, on databases created before it existed.
MIGRATIONS: list[list[str]] = [
    [],  # -> v1 baseline
    [],  # -> v2 api_keys (created by SCHEMA, nothing to alter)
]


# ------------------------------------------------------------------ lifecycle
def init(path: Path | None = None) -> None:
    global _db, PATH
    if path:
        PATH = Path(path)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        if _db:
            _db.close()
        _db = sqlite3.connect(PATH, check_same_thread=False, isolation_level=None, timeout=15)
        _db.row_factory = sqlite3.Row
        _db.execute("PRAGMA journal_mode=WAL")
        _db.execute("PRAGMA synchronous=NORMAL")
        _db.executescript(SCHEMA)
        _migrate(_db)
    _gcache.clear()


def _migrate(db) -> None:
    cur = db.execute("PRAGMA user_version").fetchone()[0]
    for ver in range(cur, len(MIGRATIONS)):
        for stmt in MIGRATIONS[ver]:
            db.execute(stmt)
        db.execute(f"PRAGMA user_version={ver + 1}")


def schema_version() -> int:
    return _x("PRAGMA user_version").fetchone()[0]


def close() -> None:
    global _db
    with _lock:
        if _db:
            _db.close()
            _db = None


def exists() -> bool:
    return PATH.exists()


def snapshot() -> bytes:
    """Consistent copy of the whole database (SQLite online backup API)."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with _lock:
            dst = sqlite3.connect(tmp)
            _db.backup(dst)
            dst.close()
        return Path(tmp).read_bytes()
    finally:
        os.unlink(tmp)


def restore(raw: bytes) -> None:
    """Replace the DB with a backup. Call before init() (or it re-inits)."""
    close()
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_bytes(raw)
    init()


def _x(sql: str, args=()):
    with _lock:
        return _db.execute(sql, args)


def _changed() -> None:
    if on_change:
        on_change()


# ------------------------------------------------------------------ users
def touch_user(uid: int, name: str, username: str | None, owner: bool = False) -> tuple[dict, bool]:
    now = time.time()
    with _lock:
        row = _x("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if row is None:
            _x("INSERT INTO users(id,name,username,role,created,last_seen) VALUES(?,?,?,?,?,?)",
               (uid, name, username or "", "owner" if owner else "user", now, now))
            _changed()
            return dict(_x("SELECT * FROM users WHERE id=?", (uid,)).fetchone()), True
        if owner and row["role"] != "owner":
            _x("UPDATE users SET role='owner' WHERE id=?", (uid,))
        _x("UPDATE users SET last_seen=?, name=?, username=? WHERE id=?", (now, name, username or "", uid))
        return dict(_x("SELECT * FROM users WHERE id=?", (uid,)).fetchone()), False


def get_user(uid: int) -> dict | None:
    r = _x("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(r) if r else None


def set_role(uid: int, role: str) -> bool:
    n = _x("UPDATE users SET role=? WHERE id=?", (role, uid)).rowcount
    _changed()
    return bool(n)


def set_banned(uid: int, banned: bool) -> bool:
    n = _x("UPDATE users SET banned=? WHERE id=?", (int(banned), uid)).rowcount
    _changed()
    return bool(n)


def user_ids(role: str | None = None) -> list[int]:
    q, a = ("SELECT id FROM users WHERE banned=0", ()) if not role else ("SELECT id FROM users WHERE role=?", (role,))
    return [r["id"] for r in _x(q, a).fetchall()]


def usage_today(uid: int) -> int:
    day = time.strftime("%Y-%m-%d")
    r = _x("SELECT day, day_renders FROM users WHERE id=?", (uid,)).fetchone()
    return r["day_renders"] if r and r["day"] == day else 0


def bump_usage(uid: int) -> None:
    day = time.strftime("%Y-%m-%d")
    with _lock:
        r = _x("SELECT day FROM users WHERE id=?", (uid,)).fetchone()
        if r and r["day"] == day:
            _x("UPDATE users SET renders=renders+1, day_renders=day_renders+1 WHERE id=?", (uid,))
        else:
            _x("UPDATE users SET renders=renders+1, day=?, day_renders=1 WHERE id=?", (day, uid))
    _changed()


# ------------------------------------------------------------------ per-user settings
def settings(uid: int) -> dict:
    r = _x("SELECT settings FROM users WHERE id=?", (uid,)).fetchone()
    try:
        return json.loads(r["settings"]) if r else {}
    except Exception:
        return {}


def uset(uid: int, key: str, value) -> None:
    with _lock:
        s = settings(uid)
        if value is None:
            s.pop(key, None)
        else:
            s[key] = value
        _x("UPDATE users SET settings=? WHERE id=?", (json.dumps(s), uid))
    _changed()


# ------------------------------------------------------------------ global settings (admin panel)
_gcache: dict[str, str] = {}


def gget(key: str, default=None):
    with _lock:
        if key not in _gcache:
            r = _x("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            _gcache[key] = r["value"] if r else None
        v = _gcache[key]
    if v is None:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def gset(key: str, value) -> None:
    with _lock:
        if value is None:
            _x("DELETE FROM kv WHERE key=?", (key,))
            _gcache[key] = None
        else:
            _x("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
            _gcache[key] = json.dumps(value)
    _changed()


# ------------------------------------------------------------------ channels
def add_channel(uid: int, chat_id: int, title: str) -> None:
    _x("INSERT INTO channels(user_id,chat_id,title) VALUES(?,?,?) ON CONFLICT(user_id,chat_id) DO UPDATE SET title=excluded.title",
       (uid, chat_id, title))
    _changed()


def channels(uid: int) -> list[dict]:
    return [dict(r) for r in _x("SELECT chat_id,title FROM channels WHERE user_id=? ORDER BY rowid", (uid,)).fetchall()]


def remove_channel(uid: int, chat_id: int) -> None:
    _x("DELETE FROM channels WHERE user_id=? AND chat_id=?", (uid, chat_id))
    _changed()


# ------------------------------------------------------------------ drafts (callbacks carry only a short id)
def draft_new(uid: int, data: dict) -> str:
    did = secrets.token_hex(4)
    _x("INSERT INTO drafts(id,user_id,data,updated) VALUES(?,?,?,?)", (did, uid, json.dumps(data), time.time()))
    return did


def draft_get(did: str, uid: int | None = None) -> dict | None:
    r = _x("SELECT user_id,data FROM drafts WHERE id=?", (did,)).fetchone()
    if r is None or (uid is not None and r["user_id"] != uid):
        return None
    return json.loads(r["data"])


def draft_save(did: str, data: dict) -> None:
    _x("UPDATE drafts SET data=?, updated=? WHERE id=?", (json.dumps(data), time.time(), did))


def draft_del(did: str) -> None:
    _x("DELETE FROM drafts WHERE id=?", (did,))


def cleanup(max_age: float = 3 * 86400) -> None:
    now = time.time()
    _x("DELETE FROM drafts WHERE updated<?", (now - max_age,))
    _x("DELETE FROM states WHERE expires<?", (now,))
    _x("DELETE FROM cache WHERE ts<?", (now - 90 * 86400,))


# ------------------------------------------------------------------ "waiting for the user's next message"
def state_set(uid: int, data: dict, ttl: int = 900) -> None:
    _x("INSERT INTO states(user_id,data,expires) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, expires=excluded.expires",
       (uid, json.dumps(data), time.time() + ttl))


def state_get(uid: int) -> dict | None:
    r = _x("SELECT data,expires FROM states WHERE user_id=?", (uid,)).fetchone()
    if r is None or r["expires"] < time.time():
        return None
    return json.loads(r["data"])


def state_clear(uid: int) -> None:
    _x("DELETE FROM states WHERE user_id=?", (uid,))


# ------------------------------------------------------------------ file_id cache
def cache_get(key: str) -> str | None:
    r = _x("SELECT file_id FROM cache WHERE key=?", (key,)).fetchone()
    return r["file_id"] if r else None


def cache_put(key: str, file_id: str) -> None:
    _x("INSERT INTO cache(key,file_id,ts) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET file_id=excluded.file_id, ts=excluded.ts",
       (key, file_id, time.time()))


def stats() -> dict:
    g = lambda q: _x(q).fetchone()[0] or 0
    today = time.strftime("%Y-%m-%d")
    return {
        "users": g("SELECT COUNT(*) FROM users"),
        "active_today": g(f"SELECT COUNT(*) FROM users WHERE day='{today}'"),
        "posters": g("SELECT SUM(renders) FROM users"),
        "posters_today": g(f"SELECT SUM(day_renders) FROM users WHERE day='{today}'"),
        "cached": g("SELECT COUNT(*) FROM cache"),
        "drafts": g("SELECT COUNT(*) FROM drafts"),
        "channels": g("SELECT COUNT(*) FROM channels"),
        "banned": g("SELECT COUNT(*) FROM users WHERE banned=1"),
    }


# ------------------------------------------------------------------ API keys (for other bots, see api.py)
def _hash(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def api_key_create(name: str, owner: int, rpm: int = 30, daily: int = 0) -> tuple[int, str]:
    """-> (id, token). The token is shown once; only its SHA-256 is stored."""
    token = "pbk_" + secrets.token_urlsafe(30)
    with _lock:
        cur = _x("INSERT INTO api_keys(name,owner,hash,prefix,rpm,daily,created) VALUES(?,?,?,?,?,?,?)",
                 (name[:40], owner, _hash(token), token[:9], max(1, int(rpm)), max(0, int(daily)), time.time()))
        kid = cur.lastrowid
    if on_change:
        on_change()
    return kid, token


def api_key_lookup(token: str) -> dict | None:
    import hmac
    h = _hash(token or "")
    r = _x("SELECT * FROM api_keys WHERE hash=? AND active=1", (h,)).fetchone()
    return dict(r) if r and hmac.compare_digest(r["hash"], h) else None


def api_key_use(kid: int) -> tuple[int, int]:
    """Count a call; -> (calls today, daily limit)."""
    today = time.strftime("%Y-%m-%d")
    with _lock:
        _x("UPDATE api_keys SET calls=calls+1, last_used=?, day_calls=CASE WHEN day=? THEN day_calls+1 ELSE 1 END, day=? WHERE id=?",
           (time.time(), today, today, kid))
        r = _x("SELECT day_calls, daily FROM api_keys WHERE id=?", (kid,)).fetchone()
    return (r["day_calls"], r["daily"]) if r else (0, 0)


def api_keys() -> list[dict]:
    return [dict(r) for r in _x("SELECT * FROM api_keys ORDER BY id").fetchall()]


def api_key_revoke(kid: int) -> bool:
    with _lock:
        n = _x("UPDATE api_keys SET active=0 WHERE id=? AND active=1", (kid,)).rowcount
    if n and on_change:
        on_change()
    return bool(n)
