"""Image loading with a small in-memory LRU. Downscales big images to keep RAM low on phones."""
from __future__ import annotations

import io
import os
import threading
from collections import OrderedDict

from PIL import Image

from . import http

MAX_SIDE = 1600
MAX_ITEMS = 16
_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()
_loaders: dict = {}  # scheme -> fn(rest) -> bytes ; e.g. "tg" downloads a Telegram file_id


def register_loader(scheme: str, fn) -> None:
    _loaders[scheme] = fn


def load(src: str, alpha: bool = False):
    """URL or local path -> PIL image (RGB, or RGBA when alpha=True). None if it can't be loaded."""
    if not src:
        return None
    key = (src, alpha)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    try:
        scheme = src.split(":", 1)[0]
        if scheme in _loaders:
            im = Image.open(io.BytesIO(_loaders[scheme](src.split(":", 1)[1])))
        elif src.startswith(("http://", "https://")):
            raw, _ = http.request(src, timeout=25)
            im = Image.open(io.BytesIO(raw))
        elif os.path.exists(src):
            im = Image.open(src)
        else:
            return None
        im.load()
        im = im.convert("RGBA" if alpha else "RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    except Exception:
        return None
    with _lock:
        _cache[key] = im
        while len(_cache) > MAX_ITEMS:
            _cache.popitem(last=False)
    return im


def forget(prefix: str) -> None:
    """Drop cached images whose source starts with `prefix` (per-request uploads)."""
    with _lock:
        for k in [k for k in _cache if k[0].startswith(prefix)]:
            _cache.pop(k, None)
