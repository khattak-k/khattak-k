# Handoff — Blender Phone Control

**Branch:** `claude/new-session-xzed82` on `khattak-k/khattak-k` (2 commits, pushed, no PR opened).
**Goal:** use Blender on the Windows PC from a phone via a touch web UI served by a Blender addon.

## State

Built and pushed, but **never run against real Blender** — the dev session was a cloud container
with no Blender. Everything that touches `bpy` is written to the documented API and unverified.
The HTTP/auth/bridge layers *are* tested (`python -m pytest tests/`, 5/5 pass, fake `bpy`).

```
blender_phone_control/   the addon (install this folder / zip)
  __init__.py            registration, prefs (port, autostart), N-panel "Phone" tab
  bridge.py              queue + bpy.app.timers → runs work on Blender's main thread
  server.py              ThreadingHTTPServer, PIN → token auth, lockout, static files
  ops.py                 every action the phone can trigger (ACTIONS dict at bottom)
  web/                   phone UI: index.html, style.css, app.js (no build step)
tests/                   fake_bpy.py + test_server.py
install.ps1              one-command Windows installer (untested: no PowerShell in dev container)
build_zip.py             → dist/blender_phone_control.zip
README.md                install / usage / troubleshooting
```

## Next steps (in order)

1. **Install on the PC.** Admin PowerShell:
   `irm https://raw.githubusercontent.com/khattak-k/khattak-k/claude/new-session-xzed82/install.ps1 | iex`
   (needs the repo public; otherwise clone and run `.\install.ps1`). Fall back to manual:
   `python build_zip.py` → Preferences ▸ Add-ons ▸ Install from Disk.
2. **Smoke test in Blender.** Window ▸ Toggle System Console first so tracebacks are visible.
   N ▸ Phone ▸ Start Server. On the PC itself open `http://127.0.0.1:8765`, enter PIN.
   Check in this order — each is a separate risk:
   - page loads + login → server.py OK
   - viewport image appears → `ops.capture_preview` (`render.opengl` + `temp_override`) OK
   - drag orbits → `view_orbit` quaternion math + sign; toggle *Invert orbit* if backwards
   - Object tab nudges move the cube → `transform` + `_ensure_object_mode`
   - Add ▸ Cube → operators under `temp_override(**_override())`
   - Render Image → `INVOKE_DEFAULT` render + `render_complete` handler saving JPEG
3. **Then from the phone** on the same Wi-Fi. If it can't connect: firewall rule / network must be *Private*.

## Known unknowns / likely first bugs

- `render_display_type = "NONE"` during preview: if a render window still pops, or preview
  errors, check `bpy.context.preferences.view` access from a timer.
- `render.opengl(view_context=True)` needs `window/screen/area/region` in the override;
  if it complains about context, also pass `space_data`.
- Engine names differ by version (`BLENDER_EEVEE` vs `BLENDER_EEVEE_NEXT`); UI adds unknown
  ones to the dropdown, so an error here is cosmetic.
- Does `render_complete` fire for viewport (opengl) renders? Guarded by `_expecting_render`
  and by pausing previews while a render runs, so it should be safe — verify.
- Undo from a timer (`bpy.ops.ed.undo`) can be flaky in some versions.
- `_autostart` timer reads addon prefs 1 s after register; harmless if it fails (prints).

## Conventions

- Phone can only call names in `ops.ACTIONS`; never expose arbitrary Python.
- Anything touching `bpy` goes through `bridge.submit` — never from the HTTP thread.
- Errors from ops surface as HTTP 400 + toast on phone (last line); full traceback in Blender console.
- Adding an action: function in `ops.py` → `ACTIONS` entry → `data-action` button in `index.html`.
- Commits so far include a `Co-Authored-By` / `Claude-Session` trailer; keep or drop as you like.
