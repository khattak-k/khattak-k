# Blender Phone Control

Drive Blender on your PC from your phone. A small addon starts an HTTP server
inside Blender; you open a page on your phone (same Wi‑Fi) and get a live
viewport preview with touch orbit / pan / pinch‑zoom, plus buttons for the
things you do most: view presets, shading, nudging transforms, adding
primitives, scrubbing the timeline, and kicking off renders.

No app store, no cloud, no extra software on the phone — just a browser.

```
phone ──HTTP over LAN──▶ Blender addon (server thread) ──queue──▶ Blender main thread (bpy)
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

**Manually:**

1. Build the zip (or grab `dist/blender_phone_control.zip` if you already have one):
   ```
   python build_zip.py
   ```
2. In Blender: **Edit ▸ Preferences ▸ Add-ons ▸ ⌄ ▸ Install from Disk…**
   (Blender 4.2+; on 3.x/4.0/4.1 it's the **Install…** button) and pick the zip.
3. Tick the checkbox to enable **Phone Control**.
4. In the 3D Viewport press **N**, open the **Phone** tab, click **Start Server**.
   The panel shows the URL(s) and a 6‑digit PIN.

The first time you start it, Windows will ask whether to let Blender through
the firewall — allow it on **Private** networks. If you dismissed that dialog,
allow it manually: *Windows Security ▸ Firewall & network protection ▸ Allow an
app through firewall ▸ blender.exe ▸ Private*. Or from an admin PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Blender Phone Control" -Direction Inbound -Protocol TCP -LocalPort 8765 -Profile Private -Action Allow
```

Make sure your Wi‑Fi is set to **Private** (not Public) in Windows network settings,
or the rule won't apply.

## Use

1. Phone on the same Wi‑Fi as the PC. Open `http://<PC IP>:8765` (the panel shows it).
2. Enter the PIN. You stay logged in until you press **New PIN** in Blender or stop the server.
3. Add it to your home screen for a full‑screen, app‑like feel (Share ▸ Add to Home Screen).

| Gesture / tab | Does |
|---|---|
| 1 finger drag | orbit (turntable) |
| 2 finger drag | pan |
| pinch | zoom |
| **View** | front/side/top/camera, frame selected/all, shading mode, preview quality, persp/ortho |
| **Object** | pick the active object, move/rotate/scale by step on X/Y/Z, duplicate, hide, delete, smooth/flat, apply transforms |
| **Add** | mesh primitives, empty, light, camera (at the 3D cursor) |
| **Anim** | play/pause, frame stepping, timeline slider |
| **Render** | pick engine, render image/animation; the still shows up on the phone when done |
| header | undo · redo · save |

The preview is a viewport render (`render.opengl`) of your actual 3D view, so it
reflects the current shading mode and whatever you do on the desktop too.

## Settings

**Edit ▸ Preferences ▸ Add-ons ▸ Phone Control**: port (default 8765) and
*Start server when Blender opens*.

## Security notes

- LAN only. Don't port‑forward this; there's no TLS.
- PIN is 6 digits, regenerated each Blender session. 8 wrong attempts locks
  login for 60 s. **New PIN** kicks every connected phone.
- The phone can only trigger the fixed set of actions in `ops.py` — it cannot
  run arbitrary Python.

## Development

```
python -m pytest tests/      # exercises the server + bridge with a fake bpy
python build_zip.py          # -> dist/blender_phone_control.zip
```

Layout:

- `blender_phone_control/__init__.py` – addon registration, preferences, sidebar panel
- `blender_phone_control/server.py` – threaded HTTP server, PIN auth, static files
- `blender_phone_control/bridge.py` – queue + `bpy.app.timers` that runs work on Blender's main thread (bpy isn't thread‑safe)
- `blender_phone_control/ops.py` – every Blender operation the phone can trigger
- `blender_phone_control/web/` – the phone UI (vanilla HTML/CSS/JS, no build step)

To add an action: write a function in `ops.py`, register it in `ACTIONS`, and add
a `data-action` button in `web/index.html` (the generic click handler in
`app.js` posts it).

## Troubleshooting

- **Page won't load** – firewall (see above), or phone and PC on different networks
  (guest Wi‑Fi isolates clients). Test on the PC itself first: `http://127.0.0.1:8765`.
- **"Blender unreachable" after it worked** – Blender is busy (modal operator,
  file dialog, heavy render). Actions wait up to 30 s for the main thread.
- **"no 3D Viewport open"** – the addon needs at least one 3D Viewport area in
  Blender's current window.
- **Preview looks different from the desktop** – it's a viewport *render*, which
  omits overlays like the grid and gizmos by default.
