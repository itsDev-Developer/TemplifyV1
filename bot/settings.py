"""Declarative settings. The in-bot settings panel and the admin panel are generated from these lists, so adding an
option is one line. kind: toggle | choice | text | number."""
from __future__ import annotations

from .context import COLORS

QUALITY = {"720p": 1.0, "1080p": 1.5, "1440p": 2.0}

BRAND_DEFAULTS = {  # kind -> (brand, tagline); used when the user hasn't set anything
    "anime": ("AniCruise", "Your Anime. Your Way."),
    "manga": ("Manga Cruise", "Read. Feel. Repeat."),
    "movie": ("Nova Flix", "Cinema, Delivered."),
    "tv": ("Nova Flix", "Binge Without Limits."),
}
KIND_LABEL = {"anime": "Anime", "manga": "Manga", "movie": "Movies", "tv": "TV shows"}


def brand_for(s: dict, kind: str) -> str:
    """Explicit per-type brand > explicit general brand > the type's default."""
    return (s.get(f"brand_{kind}") or s.get("brand") or BRAND_DEFAULTS.get(kind, BRAND_DEFAULTS["movie"])[0]).strip()


def tagline_for(s: dict, kind: str) -> str:
    return (s.get(f"tagline_{kind}") or s.get("tagline") or BRAND_DEFAULTS.get(kind, BRAND_DEFAULTS["movie"])[1]).strip()


USER = [
    dict(key="brand", label="Brand (all types)", kind="text", default="", max=30,
         help="One brand for every poster. Leave empty to use the per-type brands under <b>Brands &amp; taglines</b>."),
    dict(key="color", label="Accent colour", kind="choice", default="auto", choices=["auto", *COLORS],
         help="Accent colour of the poster. <b>auto</b> uses each template's own colour."),
    dict(key="template", label="Default template", kind="choice", default="auto", choices=["auto"],  # filled at runtime
         help="Template shown first. <b>auto</b> picks one that suits the title."),
    dict(key="tagline", label="Tagline (all types)", kind="text", default="", max=70,
         help="One tagline for every poster. Leave empty to use the per-type taglines."),
    dict(key="quality", label="Image quality", kind="choice", default="1080p", choices=list(QUALITY),
         help="Resolution of generated posters."),
    dict(key="caption", label="Caption style", kind="choice", default="full", choices=["full", "compact", "off"],
         help="<b>full</b> = details + synopsis, <b>compact</b> = two lines, <b>off</b> = photo only."),
    dict(key="pixels", label="Pixels line", kind="text", default="480p | 720p | 1080p", max=40,
         help="Shown as <code>Pixels:</code> in the caption of movies, series and anime. Send <code>-</code> to hide it."),
    dict(key="audio", label="Audio line", kind="text", default="Hindi & English", max=40,
         help="Shown as <code>Audio:</code> in the caption. Send <code>-</code> to hide it."),
    dict(key="synopsis", label="Synopsis in caption", kind="toggle", default=True),
    dict(key="collapse", label="Collapsible synopsis", kind="toggle", default=True,
         help="Show the synopsis as an expandable quote."),
    dict(key="fanart", label="Use extra artwork (fanart.tv / TMDB logos)", kind="toggle", default=True,
         help="Uses the best fanart.tv backgrounds/logos when available (needs a fanart key on the server)."),
    dict(key="button_text", label="Post button text", kind="text", default="📥 Download", max=24,
         help="Text of the link button under the finished post."),
]

USER += [dict(key=f"{f}_{k}", label=f"{KIND_LABEL[k]} {f}", kind="text", default=BRAND_DEFAULTS[k][0 if f == "brand" else 1],
              max=30 if f == "brand" else 70, group="brands",
              help=f"{'Brand name' if f == 'brand' else 'Tagline'} printed on <b>{KIND_LABEL[k]}</b> posters (/{ {'anime': 'anime', 'manga': 'manga', 'movie': 'movie', 'tv': 'tvshows'}[k]}).")
         for k in BRAND_DEFAULTS for f in ("brand", "tagline")]

ADMIN = [
    dict(key="public", label="Public access", kind="toggle", default=True,
         help="Off = only admins and users added with /auth can use the bot."),
    dict(key="maintenance", label="Maintenance mode", kind="toggle", default=False,
         help="On = the bot answers everyone except admins with a maintenance notice."),
    dict(key="daily_limit", label="Posters per user / day", kind="number", default=0, max=100000,
         help="0 = unlimited. Admins are exempt."),
    dict(key="api_enabled", label="Bot API", kind="toggle", default=True,
         help="On = other bots can request posters through the HTTP API (they still need a key from /apikey)."),
    dict(key="api_rpm", label="API default req/min", kind="number", default=30, max=6000,
         help="Rate limit given to new keys unless /apikey sets its own."),
    dict(key="api_daily", label="API default req/day", kind="number", default=2000, max=10000000,
         help="Daily limit given to new keys. 0 = unlimited."),
    dict(key="support_url", label="Support link", kind="text", default="", max=200,
         help="URL of the Support button on /start (e.g. <code>https://t.me/yourgroup</code>)."),
    dict(key="updates_url", label="Updates link", kind="text", default="", max=200,
         help="URL of the Updates button on /start."),
    dict(key="welcome_text", label="Welcome text", kind="text", default="", max=600,
         help="Replaces the default /start message. HTML allowed; <code>{name}</code> = the user's first name."),
    dict(key="welcome_image", label="Welcome image", kind="text", default="", max=300,
         help="Image URL or Telegram file_id shown on /start. You can also just send a photo here."),
    dict(key="log_channel", label="Logs channel", kind="text", default="", max=40,
         help="Channel id (<code>-100…</code>) that receives logs. The bot must be admin there."),
    dict(key="storage_channel", label="Storage channel", kind="text", default="", max=40,
         help="Channel id that stores finished posters and the database backup. Bot must be admin."),
]
