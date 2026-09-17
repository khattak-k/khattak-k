"""Marshal work from the HTTP thread onto Blender's main thread.

bpy is not thread-safe: everything that touches Blender data runs inside
``_drain``, which a persistent app timer calls on the main thread. The
server thread submits a Job and blocks on its Event until it's done.
"""
import queue
import threading
import traceback

import bpy

_jobs: "queue.Queue[Job]" = queue.Queue()
_TICK = 0.03  # seconds between drains (~33 Hz) while the server is up
DEFAULT_TIMEOUT = 30.0  # seconds a caller waits for the main thread


class Job:
    __slots__ = ("fn", "args", "kwargs", "event", "result", "error")

    def __init__(self, fn, args, kwargs):
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.event = threading.Event()
        self.result = None
        self.error = None


class BridgeError(RuntimeError):
    """The bridge itself failed (not running, or the main thread never answered)."""


def submit(fn, *args, timeout=None, **kwargs):
    """Run ``fn(*args, **kwargs)`` on the main thread and return its result.

    Exceptions raised by ``fn`` are re-raised here unchanged, so callers can
    tell a bad request (ValueError, RuntimeError from ops) from a dead bridge.
    """
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    if not bpy.app.timers.is_registered(_drain):
        raise BridgeError("bridge is not running")
    job = Job(fn, args, kwargs)
    _jobs.put(job)
    if not job.event.wait(timeout):
        raise BridgeError(f"timed out after {timeout:g}s waiting for Blender's main thread")
    if job.error is not None:
        raise job.error
    return job.result


def _drain():
    # Process everything queued so far, but don't starve the UI: one drain
    # per tick, and each job is expected to be short.
    while True:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            break
        try:
            job.result = job.fn(*job.args, **job.kwargs)
        except Exception as e:
            traceback.print_exc()  # full detail in Blender's console
            job.error = e
        finally:
            job.event.set()
    return _TICK


def start():
    if not bpy.app.timers.is_registered(_drain):
        bpy.app.timers.register(_drain, persistent=True)


def stop():
    if bpy.app.timers.is_registered(_drain):
        bpy.app.timers.unregister(_drain)
    # Fail anything still waiting so HTTP threads don't hang.
    while True:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            break
        job.error = BridgeError("bridge stopped")
        job.event.set()
