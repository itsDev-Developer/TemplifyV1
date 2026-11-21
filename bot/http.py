"""Minimal HTTP helper on top of urllib (stdlib only, nothing to compile on Termux)."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "poster-bot/1.0"

# Circuit breaker per host: after FAILS consecutive failures requests to that host fail fast for COOL seconds instead of
# stacking up slow timeouts (e.g. when TMDB is down). 4xx answers other than 429 are the caller's fault and don't count.
FAILS, COOL = 5, 30
_breaker: dict[str, list] = {}  # host -> [consecutive failures, open-until timestamp]
_blk = threading.Lock()


class CircuitOpen(OSError):
    pass


def _gate(host: str) -> None:
    with _blk:
        st = _breaker.get(host)
        if st and st[1] > time.time():
            raise CircuitOpen(f"{host} is temporarily unavailable")


def _record(host: str, ok: bool) -> None:
    with _blk:
        st = _breaker.setdefault(host, [0, 0.0])
        if ok:
            st[0], st[1] = 0, 0.0
        else:
            st[0] += 1
            if st[0] >= FAILS:
                st[1] = time.time() + COOL
                st[0] = FAILS - 1  # one probe after the cool-down; a failure re-opens immediately


def open_circuits() -> list[str]:
    now = time.time()
    with _blk:
        return [h for h, st in _breaker.items() if st[1] > now]


def request(url, params=None, headers=None, body=None, timeout=20, retries=2):
    """Returns (bytes, content_type). Retries on network errors, 429 and 5xx."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": UA, **(headers or {})}
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    host = urllib.parse.urlsplit(url).hostname or ""
    _gate(host)
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = r.read(), r.headers.get("Content-Type", "")
            _record(host, True)
            return out
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                _record(host, True)  # the host answered; this request was just wrong/missing
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
        time.sleep(1 + i)
    _record(host, False)
    raise last


def get_json(url, **kw):
    return json.loads(request(url, **kw)[0])
