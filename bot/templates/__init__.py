"""Template registry. A template is `render(c: Canvas, d: Ctx) -> None` drawing on a 1280x720 design canvas."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..context import Ctx
from ..draw import Canvas


@dataclass(frozen=True)
class Tpl:
    key: str
    label: str
    accent: str  # default accent colour
    fn: Callable[[Canvas, Ctx], None]
    group: str  # Series | Anime | Manga | Fanart | Universal (menu ordering only)
    hidden: bool = False  # not offered in the carousel (used for the Gen Banner view)


TEMPLATES: dict[str, Tpl] = {}


def template(key: str, label: str, accent: str, group: str = "Universal", hidden: bool = False):
    def deco(fn):
        TEMPLATES[key] = Tpl(key, label, accent, fn, group, hidden)
        return fn

    return deco


def render(key: str, d: Ctx, scale: float = 1.5) -> Canvas:
    t = TEMPLATES[key]
    c = Canvas(scale=scale, accent=d.accent)
    t.fn(c, d)
    return c


# import for side effects (registration order = menu order)
from . import core, manga, modern, creative, fanart  # noqa: E402,F401
