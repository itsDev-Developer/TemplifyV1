"""Artwork variants: which poster / background / logo / character a template uses.

Candidates per role come from the media (TMDB / AniList / fanart.tv); the user steps through them with the 🎨 ART
panel. `sel` maps role -> index and only holds roles the user changed, so untouched roles keep the template default."""
from __future__ import annotations

from dataclasses import replace

from .models import Media

ROLES = (("p", "Poster"), ("b", "Background"), ("l", "Logo"), ("c", "Character"))


def _dedupe(urls):
    out = []
    for u in urls:
        if u is not None and u not in out:
            out.append(u)
    return out


def candidates(m: Media, role: str, custom_char: str = "") -> list[str]:
    """Option urls for a role. "" = none (text title for the logo, no cutout for the character)."""
    a = m.art or {}
    if role == "p":
        return _dedupe([m.poster, *a.get("poster", [])])
    if role == "b":
        return _dedupe([m.backdrop, *a.get("background", []), *a.get("thumb", []), *m.extras])
    if role == "l":
        return _dedupe([*a.get("logo", []), ""]) if a.get("logo") else []
    if role == "c":
        pool = [("tg:" + custom_char) if custom_char else None, *a.get("character", []), *a.get("clearart", [])]
        pool = _dedupe(pool)
        return _dedupe([*pool, ""]) if pool else []
    return []


def roles_available(m: Media, custom_char: str = "") -> list[str]:
    return [r for r, _ in ROLES if len(candidates(m, r, custom_char)) >= (2 if r != "c" else 1)]


def current(sel: dict, role: str) -> int:
    """Selected index; the character role starts at -1 (AUTO = whatever the template picks)."""
    return int(sel.get(role, -1 if role == "c" else 0))


def step(m: Media, sel: dict, role: str, delta: int, custom_char: str = "") -> dict:
    n = len(candidates(m, role, custom_char))
    if n == 0:
        return sel
    cur = current(sel, role)
    new = ((cur + 1 + delta) % (n + 1)) - 1 if role == "c" else (cur + delta) % n
    out = dict(sel)
    out[role] = new
    return out


def label(m: Media, sel: dict, role: str, custom_char: str = "") -> str:
    cands = candidates(m, role, custom_char)
    cur = current(sel, role)
    if role == "c" and cur < 0:
        return "AUTO"
    if not cands:
        return "—"
    cur = min(cur, len(cands) - 1)
    name = "none" if cands[cur] == "" and role == "c" else "title text" if cands[cur] == "" else f"{cur + 1}/{len(cands)}"
    return name if name in ("none", "title text") else f"{name}"


def apply(m: Media, sel: dict, custom_char: str = "") -> tuple[Media, str | None]:
    """-> (media copy with the selection applied, cutout source or None). Never mutates `m`."""
    m = replace(m, art={k: list(v) for k, v in (m.art or {}).items()}, extras=list(m.extras))
    cutout = ("tg:" + custom_char) if custom_char else None
    sel = sel or {}
    if "p" in sel:
        c = candidates(m, "p")
        if c:
            m.poster = c[sel["p"] % len(c)]
    if "b" in sel:
        c = candidates(m, "b")
        if c:
            m.backdrop = c[sel["b"] % len(c)]
    if "l" in sel:
        c = candidates(m, "l")
        if c:
            pick = c[sel["l"] % len(c)]
            m.art["logo"] = [pick] if pick else []
    if "c" in sel and int(sel["c"]) >= 0:
        c = candidates(m, "c", custom_char)
        pick = c[int(sel["c"]) % len(c)] if c else ""
        m.art["character"], m.art["clearart"] = [], []
        cutout = pick or None
        if pick and not pick.startswith("tg:"):
            m.art["character"] = [pick]
        m.art = {k: v for k, v in m.art.items() if v}
    return m, cutout
