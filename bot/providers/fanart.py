"""Extra artwork: fanart.tv (optional key) + TMDB images, merged into ranked url lists per role.

Roles: logo (transparent title logos), background (1920x1080), poster, thumb, banner, clearart, character.

Movies  -> fanart.tv /v3/movies/{tmdb_id}
TV      -> fanart.tv /v3/tv/{tvdb_id}            (tvdb id comes from TMDB external_ids)
Anime   -> AniList has no TMDB/TVDB id, so the title is matched on TMDB first (needs TMDB_API_KEY), then as TV/movie.
Manga   -> not covered.

Ranking (first = best): fanart.tv HD logo first, English logos first, textless backgrounds/posters first, then likes;
TMDB images are appended after fanart.tv's. Every failure returns what we have, so callers always fall back to the
normal TMDB/AniList art."""
from __future__ import annotations

import logging
import threading
import time

from .. import http
from ..models import Media

log = logging.getLogger("posterbot")
BASE = "https://webservice.fanart.tv/v3"
TTL, MAX = 12 * 3600, 600
_cache: dict[str, tuple[float, dict, bool]] = {}
_lock = threading.Lock()

ROLES = {
    "movie": {"logo": ("hdmovielogo", "movielogo"), "background": ("moviebackground",), "poster": ("movieposter",),
              "thumb": ("moviethumb",), "banner": ("moviebanner",), "clearart": ("hdmovieclearart", "movieart"), "character": ()},
    "tv": {"logo": ("hdtvlogo", "clearlogo"), "background": ("showbackground",), "poster": ("tvposter",),
           "thumb": ("tvthumb",), "banner": ("tvbanner",), "clearart": ("hdclearart", "clearart"), "character": ("characterart",)},
}
LANG_ORDER = {  # smaller index = better; "" and "00" both mean textless
    "logo": ("en", "", "00"), "background": ("", "00", "en"), "poster": ("", "00", "en"), "thumb": ("", "00", "en"),
    "banner": ("en", "", "00"), "clearart": ("en", "", "00"), "character": ("", "00", "en"),
}


def rank(items, role: str) -> list[str]:
    """Order fanart items best-first: preferred language, then likes. Drops duplicates and url-less rows."""
    pref = LANG_ORDER.get(role, ("en", "", "00"))

    def lang_rank(lang):
        lang = lang or ""
        return pref.index(lang) if lang in pref else len(pref) + 1

    def likes(i):
        try:
            return int(i.get("likes") or 0)
        except (TypeError, ValueError):
            return 0

    seen, out = set(), []
    for it in sorted((i for i in items if i.get("url")), key=lambda i: (lang_rank(i.get("lang")), -likes(i))):
        if it["url"] not in seen:
            seen.add(it["url"])
            out.append(it["url"])
    return out


def _parse(data: dict, kind: str) -> dict:
    art = {}
    for role, keys in ROLES[kind].items():
        urls = []
        for k in keys:  # keep HD-key results ahead of the legacy key
            urls += [u for u in rank(data.get(k) or [], role) if u not in urls]
        if urls:
            art[role] = urls[:8]
    return art


def merge(*arts: dict) -> dict:
    """Combine art dicts role by role, earlier dicts first, no duplicates."""
    out: dict = {}
    for a in arts:
        for role, urls in (a or {}).items():
            cur = out.setdefault(role, [])
            cur += [u for u in urls if u not in cur]
    return {k: v[:10] for k, v in out.items() if v}


def _tmdb_ref(media: Media, tmdb) -> tuple[str, int]:
    """(tmdb kind 'movie'|'tv', tmdb id) for any media, or ('', 0)."""
    if media.source == "tmdb":
        return media.kind, media.id
    if media.source == "anilist" and media.kind == "anime" and tmdb:
        kind = "movie" if media.type_label == "MOVIE" else "tv"
        tid = tmdb.match([media.title, *media.alt_titles], media.year, kind)
        return (kind, tid) if tid else ("", 0)
    return "", 0


def fetch(media: Media, key: str, tmdb=None) -> tuple[dict, bool]:
    """-> (art, has_fanart). Cached 12 h per title."""
    if media.kind == "manga" or not (key or tmdb):
        return {}, False
    ck = f"{media.source}:{media.kind}:{media.id}:{bool(key)}"
    with _lock:
        hit = _cache.get(ck)
        if hit and time.time() - hit[0] < TTL:
            return hit[1], hit[2]
    fan, tm = {}, {}
    try:
        kind, tid = _tmdb_ref(media, tmdb)
        if tid:
            if key:
                try:
                    fid = tid if kind == "movie" else (tmdb.tvdb_id(tid) if tmdb else 0)
                    if fid:
                        data = http.get_json(f"{BASE}/{'movies' if kind == 'movie' else 'tv'}/{fid}", params={"api_key": key}, retries=1, timeout=15)
                        fan = _parse(data, "movie" if kind == "movie" else "tv")
                except Exception as e:  # 404 = nothing on fanart for this title
                    if "404" not in str(e):
                        log.warning("fanart %s: %s", ck, e)
            if tmdb and media.source != "tmdb":  # tmdb-sourced media already carries its own images
                try:
                    tm = tmdb.images(kind, tid)
                except Exception as e:
                    log.info("tmdb images %s: %s", ck, e)
    except Exception as e:
        log.warning("artwork lookup %s: %s", ck, e)
    art = merge(fan, tm)
    with _lock:
        if len(_cache) >= MAX:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[: MAX // 4]:
                _cache.pop(k, None)
        _cache[ck] = (time.time(), art, bool(fan))
    return art, bool(fan)


def enhance(media: Media, key: str, tmdb=None) -> Media:
    """Attach ranked artwork; fanart.tv's best textless background replaces the default backdrop."""
    art, has_fan = fetch(media, key, tmdb)
    if not art:
        return media
    media.art = merge(art, media.art)
    if has_fan and art.get("background"):
        if media.backdrop and media.backdrop not in media.art["background"]:
            media.extras = [media.backdrop, *media.extras]
        media.backdrop = art["background"][0]
    if has_fan and media.source == "tmdb" and art.get("poster"):
        media.poster = art["poster"][0]
    return media
