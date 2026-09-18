(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  let token = "";
  try { token = localStorage.getItem("bpc_token") || ""; } catch (_) {}
  let state = null;
  let previewWidth = 720;
  let invertOrbit = false;
  try { invertOrbit = localStorage.getItem("bpc_invert") === "1"; } catch (_) {}
  const xf = { kind: "move", step: 0.1 };
  const STEPS = { move: [0.01, 0.1, 1, 10], rotate: [1, 5, 15, 90], scale: [1.01, 1.1, 1.5, 2] };
  const ENGINE_LABELS = { BLENDER_EEVEE: "EEVEE", BLENDER_EEVEE_NEXT: "EEVEE", CYCLES: "Cycles", BLENDER_WORKBENCH: "Workbench", HYDRA_STORM: "Hydra Storm" };

  // ---------------------------------------------------------------- API

  async function api(path, opts = {}) {
    const headers = { "X-Token": token };
    if (opts.body) headers["Content-Type"] = "application/json";
    let res;
    try {
      res = await fetch(path, { method: opts.body ? "POST" : "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
    } catch (e) {
      setConn(false);
      throw new Error("Blender unreachable");
    }
    if (res.status === 401) { showLogin(); throw new Error("Session expired — enter the PIN again"); }
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "error");
    setConn(true);
    if ("claude_online" in data) setClaude(data.claude_online);
    return data;
  }

  async function action(name, params = {}) {
    try {
      const data = await api("/api/action", { body: { action: name, params } });
      applyState(data.state);
      bumpPreview();
    } catch (e) {
      toast(e.message);
    }
  }

  // ------------------------------------------------------------- login

  function showLogin() {
    token = "";
    try { localStorage.removeItem("bpc_token"); } catch (_) {}
    $("#login").hidden = false;
    $("#pin").focus();
  }

  $("#login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const pin = $("#pin").value.trim();
    $("#login-error").textContent = "";
    try {
      const res = await fetch("/api/auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin }) });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error);
      token = data.token;
      try { localStorage.setItem("bpc_token", token); } catch (_) {}
      $("#login").hidden = true;
      $("#pin").value = "";
      boot();
    } catch (e) {
      $("#login-error").textContent = e.message || "Could not connect";
    }
  });

  // -------------------------------------------------------------- state

  function setConn(ok) {
    const d = $("#conn");
    d.classList.toggle("bad", !ok);
    d.classList.toggle("ok", ok && !(state && state.dirty));
    d.classList.toggle("dirty", ok && !!(state && state.dirty));
  }

  function applyState(s) {
    state = s;
    $("#file").textContent = s.file + (s.dirty ? " *" : "");
    setConn(true);

    if (s.view) {
      $("#hud-shading").textContent = s.view.shading.toLowerCase();
      $("#hud-persp").textContent = s.view.perspective.toLowerCase();
      $$("#shading button").forEach((b) => b.classList.toggle("on", b.dataset.type === s.view.shading));
    }

    // objects
    const sel = $("#obj-select");
    const names = s.objects.map((o) => o.name);
    if (sel.dataset.sig !== names.join("\n")) {
      sel.dataset.sig = names.join("\n");
      sel.innerHTML = "";
      for (const o of s.objects) {
        const opt = document.createElement("option");
        opt.value = o.name;
        opt.textContent = `${o.hidden ? "◌ " : ""}${o.name}  (${o.type.toLowerCase()})`;
        sel.appendChild(opt);
      }
    }
    if (s.active) {
      sel.value = s.active.name;
      $("#xf-name").textContent = "· " + s.active.name;
      const vals = s.active[{ move: "location", rotate: "rotation", scale: "scale" }[xf.kind]];
      ["x", "y", "z"].forEach((a, i) => { $("#val-" + a).textContent = fmt(vals[i]); });
    } else {
      $("#xf-name").textContent = "· none";
      ["x", "y", "z"].forEach((a) => { $("#val-" + a).textContent = "–"; });
    }

    // animation
    $("#frame-out").textContent = s.frame;
    $("#frame-range").textContent = `${s.frame_start} – ${s.frame_end}`;
    const slider = $("#frame-slider");
    slider.min = s.frame_start; slider.max = s.frame_end;
    if (!slider.matches(":active")) slider.value = s.frame;
    $("#btn-play").innerHTML = s.playing ? "&#10074;&#10074;" : "&#9654;";

    // render
    const eng = $("#engine");
    const engines = s.engines || [];
    if (eng.dataset.sig !== engines.join(",")) {
      eng.dataset.sig = engines.join(",");
      eng.innerHTML = "";
      for (const id of engines) {
        const opt = document.createElement("option"); opt.value = id; opt.textContent = ENGINE_LABELS[id] || id; eng.appendChild(opt);
      }
    }
    if (![...eng.options].some((o) => o.value === s.engine)) {
      const opt = document.createElement("option"); opt.value = s.engine; opt.textContent = s.engine; eng.appendChild(opt);
    }
    eng.value = s.engine;
    $("#res").textContent = `${s.resolution[0]}×${s.resolution[1]} @ ${s.resolution[2]}%`;
    renderStatus(s.render);
  }

  function fmt(v) { return Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(2); }

  let lastRenderStatus = "";
  function renderStatus(r) {
    const el = $("#render-status");
    const t = r.status === "running" ? `rendering… ${Math.round((Date.now() / 1000) - r.started)}s`
      : r.status === "done" ? `done in ${Math.round(r.finished - r.started)}s`
      : r.status === "error" ? "error: " + r.message : r.status;
    el.textContent = t;
    if (r.status === "done" && lastRenderStatus !== "done") {
      const url = `/api/render/result.jpg?k=${encodeURIComponent(token)}&t=${Date.now()}`;
      $("#render-result").src = url; $("#render-result").hidden = false;
      $("#render-download").href = url; $("#render-download").hidden = false;
    }
    if (r.status !== "done") { $("#render-result").hidden = true; $("#render-download").hidden = true; }
    lastRenderStatus = r.status;
  }

  async function pollState() {
    try {
      const data = await api("/api/state");
      applyState(data.state);
    } catch (e) { /* conn dot already updated */ }
  }

  // ------------------------------------------------------------ preview

  const img = $("#preview");
  let previewBusy = false, previewWanted = false, previewTimer = null;

  function bumpPreview() { previewWanted = true; if (!previewBusy) fetchPreview(); }

  async function fetchPreview() {
    if (previewBusy || document.hidden || !token) return;
    previewBusy = true; previewWanted = false;
    clearTimeout(previewTimer);
    try {
      const res = await fetch(`/api/preview.jpg?w=${previewWidth}&k=${encodeURIComponent(token)}`);
      if (res.status === 401) { showLogin(); return; }
      if (!res.ok) throw new Error("preview failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      img.onload = () => URL.revokeObjectURL(img.dataset.prev || "");
      img.dataset.prev = img.src; img.src = url;
      setConn(true);
    } catch (e) {
      setConn(false);
    } finally {
      previewBusy = false;
      // Fast follow-up when the user is interacting, relaxed otherwise.
      previewTimer = setTimeout(fetchPreview, previewWanted || pointers.size ? 40 : 700);
    }
  }

  document.addEventListener("visibilitychange", () => { if (!document.hidden) fetchPreview(); });

  // ----------------------------------------------------------- gestures

  const vp = $("#viewport");
  const pointers = new Map();
  let pending = { dx: 0, dy: 0, px: 0, py: 0, zoom: 1 };
  let lastPinch = null, flushTimer = null;
  const ORBIT_SPEED = 0.0075;   // radians per pixel

  vp.addEventListener("pointerdown", (e) => {
    vp.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    lastPinch = null;
    $("#vp-hint").classList.add("gone");
  });
  vp.addEventListener("pointermove", (e) => {
    const p = pointers.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;

    if (pointers.size === 1) {
      const s = invertOrbit ? -1 : 1;
      pending.dx += dx * ORBIT_SPEED * s;
      pending.dy += dy * ORBIT_SPEED * s;
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
      if (lastPinch) {
        pending.zoom *= lastPinch.dist / Math.max(1, dist);
        pending.px += (cx - lastPinch.cx) / vp.clientWidth;
        pending.py += (cy - lastPinch.cy) / vp.clientWidth;
      }
      lastPinch = { dist, cx, cy };
    }
    if (!flushTimer) flushTimer = setTimeout(flushGesture, 45);
  });
  const endPointer = (e) => { pointers.delete(e.pointerId); lastPinch = null; };
  vp.addEventListener("pointerup", endPointer);
  vp.addEventListener("pointercancel", endPointer);
  vp.addEventListener("wheel", (e) => { e.preventDefault(); pending.zoom *= e.deltaY > 0 ? 1.1 : 0.9; if (!flushTimer) flushTimer = setTimeout(flushGesture, 45); }, { passive: false });

  async function flushGesture() {
    flushTimer = null;
    const g = pending; pending = { dx: 0, dy: 0, px: 0, py: 0, zoom: 1 };
    const calls = [];
    if (g.dx || g.dy) calls.push({ action: "orbit", params: { dx: g.dx, dy: g.dy } });
    if (g.px || g.py) calls.push({ action: "pan", params: { dx: g.px, dy: g.py } });
    if (Math.abs(g.zoom - 1) > 0.002) calls.push({ action: "zoom", params: { factor: g.zoom } });
    for (const c of calls) {
      try { await api("/api/action", { body: c }); } catch (e) { toast(e.message); break; }
    }
    bumpPreview();
  }

  // --------------------------------------------------------------- UI

  $$("#tabs button").forEach((b) => b.addEventListener("click", () => {
    $$("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
    $$("#panel .tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === b.dataset.tab));
  }));
  $("#panel .tab").classList.add("on");

  // Generic data-action buttons.
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-action]");
    if (!b) return;
    const d = b.dataset;
    switch (d.action) {
      case "view": return action("view", { name: d.name });
      case "shading": return action("shading", { type: d.type });
      case "add": return action("add", { kind: d.kind });
      case "object": {
        if (d.name === "delete" && !confirm(`Delete ${state?.active?.name || "selection"}?`)) return;
        return action("object", { name: d.name });
      }
      case "select_all": return action("select_all", { state: d.state === "true" });
      case "frame": {
        if (!state) return;
        let f = d.abs === "start" ? state.frame_start : d.abs === "end" ? state.frame_end : state.frame + Number(d.rel);
        return action("frame", { frame: f });
      }
      case "render": return action("render", { animation: d.animation === "true" });
      default: return action(d.action);
    }
  });

  $$("#quality button").forEach((b) => b.addEventListener("click", () => {
    previewWidth = Number(b.dataset.w);
    $$("#quality button").forEach((x) => x.classList.toggle("on", x === b));
    bumpPreview();
  }));

  const invBtn = $("#btn-invert");
  const paintInvert = () => { invBtn.textContent = "Invert orbit: " + (invertOrbit ? "on" : "off"); };
  invBtn.addEventListener("click", () => { invertOrbit = !invertOrbit; try { localStorage.setItem("bpc_invert", invertOrbit ? "1" : "0"); } catch (_) {} paintInvert(); });
  paintInvert();

  $("#obj-select").addEventListener("change", (e) => action("select", { name: e.target.value }));
  $("#btn-rename").addEventListener("click", () => {
    if (!state?.active) return toast("nothing selected");
    const n = prompt("Rename object", state.active.name);
    if (n && n !== state.active.name) action("rename", { name: n });
  });

  function paintSteps() {
    const box = $("#xf-step");
    box.innerHTML = "";
    const steps = STEPS[xf.kind];
    if (!steps.includes(xf.step)) xf.step = steps[1];
    for (const s of steps) {
      const b = document.createElement("button");
      b.textContent = xf.kind === "rotate" ? s + "°" : xf.kind === "scale" ? "×" + s : String(s);
      b.classList.toggle("on", s === xf.step);
      b.addEventListener("click", () => { xf.step = s; paintSteps(); });
      box.appendChild(b);
    }
    if (state) applyState(state);
  }
  $$("#xf-kind button").forEach((b) => b.addEventListener("click", () => {
    xf.kind = b.dataset.kind;
    $$("#xf-kind button").forEach((x) => x.classList.toggle("on", x === b));
    paintSteps();
  }));
  paintSteps();

  $$(".axis").forEach((row) => {
    const axis = row.classList.contains("x") ? "x" : row.classList.contains("y") ? "y" : "z";
    row.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      const dir = Number(b.dataset.dir);
      const value = xf.kind === "scale" ? (dir > 0 ? xf.step : 1 / xf.step) : xf.step * dir;
      action("transform", { kind: xf.kind, axis, value });
    }));
  });

  $("#btn-play").addEventListener("click", () => action("play"));
  $("#frame-slider").addEventListener("change", (e) => action("frame", { frame: Number(e.target.value) }));
  $("#frame-slider").addEventListener("input", (e) => { $("#frame-out").textContent = e.target.value; });
  $("#engine").addEventListener("change", (e) => action("engine", { engine: e.target.value }));

  // Controls (all tabs except Chat, plus undo/redo/save) are hidden until the gear is toggled.
  let controls = false;
  try { controls = localStorage.getItem("bpc_controls") === "1"; } catch (_) {}
  function paintControls() {
    document.body.classList.toggle("controls", controls);
    $("#btn-controls").classList.toggle("on", controls);
    if (!controls) $("#tabs button[data-tab=chat]").click();
  }
  $("#btn-controls").addEventListener("click", () => {
    controls = !controls;
    try { localStorage.setItem("bpc_controls", controls ? "1" : "0"); } catch (_) {}
    paintControls();
  });
  paintControls();

  // ---------------------------------------------------------------- chat

  const thread = $("#chat-thread"), chatText = $("#chat-text");
  let lastMsgId = 0, chatPolling = false;

  function setClaude(online) {
    const el = $("#claude");
    el.textContent = online ? "Claude listening" : "Claude not listening";
    el.classList.toggle("on", !!online);
  }

  function fmtTime(ts) { return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }

  function addMessage(m, pending = false) {
    $("#chat-empty").hidden = true;
    const el = document.createElement("div");
    el.className = `msg ${m.role}${pending ? " pending" : ""}`;
    el.textContent = m.text;
    if (!pending) {
      const t = document.createElement("time");
      t.textContent = (m.role === "claude" ? "Claude · " : "") + fmtTime(m.ts);
      el.appendChild(t);
    }
    thread.appendChild(el);
    thread.scrollTop = thread.scrollHeight;
    return el;
  }

  async function pollMessages() {
    if (chatPolling || !token || document.hidden) return;
    chatPolling = true;
    try {
      const data = await api(`/api/messages?since=${lastMsgId}&wait=25`);
      for (const m of data.messages) if (m.id > lastMsgId) { addMessage(m); lastMsgId = m.id; }
    } catch (e) {
      await new Promise((r) => setTimeout(r, 2000));
    } finally {
      chatPolling = false;
      if (token && !document.hidden) pollMessages();
    }
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) pollMessages(); });

  function autosize() { chatText.style.height = "auto"; chatText.style.height = Math.min(chatText.scrollHeight, 120) + "px"; }
  chatText.addEventListener("input", autosize);
  chatText.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#chat-form").requestSubmit(); }
  });

  $("#chat-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const t = chatText.value.trim();
    if (!t) return;
    const pending = addMessage({ role: "phone", text: t }, true);
    chatText.value = ""; autosize();
    try {
      const data = await api("/api/send", { body: { text: t } });
      pending.remove();
      if (data.message.id > lastMsgId) { addMessage(data.message); lastMsgId = data.message.id; }
      if (!data.claude_online) toast("Sent, but Claude is not listening right now");
    } catch (e) {
      pending.remove();
      chatText.value = t; autosize();
      toast(e.message);
    }
  });

  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 3500);
  }

  // --------------------------------------------------------------- boot

  let stateTimer = null;
  function boot() {
    clearInterval(stateTimer);
    pollState();
    stateTimer = setInterval(() => { if (!document.hidden) pollState(); }, 1500);
    fetchPreview();
    lastMsgId = 0;
    thread.querySelectorAll(".msg").forEach((n) => n.remove());
    $("#chat-empty").hidden = false;
    pollMessages();
  }

  (async () => {
    if (!token) return showLogin();
    try {
      const r = await fetch("/api/ping", { headers: { "X-Token": token } }).then((r) => r.json());
      if (!r.authed) return showLogin();
      $("#login").hidden = true;
      boot();
    } catch (_) { showLogin(); toast("Blender unreachable"); }
  })();
})();
