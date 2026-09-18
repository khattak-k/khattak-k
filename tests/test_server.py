"""End-to-end test of the HTTP layer + main-thread bridge with a fake bpy.
Run: python -m pytest tests/  (or python tests/test_server.py)"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_bpy  # noqa: E402

bpy = fake_bpy.install()

from blender_phone_control import bridge, server  # noqa: E402

PORT = 18765
BASE = f"http://127.0.0.1:{PORT}"


class MainLoop:
    """Pretends to be Blender's main thread: ticks app timers until stopped."""

    def __init__(self):
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            bpy.app.timers.tick()
            time.sleep(0.01)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self.thread.join(1)


def req(path, body=None, token=None, raw=False, timeout=5):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    if data:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("X-Token", token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else json.loads(payload))
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, (payload if raw else json.loads(payload))


def setup_module(_=None):
    server.start(PORT)
    bridge.start()


def teardown_module(_=None):
    server.stop()
    bridge.stop()


def test_static_and_ping():
    code, body = req("/", raw=True)
    assert code == 200 and b"<title>Blender Phone Control</title>" in body
    code, body = req("/app.js", raw=True)
    assert code == 200 and b"use strict" in body
    code, body = req("/api/ping")
    assert body["ok"] is True and body["authed"] is False and body["claude_online"] is False


def test_auth_required():
    assert req("/api/state")[0] == 401
    assert req("/api/action", {"action": "undo"})[0] == 401
    assert req("/api/preview.jpg")[0] == 401


def test_phone_message_reaches_inbox_and_reply_comes_back():
    server.clear_messages()
    tok = login()

    code, body = req("/api/send", {"text": "  add a red cube  "}, token=tok)
    assert code == 200 and body["message"]["role"] == "phone" and body["message"]["text"] == "add a red cube"
    assert body["claude_online"] is False
    mid = body["message"]["id"]

    # Claude's relay (loopback, no token) sees only phone messages, and polling marks Claude online.
    code, body = req("/api/inbox?since=0")
    assert code == 200 and [m["id"] for m in body["messages"]] == [mid]
    assert server.status()["claude_online"] is True
    assert req("/api/inbox?since=%d" % mid)[1]["messages"] == []

    code, body = req("/api/reply", {"text": "Done, cube added."})
    assert code == 200 and body["message"]["role"] == "claude"
    rid = body["message"]["id"]

    code, body = req(f"/api/messages?since={mid}", token=tok)
    assert [m["id"] for m in body["messages"]] == [rid] and body["claude_online"] is True
    assert req(f"/api/inbox?since={mid}")[1]["messages"] == [], "relay must not see Claude's own replies"

    assert req("/api/send", {"text": "   "}, token=tok)[0] == 400
    assert req("/api/reply", {"text": ""})[0] == 400
    assert req("/api/clear", {}, token=tok)[0] == 200
    assert req("/api/messages?since=0", token=tok)[1]["messages"] == []


def test_long_poll_wakes_on_new_message_and_stop_cuts_it():
    server.clear_messages()
    tok = login()
    got = {}

    def waiter(since):
        try:
            got[since] = req(f"/api/messages?since={since}&wait=20", token=tok, timeout=30)
        except Exception as e:  # a cut connection is the expected outcome for the second waiter
            got[since] = e

    t = threading.Thread(target=waiter, args=(0,))
    t.start()
    t.join(0.3)
    assert t.is_alive(), "long-poll should block while there are no messages"
    req("/api/send", {"text": "hello"}, token=tok)
    t.join(5)
    assert not t.is_alive()
    assert [m["text"] for m in got[0][1]["messages"]] == ["hello"]

    t = threading.Thread(target=waiter, args=(99,))
    t.start()
    t.join(0.3)
    assert t.is_alive()
    server.stop()
    t.join(3)
    assert not t.is_alive(), "stop() must release/cut a pending long-poll"
    server.start(PORT)
    assert req("/api/ping")[0] == 200


def test_wrong_pin_then_lockout():
    server.rotate_pin()
    code, body = req("/api/auth", {"pin": "nope"})
    assert code == 403 and body["error"] == "wrong PIN"
    for _ in range(server._MAX_FAILED):
        req("/api/auth", {"pin": "nope"})
    code, body = req("/api/auth", {"pin": server._pin})
    assert code == 429, "correct PIN must be rejected while locked out"
    server.rotate_pin()  # clears lockout


def login():
    code, body = req("/api/auth", {"pin": server.status()["pin"]})
    assert code == 200 and body["ok"]
    return body["token"]


def test_state_and_actions_go_through_bridge():
    tok = login()
    with MainLoop():
        code, body = req("/api/state", token=tok)
        assert code == 200
        s = body["state"]
        assert s["file"] == "test.blend"
        assert s["active"]["name"] == "Cube"
        assert [o["name"] for o in s["objects"]] == ["Cube", "Camera"]
        assert s["view"]["shading"] == "SOLID"

        # Orbit changes the view rotation; pan moves the location; zoom scales distance.
        r3d = bpy.context.window_manager.windows[0].screen.areas[0].spaces.active.region_3d
        before = repr(r3d.view_rotation)
        code, body = req("/api/action", {"action": "orbit", "params": {"dx": 0.5, "dy": 0.1}}, token=tok)
        assert code == 200, body
        assert repr(r3d.view_rotation) != before

        req("/api/action", {"action": "zoom", "params": {"factor": 0.5}}, token=tok)
        assert abs(r3d.view_distance - 5.0) < 1e-6

        req("/api/action", {"action": "pan", "params": {"dx": 0.1, "dy": 0.0}}, token=tok)
        assert r3d.view_location != fake_bpy.Vector()

        # Transforms hit the selected object.
        code, body = req("/api/action", {"action": "transform", "params": {"kind": "move", "axis": "z", "value": 2}}, token=tok)
        assert body["state"]["active"]["location"][2] == 2.0
        req("/api/action", {"action": "transform", "params": {"kind": "rotate", "axis": "x", "value": 90}}, token=tok)
        req("/api/action", {"action": "transform", "params": {"kind": "scale", "axis": "y", "value": 2}}, token=tok)
        code, body = req("/api/state", token=tok)
        a = body["state"]["active"]
        assert a["rotation"][0] == 90.0 and a["scale"][1] == 2.0

        # Frame set, shading, and query-string tokens (used by <img> URLs).
        code, body = req("/api/action", {"action": "frame", "params": {"frame": 42}}, token=tok)
        assert body["state"]["frame"] == 42
        code, body = req("/api/action", {"action": "shading", "params": {"type": "wireframe"}}, token=tok)
        assert body["state"]["view"]["shading"] == "WIREFRAME"
        code, body = req(f"/api/state?k={tok}")
        assert code == 200

        # Errors from the main thread come back as clean 400s, not hangs.
        code, body = req("/api/action", {"action": "nope"}, token=tok)
        assert code == 400 and "unknown action" in body["error"]
        code, body = req("/api/action", {"action": "select", "params": {"name": "Ghost"}}, token=tok)
        assert code == 400 and "no object named" in body["error"]
        code, body = req("/api/render/result.jpg", token=tok)
        assert code == 400 and "no finished render" in body["error"]

        # Logout invalidates the token.
        req("/api/logout", {}, token=tok)
        assert req("/api/state", token=tok)[0] == 401


def test_bridge_times_out_when_main_thread_is_stalled():
    tok = login()
    # No MainLoop running -> nothing drains the queue.
    bridge.DEFAULT_TIMEOUT, saved = 1.0, bridge.DEFAULT_TIMEOUT
    try:
        t0 = time.monotonic()
        code, body = req("/api/action", {"action": "undo"}, token=tok, timeout=10)
        assert code == 500 and "timed out" in body["error"]
        assert time.monotonic() - t0 >= 1.0, "should have waited for the bridge timeout"
    finally:
        bridge.DEFAULT_TIMEOUT = saved
        bridge.stop()  # drop the stalled job so it can't run during later tests
        bridge.start()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
