"""Illustrated / editorial layouts: Manga Panel, Retro Ticket, Mosaic, Magazine Cover, Sakura Soft."""
from __future__ import annotations

import hashlib
import math

from ..draw import darken, lighten
from . import template
from .core import INK, WHITE, brand_logo
from .modern import chips, num, stars


def scale_poly(pts, dx, dy):
    """Shrink a polygon about its centroid by dx, dy units on each side (for borders)."""
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    w = max(p[0] for p in pts) - min(p[0] for p in pts)
    h = max(p[1] for p in pts) - min(p[1] for p in pts)
    sx, sy = 1 - 2 * dx / w, 1 - 2 * dy / h
    return [(cx + (x - cx) * sx, cy + (y - cy) * sy) for x, y in pts]


# ------------------------------------------------------------------ Manga Panel
@template("panel", "Manga Panel", "#e11d48", "Manga")
def panel(c, d):
    acc = d.accent
    paper, black = (250, 247, 241), (12, 12, 14)
    c.rect(0, 0, 1280, 720, paper)
    g = d.gallery(3)
    panels = [
        ([(36, 36), (700, 36), (626, 486), (36, 486)], g[0], (.5, .2), False),
        ([(724, 36), (1244, 36), (1244, 262), (686, 262)], g[1], (.5, .35), True),
        ([(676, 286), (1244, 286), (1244, 486), (640, 486)], g[2], (.5, .3), True),
    ]
    for pts, im, focus, gray in panels:
        c.poly(pts, black)
        c.image_poly(im, scale_poly(pts, 6, 6), focus=focus, gray=gray)
    c.poly([(0, 512), (1280, 488), (1280, 720), (0, 720)], black)
    c.poly([(0, 502), (1280, 478), (1280, 490), (0, 514)], acc)
    c.dots(930, 650, 18, 4, 18, 16, 2.4, acc, alpha=150)

    X = 56
    size, tl = c.fit(d.title.upper(), 820, 82, 62, 28, "extrabold", lh=1.04, max_lines=2)
    ty = 536
    c.lines(X, ty, tl, size, "extrabold", WHITE, lh=1.04)
    y = ty + len(tl) * size * 1.04 + 8
    c.text(X, y, " | ".join(p for p in (d.genre_line, d.year, d.eps_long.upper()) if p), 14, "bold", acc, lh=1.4, sp=1)
    c.para(X, y + 28, 760, d.synopsis, 12.5, "regular", (200, 200, 205), lh=1.5, max_lines=2)

    c.rect(924, 530, 300, 92, WHITE, r=30)
    c.poly([(962, 616), (948, 664), (1012, 618)], WHITE)
    c.text(1074, 552, d.cta + " NOW!", 30, "extrabold", black, align="m", lh=1.2)
    c.starburst(1166, 262, 76, 54, 14, acc, rot=8)
    c.starburst(1166, 262, 76, 54, 14, black, rot=8, alpha=0)
    c.text(1166, 240, "NEW", 28, "extrabold", WHITE, align="m", lh=1.4)


# ------------------------------------------------------------------ Retro Ticket
@template("ticket", "Retro Ticket", "#c2410c")
def ticket(c, d):
    acc = d.accent
    paper, ink = (246, 236, 214), (52, 36, 28)
    c.gradient(0, 0, 1280, 720, (48, 36, 32), (20, 15, 15), angle=60)
    x0, y0, w, h, px = 70, 96, 1140, 528, 392
    top_bg = c.im.getpixel((c.u(px), c.u(y0 - 6)))
    bot_bg = c.im.getpixel((c.u(px), c.u(y0 + h + 6)))
    sheet = c.piece(w, h)
    sheet.rect(0, 0, w, h, paper)
    c.place(sheet, x0, y0, r=26, shadow=(60, 0, 24, 170, (0, 0, 0)))
    c.circle(px, y0, 24, fill=top_bg)
    c.circle(px, y0 + h, 24, fill=bot_bg)
    c.rect(x0 + 16, y0 + 16, w - 32, h - 32, outline=ink, ow=1.4, r=16, alpha=80)
    for yy in range(y0 + 40, y0 + h - 30, 14):
        c.circle(px, yy, 2.2, fill=ink, alpha=110)

    # stub
    c.image(d.poster, 108, 142, 244, 336, r=4, border=4, border_color=ink, focus=(.5, .2))
    seed = hashlib.md5(d.title.encode()).digest() * 4
    x, i = 108, 0
    while x < 350:
        bw = 1 + seed[i % len(seed)] % 4
        if i % 2 == 0:
            c.rect(x, 504, bw, 54, ink)
        x += bw + 1.4
        i += 1
    c.text(230, 564, f"NO. {abs(hash(d.title)) % 900000 + 100000}", 10, "bold", ink, align="m", lh=1.4, sp=2, alpha=190)

    # main
    X, R = 436, 1166
    c.text(X, 130, "ADMIT ONE", 15, "bold", acc, lh=1.4, sp=8)
    c.text(R, 132, d.brand_up, 12, "bold", ink, align="r", lh=1.4, sp=3, alpha=170)
    c.rect(X, 166, R - X, 2.4, ink, alpha=200)
    c.rect(X, 173, R - X, 1, ink, alpha=140)
    size, tl = c.fit(d.title.upper(), R - X, 168, 70, 30, "extrabold", lh=1.04, max_lines=3)
    c.lines(X, 192, tl, size, "extrabold", ink, lh=1.04)
    y = 192 + len(tl) * size * 1.04 + 8
    sub = f"A {d.studio.upper()} PRODUCTION" if d.studio else d.type_label.upper()
    c.text(X, y, sub, 15, "mediumitalic", (110, 84, 66), lh=1.4, sp=1)

    fields = [("YEAR", d.year or "—"), (d.m.unit.upper() or "TYPE", d.eps or d.type_label[:8]), ("RATING", d.score or d.status[:8].upper() or "—")]
    fy = 408
    cw = (R - X) / 3
    for i, (lab, val) in enumerate(fields):
        fx = X + i * cw
        if i:
            c.rect(fx - 16, fy, 1.4, 70, ink, alpha=90)
        c.text(fx, fy, lab, 10.5, "bold", acc, lh=1.4, sp=2.5)
        c.text(fx, fy + 20, str(val), 40, "extrabold", ink, lh=1.1)
    c.rect(X, 496, R - X, 1.2, ink, alpha=110)
    c.para(X, 510, 560, d.synopsis, 12.5, "mediumitalic", (96, 74, 58), lh=1.55, max_lines=3)
    c.stamp(1086, 548, 52, [("ADMIT", 15, "extrabold"), ("ONE", 15, "extrabold")], acc, rot=-14)


# ------------------------------------------------------------------ Sakura Soft
@template("sakura", "Sakura Soft", "#ec4899", "Anime")
def sakura(c, d):
    acc = d.accent
    deep = darken(acc, .45)
    c.gradient(0, 0, 1280, 720, lighten(acc, .9), (226, 236, 255), angle=45)
    for x, y, r, a in [(120, 90, 46, 34), (300, 650, 72, 26), (1190, 650, 96, 30), (700, 56, 26, 44),
                       (1236, 170, 34, 36), (46, 430, 22, 44), (560, 694, 28, 38), (40, 40, 80, 20)]:
        c.circle(x, y, r, fill=acc, alpha=a)
    petals = [(180, 200, 15, 30), (540, 130, 12, -20), (610, 520, 14, 50), (90, 560, 11, 10), (1220, 420, 13, 70),
              (1000, 40, 12, -40), (640, 330, 10, 25), (250, 690, 12, -15), (1250, 60, 10, 35)]
    for cx, cy, s, rot in petals:
        pts = []
        for k in range(24):
            t = k / 24 * 2 * math.pi
            px, py = s * math.cos(t), s * .55 * math.sin(t)
            a = math.radians(rot)
            pts.append((cx + px * math.cos(a) - py * math.sin(a), cy + px * math.sin(a) + py * math.cos(a)))
        c.poly(pts, lighten(acc, .3), alpha=170)

    cx, cy, R = 930, 372, 262
    c.circle(cx, cy, R + 30, outline=acc, ow=2, alpha=120)
    c.circle(cx, cy, R + 58, outline=acc, ow=1.2, alpha=60)
    c.image(d.poster, cx - R, cy - R, 2 * R, 2 * R, r=R, border=10, border_color=WHITE, focus=(.5, .22),
            shadow=(54, 0, 24, 100, deep))
    if d.score:
        c.circle(cx - R + 34, cy - R + 78, 48, fill=acc)
        c.circle(cx - R + 34, cy - R + 78, 48, outline=WHITE, ow=4)
        c.text(cx - R + 34, cy - R + 56, d.score, 26, "extrabold", WHITE, align="m", lh=1.3)
        c.text(cx - R + 34, cy - R + 88, "SCORE", 8.5, "bold", WHITE, align="m", lh=1.3, sp=1.5)

    c.frost(70, 118, 570, 484, r=36, blur=18, tint=WHITE, ta=170, border=140)
    X, W = 112, 486
    c.icon("heart", X + 8, 160, 18, acc)
    brand_logo(c, d, X + 26, 148, 15, dark=deep, weight="bold", accent=acc)
    size, tl = c.fit(d.title, W, 134, 50, 26, "bold", lh=1.08, max_lines=3, sp=-.3)
    y = 190
    c.lines(X, y, tl, size, "bold", (92, 42, 78), lh=1.08, sp=-.3)
    y += len(tl) * size * 1.08 + 16
    y = chips(c, X, y, d.genres[:3] + ([d.year] if d.year else []), 11, 28, 15, 8, W,
              color=darken(acc, .15), fill=lighten(acc, .82)) + 20
    n = len(c.clamp(d.synopsis, 15, "regular", W, 3))
    c.para(X, y, W, d.synopsis, 15, "regular", (124, 98, 120), lh=1.6, max_lines=3)
    y += n * 15 * 1.6 + 26
    sub = c.piece(200, 54)
    sub.gradient(0, 0, 200, 54, acc, lighten(acc, .25), angle=0)
    c.place(sub, X, y, r=27)
    c.text(X + 100, y + 15, d.cta.title() + " Now", 15, "bold", WHITE, align="m", lh=1.4)
    c.circle(X + 200 + 14 + 27, y + 27, 27, fill=WHITE)
    c.circle(X + 200 + 14 + 27, y + 27, 27, outline=acc, ow=1.6)
    c.icon("heart", X + 200 + 14 + 27, y + 28, 20, acc)
