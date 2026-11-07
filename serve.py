"""Serve the built app (dist/) on localhost and open it.

    python serve.py [--port 5198] [--browser chrome|edge|default|none] [file.sbox]

Standard library only. Binds to 127.0.0.1, so nothing is reachable from the network. Chrome or Edge open it as an
app window: both can write straight into a folder (File System Access); Brave needs
brave://flags/#file-system-access-api for that.

POST /api/open-lightburn opens a project the page just wrote in LightBurn (see open_in_lightburn). POST /api/box reads
and writes a box beside its own .sbox file, and shows Windows' Open / Save As dialogs for it (see box_op). A file
given on the command line (a double-clicked .sbox) opens in an app window, on the server already running if there is
one.
"""
import argparse
import functools
import hashlib
import http.server
import json
import mimetypes
import os
import re
import shutil
import socket
import string
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/otf", ".otf")

BROWSERS = {
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
               r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", "chrome", "google-chrome"],
    "edge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", "msedge", "microsoft-edge"],
}


OPEN_LIGHTBURN = "/api/open-lightburn"
BOX = "/api/box"
LOGOS = "/api/logos"
LOGO_DIR = r"C:\Projects\eating voltage Fonts\logos"
PARTS = "/api/parts"
# The eatingVoltage parts library (DeviceWizard's, private): where DeviceWizard keeps it on every PC
PARTS_DIR = os.path.join(os.path.expanduser("~"), "eatingVoltageLibrary")
LIGHTBURN_EXE = [r"C:\Program Files\LightBurn\LightBurn.exe", r"C:\Program Files (x86)\LightBurn\LightBurn.exe"]
# never searched for the box folder: system folders, caches, repos
SKIP_DIRS = {"windows", "program files", "program files (x86)", "programdata", "appdata", "system volume information",
             "recovery", "perflogs", "node_modules", "__pycache__", "site-packages", "intel", "amd", "nvidia"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):   # quiet: only errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split("?")[0])
        if path == PARTS:
            self.send_parts()
            return
        if path == LOGOS or path.startswith(LOGOS + "/"):
            self.send_logo(path[len(LOGOS) + 1:])
            return
        super().do_GET()

    def send_parts(self):
        """GET /api/parts: the parts library's confirmed panel holes, as hole presets for the face editor
        (part_holes). To this PC's own page only: the library is private."""
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        if host not in ("localhost:%d" % port, "127.0.0.1:%d" % port):
            self.send_error(403)
            return
        body = json.dumps(part_holes()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_logo(self, name):
        """GET /api/logos: the house logos' names (JSON); /api/logos/<name>.svg: one of them. The logos are private and
        never ship with the app (.grill/stamp-case-merge.md): they come from Samuel's folder, to this PC's own page."""
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        if host not in ("localhost:%d" % port, "127.0.0.1:%d" % port):
            self.send_error(403)
            return
        try:
            names = sorted(f for f in os.listdir(LOGO_DIR) if f.lower().endswith(".svg"))
        except OSError:
            names = []
        if not name:
            body, kind = json.dumps(names).encode("utf-8"), "application/json"
        elif name in names:      # only a file that is in the folder: no paths
            with open(os.path.join(LOGO_DIR, name), "rb") as f:
                body, kind = f.read(), "image/svg+xml"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, limit=65536):
        """The whole request body, or None when it is bigger than `limit` (read anyway and dropped). Every POST reads
        its body before any answer, refusals too: on Windows, closing a socket that still holds unread bytes sends a
        reset, and the page then sees a dropped connection instead of the answer (measured: 4 in 200 test runs)."""
        try:
            n = max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            n = 0
        data, kept = [], 0
        while n > 0:
            chunk = self.rfile.read(min(n, 65536))
            if not chunk:
                break
            n -= len(chunk)
            if kept <= limit:
                data.append(chunk)
                kept += len(chunk)
        return b"".join(data) if kept <= limit else None

    def do_POST(self):
        # a box's files can be big (a stamp case's hatched lid): 64 MB for those, 64 kB for the rest
        body = self.read_body(64 << 20 if self.path == BOX else 65536)
        if self.path not in (OPEN_LIGHTBURN, BOX):
            self.send_error(404)
            return
        if not self.from_the_app():
            self.send_error(403)
            return
        try:
            if body is None:
                raise ValueError("request too big")
            req = json.loads(body)
            res = box_op(req) if self.path == BOX else open_in_lightburn(req)
        except Exception as e:   # noqa: BLE001 - every failure goes back to the page as text
            res = {"ok": False, "error": str(e)}
        body = json.dumps(res).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def from_the_app(self):
        """Only the app's own page may ask: a JSON body (other sites can't send one without a CORS preflight, which
        this server never answers), a localhost Host (no DNS rebinding) and, when the browser says, the same origin."""
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return False
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        if host not in ("localhost:%d" % port, "127.0.0.1:%d" % port):
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != "http://" + host:
            return False
        return self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")


# ------------------------------------------------------------------ Open in LightBurn
# The page writes the project into the picked folder itself (File System Access), but a browser never learns that
# folder's full path, only its name. So the page sends the folder's name, the file's place inside it and the file's
# SHA-256; this finds the folder on disk (or takes the path the page remembered or the user typed), checks the file
# there is byte for byte the one just written, and opens it in LightBurn.
def plain_name(s):
    return isinstance(s, str) and s not in ("", ".", "..") and not any(c in s for c in '\\/:*?"<>|')


def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def fixed_drives():
    if os.name != "nt":
        return ["/"]
    import ctypes
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    roots = ["%s:\\" % c for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1]
    return [r for r in roots if k32.GetDriveTypeW(ctypes.c_wchar_p(r)) == 3]   # DRIVE_FIXED: no network, no USB


def folders_named(name):
    """Folders called `name`: up to 3 levels below the home folder, then up to 2 below each fixed drive."""
    want = name.lower()
    seen = set()
    for start, depth in [(os.path.expanduser("~"), 3)] + [(d, 2) for d in fixed_drives()]:
        level = [start]
        for _ in range(depth):
            deeper = []
            for parent in level:
                try:
                    with os.scandir(parent) as it:
                        entries = list(it)
                except OSError:
                    continue
                for e in entries:
                    low = e.name.lower()
                    try:
                        if not e.is_dir(follow_symlinks=False) or (hasattr(e, "is_junction") and e.is_junction()):
                            continue
                    except OSError:
                        continue
                    if low in SKIP_DIRS or low.startswith(("$", ".")):
                        continue
                    if low == want and os.path.normcase(e.path) not in seen:
                        seen.add(os.path.normcase(e.path))
                        yield e.path
                    deeper.append(e.path)
            level = deeper


def lightburn_exe():
    """LightBurn.exe: SUPERBOXES_LIGHTBURN, else what .lbrn2 files open with (if that is LightBurn), else the
    default install folders."""
    cands = [os.environ.get("SUPERBOXES_LIGHTBURN")]
    try:
        import winreg
        prog = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, ".lbrn2")
        cmd = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, prog + r"\shell\open\command")
        m = re.match(r'\s*(?:"([^"]+)"|(\S+))', cmd)
        cands.append(m.group(1) or m.group(2))
    except (ImportError, OSError, AttributeError):
        pass
    cands += LIGHTBURN_EXE
    return next((c for c in cands if c and os.path.basename(c).lower().startswith("lightburn") and os.path.isfile(c)),
                None)


def launch_lightburn(path):
    exe = lightburn_exe()
    if exe:   # a GUI program: no console window; its own process group, so Ctrl+C here doesn't reach it
        proc = subprocess.Popen([exe, path], cwd=os.path.dirname(path),
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        threading.Thread(target=bring_forward, args=(proc,), daemon=True).start()
    elif hasattr(os, "startfile"):
        os.startfile(path)
    else:
        raise OSError("LightBurn not found")


# ------------------------------------------------------------------ LightBurn to the front
# Windows doesn't let a background program's child take the foreground, so LightBurn would open behind the app
# (measured 2026-11-07). Samuel chose to have it brought forward, as an exception to his rule that nothing raises a
# window: only once its main window is up, and only while the superboxes window still has focus, so it never jumps
# over other work he went back to while LightBurn was starting.
# With LightBurn already open, LightBurn.exe "<file>" hands the file to that LightBurn and quits (seen 2026-11-07: the
# open one asked "Save Project?" for its current project, no second window), so then the open one is brought forward.
APP_TITLE = "superboxes"     # the app window's title (index.html <title>)


def _user32():
    import ctypes
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p     # window handles are pointer-sized
    user32.GetWindow.restype = ctypes.c_void_p
    return ctypes, user32


def window_title(hwnd):
    ctypes, user32 = _user32()
    buf = ctypes.create_unicode_buffer(512)
    if hwnd:
        user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 512)
    return buf.value


def foreground_window():
    return _user32()[1].GetForegroundWindow()


def process_name(pid):
    """Lower-case file name of process `pid`'s program ("" when it can't be read)."""
    ctypes, _ = _user32()
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x1000, False, pid)                                    # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(1024), ctypes.c_ulong(1024)
        ok = k32.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(size))
        return os.path.basename(buf.value).lower() if ok else ""
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def main_window(pid=None):
    """The visible top-level, unowned window whose title names LightBurn: of process `pid`, or (pid None) of any
    running LightBurn.exe. None when there is none."""
    ctypes, user32 = _user32()
    found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if ((pid is None or owner.value == pid) and user32.IsWindowVisible(ctypes.c_void_p(hwnd))
                and not user32.GetWindow(ctypes.c_void_p(hwnd), 4)            # GW_OWNER: skip dialogs
                and "lightburn" in window_title(hwnd).lower()
                and (pid is not None or process_name(owner.value) == "lightburn.exe")):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(proto(each), None)
    return found[0] if found else None


def raise_window(hwnd):
    """SetForegroundWindow from a background program: share input with the foreground window's thread for the
    call, which is what Windows checks."""
    ctypes, user32 = _user32()
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(ctypes.c_void_p(fg), None)
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True)
    try:
        if user32.IsIconic(ctypes.c_void_p(hwnd)):
            user32.ShowWindow(ctypes.c_void_p(hwnd), 9)                        # SW_RESTORE
        user32.BringWindowToTop(ctypes.c_void_p(hwnd))
        user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)


def bring_forward(proc, timeout=30.0, poll=0.25):
    """Wait for the main window of the LightBurn just started (`proc`, up to `timeout` s), or, if it quit because it
    handed the file to a LightBurn that was already open, for that one's; then bring it in front of the superboxes
    window - but only if that window still has focus. Returns True when it raised it."""
    if os.name != "nt":
        return False
    deadline = time.monotonic() + timeout
    while True:
        hwnd = main_window(proc.pid)
        if not hwnd and proc.poll() is not None:
            hwnd = main_window(None)
        if hwnd or time.monotonic() >= deadline:
            break
        time.sleep(poll)
    if not hwnd or window_title(foreground_window()).strip().lower() != APP_TITLE:
        return False
    raise_window(hwnd)
    return True


def open_in_lightburn(req, launch=None):
    """req = {"folder": picked folder's name, "path": [box folder, file.lbrn2], "sha256": hex, "root": optional full
    path of the picked folder}, or {"file": full path of the .lbrn2 (a box beside its own file), "sha256"}.
    {"ok": True, "path", "root"} once LightBurn is started; {"ok": False, "need_root": True} when the folder can't be
    found, so the page can ask for its path."""
    folder, rel, sha, hint = req.get("folder"), req.get("path"), req.get("sha256"), req.get("root")
    if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise ValueError("no checksum")
    if "file" in req:
        path = req["file"]
        if not (isinstance(path, str) and os.path.isabs(path) and path.lower().endswith(".lbrn2")):
            raise ValueError("not a .lbrn2 file")
        if not (os.path.isfile(path) and file_sha256(path) == sha):
            return {"ok": False, "error": "%s isn't the project just written" % path}
        (launch or launch_lightburn)(path)
        return {"ok": True, "path": path, "root": os.path.dirname(path)}
    if not plain_name(folder):
        raise ValueError("no folder name")
    if not (isinstance(rel, list) and 1 <= len(rel) <= 3 and all(plain_name(p) for p in rel)
            and rel[-1].lower().endswith(".lbrn2")):
        raise ValueError("not a .lbrn2 file in the folder")
    roots = [hint] if isinstance(hint, str) and os.path.isabs(hint) and os.path.isdir(hint) else []
    for root in roots + [r for r in folders_named(folder) if r not in roots]:
        path = os.path.join(root, *rel)
        try:
            if os.path.isfile(path) and file_sha256(path) == sha:
                (launch or launch_lightburn)(path)
                return {"ok": True, "path": path, "root": root}
        except OSError:
            continue
    return {"ok": False, "need_root": True,
            "error": "Couldn't find the folder \"%s\" holding %s" % (folder, "/".join(rel))
                     + (" (not in %s)" % hint if hint else "")}


# ------------------------------------------------------------------ hole presets from the parts library
# The face editor's device-panel holes come from Samuel's parts library (DeviceWizard's eatingVoltageLibrary): each
# part's latest published revision, its frontplate_hole or frontplate_window when confirmed (.grill/face-editor.md).
# Only the shape's size matters here (where the part's pins sit relative to it is DeviceWizard's business).
def _hole_shape(v):
    """A library shape (nanometres) as {"shape": "round", "d"} or {"shape": "rect", "w", "h", "r"} in mm; None for
    others."""
    if not isinstance(v, dict):
        return None
    if v.get("type") == "circle" and isinstance(v.get("r"), (int, float)):
        return {"shape": "round", "d": round(2 * v["r"] / 1e6, 3)}
    lo, hi = v.get("min"), v.get("max")
    if isinstance(lo, dict) and isinstance(hi, dict):
        radii = [r for r in v.get("radii") or [0] if isinstance(r, (int, float))] or [0]
        return {"shape": "rect", "w": round((hi["x"] - lo["x"]) / 1e6, 3), "h": round((hi["y"] - lo["y"]) / 1e6, 3),
                "r": round(max(radii) / 1e6, 3)}
    return None


def part_holes(root=None):
    """[{"code", "name", "kind": "hole" | "window", shape fields}] for every part with a confirmed panel hole or
    window, sorted by name; [] without the library."""
    base = os.path.join(root or PARTS_DIR, "items", "part")
    out = []
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for d in names:
        try:
            with open(os.path.join(base, d, "item.json"), encoding="utf-8") as f:
                item = json.load(f)
            revs = sorted(os.listdir(os.path.join(base, d, "revisions")))
            if item.get("deprecated") or not revs:
                continue
            with open(os.path.join(base, d, "revisions", revs[-1], "revision.json"), encoding="utf-8") as f:
                props = (json.load(f).get("data") or {}).get("properties") or {}
        except (OSError, ValueError):
            continue
        for key, kind in (("frontplate_hole", "hole"), ("frontplate_window", "window")):
            prop = props.get(key) or {}
            shape = _hole_shape(prop.get("value")) if prop.get("status") == "confirmed" else None
            if shape:
                out.append({"code": item.get("code", d), "name": item.get("name", d), "kind": kind, **shape})
    return sorted(out, key=lambda h: h["name"].lower())


# ------------------------------------------------------------------ a box beside its own file
# A box opened or saved anywhere (Open..., Save as..., a .sbox given to serve.py) keeps its full path: Save and the
# exports write beside it (.grill/stamp-case-merge.md). A browser never learns full paths, so serve.py reads and writes
# there, and Open... / Save as... are Windows' own file dialogs, which serve.py shows over the app window.
# A box is a .sbox file (JSON): an extension of its own, so a double-click can open it (Windows goes by the last
# extension, and .box.json is a .json to it). Boxes saved before 2026-11-07 are .box.json: they still open, and save
# as .sbox.
BOX_EXT, OLD_BOX_EXT = ".sbox", ".box.json"
BESIDE = (BOX_EXT, ".lbrn2", ".svg")          # what may be written beside a box
_dialog = threading.Lock()


def box_path(p):
    """p, normalised, when it's the full path of a box (.sbox, or an older .box.json) in a folder that exists; else
    ValueError."""
    if not (isinstance(p, str) and os.path.isabs(p) and p.lower().endswith((BOX_EXT, OLD_BOX_EXT))
            and os.path.isdir(os.path.dirname(p))):
        raise ValueError("not a box file in a folder: %r" % (p,))
    return os.path.normpath(p)


def beside(home, name, kinds=BESIDE):
    """Full path of file `name` beside the box `home`: a plain name of one of `kinds`, never anywhere else."""
    if not (plain_name(name) and name.lower().endswith(kinds)):
        raise ValueError("not a file a box keeps beside it: %r" % (name,))
    return os.path.join(os.path.dirname(box_path(home)), name)


def write_text(path, content):
    """Write as given (the page's own line ends), through a temporary file, so a failed write leaves the old one."""
    tmp = path + ".superboxes-tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    os.replace(tmp, path)


def box_op(req, ask=None):
    """POST /api/box. {"op": "hello"} | {"op": "read", "path"} -> {"path", "text"} |
    {"op": "ask_open", "start"} -> the same, for the file picked in the Open dialog |
    {"op": "ask_save", "name", "start"} -> {"path"} picked in the Save As dialog (always a .sbox) |
    {"op": "list", "home"} -> {"dir", "names"} of the box's folder |
    {"op": "read_beside", "home", "name"} -> {"text", "mtime"} of a .lbrn2 beside it, text None if there's none |
    {"op": "write", "home", "files": [{"name", "content"}]} -> {"dir"}.
    A cancelled dialog answers {"ok": False, "cancelled": True}. ask: the dialog (tests replace it)."""
    op = req.get("op")
    if op == "hello":
        return {"ok": True}
    if op == "read":
        path = box_path(req.get("path"))
        with open(path, encoding="utf-8") as f:
            return {"ok": True, "path": path, "text": f.read()}
    if op in ("ask_open", "ask_save"):
        start = req.get("start")
        start = start if isinstance(start, str) and os.path.isdir(start) else None
        name = req.get("name") if op == "ask_save" and plain_name(req.get("name")) else None
        path = (ask or ask_path)("open" if op == "ask_open" else "save", name, start)
        if not path:
            return {"ok": False, "cancelled": True}
        if op == "ask_open":
            return box_op({"op": "read", "path": path})
        if not path.lower().endswith(BOX_EXT):            # "abox", "abox.json", "abox.box.json" typed: a .sbox
            path = re.sub(r"(?i)(\.box)?\.json$", "", path) + BOX_EXT
        return {"ok": True, "path": box_path(path)}
    if op == "list":
        d = os.path.dirname(box_path(req.get("home")))
        with os.scandir(d) as it:
            return {"ok": True, "dir": d, "names": sorted(e.name for e in it if e.is_file())}
    if op == "read_beside":
        path = beside(req.get("home"), req.get("name"), (".lbrn2",))
        try:
            with open(path, encoding="utf-8") as f:
                return {"ok": True, "text": f.read(), "mtime": os.path.getmtime(path)}
        except FileNotFoundError:
            return {"ok": True, "text": None}
    if op == "write":
        files = req.get("files")
        if not (isinstance(files, list) and files and all(isinstance(f, dict) for f in files)):
            raise ValueError("nothing to write")
        todo = [(beside(req.get("home"), f.get("name")), f.get("content")) for f in files]
        if not all(isinstance(c, str) for _, c in todo):
            raise ValueError("a file without content")
        for path, content in todo:
            write_text(path, content)
        return {"ok": True, "dir": os.path.dirname(todo[0][0])}
    raise ValueError("unknown op %r" % (op,))


def app_window():
    """The superboxes app window: the foreground window if it's that, else the first visible one titled so."""
    if os.name != "nt":
        return None
    fg = foreground_window()
    if fg and window_title(fg).strip().lower() == APP_TITLE:
        return fg
    ctypes, user32 = _user32()
    found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each(hwnd, _):
        if user32.IsWindowVisible(ctypes.c_void_p(hwnd)) and window_title(hwnd).strip().lower() == APP_TITLE:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(proto(each), None)
    return found[0] if found else None


# IFileDialog (Windows Vista and later), through its vtable: the older GetOpenFileName ignores the folder it's given and
# starts in pythonw's last folder, which every Python program shares (seen 2026-11-07). SetFolder starts it in the
# box's own folder; SetClientGuid gives superboxes a last folder of its own for the rest.
FOS_OVERWRITEPROMPT, FOS_NOCHANGEDIR, FOS_FORCEFILESYSTEM = 0x2, 0x8, 0x40
FOS_PATHMUSTEXIST, FOS_FILEMUSTEXIST = 0x800, 0x1000
CANCELLED = -2147023673         # HRESULT_FROM_WIN32(ERROR_CANCELLED)
SIGDN_FILESYSPATH = 0x80058000
DIALOG_GUID = "{6B1E6F5A-2C1D-4B8E-9D3A-5F0C2E7A9B41}"   # superboxes' own last folder in the file dialogs


def ask_path(kind, name=None, start=None, owner=None):
    """Windows' Open ("open") or Save As ("save") dialog for a box, starting in folder `start` with `name` in the
    file box: the full path picked, or None. It is owned by the app window (or `owner`), so it opens over it and keeps
    it waiting, like the browser's own dialogs. SUPERBOXES_DIALOG, when set, answers instead without a dialog: a path,
    or empty for Cancel (headless tests)."""
    fake = os.environ.get("SUPERBOXES_DIALOG")
    if fake is not None:
        return fake or None
    if os.name != "nt":
        raise OSError("file dialogs need Windows")
    if not _dialog.acquire(blocking=False):
        raise OSError("a file dialog is already open")
    import ctypes
    from ctypes import wintypes as W

    def guid(text):
        g = (ctypes.c_byte * 16)()
        if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g)):
            raise OSError("bad GUID " + text)
        return g

    def call(obj, index, *args, types=()):
        """Method `index` of COM object `obj` (its vtable order), returning the HRESULT."""
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(vtable[index])(obj, *args)

    def check(hr, what):
        if hr:
            raise OSError("the file dialog failed at %s (0x%08x)" % (what, hr & 0xFFFFFFFF))

    class Spec(ctypes.Structure):
        _fields_ = [("name", W.LPCWSTR), ("spec", W.LPCWSTR)]

    ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
    inited = ole32.CoInitializeEx(None, 2) in (0, 1)              # COINIT_APARTMENTTHREADED: S_OK or S_FALSE
    dialog, item, result = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        clsid, iid = (("{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}", "{d57c7288-d4ad-4768-be02-9d969532d960}")
                      if kind == "open" else
                      ("{C0B4E2F3-BA21-4773-8DBA-335EC946EB8B}", "{84bccd23-5fde-4cdb-aea4-af64b83d78ab}"))
        check(ole32.CoCreateInstance(guid(clsid), None, 1, guid(iid), ctypes.byref(dialog)), "CoCreateInstance")
        specs = (Spec * 2)(Spec("Boxes (*.sbox, *.box.json)", "*.sbox;*.box.json"), Spec("All files (*.*)", "*.*"))
        check(call(dialog, 4, 2, specs, types=(W.UINT, ctypes.c_void_p)), "SetFileTypes")
        opts = W.DWORD()
        check(call(dialog, 10, ctypes.byref(opts), types=(ctypes.c_void_p,)), "GetOptions")
        opts = opts.value | FOS_FORCEFILESYSTEM | FOS_NOCHANGEDIR | FOS_PATHMUSTEXIST | (
            FOS_FILEMUSTEXIST if kind == "open" else FOS_OVERWRITEPROMPT)
        check(call(dialog, 9, opts, types=(W.DWORD,)), "SetOptions")
        check(call(dialog, 24, guid(DIALOG_GUID), types=(ctypes.c_void_p,)), "SetClientGuid")
        call(dialog, 17, "Open a box" if kind == "open" else "Save the box as", types=(W.LPCWSTR,))
        if start and not shell32.SHCreateItemFromParsingName(
                ctypes.c_wchar_p(start), None, guid("{43826d1e-e718-42ee-bc55-a1e261c37bfe}"), ctypes.byref(item)):
            check(call(dialog, 12, item, types=(ctypes.c_void_p,)), "SetFolder")
        if name:
            check(call(dialog, 15, name, types=(W.LPCWSTR,)), "SetFileName")
        hr = call(dialog, 3, owner if owner is not None else app_window(), types=(W.HWND,))
        if hr == CANCELLED:
            return None
        check(hr, "Show")
        check(call(dialog, 20, ctypes.byref(result), types=(ctypes.c_void_p,)), "GetResult")
        text = ctypes.c_wchar_p()
        check(call(result, 5, SIGDN_FILESYSPATH, ctypes.byref(text), types=(W.DWORD, ctypes.c_void_p)),
              "GetDisplayName")
        try:
            return text.value
        finally:
            ole32.CoTaskMemFree(text)
    finally:
        for obj in (result, item, dialog):
            if obj.value:
                call(obj, 2)                                         # IUnknown::Release
        if inited:
            ole32.CoUninitialize()
        _dialog.release()


def find(name):
    for c in BROWSERS[name]:
        if os.path.isfile(c) or shutil.which(c):
            return shutil.which(c) or c
    return None


def open_app(url, which):
    if which == "none":
        return
    order = [which] if which in BROWSERS else ["chrome", "edge"] if which == "auto" else []
    for name in order:
        exe = find(name)
        if exe:
            subprocess.Popen([exe, "--app=" + url, "--window-size=1500,950"])
            return
    webbrowser.open(url)


def open_hash(file):
    """The page's #open=<full path> for a box given on the command line ("" without one): the page reads it
    through /api/box and saves beside it."""
    if not file:
        return ""
    return "#open=" + urllib.parse.quote(os.path.abspath(file), safe="")


def already_running(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def main():
    if sys.stderr is None:   # pythonw (Start menu shortcut) has no console: logging to it would break the request
        sys.stdout = sys.stderr = open(os.devnull, "w")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5198)
    ap.add_argument("--browser", default="auto", choices=["auto", "chrome", "edge", "default", "none"])
    ap.add_argument("file", nargs="?", help="a .sbox (or an older .box.json) to open")
    a = ap.parse_args()
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        sys.exit("No build found. Run once:  npm install  &&  npm run setup  &&  npm run build")
    url = "http://localhost:%d/" % a.port + open_hash(a.file)
    if already_running(a.port):   # started before: open another window on it instead of a second server
        print("superboxes already running at %s" % url)
        open_app(url, a.browser)
        return
    server = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), functools.partial(Handler, directory=DIST))
    print("superboxes running at %s  (Ctrl+C to stop)" % url)
    threading.Timer(0.4, open_app, (url, a.browser)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
