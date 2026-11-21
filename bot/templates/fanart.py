"""Three templates built only from the best fanart.tv artwork: textless background, HD logo, textless poster,
character/clear art. Missing pieces degrade gracefully (text title instead of a logo, TMDB/AniList art instead of
fanart) so they never fail, but the bot only offers them when fanart.tv actually returned artwork."""
from __future__ import annotations

from ..draw import darken, lighten
from . import template
from .core import INK, WHITE, brand_logo, info_layout
from .modern import chips, num, stars

SHADOW = (18, 0, 8, 170, (0, 0, 0))


def logo_or_title(c, d, x, y, w, h, align="l", light=False):
    """HD logo contained in the box (title text if there is no logo). Returns the bottom y of what was drawn."""
    lg = d.logo_for(light)
    if lg is not None:
        k = min(w / lg.width, h / lg.height)
        lw, lh = lg.width * k, lg.height * k
        lx = x if align == "l" else x + (w - lw) / 2
        c.cutout(lg, lx, y + (h - lh) / 2, lw, lh, shadow=None if light else SHADOW)
        return y + (h + lh) / 2
    size, tl = c.fit(d.title.upper(), w, h, 64, 26, "extrabold", lh=1.05, max_lines=3, sp=-.5)
    th = len(tl) * size * 1.05
    c.lines(x if align == "l" else x + w / 2, y + (h - th) / 2, tl, size, "extrabold", (28, 24, 38) if light else WHITE, lh=1.05,
            align="l" if align == "l" else "m", sp=-.5, shadow=None if light else (0, 4, 14, 150, (0, 0, 0)))
    return y + (h + th) / 2


def meta_line(c, d, x, y, color=(222, 222, 230)):
    bits = [d.year, d.genres[0].title() if d.genres else "", d.eps_long or d.type_label.title()]
    s = "  •  ".join(b for b in bits if b)
    c.text(x, y, s, 14.5, "medium", color, lh=1.4)


def cta(c, d, x, y, acc, text=None):
    c.rect(x, y, 196, 50, acc, r=25)
    c.icon("play", x + 36, y + 25, 15, WHITE)
    c.text(x + 58, y + 13, text or f"{d.cta} NOW", 14, "extrabold", WHITE, lh=1.4, sp=1)
    c.rect(x + 210, y, 50, 50, fill=(255, 255, 255), alpha=34, r=25)
    c.rect(x + 210, y, 50, 50, outline=WHITE, ow=1.2, r=25, alpha=120)
    c.icon("bookmark", x + 235, y + 25, 15, WHITE)


def brand_top(c, d, x=80, y=40):
    brand_logo(c, d, x, y, 17, dark=WHITE, weight="bold")


def rating(c, d, x, y):
    if not d.score:
        return 0
    w = stars(c, x, y + 1, d.score, 15)
    c.text(x + w + 8, y, d.score, 15, "bold", WHITE, lh=1.4)
    return w + 8 + c.tw(d.score, 15, "bold")


# ------------------------------------------------------------------ 1. Logo Hero
@template("fa_hero", "Fanart · Logo Hero", "#e11d48", "Fanart")
def fa_hero(c, d):
    acc = d.accent
    c.image(d.art_bg, 0, 0, 1280, 720, mode="smart", focus=(.55, .3))
    c.gradient(0, 0, 1280, 720, (0, 0, 0), (0, 0, 0), a1=225, a2=0, angle=0)
    c.gradient(0, 440, 1280, 280, (0, 0, 0), (0, 0, 0), a1=0, a2=190)
    brand_top(c, d)
    c.chip(1090, 38, d.type_label.upper(), 10.5, 26, 14, "bold", color=WHITE, outline=WHITE, ow=1.2, sp=1.5)
    y = logo_or_title(c, d, 80, 150, 560, 250) + 26
    meta_line(c, d, 80, y)
    y += 40
    n = len(c.clamp(d.synopsis, 15, "regular", 500, 3))
    c.para(80, y, 500, d.synopsis, 15, "regular", (228, 228, 235), lh=1.6, max_lines=3,
           shadow=(0, 2, 8, 140, (0, 0, 0)))
    y += n * 15 * 1.6 + 26
    cta(c, d, 80, y, acc)
    rating(c, d, 360, y + 15)


# ------------------------------------------------------------------ 2. Poster Stage
@template("fa_poster", "Fanart · Poster Stage", "#0ea5e9", "Fanart")
def fa_poster(c, d):
    acc = d.accent
    c.image(d.art_bg, 0, 0, 1280, 720, mode="smart", blur=10, shade=(darken(acc, .22), 150))
    c.gradient(0, 0, 1280, 720, (0, 0, 0), (0, 0, 0), a1=170, a2=40, angle=0)
    c.glow(1010, 380, 330, acc, alpha=70)
    brand_top(c, d)
    c.image(d.art_poster, 842, 96, 340, 510, r=16, border=3, border_color=WHITE, focus=(.5, .2), rot=2.5,
            shadow=(48, 0, 22, 170, (0, 0, 0)))
    c.rect(868, 640, 288, 3, acc, r=2)
    y = logo_or_title(c, d, 80, 130, 560, 200) + 24
    chips(c, 80, y, d.genres[:3], 10.5, 26, 13, 8, 560, color=WHITE, outline=WHITE, ow=1.1, sp=.8)
    y += 46
    w = rating(c, d, 80, y)
    c.text(80 + (w + 16 if w else 0), y, " • ".join(p for p in (d.year, d.eps_long) if p), 14, "medium", (215, 215, 224), lh=1.4)
    y += 38
    n = len(c.clamp(d.synopsis, 14.5, "regular", 520, 4))
    c.para(80, y, 520, d.synopsis, 14.5, "regular", (226, 226, 234), lh=1.62, max_lines=4)
    y += n * 14.5 * 1.62 + 26
    cta(c, d, 80, y, acc)


# ------------------------------------------------------------------ 3. Character Spotlight
@template("fa_character", "Fanart · Character Spotlight", "#8b5cf6", "Fanart")
def fa_character(c, d):
    acc = d.accent
    deep = darken(acc, .55)
    c.image(d.art_bg, 0, 0, 1280, 720, mode="smart", shade=(deep, 175))
    c.gradient(0, 0, 1280, 720, deep, (0, 0, 0), a1=210, a2=120, angle=60)
    c.glow(900, 360, 380, lighten(acc, .25), alpha=60)
    # oversized outlined title behind the character
    word = (d.title.split(":")[0].split(" - ")[0]).upper()
    size = min(210, 1150 / max(c.tw(word, 100, "extrabold") / 100, 1))
    c.text(1280 - 40, 720 - size * 1.02, word, size, "extrabold", fill=None, outline=WHITE, ow=2, align="r",
           lh=1, alpha=70, sp=-3)
    art = d.art_cutout
    if art is not None:
        c.cutout(art, 640, 30, 620, 690, shadow=(40, -10, 10, 160, (0, 0, 0)))
    else:  # no transparent art for this title: tilted poster card instead
        c.image(d.art_poster, 860, 110, 320, 480, r=16, border=3, border_color=WHITE, focus=(.5, .2), rot=-4,
                shadow=(48, 0, 22, 170, (0, 0, 0)))
    brand_top(c, d)
    y = logo_or_title(c, d, 80, 140, 520, 220) + 24
    meta_line(c, d, 80, y, lighten(acc, .8))
    y += 40
    n = len(c.clamp(d.synopsis, 14.5, "regular", 460, 3))
    c.para(80, y, 460, d.synopsis, 14.5, "regular", (230, 230, 238), lh=1.62, max_lines=3)
    y += n * 14.5 * 1.62 + 26
    cta(c, d, 80, y, acc)
    if d.score:
        sc = num(d.score)
        if sc:
            c.text(80 + 290, y + 3, f"{sc:.1f}", 34, "extrabold", WHITE, lh=1.1)
            c.text(80 + 290 + c.tw(f"{sc:.1f}", 34, "extrabold") + 6, y + 22, "/ 10", 12, "bold", (200, 200, 215), lh=1.2)


# ------------------------------------------------------------------ AniCruise-style light/dark layouts
def _art_or_poster(c, d, box, rot=-4, dark=False):
    """Character/clear-art cutout overflowing its box; a tilted poster card when the title has no transparent art."""
    art = d.art_cutout
    x, y, w, h = box
    if art is not None:
        c.cutout(art, x, y, w, h, shadow=(40, 0, 16, 120 if not dark else 170, (0, 0, 0)))
        return True
    pw = min(w * .62, h * .62 * .667)
    c.image(d.art_poster, x + (w - pw) / 2, y + (h - pw * 1.5) / 2, pw, pw * 1.5, r=14, border=4, border_color=WHITE,
            focus=(.5, .2), rot=rot, shadow=(44, 0, 20, 150, (0, 0, 0)))
    return False


@template("fa_diamond", "Fanart · Diamond Light", "#d6005b", "Fanart")
def fa_diamond(c, d):
    acc = d.accent
    c.rect(0, 0, 1280, 720, WHITE)
    info_layout(c, d, nav_x=(105, 279, 448, 608), text_w=470, logo=True)
    cx, cy, hd = 898, 360, 312
    c.diamond(d.art_bg, cx, cy, hd, border=5, border_color=WHITE, focus=(.5, .4), shade=(acc, 190),
              shadow=(46, 0, 22, 70, (0, 0, 0)))
    c.poly([(1021, 61), (1032, 72), (1021, 83), (1010, 72)], acc)
    _art_or_poster(c, d, (630, 30, 540, 690))


@template("fa_diamond_dark", "Fanart · Diamond Night", "#a855f7", "Fanart")
def fa_diamond_dark(c, d):
    acc = d.accent
    c.rect(0, 0, 1280, 720, (14, 12, 22))
    c.image(d.art_bg, 560, 0, 720, 720, mode="smart", blur=14, shade=(darken(acc, .5), 205))
    c.gradient(0, 0, 760, 720, (14, 12, 22), (14, 12, 22), a1=255, a2=0, angle=0)
    info_layout(c, d, nav_x=(105, 279, 448, 608), text_w=470, dark=True, logo=True)
    cx, cy, hd = 898, 360, 312
    c.glow(cx, cy, 420, acc, alpha=90)
    c.diamond(d.art_bg, cx, cy, hd, border=4, border_color=lighten(acc, .35), focus=(.5, .4), shade=(darken(acc, .35), 150),
              shadow=(50, 0, 24, 160, (0, 0, 0)))
    c.poly([(1021, 61), (1032, 72), (1021, 83), (1010, 72)], lighten(acc, .3))
    _art_or_poster(c, d, (630, 30, 540, 690), dark=True)


@template("fa_frame", "Fanart · Frame Light", "#2563eb", "Fanart")
def fa_frame(c, d):
    acc = d.accent
    c.rect(0, 0, 1280, 720, WHITE)
    info_layout(c, d, nav_x=(105, 279, 448, 608), text_w=470, logo=True)
    fx, fy, fw, fh = 640, 120, 580, 500
    c.image(d.art_bg, fx, fy, fw, fh, r=40, mode="smart", focus=(.5, .35), shade=(acc, 150), border=6, border_color=WHITE,
            shadow=(46, 0, 22, 70, (0, 0, 0)))
    c.rect(fx - 18, fy + 28, 7, 120, acc, r=3.5)
    c.poly([(1180, 80), (1196, 96), (1180, 112), (1164, 96)], acc)
    _art_or_poster(c, d, (700, 10, 480, 710))


@template("fa_showcase", "Fanart · Showcase Night", "#f59e0b", "Fanart")
def fa_showcase(c, d):
    acc = d.accent
    c.rect(0, 0, 1280, 720, (12, 12, 18))
    c.image(d.art_bg, 0, 0, 1280, 720, mode="smart", blur=18, shade=(darken(acc, .6), 215))
    info_layout(c, d, nav_x=(105, 279, 448, 608), text_w=470, dark=True, logo=True)
    c.image(d.art_bg, 640, 120, 580, 330, r=26, mode="smart", focus=(.5, .35), border=3, border_color=lighten(acc, .4),
            shadow=(44, 0, 20, 170, (0, 0, 0)))
    c.image(d.art_poster, 668, 292, 200, 300, r=14, border=4, border_color=WHITE, focus=(.5, .2), rot=-3,
            shadow=(44, 0, 20, 180, (0, 0, 0)))
    art = d.art_cutout
    if art is not None:
        c.cutout(art, 880, 40, 380, 680, shadow=(40, 0, 16, 170, (0, 0, 0)))


# ------------------------------------------------------------------ Gen Banner (hidden: reached via the GEN BANNER button)
@template("banner", "Clean Banner", "#e11d48", "Fanart", hidden=True)
def banner(c, d):
    """Plain landscape banner: best backdrop, title/logo and one meta line. No UI furniture."""
    acc = d.accent
    c.image(d.art_bg, 0, 0, 1280, 720, mode="smart", focus=(.5, .3))
    c.gradient(0, 300, 1280, 420, (0, 0, 0), (0, 0, 0), a1=0, a2=215)
    c.gradient(0, 0, 1280, 160, (0, 0, 0), (0, 0, 0), a1=110, a2=0)
    brand_top(c, d)
    c.rect(80, 520, 64, 5, acc, r=2)
    y = logo_or_title(c, d, 80, 540, 640, 120) + 4
    meta_line(c, d, 80, 672)
