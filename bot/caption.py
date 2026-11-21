"""Caption under the poster, in the layout of the reference bot:

    Title (Year)
    ─────────
    ➥ Status / Episodes / Ratings / Pixels / Audio
    ─────────
    ➥ Genres
    ┃ expandable synopsis
"""
from __future__ import annotations

import html

from .models import Media

LIMIT = 1024  # Telegram caption limit
RULE = "─" * 18
SOURCE = {"tmdb": "TMDB", "anilist": "AniList"}


def e(x) -> str:
    return html.escape(str(x), quote=False)


def build(m: Media, s: dict) -> str:
    """s = the user's settings dict (caption style, pixels/audio lines, synopsis collapse)."""
    style = s.get("caption", "full")
    if style == "off":
        return ""
    title = f"{m.title} ({m.year})" if m.year else m.title
    unit = {"Min": "Runtime", "Chapters": "Chapters"}.get(m.unit, "Episodes")
    eps = f"{m.episodes} min" if m.unit == "Min" and m.episodes else m.episodes
    src = SOURCE.get(m.source, "")
    rating = (f"{m.score}/10 {src}".strip() if m.score else "")
    genres = ", ".join(g.title() if g.isupper() else g for g in m.genres)
    lines = [f"<b>{e(title)}</b>"]
    if style == "compact":
        bits = [x for x in (m.status, f"{unit}: {eps}" if eps else "", f"⭐ {rating}" if rating else "") if x]
        if bits:
            lines.append(" • ".join(e(b) for b in bits))
        if genres:
            lines.append(e(genres))
        return "\n".join(lines)[:LIMIT]
    lines.append(RULE)
    if m.status:
        lines.append(f"➥ Status: {e(m.status)}")
    if eps:
        lines.append(f"➥ {unit}: {e(eps)}")
    if rating:
        lines.append(f"➥ Ratings: {e(rating)}")
    if m.kind != "manga":
        if s.get("pixels", "480p | 720p | 1080p"):
            lines.append(f"➥ Pixels: {e(s.get('pixels', '480p | 720p | 1080p'))}")
        if s.get("audio", "Hindi & English"):
            lines.append(f"➥ Audio: {e(s.get('audio', 'Hindi & English'))}")
    if genres:
        lines += [RULE, f"➥ Genres: {e(genres)}"]
    head = "\n".join(lines)
    if s.get("synopsis", True) and m.synopsis:
        syn = " ".join(m.synopsis.split())
        wrap = ("<blockquote expandable>", "</blockquote>") if s.get("collapse", True) else ("<i>", "</i>")
        room = LIMIT - len(head) - len(wrap[0]) - len(wrap[1]) - 4
        if room > 60:
            body = syn if len(syn) <= room else syn[: room - 1].rsplit(" ", 1)[0] + "…"
            # escaping can grow the text; trim until the escaped form fits
            while len(e(body)) > room and len(body) > 10:
                body = body[: int(len(body) * .9)].rsplit(" ", 1)[0] + "…"
            head += "\n\n" + wrap[0] + e(body) + wrap[1]
    return head[:LIMIT]
