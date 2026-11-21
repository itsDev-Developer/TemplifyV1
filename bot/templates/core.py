"""The four original layouts: Series Split, Anime Card, Diamond, Polaroid."""
from __future__ import annotations

from ..draw import darken, lighten
from . import template

WHITE = (255, 255, 255)
INK = (20, 20, 24)
GRAY = (140, 144, 156)


def brand_logo(c, d, x, y, size=16, dark=(61, 61, 72), weight="extrabold", accent=None):
    """'NOVA FLIX' wordmark: first part dark, last part in the accent colour. Returns its width."""
    up_a, up_b = d.brand_a.upper(), d.brand_b.upper()
    a = up_a + d.brand_sep if up_a else ""
    wa = c.tw(a, size, weight) if a else 0
    if a:
        c.text(x, y, a, size, weight, dark)
    wb = c.text(x + wa, y, up_b, size, weight, accent or d.accent)
    return wa + wb


# ------------------------------------------------------------------ Series Split
def split_layout(c, d, manga=False):
    acc = d.accent
    c.rect(0, 0, 1280, 720, (236, 236, 242))

    # right side: faded copy of the art + glass veil
    c.image(d.wide, 576, 0, 704, 720, mode="smart", blur=3, focus=(.5, .5))
    c.rect(576, 0, 704, 720, (244, 244, 250), alpha=228)

    # left side: portrait art with accent fade and promo text
    c.image(d.poster, 0, 0, 576, 720, mode="smart", focus=(.5, .4))
    c.gradient(0, 230, 576, 490, darken(acc, .25), darken(acc, .25), a1=0, a2=240)
    c.para(248, 631, 214, d.promo.upper(), 7.8, "bold", WHITE, lh=1.95, max_lines=4)
    c.rect(459, 633, 2, 52, WHITE)
    words = [w for w in (d.brand_a, d.brand_b) if w] if d.brand_a else [d.brand]
    for i, w in enumerate(words[:2]):
        c.text(475, 633 + i * 23, w.upper(), 21, "extrabold", WHITE, lh=1.1)

    # header
    lw = brand_logo(c, d, 636, 40)
    tag = d.tag("WHERE EVERY MANGA CHAPTER COMES TO LIFE" if manga else "THE HOME OF COUNTLESS SERIES ADVENTURES")
    tx = max(816, 636 + lw + 60)
    ts = 9.5
    while c.tw(tag, ts, "bold") > 1185 - tx and ts > 6:
        ts -= .5
    c.text(tx, 42, tag, ts, "bold", (138, 138, 152))
    for yy in (44, 52.5, 61):
        c.rect(1220, yy, 25, 4, INK, r=2)

    # title / synopsis / buttons flow
    X, WID = 636, 584
    size, tl = c.fit(d.title, WID, 132, 56, 30, "extrabold", lh=1.12, max_lines=2, sp=-.3)
    th = len(tl) * size * 1.12
    syn_h = 3 * 15.5 * 1.5
    gh = th + 10 + 2 + 24 + syn_h + 30 + 46
    top = 168 if manga else max(120, 372 - gh / 2)

    c.lines(X, top, tl, size, "extrabold", (20, 20, 24), lh=1.12, sp=-.3)
    ly = top + th + 10
    c.rect(X, ly, WID, 2, (20, 20, 40), alpha=70)
    n = len(c.clamp(d.synopsis, 15.5, "medium", WID, 3))
    c.para(X, ly + 24, WID, d.synopsis, 15.5, "medium", (75, 75, 88), lh=1.5, max_lines=3)
    by = ly + 24 + n * 15.5 * 1.5 + 30

    wa = c.tw(d.cta + " ", 15, "extrabold")
    wb = c.tw("NOW", 15, "extrabold")
    pw = wa + wb + 54
    c.rect(X, by, pw, 46, INK, r=23)
    c.text(X + 27, by + 11.5, d.cta + " ", 15, "extrabold", WHITE, lh=1.2)
    c.text(X + 27 + wa, by + 11.5, "NOW", 15, "extrabold", acc, lh=1.2)
    bx = X + pw + 16
    c.circle(bx + 23, by + 23, 23, fill=WHITE)
    c.icon("bookmark", bx + 23, by + 23, 19, INK)

    if manga:
        c.rect(X, by + 62, 594, 1.5, (20, 20, 40), alpha=30)
        c.dots(913, 488, 3, 1, 15, 0, 3, INK, pick=lambda i, j: INK if i == 1 else (200, 200, 208))
        g = d.gallery(3)
        c.image(g[1], 730, 522, 112, 112, r=14, focus=(.5, .3), shadow=(10, 0, 3, 40, (0, 0, 0)))
        c.image(g[2], 1014, 522, 112, 112, r=14, focus=(.5, .3), shadow=(10, 0, 3, 40, (0, 0, 0)))
        c.image(g[0], 860, 510, 136, 136, r=18, focus=(.5, .25), border=3, border_color=acc,
                shadow=(14, 0, 5, 60, (0, 0, 0)))
        c.rect(758, 660, 340, 48, (24, 24, 28), r=24)
        c.icon("home", 792, 685, 21, WHITE)
        c.icon("search", 860, 685, 20, WHITE)
        c.icon("heart", 995, 686, 21, WHITE)
        c.circle(1007, 675, 7.5, fill=acc)
        c.text(1007, 670.5, "99", 6.5, "bold", WHITE, align="m", lh=1.4)
        c.icon("share", 1064, 685, 20, WHITE)
        c.circle(928, 659, 19, fill=acc)
        c.circle(928, 659, 19, outline=WHITE, ow=2)
        c.icon("plus", 928, 659, 19, WHITE)
    else:
        c.rect(758, 645, 340, 56, (0, 0, 0), r=28)
        for name, cx in (("home", 815), ("search", 872), ("user", 985), ("share", 1041)):
            c.icon(name, cx, 673, 22, WHITE)
        c.circle(928, 673, 19, fill=acc)
        c.circle(928, 673, 19, outline=WHITE, ow=2)
        c.icon("plus", 928, 673, 19, WHITE)


@template("split", "Series Split", "#7c3aed", "Series")
def split(c, d):
    split_layout(c, d, manga=False)


# ------------------------------------------------------------------ Anime Card
@template("card", "Anime Card", "#7c3aed", "Anime")
def card(c, d):
    acc = d.accent
    c.rect(0, 0, 1280, 720, WHITE)

    # outlined ghost brand behind everything
    ghost = d.brand_up.replace(" ", "")
    size = min(176, 940 / max(c.tw(ghost, 100, "extrabold"), 1) * 100)
    c.text(290, 751 - size * .98, ghost, size, "extrabold", fill=None, outline=(236, 236, 241), ow=1.6, lh=1)
    c.rect(0, 698, 1280, 22, acc)

    c.poly([(832, 0), (1082, 0), (987, 330)], (221, 226, 238))
    c.poly([(1048, 0), (1280, 0), (1280, 325)], acc)

    c.rect(34, 108, 13, 505, acc, r=6.5)
    for i, g in enumerate(d.genres[:2]):
        c.vtext(66 + i * 26, 111, g[:9], 11.5, "bold", INK, 15.5)
    gray = (186, 186, 194)
    c.dots(128, 183, 6, 5, 14, 16, 3.2, gray, pick=lambda i, j: (acc if i >= 3 else gray) if (i + j) % 2 == 0 else None)

    # left column (flow layout, centred vertically)
    X, WID = 150, 670
    meta = " • ".join(x for x in ((f"YEAR {d.year}" if d.year else ""), d.eps_long.upper()) if x)
    size, tl = c.fit(d.title.upper(), WID, 128, 56, 30, "extrabold", lh=1.1, max_lines=2, sp=-.6)
    th = len(tl) * size * 1.1
    studio_h = 34 if d.studio else 0
    gh = 20 + 16 + th + studio_h + 28 + 51
    y = 400 - gh / 2
    c.circle(X + 4.5, y + 10, 4.5, fill=acc)
    c.text(X + 20, y, meta, 17, "bold", (91, 91, 104), lh=1.2)
    y += 36
    c.two_tone(X, y, tl, size, "extrabold", acc, GRAY, lh=1.1, sp=-.6)
    y += th
    if d.studio:
        c.text(X, y + 8, d.studio.upper()[:34], 17, "bold", (35, 35, 43), lh=1.2)
        y += studio_h
    y += 28
    c.rect(X, y, 131, 51, acc, r=25.5)
    c.text(X + 65.5, y + 14, d.cta, 17, "bold", WHITE, align="m", lh=1.2)
    c.rect(X + 155, y + 11, 4, 28, (6, 182, 212))
    c.circle(X + 184, y + 25, 4.5, fill=(245, 158, 11))
    c.text(X + 198, y + 14, d.status.upper(), 17, "bold", (35, 35, 43), lh=1.2)

    c.image(d.poster, 885, 88, 336, 504, r=40, border=8, focus=(.5, .2), shadow=(36, 0, 22, 90, (40, 30, 70)))


# ------------------------------------------------------------------ Polaroid info panel
def info_layout(c, d, nav_x=(105, 279, 448, 608), text_w=480, dark=False, logo=False):
    """Left column of the AniCruise-style layout. dark=True swaps it to a night theme; logo=True prints the art logo
    (when there is one) instead of the two-tone text title."""
    acc = d.accent
    pale = darken(acc, .7) if dark else lighten(acc, .93)
    INK = WHITE if dark else globals()["INK"]
    muted, body, foot = ((150, 150, 168), (226, 226, 236), (130, 130, 146)) if dark else ((154, 154, 166), (27, 27, 34), (163, 163, 174))
    dots = (70, 70, 86) if dark else (201, 201, 209)
    lg = d.logo_for(not dark) if logo else None
    c.poly([(565, -31), (710, 114), (565, 259), (420, 114)], pale)
    c.poly([(118, 465), (293, 640), (118, 815), (-57, 640)], pale)
    c.dots(602, 120, 8, 4, 16, 15, 1.8, dots)
    c.dots(1168, 518, 7, 4, 16, 15, 1.8, dots)
    c.poly([(38, 0), (76, 0), (76, 66), (57, 52), (38, 66)], acc)
    c.poly([(266, 0), (333, 0), (299.5, 51)], acc)
    for label, x in zip(("EPISODE", "HOME", "TRAILER", "DETAIL & MORE"), nav_x):
        c.text(x, 63, label, 13, "bold", INK, lh=1.5)
    c.rect(nav_x[1] + 4, 88, 34, 4, acc, r=2)

    X = 100
    size, tl = c.fit(d.title.upper(), text_w, 128, 56, 30, "extrabold", lh=1.1, max_lines=2, sp=-.4)
    th = 112 if lg is not None else len(tl) * size * 1.1
    desc_n = len(c.clamp(d.synopsis, 15.5, "medium", 470, 3))
    desc_h = desc_n * 15.5 * 1.74
    gh = 22 + 20 + th + 18 + 20 + 22 + desc_h + 28 + 48
    y = max(110, 380 - gh / 2)

    c.rect(X + 4, y + 2, 16, 16, acc, r=3.5)
    brand_logo(c, d, X + 38, y - 1, size=16, dark=INK, weight="bold")
    y += 42
    if lg is not None:
        k = min(text_w / lg.width, 100 / lg.height)
        c.cutout(lg, X, y, lg.width * k, lg.height * k)
    else:
        c.lines(X, y, tl[:1], size, "extrabold", INK, lh=1.1, sp=-.4)
        if len(tl) > 1:
            c.lines(X, y + size * 1.1, tl[1:], size, "extrabold", acc, lh=1.1, sp=-.4)
    y += th + 18

    parts = [p for p in (d.year, d.genre_line, d.eps_short, d.type_label) if p]
    xx = X
    for i, p in enumerate(parts):
        if i:
            c.text(xx + 4, y, "|", 14.5, "bold", INK, lh=1.3)
            xx += 16
        xx += c.text(xx, y, p, 14.5, "bold", muted, lh=1.3)
    y += 28
    c.rect(X, y, 145, 2, acc)
    c.dots(X + 156, y + 1, 5, 1, 12, 0, 2.5, acc)
    y += 24
    c.para(X, y, 470, d.synopsis, 15.5, "medium", body, lh=1.74, max_lines=3)
    y += desc_h + 28

    sub = c.piece(168, 48)
    sub.gradient(0, 0, 168, 48, acc, darken(acc, .3), angle=0)
    c.place(sub, X, y, r=24)
    c.text(X + 84, y + 14, "DOWNLOAD NOW", 12, "bold", WHITE, align="m", lh=1.4)
    c.rect(X + 182, y, 48, 48, acc, r=14)
    c.icon("download", X + 206, y + 24, 22, WHITE)
    c.poly([(X + 253, y + 15), (X + 262, y + 24), (X + 253, y + 33), (X + 244, y + 24)], acc)

    c.rect(98, 649, 3, 24, acc)
    c.text(113, 650, d.brand_up, 14.5, "bold", foot, lh=1.4)


@template("polaroid", "Polaroid", "#06b6d4", "Anime")
def polaroid(c, d):
    c.rect(0, 0, 1280, 720, WHITE)
    info_layout(c, d, nav_x=(105, 279, 425, 557), text_w=520)
    g = d.gallery(4)
    cards = [(g[2], "CARD 01", "SCENE", (858, 205), 8), (g[1], "CARD 02", "OPERATOR FILE", (1058, 305), -7),
             (g[0], "CARD 03", "MAIN PROFILE", (912, 500), -3)]
    for i, (im, label, sub_label, (cx, cy), rot) in enumerate(cards):
        p = c.piece(340, 430)
        p.rect(0, 0, 340, 430, WHITE)
        p.image(im, 10, 10, 320, 330, focus=(.5, .22))
        p.rect(298, 22, 30, 19, (68, 68, 72), r=5)
        p.text(313, 24, f"0{i + 1}", 11, "bold", WHITE, align="m", lh=1.3)
        p.rect(10, 357, 5, 20, d.accent)
        p.text(26, 355, label, 17, "extrabold", INK, lh=1.3)
        p.rect(284, 394, 26, 3, d.accent, r=1.5)
        p.text(310, 399, d.brand_up[:14], 8.5, "bold", (138, 138, 150), align="r", lh=1.3)
        p.text(310, 410, sub_label, 8.5, "bold", (138, 138, 150), align="r", lh=1.3)
        c.place(p, cx - 170, cy - 215, rot=rot, shadow=(34, 0, 14, 70, (0, 0, 0)))
