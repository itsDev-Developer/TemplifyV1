"""Search -> pick -> poster -> controls -> button link -> post, modelled on the reference bot's flow."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from . import variants, caption, config, images, metrics, store, templates
from .context import COLORS, Ctx
from .kb import btn, kb, paginate
from .models import Media
from .providers import fanart
from .settings import QUALITY, brand_for, tagline_for
from .tg import TgError

log = logging.getLogger("posterbot")
PAGE = 6
KIND_NAME = {"anime": "ANIME", "manga": "MANGA", "movie": "MOVIE", "tv": "TV SHOW"}
SRC_NAME = {"tmdb": "TMDB", "anilist": "ANILIST"}
_render_gate = threading.Semaphore(config.RENDER_CONCURRENCY)
_search_pool = ThreadPoolExecutor(8, thread_name_prefix="search")
URL_RE = re.compile(r"^https?://[^\s]{4,}$", re.I)
EDIT_FIELDS = [("title", "TITLE"), ("rating", "RATING"), ("genres", "GENRES"), ("synopsis", "SYNOPSIS"),
               ("status", "STATUS"), ("episodes", "EPISODES")]


class LRU:
    def __init__(self, n):
        self.n, self.d, self.l = n, OrderedDict(), threading.Lock()

    def get(self, k):
        with self.l:
            if k in self.d:
                self.d.move_to_end(k)
                return self.d[k]

    def put(self, k, v):
        with self.l:
            self.d[k] = v
            while len(self.d) > self.n:
                self.d.popitem(last=False)


class Flow:
    def __init__(self, app):
        self.app = app
        self.bot = app.bot
        self.media_cache = LRU(300)   # (source,kind,id) -> (ts, media dict)
        self.jpg_cache = LRU(24)      # render key -> jpeg bytes (for archiving / re-upload)

    # ================================================================ search
    def search(self, u: dict, q: str, kind: str | None) -> None:
        a, chat = self.app, u["chat"]
        q = " ".join(q.split())[:100]
        if not q:
            return
        jobs = []
        if kind in (None, "anime", "manga"):
            jobs.append(("AniList", lambda: a.anilist.search(q, kind if kind in ("anime", "manga") else None)))
        if kind in (None, "movie", "tv"):
            if a.tmdb:
                jobs.append(("TMDB", lambda: a.tmdb.search(q, kind if kind in ("movie", "tv") else None)))
            elif kind in ("movie", "tv"):
                return self.bot.send(chat, "⚠️ Movie/TV search isn't configured yet (the admin needs to set <code>TMDB_API_KEY</code>).")
        wait = self.bot.send(chat, f"🔎 <b>Search results for</b> '{caption.e(q)}'\n<i>Loading sources (0/{len(jobs)})…</i>")
        futs = [(name, _search_pool.submit(fn)) for name, fn in jobs]
        lists, failed = [], 0
        for name, f in futs:
            try:
                lists.append(f.result(timeout=25))
            except Exception as ex:
                failed += 1
                log.warning("search %s failed: %s", name, ex)
        hits, seen = [], set()
        for i in range(max((len(x) for x in lists), default=0)):  # interleave sources
            for lst in lists:
                if i < len(lst):
                    h = lst[i]
                    if (h.source, h.kind, h.id) not in seen:
                        seen.add((h.source, h.kind, h.id))
                        hits.append([h.source, h.kind, h.id, h.title, h.year])
        if not hits:
            msg = ("⚠️ The search services aren't responding. Please try again in a moment." if failed
                   else f"😕 Nothing found for <b>{caption.e(q)}</b>. Try another spelling.")
            return self.bot.edit(chat, wait["message_id"], msg)
        did = store.draft_new(u["id"], {"t": "search", "q": q, "hits": hits[:18]})
        self._results(u, did, 0, wait["message_id"])

    def _results(self, u, did, page, mid):
        d = store.draft_get(did, u["id"])
        hits, pages = d["hits"], max(1, math.ceil(len(d["hits"]) / PAGE))
        page = max(0, min(page, pages - 1))
        rows = []
        for i in range(page * PAGE, min(len(hits), (page + 1) * PAGE)):
            s, k, _, title, year = hits[i]
            label = f"{title.upper()}{f' ({year})' if year else ''} · {SRC_NAME.get(s, s.upper())}"
            rows.append([btn(label[:58], f"r:{did}:{i}", style="primary")])
        rows.append(paginate(f"g:{did}", page, pages))
        rows.append([btn("CANCEL", f"x:{did}", style="danger")])
        self.bot.edit(u["chat"], mid, f"🔎 <b>Search results for</b> '{caption.e(d['q'])}'\nSelect the correct title from the list below:",
                      reply_markup=kb(*rows))

    # ================================================================ callbacks
    def callback(self, u: dict, p: list) -> None:
        bot, cb = self.bot, u["cb"]
        did = p[1] if len(p) > 1 else ""
        d = store.draft_get(did, u["id"])
        if d is None:
            return bot.answer(cb, "⌛ This session expired. Please search again.", True)
        if p[0] == "g":
            bot.answer(cb)
            return self._results(u, did, int(p[2]), u["mid"])
        if p[0] == "r":
            return self.pick(u, did, d, int(p[2]))
        act = p[2] if len(p) > 2 else ""
        if d.get("t") != "poster":
            return bot.answer(cb)
        {"t": self._a_template, "e": self._a_edit, "f": self._a_field, "b": self._a_banner, "k": self._a_skip,
         "l": self._a_skip_link, "v": self._a_art, "s": self._a_art_step, "c": self._a_post, "a": self._a_again, "x": self._a_cancel, "bk": self._a_back,
         }.get(act, lambda *_: bot.answer(cb))(u, did, d, p[3:])

    # ================================================================ pick -> first poster
    def media_for(self, uid: int, source: str, kind: str, id_: int) -> Media:
        key = (source, kind, id_)
        hit = self.media_cache.get(key)
        if hit and time.time() - hit[0] < 1800:
            m = Media(**json.loads(hit[1]))
        else:
            m = self.app.anilist.details(id_) if source == "anilist" else self.app.tmdb.details(kind, id_)
            self.media_cache.put(key, (time.time(), json.dumps(asdict(m))))
        if (config.FANART_API_KEY or config.TMDB_API_KEY) and store.settings(uid).get("fanart", True):
            m = fanart.enhance(m, config.FANART_API_KEY, self.app.tmdb)
        return m

    def pick(self, u, did, d, idx):
        bot, chat, uid = self.bot, u["chat"], u["id"]
        if idx >= len(d["hits"]):
            return bot.answer(u["cb"])
        limit = int(store.gget("daily_limit", 0) or 0)
        if limit and u["role"] not in ("owner", "sudo") and store.usage_today(uid) >= limit:
            return bot.answer(u["cb"], f"Daily limit reached ({limit} posters). Try again tomorrow.", True)
        source, kind, id_, title, _ = d["hits"][idx]
        bot.answer(u["cb"], "Generating…")
        bot.edit(chat, u["mid"], f"⚙️ <b>Generating {KIND_NAME.get(kind, 'MEDIA').lower()} poster…</b>\n<i>{caption.e(title)}</i>")
        try:
            m = self.media_for(uid, source, kind, id_)
        except Exception as ex:
            log.warning("details failed %s:%s: %s", source, id_, ex)
            self.app.logs.error("details", ex)
            return bot.edit(chat, u["mid"], "⚠️ Couldn't load that title right now. Please try another result.")
        s = store.settings(uid)
        tpls = self.tpl_keys(m, s)
        pd = {"t": "poster", "m": asdict(m), "tpls": tpls, "ti": tpls.index(self.start_tpl(m, s, tpls)),
              "banner": False, "char": "", "sel": {}, "url": "", "pm": 0, "cm": u["mid"], "fid": "", "thumb": False}
        pid = store.draft_new(uid, pd)
        store.draft_del(did)
        store.bump_usage(uid)
        try:
            self.show(u, pid, pd, first=True)
        except Exception as ex:
            log.exception("render failed")
            self.app.logs.error("render", ex)
            return bot.edit(chat, u["mid"], "⚠️ Couldn't generate that poster. Please try another template or title.")
        store.state_set(uid, {"t": "draft", "d": pid}, ttl=7200)
        text, markup = self.controls(pid, pd)
        bot.edit(chat, u["mid"], text, reply_markup=markup)

    # ================================================================ templates / rendering
    @staticmethod
    def tpl_keys(m: Media, s: dict) -> list[str]:
        a = m.art or {}
        # fanart templates need a logo or a character cutout to shine; plain backgrounds alone don't justify them
        use_fa = bool(a.get("logo") or a.get("character") or a.get("clearart")) and s.get("fanart", True)
        return [k for k, t in templates.TEMPLATES.items() if not t.hidden and (use_fa or t.group != "Fanart")]

    @staticmethod
    def start_tpl(m: Media, s: dict, tpls: list[str]) -> str:
        want = s.get("template", "auto")
        if want in tpls:
            return want
        for k in (("fa_hero",) if "fa_hero" in tpls else ()) + ({"manga": ("manga_cover",), "anime": ("card",)}.get(m.kind, ()) + ("split",)):
            if k in tpls:
                return k
        return tpls[0]

    def render(self, uid: int, pd: dict) -> tuple[bytes, str]:
        s = store.settings(uid)
        key_tpl = "banner" if pd["banner"] else pd["tpls"][pd["ti"]]
        tpl = templates.TEMPLATES[key_tpl]
        color = s.get("color", "auto")
        accent = COLORS.get(color, tpl.accent)
        kind = pd["m"].get("kind", "movie")
        brand, tagline = brand_for(s, kind), tagline_for(s, kind)
        scale = QUALITY.get(s.get("quality", "1080p"), 1.5)
        sel = pd.get("sel") or {}
        rk = hashlib.sha1(json.dumps([pd["m"], key_tpl, accent, brand, tagline, scale, pd["char"], sel], sort_keys=True).encode()).hexdigest()
        jpg = self.jpg_cache.get(rk)
        if jpg is None:
            t0 = time.time()
            with _render_gate:
                media, cutout = variants.apply(Media(**pd["m"]), sel, pd["char"])
                ctx = Ctx(media, brand=brand, accent=accent, tagline=tagline, cutout=cutout)
                jpg = templates.render(key_tpl, ctx, scale).jpeg(92)
            metrics.observe("render_seconds", time.time() - t0)
            metrics.inc("renders")
            self.jpg_cache.put(rk, jpg)
        return jpg, rk

    def show(self, u, pid, pd, first=False) -> None:
        """Render and send (first=True) or swap the picture + caption of the poster message in place."""
        uid, chat = u["id"], u["chat"]
        jpg, rk = self.render(uid, pd)
        s = store.settings(uid)
        cap = caption.build(Media(**pd["m"]), s)
        markup = kb([btn(s.get("button_text") or "📥 Download", url=pd["url"])]) if pd["url"] else None
        photo = store.cache_get(rk) or jpg
        res = None
        if not first and pd["pm"]:
            for src in ([photo, jpg] if isinstance(photo, str) else [jpg]):  # stale cached file_id -> fall back to the bytes
                try:
                    res = self.bot.edit_media(chat, pd["pm"], src, cap, reply_markup=markup)
                    break
                except TgError as ex:
                    if "not modified" in str(ex):
                        return
                    log.info("edit_media failed (%s)", ex)
        if res is None:
            try:
                res = self.bot.send_photo(chat, photo, caption=cap or None, reply_markup=markup)
            except TgError:
                res = self.bot.send_photo(chat, jpg, caption=cap or None, reply_markup=markup)
        if isinstance(res, dict) and res.get("photo"):
            pd["pm"] = res.get("message_id", pd["pm"])
            pd["fid"] = res["photo"][-1]["file_id"]
            store.cache_put(rk, pd["fid"])
        store.draft_save(pid, pd)

    # ================================================================ controls
    def controls(self, pid, pd) -> tuple[str, dict]:
        m, n = Media(**pd["m"]), len(pd["tpls"])
        key = pd["tpls"][pd["ti"]]
        label = "Clean Banner" if pd["banner"] else templates.TEMPLATES[key].label
        text = (f"🎛 <b>{KIND_NAME.get(m.kind, 'MEDIA')} POSTER CONTROLS</b>\n"
                "<blockquote>Send me a custom thumbnail image, edit details, or click skip to continue.</blockquote>\n"
                f"<i>Template {pd['ti'] + 1}/{n}: {caption.e(label)}</i>")
        rows = [
            [btn("◀ PREV", f"p:{pid}:t:{(pd['ti'] - 1) % n}", style="primary"), btn(f"{pd['ti'] + 1:02d}/{n:02d}", "noop"),
             btn("NEXT ▶", f"p:{pid}:t:{(pd['ti'] + 1) % n}", style="primary")],
            [btn("✏️ EDIT DATA", f"p:{pid}:e", style="primary")] +
            ([btn("🎨 ART", f"p:{pid}:v", style="primary")] if variants.roles_available(m, pd["char"]) else []),
            [btn("🎨 POSTER VIEW" if pd["banner"] else "🖼 GEN BANNER", f"p:{pid}:b", style="primary"),
             btn("✅ CONTINUE" if pd["thumb"] else "⏭ SKIP THUMB", f"p:{pid}:k", style="success" if pd["thumb"] else "primary")],
            [btn("CANCEL", f"p:{pid}:x", style="danger")],
        ]
        return text, kb(*rows)

    def _refresh_controls(self, u, pid, pd):
        text, markup = self.controls(pid, pd)
        self.bot.edit(u["chat"], pd["cm"], text, reply_markup=markup)

    def _a_template(self, u, pid, d, a):
        self.bot.answer(u["cb"])
        d["ti"], d["banner"] = int(a[0]) % len(d["tpls"]), False
        self.show(u, pid, d)
        self._refresh_controls(u, pid, d)

    # ---------------------------------------------------------------- art variants
    def art_panel(self, u, pid, pd):
        m, sel, ch = Media(**pd["m"]), pd.get("sel") or {}, pd["char"]
        text = ("🎨 <b>ARTWORK</b>\n<blockquote>Step through the available posters, backgrounds, logos and character art. "
                "The poster updates instantly.</blockquote>")
        rows = []
        for r in variants.roles_available(m, ch):
            name = dict(variants.ROLES)[r]
            rows.append([btn("◀", f"p:{pid}:s:{r}:-1", style="primary"), btn(f"{name}: {variants.label(m, sel, r, ch)}", "noop"),
                         btn("▶", f"p:{pid}:s:{r}:1", style="primary")])
        rows.append([btn("♻️ RESET", f"p:{pid}:s:x:0"), btn("⬅ BACK", f"p:{pid}:bk")])
        self.bot.edit(u["chat"], pd["cm"], text, reply_markup=kb(*rows))

    def _a_art(self, u, pid, d, a):
        self.bot.answer(u["cb"])
        self.art_panel(u, pid, d)

    def _a_art_step(self, u, pid, d, a):
        role, delta = a[0], int(a[1])
        if role == "x":
            d["sel"] = {}
        elif role in dict(variants.ROLES):
            d["sel"] = variants.step(Media(**d["m"]), d.get("sel") or {}, role, delta, d["char"])
        else:
            return self.bot.answer(u["cb"])
        self.bot.answer(u["cb"])
        self.show(u, pid, d)
        self.art_panel(u, pid, d)

    def _a_banner(self, u, pid, d, a):
        d["banner"] = not d["banner"]
        self.bot.answer(u["cb"], "Switched to Landscape Backdrop Banner!" if d["banner"] else "Back to the template poster")
        self.show(u, pid, d)
        self._refresh_controls(u, pid, d)

    def _a_back(self, u, pid, d, a):
        self.bot.answer(u["cb"])
        store.state_set(u["id"], {"t": "draft", "d": pid}, ttl=7200)
        self._refresh_controls(u, pid, d)

    def _a_cancel(self, u, pid, d, a):
        self.bot.answer(u["cb"], "Cancelled")
        for mid in (d["pm"], d["cm"]):
            if mid:
                self.bot.delete(u["chat"], mid)
        store.draft_del(pid)
        store.state_clear(u["id"])

    # ---------------------------------------------------------------- edit data
    def edit_panel(self, u, pid, pd, note: str = ""):
        m = Media(**pd["m"])
        short = lambda x, n=70: (x if len(x) <= n else x[: n - 1] + "…")
        text = (f"📝 <b>EDIT {KIND_NAME.get(m.kind, 'MEDIA')} POST DETAILS</b>\n"
                "<blockquote>Select a field, then send the new value in chat. Both poster thumbnail and caption will be auto-updated!</blockquote>\n"
                f"▸ Title: {caption.e(short(m.title))}\n▸ Rating: {caption.e(m.score or '—')}\n"
                f"▸ Genres: {caption.e(', '.join(m.genres) or '—')}\n"
                f"▸ Status / Ep: {caption.e(m.status or '—')} / {caption.e(m.episodes or '—')}\n"
                f"▸ Synopsis: {caption.e(short(m.synopsis or '—', 60))}" + (f"\n\n{note}" if note else ""))
        rows = [[btn(lbl, f"p:{pid}:f:{k}", style="primary") for k, lbl in EDIT_FIELDS[i:i + 2]] for i in range(0, len(EDIT_FIELDS), 2)]
        rows.append([btn("🖼 CUSTOM POSTER", f"p:{pid}:f:poster", style="primary"), btn("🧍 CUSTOM CHAR (PNG)", f"p:{pid}:f:char", style="primary")])
        rows.append([btn("↩ BACK", f"p:{pid}:bk", style="danger")])
        self.bot.edit(u["chat"], pd["cm"], text, reply_markup=kb(*rows))

    def _a_edit(self, u, pid, d, a):
        self.bot.answer(u["cb"])
        store.state_set(u["id"], {"t": "draft", "d": pid}, ttl=7200)
        self.edit_panel(u, pid, d)

    def _a_field(self, u, pid, d, a):
        f = a[0]
        prompts = {"title": "the new <b>title</b>", "rating": "the new <b>rating</b> (0-10, e.g. <code>8.1</code>)",
                   "genres": "the <b>genres</b> separated by commas", "synopsis": "the new <b>synopsis</b>",
                   "status": "the new <b>status</b> (e.g. <code>Completed</code>)", "episodes": "the number of <b>episodes</b> / chapters",
                   "poster": "a <b>photo</b> to use as the custom poster / thumbnail",
                   "char": "the character <b>PNG as a file</b> (send as document so transparency is kept)"}
        if f not in prompts:
            return self.bot.answer(u["cb"])
        self.bot.answer(u["cb"])
        store.state_set(u["id"], {"t": "edit", "d": pid, "f": f}, ttl=1800)
        self.bot.edit(u["chat"], d["cm"], f"✏️ Send me {prompts[f]}.", reply_markup=kb([btn("↩ BACK", f"p:{pid}:e", style="danger")]))

    def on_edit_text(self, u, text, st):
        pid = st["d"]
        d = store.draft_get(pid, u["id"])
        if d is None:
            store.state_clear(u["id"])
            return self.bot.send(u["chat"], "⌛ This session expired. Please search again.")
        f, m = st["f"], d["m"]
        if f in ("poster", "char"):
            return self.bot.send(u["chat"], "Please send an image, not text.")
        if f == "title":
            m["title"] = text[:100]
        elif f == "rating":
            try:
                v = float(text.replace("%", "").replace(",", ".").strip())
                v = v / 10 if v > 10 else v
                assert 0 <= v <= 10
                m["score"] = f"{v:.1f}"
            except Exception:
                return self.bot.send(u["chat"], "❌ Send a number between 0 and 10.")
        elif f == "genres":
            m["genres"] = [g.strip() for g in re.split(r"[,/|]+", text) if g.strip()][:6]
        elif f == "synopsis":
            m["synopsis"] = text[:900]
        elif f == "status":
            m["status"] = text[:30]
        elif f == "episodes":
            m["episodes"] = text[:12]
        self._after_edit(u, pid, d, "✅ Updated.")

    def _after_edit(self, u, pid, d, note):
        store.state_set(u["id"], {"t": "draft", "d": pid}, ttl=7200)
        self.show(u, pid, d)
        self.edit_panel(u, pid, d, note)

    # ---------------------------------------------------------------- photos / files from the user
    def on_media(self, u, m, st):
        chat, uid = u["chat"], u["id"]
        pid = st["d"]
        d = store.draft_get(pid, uid)
        if d is None:
            store.state_clear(uid)
            return self.bot.send(chat, "⌛ This session expired. Please search again.")
        ph, doc = m.get("photo"), m.get("document")
        if ph:
            fid, w, h, is_doc = ph[-1]["file_id"], ph[-1].get("width", 1), ph[-1].get("height", 1), False
        elif doc and str(doc.get("mime_type", "")).startswith("image/"):
            fid, w, h, is_doc = doc["file_id"], 1, 1, True
            if doc.get("thumbnail"):
                w, h = doc["thumbnail"].get("width", 1), doc["thumbnail"].get("height", 1)
        else:
            return self.bot.send(chat, "Please send an image.")
        field = st.get("f") if st["t"] == "edit" else "thumb"
        if field == "char":
            if not is_doc:
                return self.bot.send(chat, "ℹ️ Send the PNG <b>as a file</b> (attach → File) so the transparent background is kept.")
            if images.load("tg:" + fid, alpha=True) is None:
                return self.bot.send(chat, "❌ I couldn't read that image. Send a PNG/WebP file.")
            d["char"] = fid
            return self._after_edit(u, pid, d, "✅ Character art set.")
        if images.load("tg:" + fid) is None:
            return self.bot.send(chat, "❌ I couldn't read that image.")
        src, mm = "tg:" + fid, d["m"]
        landscape = w >= h * 1.2
        if field == "poster" and not landscape:
            mm["poster"] = src
            if mm.get("art", {}).get("poster"):
                mm["art"]["poster"] = [src]
        else:  # custom thumbnail / landscape image -> becomes the backdrop (and the poster when none better)
            mm["backdrop"] = src
            if mm.get("art", {}).get("background"):
                mm["art"]["background"] = [src]
            if not landscape:
                mm["poster"] = src
        d["thumb"] = True
        if st["t"] == "edit":
            return self._after_edit(u, pid, d, "✅ Image set.")
        self.show(u, pid, d)
        self._refresh_controls(u, pid, d)

    # ---------------------------------------------------------------- continue -> button link -> done
    def _a_skip(self, u, pid, d, a):
        self.bot.answer(u["cb"])
        store.state_set(u["id"], {"t": "link", "d": pid}, ttl=1800)
        self.bot.edit(u["chat"], d["cm"], "🔗 <b>CUSTOM BUTTON LINK</b>\n<blockquote>Please send me the link for the post / download button.</blockquote>",
                      reply_markup=kb([btn("⏭ SKIP", f"p:{pid}:l", style="primary"), btn("CANCEL", f"p:{pid}:x", style="danger")]))

    def _a_skip_link(self, u, pid, d, a):
        self.bot.answer(u["cb"])
        store.state_clear(u["id"])
        self.finish(u, pid, d)

    def on_link(self, u, text, st):
        pid = st["d"]
        d = store.draft_get(pid, u["id"])
        if d is None:
            store.state_clear(u["id"])
            return self.bot.send(u["chat"], "⌛ This session expired. Please search again.")
        if not URL_RE.match(text):
            return self.bot.send(u["chat"], "❌ That doesn't look like a link. Send a URL starting with <code>https://</code>, or press SKIP.")
        d["url"] = text
        store.state_clear(u["id"])
        self.show(u, pid, d)  # re-edit so the photo carries the button
        self.finish(u, pid, d)

    def finish(self, u, pid, d):
        uid, chat = u["id"], u["chat"]
        s = store.settings(uid)
        if d["url"] and d["pm"]:
            try:
                self.bot.call("editMessageReplyMarkup", chat_id=chat, message_id=d["pm"],
                              reply_markup=kb([btn(s.get("button_text") or "📥 Download", url=d["url"])]))
            except TgError:
                pass
        chans = store.channels(uid)
        rows = [[btn(f"📢 POST TO {c['title'][:22].upper()}", f"p:{pid}:c:{i}", style="success")] for i, c in enumerate(chans[:5])]
        if not chans:
            rows.append([btn("➕ ADD CHANNEL TO POST", "ch:add", style="primary")])
        rows.append([btn("✏️ EDIT AGAIN", f"p:{pid}:a", style="primary"), btn("🗑 DISMISS", f"p:{pid}:x", style="danger")])
        m = Media(**d["m"])
        self.bot.edit(chat, d["cm"], "✅ <b>Poster ready!</b>\nForward it, save it, or post it straight to your channel." +
                      ("" if chans else "\n<i>Tip: add your channel to post with one tap.</i>"), reply_markup=kb(*rows))
        jpg, _ = self.render(uid, d)
        tpl = "Clean Banner" if d["banner"] else templates.TEMPLATES[d["tpls"][d["ti"]]].label
        self.app.logs.poster(uid, u["name"], m.title, tpl, 0)
        safe = "".join(ch if ch.isalnum() else "_" for ch in m.title)[:40]
        cap = f"<b>{caption.e(m.title)}</b>\n{caption.e(tpl)} · {caption.e(brand_for(s, m.kind))}\nby {caption.e(u['name'])} <code>{uid}</code>"
        threading.Thread(target=self.app.archive.save_poster, args=(jpg, f"{safe}_{d['tpls'][d['ti']]}.jpg", cap), daemon=True).start()

    def _a_again(self, u, pid, d, a):
        self.bot.answer(u["cb"])
        store.state_set(u["id"], {"t": "draft", "d": pid}, ttl=7200)
        self._refresh_controls(u, pid, d)

    def _a_post(self, u, pid, d, a):
        chans = store.channels(u["id"])
        i = int(a[0])
        if i >= len(chans) or not d.get("fid"):
            return self.bot.answer(u["cb"], "Channel not found.", True)
        s = store.settings(u["id"])
        markup = kb([btn(s.get("button_text") or "📥 Download", url=d["url"])]) if d["url"] else None
        try:
            self.bot.send_photo(chans[i]["chat_id"], d["fid"], caption=caption.build(Media(**d["m"]), s) or None, reply_markup=markup)
            self.bot.answer(u["cb"], f"✅ Posted to {chans[i]['title']}", True)
        except TgError as ex:
            self.bot.answer(u["cb"], f"❌ Couldn't post: {str(ex)[:150]}. Is the bot still an admin there?", True)
