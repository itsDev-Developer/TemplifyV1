"""Logs channel + storage channel (both configurable at runtime from /admin, env vars are the fallback).

LogChannel - queued, batched messages (one send every ~3 s), so bursts never hit Telegram rate limits.
Archive    - every finished poster is uploaded to the storage channel as a full-quality document with a caption.
             The SQLite database is snapshotted there too (pinned `bot.db`, at most once a minute after changes)
             and restored on start-up when the local disk is empty (Render's disk is ephemeral).
Both are no-ops while no channel is set. The bot must be an admin of each channel."""
from __future__ import annotations

import html
import logging
import queue
import threading
import time

from . import config, store
from .tg import Bot, TgError

log = logging.getLogger("posterbot")


def esc(x) -> str:
    return html.escape(str(x), quote=False)


def _chan(key: str, fallback: int) -> int:
    try:
        return int(store.gget(key, "") or fallback or 0)
    except (TypeError, ValueError):
        return fallback or 0


class LogChannel:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.q: queue.Queue[str] = queue.Queue(maxsize=500)
        self._started = False
        self._lock = threading.Lock()

    @property
    def chat_id(self) -> int:
        return _chan("log_channel", config.LOG_CHANNEL_ID)

    def send(self, text: str) -> None:
        if not self.chat_id:
            return
        with self._lock:
            if not self._started:
                threading.Thread(target=self._run, daemon=True, name="logchannel").start()
                self._started = True
        try:
            self.q.put_nowait(f"{time.strftime('%H:%M:%S')} {text}")
        except queue.Full:
            pass

    def _run(self) -> None:
        while True:
            batch = [self.q.get()]
            time.sleep(3)  # let a burst accumulate
            while len(batch) < 40:
                try:
                    batch.append(self.q.get_nowait())
                except queue.Empty:
                    break
            self.flush(batch)

    def flush(self, batch: list[str]) -> None:
        msg = ""
        for line in batch:
            if len(msg) + len(line) + 1 > 3800:
                self._post(msg)
                msg = ""
            msg += line + "\n"
        if msg:
            self._post(msg)

    def drain(self) -> None:
        """Send whatever is queued right now (graceful shutdown)."""
        batch = []
        while True:
            try:
                batch.append(self.q.get_nowait())
            except queue.Empty:
                break
        if batch and self.chat_id:
            self.flush(batch)

    def _post(self, text: str) -> None:
        try:
            self.bot.send(self.chat_id, text)
        except TgError as e:
            print("log channel send failed:", e)

    # ---- typed events
    def started(self, mode: str) -> None:
        self.send(f"🟢 <b>Bot started</b> @{esc(self.bot.me.get('username', '?'))} · {mode} · scale {config.RENDER_SCALE}")

    def stopped(self) -> None:
        self.send("🔴 <b>Bot stopping</b> (shutdown signal)")

    def new_user(self, uid, name, username) -> None:
        self.send(f"👤 <b>New user</b> {esc(name)} {('@' + esc(username)) if username else ''} <code>{uid}</code>")

    def poster(self, uid, name, title, tpl, ms=0, cached=False) -> None:
        self.send(f"🖼 {esc(name)} <code>{uid}</code> → <b>{esc(title)}</b> · {esc(tpl)}" + (" · ⚡ cached" if cached else ""))

    def error(self, where: str, err) -> None:
        self.send(f"🔴 <b>Error</b> in {esc(where)}: <code>{esc(str(err)[:600])}</code>")


class ChannelLogHandler(logging.Handler):
    """Forwards WARNING+ records of the whole app to the logs channel."""

    def __init__(self, ch: LogChannel):
        super().__init__(logging.WARNING)
        self.ch = ch

    def emit(self, record):
        try:
            self.ch.send(f"⚠️ {record.levelname} {esc(record.name)}: <code>{esc(record.getMessage())[:600]}</code>")
        except Exception:
            pass


class Archive:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        store.on_change = self._schedule_backup

    @property
    def chat_id(self) -> int:
        return _chan("storage_channel", config.STORAGE_CHANNEL_ID)

    @property
    def on(self) -> bool:
        return bool(self.chat_id)

    def save_poster(self, data: bytes, name: str, caption: str) -> None:
        if not self.on:
            return
        try:
            self.bot.send_document(self.chat_id, data, name=name, caption=caption[:1000])
        except TgError as e:
            log.warning("storage upload failed: %s", e)

    # ---- database backup / restore
    def restore_if_empty(self) -> bool:
        """Fresh disk + env STORAGE_CHANNEL_ID set: pull the pinned bot.db backup before the DB is opened."""
        cid = config.STORAGE_CHANNEL_ID
        if not cid or store.exists():
            return False
        try:
            pinned = (self.bot.call("getChat", chat_id=cid) or {}).get("pinned_message") or {}
            doc = pinned.get("document")
            if doc and doc.get("file_name") == "bot.db":
                store.PATH.parent.mkdir(parents=True, exist_ok=True)
                store.PATH.write_bytes(self.bot.download(doc["file_id"], max_bytes=200 * 1024 * 1024))
                log.info("database restored from the storage channel")
                return True
        except Exception as e:
            log.warning("restore failed: %s", e)
        return False

    def _schedule_backup(self) -> None:
        if not self.on:
            return
        with self._lock:
            if self._timer:
                return  # one backup per 60 s window
            self._timer = threading.Timer(60, self.backup_now)
            self._timer.daemon = True
            self._timer.start()

    def backup_now(self) -> None:
        with self._lock:
            self._timer = None
        if not self.on:
            return
        try:
            st = store.stats()
            m = self.bot.send_document(self.chat_id, store.snapshot(), name="bot.db",
                                       caption=f"db backup · {st['users']} users · {st['posters']} posters",
                                       disable_notification=True)
            self.bot.call("pinChatMessage", chat_id=self.chat_id, message_id=m["message_id"], disable_notification=True)
        except Exception as e:
            log.warning("db backup failed: %s", e)
