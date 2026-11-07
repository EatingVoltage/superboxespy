"""Serve the built app (dist/) on localhost and open it.

    python serve.py [--port 5198] [--browser chrome|edge|default|none]

Standard library only. Binds to 127.0.0.1, so nothing is reachable from the network. Chrome or Edge open it as an
app window: both can write straight into a folder (File System Access); Brave needs
brave://flags/#file-system-access-api for that.

POST /api/open-lightburn opens a project the page just wrote into its folder in LightBurn (see open_in_lightburn).
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

    def do_POST(self):
        if self.path != OPEN_LIGHTBURN:
            self.send_error(404)
            return
        if not self.from_the_app():
            self.send_error(403)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                raise ValueError("request too big")
            res = open_in_lightburn(json.loads(self.rfile.read(n)))
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
        threading.Thread(target=bring_forward, args=(proc.pid,), daemon=True).start()
    elif hasattr(os, "startfile"):
        os.startfile(path)
    else:
        raise OSError("LightBurn not found")


# ------------------------------------------------------------------ LightBurn to the front
# Windows doesn't let a background program's child take the foreground, so LightBurn would open behind the app
# (measured 2026-11-07). Samuel chose to have it brought forward, as an exception to his rule that nothing raises a
# window: only once its main window is up, and only while the superboxes window still has focus, so it never jumps
# over other work he went back to while LightBurn was starting.
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


def main_window(pid):
    """The visible top-level, unowned window of process `pid` whose title names LightBurn, or None."""
    ctypes, user32 = _user32()
    found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if (owner.value == pid and user32.IsWindowVisible(ctypes.c_void_p(hwnd))
                and not user32.GetWindow(ctypes.c_void_p(hwnd), 4)            # GW_OWNER: skip dialogs
                and "lightburn" in window_title(hwnd).lower()):
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


def bring_forward(pid, timeout=30.0, poll=0.25):
    """Wait for LightBurn's main window (up to `timeout` s), then bring it in front of the superboxes window - but
    only if that window still has focus. Returns True when it raised it."""
    if os.name != "nt":
        return False
    deadline = time.monotonic() + timeout
    hwnd = main_window(pid)
    while not hwnd and time.monotonic() < deadline:
        time.sleep(poll)
        hwnd = main_window(pid)
    if not hwnd or window_title(foreground_window()).strip().lower() != APP_TITLE:
        return False
    raise_window(hwnd)
    return True


def open_in_lightburn(req, launch=None):
    """req = {"folder": picked folder's name, "path": [box folder, file.lbrn2], "sha256": hex, "root": optional full
    path of the picked folder}. {"ok": True, "path", "root"} once LightBurn is started; {"ok": False, "need_root":
    True} when the folder can't be found, so the page can ask for its path."""
    folder, rel, sha, hint = req.get("folder"), req.get("path"), req.get("sha256"), req.get("root")
    if not plain_name(folder):
        raise ValueError("no folder name")
    if not (isinstance(rel, list) and 1 <= len(rel) <= 3 and all(plain_name(p) for p in rel)
            and rel[-1].lower().endswith(".lbrn2")):
        raise ValueError("not a .lbrn2 file in the folder")
    if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise ValueError("no checksum")
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
    a = ap.parse_args()
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        sys.exit("No build found. Run once:  npm install  &&  npm run setup  &&  npm run build")
    url = "http://localhost:%d/" % a.port
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
