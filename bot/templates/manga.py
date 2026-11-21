"""The two Manga Cruise layouts."""
from __future__ import annotations

from ..draw import darken, lighten, mix
from . import template
from .core import WHITE, split_layout


@template("manga_cover", "Manga Cruise · Synopsis", "#b0692a", "Manga")
def manga_cover(c, d):
    acc = d.accent
    deep = darken(acc, .62)
    c.rect(0, 0, 1280, 720, (238, 238, 241))

    # right: big art
    c.image(d.poster, 572, 0, 708, 720, mode="smart", focus=(.5, .3))
    c.gradient(572, 0, 708, 130, (0, 0, 0), (0, 0, 0), a1=150, a2=0)
    c.text(752, 31, d.brand, 24, "mediumitalic", WHITE, lh=1.3)
    bw = c.tw(d.brand, 24, "mediumitalic")
    c.text(752 + bw + 14, 40, d.tag("THE COMPLETE ENTERTAINMENT EXPERIENCE"), 8.5, "bold", WHITE, lh=1.3)
    c.rect(750, 65, 490, 1.4, WHITE, alpha=190)

    # left: brown panel over a blurred copy of the art
    c.image(d.poster, 90, 0, 482, 720, mode="cover", blur=7, focus=(.5, .3))
    c.rect(90, 0, 482, 720, deep, alpha=222)
    c.gradient(90, 0, 482, 720, acc, deep, a1=70, a2=0)

    # left strip: logo dot, two thumbnails, small logo
    g = d.gallery(3)
    c.circle(45, 55, 26, fill=acc)
    c.image(g[1], 54, 78, 113, 113, r=14, border=2, border_color=WHITE, focus=(.5, .25))
    c.image(g[2], 54, 218, 113, 113, r=14, border=2, border_color=WHITE, focus=(.5, .25))
    c.rect(25, 660, 40, 30, WHITE)
    c.text(45, 666, "MANGA", 5.2, "bold", (30, 30, 30), align="m", lh=1.2)
    c.text(45, 673, "CRUISE", 5.2, "bold", (30, 30, 30), align="m", lh=1.2)

    # header
    words = d.brand.split() if len(d.brand.split()) > 1 else [d.brand]
    if len(words) > 1:
        c.text(185, 38, words[0], 26, "mediumitalic", WHITE, lh=1.1)
        c.text(185, 66, " ".join(words[1:]), 26, "mediumitalic", WHITE, lh=1.1)
        tx = 185 + max(c.tw(words[0], 26, "mediumitalic"), c.tw(" ".join(words[1:]), 26, "mediumitalic")) + 14
    else:
        c.text(185, 48, d.brand, 26, "mediumitalic", WHITE, lh=1.1)
        tx = 185 + c.tw(d.brand, 26, "mediumitalic") + 14
    tag = d.tag("COUNTLESS STORIES, ONE PERFECT DESTINATION")
    ts = 8.5
    while c.tw(tag, ts, "bold") > 566 - tx and ts > 5.5:
        ts -= .25
    c.text(tx, 44, tag, ts, "bold", WHITE, lh=1.3)
    c.rect(185, 103, 381, 1.4, WHITE, alpha=200)

    # synopsis
    c.text(331, 128, "SYNOPSIS", 17, "bold", WHITE, align="m", lh=1.3, sp=.3)
    sw = c.tw("SYNOPSIS", 17, "bold", .3)
    for i in range(3):
        c.text(331 + sw / 2 + 10 + i * 5, 130, "›", 15, "bold", WHITE, lh=1.3, alpha=120 + i * 55)
    c.para(165, 166, 332, d.synopsis, 12, "medium", WHITE, lh=1.55, max_lines=4, align="m")
    sy = 252
    label = f"››› {d.brand}"
    lw = c.tw(label, 12.5, "mediumitalic")
    c.rect(331 - lw / 2 - 62, sy + 10, 52, 1, WHITE, alpha=200)
    c.rect(331 + lw / 2 + 10, sy + 10, 52, 1, WHITE, alpha=200)
    c.text(331, sy, label, 12.5, "mediumitalic", WHITE, align="m", lh=1.3)

    # glass card with title + genre chips
    c.rect(175, 441, 400, 244, (18, 26, 46), alpha=215, r=18)
    c.rect(175, 441, 400, 244, outline=(255, 255, 255), ow=1, r=18, alpha=40)
    size, tl = c.fit(d.title.upper(), 356, 70, 26, 14, "extrabold", lh=1.15, max_lines=2)
    ty = 463
    c.lines(375, ty, tl, size, "extrabold", WHITE, lh=1.15, align="m")
    y = ty + len(tl) * size * 1.15 + 14
    chips = (d.genres[:4] + [d.type_label.upper()])[:5]
    rows, cur, curw = [], [], 0
    for i, t in enumerate(chips):
        wd = c.tw(t, 9, "bold") + 28
        if cur and curw + wd + 10 > 340:
            rows.append((cur, curw))
            cur, curw = [], 0
        cur.append((i, t, wd))
        curw += wd + (10 if cur[:-1] else 0)
    if cur:
        rows.append((cur, curw))
    for row, rw in rows:
        x = 375 - rw / 2
        for i, t, wd in row:
            filled = i % 2 == 1
            c.rect(x, y, wd, 22, fill=(95, 100, 112) if filled else None, outline=WHITE, ow=1.1, r=11)
            c.text(x + wd / 2, y + 5, t, 9, "bold", WHITE, align="m", lh=1.2)
            x += wd + 10
        y += 32
    info = " • ".join(x for x in (d.status.upper(), d.eps_long.upper(), (f"RATING {d.score}" if d.score else "")) if x)
    c.text(375, y + 8, info, 9.5, "bold", (200, 205, 215), align="m", lh=1.3)
    c.text(375, y + 30, d.brand_up, 9, "bold", WHITE, align="m", lh=1.3, sp=.5)
    c.rect(233, 699, 284, 1.2, WHITE, alpha=170)


@template("manga_split", "Manga Cruise · Read Now", "#e0820d", "Manga")
def manga_split(c, d):
    split_layout(c, d, manga=True)
