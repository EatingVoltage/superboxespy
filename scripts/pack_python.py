"""Zip the app's Python (boxes.py, superboxes, the evlaser copy, vendored qrcode) into public/py.zip.

The web worker unpacks it into Pyodide's file system. Run by `npm run dev` / `npm run build`.
"""
import os
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "python")
OUT = os.path.join(ROOT, "public", "py.zip")
SKIP_DIRS = {"__pycache__", "scripts", "tests"}
SKIP_FILES = {"preview.py"}          # evlaser/preview.py needs Pillow: dev-only


def add_tree(z, base, arc_prefix):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for f in sorted(filenames):
            if f.endswith(".pyc") or f in SKIP_FILES:
                continue
            full = os.path.join(dirpath, f)
            arc = os.path.join(arc_prefix, os.path.relpath(full, base)).replace(os.sep, "/")
            z.write(full, arc)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for pkg in ("boxes", "superboxes", "evlaser"):
            add_tree(z, os.path.join(SRC, pkg), pkg)
        vendor = os.path.join(SRC, "_vendor")
        for pkg in sorted(os.listdir(vendor)):
            add_tree(z, os.path.join(vendor, pkg), pkg)
    print("wrote %s (%.0f kB)" % (os.path.relpath(OUT, ROOT), os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
