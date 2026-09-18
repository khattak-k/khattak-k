# Blender Phone Control

Talk to the Claude session that is driving Blender, from your phone, and watch
the viewport while it works. A small addon starts an HTTP server inside
Blender; you open a page on your phone (same Wi‑Fi), enter a PIN, and get:

- **Chat** (default): a textbox. What you type is picked up by Claude Code on
  the PC (via `claude_relay.py`), Claude does the work in Blender through its
  MCP connection, and its replies show up in the same thread.
- **Live viewport preview** with touch orbit / pan / pinch‑zoom.
- **Controls** (hidden behind the gear in the header): view presets, shading,
  transform nudges, add primitives, timeline, render. Undo/redo/save live
  there too.

No app store, no cloud, no extra software on the phone: just a browser.

```
phone ──HTTP over LAN──▶ Blender addon (server thread)
                           ├─ /api/send, /api/messages ── chat thread ── /api/inbox, /api/reply ──▶ claude_relay.py ──▶ Claude Code
                           └─ /api/action, /api/preview.jpg ──queue──▶ Blender main thread (bpy)
```

## Install (Windows)

**One command** (PowerShell, ideally "Run as Administrator" so it can add the firewall rule):

```powershell
irm https://raw.githubusercontent.com/khattak-k/khattak-k/claude/new-session-xzed82/install.ps1 | iex
```

Or from a clone: `powershell -ExecutionPolicy Bypass -File .\install.ps1`.
It finds `blender.exe`, copies the addon into `%APPDATA%\Blender Foundation\Blender\<ver>\scripts\addons`,
enables it with autostart, adds the firewall rule, and prints the URL for your phone.
Pass `-BlenderExe 'C:\...\blender.exe'` if it picks the wrong Blender.

**Manually:** `python build_zip.py`, then in Blender **Edit ▸ Preferences ▸ Add-ons ▸ Install from Disk…**,
pick `dist/blender_phone_control.zip`, enable **Phone Control**.

The first time the server starts, Windows may ask whether to let Blender
through the firewall: allow it on **Private** networks. Your Wi‑Fi must be set
to Private in Windows for the phone to reach the PC.

## Use

1. Start Blender. The server starts on port 8765 (N ▸ **Phone** tab shows the
   URL and the 6‑digit PIN, and whether Claude is listening).
2. In the Claude Code session that has the Blender MCP connected, arm the relay
   once per session (Claude runs this under its Monitor tool so each phone
   message wakes it):
   ```
   python claude_relay.py watch
   ```
   Claude answers with `python claude_relay.py reply "text"`.
3. On the phone open `http://<pc-ip>:8765`, enter the PIN, type.

`/api/inbox` and `/api/reply` only answer requests from the PC itself, so a
phone on the LAN cannot read Claude's queue or forge replies.

## Layout

```
blender_phone_control/   the addon
  __init__.py            registration, prefs (port, autostart), N-panel "Phone" tab
  bridge.py              queue + bpy.app.timers → runs work on Blender's main thread
  server.py              ThreadingHTTPServer, PIN→token auth, lockout, chat thread, static files
  ops.py                 every phone control action (ACTIONS dict at bottom)
  web/                   index.html / style.css / app.js, no build step
claude_relay.py          watch / reply / peek: the Claude side of the chat
tests/                   fake_bpy.py + test_server.py   (python -m pytest tests/)
install.ps1              one-command Windows installer
build_zip.py             → dist/blender_phone_control.zip
```

Conventions: the phone can only call names in `ops.ACTIONS`; all `bpy` access
goes through `bridge.submit`; op errors become HTTP 400 and a toast on the
phone, with the full traceback in Blender's console. Scene-editing actions
push an undo step so the phone's Undo works.
