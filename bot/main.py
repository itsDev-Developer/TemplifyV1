"""Entry point.  python -m bot.main

Render web service: binds $PORT, answers /health and /metrics, receives updates by webhook when
RENDER_EXTERNAL_URL / WEBHOOK_URL is set. Termux / local: long polling. SIGTERM/SIGINT shut down gracefully."""
from __future__ import annotations

import hashlib
import json
import logging
import signal
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import api, config, http, metrics, store
from .app import App
from .logs import Archive, ChannelLogHandler, LogChannel
from .tg import Bot, TgError

log = logging.getLogger("posterbot")
stop = threading.Event()
MAX_QUEUE = 400  # webhook backpressure: beyond this we answer 503 and Telegram retries later


API_INFLIGHT = threading.BoundedSemaphore(32)  # concurrent API requests; beyond this we answer 503


def serve(app: App, pool: ThreadPoolExecutor, secret: str, path: str) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        timeout = 30  # slow or stalled clients can't hold a thread forever

        def _ready(self):
            """Readiness: 200 only when the DB answers, the bot identity is known and we're not shutting down."""
            checks = {"db": False, "telegram": bool(app.bot.me), "shutting_down": stop.is_set()}
            try:
                checks["schema"] = store.schema_version()
                store.stats()
                checks["db"] = True
            except Exception as e:
                checks["db_error"] = str(e)
            checks["open_circuits"] = http.open_circuits()
            ok = checks["db"] and checks["telegram"] and not checks["shutting_down"]
            self._send(json.dumps({"ready": ok, **checks}).encode(), 200 if ok else 503, "application/json")

        def _api(self):
            from urllib.parse import parse_qs, urlsplit
            u = urlsplit(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            if n > api.MAX_BODY:
                return self._send(*self._pack(*api._json({"error": {"code": "too_large", "message": "Request body too large"}}, 413)))
            if not API_INFLIGHT.acquire(blocking=False):
                return self._send(*self._pack(*api._json({"error": {"code": "busy", "message": "Server busy"}}, 503, {"Retry-After": "2"})))
            try:
                body = self.rfile.read(n) if n else b""
                st, hdr, out = api.handle(app, self.command, u.path, parse_qs(u.query), dict(self.headers.items()), body)
            finally:
                API_INFLIGHT.release()
            self._send(*self._pack(st, hdr, out))

        @staticmethod
        def _pack(st, hdr, out):
            return out, st, hdr.get("Content-Type", "application/json"), {k: v for k, v in hdr.items() if k != "Content-Type"}
        def _send(self, body=b"ok", code=200, ctype="text/plain", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/api/"):
                return self._api()
            if self.path.startswith("/ready"):
                return self._ready()
            if self.path.startswith("/health"):
                try:
                    st = store.stats()
                    return self._send(json.dumps({"status": "ok", "users": st["users"], "posters": st["posters"],
                                                  "queue": pool._work_queue.qsize()}).encode(), ctype="application/json")
                except Exception as e:
                    return self._send(json.dumps({"status": "error", "error": str(e)}).encode(), 503, "application/json")
            if self.path.startswith("/metrics"):
                return self._send(metrics.render({"queue": pool._work_queue.qsize()}).encode())
            self._send(b"Poster Bot is running")

        do_HEAD = do_GET

        def do_POST(self):
            if self.path.startswith("/api/"):
                return self._api()
            if self.path != path or self.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
                return self._send(b"forbidden", 403)
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > 1_000_000:
                    return self._send(b"too large", 413)
                upd = json.loads(self.rfile.read(n))
            except Exception:
                return self._send(b"bad request", 400)
            if pool._work_queue.qsize() > MAX_QUEUE:
                metrics.inc("shed")
                return self._send(b"busy", 503)
            pool.submit(app.handle, upd)
            self._send()  # answer immediately; the work happens on the pool

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((config.HOST, config.PORT), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="http").start()
    log.info("listening on %s:%s", config.HOST, config.PORT)
    return srv


def keepalive() -> None:
    while not stop.wait(600):
        try:
            urllib.request.urlopen(f"{config.PUBLIC_URL}/health", timeout=15).read()
        except Exception:
            pass


def housekeeping() -> None:
    while not stop.wait(3600):
        try:
            store.cleanup()
        except Exception as e:
            log.warning("cleanup failed: %s", e)


def poll(bot: Bot, app: App, pool: ThreadPoolExecutor) -> None:
    bot.call("deleteWebhook", drop_pending_updates=False)
    offset, backoff = None, 1
    while not stop.is_set():
        try:
            ups = bot.call("getUpdates", offset=offset, timeout=25, allowed_updates=["message", "callback_query"]) or []
            backoff = 1
            for u in ups:
                offset = u["update_id"] + 1
                pool.submit(app.handle, u)
        except Exception as e:  # network blips, 409 while a second instance starts, Telegram 5xx…
            log.warning("getUpdates: %s", e)
            stop.wait(min(backoff, 30))
            backoff *= 2


def set_commands(bot: Bot) -> None:
    user = [("start", "Welcome & menu"), ("anime", "Create anime poster"), ("manga", "Create manga poster"), ("movie", "Create movie poster"),
            ("tvshows", "Create TV show poster"), ("settings", "Brand, colours, caption…"), ("channels", "Link your channels"), ("help", "Help")]
    try:
        bot.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in user])
        if config.OWNER_ID:
            admin = user + [("admin", "Bot settings (admin)"), ("stats", "Bot stats"), ("broadcast", "Message all users")]
            bot.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in admin],
                     scope={"type": "chat", "chat_id": config.OWNER_ID})
    except TgError as e:
        log.warning("setMyCommands: %s", e)


class JsonFormatter(logging.Formatter):
    def format(self, r):
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)) + "Z", "level": r.levelname, "logger": r.name, "msg": r.getMessage()}
        if r.exc_info:
            out["exc"] = self.formatException(r.exc_info)
        return json.dumps(out, ensure_ascii=False)


def setup_logging() -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter() if config.LOG_FORMAT == "json"
                   else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h], force=True)


def main() -> None:
    setup_logging()
    errs, warns = config.validate()
    for w in warns:
        log.warning("config: %s", w)
    if errs:
        raise SystemExit("Configuration problem:\n  - " + "\n  - ".join(errs))
    bot = Bot(config.BOT_TOKEN)
    bot.me = bot.call("getMe")
    logs = LogChannel(bot)
    archive = Archive(bot)
    archive.restore_if_empty()
    store.init()
    logging.getLogger().addHandler(ChannelLogHandler(logs))
    app = App(bot, logs, archive)
    pool = ThreadPoolExecutor(max_workers=config.WORKERS, thread_name_prefix="upd")

    def shutdown(*_):
        if not stop.is_set():
            log.info("shutting down…")
            stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    webhook = config.MODE == "webhook" and config.PUBLIC_URL
    secret = hashlib.sha256(config.BOT_TOKEN.encode()).hexdigest()[:32]
    srv = serve(app, pool, secret, "/webhook")
    set_commands(bot)
    logs.started("webhook" if webhook else "polling")
    log.info("started as @%s (%s)", bot.me.get("username"), "webhook" if webhook else "polling")
    threading.Thread(target=housekeeping, daemon=True).start()
    if config.KEEPALIVE and config.PUBLIC_URL:
        threading.Thread(target=keepalive, daemon=True).start()
    if webhook:
        bot.call("setWebhook", url=config.PUBLIC_URL + "/webhook", secret_token=secret,
                 allowed_updates=["message", "callback_query"], drop_pending_updates=False, max_connections=40)
        stop.wait()
    else:
        poll(bot, app, pool)
    # ---- graceful shutdown: stop intake, let in-flight work finish, flush logs, final backup
    srv.shutdown()
    pool.shutdown(wait=True, cancel_futures=False)
    logs.stopped()
    time.sleep(0.2)
    logs.drain()
    archive.backup_now()
    store.close()
    log.info("bye")


if __name__ == "__main__":
    main()
