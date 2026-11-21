"""HTTP API so other bots/services can ask this bot for finished posters.

    GET  /api/v1/templates            list templates
    GET  /api/v1/search?q=&type=      find titles (type: anime|manga|movie|tv)
    GET  /api/v1/media/{source}/{kind}/{id}
    POST /api/v1/render               render a poster (image bytes, or JSON with base64 + caption)
    GET  /api/v1/usage                this key's limits and counters
    GET  /api/v1/openapi.json         machine-readable description

Auth: `Authorization: Bearer pbk_…` or `X-API-Key: pbk_…`. Keys are created by an admin with /apikey in the bot and are
stored hashed. Everything is rate limited per key, renders share the bot's render semaphore, and any URL a caller asks us
to fetch (poster_url …) is checked against private/loopback addresses first.

`handle()` is transport-agnostic (method, path, query, headers, body -> status, headers, bytes) so it is unit-testable;
main.py wires it into the HTTP server."""
from __future__ import annotations

import base64
import binascii
import http.client
import ipaddress
import json
import logging
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.parse
from dataclasses import asdict, fields

from . import caption, config, images, metrics, store, templates, variants
from .context import COLORS, Ctx
from .models import Media
from .settings import brand_for, tagline_for

log = logging.getLogger("posterbot")

MAX_BODY = 10 * 1024 * 1024
MAX_IMAGE = 15 * 1024 * 1024
MAX_PIXELS = 3840 * 2160
VERSION = "1"
KINDS = ("anime", "manga", "movie", "tv")
URL_FIELDS = {"poster_url": "poster", "backdrop_url": "backdrop", "logo_url": "logo", "character_url": "character"}
TEXT_FIELDS = {"title": 200, "synopsis": 2000, "year": 12, "episodes": 12, "status": 40, "type_label": 30, "studio": 60,
               "unit": 20}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


# ================================================================== rate limiting (per key, token bucket)
class Limiter:
    def __init__(self):
        self._b: dict[int, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: int, rpm: int) -> tuple[bool, float, int]:
        """-> (allowed, retry_after_seconds, remaining)."""
        cap, rate = float(max(1, rpm)), max(1, rpm) / 60.0
        now = time.monotonic()
        with self._lock:
            tokens, last = self._b.get(key, (cap, now))
            tokens = min(cap, tokens + (now - last) * rate)
            if tokens >= 1:
                self._b[key] = (tokens - 1, now)
                return True, 0.0, int(tokens - 1)
            self._b[key] = (tokens, now)
            return False, (1 - tokens) / rate, 0


LIMITER = Limiter()


# ================================================================== safe remote image fetch (SSRF guard)
def _check_host(host: str, port: int) -> str:
    """Resolve and refuse anything that isn't a public address. Returns the IP to connect to."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ApiError(422, "bad_url", f"Can't resolve {host}")
    for _, _, _, _, addr in infos:
        ip = ipaddress.ip_address(addr[0])
        if not ip.is_global:
            raise ApiError(422, "bad_url", "URL points to a private or reserved address")
    return infos[0][4][0]


def _fetch(url: str, timeout: float = 15, hops: int = 3) -> bytes:
    """GET an image over http(s). The checked IP is the one we connect to (no DNS rebinding) and every redirect is
    re-checked. Size and content-type are enforced."""
    for _ in range(hops + 1):
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ApiError(422, "bad_url", "Only http(s) image URLs are allowed")
        port = u.port or (443 if u.scheme == "https" else 80)
        ip = _check_host(u.hostname, port)
        if u.scheme == "https":
            conn = http.client.HTTPSConnection(ip, port, timeout=timeout, context=ssl.create_default_context())
            conn.connect = _tls_connect(conn, ip, port, u.hostname, timeout)
        else:
            conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        try:
            path = (u.path or "/") + (f"?{u.query}" if u.query else "")
            conn.request("GET", path, headers={"Host": u.netloc, "User-Agent": "poster-bot/1.0", "Accept": "image/*"})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
                url = urllib.parse.urljoin(url, r.getheader("Location"))
                continue
            if r.status != 200:
                raise ApiError(422, "bad_url", f"Image URL answered HTTP {r.status}")
            ctype = (r.getheader("Content-Type") or "").split(";")[0].strip().lower()
            if not ctype.startswith("image/"):
                raise ApiError(422, "bad_url", "URL is not an image")
            if int(r.getheader("Content-Length") or 0) > MAX_IMAGE:
                raise ApiError(413, "too_large", "Image is larger than 15 MB")
            data = r.read(MAX_IMAGE + 1)
            if len(data) > MAX_IMAGE:
                raise ApiError(413, "too_large", "Image is larger than 15 MB")
            return data
        except (OSError, http.client.HTTPException) as e:
            raise ApiError(422, "bad_url", f"Couldn't fetch the image: {type(e).__name__}")
        finally:
            conn.close()
    raise ApiError(422, "bad_url", "Too many redirects")


def _tls_connect(conn, ip, port, hostname, timeout):
    def connect():
        sock = socket.create_connection((ip, port), timeout)
        conn.sock = conn._context.wrap_socket(sock, server_hostname=hostname)
    return connect


def _decode_data_uri(s: str) -> bytes:
    m = re.match(r"^data:image/[a-z0-9.+-]+;base64,(.+)$", s, re.I | re.S)
    if not m:
        raise ApiError(422, "bad_image", "Image must be an http(s) URL or a base64 data:image/… URI")
    try:
        raw = base64.b64decode(m.group(1), validate=False)
    except (binascii.Error, ValueError):
        raise ApiError(422, "bad_image", "Invalid base64 image")
    if len(raw) > MAX_IMAGE:
        raise ApiError(413, "too_large", "Image is larger than 15 MB")
    return raw


# per-request uploads live here under random "mem:<token>" sources and are dropped after the render
_mem: dict[str, bytes] = {}
images.register_loader("mem", lambda rest: _mem[rest])


def _stash(src: str) -> str:
    raw = _decode_data_uri(src) if src.startswith("data:") else _fetch(src)
    tok = secrets.token_hex(8)
    _mem[tok] = raw
    return "mem:" + tok


# ================================================================== request -> Media / options
def _clean(x, limit: int) -> str:
    return " ".join(str(x).split())[:limit]


def _media(app, body: dict) -> Media:
    if isinstance(body.get("media"), dict):
        raw = body["media"]
        allowed = {f.name for f in fields(Media)}
        data = {k: v for k, v in raw.items() if k in allowed}
        data.setdefault("source", "custom")
        data.setdefault("kind", raw.get("type") or "movie")
        data.setdefault("id", 0)
        data.setdefault("title", "Untitled")
        if data["kind"] not in KINDS:
            raise ApiError(422, "bad_request", f"media.kind must be one of {', '.join(KINDS)}")
        for k in ("poster", "backdrop"):
            if data.get(k) and not str(data[k]).startswith(("http://", "https://", "data:")):
                raise ApiError(422, "bad_request", f"media.{k} must be an http(s) URL or data URI")
        try:
            return Media(**{k: v for k, v in data.items() if k in allowed})
        except TypeError as e:
            raise ApiError(422, "bad_request", f"Invalid media object: {e}")
    if body.get("source") and body.get("kind") and body.get("id") is not None:
        src, kind = str(body["source"]), str(body["kind"])
        if src not in ("tmdb", "anilist") or kind not in KINDS:
            raise ApiError(422, "bad_request", "source must be tmdb|anilist and kind anime|manga|movie|tv")
        try:
            return _details(app, src, kind, int(body["id"]))
        except ValueError:
            raise ApiError(422, "bad_request", "id must be a number")
    if body.get("title") and body.get("type") in KINDS:
        hits = _search(app, str(body["title"])[:100], body["type"])
        if not hits:
            raise ApiError(404, "not_found", "No title matched that search")
        h = hits[0]
        return _details(app, h["source"], h["kind"], h["id"])
    raise ApiError(422, "bad_request", "Send `media`, or source+kind+id, or title+type")


def _details(app, source: str, kind: str, id_: int) -> Media:
    if source == "tmdb" and not app.tmdb:
        raise ApiError(503, "unavailable", "Movie/TV data isn't configured on this server (TMDB_API_KEY)")
    try:
        return app.flow.media_for(0, source, kind, id_)
    except ApiError:
        raise
    except Exception as e:
        log.warning("api details %s:%s: %s", source, id_, e)
        raise ApiError(502, "upstream", "The data provider didn't answer. Try again shortly.")


def _search(app, q: str, kind: str) -> list[dict]:
    if kind not in KINDS:
        raise ApiError(422, "bad_request", f"type must be one of {', '.join(KINDS)}")
    try:
        if kind in ("anime", "manga"):
            hits = app.anilist.search(q, kind)
        elif app.tmdb:
            hits = app.tmdb.search(q, kind)
        else:
            raise ApiError(503, "unavailable", "Movie/TV search isn't configured on this server (TMDB_API_KEY)")
    except ApiError:
        raise
    except Exception as e:
        log.warning("api search: %s", e)
        raise ApiError(502, "upstream", "The search provider didn't answer. Try again shortly.")
    return [asdict(h) for h in hits]


def _options(body: dict, media: Media) -> dict:
    tpl = "banner" if body.get("banner") else str(body.get("template") or "")
    if not tpl:
        raise ApiError(422, "bad_request", "`template` is required (see GET /api/v1/templates)")
    t = templates.TEMPLATES.get(tpl)
    if not t or (t.hidden and tpl != "banner"):
        raise ApiError(422, "bad_request", f"Unknown template '{tpl}'")
    color = str(body.get("color") or "auto")
    if color != "auto" and color not in COLORS and not HEX.match(color):
        raise ApiError(422, "bad_request", "color must be auto, a colour name or #rrggbb")
    try:
        scale = float(body.get("scale", 1.0))
    except (TypeError, ValueError):
        raise ApiError(422, "bad_request", "scale must be a number")
    scale = min(2.0, max(0.5, scale))
    if int(1280 * scale) * int(720 * scale) > MAX_PIXELS:
        raise ApiError(422, "bad_request", "scale too large")
    fmt = str(body.get("format") or "jpeg").lower()
    if fmt not in ("jpeg", "jpg", "png"):
        raise ApiError(422, "bad_request", "format must be jpeg or png")
    resp = str(body.get("response") or "image").lower()
    if resp not in ("image", "json"):
        raise ApiError(422, "bad_request", "response must be image or json")
    gen = {"brand": body.get("brand") and _clean(body["brand"], 30), "tagline": body.get("tagline") and _clean(body["tagline"], 70)}
    return {"tpl": tpl, "color": color, "scale": scale, "fmt": "png" if fmt == "png" else "jpeg", "resp": resp, "gen": gen}


def _apply_overrides(media: Media, body: dict) -> tuple[Media, dict, str | None, list[str]]:
    """Text overrides, uploads and art selection -> (media, selection, cutout, mem tokens to free)."""
    ov = body.get("overrides") or {}
    if not isinstance(ov, dict):
        raise ApiError(422, "bad_request", "`overrides` must be an object")
    for k, lim in TEXT_FIELDS.items():
        if ov.get(k) not in (None, ""):
            setattr(media, k, _clean(ov[k], lim))
    if ov.get("rating") not in (None, ""):
        media.score = _clean(ov["rating"], 6)
    if isinstance(ov.get("genres"), list):
        media.genres = [_clean(g, 24) for g in ov["genres"][:6] if str(g).strip()]
    stashed, cutout = [], None
    for key, role in URL_FIELDS.items():
        if not ov.get(key):
            continue
        ref = _stash(str(ov[key]))
        stashed.append(ref)
        if role == "poster":
            media.poster = ref
        elif role == "backdrop":
            media.backdrop = ref
        elif role == "logo":
            media.art = {**media.art, "logo": [ref]}
        else:
            cutout = ref
    art = body.get("art") or {}
    if not isinstance(art, dict):
        raise ApiError(422, "bad_request", "`art` must be an object like {\"logo\": 1, \"character\": 0}")
    sel = {}
    for name, role in (("poster", "p"), ("background", "b"), ("logo", "l"), ("character", "c")):
        if name in art:
            try:
                sel[role] = int(art[name])
            except (TypeError, ValueError):
                raise ApiError(422, "bad_request", f"art.{name} must be an integer index")
    media, sel_cut = variants.apply(media, sel)
    return media, sel, cutout or sel_cut, stashed


# ================================================================== endpoints
def _templates() -> dict:
    out = []
    for k, t in templates.TEMPLATES.items():
        out.append({"key": k, "label": t.label, "group": t.group, "accent": t.accent, "hidden": t.hidden,
                    "needs_artwork": t.group == "Fanart"})
    return {"templates": out, "colors": COLORS}


def _render(app, key: dict, body: dict) -> tuple[int, dict, bytes]:
    media = _media(app, body)
    opt = _options(body, media)
    if opt["tpl"] in templates.TEMPLATES and templates.TEMPLATES[opt["tpl"]].group == "Fanart" and opt["tpl"] != "banner" \
            and not (media.art or {}):
        # still renders (templates degrade gracefully) - say so in a header instead of failing
        note = "no-extra-artwork"
    else:
        note = ""
    media, sel, cutout, mem = _apply_overrides(media, body)
    try:
        accent = COLORS.get(opt["color"]) or (opt["color"] if opt["color"].startswith("#") else templates.TEMPLATES[opt["tpl"]].accent)
        kind = media.kind
        brand = opt["gen"]["brand"] or brand_for({}, kind)
        tagline = opt["gen"]["tagline"] or tagline_for({}, kind)
        from . import flow  # render gate shared with the bot
        if not flow._render_gate.acquire(timeout=20):
            raise ApiError(503, "busy", "Renderer is busy, retry shortly", {"Retry-After": "5"})
        t0 = time.time()
        try:
            ctx = Ctx(media, brand=brand, accent=accent, tagline=tagline, cutout=cutout)
            canvas = templates.render(opt["tpl"], ctx, opt["scale"])
            data = canvas.png() if opt["fmt"] == "png" else canvas.jpeg(90)
            size = (canvas.im.width, canvas.im.height)
        finally:
            flow._render_gate.release()
        ms = int((time.time() - t0) * 1000)
    finally:
        for ref in mem:
            _mem.pop(ref[4:], None)
            images.forget(ref)
    metrics.inc("api_renders")
    metrics.observe("render_seconds", ms / 1000)
    ctype = "image/png" if opt["fmt"] == "png" else "image/jpeg"
    cap_settings = {k: body[k] for k in ("pixels", "audio") if isinstance(body.get(k), str)}
    cap_settings["caption"] = body.get("caption_style") if body.get("caption_style") in ("full", "compact", "off") else "full"
    cap = caption.build(media, cap_settings)
    hdr = {"X-Render-Ms": str(ms), "X-Template": opt["tpl"], "X-Title": urllib.parse.quote(media.title)}
    if note:
        hdr["X-Warning"] = note
    if opt["resp"] == "json":
        return 200, {}, json.dumps({
            "template": opt["tpl"], "format": opt["fmt"], "width": size[0], "height": size[1], "render_ms": ms,
            "brand": brand, "tagline": tagline, "caption": cap,
            "media": {"source": media.source, "kind": media.kind, "id": media.id, "title": media.title, "year": media.year,
                      "score": media.score, "genres": media.genres},
            "image_base64": base64.b64encode(data).decode(),
        }).encode()
    hdr["Content-Type"] = ctype
    return 200, hdr, data


def openapi() -> dict:
    err = {"description": "Error", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
    return {
        "openapi": "3.0.3",
        "info": {"title": "Poster Bot API", "version": VERSION,
                 "description": "Render anime / manga / movie / TV posters from other bots. Auth: `Authorization: Bearer pbk_…`."},
        "components": {
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}, "apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
            "schemas": {"Error": {"type": "object", "properties": {"error": {"type": "object", "properties": {
                "code": {"type": "string"}, "message": {"type": "string"}}}}}},
        },
        "security": [{"bearer": []}, {"apiKey": []}],
        "paths": {
            "/api/v1/templates": {"get": {"summary": "List templates", "responses": {"200": {"description": "OK"}, "401": err}}},
            "/api/v1/search": {"get": {"summary": "Search titles", "parameters": [
                {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
                {"name": "type", "in": "query", "required": True, "schema": {"type": "string", "enum": list(KINDS)}}],
                "responses": {"200": {"description": "OK"}, "401": err}}},
            "/api/v1/media/{source}/{kind}/{id}": {"get": {"summary": "Title details incl. artwork options", "responses": {"200": {"description": "OK"}, "404": err}}},
            "/api/v1/render": {"post": {"summary": "Render a poster", "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "required": ["template"], "properties": {
                    "template": {"type": "string"}, "banner": {"type": "boolean"},
                    "source": {"type": "string", "enum": ["tmdb", "anilist"]}, "kind": {"type": "string", "enum": list(KINDS)},
                    "id": {"type": "integer"}, "title": {"type": "string"}, "type": {"type": "string", "enum": list(KINDS)},
                    "media": {"type": "object", "description": "Inline media (no lookup). Fields: title, kind, year, synopsis, genres, poster, backdrop, score, episodes, unit, status, type_label, studio, art"},
                    "brand": {"type": "string"}, "tagline": {"type": "string"}, "color": {"type": "string"},
                    "scale": {"type": "number", "minimum": 0.5, "maximum": 2}, "format": {"type": "string", "enum": ["jpeg", "png"]},
                    "response": {"type": "string", "enum": ["image", "json"]},
                    "overrides": {"type": "object", "description": "title, rating, genres, synopsis, year, episodes, status, type_label, poster_url, backdrop_url, logo_url, character_url (http(s) or data: URIs)"},
                    "art": {"type": "object", "description": "Indices into the artwork lists: poster, background, logo, character"},
                    "caption_style": {"type": "string", "enum": ["full", "compact", "off"]}, "pixels": {"type": "string"}, "audio": {"type": "string"}}}}}},
                "responses": {"200": {"description": "image/jpeg|png or JSON"}, "401": err, "422": err, "429": err}}},
            "/api/v1/usage": {"get": {"summary": "Key limits and counters", "responses": {"200": {"description": "OK"}}}},
        },
    }


# ================================================================== dispatcher
def _json(obj, status=200, headers=None) -> tuple[int, dict, bytes]:
    return status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(obj).encode()


def _auth(headers: dict) -> dict:
    tok = headers.get("x-api-key", "")
    auth = headers.get("authorization", "")
    if not tok and auth.lower().startswith("bearer "):
        tok = auth[7:]
    key = store.api_key_lookup(tok.strip()) if tok else None
    if not key:
        raise ApiError(401, "unauthorized", "Missing or invalid API key", {"WWW-Authenticate": 'Bearer realm="poster-bot"'})
    return key


def handle(app, method: str, path: str, query: dict, headers: dict, body: bytes) -> tuple[int, dict, bytes]:
    """-> (status, headers, body). Never raises."""
    metrics.inc("api_requests")
    headers = {k.lower(): v for k, v in headers.items()}
    try:
        if path.rstrip("/") == "/api/v1/openapi.json" and method == "GET":
            return _json(openapi())
        if not store.gget("api_enabled", True):
            raise ApiError(503, "disabled", "The API is switched off")
        key = _auth(headers)
        ok, retry, left = LIMITER.take(key["id"], key["rpm"])
        rl = {"X-RateLimit-Limit": str(key["rpm"]), "X-RateLimit-Remaining": str(left)}
        if not ok:
            metrics.inc("api_limited")
            raise ApiError(429, "rate_limited", "Too many requests", {**rl, "Retry-After": str(int(retry) + 1)})
        today, daily = store.api_key_use(key["id"])
        if daily and today > daily:
            raise ApiError(429, "daily_limit", f"Daily limit of {daily} calls reached", {**rl, "Retry-After": "3600"})
        route = path.rstrip("/")
        if method == "GET" and route == "/api/v1/templates":
            st, h, b = _json(_templates())
        elif method == "GET" and route == "/api/v1/usage":
            st, h, b = _json({"name": key["name"], "rpm": key["rpm"], "daily_limit": daily, "calls_today": today, "calls_total": key["calls"] + 1})
        elif method == "GET" and route == "/api/v1/search":
            q = _clean((query.get("q") or [""])[0], 100)
            if not q:
                raise ApiError(422, "bad_request", "q is required")
            st, h, b = _json({"results": _search(app, q, (query.get("type") or [""])[0])})
        elif method == "GET" and (m := re.fullmatch(r"/api/v1/media/(tmdb|anilist)/(anime|manga|movie|tv)/(\d+)", route)):
            media = _details(app, m.group(1), m.group(2), int(m.group(3)))
            d = asdict(media)
            d["art_counts"] = {k: len(v) for k, v in (media.art or {}).items()}
            st, h, b = _json(d)
        elif method == "POST" and route == "/api/v1/render":
            if len(body) > MAX_BODY:
                raise ApiError(413, "too_large", "Request body too large")
            try:
                req = json.loads(body or b"{}")
                assert isinstance(req, dict)
            except Exception:
                raise ApiError(400, "bad_json", "Body must be a JSON object")
            st, h, b = _render(app, key, req)
        elif route.startswith("/api/v1/"):
            raise ApiError(404, "not_found", "Unknown endpoint") if method in ("GET", "POST") else ApiError(405, "method_not_allowed", "Use GET or POST")
        else:
            raise ApiError(404, "not_found", "Unknown endpoint")
        return st, {**rl, **h}, b
    except ApiError as e:
        if e.status >= 500:
            metrics.inc("api_errors")
        return _json({"error": {"code": e.code, "message": e.message}}, e.status, e.headers)
    except Exception as e:  # a bug is our problem, not the caller's: log it, hide the details
        log.exception("api error")
        metrics.inc("api_errors")
        try:
            app.logs.error("api", e)
        except Exception:
            pass
        return _json({"error": {"code": "internal", "message": "Internal error"}}, 500)
