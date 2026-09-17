"""Minimal stand-ins for bpy / mathutils so the addon's HTTP + bridge layers
can be exercised outside Blender. Only what the tests touch is modelled."""
import math
import sys
import threading
import types


class Vector(list):
    def __init__(self, v=(0.0, 0.0, 0.0)):
        super().__init__(float(x) for x in v)

    def copy(self):
        return Vector(self)

    def __add__(self, o):
        return Vector(a + b for a, b in zip(self, o))

    def __iadd__(self, o):
        for i in range(3):
            self[i] += o[i]
        return self

    def __neg__(self):
        return Vector(-a for a in self)

    def __mul__(self, k):
        return Vector(a * k for a in self)

    __rmul__ = __mul__


class Quaternion:
    def __init__(self, axis=(1, 0, 0, 0), angle=None):
        if angle is None:
            self.w, self.x, self.y, self.z = axis
        else:
            ax = Vector(axis)
            n = math.sqrt(sum(a * a for a in ax)) or 1.0
            s = math.sin(angle / 2) / n
            self.w = math.cos(angle / 2)
            self.x, self.y, self.z = ax[0] * s, ax[1] * s, ax[2] * s

    def copy(self):
        return Quaternion((self.w, self.x, self.y, self.z))

    def __matmul__(self, o):
        if isinstance(o, Quaternion):
            w1, x1, y1, z1 = self.w, self.x, self.y, self.z
            w2, x2, y2, z2 = o.w, o.x, o.y, o.z
            return Quaternion((
                w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
                w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            ))
        # rotate vector
        qv = Quaternion((0.0, *o))
        inv = Quaternion((self.w, -self.x, -self.y, -self.z))
        r = self @ qv @ inv
        return Vector((r.x, r.y, r.z))

    def __repr__(self):
        return f"Quaternion({self.w:.3f},{self.x:.3f},{self.y:.3f},{self.z:.3f})"


class _NS(types.SimpleNamespace):
    pass


class FakeObject(_NS):
    def __init__(self, name, type="MESH"):
        super().__init__(name=name, type=type, mode="OBJECT", location=Vector(), rotation_euler=Vector(),
                         scale=Vector((1, 1, 1)), _selected=False, _hidden=False)

    def select_get(self):
        return self._selected

    def select_set(self, v):
        self._selected = v

    def hide_get(self):
        return self._hidden


class _Timers:
    def __init__(self):
        self._fns = {}
        self._lock = threading.Lock()

    def register(self, fn, first_interval=0.0, persistent=False):
        with self._lock:
            self._fns[fn] = True

    def unregister(self, fn):
        with self._lock:
            self._fns.pop(fn, None)

    def is_registered(self, fn):
        with self._lock:
            return fn in self._fns

    def tick(self):
        """Test helper: run every registered timer once (like Blender's main loop)."""
        with self._lock:
            fns = list(self._fns)
        for fn in fns:
            r = fn()
            if r is None:
                self.unregister(fn)


def build():
    bpy = types.ModuleType("bpy")
    bpy.app = _NS(timers=_Timers(), handlers=_NS(render_complete=[], render_cancel=[]))

    cube = FakeObject("Cube")
    cube._selected = True
    cam = FakeObject("Camera", "CAMERA")
    objects = [cube, cam]

    r3d = _NS(view_perspective="PERSP", view_distance=10.0,
              view_rotation=Quaternion((1, 0, 0, 0)), view_location=Vector())
    space = _NS(region_3d=r3d, shading=_NS(type="SOLID"))
    region = _NS(type="WINDOW")
    area = _NS(type="VIEW_3D", regions=[region], spaces=_NS(active=space), tag_redraw=lambda: None)
    screen = _NS(areas=[area], is_animation_playing=False)
    window = _NS(screen=screen)

    scene = _NS(name="Scene", objects=objects, frame_current=1, frame_start=1, frame_end=250,
                render=_NS(fps=24, engine="CYCLES", resolution_x=1920, resolution_y=1080, resolution_percentage=100))
    scene.frame_set = lambda f: setattr(scene, "frame_current", f)

    class _Objs:  # supports both `.active` and `for o in view_layer.objects`
        active = cube
        def __iter__(self):
            return iter(objects)
    view_layer = _NS(objects=_Objs())

    bpy.context = _NS(scene=scene, view_layer=view_layer, window_manager=_NS(windows=[window]),
                      preferences=_NS(view=_NS(render_display_type="WINDOW")))
    bpy.data = _NS(filepath="C:/work/test.blend", is_dirty=False, objects={o.name: o for o in objects})
    bpy.types = _NS(AddonPreferences=object, Operator=object, Panel=object)
    bpy.props = _NS(IntProperty=lambda **k: None, BoolProperty=lambda **k: None)
    bpy.utils = _NS(register_class=lambda c: None, unregister_class=lambda c: None)
    bpy.ops = _NS()

    mathutils = types.ModuleType("mathutils")
    mathutils.Vector, mathutils.Quaternion = Vector, Quaternion
    return bpy, mathutils


def install():
    bpy, mathutils = build()
    sys.modules["bpy"] = bpy
    sys.modules["mathutils"] = mathutils
    return bpy
