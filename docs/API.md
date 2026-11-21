# Poster Bot API

Lets other bots/services request finished posters. Base URL: `https://<your-app>/api/v1`

## Keys
The owner creates keys in a **private chat** with the bot:

    /apikey mychannelbot 30 2000      name, requests/min, requests/day (0 = unlimited)
    /apikeys                          list (never shows the secret)
    /apirevoke 3                      revoke by id

The token (`pbk_…`) is shown once and stored only as a SHA-256 hash. Send it as `Authorization: Bearer pbk_…` or
`X-API-Key: pbk_…`. Admin panel → **Bot API** switches the whole API off; default limits are in the same panel.

## Endpoints
| | |
|---|---|
| `GET /templates` | template keys, labels, groups (`needs_artwork` = Fanart group), colours |
| `GET /search?q=naruto&type=anime` | `type`: anime, manga, movie, tv → `{results:[{source,kind,id,title,year…}]}` |
| `GET /media/{source}/{kind}/{id}` | full details + `art_counts` (how many logos/posters/backgrounds/characters exist) |
| `POST /render` | render a poster (below) |
| `GET /usage` | your key's limits and counters |
| `GET /openapi.json` | OpenAPI 3 spec (no key needed) |

## POST /render
Pick the title one of three ways: `{"source":"anilist","kind":"anime","id":1}`, `{"title":"naruto","type":"anime"}`
(first search hit), or inline `{"media":{"title":"…","kind":"movie","genres":[…],"poster":"https://…"}}`.

| field | |
|---|---|
| `template` | required (`banner: true` renders the wide banner instead) |
| `brand`, `tagline` | default: per-type brand (AniCruise, Manga Cruise, Nova Flix…) |
| `color` | `auto`, a colour name from `/templates`, or `#rrggbb` |
| `scale` | 0.5 – 2 (1 = 1280×720) |
| `format` | `jpeg` (default) or `png` |
| `response` | `image` (default, raw bytes) or `json` (`image_base64`, `caption`, media summary) |
| `art` | indices into the artwork lists: `{"logo":1,"character":0,"poster":2,"background":1}` |
| `overrides` | `title, rating, genres[], synopsis, year, episodes, status, type_label, poster_url, backdrop_url, logo_url, character_url` |
| `caption_style`, `pixels`, `audio` | caption options for `response: json` |

`*_url` accepts `https://` URLs or `data:image/png;base64,…`. URLs pointing at private/loopback/link-local addresses
are refused; images are limited to 15 MB. Fanart templates need a logo and/or character image; give `logo_url` /
`character_url` (transparent PNG) or let the server use fanart.tv/TMDB art when configured.

### curl
    curl -s https://HOST/api/v1/render -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
      -d '{"title":"Frieren","type":"anime","template":"fa_diamond","scale":1.5}' -o poster.jpg

### Python (a bot posting to a channel)
    import requests
    r = requests.post(f"{BASE}/api/v1/render", headers={"Authorization": f"Bearer {KEY}"},
                      json={"source": "tmdb", "kind": "movie", "id": 603, "template": "cinema", "response": "json"}, timeout=90)
    r.raise_for_status()
    d = r.json()
    bot.send_photo(chat_id, base64.b64decode(d["image_base64"]), caption=d["caption"], parse_mode="HTML")

## Errors & limits
JSON `{"error":{"code","message"}}`. `401` bad key · `422` bad request · `404` no match · `413` too large ·
`429` rate/daily limit (`Retry-After`) · `503` busy/disabled (`Retry-After`) · `502` upstream provider down.
Every response carries `X-RateLimit-Limit/Remaining`; renders add `X-Render-Ms`, `X-Template`.
Rendering is CPU-heavy: on a free Render instance expect 1–4 s per poster; retry on 503.
