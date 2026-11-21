"""App: update dispatch, access control, rate limiting, commands. Poster flow lives in flow.py,
settings/admin/channels/start in panels.py."""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

from . import config, images, metrics, store
from .caption import e
from .flow import Flow
from .kb import btn, kb
from .logs import Archive, LogChannel
from .panels import Panels
from .providers.anilist import AniList
from .providers.tmdb import TMDB
from .tg import Bot, TgError

log = logging.getLogger("posterbot")
ADMIN_ROLES = ("owner", "sudo")
SEARCH_CMDS = {"/anime": "anime", "/manga": "manga", "/movie": "movie", "/tvshows": "tv", "/tv": "tv"}


class RateLimiter:
    """Token bucket per user: bursts of `cap` events, refilling one per `every` seconds."""

    def __init__(self, cap=8, every=0.7):
        self.cap, self.every = cap, every
        self.b: dict[int, list[float]] = {}
        self.lock = threading.Lock()

    def ok(self, uid: int) -> bool:
        now = time.time()
        with self.lock:
            tok, ts = self.b.get(uid, (self.cap, now))
            tok = min(self.cap, tok + (now - ts) / self.every)
            if tok < 1:
                self.b[uid] = [tok, now]
                return False
            self.b[uid] = [tok - 1, now]
            if len(self.b) > 20000:  # keep memory bounded
                for k in list(self.b)[:5000]:
                    self.b.pop(k, None)
            return True


class App:
    def __init__(self, bot: Bot, logs: LogChannel, archive: Archive):
        self.bot, self.logs, self.archive = bot, logs, archive
        self.tmdb = TMDB(config.TMDB_API_KEY) if config.TMDB_API_KEY else None
        self.anilist = AniList()
        self.limiter = RateLimiter()
        self._locks = [threading.Lock() for _ in range(64)]  # one user's updates run one at a time
        self._seen: OrderedDict[int, None] = OrderedDict()
        self._seen_lock = threading.Lock()
        self._warned: dict[int, float] = {}
        images.register_loader("tg", lambda fid: bot.download(fid))
        self.panels = Panels(self)
        self.flow = Flow(self)

    # ------------------------------------------------------------ helpers
    def is_admin(self, uid: int) -> bool:
        u = store.get_user(uid)
        return bool(u and u["role"] in ADMIN_ROLES)

    def say(self, chat, text, **kw):
        return self.bot.send(chat, text, **kw)

    def _dupe(self, update_id: int) -> bool:
        with self._seen_lock:
            if update_id in self._seen:
                return True
            self._seen[update_id] = None
            while len(self._seen) > 4000:
                self._seen.popitem(last=False)
        return False

    # ------------------------------------------------------------ entry
    def handle(self, upd: dict) -> None:
        t0 = time.time()
        metrics.inc("updates")
        try:
            if "update_id" in upd and self._dupe(upd["update_id"]):
                return
            if "message" in upd:
                self._message(upd["message"])
            elif "callback_query" in upd:
                self._callback(upd["callback_query"])
        except Exception as e_:  # one bad update must never kill a worker
            metrics.inc("errors")
            log.exception("update failed")
            self.logs.error("update", e_)
            chat = (upd.get("message") or (upd.get("callback_query") or {}).get("message") or {}).get("chat", {}).get("id")
            if chat:
                try:
                    self.bot.send(chat, "⚠️ Something went wrong. Please try again.")
                except TgError:
                    pass
        finally:
            metrics.observe("update_seconds", time.time() - t0)

    def _gate(self, user: dict, chat: int, cb_id: str | None) -> bool:
        """Ban / maintenance / access / rate limit. False = stop processing."""
        uid, role = user["id"], user["role"]
        deny = None
        if user["banned"]:
            deny = "🚫 You are banned from using this bot."
        elif role not in ADMIN_ROLES and store.gget("maintenance", False):
            deny = "🛠 The bot is under maintenance. Please try again in a little while."
        elif role == "user" and not store.gget("public", True):
            deny = "🔒 This bot is private. Ask the admin to authorise you (your id: <code>%d</code>)." % uid
        elif not self.limiter.ok(uid):
            metrics.inc("rate_limited")
            if cb_id:
                self.bot.answer(cb_id, "Slow down ⏳")
            return False
        if deny:
            if cb_id:
                self.bot.answer(cb_id, re_strip(deny), True)
            elif time.time() - self._warned.get(uid, 0) > 30:
                self._warned[uid] = time.time()
                self.bot.send(chat, deny)
            return False
        return True

    def _user(self, frm: dict) -> dict:
        uid = frm["id"]
        owner = uid == config.OWNER_ID
        user, new = store.touch_user(uid, frm.get("first_name", "user"), frm.get("username"), owner)
        if uid in config.SUDO_IDS and user["role"] == "user":
            store.set_role(uid, "sudo")
            user["role"] = "sudo"
        if new:
            self.logs.new_user(uid, user["name"], frm.get("username"))
        return user

    # ------------------------------------------------------------ messages
    def _message(self, m: dict) -> None:
        chat = m["chat"]
        if chat.get("type") != "private" or not m.get("from"):
            return
        user = self._user(m["from"])
        if not self._gate(user, chat["id"], None):
            return
        with self._locks[user["id"] % 64]:
            u = {"id": user["id"], "chat": chat["id"], "name": user["name"], "role": user["role"]}
            text = (m.get("text") or "").strip()
            if text.startswith("/"):
                store.state_clear(u["id"])
                cmd, _, arg = text.partition(" ")
                self.command(cmd.split("@")[0].lower(), arg.strip(), u, m)
                return
            st = store.state_get(u["id"])
            if m.get("photo") or m.get("document"):
                self.flow.on_media(u, m, st) if st and st.get("t") in ("draft", "edit") else self.panels.on_media(u, m, st)
            elif text:
                self.on_text(u, text, st, m)
            elif st and st.get("t") == "chan":
                self.panels.on_text(u, "", st, m)  # forwarded channel post without text

    def on_text(self, u: dict, text: str, st: dict | None, m: dict) -> None:
        t = (st or {}).get("t")
        if t == "search":
            store.state_clear(u["id"])
            self.flow.search(u, text, st.get("kind"))
        elif t == "edit":
            self.flow.on_edit_text(u, text, st)
        elif t == "link":
            self.flow.on_link(u, text, st)
        elif t in ("set", "chan", "bcast"):
            self.panels.on_text(u, text, st, m)
        else:
            self.flow.search(u, text, None)

    # ------------------------------------------------------------ commands
    def command(self, cmd: str, arg: str, u: dict, m: dict) -> None:
        uid, chat = u["id"], u["chat"]
        if cmd == "/start":
            self.panels.start(u)
        elif cmd in ("/help", "/commands"):
            self.panels.help(u)
        elif cmd == "/settings":
            self.panels.settings(u, "user")
        elif cmd in ("/channels", "/addchannel"):
            self.panels.channels(u, add=cmd == "/addchannel")
        elif cmd in SEARCH_CMDS:
            kind = SEARCH_CMDS[cmd]
            if arg:
                self.flow.search(u, arg, kind)
            else:
                store.state_set(uid, {"t": "search", "kind": kind})
                self.say(chat, f"Send me the <b>{ {'tv': 'TV show', 'anime': 'anime', 'manga': 'manga / manhwa', 'movie': 'movie'}[kind] } title</b> to search:",
                         reply_markup=kb([btn("CANCEL", "x:s", style="danger")]))
        elif cmd == "/cancel":
            self.say(chat, "✅ Cancelled.")
        elif cmd == "/id":
            self.say(chat, f"Your id: <code>{uid}</code>\nChat id: <code>{chat}</code>")
        elif cmd in ("/stats", "/admin", "/broadcast", "/backup", "/addsudo", "/rmsudo", "/sudo", "/auth", "/unauth", "/ban", "/unban", "/apikey", "/apikeys", "/apirevoke"):
            if u["role"] not in ADMIN_ROLES:
                return self.say(chat, "⛔ Admins only.")
            self.panels.admin_command(cmd, arg, u, m)
        else:
            self.say(chat, "Unknown command. Send /help")

    # ------------------------------------------------------------ callbacks
    def _callback(self, cb: dict) -> None:
        msg = cb.get("message") or {}
        chat, mid = msg.get("chat", {}).get("id"), msg.get("message_id")
        if not chat:
            return self.bot.answer(cb["id"])
        user = self._user(cb["from"])
        if not self._gate(user, chat, cb["id"]):
            return
        data = cb.get("data", "")
        if data == "noop":
            return self.bot.answer(cb["id"])
        u = {"id": user["id"], "chat": chat, "name": user["name"], "role": user["role"], "mid": mid, "cb": cb["id"]}
        with self._locks[u["id"] % 64]:
            p = data.split(":")
            head = p[0]
            if head in ("r", "g", "p"):
                self.flow.callback(u, p)
            elif head in ("s", "a", "ch", "h"):
                self.panels.callback(u, p)
            elif head == "x":  # cancel a pending prompt / search list
                store.state_clear(u["id"])
                if len(p) > 1 and p[1] != "s":
                    store.draft_del(p[1])
                self.bot.answer(cb["id"], "Cancelled")
                self.bot.delete(chat, mid)
            else:
                self.bot.answer(cb["id"])


def re_strip(s: str) -> str:
    """Plain text for callback alerts (no HTML tags)."""
    import re
    return re.sub(r"<[^>]+>", "", s)
