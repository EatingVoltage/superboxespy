"""Serve the built app (dist/) on localhost and open it.

    python serve.py [--port 5198] [--browser chrome|edge|default|none]

Standard library only. Binds to 127.0.0.1, so nothing is reachable from the network. Chrome or Edge open it as an
app window: both can write straight into a folder (File System Access); Brave needs
brave://flags/#file-system-access-api for that.
"""
import argparse
import functools
import http.server
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
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


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):   # quiet: only errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5198)
    ap.add_argument("--browser", default="auto", choices=["auto", "chrome", "edge", "default", "none"])
    a = ap.parse_args()
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        sys.exit("No build found. Run once:  npm install  &&  npm run setup  &&  npm run build")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), functools.partial(Handler, directory=DIST))
    url = "http://localhost:%d/" % a.port
    print("superboxes running at %s  (Ctrl+C to stop)" % url)
    threading.Timer(0.4, open_app, (url, a.browser)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
