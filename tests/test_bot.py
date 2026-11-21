"""End-to-end tests against a fake Telegram server. Providers (TMDB / AniList / fanart.tv) are stubbed, no network.
Run:  python -m unittest discover -s tests -v"""
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_tg import Fake  # noqa: E402

FAKE = Fake()
TMP = tempfile.mkdtemp()
os.environ.update(BOT_TOKEN="123:abc", BOT_API_BASE=FAKE.base, DATA_DIR=TMP, OWNER_ID="1", TMDB_API_KEY="t",
                  FANART_API_KEY="f", RENDER_SCALE="0.5", PORT="0", LOG_CHANNEL_ID="", STORAGE_CHANNEL_ID="")

from PIL import Image, ImageDraw  # noqa: E402

from bot import app as appmod, config, store, templates  # noqa: E402
from bot.logs import Archive, LogChannel  # noqa: E402
from bot.models import Media, SearchHit  # noqa: E402
from bot.providers import anilist, fanart, tmdb  # noqa: E402
from bot.tg import Bot  # noqa: E402

# ---- fixtures ------------------------------------------------------------------------------------------------
ASSETS = os.path.join(TMP, "assets")
os.makedirs(ASSETS)
for name, size, col in (("poster.jpg", (400, 600), (120, 60, 200)), ("bg.jpg", (960, 540), (30, 60, 120))):
    im = Image.new("RGB", size, col)
    ImageDraw.Draw(im).ellipse((size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4), fill=(240, 200, 80))
    im.save(f"{ASSETS}/{name}")
logo = Image.new("RGBA", (500, 200), (0, 0, 0, 0))
ImageDraw.Draw(logo).rectangle((40, 40, 460, 160), fill=(255, 0, 0, 255))
logo.save(f"{ASSETS}/logo.png")
buf = io.BytesIO()
Image.new("RGB", (800, 450), (10, 200, 90)).save(buf, "JPEG")
FAKE.files["photos/USERIMG"] = buf.getvalue()
FAKE.files["photos/USERPNG"] = (lambda b: (Image.new("RGBA", (300, 500), (255, 0, 0, 160)).save(b, "PNG"), b.getvalue())[1])(io.BytesIO())


def make_media(i=1, art=False, kind="anime", title="Naruto"):
    m = Media(source="anilist", kind=kind, id=i, title=title, year="2002", episodes="220", unit="Episodes",
              genres=["Action", "Adventure"], synopsis="A mischievous ninja dreams of becoming Hokage. " * 6,
              poster=f"{ASSETS}/poster.jpg", backdrop=f"{ASSETS}/bg.jpg", status="Ended", type_label="TV SERIES", score="8.4")
    if art:
        m.art = {"logo": [f"{ASSETS}/logo.png"], "background": [f"{ASSETS}/bg.jpg"], "poster": [f"{ASSETS}/poster.jpg"]}
    return m


HITS = [SearchHit("anilist", "anime", i, f"Naruto Part {i}", "2002") for i in range(1, 9)]
anilist.AniList.search = lambda self, q, kind=None: HITS
anilist.AniList.details = lambda self, id_: make_media(id_)
tmdb.TMDB.search = lambda self, q, kind=None: [SearchHit("tmdb", "movie", 50, "The Movie", "2020")]
tmdb.TMDB.details = lambda self, kind, id_: make_media(id_, kind=kind, title="The Movie")

BOT = Bot("123:abc")
BOT.me = {"id": 999, "username": "fakebot"}
store.init()
LOGS, ARCH = LogChannel(BOT), Archive(BOT)
APP = appmod.App(BOT, LOGS, ARCH)
APP.limiter = appmod.RateLimiter(cap=10**6, every=0.001)  # rate limiting has its own test


def msg(uid, text=None, **kw):
    m = {"message_id": 5, "chat": {"id": uid, "type": "private"}, "from": {"id": uid, "first_name": f"U{uid}", "username": f"u{uid}"}}
    if text is not None:
        m["text"] = text
    m.update(kw)
    APP.handle({"update_id": time.time_ns(), "message": m})


def press(uid, data, mid):
    APP.handle({"update_id": time.time_ns(), "callback_query": {"id": "cb", "from": {"id": uid, "first_name": f"U{uid}"},
                                                                  "data": data, "message": {"chat": {"id": uid}, "message_id": mid}}})


def last_mid(method="sendMessage"):
    return FAKE.last(method)["r"]["message_id"]


def labels(call):
    return [b["text"] for b in FAKE.buttons(call)]


def find(call, text):
    return next(b for b in FAKE.buttons(call) if text in b["text"])


class T(unittest.TestCase):
    def setUp(self):
        FAKE.clear()

    # ---------------------------------------------------------------- start / settings
    def test_start_has_styled_buttons_and_creates_user(self):
        msg(10, "/start")
        c = FAKE.last("sendMessage")
        self.assertIn("Hey", c["p"]["text"])
        self.assertTrue(any("ADD CHANNEL" in x for x in labels(c)))
        self.assertTrue(any(b.get("style") for b in FAKE.buttons(c)))
        self.assertEqual(store.get_user(10)["name"], "U10")

    def test_settings_text_toggle_choice(self):
        msg(12, "/settings")
        c = FAKE.last("sendMessage")
        mid = c["r"]["message_id"]
        press(12, find(c, "Brand (all types)")["callback_data"], mid)
        msg(12, "My Brand")
        self.assertEqual(store.settings(12)["brand"], "My Brand")
        FAKE.clear()
        msg(12, "/settings")
        c = FAKE.last("sendMessage")
        press(12, find(c, "Synopsis in caption")["callback_data"], c["r"]["message_id"])
        self.assertFalse(store.settings(12)["synopsis"])
        press(12, find(c, "Accent colour")["callback_data"], c["r"]["message_id"])
        opts = FAKE.last("editMessageText")
        press(12, find(opts, "Purple")["callback_data"], c["r"]["message_id"])
        self.assertEqual(store.settings(12)["color"], "purple")

    # ---------------------------------------------------------------- the main poster flow
    def test_full_poster_flow(self):
        uid = 11
        msg(uid, "/anime naruto")
        res = FAKE.last("editMessageText")
        self.assertIn("Search results", res["p"]["text"])
        self.assertEqual(sum(1 for b in FAKE.buttons(res) if b["callback_data"].startswith("r:")), 6)
        mid = res["p"]["message_id"]
        press(uid, find(res, "NEXT")["callback_data"], mid)
        page2 = FAKE.last("editMessageText")
        self.assertEqual(sum(1 for b in FAKE.buttons(page2) if b["callback_data"].startswith("r:")), 2)
        FAKE.clear()
        press(uid, next(b for b in FAKE.buttons(page2) if b["callback_data"].startswith("r:"))["callback_data"], mid)
        photo = FAKE.last("sendPhoto")
        self.assertTrue(photo["files"]["photo"][:2] == b"\xff\xd8")           # a real JPEG was uploaded
        self.assertIn("Status: Ended", photo["p"]["caption"])
        self.assertIn("blockquote expandable", photo["p"]["caption"])
        ctrl = FAKE.last("editMessageText")
        self.assertIn("POSTER CONTROLS", ctrl["p"]["text"])
        self.assertEqual(len(FAKE.of("sendPhoto")), 1)
        nxt = find(ctrl, "NEXT")["callback_data"]
        pid = nxt.split(":")[1]
        back = f"p:{pid}:t:{store.draft_get(pid)['ti']}"
        # carousel: next, then back (second time served from the file_id cache)
        FAKE.clear()
        press(uid, nxt, mid)
        em = FAKE.last("editMessageMedia")
        self.assertTrue(em["files"]["file"][:2] == b"\xff\xd8")
        press(uid, back, mid)
        self.assertTrue(FAKE.last("editMessageMedia")["p"]["media"]["media"].startswith("PH"))  # cached id, no upload
        # edit data: title + invalid/valid rating
        press(uid, f"p:{pid}:e", mid)
        self.assertIn("EDIT ANIME POST DETAILS", FAKE.last("editMessageText")["p"]["text"])
        press(uid, f"p:{pid}:f:title", mid)
        FAKE.clear()
        msg(uid, "Brand New Title")
        self.assertIn("Brand New Title", FAKE.last("editMessageMedia")["p"]["media"]["caption"])
        press(uid, f"p:{pid}:f:rating", mid)
        FAKE.clear()
        msg(uid, "abc")
        self.assertIn("number", FAKE.last("sendMessage")["p"]["text"])
        msg(uid, "9.5")
        self.assertIn("9.5", FAKE.last("editMessageMedia")["p"]["media"]["caption"])
        # banner toggle
        FAKE.clear()
        press(uid, f"p:{pid}:b", mid)
        self.assertIn("Banner", FAKE.last("answerCallbackQuery")["p"]["text"])
        self.assertEqual(len(FAKE.of("editMessageMedia")), 1)
        # custom thumbnail photo from the user (landscape -> backdrop)
        press(uid, f"p:{pid}:bk", mid)
        FAKE.clear()
        msg(uid, photo=[{"file_id": "USERIMG", "width": 800, "height": 450}])
        self.assertEqual(len(FAKE.of("editMessageMedia")), 1)
        self.assertIn("CONTINUE", labels(FAKE.last("editMessageText"))[-2])
        # custom character PNG must come as a document
        press(uid, f"p:{pid}:f:char", mid)
        FAKE.clear()
        msg(uid, photo=[{"file_id": "USERIMG", "width": 10, "height": 10}])
        self.assertIn("as a file", FAKE.last("sendMessage")["p"]["text"])
        msg(uid, document={"file_id": "USERPNG", "mime_type": "image/png"})
        self.assertEqual(store.draft_get(pid)["char"], "USERPNG")
        # continue -> link
        press(uid, f"p:{pid}:bk", mid)
        press(uid, f"p:{pid}:k", mid)
        self.assertIn("CUSTOM BUTTON LINK", FAKE.last("editMessageText")["p"]["text"])
        FAKE.clear()
        msg(uid, "not a link")
        self.assertIn("link", FAKE.last("sendMessage")["p"]["text"].lower())
        msg(uid, "https://example.com/download")
        fin = FAKE.last("editMessageText")
        self.assertIn("Poster ready", fin["p"]["text"])
        em = FAKE.last("editMessageMedia")
        self.assertEqual(FAKE.buttons(em)[0]["url"], "https://example.com/download")
        # link a channel, then post to it
        FAKE.chats[-100777] = {"id": -100777, "type": "channel", "title": "My Channel"}
        msg(uid, "/addchannel")
        FAKE.clear()
        msg(uid, forward_origin={"type": "channel", "chat": {"id": -100777, "title": "My Channel"}}, text="fwd")
        self.assertEqual(store.channels(uid)[0]["chat_id"], -100777)
        press(uid, f"p:{pid}:a", mid)
        press(uid, f"p:{pid}:k", mid)
        press(uid, f"p:{pid}:l", mid)
        fin = FAKE.last("editMessageText")
        FAKE.clear()
        press(uid, find(fin, "POST TO")["callback_data"], mid)
        posted = FAKE.last("sendPhoto")
        self.assertEqual(posted["p"]["chat_id"], -100777)
        self.assertTrue(posted["p"]["photo"].startswith("PH"))
        # cancel removes both messages and the draft
        press(uid, f"p:{pid}:x", mid)
        self.assertIsNone(store.draft_get(pid))

    def test_channel_requires_user_to_be_admin(self):
        FAKE.chats[-100888] = {"id": -100888, "type": "channel", "title": "Not Yours"}
        FAKE.members[(-100888, 13)] = {"status": "member"}
        msg(13, "/addchannel")
        msg(13, "-100888")
        self.assertEqual(store.channels(13), [])
        self.assertIn("admin", FAKE.last("sendMessage")["p"]["text"])

    def test_session_expiry_is_handled(self):
        press(14, "r:deadbeef:0", 7)
        self.assertIn("expired", FAKE.last("answerCallbackQuery")["p"]["text"])

    def test_persistence_across_restart(self):
        msg(15, "/anime naruto")
        res = FAKE.last("editMessageText")
        press(15, find(res, "NARUTO PART 1")["callback_data"], res["p"]["message_id"])
        pid = find(FAKE.last("editMessageText"), "NEXT")["callback_data"].split(":")[1]
        store.close()
        store.init()  # simulated restart: drafts live in SQLite
        FAKE.clear()
        press(15, f"p:{pid}:t:1", res["p"]["message_id"])
        self.assertEqual(len(FAKE.of("editMessageMedia")), 1)

    # ---------------------------------------------------------------- fanart
    def test_fanart_ranking(self):
        data = {
            "hdmovielogo": [{"url": "a", "lang": "de", "likes": "50"}, {"url": "b", "lang": "en", "likes": "3"}, {"url": "c", "lang": "en", "likes": "9"}],
            "movielogo": [{"url": "d", "lang": "en", "likes": "99"}],
            "moviebackground": [{"url": "e", "lang": "en", "likes": "70"}, {"url": "f", "lang": "", "likes": "5"}, {"url": "g", "lang": "00", "likes": "8"}],
            "movieposter": [{"url": "h", "lang": "en", "likes": "1"}, {"url": "i", "lang": "00", "likes": "0"}],
        }
        art = fanart._parse(data, "movie")
        self.assertEqual(art["logo"], ["c", "b", "a", "d"])          # HD first, English first, most liked first
        self.assertEqual(art["background"], ["f", "g", "e"])         # textless before English
        self.assertEqual(art["poster"][0], "i")                      # textless poster first
        tv = fanart._parse({"characterart": [{"url": "x", "lang": "", "likes": "1"}], "hdclearart": [{"url": "y", "lang": "en", "likes": "2"}]}, "tv")
        self.assertEqual(tv["character"], ["x"])
        self.assertEqual(tv["clearart"], ["y"])

    def test_fanart_fetch_paths_and_fallbacks(self):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            if "/movies/" in url:
                return {"moviebackground": [{"url": "bg1", "lang": "", "likes": "1"}], "hdmovielogo": [{"url": "lg1", "lang": "en", "likes": "1"}]}
            if "/tv/777" in url:
                return {"showbackground": [{"url": "tbg", "lang": "", "likes": "1"}]}
            raise RuntimeError("HTTP Error 404: Not Found")

        orig = fanart.http.get_json
        fanart.http.get_json = fake_get
        try:
            fanart._cache.clear()
            movie = Media(source="tmdb", kind="movie", id=603, title="M")
            self.assertEqual(fanart.fetch(movie, "k")[0]["logo"], ["lg1"])
            self.assertIn("/movies/603", calls[-1])
            tmdb_stub = type("T", (), {"tvdb_id": lambda s, i: 777, "images": lambda s, k, i: {"logo": ["tl1"]}, "match": lambda s, t, y, k: 4242})()
            show = Media(source="tmdb", kind="tv", id=5, title="S")
            self.assertEqual(fanart.fetch(show, "k", tmdb_stub)[0]["background"], ["tbg"])
            anime = Media(source="anilist", kind="anime", id=9, title="A", year="2020", type_label="TV SERIES")
            self.assertEqual(fanart.fetch(anime, "k", tmdb_stub)[0]["background"], ["tbg"])   # anime -> TMDB match -> TVDB id
            self.assertEqual(fanart.fetch(Media(source="anilist", kind="manga", id=1, title="M"), "k", tmdb_stub), ({}, False))
            self.assertEqual(fanart.fetch(Media(source="tmdb", kind="movie", id=1, title="X"), ""), ({}, False))      # no key
            tmdb_stub2 = type("T", (), {"tvdb_id": lambda s, i: 123, "images": lambda s, k, i: {}, "match": lambda s, t, y, k: 1})()
            self.assertEqual(fanart.fetch(Media(source="tmdb", kind="tv", id=6, title="T"), "k", tmdb_stub2), ({}, False))  # 404 -> {}
        finally:
            fanart.http.get_json = orig

    def test_fanart_templates_only_offered_with_art(self):
        s = {}
        self.assertFalse(any(k.startswith("fa_") for k in APP.flow.tpl_keys(make_media(), s)))
        keys = APP.flow.tpl_keys(make_media(art=True), s)
        self.assertEqual([k for k in keys if k.startswith("fa_")], ["fa_hero", "fa_poster", "fa_character", "fa_diamond", "fa_diamond_dark", "fa_frame", "fa_showcase"])
        self.assertNotIn("banner", keys)
        self.assertEqual(APP.flow.start_tpl(make_media(art=True), s, keys), "fa_hero")
        self.assertFalse(any(k.startswith("fa_") for k in APP.flow.tpl_keys(make_media(art=True), {"fanart": False})))

    def test_art_variants(self):
        from bot import variants
        m = make_media(art=True)
        m.art.update({"logo": ["L1", "L2"], "poster": ["P2"], "background": ["B2"], "character": ["C1"]})
        self.assertEqual(variants.candidates(m, "l"), ["L1", "L2", ""])
        self.assertEqual(variants.candidates(m, "c", "FID"), ["tg:FID", "C1", ""])
        self.assertEqual(set(variants.roles_available(m)), {"p", "b", "l", "c"})
        sel = variants.step(m, {}, "c", 1)                 # AUTO -> first candidate
        self.assertEqual(sel["c"], 0)
        self.assertEqual(variants.step(m, {"c": 0}, "c", 1)["c"], 1)    # -> none
        self.assertEqual(variants.step(m, {"c": 1}, "c", 1)["c"], -1)   # -> back to AUTO
        out, cut = variants.apply(m, {"l": 1, "p": 1, "c": 0}, "")
        self.assertEqual((out.art["logo"], out.poster, cut), (["L2"], "P2", "C1"))
        self.assertNotIn("character", variants.apply(m, {"c": 1}, "")[0].art)  # "none" strips character art
        self.assertEqual(m.art["logo"], ["L1", "L2"])      # input never mutated
        # end to end: the ART panel re-renders and stores the selection
        m2 = make_media(art=True)
        m2.art["logo"] = [f"{ASSETS}/logo.png", ""]
        pd = {"t": "poster", "m": __import__("dataclasses").asdict(m2), "tpls": ["fa_hero", "split"], "ti": 0, "banner": False,
              "char": "", "sel": {}, "url": "", "pm": 0, "cm": 0, "fid": "", "thumb": False}
        _, txt_markup = APP.flow.controls("x", pd)
        self.assertIn("p:x:v", str(txt_markup))
        a, _ = APP.flow.render(1, pd)
        pd["sel"] = {"l": 1}
        b, _ = APP.flow.render(1, pd)
        self.assertNotEqual(a, b)

    def test_per_category_brands(self):
        from bot.settings import brand_for, tagline_for
        self.assertEqual(brand_for({}, "anime"), "AniCruise")
        self.assertEqual(brand_for({}, "manga"), "Manga Cruise")
        self.assertEqual(brand_for({"brand": "Mine"}, "anime"), "Mine")                    # general beats default
        self.assertEqual(brand_for({"brand": "Mine", "brand_anime": "A"}, "anime"), "A")   # category beats general
        self.assertEqual(brand_for({"brand_movie": "M"}, "tv"), "Nova Flix")
        self.assertTrue(tagline_for({}, "tv"))
        # the settings panel has a Brands group reachable from the main panel
        store.touch_user(77, "U", "u", True)
        FAKE.clear()
        msg(77, "/settings")
        self.assertIn("s:g:brands", [b.get("callback_data") for b in FAKE.buttons(FAKE.last("sendMessage"))])

    # ---------------------------------------------------------------- HTTP API for other bots
    def _api(self, method, path, key=None, body=None, query=None, headers=None):
        from bot import api
        h = dict(headers or {})
        if key:
            h["Authorization"] = "Bearer " + key
        raw = json.dumps(body).encode() if isinstance(body, (dict, list)) else (body or b"")
        st, hdr, out = api.handle(APP, method, path, query or {}, h, raw)
        return st, hdr, out

    def test_api_auth_and_listing(self):
        import json as j
        st, _, out = self._api("GET", "/api/v1/templates")
        self.assertEqual(st, 401)
        self.assertEqual(self._api("GET", "/api/v1/templates", key="pbk_nope")[0], 401)
        self.assertEqual(self._api("GET", "/api/v1/openapi.json")[0], 200)            # spec is public
        kid, tok = store.api_key_create("t1", 1, rpm=60, daily=0)
        self.assertNotIn(tok, str(store.api_keys()))                                   # only the hash is stored
        st, _, out = self._api("GET", "/api/v1/templates", key=tok)
        keys = [t["key"] for t in j.loads(out)["templates"]]
        self.assertEqual(st, 200)
        self.assertIn("fa_diamond", keys)
        st, hdr, _ = self._api("GET", "/api/v1/usage", headers={"X-API-Key": tok})      # second auth style
        self.assertEqual(st, 200)
        self.assertEqual(self._api("GET", "/api/v1/search", key=tok, query={"q": ["naruto"], "type": ["anime"]})[0], 200)
        self.assertEqual(self._api("GET", "/api/v1/search", key=tok, query={"q": ["x"], "type": ["bogus"]})[0], 422)
        st, _, out = self._api("GET", "/api/v1/media/anilist/anime/3", key=tok)
        self.assertEqual((st, j.loads(out)["title"]), (200, "Naruto"))
        self.assertEqual(self._api("GET", "/api/v1/nope", key=tok)[0], 404)
        store.api_key_revoke(kid)
        self.assertEqual(self._api("GET", "/api/v1/templates", key=tok)[0], 401)

    def test_api_render(self):
        import base64, io, json as j
        from PIL import Image
        _, tok = store.api_key_create("render", 1, rpm=600, daily=0)
        req = {"source": "anilist", "kind": "anime", "id": 1, "template": "split", "scale": 0.5}
        st, hdr, out = self._api("POST", "/api/v1/render", key=tok, body=req)
        self.assertEqual((st, hdr["Content-Type"]), (200, "image/jpeg"))
        self.assertEqual(Image.open(io.BytesIO(out)).size, (640, 360))
        st, _, out = self._api("POST", "/api/v1/render", key=tok, body={**req, "response": "json", "format": "png", "brand": "My Brand"})
        r = j.loads(out)
        self.assertEqual((st, r["brand"], r["format"]), (200, "My Brand", "png"))
        self.assertTrue(Image.open(io.BytesIO(base64.b64decode(r["image_base64"]))).format == "PNG")
        self.assertIn("Naruto", r["caption"])
        # per-type default brand when none is sent
        _, _, out = self._api("POST", "/api/v1/render", key=tok, body={**req, "response": "json"})
        self.assertEqual(j.loads(out)["brand"], "AniCruise")
        # inline media, no lookup, + data-URI poster override
        buf = io.BytesIO(); Image.new("RGB", (200, 300), (20, 120, 220)).save(buf, "PNG")
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        inline = {"media": {"title": "My Show", "kind": "tv", "genres": ["Drama"]}, "template": "card", "scale": 0.5}
        st, _, a = self._api("POST", "/api/v1/render", key=tok, body=inline)
        st2, _, b = self._api("POST", "/api/v1/render", key=tok, body={**inline, "overrides": {"poster_url": uri, "title": "Other"}})
        self.assertEqual((st, st2), (200, 200))
        self.assertNotEqual(a, b)
        from bot import api
        self.assertEqual(api._mem, {})                                                  # uploads are dropped after the render
        # banner + title lookup
        st, _, _ = self._api("POST", "/api/v1/render", key=tok, body={"title": "naruto", "type": "anime", "banner": True, "template": "x", "scale": .5})
        self.assertEqual(st, 200)

    def test_api_validation_limits_and_ssrf(self):
        import json as j
        from bot import api
        _, tok = store.api_key_create("v", 1, rpm=600, daily=0)
        good = {"source": "anilist", "kind": "anime", "id": 1, "template": "split", "scale": 0.5}
        for bad in ({**good, "template": "nope"}, {**good, "template": "banner_hidden"}, {**good, "color": "javascript"},
                    {**good, "format": "gif"}, {**good, "response": "xml"}, {"template": "split"},
                    {**good, "source": "evil"}, {**good, "art": {"logo": "x"}}, {**good, "overrides": "str"}):
            st, _, out = self._api("POST", "/api/v1/render", key=tok, body=bad)
            self.assertEqual(st, 422, (bad, out))
            self.assertIn("error", j.loads(out))
        self.assertEqual(self._api("POST", "/api/v1/render", key=tok, body=b"{not json")[0], 400)
        # SSRF: private / loopback / metadata / non-http targets are refused before any request is made
        for url in ("http://127.0.0.1/x.png", "http://169.254.169.254/latest", "http://localhost:8080/a", "http://10.0.0.5/a.png",
                    "file:///etc/passwd", "ftp://example.com/a.png", "http://[::1]/a.png"):
            st, _, out = self._api("POST", "/api/v1/render", key=tok, body={**good, "overrides": {"poster_url": url}})
            self.assertEqual(st, 422, url)
        self.assertEqual(self._api("POST", "/api/v1/render", key=tok, body={**good, "overrides": {"poster_url": "data:text/html;base64,AAAA"}})[0], 422)
        # rate limit per key
        _, slow = store.api_key_create("slow", 1, rpm=2, daily=0)
        codes = [self._api("GET", "/api/v1/usage", key=slow)[0] for _ in range(4)]
        self.assertEqual(codes[:2], [200, 200])
        self.assertEqual(codes[3], 429)
        st, hdr, _ = self._api("GET", "/api/v1/usage", key=slow)
        self.assertIn("Retry-After", hdr)
        # daily limit
        _, day = store.api_key_create("day", 1, rpm=600, daily=2)
        codes = [self._api("GET", "/api/v1/usage", key=day)[0] for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        # kill switch
        store.gset("api_enabled", False)
        try:
            self.assertEqual(self._api("GET", "/api/v1/usage", key=tok)[0], 503)
        finally:
            store.gset("api_enabled", True)

    def test_api_safe_fetch_checks_every_hop(self):
        import http.server, threading as th
        from bot import api

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.path == "/ok":
                    body = open(os.path.join(ASSETS, "poster.jpg"), "rb").read()
                    self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.send_header("Content-Length", str(len(body)))
                    self.end_headers(); self.wfile.write(body)
                elif self.path == "/redir":
                    self.send_response(302); self.send_header("Location", "http://internal.test/secret"); self.end_headers()
                else:
                    self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(b"<html>")
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        th.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        real = api._check_host
        try:
            self.assertEqual(api._fetch.__name__, "_fetch")
            with self.assertRaises(api.ApiError):                       # loopback is refused by the real check
                api._fetch(f"http://127.0.0.1:{port}/ok")
            api._check_host = lambda host, p: "127.0.0.1" if host != "internal.test" else real("127.0.0.1", p)
            self.assertGreater(len(api._fetch(f"http://public.test:{port}/ok")), 1000)
            with self.assertRaises(api.ApiError):                       # not an image
                api._fetch(f"http://public.test:{port}/html")
            with self.assertRaises(api.ApiError):                       # redirect into a private host is re-checked
                api._fetch(f"http://public.test:{port}/redir")
        finally:
            api._check_host = real
            srv.shutdown()

    def test_api_over_real_http(self):
        import urllib.error
        from bot import config, main
        config.PORT, config.HOST = 0, "127.0.0.1"
        pool = ThreadPoolExecutor(2)
        srv = main.serve(APP, pool, "sec", "/webhook")
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        _, tok = store.api_key_create("http", 1, rpm=600, daily=0)

        def call(path, data=None, key=tok, method=None):
            req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None, method=method,
                                         headers={"Authorization": "Bearer " + key} if key else {})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, dict(r.headers), r.read()
            except urllib.error.HTTPError as e:
                return e.code, dict(e.headers), e.read()
        try:
            self.assertEqual(call("/api/v1/templates", key=None)[0], 401)
            st, h, body = call("/api/v1/render", {"source": "anilist", "kind": "anime", "id": 1, "template": "polaroid", "scale": .5})
            self.assertEqual((st, h["Content-Type"]), (200, "image/jpeg"))
            self.assertTrue(body.startswith(b"\xff\xd8"))
            self.assertIn("X-RateLimit-Remaining", h)
            self.assertEqual(call("/api/v1/render", {"template": "x"})[0], 422)
            self.assertEqual(call("/health", key=None)[0], 200)                     # normal endpoints unaffected
        finally:
            srv.shutdown()
            pool.shutdown(wait=False)

    def test_hardening_breaker_validate_ready(self):
        from bot import config, http, main
        # circuit breaker opens after repeated upstream failures and fails fast
        http._breaker.clear()
        calls = []
        real = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: (calls.append(1), (_ for _ in ()).throw(OSError("down")))[1]
        real_sleep, http.time.sleep = http.time.sleep, lambda x: None
        try:
            for _ in range(http.FAILS):
                with self.assertRaises(OSError):
                    http.request("http://flaky.test/x", retries=0)
            n = len(calls)
            with self.assertRaises(http.CircuitOpen):
                http.request("http://flaky.test/y")
            self.assertEqual(len(calls), n)                      # no network attempt while open
            self.assertIn("flaky.test", http.open_circuits())
            with self.assertRaises(OSError):                     # other hosts unaffected
                http.request("http://other.test/", retries=0)
            self.assertEqual(len(calls), n + 1)
        finally:
            urllib.request.urlopen = real
            http.time.sleep = real_sleep
            http._breaker.clear()
        # config validation
        old = (config.BOT_TOKEN, config.OWNER_ID, config.TMDB_API_KEY)
        try:
            config.BOT_TOKEN, config.OWNER_ID, config.TMDB_API_KEY = "garbage", 0, ""
            errs, warns = config.validate()
            self.assertTrue(any("BOT_TOKEN" in e for e in errs))
            self.assertTrue(any("OWNER_ID" in w for w in warns) and any("TMDB" in w for w in warns))
            config.BOT_TOKEN = "123456789:" + "A" * 35
            self.assertEqual(config.validate()[0], [])
        finally:
            config.BOT_TOKEN, config.OWNER_ID, config.TMDB_API_KEY = old
        # /ready and /health
        config.PORT, config.HOST = 0, "127.0.0.1"
        pool = ThreadPoolExecutor(1)
        srv = main.serve(APP, pool, "sec", "/webhook")
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            r = json.loads(urllib.request.urlopen(base + "/ready", timeout=10).read())
            self.assertTrue(r["ready"] and r["db"] and r["schema"] >= 2)
            main.stop.set()
            try:
                urllib.request.urlopen(base + "/ready", timeout=10)
                self.fail("expected 503 while shutting down")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 503)
        finally:
            main.stop.clear()
            srv.shutdown()
            pool.shutdown(wait=False)

    def test_api_key_commands(self):
        store.touch_user(1, "Owner", "o", True)
        FAKE.clear()
        msg(1, "/apikey friendbot 7 70")
        text = FAKE.last("sendMessage")["p"]["text"]
        tok = re.search(r"pbk_[\w-]+", text).group(0)
        k = store.api_key_lookup(tok)
        self.assertEqual((k["name"], k["rpm"], k["daily"]), ("friendbot", 7, 70))
        FAKE.clear()
        msg(1, "/apikeys")
        self.assertIn("friendbot", FAKE.last("sendMessage")["p"]["text"])
        self.assertNotIn(tok, FAKE.last("sendMessage")["p"]["text"])
        msg(1, f"/apirevoke {k['id']}")
        self.assertIsNone(store.api_key_lookup(tok))
        FAKE.clear()
        msg(31, "/apikey sneaky")
        self.assertIn("Admins only", FAKE.last("sendMessage")["p"]["text"])

    # ---------------------------------------------------------------- access control / limits
    def test_access_control(self):
        store.touch_user(1, "Owner", "o", True)
        msg(20, "/start")
        store.gset("maintenance", True)
        FAKE.clear()
        msg(20, "/help")
        self.assertIn("maintenance", FAKE.last("sendMessage")["p"]["text"])
        FAKE.clear()
        msg(1, "/help")
        self.assertIn("Commands", FAKE.last("sendMessage")["p"]["text"])           # owner passes
        store.gset("maintenance", False)
        store.gset("public", False)
        FAKE.clear()
        msg(21, "/help")
        self.assertIn("private", FAKE.last("sendMessage")["p"]["text"])
        msg(1, "/auth 21")
        FAKE.clear()
        msg(21, "/help")
        self.assertIn("Commands", FAKE.last("sendMessage")["p"]["text"])
        store.gset("public", True)
        msg(1, "/ban 20")
        APP._warned.clear()
        FAKE.clear()
        msg(20, "/help")
        self.assertIn("banned", FAKE.last("sendMessage")["p"]["text"])
        msg(1, "/unban 20")
        FAKE.clear()
        msg(22, "/stats")
        self.assertIn("Admins only", FAKE.last("sendMessage")["p"]["text"])

    def test_rate_limiter(self):
        rl = appmod.RateLimiter(cap=5, every=10)
        self.assertEqual(sum(rl.ok(1) for _ in range(20)), 5)
        self.assertTrue(rl.ok(2))

    def test_daily_limit(self):
        store.gset("daily_limit", 1)
        try:
            msg(30, "/anime naruto")
            res = FAKE.last("editMessageText")
            press(30, find(res, "NARUTO PART 1")["callback_data"], res["p"]["message_id"])
            self.assertEqual(len(FAKE.of("sendPhoto")), 1)
            msg(30, "/anime naruto")
            res = FAKE.last("editMessageText")
            FAKE.clear()
            press(30, find(res, "NARUTO PART 2")["callback_data"], res["p"]["message_id"])
            self.assertIn("Daily limit", FAKE.last("answerCallbackQuery")["p"]["text"])
            self.assertEqual(len(FAKE.of("sendPhoto")), 0)
        finally:
            store.gset("daily_limit", 0)

    # ---------------------------------------------------------------- admin panel, channels for logs/storage
    def test_admin_panel_sets_log_channel_and_logs(self):
        msg(1, "/admin")
        c = FAKE.last("sendMessage")
        self.assertIn("Logs channel", " ".join(labels(c)))
        press(1, find(c, "Logs channel")["callback_data"], c["r"]["message_id"])
        FAKE.clear()
        msg(1, "abc")
        self.assertIn("can't post", FAKE.last("sendMessage")["p"]["text"])
        FAKE.clear()
        press(1, find(c, "Logs channel")["callback_data"], c["r"]["message_id"])
        msg(1, "-100555")
        self.assertEqual(store.gget("log_channel"), "-100555")
        self.assertEqual(FAKE.of("sendMessage")[0]["p"]["chat_id"], -100555)       # test message
        FAKE.clear()
        LOGS.new_user(5, "Zed", "zed")
        LOGS.flush([LOGS.q.get(timeout=2)])
        self.assertEqual(FAKE.last("sendMessage")["p"]["chat_id"], -100555)
        store.gset("log_channel", None)

    def test_archive_and_backup(self):
        store.gset("storage_channel", "-100999")
        ARCH.save_poster(b"JPEGDATA", "x.jpg", "cap")
        d = FAKE.last("sendDocument")
        self.assertEqual(d["p"]["chat_id"], "-100999") if isinstance(d["p"]["chat_id"], str) else self.assertEqual(d["p"]["chat_id"], -100999)
        ARCH.backup_now()
        self.assertEqual(FAKE.last("sendDocument")["files"]["document"][:6], b"SQLite")   # a real SQLite snapshot
        self.assertTrue(FAKE.of("pinChatMessage"))
        store.gset("storage_channel", None)

    def test_snapshot_restore_roundtrip(self):
        store.uset(40, "brand", "x") if store.get_user(40) else store.touch_user(40, "A", "a") and store.uset(40, "brand", "x")
        raw = store.snapshot()
        path = store.PATH
        store.restore(raw)
        self.assertEqual(store.settings(40)["brand"], "x")
        self.assertEqual(store.PATH, path)

    def test_broadcast(self):
        msg(50, "/start")
        FAKE.clear()
        msg(1, "/broadcast hello everyone")
        for _ in range(100):
            if any("Broadcast finished" in c["p"].get("text", "") for c in FAKE.of("sendMessage")):
                break
            time.sleep(0.1)
        sent = [c["p"]["chat_id"] for c in FAKE.of("sendMessage") if c["p"].get("text") == "hello everyone"]
        self.assertIn(50, sent)

    # ---------------------------------------------------------------- templates
    def test_every_template_renders_on_hostile_data(self):
        cases = [
            Media(source="x", kind="tv", id=1, title="The Eminence in Shadow: Reincarnated as a Background Character Who Secretly Controls Everything", year="2022"),
            Media(source="x", kind="manga", id=2, title="괴력난신 怪力亂神 Привет", year="2021", episodes="88", unit="Chapters",
                  genres=["Action", "Monsters", "Fantasy", "Drama", "Romance"], synopsis="설명 " * 80, studio="スタジオ", status="Ongoing", type_label="MANHWA", score="9.1"),
            Media(source="x", kind="movie", id=3, title="X"),
            make_media(art=True),
        ]
        from bot.context import Ctx
        for m in cases:
            for key, t in templates.TEMPLATES.items():
                for brand in ("AniCruise", "A very long brand name here"):
                    im = templates.render(key, Ctx(m, brand=brand, accent=t.accent), 0.5)
                    self.assertEqual(im.im.size, (640, 360), key)

    # ---------------------------------------------------------------- HTTP server (Render)
    def test_http_server_health_metrics_webhook(self):
        from bot import main as bm
        pool = ThreadPoolExecutor(2)
        seen = []
        stub = type("A", (), {"handle": lambda s, u: seen.append(u)})()
        config.PORT = 0
        srv = bm.serve(stub, pool, "sec", "/webhook")
        port = srv.server_address[1]
        try:
            h = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health").read())
            self.assertEqual(h["status"], "ok")
            self.assertIn("posterbot_updates", urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics").read().decode())
            req = lambda tok: urllib.request.Request(f"http://127.0.0.1:{port}/webhook", data=b'{"update_id":1}', headers={"X-Telegram-Bot-Api-Secret-Token": tok})
            self.assertEqual(urllib.request.urlopen(req("sec")).status, 200)
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req("wrong"))
            self.assertEqual(cm.exception.code, 403)
            time.sleep(0.3)
            self.assertEqual(seen, [{"update_id": 1}])
        finally:
            srv.shutdown()
            pool.shutdown()


if __name__ == "__main__":
    unittest.main()
