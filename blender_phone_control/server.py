"""Threaded HTTP server that the phone talks to. Runs off the main thread;
anything touching bpy goes through bridge.submit."""
import json
import mimetypes
import os
import secrets
import socket
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import bridge, ops

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
_STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}

_server = None
_thread = None
_port = 0

_lock = threading.Lock()
_pin = ""
_sessions = set()
_failed = {"count": 0, "locked_until": 0.0}
_MAX_FAILED = 8
_LOCKOUT = 60.0

# --- chat thread (phone <-> Claude) -----------------------------------------
_cond = threading.Condition(_lock)
_messages = []          # [{"id", "role": "phone"|"claude", "text", "ts"}]
_next_id = 1
_MAX_MESSAGES = 500
_MAX_TEXT = 8000
_last_inbox_poll = 0.0  # when Claude's relay last asked for messages
_CLAUDE_ONLINE_WINDOW = 45.0
_MAX_WAIT = 30.0        # long-poll cap
_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
_connections = set()    # open client sockets, so stop() can cut keep-alive/long-poll connections


def claude_online():
    return time.monotonic() - _last_inbox_poll < _CLAUDE_ONLINE_WINDOW


def post_message(role, text):
    """Append a chat message (any thread). Returns the stored dict."""
    global _next_id
    text = str(text).strip()
    if not text:
        raise ValueError("empty message")
    if len(text) > _MAX_TEXT:
        raise ValueError(f"message too long (max {_MAX_TEXT} chars)")
    with _cond:
        msg = {"id": _next_id, "role": role, "text": text, "ts": time.time()}
        _next_id += 1
        _messages.append(msg)
        del _messages[:-_MAX_MESSAGES]
        _cond.notify_all()
    return msg


def messages_since(since, role=None, wait=0.0):
    """Messages with id > since (optionally one role only). Blocks up to
    ``wait`` seconds for a new one if there are none yet."""
    deadline = time.monotonic() + min(float(wait), _MAX_WAIT)
    with _cond:
        while True:
            out = [m for m in _messages if m["id"] > since and (role is None or m["role"] == role)]
            if out:
                return out
            remaining = deadline - time.monotonic()
            if remaining <= 0 or _server is None:
                return []
            _cond.wait(remaining)


def clear_messages():
    with _cond:
        _messages.clear()
        _cond.notify_all()


def _new_pin():
    return f"{secrets.randbelow(1_000_000):06d}"


def rotate_pin():
    global _pin
    with _lock:
        _pin = _new_pin()
        _sessions.clear()
        _failed.update(count=0, locked_until=0.0)


def _lan_addresses():
    addrs = []
    # The UDP "connect" trick finds the interface that routes to the LAN
    # without sending anything.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        addrs.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127.") and ip not in addrs:
                addrs.append(ip)
    except OSError:
        pass
    return addrs or ["<this PC's IP>"]


def status():
    return {
        "running": _server is not None,
        "port": _port,
        "pin": _pin,
        "sessions": len(_sessions),
        "messages": len(_messages),
        "claude_online": claude_online(),
        "addresses": _lan_addresses() if _server is not None else [],
    }


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # A phone dropping its connection mid-request (or stop() cutting it) is not worth a traceback.
        if isinstance(sys.exc_info()[1], (ConnectionError, OSError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    server_version = "BlenderPhoneControl/0.2"
    protocol_version = "HTTP/1.1"
    timeout = 90  # idle keep-alive connections close on their own

    def log_message(self, fmt, *args):  # keep Blender's console quiet
        pass

    def setup(self):
        super().setup()
        with _lock:
            _connections.add(self.connection)

    def finish(self):
        try:
            super().finish()
        finally:
            with _lock:
                _connections.discard(self.connection)

    # -- helpers ---------------------------------------------------------

    def _send(self, code, body, ctype="application/json", cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        if n > 65536:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def _token(self, query):
        tok = self.headers.get("X-Token")
        if not tok:
            tok = (query.get("k") or [""])[0]
        return tok

    def _authed(self, query):
        tok = self._token(query)
        with _lock:
            return bool(tok) and tok in _sessions

    def _error(self, code, msg):
        self._send(code, {"ok": False, "error": msg})

    def _is_loopback(self):
        return self.client_address[0] in _LOOPBACK

    @staticmethod
    def _int(query, key, default):
        try:
            return int((query.get(key) or [default])[0])
        except ValueError:
            return default

    # -- routes ----------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)

        if path in _STATIC:
            return self._static(_STATIC[path])

        if not path.startswith("/api/"):
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        if path == "/api/ping":
            return self._send(HTTPStatus.OK, {"ok": True, "authed": self._authed(query), "claude_online": claude_online()})

        if path == "/api/inbox":
            # Claude's relay (claude_relay.py): this PC only, no PIN needed.
            global _last_inbox_poll
            if not self._is_loopback():
                return self._error(HTTPStatus.FORBIDDEN, "inbox is only available from this PC")
            with _lock:
                _last_inbox_poll = time.monotonic()
            msgs = messages_since(self._int(query, "since", 0), role="phone", wait=self._int(query, "wait", 0))
            with _lock:
                _last_inbox_poll = time.monotonic()
            return self._send(HTTPStatus.OK, {"ok": True, "messages": msgs})

        if not self._authed(query):
            return self._error(HTTPStatus.UNAUTHORIZED, "unauthorized")

        if path == "/api/messages":
            msgs = messages_since(self._int(query, "since", 0), wait=self._int(query, "wait", 0))
            return self._send(HTTPStatus.OK, {"ok": True, "messages": msgs, "claude_online": claude_online()})

        try:
            if path == "/api/state":
                return self._send(HTTPStatus.OK, {"ok": True, "state": bridge.submit(ops.get_state), "claude_online": claude_online()})
            if path == "/api/preview.jpg":
                w = int((query.get("w") or ["720"])[0])
                w = max(160, min(1920, w))
                data = bridge.submit(ops.capture_preview, w, timeout=15.0)
                return self._send(HTTPStatus.OK, data, "image/jpeg")
            if path == "/api/render/result.jpg":
                data = bridge.submit(ops.render_result_bytes)
                return self._send(HTTPStatus.OK, data, "image/jpeg")
        except bridge.BridgeError as e:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, _short(e))
        except Exception as e:
            return self._error(HTTPStatus.BAD_REQUEST, _short(e))
        return self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self):
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)
        try:
            body = self._json_body()
        except Exception as e:
            return self._error(HTTPStatus.BAD_REQUEST, f"bad json: {e}")

        if path == "/api/auth":
            return self._auth(body)

        if path == "/api/reply":  # Claude's answer, this PC only
            if not self._is_loopback():
                return self._error(HTTPStatus.FORBIDDEN, "reply is only available from this PC")
            try:
                msg = post_message("claude", body.get("text", ""))
            except ValueError as e:
                return self._error(HTTPStatus.BAD_REQUEST, str(e))
            return self._send(HTTPStatus.OK, {"ok": True, "message": msg})

        if not self._authed(query):
            return self._error(HTTPStatus.UNAUTHORIZED, "unauthorized")

        if path == "/api/send":
            try:
                msg = post_message("phone", body.get("text", ""))
            except ValueError as e:
                return self._error(HTTPStatus.BAD_REQUEST, str(e))
            return self._send(HTTPStatus.OK, {"ok": True, "message": msg, "claude_online": claude_online()})
        if path == "/api/clear":
            clear_messages()
            return self._send(HTTPStatus.OK, {"ok": True})

        try:
            if path == "/api/action":
                state = bridge.submit(ops.run_action, body.get("action"), body.get("params") or {})
                return self._send(HTTPStatus.OK, {"ok": True, "state": state})
            if path == "/api/logout":
                with _lock:
                    _sessions.discard(self._token(query))
                return self._send(HTTPStatus.OK, {"ok": True})
        except bridge.BridgeError as e:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, _short(e))
        except Exception as e:
            return self._error(HTTPStatus.BAD_REQUEST, _short(e))
        return self._error(HTTPStatus.NOT_FOUND, "not found")

    def _auth(self, body):
        pin = str(body.get("pin", ""))
        with _lock:
            now = time.monotonic()
            if now < _failed["locked_until"]:
                wait = int(_failed["locked_until"] - now) + 1
                return self._error(HTTPStatus.TOO_MANY_REQUESTS, f"too many attempts, try again in {wait}s")
            if not secrets.compare_digest(pin, _pin):
                _failed["count"] += 1
                if _failed["count"] >= _MAX_FAILED:
                    _failed.update(count=0, locked_until=now + _LOCKOUT)
                return self._error(HTTPStatus.FORBIDDEN, "wrong PIN")
            _failed["count"] = 0
            tok = secrets.token_urlsafe(24)
            _sessions.add(tok)
        self._send(HTTPStatus.OK, {"ok": True, "token": tok})

    def _static(self, name):
        full = os.path.join(WEB_DIR, name)
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            return self._error(HTTPStatus.NOT_FOUND, "missing web asset")
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(HTTPStatus.OK, data, ctype)


def _short(e):
    s = str(e).strip()
    # Tracebacks from the bridge: keep only the last line for the phone.
    return s.splitlines()[-1] if s else e.__class__.__name__


def start(port):
    global _server, _thread, _port, _pin
    if _server is not None:
        return
    if not _pin:
        _pin = _new_pin()
    srv = _Server(("0.0.0.0", port), Handler)
    t = threading.Thread(target=srv.serve_forever, name="blender-phone-control", daemon=True)
    t.start()
    _server, _thread, _port = srv, t, port
    print(f"[Phone Control] listening on http://0.0.0.0:{port}  PIN {_pin}")


def stop():
    global _server, _thread
    if _server is None:
        return
    srv = _server
    srv.shutdown()          # stop accepting
    srv.server_close()
    with _cond:
        _server, _thread = None, None
        _cond.notify_all()  # release long-polls
        conns = list(_connections)
    # shutdown() does not touch connections already being served; without
    # this, keep-alive sockets keep answering with the old code after a reload.
    for c in conns:
        try:
            c.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            c.close()
        except OSError:
            pass
    print("[Phone Control] stopped")
