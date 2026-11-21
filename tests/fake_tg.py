"""A tiny fake Telegram Bot API server (stdlib) for tests: records every call, serves uploaded files."""
import json
import re
import threading
import time
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Fake:
    def __init__(self, port=0):
        self.calls, self.files, self.updates = [], {}, []
        self.mid, self.lock = 100, threading.Lock()
        self.chats = {}          # chat_id -> getChat result
        self.members = {}        # (chat_id, user_id) -> getChatMember result
        self.fail = {}           # method -> description (forces a 400)
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _json(self, obj, code=200):
                b = json.dumps(obj).encode()
                self.send_response(code); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def do_GET(self):
                m = re.match(r"/file/bot[^/]+/(.+)", self.path)
                if m and m.group(1) in outer.files:
                    b = outer.files[m.group(1)]
                    self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
                else:
                    self.send_response(404); self.end_headers()

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n)
                method = self.path.rsplit("/", 1)[-1]; ct = self.headers.get("Content-Type", "")
                p, files = {}, {}
                if "multipart" in ct:
                    msg = BytesParser(policy=default).parsebytes(b"Content-Type: " + ct.encode() + b"\r\n\r\n" + body)
                    for part in msg.iter_parts():
                        name = part.get_param("name", header="content-disposition")
                        fn = part.get_filename()
                        data = part.get_payload(decode=True)
                        if fn: files[name] = data
                        else: p[name] = data.decode()
                elif body:
                    p = json.loads(body)
                for k in ("chat_id", "user_id"):
                    if isinstance(p.get(k), str) and re.fullmatch(r"-?\d+", p[k]):
                        p[k] = int(p[k])
                for k in ("reply_markup", "media", "commands", "scope"):
                    if isinstance(p.get(k), str):
                        try: p[k] = json.loads(p[k])
                        except Exception: pass
                with outer.lock:
                    outer.calls.append({"m": method, "p": p, "files": files, "t": time.time()})
                if method in outer.fail:
                    return self._json({"ok": False, "error_code": 400, "description": outer.fail[method]}, 400)
                res = outer.result(method, p, files)
                with outer.lock:
                    for c in reversed(outer.calls):
                        if c["m"] == method and c["p"] is p:
                            c["r"] = res
                            break
                self._json({"ok": True, "result": res})

        self.srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"

    def result(self, m, p, files):
        with self.lock:
            self.mid += 1
            mid = self.mid
        if m == "getMe": return {"id": 999, "username": "fakebot", "first_name": "Fake"}
        if m == "getUpdates":
            time.sleep(0.2)
            with self.lock:
                return [self.updates.pop(0)] if self.updates else []
        if m in ("sendMessage", "editMessageText", "sendDocument", "editMessageReplyMarkup", "copyMessage", "editMessageCaption"):
            return {"message_id": p.get("message_id", mid), "document": {"file_id": "D%d" % mid, "file_name": "x"}}
        if m in ("sendPhoto", "editMessageMedia"):
            fid = "PH%d" % mid
            data = files.get("photo") or files.get("file")
            if data: self.files["photos/" + fid] = data
            media = p.get("media")
            if isinstance(media, dict) and media.get("media") and not str(media["media"]).startswith("attach://"):
                fid = media["media"]
            return {"message_id": p.get("message_id", mid), "photo": [{"file_id": "small"}, {"file_id": fid}]}
        if m == "getFile":
            fid = p["file_id"]; path = "photos/" + fid
            return {"file_id": fid, "file_path": path, "file_size": len(self.files.get(path, b""))}
        if m == "getChat":
            return self.chats.get(p.get("chat_id"), {"id": p.get("chat_id"), "type": "channel", "title": "Chan"})
        if m == "getChatMember":
            return self.members.get((p.get("chat_id"), p.get("user_id")), {"status": "administrator", "can_post_messages": True})
        return True

    def of(self, method):
        return [c for c in self.calls if c["m"] == method]

    def last(self, method):
        xs = self.of(method)
        return xs[-1] if xs else None

    def buttons(self, call):
        mk = call["p"].get("reply_markup") or {}
        return [b for row in mk.get("inline_keyboard", []) for b in row]

    def clear(self): self.calls.clear()
