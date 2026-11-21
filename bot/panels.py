"""Everything that is configured from inside the bot: /start, /help, user settings, admin panel, channels, admin commands."""
from __future__ import annotations

import logging
import re
import threading
import time

from . import config, metrics, settings, store, templates
from .caption import e
from .kb import btn, chunk, kb
from .tg import TgError

log = logging.getLogger("posterbot")
DEFAULT_WELCOME = (
    "<b>👋 Hey {name}!</b>\n\n"
    "I'm an <b>auto poster &amp; thumbnail maker</b> for your channel.\n"
    "<blockquote>Send me any movie, series, anime or manga title — or use /anime, /manga, /movie, /tvshows — "
    "and I'll build a ready-to-post poster with caption.</blockquote>\n"
    "• Pick a template, edit any detail, add your own thumbnail\n"
    "• Post to your channel in one tap\n"
    "• Set your brand, colours and caption in /settings"
)
HELP = (
    "<b>📘 Commands</b>\n"
    "/anime <code>title</code> – anime poster (AniList)\n"
    "/manga <code>title</code> – manga / manhwa poster (AniList)\n"
    "/movie <code>title</code> – movie poster (TMDB)\n"
    "/tvshows <code>title</code> – TV show poster (TMDB)\n"
    "Or just send a title.\n\n"
    "/settings – brand, colour, caption, default template…\n"
    "/channels – link the channels you post to\n"
    "/cancel – cancel what you're doing\n"
    "/id – your Telegram id"
)
CHANNEL_HELP = (
    "<b>📢 Posting to your channel</b>\n"
    "1. Add this bot to your channel as an <b>administrator</b> with permission to post messages.\n"
    "2. Send /addchannel, then forward any message from the channel here (or send its <code>@username</code>).\n"
    "3. Make a poster; when it's ready you'll get a <b>POST TO …</b> button."
)
ADMIN_HELP = (
    "\n\n<b>🛡 Admin</b>\n/admin – bot settings panel · /stats\n/broadcast <code>text</code> (or reply to a message)\n"
    "/auth /unauth <code>id</code> · /ban /unban <code>id</code>\nOwner: /addsudo /rmsudo <code>id</code> · /sudo · /backup\n"
    "API for other bots (owner): /apikey <code>name</code> [rpm] [daily] · /apikeys · /apirevoke <code>id</code>"
)


def _short(x, n=26):
    x = str(x)
    return x if len(x) <= n else x[: n - 1] + "…"


class Panels:
    def __init__(self, app):
        self.app = app
        self.bot = app.bot

    # ================================================================ start / help
    def start(self, u):
        text = (store.gget("welcome_text", "") or DEFAULT_WELCOME).replace("{name}", e(u["name"]))
        rows = [[btn("➕ ADD CHANNEL", "ch:add", style="success")], [btn("📘 CHANNEL HELP", "h:ch", style="primary")]]
        links = [btn(t, url=url, style="primary") for t, k in (("📣 UPDATES", "updates_url"), ("💬 SUPPORT", "support_url"))
                 if (url := store.gget(k, "")) and url.startswith("http")]
        if links:
            rows.append(links)
        rows.append([btn("⚙️ SETTINGS", "s:root", style="danger")])
        img = store.gget("welcome_image", "")
        if img:
            try:
                return self.bot.send_photo(u["chat"], img, caption=text[:1024], reply_markup=kb(*rows))
            except TgError:
                pass
        self.bot.send(u["chat"], text, reply_markup=kb(*rows))

    def help(self, u):
        self.bot.send(u["chat"], HELP + (ADMIN_HELP if u["role"] in ("owner", "sudo") else ""), reply_markup=kb([btn("📢 CHANNEL HELP", "h:ch", style="primary")]))

    # ================================================================ generic settings engine
    def _defs(self, scope):
        return settings.USER if scope == "user" else settings.ADMIN

    def _get(self, scope, uid, d):
        return store.settings(uid).get(d["key"], d["default"]) if scope == "user" else store.gget(d["key"], d["default"])

    def _choices(self, d):
        if d["key"] == "template":
            return ["auto"] + [k for k, t in templates.TEMPLATES.items() if not t.hidden]
        return d["choices"]

    def _label(self, d, v):
        if d["key"] == "template" and v in templates.TEMPLATES:
            return templates.TEMPLATES[v].label
        return str(v).title() if d["kind"] == "choice" else str(v)

    def _show_val(self, d, v):
        if d["kind"] == "toggle":
            return "✅ ON" if v else "❌ OFF"
        if d["kind"] == "choice":
            return self._label(d, v)
        return _short(v, 16) if v not in ("", None) else "—"

    def settings(self, u, scope, mid=None, group=None):
        defs = self._defs(scope)
        if scope == "admin" and u["role"] not in ("owner", "sudo"):
            return
        pre = "s" if scope == "user" else "a"
        items = []
        for i, d in enumerate(defs):
            if d.get("group") != group:
                continue
            v = self._get(scope, u["id"], d)
            lbl = f"{d['label']}" if d["kind"] == "toggle" else f"{d['label']}: {self._show_val(d, v)}"
            if d["kind"] == "toggle":
                lbl = f"{'✅' if v else '❌'} {d['label']}"
            items.append(btn(_short(lbl, 30), f"{pre}:o:{i}", style="primary"))
        rows = chunk(items, 2)
        if scope == "user" and group:
            rows.append([btn("↩ BACK", "s:root", style="danger")])
            title, sub = "🏷 <b>Brands &amp; taglines</b>", "Each type gets its own brand and tagline. Empty = default."
        elif scope == "user":
            rows.append([btn("🏷 BRANDS & TAGLINES", "s:g:brands", style="primary"), btn("📢 CHANNELS", "ch:root", style="primary")])
            title, sub = "⚙️ <b>Settings</b>", "Tap an option to change it. Changes apply to your next poster."
        else:
            rows.append([btn("📊 STATS", "a:stats", style="primary"), btn("💾 BACKUP NOW", "a:backup", style="primary")])
            title, sub = "🛡 <b>Bot settings (admin)</b>", "Global settings. They apply to every user and take effect immediately."
        if not group:
            rows.append([btn("✖ CLOSE", "s:close", style="danger")])
        text = f"{title}\n{sub}"
        if mid:
            try:
                return self.bot.edit(u["chat"], mid, text, reply_markup=kb(*rows))
            except TgError:  # e.g. the /start message is a photo and can't be edited as text
                pass
        self.bot.send(u["chat"], text, reply_markup=kb(*rows))

    def _save(self, scope, uid, d, v):
        if scope == "user":
            store.uset(uid, d["key"], v)
        else:
            store.gset(d["key"], v)

    def callback(self, u, p):
        bot, cb, head = self.bot, u["cb"], p[0]
        if head == "h":
            bot.answer(cb)
            if p[1] == "ch":
                bot.send(u["chat"], CHANNEL_HELP)
            return
        if head == "ch":
            return self._channel_cb(u, p)
        scope = "user" if head == "s" else "admin"
        if scope == "admin" and u["role"] not in ("owner", "sudo"):
            return bot.answer(cb, "Admins only", True)
        act = p[1]
        if act == "close":
            bot.answer(cb)
            return bot.delete(u["chat"], u["mid"])
        if act == "root":
            bot.answer(cb)
            return self.settings(u, scope, u["mid"])
        if act == "g":
            bot.answer(cb)
            return self.settings(u, scope, u["mid"], group=p[2])
        if act == "stats":
            bot.answer(cb)
            return bot.send(u["chat"], self.stats_text())
        if act == "backup":
            bot.answer(cb, "Backing up…")
            threading.Thread(target=self.app.archive.backup_now, daemon=True).start()
            return
        defs = self._defs(scope)
        i = int(p[2])
        d = defs[i]
        if act == "o":
            return self._open(u, scope, i, d)
        if act == "v":  # choice picked
            v = self._choices(d)[int(p[3])]
            self._save(scope, u["id"], d, v)
            bot.answer(cb, f"{d['label']}: {self._label(d, v)}")
            return self.settings(u, scope, u["mid"], group=d.get("group"))
        if act == "r":  # reset to default
            self._save(scope, u["id"], d, None)
            bot.answer(cb, "Reset to default")
            store.state_clear(u["id"])
            return self.settings(u, scope, u["mid"], group=d.get("group"))

    def _open(self, u, scope, i, d):
        bot, cb, pre = self.bot, u["cb"], "s" if scope == "user" else "a"
        cur = self._get(scope, u["id"], d)
        back = f"{pre}:g:{d['group']}" if d.get("group") else f"{pre}:root"
        if d["kind"] == "toggle":
            self._save(scope, u["id"], d, not cur)
            bot.answer(cb, f"{d['label']}: {'ON' if not cur else 'OFF'}")
            return self.settings(u, scope, u["mid"], group=d.get("group"))
        if d["kind"] == "choice":
            bot.answer(cb)
            ch = self._choices(d)
            btns = [btn(("● " if c == cur else "") + _short(self._label(d, c), 24), f"{pre}:v:{i}:{j}", style="success" if c == cur else "primary")
                    for j, c in enumerate(ch)]
            rows = chunk(btns, 2) + [[btn("↩ BACK", back, style="danger")]]
            return bot.edit(u["chat"], u["mid"], f"<b>{e(d['label'])}</b>\n{d.get('help', '')}", reply_markup=kb(*rows))
        # text / number: wait for the next message
        bot.answer(cb)
        store.state_set(u["id"], {"t": "set", "scope": scope, "i": i, "mid": u["mid"]}, ttl=900)
        extra = "\nSend <code>-</code> to clear it." if d["kind"] == "text" else ""
        bot.edit(u["chat"], u["mid"], f"<b>{e(d['label'])}</b>\n{d.get('help', '')}\n\nCurrent: <code>{e(cur if cur != '' else '—')}</code>\n"
                 f"Send the new value now.{extra}", reply_markup=kb([btn("↺ RESET", f"{pre}:r:{i}", style="primary"), btn("↩ BACK", back, style="danger")]))

    def on_text(self, u, text, st, m):
        t = st["t"]
        if t == "chan":
            return self._channel_input(u, text, st, m)
        if t == "bcast":
            return
        scope, d = st["scope"], self._defs(st["scope"])[st["i"]]
        if scope == "admin" and u["role"] not in ("owner", "sudo"):
            return
        if d["kind"] == "number":
            try:
                v = int(text.strip())
                assert 0 <= v <= d.get("max", 10**9)
            except Exception:
                return self.bot.send(u["chat"], "❌ Send a whole number (0 or more).")
        else:
            v = "" if text.strip() == "-" else text.strip()[: d.get("max", 200)]
        if scope == "admin" and d["key"] in ("log_channel", "storage_channel") and v:
            err = self._test_channel(v, d["key"])
            if err:
                return self.bot.send(u["chat"], f"❌ {err}")
            v = str(v)
        if scope == "admin" and d["key"] in ("support_url", "updates_url") and v and not v.startswith("http"):
            return self.bot.send(u["chat"], "❌ The link must start with <code>https://</code>.")
        self._save(scope, u["id"], d, v)
        store.state_clear(u["id"])
        self.bot.send(u["chat"], f"✅ <b>{e(d['label'])}</b> saved.")
        self.settings(u, scope, group=d.get("group"))

    def on_media(self, u, m, st):
        """A photo sent while the admin is setting the welcome image."""
        if st and st.get("t") == "set" and u["role"] in ("owner", "sudo") and st["scope"] == "admin" \
                and settings.ADMIN[st["i"]]["key"] == "welcome_image" and m.get("photo"):
            store.gset("welcome_image", m["photo"][-1]["file_id"])
            store.state_clear(u["id"])
            self.bot.send(u["chat"], "✅ Welcome image saved.")
            return self.settings(u, "admin")
        self.bot.send(u["chat"], "Send a title to search (e.g. <code>/anime naruto</code>). To use your own image, search a title first, then send the image while its controls are open.")

    def _test_channel(self, ref, key):
        try:
            cid = int(ref)
            self.bot.send(cid, "✅ Connected." if key == "log_channel" else "✅ Storage channel connected.")
        except (ValueError, TgError) as ex:
            return f"I can't post there ({str(ex)[:120]}). Use the numeric id (<code>-100…</code>) and make the bot an admin."
        return None

    # ================================================================ channels
    def channels(self, u, add=False, mid=None):
        chans = store.channels(u["id"])
        if add:
            return self._ask_channel(u, mid)
        text = "<b>📢 Your channels</b>\n" + ("\n".join(f"{i + 1}. {e(c['title'])} <code>{c['chat_id']}</code>" for i, c in enumerate(chans)) if chans else "<i>None yet.</i>")
        rows = [[btn(f"🗑 {_short(c['title'], 22)}", f"ch:rm:{c['chat_id']}", style="danger")] for c in chans]
        rows.append([btn("➕ ADD CHANNEL", "ch:add", style="success")])
        rows.append([btn("↩ SETTINGS", "s:root", style="primary")])
        try:
            if mid:
                return self.bot.edit(u["chat"], mid, text, reply_markup=kb(*rows))
        except TgError:
            pass
        self.bot.send(u["chat"], text, reply_markup=kb(*rows))

    def _ask_channel(self, u, mid=None):
        store.state_set(u["id"], {"t": "chan"}, ttl=900)
        text = (CHANNEL_HELP + "\n\n<b>Now forward any message from your channel here</b>, or send its <code>@username</code> / numeric id.")
        rows = kb([btn("CANCEL", "x:s", style="danger")])
        self.bot.send(u["chat"], text, reply_markup=rows)

    def _channel_cb(self, u, p):
        self.bot.answer(u["cb"])
        if p[1] == "add":
            return self._ask_channel(u)
        if p[1] == "rm":
            store.remove_channel(u["id"], int(p[2]))
        self.channels(u, mid=u["mid"])

    def _channel_input(self, u, text, st, m):
        ref = None
        fo = m.get("forward_origin") or {}
        if fo.get("type") == "channel":
            ref = fo["chat"]["id"]
        elif m.get("forward_from_chat"):
            ref = m["forward_from_chat"]["id"]
        elif re.fullmatch(r"@[A-Za-z0-9_]{4,}|-100\d+", text.strip()):
            ref = text.strip()
        if ref is None:
            return self.bot.send(u["chat"], "❌ Forward a message from the channel, or send its <code>@username</code>.")
        try:
            info = self.bot.call("getChat", chat_id=ref)
            me = self.bot.call("getChatMember", chat_id=info["id"], user_id=self.bot.me["id"])
            you = self.bot.call("getChatMember", chat_id=info["id"], user_id=u["id"])
        except TgError as ex:
            return self.bot.send(u["chat"], f"❌ I can't access that channel ({e(str(ex)[:100])}). Add me as an admin first.")
        if me.get("status") != "administrator" or (info.get("type") == "channel" and not me.get("can_post_messages")):
            return self.bot.send(u["chat"], "❌ I'm not an admin there with permission to post messages. Fix that and try again.")
        if you.get("status") not in ("creator", "administrator"):
            return self.bot.send(u["chat"], "❌ You must be an admin of that channel to link it.")
        store.add_channel(u["id"], info["id"], info.get("title") or str(info["id"]))
        store.state_clear(u["id"])
        self.bot.send(u["chat"], f"✅ Linked <b>{e(info.get('title', ''))}</b>.")
        self.channels(u)

    # ================================================================ admin
    def stats_text(self) -> str:
        s = store.stats()
        up = int(time.time() - metrics.START)
        return (f"<b>📊 Stats</b>\n👥 Users: {s['users']} (active today {s['active_today']}, banned {s['banned']})\n"
                f"🖼 Posters: {s['posters']} (today {s['posters_today']})\n⚡ Cached: {s['cached']} · 📝 Open drafts: {s['drafts']}\n"
                f"📢 Linked channels: {s['channels']}\n⏱ Uptime: {up // 3600}h {up % 3600 // 60}m")

    def admin_command(self, cmd, arg, u, m):
        chat, bot = u["chat"], self.bot
        owner = u["role"] == "owner"
        if cmd == "/stats":
            return bot.send(chat, self.stats_text())
        if cmd == "/admin":
            return self.settings(u, "admin")
        if cmd == "/backup":
            if not owner:
                return bot.send(chat, "⛔ Owner only.")
            threading.Thread(target=self.app.archive.backup_now, daemon=True).start()
            return bot.send(chat, "💾 Backup started (needs a storage channel).")
        if cmd in ("/apikey", "/apikeys", "/apirevoke"):
            return self._api_command(cmd, arg, u)
        if cmd == "/sudo":
            return bot.send(chat, "<b>Admins</b>\n" + "\n".join(f"<code>{i}</code> {r}" for r in ("owner", "sudo") for i in store.user_ids(r)))
        if cmd == "/broadcast":
            if not owner and u["role"] != "sudo":
                return
            reply = m.get("reply_to_message")
            if not arg and not reply:
                return bot.send(chat, "Usage: /broadcast <code>text</code> or reply to a message with /broadcast")
            ids = store.user_ids()
            bot.send(chat, f"📣 Broadcasting to {len(ids)} users…")
            threading.Thread(target=self._broadcast, args=(chat, ids, arg, reply), daemon=True).start()
            return
        try:
            target = int(arg.split()[0])
        except (ValueError, IndexError):
            return bot.send(chat, f"Usage: {cmd} <code>user_id</code>")
        t = store.get_user(target)
        if not t:
            return bot.send(chat, "That user hasn't started the bot yet.")
        if cmd in ("/addsudo", "/rmsudo") and not owner:
            return bot.send(chat, "⛔ Owner only.")
        if t["role"] in ("owner", "sudo") and cmd not in ("/rmsudo",) and not owner:
            return bot.send(chat, "⛔ You can't change an admin.")
        if cmd == "/addsudo":
            store.set_role(target, "sudo")
        elif cmd == "/rmsudo":
            if t["role"] == "owner":
                return bot.send(chat, "The owner can't be demoted.")
            store.set_role(target, "user")
        elif cmd == "/auth":
            store.set_role(target, "auth") if t["role"] == "user" else None
        elif cmd == "/unauth":
            store.set_role(target, "user") if t["role"] == "auth" else None
        elif cmd == "/ban":
            if t["role"] == "owner":
                return bot.send(chat, "The owner can't be banned.")
            store.set_banned(target, True)
        elif cmd == "/unban":
            store.set_banned(target, False)
        bot.send(chat, f"✅ Done: {cmd} <code>{target}</code>")

    def _api_command(self, cmd, arg, u):
        chat, bot = u["chat"], self.bot
        base = config.PUBLIC_URL or "https://YOUR-APP.onrender.com"
        if cmd == "/apikeys":
            rows = store.api_keys()
            if not rows:
                return bot.send(chat, "No API keys yet. Create one with /apikey <code>name</code>.")
            lines = [f"{'🟢' if k['active'] else '⚫'} <code>{k['id']}</code> <b>{e(k['name'])}</b> · <code>{k['prefix']}…</code> · "
                     f"{k['rpm']}/min · {k['daily'] or '∞'}/day · {k['calls']} calls" for k in rows]
            return bot.send(chat, "<b>🔑 API keys</b>\n" + "\n".join(lines))
        if u["role"] != "owner":
            return bot.send(chat, "⛔ Owner only.")
        if cmd == "/apirevoke":
            try:
                ok = store.api_key_revoke(int(arg.split()[0]))
            except (ValueError, IndexError):
                return bot.send(chat, "Usage: /apirevoke <code>id</code> (see /apikeys)")
            return bot.send(chat, "✅ Key revoked." if ok else "No active key with that id.")
        parts = arg.split()
        if not parts:
            return bot.send(chat, "Usage: /apikey <code>name</code> [requests/min] [requests/day]\nExample: <code>/apikey mychannelbot 30 2000</code>")
        if chat != u["id"]:
            return bot.send(chat, "🔒 Create keys in a private chat with the bot, not in a group.")
        nums = [int(x) for x in parts[1:3] if x.isdigit()]
        rpm = nums[0] if nums else int(store.gget("api_rpm", 30) or 30)
        daily = nums[1] if len(nums) > 1 else int(store.gget("api_daily", 2000) or 0)
        kid, token = store.api_key_create(parts[0], u["id"], rpm, daily)
        bot.send(chat, f"🔑 <b>API key created</b> (id <code>{kid}</code>, {rpm}/min, {daily or '∞'}/day)\n"
                       f"<code>{token}</code>\n<i>Shown only once - store it safely.</i>\n\n"
                       f"Base URL: <code>{base}/api/v1</code>\nHeader: <code>Authorization: Bearer {token[:9]}…</code>\n"
                       "Docs: <code>/api/v1/openapi.json</code>")

    def _broadcast(self, chat, ids, text, reply):
        ok = fail = 0
        for uid in ids:
            try:
                if reply:
                    self.bot.call("copyMessage", chat_id=uid, from_chat_id=reply["chat"]["id"], message_id=reply["message_id"])
                else:
                    self.bot.send(uid, text)
                ok += 1
            except TgError:
                fail += 1
            time.sleep(0.05)  # ~20 msg/s, under Telegram's broadcast limit
        self.bot.send(chat, f"📣 Broadcast finished: {ok} delivered, {fail} failed.")
