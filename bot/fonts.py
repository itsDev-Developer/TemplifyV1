"""Font loading. Poppins ships in /fonts; other scripts (CJK, Cyrillic...) fall back to system fonts."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

# weight -> files tried in order. "extrabold" is Bold + a thin stroke added by draw.py
# (drop Poppins-ExtraBold.ttf into /fonts and it is used instead).
FILES = {
    "regular": ["Poppins-Regular.ttf"],
    "medium": ["Poppins-Medium.ttf", "Poppins-Regular.ttf"],
    "semibold": ["Poppins-SemiBold.ttf", "Poppins-Bold.ttf"],
    "bold": ["Poppins-Bold.ttf"],
    "extrabold": ["Poppins-ExtraBold.ttf", "Poppins-Bold.ttf"],
    "italic": ["Poppins-Italic.ttf", "Poppins-Regular.ttf"],
    "mediumitalic": ["Poppins-MediumItalic.ttf", "Poppins-Italic.ttf", "Poppins-Regular.ttf"],
    "bolditalic": ["Poppins-BoldItalic.ttf", "Poppins-Bold.ttf"],
}
HEAVY = {"semibold", "bold", "extrabold", "bolditalic"}

CJK_REG = [
    "/system/fonts/NotoSansCJK-Regular.ttc",  # Android / Termux
    "/system/fonts/NotoSansSC-Regular.otf",
    "/system/fonts/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Debian / Docker (fonts-noto-cjk)
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
CJK_BOLD = [
    "/system/fonts/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]
LATIN_REG = [
    "/system/fonts/Roboto-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
LATIN_BOLD = [
    "/system/fonts/Roboto-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def script_of(text: str) -> int:
    """0 = Poppins is fine, 1 = needs a CJK font, 2 = needs another fallback (Cyrillic, Greek, Arabic...)."""
    need = 0
    for ch in text:
        o = ord(ch)
        if o < 0x370 or 0x2000 <= o <= 0x2BFF:
            continue
        if 0x2E80 <= o <= 0xD7FF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF:
            return 1
        need = 2
    return need


@lru_cache(maxsize=128)
def font(weight: str, px: float, fb: int = 0) -> ImageFont.FreeTypeFont:
    size = max(1, int(round(px)))
    heavy = weight in HEAVY
    if fb == 1:
        names = (CJK_BOLD if heavy else []) + CJK_REG
    elif fb == 2:
        names = (LATIN_BOLD if heavy else []) + LATIN_REG
    else:
        names = []
    paths = [Path(p) for p in names]
    paths += [FONT_DIR / f for f in FILES.get(weight, FILES["regular"])]
    paths += [Path(p) for p in (LATIN_BOLD if heavy else LATIN_REG)]
    for p in paths:
        if p.exists():
            try:
                # BASIC layout: no libraqm needed (Termux's Pillow may not ship it)
                return ImageFont.truetype(str(p), size, layout_engine=ImageFont.Layout.BASIC)
            except OSError:
                continue
    return ImageFont.load_default(size)


def pick(weight: str, px: float, text: str = "") -> ImageFont.FreeTypeFont:
    return font(weight, px, script_of(text) if text else 0)
