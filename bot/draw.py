"""Pillow drawing toolkit used by every template.

All coordinates are *design units* on a 1280x720 canvas. `Canvas.s` scales them to real pixels
(1.5 -> 1920x1080), so templates never care about the output resolution.
Shapes are anti-aliased through supersampled masks. Only Pillow + stdlib are used.
"""
from __future__ import annotations

import io
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import fonts

W, H = 1280, 720


# ----------------------------------------------------------------------------- colours
def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(a, b, t: float):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def lighten(c, t: float):
    return mix(c, (255, 255, 255), t)


def darken(c, t: float):
    return mix(c, (0, 0, 0), t)


def _lut(alpha: int):
    return [int(i * alpha / 255) for i in range(256)]


# ----------------------------------------------------------------------------- icons (drawn at n x n)
def _ic_home(d, n):
    p = [(.5, .08), (.04, .52), (.2, .52), (.2, .92), (.42, .92), (.42, .64), (.58, .64), (.58, .92), (.8, .92), (.8, .52), (.96, .52)]
    d.polygon([(x * n, y * n) for x, y in p], fill=255)


def _ic_search(d, n):
    d.ellipse((.1 * n, .1 * n, .68 * n, .68 * n), outline=255, width=int(.11 * n))
    d.line((.6 * n, .6 * n, .9 * n, .9 * n), fill=255, width=int(.13 * n))
    d.ellipse((.84 * n - .065 * n, .84 * n - .065 * n, .9 * n + .065 * n, .9 * n + .065 * n), fill=255)


def _ic_plus(d, n):
    d.rounded_rectangle((.44 * n, .12 * n, .56 * n, .88 * n), radius=.05 * n, fill=255)
    d.rounded_rectangle((.12 * n, .44 * n, .88 * n, .56 * n), radius=.05 * n, fill=255)


def _ic_user(d, n):
    d.ellipse((.3 * n, .06 * n, .7 * n, .46 * n), fill=255)
    d.pieslice((.08 * n, .54 * n, .92 * n, 1.38 * n), 180, 360, fill=255)


def _ic_share(d, n):
    pts = [(.78, .2), (.22, .5), (.78, .8)]
    d.line([(pts[0][0] * n, pts[0][1] * n), (pts[1][0] * n, pts[1][1] * n), (pts[2][0] * n, pts[2][1] * n)], fill=255, width=int(.08 * n))
    for x, y in pts:
        r = .15 * n
        d.ellipse((x * n - r, y * n - r, x * n + r, y * n + r), fill=255)


def _ic_bookmark(d, n):
    p = [(.22, .06), (.78, .06), (.78, .94), (.5, .7), (.22, .94)]
    d.polygon([(x * n, y * n) for x, y in p], fill=255)


def _ic_heart(d, n):
    d.ellipse((.06 * n, .14 * n, .54 * n, .62 * n), fill=255)
    d.ellipse((.46 * n, .14 * n, .94 * n, .62 * n), fill=255)
    d.polygon([(.09 * n, .45 * n), (.91 * n, .45 * n), (.5 * n, .93 * n)], fill=255)


def _ic_download(d, n):
    d.rounded_rectangle((.43 * n, .08 * n, .57 * n, .58 * n), radius=.04 * n, fill=255)
    d.polygon([(.2 * n, .45 * n), (.8 * n, .45 * n), (.5 * n, .76 * n)], fill=255)
    d.rounded_rectangle((.14 * n, .84 * n, .86 * n, .95 * n), radius=.05 * n, fill=255)


def _ic_play(d, n):
    d.polygon([(.26 * n, .12 * n), (.92 * n, .5 * n), (.26 * n, .88 * n)], fill=255)


def _ic_burger(d, n):
    for y in (.16, .44, .72):
        d.rounded_rectangle((.04 * n, y * n, .96 * n, (y + .13) * n), radius=.06 * n, fill=255)


def _ic_star(d, n):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = .5 if i % 2 == 0 else .21
        pts.append((n * (.5 + r * math.cos(a)), n * (.54 + r * math.sin(a))))
    d.polygon(pts, fill=255)


def _ic_check(d, n):
    d.line([(.14 * n, .54 * n), (.4 * n, .8 * n), (.88 * n, .24 * n)], fill=255, width=int(.14 * n), joint="curve")


def _ic_clock(d, n):
    d.ellipse((.06 * n, .06 * n, .94 * n, .94 * n), outline=255, width=int(.1 * n))
    d.line([(.5 * n, .24 * n), (.5 * n, .52 * n), (.7 * n, .62 * n)], fill=255, width=int(.09 * n), joint="curve")


ICONS = {
    "home": _ic_home, "search": _ic_search, "plus": _ic_plus, "user": _ic_user, "share": _ic_share,
    "bookmark": _ic_bookmark, "heart": _ic_heart, "download": _ic_download, "play": _ic_play,
    "burger": _ic_burger, "star": _ic_star, "check": _ic_check, "clock": _ic_clock,
}


# ----------------------------------------------------------------------------- canvas
class Canvas:
    def __init__(self, scale: float = 1.5, bg=(255, 255, 255), accent=(124, 58, 237)):
        self.s = float(scale)
        self.w, self.h = round(W * self.s), round(H * self.s)
        self.im = Image.new("RGB", (self.w, self.h), bg)
        self.accent = accent
        self._d = ImageDraw.Draw(self.im)

    # ---- units
    def u(self, v: float) -> int:
        return int(round(v * self.s))

    def _px(self, x, y, w, h):
        x0, y0 = round(x * self.s), round(y * self.s)
        return x0, y0, round((x + w) * self.s) - x0, round((y + h) * self.s) - y0

    # ---- masks
    @staticmethod
    def _mask(pw: int, ph: int, fn):
        area = pw * ph
        k = 4 if area < 700_000 else 2 if area < 3_000_000 else 1
        m = Image.new("L", (pw * k, ph * k), 0)
        fn(ImageDraw.Draw(m), k)
        return m if k == 1 else m.resize((pw, ph), Image.LANCZOS)

    def _rr(self, pw, ph, r, ring=0):
        r = min(r, pw / 2, ph / 2)
        if r <= 0 and not ring:
            return Image.new("L", (pw, ph), 255)

        def fn(d, k):
            d.rounded_rectangle((0, 0, pw * k - 1, ph * k - 1), radius=max(r, 0) * k, fill=255)
            if ring:
                i = ring * k
                d.rounded_rectangle((i, i, pw * k - 1 - i, ph * k - 1 - i), radius=max(r - ring, 0) * k, fill=0)

        return self._mask(pw, ph, fn)

    def _fill(self, color, mask, px, py, alpha=255):
        if alpha < 255:
            mask = mask.point(_lut(alpha))
        self.im.paste(color, (px, py, px + mask.width, py + mask.height), mask)

    # ---- shapes
    def rect(self, x, y, w, h, fill=None, alpha=255, r=0, outline=None, ow=1):
        px, py, pw, ph = self._px(x, y, w, h)
        if pw <= 0 or ph <= 0:
            return
        rr = self.u(r)
        if fill is not None:
            if rr == 0 and alpha == 255:
                self._d.rectangle((px, py, px + pw - 1, py + ph - 1), fill=fill)
            else:
                self._fill(fill, self._rr(pw, ph, rr), px, py, alpha)
        if outline is not None:
            self._fill(outline, self._rr(pw, ph, rr, ring=max(1, self.u(ow))), px, py, alpha)

    def ellipse(self, x, y, w, h, fill=None, alpha=255, outline=None, ow=1):
        px, py, pw, ph = self._px(x, y, w, h)
        if pw <= 0 or ph <= 0:
            return
        if fill is not None:
            self._fill(fill, self._mask(pw, ph, lambda d, k: d.ellipse((0, 0, pw * k - 1, ph * k - 1), fill=255)), px, py, alpha)
        if outline is not None:
            b = max(1, self.u(ow))

            def ring(d, k):
                d.ellipse((0, 0, pw * k - 1, ph * k - 1), fill=255)
                d.ellipse((b * k, b * k, (pw - b) * k - 1, (ph - b) * k - 1), fill=0)

            self._fill(outline, self._mask(pw, ph, ring), px, py, alpha)

    def circle(self, cx, cy, r, **kw):
        self.ellipse(cx - r, cy - r, 2 * r, 2 * r, **kw)

    def poly(self, pts, fill, alpha=255):
        """pts in design units."""
        P = [(a * self.s, b * self.s) for a, b in pts]
        x0, y0 = int(math.floor(min(p[0] for p in P))), int(math.floor(min(p[1] for p in P)))
        x1, y1 = int(math.ceil(max(p[0] for p in P))), int(math.ceil(max(p[1] for p in P)))
        x0c, y0c, x1c, y1c = max(x0, 0), max(y0, 0), min(x1, self.w), min(y1, self.h)
        if x1c <= x0c or y1c <= y0c:
            return
        pw, ph = x1c - x0c, y1c - y0c
        self._fill(fill, self._mask(pw, ph, lambda d, k: d.polygon([((a - x0c) * k, (b - y0c) * k) for a, b in P], fill=255)), x0c, y0c, alpha)

    def line(self, x1, y1, x2, y2, w, fill, alpha=255):
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L * w / 2, dx / L * w / 2
        self.poly([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)], fill, alpha)

    def starburst(self, cx, cy, r1, r2, n, fill, rot=0, alpha=255):
        pts = []
        for i in range(n * 2):
            a = math.radians(rot) + i * math.pi / n
            r = r1 if i % 2 == 0 else r2
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        self.poly(pts, fill, alpha)

    def dots(self, x, y, cols, rows, gx, gy, r, color, alpha=255, pick=None):
        for j in range(rows):
            for i in range(cols):
                c = pick(i, j) if pick else color
                if c is not None:
                    self.circle(x + i * gx, y + j * gy, r, fill=c, alpha=alpha)

    def gradient(self, x, y, w, h, c1, c2, a1=255, a2=255, angle=90):
        """Linear gradient. angle: 90 = top->bottom, 0 = left->right, 45 = top-left->bottom-right."""
        px, py, pw, ph = self._px(x, y, w, h)
        if pw <= 0 or ph <= 0:
            return
        base = Image.linear_gradient("L")
        if angle == 90:
            g = base.resize((pw, ph), Image.BILINEAR)
        elif angle == 0:
            g = base.transpose(Image.ROTATE_90).resize((pw, ph), Image.BILINEAR)
        else:
            D = int(math.hypot(pw, ph)) + 2
            g = base.resize((D, D), Image.BILINEAR).rotate(90 - angle, resample=Image.BILINEAR)
            g = g.crop(((D - pw) // 2, (D - ph) // 2, (D - pw) // 2 + pw, (D - ph) // 2 + ph))
        mask = g.point([int(a1 + (a2 - a1) * i / 255) for i in range(256)])
        if c1 == c2:
            layer = c1
        else:
            layer = Image.composite(Image.new("RGB", (pw, ph), c2), Image.new("RGB", (pw, ph), c1), g)
        self.im.paste(layer, (px, py) if not isinstance(layer, tuple) else (px, py, px + pw, py + ph), mask)

    # ---- images
    def _fallback(self, pw, ph):
        top, bot = lighten(self.accent, .1), darken(self.accent, .55)
        g = Image.linear_gradient("L").resize((pw, ph), Image.BILINEAR)
        return Image.composite(Image.new("RGB", (pw, ph), bot), Image.new("RGB", (pw, ph), top), g)

    def _tile(self, im, pw, ph, focus=(.5, .3), mode="cover"):
        pw, ph = max(1, pw), max(1, ph)
        if im is None:
            return self._fallback(pw, ph)
        sw, sh = im.size
        mism = max((sw / sh) / (pw / ph), (pw / ph) / (sw / sh))
        if mode == "cover" or mism <= 1.95:
            return ImageOps.fit(im, (pw, ph), Image.LANCZOS, centering=focus)
        # very different aspect ratio: blurred copy fills the box, sharp image sits contained on top
        sm = (max(1, pw // 6), max(1, ph // 6))
        bg = ImageOps.fit(im, sm, Image.BILINEAR, centering=focus).filter(ImageFilter.GaussianBlur(max(2, max(sm) / 14)))
        bg = Image.blend(bg.resize((pw, ph), Image.BICUBIC), Image.new("RGB", (pw, ph), (0, 0, 0)), .22)
        fg = ImageOps.contain(im, (pw, ph), Image.LANCZOS)
        m = Image.new("L", fg.size, 255)
        f = max(2, int(min(fg.size) * .03))
        if fg.width < pw:   # feather the vertical edges so the sharp art melts into the blur
            for i in range(f):
                v = int(255 * (i + 1) / (f + 1))
                ImageDraw.Draw(m).line([(i, 0), (i, fg.height)], fill=v)
                ImageDraw.Draw(m).line([(fg.width - 1 - i, 0), (fg.width - 1 - i, fg.height)], fill=v)
        if fg.height < ph:  # same for the horizontal edges
            for i in range(f):
                v = int(255 * (i + 1) / (f + 1))
                ImageDraw.Draw(m).line([(0, i), (fg.width, i)], fill=v)
                ImageDraw.Draw(m).line([(0, fg.height - 1 - i), (fg.width, fg.height - 1 - i)], fill=v)
        bg.paste(fg, ((pw - fg.width) // 2, (ph - fg.height) // 2), m)
        return bg

    def image(self, im, x, y, w, h, r=0, focus=(.5, .3), mode="cover", blur=0, shade=None, rot=0,
              shadow=None, border=0, border_color=(255, 255, 255), alpha=255, gray=False):
        """Cover-fit `im` (PIL image or None) into the box. shade=(color, 0-255) overlays a tint.
        shadow=(blur, dx, dy, alpha, color) in design units. rot in degrees, counter-clockwise."""
        px, py, pw, ph = self._px(x, y, w, h)
        if pw <= 0 or ph <= 0:
            return
        b = self.u(border) if border else 0
        iw, ih = pw - 2 * b, ph - 2 * b
        tile = self._tile(im, iw, ih, focus, mode)
        if gray:
            tile = ImageOps.colorize(ImageOps.grayscale(tile), (0, 0, 0), (255, 255, 255))
        if blur:
            tile = tile.filter(ImageFilter.GaussianBlur(blur * self.s))
        if shade:
            tile = Image.blend(tile, Image.new("RGB", tile.size, shade[0]), shade[1] / 255)
        rr = self.u(r)
        if not (rr or b or rot or shadow or alpha < 255):
            self.im.paste(tile, (px, py))
            return
        if b:
            piece = Image.new("RGBA", (pw, ph), tuple(border_color) + (255,))
            piece.paste(tile, (b, b), self._rr(iw, ih, max(rr - b, 0)))
            piece.putalpha(self._rr(pw, ph, rr))
        else:
            piece = tile.convert("RGBA")
            piece.putalpha(self._rr(pw, ph, rr))
        if alpha < 255:
            piece.putalpha(piece.getchannel("A").point(_lut(alpha)))
        self._place(piece, px, py, rot, shadow)

    def piece(self, w, h):
        """Blank RGBA piece (design units) you can draw on with a sub-Canvas, then place() rotated."""
        sub = Canvas.__new__(Canvas)
        sub.s, sub.accent = self.s, self.accent
        sub.w, sub.h = round(w * self.s), round(h * self.s)
        sub.im = Image.new("RGB", (sub.w, sub.h), (255, 255, 255))
        sub._d = ImageDraw.Draw(sub.im)
        return sub

    def place(self, sub: "Canvas", x, y, r=0, rot=0, shadow=None):
        piece = sub.im.convert("RGBA")
        piece.putalpha(self._rr(sub.w, sub.h, self.u(r)))
        self._place(piece, round(x * self.s), round(y * self.s), rot, shadow)

    def _place(self, piece, px, py, rot=0.0, shadow=None):
        if shadow:
            blur, dx, dy, alpha, col = shadow
            bl = max(1, self.u(blur))
            pad = int(bl * 1.6) + max(abs(self.u(dx)), abs(self.u(dy))) + 2
            comp = Image.new("RGBA", (piece.width + 2 * pad, piece.height + 2 * pad), (0, 0, 0, 0))
            sh = Image.new("L", comp.size, 0)
            sh.paste(piece.getchannel("A"), (pad + self.u(dx), pad + self.u(dy)))
            sh = sh.filter(ImageFilter.GaussianBlur(bl / 2)).point(_lut(alpha))
            comp.paste(Image.new("RGBA", comp.size, tuple(col) + (255,)), (0, 0), sh)
            comp.alpha_composite(piece, (pad, pad))
            ox, oy = px - pad, py - pad
        else:
            comp, ox, oy = piece, px, py
        if rot:
            cx, cy = ox + comp.width / 2, oy + comp.height / 2
            comp = comp.rotate(rot, resample=Image.BICUBIC, expand=True)
            ox, oy = int(round(cx - comp.width / 2)), int(round(cy - comp.height / 2))
        self.im.paste(comp.convert("RGB"), (ox, oy), comp.getchannel("A"))

    def diamond(self, im, cx, cy, hd, border=0, border_color=(255, 255, 255), focus=(.5, .25), shade=None, shadow=None):
        """Image cropped to a diamond (rotated square) with half-diagonal `hd`."""
        px, py, pw, ph = self._px(cx - hd, cy - hd, 2 * hd, 2 * hd)
        tile = self._tile(im, pw, ph, focus)
        if shade:
            tile = Image.blend(tile, Image.new("RGB", tile.size, shade[0]), shade[1] / 255)
        b = self.u(border) * math.sqrt(2)

        def poly(inset):
            def fn(d, k):
                h = (pw / 2 - inset) * k
                cxk, cyk = pw * k / 2, ph * k / 2
                d.polygon([(cxk, cyk - h), (cxk + h, cyk), (cxk, cyk + h), (cxk - h, cyk)], fill=255)
            return self._mask(pw, ph, fn)

        piece = Image.new("RGBA", (pw, ph), tuple(border_color) + (255,))
        if border:
            piece.paste(tile, (0, 0), poly(b))
        else:
            piece.paste(tile, (0, 0))
        piece.putalpha(poly(0))
        self._place(piece, px, py, 0, shadow)

    def image_poly(self, im, pts, focus=(.5, .3), shade=None, shadow=None, gray=False):
        """Image cropped to a polygon (pts in design units), e.g. slanted comic panels."""
        P = [(a * self.s, b * self.s) for a, b in pts]
        x0, y0 = int(math.floor(min(p[0] for p in P))), int(math.floor(min(p[1] for p in P)))
        x1, y1 = int(math.ceil(max(p[0] for p in P))), int(math.ceil(max(p[1] for p in P)))
        pw, ph = x1 - x0, y1 - y0
        tile = self._tile(im, pw, ph, focus)
        if gray:
            tile = ImageOps.autocontrast(ImageOps.grayscale(tile), cutoff=2).convert("RGB")
        if shade:
            tile = Image.blend(tile, Image.new("RGB", tile.size, shade[0]), shade[1] / 255)
        piece = tile.convert("RGBA")
        piece.putalpha(self._mask(pw, ph, lambda d, k: d.polygon([((a - x0) * k, (b - y0) * k) for a, b in P], fill=255)))
        self._place(piece, x0, y0, 0, shadow)

    def glow(self, cx, cy, r, color, alpha=120):
        """Soft radial light (design units)."""
        px, py, pw, ph = self._px(cx - r, cy - r, 2 * r, 2 * r)
        g = ImageOps.invert(Image.radial_gradient("L")).resize((max(1, pw), max(1, ph)), Image.BICUBIC)
        g = g.point([int((i / 255) ** 1.7 * alpha) for i in range(256)])
        self.im.paste(color, (px, py, px + g.width, py + g.height), g)

    def frost(self, x, y, w, h, r=16, blur=18, tint=(255, 255, 255), ta=30, border=70):
        """Frosted-glass panel: blurs whatever is already drawn underneath."""
        px, py, pw, ph = self._px(x, y, w, h)
        reg = self.im.crop((px, py, px + pw, py + ph)).filter(ImageFilter.GaussianBlur(blur * self.s))
        reg = Image.blend(reg, Image.new("RGB", reg.size, tint), ta / 255)
        self.im.paste(reg, (px, py), self._rr(pw, ph, self.u(r)))
        if border:
            self.rect(x, y, w, h, outline=(255, 255, 255), ow=1.2, r=r, alpha=border)

    def stamp(self, cx, cy, r, lines, color, rot=-12, alpha=215, ow=3):
        """Round rubber-stamp: double ring + centred text lines [(text, size, weight)], rotated."""
        n = self.u(2 * r) + 8
        ring_w, in_off = max(1, self.u(ow)), self.u(8)

        def ring(d, k):
            d.ellipse((4 * k, 4 * k, (n - 4) * k, (n - 4) * k), outline=255, width=ring_w * k)
            d.ellipse(((4 + in_off) * k, (4 + in_off) * k, (n - 4 - in_off) * k, (n - 4 - in_off) * k), outline=255, width=max(1, k))

        m = self._mask(n, n, ring)
        d = ImageDraw.Draw(m)
        total = sum(sz * 1.25 for _, sz, _ in lines) * self.s
        y = n / 2 - total / 2
        for t, sz, wt in lines:
            f = self.font(wt, sz, t)
            asc, desc = f.getmetrics()
            box = sz * 1.25 * self.s
            d.text((n / 2 - f.getlength(t) / 2, y + (box - (asc + desc)) / 2 + asc), t, font=f, fill=255, anchor="ls")
            y += box
        m = m.rotate(rot, resample=Image.BICUBIC)
        self._fill(color, m, int(round(cx * self.s - n / 2)), int(round(cy * self.s - n / 2)), alpha)

    def cutout(self, im_rgba, x, y, w, h, shadow=None):
        """Place a transparent PNG (contain-fit, bottom aligned) in the box."""
        px, py, pw, ph = self._px(x, y, w, h)
        c = ImageOps.contain(im_rgba, (pw, ph), Image.LANCZOS)
        self._place(c, px + (pw - c.width) // 2, py + ph - c.height, 0, shadow)

    # ---- text
    def font(self, weight, size, text=""):
        return fonts.pick(weight, size * self.s, text)

    def _len(self, f, s, sp):
        if not sp:
            return f.getlength(s)
        return sum(f.getlength(ch) for ch in s) + sp * self.s * max(len(s) - 1, 0)

    def tw(self, s, size, weight="regular", sp=0):
        """Text width in design units."""
        return self._len(self.font(weight, size, s), s, sp) / self.s

    def _stroke(self, weight, px):
        return max(1, int(round(px / 70))) if weight == "extrabold" and px >= 40 and not (fonts.FONT_DIR / "Poppins-ExtraBold.ttf").exists() else 0

    def _tmask(self, f, s, sp, st, pad=0):
        asc, desc = f.getmetrics()
        wpx = int(math.ceil(self._len(f, s, sp))) + 2 * (st + pad) + 2
        hpx = asc + desc + 2 * (st + pad) + 2
        m = Image.new("L", (wpx, hpx), 0)
        d = ImageDraw.Draw(m)
        x, by = st + pad, st + pad + asc
        if sp:
            for ch in s:
                d.text((x, by), ch, font=f, fill=255, anchor="ls", stroke_width=st)
                x += f.getlength(ch) + sp * self.s
        else:
            d.text((x, by), s, font=f, fill=255, anchor="ls", stroke_width=st)
        return m, st + pad, by

    def text(self, x, y, s, size, weight="regular", fill=(0, 0, 0), align="l", sp=0, lh=1.25, alpha=255,
             outline=None, ow=1, glow=None, shadow=None):
        """Draw one line. (x, y) = left/centre/right and TOP of a line box of height size*lh. Returns width."""
        if not s:
            return 0
        f = self.font(weight, size, s)
        asc, desc = f.getmetrics()
        pxsz = size * self.s
        st = self._stroke(weight, pxsz)
        wpx = self._len(f, s, sp)
        left = x * self.s - (0 if align == "l" else wpx / 2 if align == "m" else wpx)
        base = y * self.s + (pxsz * lh - (asc + desc)) / 2 + asc
        gpad = int(glow[1] * self.s * 3) if glow else 0
        m, ox, oy = self._tmask(f, s, sp, st, pad=gpad)
        px, py = int(round(left)) - ox, int(round(base)) - oy
        if glow:
            gm = m.filter(ImageFilter.GaussianBlur(glow[1] * self.s)).point([min(255, i * 3) for i in range(256)])
            self._fill(glow[0], gm, px, py, glow[2] if len(glow) > 2 else 255)
        if shadow:  # (dx, dy, blur, alpha, color)
            sm = m.filter(ImageFilter.GaussianBlur(max(0.1, shadow[2] * self.s / 2)))
            self._fill(shadow[4], sm, px + self.u(shadow[0]), py + self.u(shadow[1]), shadow[3])
        if outline is not None:  # hollow/outlined text: stroked mask minus plain mask
            grow = max(1, self.u(ow))
            outer, ox2, oy2 = self._tmask(f, s, sp, st + grow, pad=gpad)
            inner, _, _ = self._tmask(f, s, sp, st, pad=gpad + grow)
            self._fill(outline, ImageChops.subtract(outer, inner), int(round(left)) - ox2, int(round(base)) - oy2, alpha)
            if fill is None:
                return wpx / self.s
        self._fill(fill, m, px, py, alpha)
        return wpx / self.s

    # ---- text layout
    def wrap(self, s, size, weight, max_w, sp=0):
        f = self.font(weight, size, s)
        lim = max_w * self.s
        lines, cur = [], ""
        for word in s.split():
            trial = (cur + " " + word).strip()
            if self._len(f, trial, sp) <= lim:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            cur = ""
            while self._len(f, word, sp) > lim and len(word) > 1:  # break a very long word
                k = len(word)
                while k > 1 and self._len(f, word[:k], sp) > lim:
                    k -= 1
                lines.append(word[:k])
                word = word[k:]
            cur = word
        if cur:
            lines.append(cur)
        return lines or [""]

    def _ellipsize(self, line, size, weight, max_w, sp=0):
        line = line.rstrip(" ,.;:-–—")
        while len(line) > 1 and self.tw(line + "…", size, weight, sp) > max_w:
            line = line[:-1].rstrip(" ,.;:-–—")
        return line + "…"

    def clamp(self, s, size, weight, w, max_lines, sp=0):
        """Wrap to at most max_lines, ellipsis on the last line when the text is cut."""
        lines = self.wrap(s, size, weight, w, sp)
        if len(lines) <= max_lines:
            return lines
        lines = lines[:max_lines]
        lines[-1] = self._ellipsize(lines[-1], size, weight, w, sp)
        return lines

    def fit(self, s, w, h, max_size, min_size=10, weight="bold", lh=1.15, max_lines=None, sp=0):
        """Largest font size (design units) at which `s` fits w x h. Returns (size, lines)."""
        size = float(max_size)
        # prefer one line if it only costs a little size (>= 72% of max)
        if (max_lines is None or max_lines > 1) and len(self.wrap(s, size, weight, w, sp)) > 1:
            lo = max(min_size, size * .72)
            t = size
            while t > lo and self.tw(s, t, weight, sp) > w:
                t -= 1
            if self.tw(s, t, weight, sp) <= w and t * lh <= h + .5:
                return t, [s]
        while True:
            lines = self.wrap(s, size, weight, w, sp)
            ok = (max_lines is None or len(lines) <= max_lines) and len(lines) * size * lh <= h + .5
            if ok or size <= min_size:
                break
            size -= 1
        if not ok:
            n = max(1, min(max_lines or 99, int(h // (size * lh)) or 1))
            lines = lines[:n]
            lines[-1] = self._ellipsize(lines[-1], size, weight, w, sp)
        return size, lines

    def lines(self, x, y, lines, size, weight, colors, lh=1.15, align="l", sp=0, **kw):
        """Draw lines; colors is one colour or a list (per line). Returns total height."""
        cols = colors if isinstance(colors[0], (tuple, list)) else [colors]
        for i, ln in enumerate(lines):
            self.text(x, y + i * size * lh, ln, size, weight, cols[min(i, len(cols) - 1)], align=align, sp=sp, lh=lh, **kw)
        return len(lines) * size * lh

    def para(self, x, y, w, s, size, weight="regular", fill=(0, 0, 0), lh=1.5, max_lines=3, align="l", **kw):
        """Wrapped paragraph (align l/m/r inside the box x..x+w). Returns height."""
        lines = self.clamp(s, size, weight, w, max_lines)
        ax = x if align == "l" else x + w / 2 if align == "m" else x + w
        return self.lines(ax, y, lines, size, weight, fill, lh=lh, align=align, **kw)

    def two_tone(self, x, y, lines, size, weight, c1, c2, lh=1.15, align="l", sp=0):
        """Title in two colours: first line c1, the rest c2. A single line is split in the middle by words."""
        if len(lines) == 1 and " " in lines[0]:
            words = lines[0].split()
            k = math.ceil(len(words) / 2)
            a, b = " ".join(words[:k]) + " ", " ".join(words[k:])
            wa, wb = self.tw(a, size, weight, sp), self.tw(b, size, weight, sp)
            x0 = x if align == "l" else x - (wa + wb) / 2 if align == "m" else x - wa - wb
            self.text(x0, y, a, size, weight, c1, sp=sp, lh=lh)
            self.text(x0 + wa, y, b, size, weight, c2, sp=sp, lh=lh)
            return size * lh
        return self.lines(x, y, lines, size, weight, [c1, c2], lh=lh, align=align, sp=sp)

    def vtext(self, x, y, s, size, weight, fill, step):
        """Letters stacked upright, one per `step` units."""
        for i, ch in enumerate(s):
            self.text(x, y + i * step, ch, size, weight, fill, align="m", lh=1)

    def chip(self, x, y, s, size=10, h=24, padx=12, weight="bold", color=(255, 255, 255), fill=None,
             outline=None, ow=1, alpha=255, sp=0, align="l"):
        """Pill with text. Returns the width so chips can be chained."""
        w = self.tw(s, size, weight, sp) + 2 * padx
        x0 = x if align == "l" else x - w / 2 if align == "m" else x - w
        self.rect(x0, y, w, h, fill=fill, outline=outline, ow=ow, r=h / 2, alpha=alpha)
        self.text(x0 + w / 2, y + (h - size * 1.25) / 2, s, size, weight, color, align="m", sp=sp)
        return w

    def icon(self, name, cx, cy, size, color, alpha=255):
        n = max(2, self.u(size))
        K = 8
        m = Image.new("L", (n * K, n * K), 0)
        ICONS[name](ImageDraw.Draw(m), n * K)
        m = m.resize((n, n), Image.LANCZOS)
        self._fill(color, m, int(round(cx * self.s - n / 2)), int(round(cy * self.s - n / 2)), alpha)

    # ---- export
    def png(self) -> bytes:
        buf = io.BytesIO()
        self.im.save(buf, "PNG", compress_level=3)
        return buf.getvalue()

    def jpeg(self, quality=92) -> bytes:
        buf = io.BytesIO()
        self.im.save(buf, "JPEG", quality=quality, optimize=False)
        return buf.getvalue()
