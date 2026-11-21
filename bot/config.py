"""All settings come from environment variables (optionally a .env file; no extra package needed)."""
from __future__ import annotations

import os
from pathlib import Path


def _load_env() -> None:
    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env()


def _int(name: str, default=0) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
FANART_API_KEY = os.getenv("FANART_API_KEY", "").strip()  # optional, better movie/TV art
RENDER_SCALE = float(os.getenv("RENDER_SCALE", "1.5") or 1.5)
RENDER_CONCURRENCY = max(1, _int("RENDER_CONCURRENCY", 2))
PORT = _int("PORT", 8080)
HOST = os.getenv("HOST", "0.0.0.0")
DATA_DIR = os.getenv("DATA_DIR", "data")
OWNER_ID = _int("OWNER_ID")
LOG_CHANNEL_ID = _int("LOG_CHANNEL_ID")  # e.g. -1001234567890
STORAGE_CHANNEL_ID = _int("STORAGE_CHANNEL_ID")
BOT_API_BASE = os.getenv("BOT_API_BASE", "https://api.telegram.org").rstrip("/")
# Render sets RENDER_EXTERNAL_URL automatically for web services; WEBHOOK_URL overrides it.
PUBLIC_URL = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
MODE = (os.getenv("MODE") or ("webhook" if PUBLIC_URL else "polling")).lower()
KEEPALIVE = os.getenv("KEEPALIVE", "1" if os.getenv("RENDER_EXTERNAL_URL") else "0") == "1"

BUTTON_STYLES = os.getenv("BUTTON_STYLES", "1") == "1"
WORKERS = max(4, _int("WORKERS", 16))
SUDO_IDS = {int(x) for x in os.getenv("SUDO_IDS", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()}
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()  # text | json (one JSON object per line, for log aggregators)


def validate() -> tuple[list[str], list[str]]:
    """-> (errors, warnings). Errors stop the bot at startup with a readable message instead of failing later."""
    import re
    errs, warns = [], []
    if not BOT_TOKEN:
        errs.append("BOT_TOKEN is not set (get one from @BotFather)")
    elif not re.fullmatch(r"\d{5,}:[\w-]{20,}", BOT_TOKEN):
        errs.append("BOT_TOKEN doesn't look like a Telegram bot token (expected 123456:ABC…)")
    if not 0 <= PORT <= 65535:
        errs.append(f"PORT={PORT} is out of range")
    if not 0.5 <= RENDER_SCALE <= 3:
        errs.append("RENDER_SCALE must be between 0.5 and 3")
    if MODE not in ("polling", "webhook"):
        errs.append("MODE must be polling or webhook")
    if MODE == "webhook" and not PUBLIC_URL:
        errs.append("MODE=webhook needs WEBHOOK_URL (or RENDER_EXTERNAL_URL)")
    if PUBLIC_URL and not PUBLIC_URL.startswith("https://"):
        warns.append("WEBHOOK_URL is not https - Telegram only delivers webhooks to https URLs")
    try:
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
        probe = Path(DATA_DIR) / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as e:
        errs.append(f"DATA_DIR={DATA_DIR!r} is not writable ({e.strerror or e})")
    if not OWNER_ID:
        warns.append("OWNER_ID is not set - nobody can use /admin until you set it")
    if not TMDB_API_KEY:
        warns.append("TMDB_API_KEY is not set - /movie and /tvshows search are disabled, and anime art has no logos/fanart")
    if not STORAGE_CHANNEL_ID:
        warns.append("No STORAGE_CHANNEL_ID - on hosts with an ephemeral disk (Render free) settings are lost on redeploy unless set in /admin")
    return errs, warns
