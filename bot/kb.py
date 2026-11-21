"""Inline keyboard helpers."""
from __future__ import annotations

from . import tg


def btn(text: str, data: str | None = None, url: str | None = None, style: str | None = None) -> dict:
    """style: 'primary' (blue) | 'success' (green) | 'danger' (red). Ignored when the server lacks button styles."""
    b = {"text": text}
    if url:
        b["url"] = url
    else:
        b["callback_data"] = data or "noop"
    if style and tg.STYLES:
        b["style"] = style
    return b


def kb(*rows) -> dict:
    return {"inline_keyboard": [list(r) for r in rows if r]}


def chunk(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def paginate(prefix: str, page: int, pages: int) -> list[dict]:
    """PREV | 1/3 | NEXT row; callbacks are f'{prefix}:{page}'."""
    row = []
    if pages > 1:
        row.append(btn("◀ PREV", f"{prefix}:{(page - 1) % pages}", style="primary"))
        row.append(btn(f"{page + 1:02d}/{pages:02d}", "noop"))
        row.append(btn("NEXT ▶", f"{prefix}:{(page + 1) % pages}", style="primary"))
    return row
