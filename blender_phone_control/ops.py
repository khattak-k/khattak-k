"""Everything here runs on Blender's main thread (via bridge.submit)."""
import math
import os
import tempfile
import time

import bpy
from mathutils import Quaternion, Vector

# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _find_view3d():
    """Return (window, area, region, space) for the first 3D viewport."""
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    return window, area, region, area.spaces.active
    raise RuntimeError("no 3D Viewport open in Blender")


def _override():
    window, area, region, space = _find_view3d()
    return dict(window=window, screen=window.screen, area=area, region=region, space_data=space)


def _ensure_object_mode():
    obj = bpy.context.view_layer.objects.active
    if obj is not None and obj.mode != "OBJECT":
        with bpy.context.temp_override(**_override()):
            bpy.ops.object.mode_set(mode="OBJECT")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def get_state():
    scene = bpy.context.scene
    vl = bpy.context.view_layer
    active = vl.objects.active
    try:
        window, area, region, space = _find_view3d()
        r3d = space.region_3d
        view = {
            "shading": space.shading.type,
            "perspective": r3d.view_perspective,
            "distance": round(r3d.view_distance, 3),
        }
        playing = window.screen.is_animation_playing
    except RuntimeError:
        view = None
        playing = False

    objects = []
    for o in scene.objects:
        objects.append({"name": o.name, "type": o.type, "selected": o.select_get(), "hidden": o.hide_get()})
        if len(objects) >= 300:
            break

    return {
        "file": os.path.basename(bpy.data.filepath) or "(unsaved)",
        "dirty": bpy.data.is_dirty,
        "scene": scene.name,
        "frame": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
        "playing": playing,
        "engine": scene.render.engine,
        "engines": available_engines(),
        "resolution": [scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage],
        "mode": active.mode if active else "OBJECT",
        "active": _object_info(active),
        "objects": objects,
        "view": view,
        "render": dict(_render),
    }


def _object_info(o):
    if o is None:
        return None
    return {
        "name": o.name,
        "type": o.type,
        "location": [round(v, 4) for v in o.location],
        "rotation": [round(math.degrees(v), 2) for v in o.rotation_euler],
        "scale": [round(v, 4) for v in o.scale],
    }


# ---------------------------------------------------------------------------
# Viewport navigation (touch gestures)
# ---------------------------------------------------------------------------

def view_orbit(dx, dy):
    """dx/dy in radians; positive dx = finger moved right, positive dy = down."""
    _, area, _, space = _find_view3d()
    r3d = space.region_3d
    if r3d.view_perspective == "CAMERA":
        r3d.view_perspective = "PERSP"
    q = r3d.view_rotation.copy()
    # Yaw around world Z, then pitch around the view's own X axis, so it
    # behaves like Blender's turntable orbit.
    q = Quaternion((0.0, 0.0, 1.0), -dx) @ q
    x_axis = q @ Vector((1.0, 0.0, 0.0))
    q = Quaternion(x_axis, -dy) @ q
    r3d.view_rotation = q
    area.tag_redraw()


def view_pan(dx, dy):
    """dx/dy as a fraction of the viewport (1.0 = full width)."""
    _, area, region, space = _find_view3d()
    r3d = space.region_3d
    if r3d.view_perspective == "CAMERA":
        r3d.view_perspective = "PERSP"
    scale = r3d.view_distance * 1.2
    right = r3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    up = r3d.view_rotation @ Vector((0.0, 1.0, 0.0))
    r3d.view_location += (-right * dx + up * dy) * scale
    area.tag_redraw()


def view_zoom(factor):
    _, area, _, space = _find_view3d()
    r3d = space.region_3d
    if r3d.view_perspective == "CAMERA":
        r3d.view_perspective = "PERSP"
    r3d.view_distance = max(0.01, min(10000.0, r3d.view_distance * factor))
    area.tag_redraw()


_AXES = {"front", "back", "left", "right", "top", "bottom"}


def view_preset(name):
    name = name.lower()
    with bpy.context.temp_override(**_override()):
        if name in _AXES:
            bpy.ops.view3d.view_axis(type=name.upper())
        elif name == "camera":
            bpy.ops.view3d.view_camera()
        elif name == "selected":
            bpy.ops.view3d.view_selected()
        elif name == "all":
            bpy.ops.view3d.view_all()
        elif name == "persp":
            bpy.ops.view3d.view_persportho()
        else:
            raise ValueError(f"unknown view preset {name!r}")


def view_shading(kind):
    kind = kind.upper()
    if kind not in {"WIREFRAME", "SOLID", "MATERIAL", "RENDERED"}:
        raise ValueError(f"unknown shading {kind!r}")
    _, area, _, space = _find_view3d()
    space.shading.type = kind
    area.tag_redraw()


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------

def select(name, extend=False):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"no object named {name!r}")
    _ensure_object_mode()
    if not extend:
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def select_all(state):
    _ensure_object_mode()
    for o in bpy.context.view_layer.objects:
        o.select_set(bool(state))


def _selected():
    objs = [o for o in bpy.context.view_layer.objects if o.select_get()]
    if not objs:
        raise RuntimeError("nothing selected")
    return objs


def transform(kind, axis, value):
    """kind: move|rotate|scale ; axis: x|y|z ; value: delta (units/degrees/factor)."""
    i = "xyz".index(axis.lower())
    _ensure_object_mode()
    for o in _selected():
        if kind == "move":
            o.location[i] += float(value)
        elif kind == "rotate":
            o.rotation_euler[i] += math.radians(float(value))
        elif kind == "scale":
            o.scale[i] *= float(value)
        else:
            raise ValueError(f"unknown transform {kind!r}")


def set_transform(kind, values):
    """Set absolute location/rotation(deg)/scale on the active object."""
    obj = bpy.context.view_layer.objects.active
    if obj is None:
        raise RuntimeError("no active object")
    _ensure_object_mode()
    v = [float(x) for x in values]
    if kind == "move":
        obj.location = v
    elif kind == "rotate":
        obj.rotation_euler = [math.radians(x) for x in v]
    elif kind == "scale":
        obj.scale = v
    else:
        raise ValueError(f"unknown transform {kind!r}")


def rename(name):
    obj = bpy.context.view_layer.objects.active
    if obj is None:
        raise RuntimeError("no active object")
    obj.name = str(name)


def add_primitive(kind):
    ops = {
        "cube": bpy.ops.mesh.primitive_cube_add,
        "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
        "cylinder": bpy.ops.mesh.primitive_cylinder_add,
        "plane": bpy.ops.mesh.primitive_plane_add,
        "cone": bpy.ops.mesh.primitive_cone_add,
        "torus": bpy.ops.mesh.primitive_torus_add,
        "monkey": bpy.ops.mesh.primitive_monkey_add,
        "empty": bpy.ops.object.empty_add,
        "light": bpy.ops.object.light_add,
        "camera": bpy.ops.object.camera_add,
    }
    if kind not in ops:
        raise ValueError(f"unknown primitive {kind!r}")
    _ensure_object_mode()
    with bpy.context.temp_override(**_override()):
        if kind == "light":
            ops[kind](type="POINT")
        else:
            ops[kind]()


def object_op(name):
    """Simple whole-selection operators."""
    _ensure_object_mode()
    _selected()
    with bpy.context.temp_override(**_override()):
        if name == "delete":
            bpy.ops.object.delete(use_global=False)
        elif name == "duplicate":
            bpy.ops.object.duplicate()
        elif name == "shade_smooth":
            bpy.ops.object.shade_smooth()
        elif name == "shade_flat":
            bpy.ops.object.shade_flat()
        elif name == "apply_transforms":
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        elif name == "origin_to_geometry":
            bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY")
        elif name == "hide":
            bpy.ops.object.hide_view_set(unselected=False)
        else:
            raise ValueError(f"unknown object op {name!r}")


def unhide_all():
    with bpy.context.temp_override(**_override()):
        bpy.ops.object.hide_view_clear()


# ---------------------------------------------------------------------------
# Global / scene
# ---------------------------------------------------------------------------

def _undo_push(message):
    """Operators run from a timer don't push undo steps, so record one per phone edit."""
    try:
        with bpy.context.temp_override(**_override()):
            bpy.ops.ed.undo_push(message=message)
    except Exception as e:
        print("[Phone Control] undo push failed:", e)


def undo():
    with bpy.context.temp_override(**_override()):
        if not bpy.ops.ed.undo.poll():
            raise RuntimeError("nothing to undo")
        bpy.ops.ed.undo()


def redo():
    with bpy.context.temp_override(**_override()):
        if not bpy.ops.ed.redo.poll():
            raise RuntimeError("nothing to redo")
        bpy.ops.ed.redo()


def save():
    if not bpy.data.filepath:
        raise RuntimeError("file has never been saved; save it once from the desktop first")
    with bpy.context.temp_override(**_override()):
        bpy.ops.wm.save_mainfile()


def set_frame(frame):
    scene = bpy.context.scene
    scene.frame_set(int(frame))


def toggle_play():
    with bpy.context.temp_override(**_override()):
        bpy.ops.screen.animation_play()


_engines = None
_ENGINE_CANDIDATES = ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES", "BLENDER_WORKBENCH", "HYDRA_STORM")


def available_engines():
    """Engine identifiers this Blender accepts (names differ per version;
    the enum is dynamic so probing is the only reliable way). Cached."""
    global _engines
    if _engines is None:
        r = bpy.context.scene.render
        saved, found = r.engine, []
        for cand in _ENGINE_CANDIDATES:
            try:
                r.engine = cand
            except TypeError:
                continue
            found.append(cand)
        r.engine = saved
        _engines = found
    return _engines


def set_engine(engine):
    if engine not in available_engines():
        raise ValueError(f"engine {engine!r} not available; choose from {', '.join(available_engines())}")
    bpy.context.scene.render.engine = engine


# ---------------------------------------------------------------------------
# Viewport preview capture
# ---------------------------------------------------------------------------

_preview_cache = {"bytes": None, "time": 0.0, "width": 0}
_PREVIEW_MIN_INTERVAL = 0.08  # don't re-render the viewport faster than this


def capture_preview(width=720, quality=75):
    now = time.monotonic()
    cached = _preview_cache["bytes"]
    if _render["status"] == "running":
        # render.opengl can't run while a render job is active, and its
        # completion would trip our render handlers anyway.
        if cached is None:
            raise RuntimeError("rendering; preview paused")
        return cached
    if cached is not None and now - _preview_cache["time"] < _PREVIEW_MIN_INTERVAL and _preview_cache["width"] == width:
        return cached

    window, area, region, space = _find_view3d()
    scene = bpy.context.scene
    r = scene.render
    img = r.image_settings
    prefs_view = bpy.context.preferences.view

    saved = (
        r.filepath, r.resolution_percentage, r.use_file_extension, r.use_overwrite,
        img.file_format, img.color_mode, img.quality, prefs_view.render_display_type,
    )
    base = os.path.join(tempfile.gettempdir(), f"blender_phone_preview_{os.getpid()}")
    try:
        pct = int(round(100.0 * width / max(1, r.resolution_x)))
        r.resolution_percentage = max(5, min(100, pct))
        r.filepath = base
        r.use_file_extension = True
        r.use_overwrite = True
        img.file_format = "JPEG"
        img.color_mode = "RGB"
        img.quality = int(quality)
        prefs_view.render_display_type = "NONE"  # don't pop a render window
        with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
            bpy.ops.render.opengl(write_still=True, view_context=True)
        with open(base + ".jpg", "rb") as f:
            data = f.read()
    finally:
        (
            r.filepath, r.resolution_percentage, r.use_file_extension, r.use_overwrite,
            img.file_format, img.color_mode, img.quality, prefs_view.render_display_type,
        ) = saved

    _preview_cache.update(bytes=data, time=now, width=width)
    return data


# ---------------------------------------------------------------------------
# Final render (non-blocking; handlers track completion)
# ---------------------------------------------------------------------------

_render = {"status": "idle", "started": 0.0, "finished": 0.0, "message": ""}
_RESULT_PATH = os.path.join(tempfile.gettempdir(), f"blender_phone_render_{os.getpid()}.jpg")
_expecting_render = False


def render_start(animation=False):
    global _expecting_render
    if _render["status"] == "running":
        raise RuntimeError("a render is already running")
    _render.update(status="running", started=time.time(), finished=0.0, message="")
    _expecting_render = True
    with bpy.context.temp_override(**_override()):
        # INVOKE_DEFAULT runs the render in Blender's own job system, so
        # the UI (and our timer) keep ticking while it works.
        bpy.ops.render.render("INVOKE_DEFAULT", animation=bool(animation), write_still=False)


def render_result_bytes():
    if _render["status"] != "done" or not os.path.exists(_RESULT_PATH):
        raise RuntimeError("no finished render available")
    with open(_RESULT_PATH, "rb") as f:
        return f.read()


def _on_render_complete(scene, *_):
    global _expecting_render
    if not _expecting_render:
        return
    _expecting_render = False
    try:
        img = scene.render.image_settings
        saved = (img.file_format, img.color_mode, img.quality)
        try:
            img.file_format, img.color_mode, img.quality = "JPEG", "RGB", 90
            bpy.data.images["Render Result"].save_render(_RESULT_PATH, scene=scene)
        finally:
            img.file_format, img.color_mode, img.quality = saved
        _render.update(status="done", finished=time.time())
    except Exception as e:
        _render.update(status="error", finished=time.time(), message=str(e))


def _on_render_cancel(scene, *_):
    global _expecting_render
    if not _expecting_render:
        return
    _expecting_render = False
    _render.update(status="cancelled", finished=time.time())


def register_handlers():
    if _on_render_complete not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(_on_render_complete)
    if _on_render_cancel not in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.append(_on_render_cancel)


def unregister_handlers():
    if _on_render_complete in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(_on_render_complete)
    if _on_render_cancel in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.remove(_on_render_cancel)


# ---------------------------------------------------------------------------
# Action dispatch (what the HTTP layer calls)
# ---------------------------------------------------------------------------

ACTIONS = {
    "orbit": lambda p: view_orbit(float(p["dx"]), float(p["dy"])),
    "pan": lambda p: view_pan(float(p["dx"]), float(p["dy"])),
    "zoom": lambda p: view_zoom(float(p["factor"])),
    "view": lambda p: view_preset(p["name"]),
    "shading": lambda p: view_shading(p["type"]),
    "select": lambda p: select(p["name"], bool(p.get("extend", False))),
    "select_all": lambda p: select_all(p.get("state", True)),
    "transform": lambda p: transform(p["kind"], p["axis"], p["value"]),
    "set_transform": lambda p: set_transform(p["kind"], p["values"]),
    "rename": lambda p: rename(p["name"]),
    "add": lambda p: add_primitive(p["kind"]),
    "object": lambda p: object_op(p["name"]),
    "unhide_all": lambda p: unhide_all(),
    "undo": lambda p: undo(),
    "redo": lambda p: redo(),
    "save": lambda p: save(),
    "frame": lambda p: set_frame(p["frame"]),
    "play": lambda p: toggle_play(),
    "engine": lambda p: set_engine(p["engine"]),
    "render": lambda p: render_start(bool(p.get("animation", False))),
}


# Actions that edit the scene get an undo step so the phone's Undo can revert them.
_UNDOABLE = {"select", "select_all", "transform", "set_transform", "rename", "add", "object", "unhide_all"}


def run_action(name, params):
    fn = ACTIONS.get(name)
    if fn is None:
        raise ValueError(f"unknown action {name!r}")
    fn(params or {})
    if name in _UNDOABLE:
        _undo_push(f"Phone: {name}")
    return get_state()
