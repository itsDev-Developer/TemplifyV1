"""Modern streaming-style layouts: Neon Night, Glass Hero, Cinema Bar, Trailer, Streaming Row,
Minimal Clean, Trending Rank, New Episode."""
from __future__ import annotations

import datetime

from ..draw import darken, lighten, mix
from . import template
from .core import INK, WHITE, brand_logo

GOLD = (255, 196, 0)


def num(s: str, default=None):
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def chips(c, x, y, items, size=11, h=26, padx=14, gap=8, max_w=600, **kw):
    """Wrapping row of chips. Returns the y below the last row."""
    cx = x
    for t in items:
        w = c.tw(t, size, kw.get("weight", "bold"), kw.get("sp", 0)) + 2 * padx
        if cx > x and cx + w > x + max_w:
            cx, y = x, y + h + gap
        c.chip(cx, y, t, size=size, h=h, padx=padx, **kw)
        cx += w + gap
    return y + h


def stars(c, x, y, score, size=16, on=GOLD, off=(90, 90, 100), gap=3):
    s10 = num(score, 0) or 0
    full = int(round(s10 / 2))
    for i in range(5):
        c.icon("star", x + size / 2 + i * (size + gap), y + size / 2, size, on if i < full else off)
    return 5 * (size + gap)


def top_brand(c, d, color=WHITE, x=70, y=34, size=17, accent=None):
    return brand_logo(c, d, x, y, size, dark=color, weight="bold", accent=accent)


# ------------------------------------------------------------------ Glass Hero
@template("glass", "Glass Hero", "#ef4444")
def glass(c, d):
    acc = d.accent
    c.image(d.wide, 0, 0, 1280, 720, mode="smart", focus=(.5, .3))
    c.gradient(0, 0, 1280, 720, (0, 0, 0), (0, 0, 0), a1=190, a2=25, angle=0)
    c.gradient(0, 480, 1280, 240, (0, 0, 0), (0, 0, 0), a1=0, a2=160)
    top_brand(c, d, x=70, y=32, size=18)
    for i, label in enumerate(("Home", "Browse", "New", "My List")):
        c.text(780 + i * 92, 36, label, 13, "bold" if i == 0 else "medium", WHITE if i == 0 else (205, 205, 212), lh=1.4)
    c.icon("search", 1190, 46, 17, WHITE)

    X, W = 110, 490
    size, tl = c.fit(d.title, W, 126, 50, 28, "extrabold", lh=1.1, max_lines=3, sp=-.3)
    syn_n = len(c.clamp(d.synopsis, 15, "regular", W, 4))
    ph = 34 + 44 + len(tl) * size * 1.1 + 14 + 40 + syn_n * 15 * 1.62 + 28 + 52 + 34
    c.frost(70, 108, 570, ph, r=30, blur=24, ta=28, border=75)
    y = 142
    x = X
    for t in [d.type_label, d.year, d.status.upper()]:
        if t:
            x += c.chip(x, y, str(t), 10, 24, 13, "bold", color=WHITE, fill=(255, 255, 255), alpha=50, sp=.8) + 8
    y += 44
    c.lines(X, y, tl, size, "extrabold", WHITE, lh=1.1, sp=-.3)
    y += len(tl) * size * 1.1 + 14
    xx = X + stars(c, X, y + 1, d.score, 16)
    if d.score:
        xx += c.text(xx + 6, y, d.score, 16, "bold", WHITE, lh=1.4) + 18
    c.text(xx, y + 1, d.eps_long or d.genre_line, 14, "medium", (215, 215, 222), lh=1.4)
    y += 40
    c.para(X, y, W, d.synopsis, 15, "regular", (232, 232, 238), lh=1.62, max_lines=4)
    by = y + syn_n * 15 * 1.62 + 28
    c.rect(X, by, 200, 52, acc, r=26)
    c.icon("play", X + 36, by + 26, 15, WHITE)
    c.text(X + 58, by + 14, "Watch Trailer" if not d.is_manga else "Read Now", 14, "bold", WHITE, lh=1.4)
    c.rect(X + 214, by, 150, 52, fill=(255, 255, 255), alpha=40, r=26)
    c.rect(X + 214, by, 150, 52, outline=WHITE, ow=1.2, r=26, alpha=110)
    c.icon("plus", X + 244, by + 26, 14, WHITE)
    c.text(X + 264, by + 14, "My List", 14, "bold", WHITE, lh=1.4)

    c.image(d.poster, 982, 300, 220, 330, r=18, border=3, border_color=WHITE, focus=(.5, .2),
            shadow=(40, 0, 18, 140, (0, 0, 0)))


# ------------------------------------------------------------------ Cinema Bar
@template("cinema", "Cinema Bar", "#f59e0b")
def cinema(c, d):
    acc = d.accent
    c.image(d.wide, 0, 0, 1280, 720, mode="smart", focus=(.5, .3))
    c.gradient(0, 0, 1280, 160, (0, 0, 0), (0, 0, 0), a1=175, a2=0)
    c.gradient(0, 300, 1280, 420, (0, 0, 0), (0, 0, 0), a1=0, a2=245)
    top_brand(c, d, x=60, y=34, size=18)
    xx = 1220
    for t in ("5.1", "HD"):
        w = c.tw(t, 11, "bold") + 24
        xx -= w
        c.chip(xx, 36, t, 11, 26, 12, "bold", color=WHITE, outline=WHITE, ow=1.3, alpha=200)
        xx -= 10

    c.image(d.poster, 60, 418, 180, 270, r=10, border=3, border_color=WHITE, focus=(.5, .2),
            shadow=(40, 0, 16, 170, (0, 0, 0)))
    X = 280
    c.rect(X, 438, c.tw("NOW STREAMING", 10.5, "bold", 1.6) + 26, 24, acc, r=3)
    c.text(X + 13, 441, "NOW STREAMING", 10.5, "bold", (20, 20, 20), lh=1.4, sp=1.6)
    size, tl = c.fit(d.title.upper(), 640, 104, 54, 28, "extrabold", lh=1.06, max_lines=2)
    c.lines(X, 478, tl, size, "extrabold", WHITE, lh=1.06)
    y = 478 + len(tl) * size * 1.06 + 12
    c.text(X, y, " • ".join(p for p in (d.year, d.genre_line, d.eps_long) if p), 15, "medium", (214, 214, 220), lh=1.4)
    c.para(X, y + 32, 640, d.synopsis, 13.5, "regular", (190, 190, 198), lh=1.55, max_lines=2)

    if d.score:
        c.text(1170, 440, d.score, 66, "extrabold", acc, align="r", lh=1.1)
        c.text(1170, 515, "OUT OF 10", 10, "bold", (190, 190, 198), align="r", lh=1.4, sp=1.6)
        stars(c, 1170 - 5 * 19, 540, d.score, 16)
    c.rect(990, 618, 180, 52, acc, r=4)
    c.text(1080, 631, d.cta + " NOW", 14, "extrabold", (20, 20, 20), align="m", lh=1.4, sp=1)


# ------------------------------------------------------------------ Minimal Clean
@template("minimal", "Minimal Clean", "#2563eb")
def minimal(c, d):
    acc = d.accent
    c.rect(0, 0, 1280, 720, (247, 247, 249))
    c.circle(1000, 620, 330, fill=acc, alpha=14)
    c.circle(1180, 90, 120, fill=acc, alpha=10)
    c.image(d.poster, 110, 80, 360, 540, r=12, focus=(.5, .2), shadow=(60, 0, 28, 70, (30, 40, 70)))
    X, W = 580, 600
    c.text(X, 112, "NOW STREAMING" if not d.is_manga else "NOW READING", 11, "bold", acc, lh=1.4, sp=3)
    size, tl = c.fit(d.title, W, 150, 62, 30, "bold", lh=1.08, max_lines=3, sp=-.5)
    c.lines(X, 142, tl, size, "bold", (17, 24, 39), lh=1.08, sp=-.5)
    y = 142 + len(tl) * size * 1.08 + 14
    xx = X
    for i, t in enumerate([p for p in (d.year, d.genre_line.replace(" • ", " / "), d.eps_long) if p]):
        if i:
            c.rect(xx + 8, y + 5, 1.5, 14, (190, 194, 204))
            xx += 20
        xx += c.text(xx, y, t, 15, "medium", (107, 114, 128), lh=1.4)
    y += 40
    c.rect(X, y, 56, 3, acc, r=1.5)
    y += 28
    n = len(c.clamp(d.synopsis, 16, "regular", 560, 4))
    c.para(X, y, 560, d.synopsis, 16, "regular", (75, 85, 99), lh=1.7, max_lines=4)
    y += n * 16 * 1.7 + 26
    if d.score:
        xx = X + stars(c, X, y, d.score, 18, on=acc, off=(210, 213, 220))
        c.text(xx + 6, y - 1, d.score, 17, "bold", (17, 24, 39), lh=1.3)
        c.text(xx + 6 + c.tw(d.score, 17, "bold") + 4, y + 1, "/ 10", 14, "medium", (140, 146, 160), lh=1.3)
        y += 46
    c.rect(X, y, 170, 52, (17, 24, 39), r=26)
    c.text(X + 85, y + 14, d.cta.title() + " now", 14, "bold", WHITE, align="m", lh=1.4)
    c.circle(X + 170 + 16 + 26, y + 26, 26, outline=(17, 24, 39), ow=1.6)
    c.icon("play", X + 170 + 16 + 28, y + 26, 16, (17, 24, 39))
    c.text(X, 656, d.brand_up, 11, "bold", (160, 166, 180), lh=1.4, sp=3)


# ------------------------------------------------------------------ Trending Rank
@template("rank", "Trending Rank", "#facc15")
def rank(c, d):
    acc = d.accent
    c.gradient(0, 0, 1280, 720, (16, 16, 20), (38, 32, 18), angle=60)
    c.glow(600, 330, 420, acc, alpha=40)
    sc = num(d.score)
    big = f"{sc:.1f}" if sc else "1"
    label = "TOP RATED" if sc else "TRENDING"
    bs = 290 if sc else 440
    c.text(34, 150 if sc else 60, big, bs, "extrabold", fill=None, outline=acc, ow=3, lh=1)
    c.text(60, 112, label, 14, "bold", acc, lh=1.4, sp=5)
    c.text(60, 626, "THIS WEEK", 13, "bold", (170, 165, 150), lh=1.4, sp=5)

    c.image(d.poster, 470, 90, 340, 510, r=14, border=4, border_color=acc, focus=(.5, .2), rot=4,
            shadow=(50, 0, 24, 170, (0, 0, 0)))
    c.poly([(0, 0), (140, 0), (0, 140)], acc)
    c.text(16, 30, "HOT", 15, "extrabold", (20, 20, 20), lh=1)

    X, W = 860, 360
    c.rect(X, 120, 4, 22, acc)
    c.text(X + 14, 120, d.type_label.upper(), 12, "bold", (200, 196, 180), lh=1.8, sp=3)
    size, tl = c.fit(d.title.upper(), W, 190, 46, 24, "extrabold", lh=1.08, max_lines=4)
    c.lines(X, 164, tl, size, "extrabold", WHITE, lh=1.08)
    y = 164 + len(tl) * size * 1.08 + 14
    c.text(X, y, " • ".join(p for p in (d.year, d.eps_long) if p), 14, "medium", (200, 196, 180), lh=1.4)
    y += 34
    y = chips(c, X, y, d.genres[:3], 10.5, 26, 13, 8, W, color=acc, outline=acc, ow=1.2, sp=.6) + 18
    c.para(X, y, W, d.synopsis, 13.5, "regular", (200, 196, 180), lh=1.6, max_lines=3)
    y += 3 * 13.5 * 1.6 + 22
    c.rect(X, y, 190, 50, acc, r=25)
    c.icon("play", X + 36, y + 25, 15, (20, 20, 20))
    c.text(X + 58, y + 13, d.cta + " NOW", 14, "extrabold", (20, 20, 20), lh=1.4, sp=1)


# ------------------------------------------------------------------ New Episode
@template("episode", "New Episode", "#7c3aed")
def episode(c, d):
    acc = d.accent
    c.gradient(0, 0, 1280, 720, lighten(acc, .08), darken(acc, .5), angle=45)
    c.glow(260, 140, 420, lighten(acc, .4), alpha=70)
    c.poly([(520, 0), (1280, 0), (1280, 720), (430, 720)], (0, 0, 0), alpha=40)
    c.image_poly(d.wide, [(600, 70), (1230, 70), (1170, 600), (540, 600)], focus=(.5, .3),
                 shadow=(50, 0, 24, 120, (0, 0, 0)))
    c.circle(840, 335, 48, fill=WHITE, alpha=60)
    c.circle(840, 335, 48, outline=WHITE, ow=3)
    c.icon("play", 848, 335, 38, WHITE)
    c.image(d.poster, 1040, 400, 168, 252, r=12, border=4, border_color=WHITE, focus=(.5, .2),
            shadow=(36, 0, 16, 150, (0, 0, 0)))

    top_brand(c, d, x=60, y=34, size=18, accent=lighten(acc, .75))
    X = 60
    today = datetime.date.today()
    x = X
    x += c.chip(x, 118, "NEW EPISODE", 12, 30, 16, "extrabold", color=darken(acc, .5), fill=WHITE, sp=2) + 10
    c.chip(x, 118, f"OUT {today.strftime('%b %d').upper()}", 12, 30, 16, "bold", color=WHITE, outline=WHITE, ow=1.5, sp=1.5)
    unit = {"Episodes": "EP", "Chapters": "CH"}.get(d.m.unit, "")
    big = f"{unit} {d.eps}" if (unit and d.eps) else "NEW"
    bs = 150 if len(big) <= 6 else 110
    c.text(X - 4, 150, big, bs, "extrabold", WHITE, lh=1, shadow=(0, 6, 18, 90, (0, 0, 0)))
    size, tl = c.fit(d.title.upper(), 440, 110, 40, 22, "extrabold", lh=1.1, max_lines=2)
    ty = 150 + bs * 1.0 + 14
    c.lines(X, ty, tl, size, "extrabold", WHITE, lh=1.1)
    y = ty + len(tl) * size * 1.1 + 12
    c.icon("clock", X + 8, y + 11, 15, lighten(acc, .75))
    c.text(X + 26, y, "AVAILABLE NOW" if not d.status else d.status.upper(), 12.5, "bold", lighten(acc, .8), lh=1.7, sp=1.5)
    y += 40
    c.rect(X, y, 200, 50, WHITE, r=25)
    c.icon("play", X + 38, y + 25, 15, darken(acc, .4))
    c.text(X + 60, y + 13, d.cta + " NOW", 14, "extrabold", darken(acc, .4), lh=1.4, sp=1)
