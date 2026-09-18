"""Bridge between the phone chat page (served by the Blender addon) and a
Claude Code session on this PC.

    python claude_relay.py watch            # print each new phone message (one line each)
    python claude_relay.py reply "text"     # post Claude's reply back to the phone
    python claude_relay.py reply -          # reply text from stdin
    python claude_relay.py peek             # print unread messages once and exit

Claude runs `watch` under its Monitor tool: every line printed becomes a
notification that wakes the session with the message. `reply` shows Claude's
answer in the phone's chat thread. Both only work from this PC (the addon
refuses /api/inbox and /api/reply from other machines).
"""
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = int(os.environ.get("BLENDER_PHONE_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"
STATE = os.path.join(tempfile.gettempdir(), f"blender_phone_relay_{PORT}.last")


def _call(path, body=None, timeout=40):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _load_last():
    try:
        with open(STATE) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _save_last(n):
    try:
        with open(STATE, "w") as f:
            f.write(str(n))
    except OSError:
        pass


def _emit(m):
    text = " ".join(m["text"].split())  # one line per message
    print(f"[phone #{m['id']}] {text}", flush=True)


def watch():
    last = _load_last()
    down = False
    while True:
        try:
            data = _call(f"/api/inbox?since={last}&wait=25")
        except (urllib.error.URLError, OSError, ValueError):
            if not down:
                print("[relay] Blender phone server unreachable; retrying", flush=True)
                down = True
            time.sleep(3)
            continue
        if down:
            print("[relay] Blender phone server back", flush=True)
            down = False
        for m in data.get("messages", []):
            if m["id"] > last:
                _emit(m)
                last = m["id"]
                _save_last(last)


def peek():
    last = _load_last()
    data = _call(f"/api/inbox?since={last}&wait=0")
    for m in data.get("messages", []):
        _emit(m)
        last = max(last, m["id"])
    _save_last(last)


def reply(text):
    text = text.strip()
    if not text:
        sys.exit("empty reply")
    data = _call("/api/reply", {"text": text})
    print(f"replied as message #{data['message']['id']}")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "watch"
    if cmd == "watch":
        watch()
    elif cmd == "peek":
        peek()
    elif cmd == "reply":
        text = " ".join(argv[2:])
        if text == "-" or not text:
            text = sys.stdin.read()
        reply(text)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except KeyboardInterrupt:
        pass
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"cannot reach the Blender phone server on port {PORT}: {e.reason}")
