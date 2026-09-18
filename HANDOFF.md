# Handoff — Blender Phone Control

**Branch:** `claude/new-session-xzed82` on `khattak-k/khattak-k`. Local clone on the PC: `D:\Khattak Data\blender-phone-control`.
**Goal:** from a phone, chat with the Claude Code session that drives Blender over MCP, watch the viewport, and optionally use touch controls.

## State (2026-09-18)

Verified against real Blender 5.2 on the Windows PC (previous sessions had no Blender):

- `install.ps1` works (finds 5.2, copies, enables, autostart on; firewall rule needs admin).
- Login, PIN lockout, state, viewport preview (`render.opengl` from the timer, no popup), orbit/pan/zoom, view presets, shading, select, nudges, add primitives, duplicate/delete, play, engine switch, final render + JPEG result: all OK.
- Orbit math matches Blender's turntable drag exactly (checked against the source convention and numerically).
- Fixed: undo failed because timer-run operators push no undo steps → `ops.run_action` now pushes one per editing action; undo/redo report "nothing to undo" instead of a poll error.
- Fixed: engine names are probed at runtime (`ops.available_engines`) and sent in state; 5.2 has `BLENDER_EEVEE`, `BLENDER_WORKBENCH`, `CYCLES`.
- Fixed: `server.stop()` now closes live keep-alive/long-poll sockets; before, handler threads kept answering with the old code after an addon reload.
- Added: chat. `/api/send` + `/api/messages` (phone, PIN-authed, long-poll) and `/api/inbox` + `/api/reply` (loopback only). `claude_relay.py watch` prints each phone message as one line; Claude runs it under Monitor so every message wakes the session; `claude_relay.py reply "..."` posts back. The page opens on the Chat tab; the gear in the header toggles the control tabs and undo/redo/save.

Tests: `python -m pytest tests/` → 7 pass (fake bpy; the chat layer is fully covered, Blender-side ops are not).

## To pick this up in a new session

1. Blender open with the addon (autostart) → N ▸ Phone shows the PIN and "Claude: listening/not listening".
2. Arm the relay: `Monitor` tool with `python -u claude_relay.py watch` (30 min max, re-arm on expiry). Each event is `[phone #N] text`: that is the user talking from their phone. Act on it via the Blender MCP, then `python claude_relay.py reply "…"`.
3. Phone: `http://192.168.1.8:8765` (PC's LAN address at time of writing).

## Not yet verified

- Access from an actual phone over Wi‑Fi (firewall rule / Private network). Everything so far was tested from the PC's own browser.
- `Render Animation` (only still renders were run).
- Blender was force-restarted once during testing; if the user had unsaved work in the instance launched at ~05:05, it was lost.
