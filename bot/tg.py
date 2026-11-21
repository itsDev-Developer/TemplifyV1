"""Minimal Telegram Bot API client on urllib (no third-party packages, works on Termux)."""
from __future__ import annotations

import json
import logging
import mimetypes
import time
import urllib.error
import urllib.request
import uuid

from . import config

log = logging.getLogger("posterbot")


STYLES = config.BUTTON_STYLES  # coloured inline buttons (Bot API 9.4+); auto-disabled if the server rejects them


class TgError(Exception):
    def __init__(self, msg, code=0, retry_after=0):
        super().__init__(msg)
        self.code, self.retry_after = code, retry_after


def _strip_styles(markup: str) -> str:
    try:
        m = json.loads(markup)
        for row in m.get("inline_keyboard", []):
            for b in row:
                b.pop("style", None)
        return json.dumps(m)
    except Exception:
        return markup


def _multipart(fields: dict, files: dict):
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (name, data) in files.items():
        ct = mimetypes.guess_type(name)[0] or "application/octet-stream"
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ct}\r\n\r\n'.encode())
        out += [data, b"\r\n"]
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


class Bot:
    def __init__(self, token: str, base: str | None = None):
        self.token = token
        self.base = f"{base or config.BOT_API_BASE}/bot{token}"
        self.file_base = f"{base or config.BOT_API_BASE}/file/bot{token}"
        self.me: dict = {}

    def call(self, method: str, files: dict | None = None, timeout=40, **params):
        params = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items() if v is not None}
        for attempt in range(3):
            if files:
                body, ctype = _multipart(params, files)
            else:
                body, ctype = json.dumps(params).encode(), "application/json"
            req = urllib.request.Request(f"{self.base}/{method}", data=body, headers={"Content-Type": ctype})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read())
            except urllib.error.HTTPError as e:
                try:
                    data = json.loads(e.read())
                except Exception:
                    data = {"ok": False, "description": str(e), "error_code": e.code}
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                if attempt == 2:
                    raise TgError(f"network: {e}")
                time.sleep(1 + attempt)
                continue
            if data.get("ok"):
                return data["result"]
            ra = (data.get("parameters") or {}).get("retry_after", 0)
            global STYLES
            desc = data.get("description", "")
            if (data.get("error_code") == 400 and STYLES and isinstance(params.get("reply_markup"), str)
                    and '"style"' in params["reply_markup"] and "not modified" not in desc and "not found" not in desc):
                STYLES = False  # server doesn't know button styles: drop them for good and retry plain
                log.warning("button styles rejected (%s); continuing without", desc)
                params["reply_markup"] = _strip_styles(params["reply_markup"])
                continue
            if ra and attempt < 2:
                time.sleep(min(ra, 30) + 1)
                continue
            raise TgError(data.get("description", "error"), data.get("error_code", 0), ra)

    # ---- helpers
    def send(self, chat_id, text, **kw):
        return self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                         disable_web_page_preview=True, **kw)

    def edit(self, chat_id, message_id, text, **kw):
        try:
            return self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                             parse_mode="HTML", disable_web_page_preview=True, **kw)
        except TgError as e:
            if "not modified" not in str(e):
                raise

    def answer(self, cb_id, text="", alert=False):
        try:
            self.call("answerCallbackQuery", callback_query_id=cb_id, text=text, show_alert=alert)
        except TgError:
            pass

    def send_photo(self, chat_id, photo, caption=None, name="poster.jpg", **kw):
        """photo: bytes (upload) or a file_id string (instant resend)."""
        if isinstance(photo, (bytes, bytearray)):
            return self.call("sendPhoto", files={"photo": (name, bytes(photo))}, timeout=90,
                             chat_id=chat_id, caption=caption, parse_mode="HTML", **kw)
        return self.call("sendPhoto", chat_id=chat_id, photo=photo, caption=caption, parse_mode="HTML", **kw)

    def send_document(self, chat_id, doc, name="file.bin", caption=None, **kw):
        if isinstance(doc, (bytes, bytearray)):
            return self.call("sendDocument", files={"document": (name, bytes(doc))}, timeout=90,
                             chat_id=chat_id, caption=caption, parse_mode="HTML", **kw)
        return self.call("sendDocument", chat_id=chat_id, document=doc, caption=caption, parse_mode="HTML", **kw)

    def edit_media(self, chat_id, message_id, photo, caption=None, name="poster.jpg", **kw):
        """Swap the picture (and caption) of an existing photo message in place. photo: bytes or a file_id."""
        media = {"type": "photo", "media": "attach://file", "caption": caption or "", "parse_mode": "HTML"}
        if isinstance(photo, (bytes, bytearray)):
            return self.call("editMessageMedia", files={"file": (name, bytes(photo))}, timeout=90,
                             chat_id=chat_id, message_id=message_id, media=media, **kw)
        media["media"] = photo
        return self.call("editMessageMedia", chat_id=chat_id, message_id=message_id, media=media, **kw)

    def edit_caption(self, chat_id, message_id, caption, **kw):
        try:
            return self.call("editMessageCaption", chat_id=chat_id, message_id=message_id, caption=caption,
                             parse_mode="HTML", **kw)
        except TgError as e:
            if "not modified" not in str(e):
                raise

    def delete(self, chat_id, message_id):
        try:
            self.call("deleteMessage", chat_id=chat_id, message_id=message_id)
        except TgError:
            pass

    def download(self, file_id: str, max_bytes: int = 15 * 1024 * 1024) -> bytes:
        info = self.call("getFile", file_id=file_id)
        if int(info.get("file_size") or 0) > max_bytes:
            raise TgError("file too large")
        with urllib.request.urlopen(f"{self.file_base}/{info['file_path']}", timeout=60) as r:
            data = r.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise TgError("file too large")
        return data
