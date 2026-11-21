# Poster Bot

Telegram bot that turns a title (movie, series, anime, manga, manhwa) into a ready-to-post poster + caption.
**16 templates** (13 classic + 3 fanart-only) drawn with Pillow only: no browser, no compiled packages, so it runs on
Termux and Render alike. Art: TMDB (movies/TV), AniList (anime/manga, no key), fanart.tv (best logos/backgrounds).

## Flow (as in the reference bot)
`/anime naruto` · `/manga` · `/movie` · `/tvshows` (or just send a title) → paginated results → poster + caption →
controls: **◀ PREV / NEXT ▶** template carousel (edits the poster in place), **EDIT DATA** (title, rating, genres,
synopsis, status, episodes, custom poster, custom character PNG), **GEN BANNER**, send your own thumbnail,
**SKIP THUMB** → custom button link → **POST TO <channel>** in one tap.

## Everything is configurable inside the bot
- `/settings` (every user): brand, accent colour, default template, tagline, quality (720p/1080p/1440p), caption style,
  Pixels / Audio lines, synopsis on/off + collapsible, fanart on/off, post-button text, linked channels.
- `/admin` (owner/sudo): public/private access, maintenance mode, per-user daily limit, welcome text/image,
  Updates/Support links, **logs channel**, **storage channel**, stats, backup.
- Roles: `/auth /unauth /ban /unban /addsudo /rmsudo /sudo /broadcast /stats /backup`.

## Run on Termux / locally
```bash
pkg install python python-pillow      # Termux (or: pip install -r requirements.txt)
cp .env.example .env                  # BOT_TOKEN, OWNER_ID, TMDB_API_KEY, FANART_API_KEY
python -m bot.main                    # long polling
python demo.py art1.jpg art2.jpg      # render every template offline -> ./out
python -m unittest discover -s tests  # 18 end-to-end tests against a fake Telegram server, no network
```

## Deploy on Render
1. Push to GitHub → **New + > Blueprint** (uses `render.yaml`, Docker), or a Docker *Web Service*.
2. Env vars: `BOT_TOKEN`, `OWNER_ID`, `TMDB_API_KEY`, `FANART_API_KEY`, `STORAGE_CHANNEL_ID`, optionally `LOG_CHANNEL_ID`.
3. Render supplies `PORT` and `RENDER_EXTERNAL_URL`: the bot binds the port, serves `/health` and `/metrics`, and
   registers a secret-protected webhook automatically. Free tier sleeps when idle; ping `/health` with UptimeRobot.
4. **Persistence:** state is SQLite (`DATA_DIR/bot.db`). Render's disk is ephemeral, so with `STORAGE_CHANNEL_ID` set the DB
   is snapshotted to that channel (pinned `bot.db`, ≤1/min after changes and on shutdown) and restored on boot.
   Or attach a Render persistent disk and set `DATA_DIR` to its mount path.

## Production notes
- Webhook answers instantly and processes on a worker pool; >400 queued updates → 503 (Telegram retries). Updates are de-duplicated.
- Per-user serialisation (no races on one user's drafts), token-bucket rate limit, daily quota, render semaphore.
- Drafts, roles, settings, channel links live in SQLite so button presses survive restarts/redeploys.
- SIGTERM: stop intake → finish in-flight updates → flush logs → final DB backup.
- Scaling: one instance comfortably serves thousands of users (renders are the bottleneck: ~0.3–1 s CPU each; raise
  `RENDER_CONCURRENCY` with cores). Multiple instances need a shared database: `bot/store.py` is the only storage
  module, swap it for a Postgres implementation of the same functions.
- Poster flips are served from a Telegram `file_id` cache (no re-render, no re-upload).

## Artwork buttons
Under every poster, **🎨 ART** steps through the available posters, backgrounds, logos (`title.png`) and character
art, and your own uploaded character image; the poster re-renders instantly. Sources: TMDB images, fanart.tv (with
`FANART_API_KEY`), AniList.

## Brands & taglines per type
`/settings` → **🏷 Brands & taglines**: separate brand + tagline for /anime (AniCruise), /manga (Manga Cruise),
/movie and /tvshows (Nova Flix). A single "Brand (all types)" overrides the defaults if you set one.

## API for other bots
`/apikey name` (owner, private chat) → `POST /api/v1/render`. Full reference: [docs/API.md](docs/API.md).

## Health
`/health` (liveness), `/ready` (DB + Telegram + not shutting down; 503 otherwise), `/metrics`.
Startup validates the config and prints readable problems. Upstream hosts (TMDB, AniList, fanart.tv) have a circuit
breaker, so an outage fails fast instead of stalling renders. Docker image runs as a non-root user.

## Fanart.tv
Movies by TMDB id, TV by TVDB id (via TMDB), anime matched to TMDB by title/year → TVDB. Results are ranked
(HD logo first, English logos first, textless backgrounds/posters first, then likes) and cached 12 h. The three Fanart
templates (Logo Hero, Poster Stage, Character Spotlight) only appear when fanart.tv returned artwork.

## Add a template
```python
@template("mine", "My Design", "#ff5500")
def mine(c, d):   # 1280x720 design units
    c.image(d.poster, 0, 0, 1280, 720); c.text(60, 60, d.title, 48, "extrabold", (255, 255, 255))
```
