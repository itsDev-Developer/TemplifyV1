"""Turns a Media object into the `Ctx` every template draws from (text fields + lazily loaded images)."""
from __future__ import annotations

import html
import re
from functools import cached_property

from . import images
from .draw import rgb
from .models import Media

COLORS = {
    "purple": "#7c3aed",
    "pink": "#d6005c",
    "cyan": "#06b6d4",
    "orange": "#e0820d",
    "red": "#e11d48",
    "green": "#16a34a",
    "blue": "#2563eb",
    "gold": "#f5b301",
}

KIND_PLURAL = {"movie": "movies", "tv": "shows", "anime": "anime", "manga": "manhwas"}
UNIT_SHORT = {"Episodes": "EPS", "Chapters": "CH", "Min": "MIN"}


def clean_text(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def split_brand(brand: str) -> tuple[str, str]:
    """'Nova Flix' -> Nova|Flix, 'AniCruise' -> Ani|Cruise, 'Zeta' -> ''|Zeta (second part gets the accent)."""
    words = brand.split()
    if len(words) > 1:
        return " ".join(words[:-1]), words[-1]
    parts = re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+|[A-Z]+(?![a-z])", brand)
    return (parts[0], "".join(parts[1:])) if len(parts) > 1 else ("", brand)


class Ctx:
    """Everything a template needs. Images load on first use and are cached (images.py)."""

    def __init__(self, media: Media, brand="Nova Flix", accent="#7c3aed", tagline=None, promo=None, cutout=None):
        self.m = media
        self.kind = media.kind
        self.is_manga = media.kind == "manga"
        self.brand = brand.strip() or "Nova Flix"
        self.brand_up = self.brand.upper()
        self.brand_a, self.brand_b = split_brand(self.brand)
        self.brand_sep = " " if " " in self.brand else ""
        self.accent_hex = accent
        self.accent = rgb(accent)
        self._tagline, self._promo = tagline, promo
        self.cutout_src = cutout

        self.title = media.title.strip() or "Untitled"
        self.year = media.year
        self.genres = [g.upper() for g in media.genres][:6]
        self.genre_line = " • ".join(self.genres[:2])
        self.studio = media.studio
        self.status = media.status or ("Ongoing" if self.is_manga else "Returning Series")
        self.type_label = media.type_label or media.kind.upper()
        self.score = media.score
        unit = UNIT_SHORT.get(media.unit, "")
        self.eps = media.episodes
        self.eps_long = f"{media.episodes} {media.unit}" if media.episodes else ""
        self.eps_short = f"{media.episodes}({unit})" if media.episodes else ""
        self.synopsis = clean_text(media.synopsis) or "No synopsis available."
        self.cta = "READ" if self.is_manga else "WATCH"

    # ---- text defaults
    def tag(self, default: str) -> str:
        return (self._tagline or default).upper()

    @property
    def promo(self) -> str:
        if self._promo:
            return self._promo
        what = {"MANHWA": "manhwas", "MANHUA": "manhuas", "MANGA": "manga"}.get(self.type_label.upper()) or KIND_PLURAL.get(self.kind, "shows")
        return f"Stay connected for exciting updates, exclusive news, release schedules, and sneak peeks into upcoming {what}........"

    @property
    def meta(self) -> str:
        return " • ".join(x for x in (self.year, self.type_label, self.eps_long) if x)

    # ---- images (lazy)
    @cached_property
    def poster(self):
        return images.load(self.m.poster) or images.load(self.m.backdrop)

    @cached_property
    def wide(self):
        return images.load(self.m.backdrop) or self.poster

    @cached_property
    def cutout(self):
        return images.load(self.cutout_src, alpha=True) if self.cutout_src else None

    # ---- fanart.tv artwork (ranked best-first by providers/fanart.py; each falls back to the normal art)
    def _first(self, urls, alpha=False):
        for u in urls[:3]:
            im = images.load(u, alpha=alpha)
            if im is not None:
                return im
        return None

    @property
    def has_fanart(self) -> bool:
        return bool(self.m.art)

    @cached_property
    def art_logo(self):
        im = self._first(self.m.art.get("logo", []), alpha=True)
        box = im.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox() if im is not None else None
        return im.crop(box) if box else im  # logos often carry transparent padding

    def logo_for(self, light: bool):
        """The art logo, tinted so it stays readable: near-white logos go dark on light layouts, near-black go white on dark."""
        im = self.art_logo
        if im is None:
            return None
        raw = im.resize((32, 32)).convert("RGBA").tobytes()
        px = [p for p in zip(*[iter(raw)] * 4) if p[3] > 40]
        if not px:
            return im
        lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _ in px) / len(px)
        tint = (28, 24, 38) if light and lum > 200 else (255, 255, 255) if not light and lum < 55 else None
        if tint is None:
            return im
        from PIL import Image
        flat = Image.new("RGBA", im.size, tint + (255,))
        flat.putalpha(im.getchannel("A"))
        return flat

    @cached_property
    def art_bg(self):
        return self._first(self.m.art.get("background", [])) or self._first(self.m.art.get("thumb", [])) or self.wide

    @cached_property
    def art_poster(self):
        return self._first(self.m.art.get("poster", [])) or self.poster

    @cached_property
    def art_cutout(self):
        """Transparent character art, else clearart, else the user's custom PNG; None if there is none."""
        return self.cutout or self._first(self.m.art.get("character", []) + self.m.art.get("clearart", []), alpha=True)

    def gallery(self, n: int) -> list:
        """n images (cycled): poster, backdrop, then extras. Never contains None unless nothing loads."""
        urls, seen = [], set()
        for u in [self.m.poster, self.m.backdrop, *self.m.extras]:
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
        imgs = [im for im in (images.load(u) for u in urls[: max(n, 3)]) if im is not None]
        if not imgs:
            return [None] * n
        return [imgs[i % len(imgs)] for i in range(n)]

    def shot(self, i: int):
        return self.gallery(i + 1)[i]
