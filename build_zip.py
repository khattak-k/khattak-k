"""Package the addon as dist/blender_phone_control.zip for 'Install from Disk'."""
import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "blender_phone_control")
OUT = os.path.join(ROOT, "dist", "blender_phone_control.zip")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in filenames:
            if f.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, f)
            z.write(full, os.path.relpath(full, ROOT))
print("wrote", OUT)
