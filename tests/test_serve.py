"""serve.py: Open in LightBurn, a box beside its own file, the file dialogs. LightBurn itself is never started (the
launch is replaced by a recorder), and the one real file dialog opens on a desktop that is never shown.
Run: .venv/Scripts/python -m unittest discover -s tests -v"""
import functools
import hashlib
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import serve  # noqa: E402

CONTENT = b'<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="2.2.00"/>\n'
SHA = hashlib.sha256(CONTENT).hexdigest()


class OpenInLightBurn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "Laser lightburn")
        os.makedirs(os.path.join(self.root, "abox"))
        self.file = os.path.join(self.root, "abox", "abox.lbrn2")
        with open(self.file, "wb") as f:
            f.write(CONTENT)
        self.launched = []
        self.req = {"folder": "Laser lightburn", "path": ["abox", "abox.lbrn2"], "sha256": SHA}

    def tearDown(self):
        self.tmp.cleanup()

    def open(self, **over):
        return serve.open_in_lightburn({**self.req, **over}, launch=self.launched.append)

    def test_opens_the_file_in_the_remembered_folder(self):
        r = self.open(root=self.root)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.launched, [self.file])
        self.assertEqual(r["root"], self.root)

    def test_asks_for_the_folder_when_it_cant_find_it(self):
        r = self.open(folder="no such folder here 7f3a")
        self.assertFalse(r["ok"])
        self.assertTrue(r["need_root"])
        self.assertEqual(self.launched, [])

    def test_never_opens_a_different_file(self):
        r = self.open(root=self.root, sha256="0" * 64)   # the file there isn't the one the page just wrote
        self.assertFalse(r["ok"])
        self.assertEqual(self.launched, [])

    def test_only_lbrn2_files_inside_the_folder(self):
        for path in (["abox", "x.exe"], ["..", "abox.lbrn2"], ["abox", "..\\abox.lbrn2"], ["C:", "abox.lbrn2"], []):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.open(root=self.root, path=path)
        self.assertEqual(self.launched, [])

    def test_finds_the_folder_by_name(self):
        real = serve.folders_named
        serve.folders_named = lambda name: iter([os.path.join(self.tmp.name, "elsewhere"), self.root])
        try:
            r = self.open()
        finally:
            serve.folders_named = real
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.launched, [self.file])

    def test_opens_a_project_beside_its_box_by_full_path(self):
        r = serve.open_in_lightburn({"file": self.file, "sha256": SHA}, launch=self.launched.append)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.launched, [self.file])
        r = serve.open_in_lightburn({"file": self.file, "sha256": "0" * 64}, launch=self.launched.append)
        self.assertFalse(r["ok"])                       # not the file the page just wrote
        for bad in ("abox.lbrn2", self.file[:-6] + ".exe"):
            with self.assertRaises(ValueError):
                serve.open_in_lightburn({"file": bad, "sha256": SHA}, launch=self.launched.append)
        self.assertEqual(self.launched, [self.file])


class BoxBesideItsFile(unittest.TestCase):
    """POST /api/box: a box opened or saved anywhere reads and writes beside its own .sbox file, nowhere else."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "hw", "packaging")
        os.makedirs(self.dir)
        self.home = os.path.join(self.dir, "CASE.sbox")
        with open(self.home, "w", encoding="utf-8") as f:
            f.write('{"name": "CASE"}')
        self.asked = []

    def tearDown(self):
        self.tmp.cleanup()

    def op(self, answer=None, **req):
        def ask(kind, name, start):
            self.asked.append((kind, name, start))
            return answer
        return serve.box_op(req, ask=ask)

    def test_reads_a_box(self):
        r = self.op(op="read", path=self.home)
        self.assertEqual((r["path"], r["text"]), (self.home, '{"name": "CASE"}'))
        for bad in ("CASE.sbox", os.path.join(self.dir, "notes.txt"), os.path.join(self.dir, "x.json"),
                    os.path.join(self.tmp.name, "no", "x.sbox")):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                self.op(op="read", path=bad)

    def test_writes_beside_the_box_only(self):
        files = [{"name": "CASE.lbrn2", "content": "<x/>\n"}, {"name": "01_CASE.svg", "content": "<svg/>"},
                 {"name": "CASE.sbox", "content": "{}"}]
        r = self.op(op="write", home=self.home, files=files)
        self.assertEqual(r["dir"], self.dir)
        with open(os.path.join(self.dir, "CASE.lbrn2"), "rb") as f:
            self.assertEqual(f.read(), b"<x/>\n")              # as the page wrote it: no CRLF
        self.assertEqual(sorted(self.op(op="list", home=self.home)["names"]),
                         ["01_CASE.svg", "CASE.lbrn2", "CASE.sbox"])
        self.assertEqual(self.op(op="read_beside", home=self.home, name="CASE.lbrn2")["text"], "<x/>\n")
        self.assertIsNone(self.op(op="read_beside", home=self.home, name="other.lbrn2")["text"])
        for name in ("..\\evil.lbrn2", "../evil.svg", "C:evil.svg", "evil.exe", "evil.bat", "x.box.json", "", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.op(op="write", home=self.home, files=[{"name": name, "content": "x"}])
        with self.assertRaises(ValueError):
            self.op(op="read_beside", home=self.home, name="CASE.sbox")        # only LightBurn's own files
        with self.assertRaises(ValueError):
            self.op(op="write", home=os.path.join(self.dir, "x.txt"), files=files)
        # a bad name anywhere in the list: nothing is written
        with self.assertRaises(ValueError):
            self.op(op="write", home=self.home,
                    files=[{"name": "NEW.svg", "content": "x"}, {"name": "x.exe", "content": "x"}])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "NEW.svg")))

    def test_dialogs(self):
        r = self.op(answer=self.home, op="ask_open", start=self.dir)
        self.assertEqual((r["path"], r["text"]), (self.home, '{"name": "CASE"}'))
        self.assertEqual(self.asked[-1], ("open", None, self.dir))
        self.assertEqual(self.op(answer=None, op="ask_open")["cancelled"], True)
        for typed, got in (("NEW", "NEW.sbox"), ("NEW.json", "NEW.sbox"), ("NEW.box.json", "NEW.sbox"),
                           ("NEW.sbox", "NEW.sbox")):
            r = self.op(answer=os.path.join(self.dir, typed), op="ask_save", name="CASE.sbox", start=self.dir)
            self.assertEqual(r["path"], os.path.join(self.dir, got))
        self.assertEqual(self.asked[-1], ("save", "CASE.sbox", self.dir))
        self.op(answer=None, op="ask_save", name="../x.sbox", start=os.path.join(self.dir, "gone"))
        self.assertEqual(self.asked[-1], ("save", None, None))  # no paths in the name, no folder that isn't there

    def test_an_older_box_json_still_opens_and_saves_as_sbox(self):
        old = os.path.join(self.dir, "OLD.box.json")
        with open(old, "w", encoding="utf-8") as f:
            f.write("{}")
        self.assertEqual(self.op(op="read", path=old)["text"], "{}")
        self.op(op="write", home=old, files=[{"name": "OLD.sbox", "content": "{}"}])
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "OLD.sbox")))

    def test_the_launcher_hands_a_file_to_the_page(self):
        self.assertEqual(serve.open_hash(None), "")
        h = serve.open_hash(self.home)
        self.assertTrue(h.startswith("#open="))
        import urllib.parse
        self.assertEqual(urllib.parse.unquote(h[6:]), self.home)


class HolePresets(unittest.TestCase):
    """GET /api/parts: the parts library's confirmed panel holes and windows, in mm."""

    def part(self, root, name, props, deprecated=False, revs=("0001",)):
        d = os.path.join(root, "items", "part", name)
        os.makedirs(d)
        with open(os.path.join(d, "item.json"), "w", encoding="utf-8") as f:
            json.dump({"code": name, "name": name.upper(), "deprecated": deprecated}, f)
        for r in revs:
            os.makedirs(os.path.join(d, "revisions", r))
            with open(os.path.join(d, "revisions", r, "revision.json"), "w", encoding="utf-8") as f:
                json.dump({"data": {"properties": props}}, f)

    def test_confirmed_holes_and_windows_only(self):
        circle = {"type": "circle", "c": {"x": 0, "y": 0}, "r": 3593500}
        rect = {"type": "rect", "min": {"x": 4445000, "y": -4745000}, "max": {"x": 29295000, "y": 4745000},
                "radii": [710000, 710000, 710000, 710000]}
        with tempfile.TemporaryDirectory() as root:
            self.part(root, "pot", {"frontplate_hole": {"status": "confirmed", "value": circle}})
            self.part(root, "oled", {"frontplate_hole": {"status": "confirmed", "value": rect}})
            self.part(root, "led", {"frontplate_window": {"status": "confirmed", "value": circle}})
            self.part(root, "draft", {"frontplate_hole": {"status": "proposed", "value": circle}})
            self.part(root, "old", {"frontplate_hole": {"status": "confirmed", "value": circle}}, deprecated=True)
            self.part(root, "jack", {"frontplate_hole": {"status": "n/a", "value": None}})
            got = serve.part_holes(root)
        self.assertEqual(got, [
            {"code": "led", "name": "LED", "kind": "window", "shape": "round", "d": 7.187},
            {"code": "oled", "name": "OLED", "kind": "hole", "shape": "rect", "w": 24.85, "h": 9.49, "r": 0.71},
            {"code": "pot", "name": "POT", "kind": "hole", "shape": "round", "d": 7.187},
        ])
        self.assertEqual(serve.part_holes(os.path.join(root, "gone")), [])


@unittest.skipUnless(os.name == "nt", "Windows only")
class FileDialog(unittest.TestCase):
    """The real Open / Save As dialog, on a desktop of its own that is never shown: it starts in the box's folder and
    gives back the path picked, or None on Cancel."""

    def run_dialog(self, kind, name, start, press):
        import ctypes
        import time
        from ctypes import wintypes as W
        u = ctypes.windll.user32
        u.CreateDesktopW.restype = W.HANDLE
        u.CreateDesktopW.argtypes = [W.LPCWSTR, W.LPCWSTR, ctypes.c_void_p, W.DWORD, W.DWORD, ctypes.c_void_p]
        u.SetThreadDesktop.argtypes = [W.HANDLE]
        u.CloseDesktop.argtypes = [W.HANDLE]
        u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        enum = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        u.EnumDesktopWindows.argtypes = [W.HANDLE, enum, W.LPARAM]
        desk = u.CreateDesktopW("superboxes-test-%d" % os.getpid(), None, None, 0, 0x10000000, None)
        self.assertTrue(desk)
        got = {}

        def dialog():
            u.SetThreadDesktop(desk)               # before this thread makes any window
            try:
                got["path"] = serve.ask_path(kind, name, start, owner=0)
            except Exception as e:  # noqa: BLE001
                got["error"] = e

        def dialogs():
            found = []

            def each(h, _):
                cls = ctypes.create_unicode_buffer(64)
                u.GetClassNameW(h, cls, 64)
                if cls.value == "#32770" and u.IsWindowVisible(h):
                    found.append(h)
                return True

            u.EnumDesktopWindows(desk, enum(each), 0)
            return found

        t = threading.Thread(target=dialog, daemon=True)
        t.start()
        try:
            deadline = time.monotonic() + 20
            while t.is_alive() and not dialogs() and time.monotonic() < deadline:
                time.sleep(0.1)
            time.sleep(0.5)
            for h in dialogs():
                u.PostMessageW(h, 0x0111, press, 0)           # WM_COMMAND IDOK / IDCANCEL
            t.join(20)
        finally:
            for h in dialogs():
                u.PostMessageW(h, 0x0111, 2, 0)
            t.join(5)
            u.CloseDesktop(desk)
        self.assertNotIn("error", got)
        return got.get("path", "still open")

    def test_save_as_starts_in_the_boxs_folder(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_dialog("save", "CASE.sbox", d, 1), os.path.join(d, "CASE.sbox"))

    def test_open_starts_in_the_boxs_folder_and_cancels(self):
        with tempfile.TemporaryDirectory() as d:
            box = os.path.join(d, "CASE.sbox")
            with open(box, "w") as f:
                f.write("{}")
            self.assertEqual(self.run_dialog("open", "CASE.sbox", d, 1), box)
            self.assertIsNone(self.run_dialog("open", None, d, 2))


@unittest.skipUnless(os.name == "nt", "Windows only")
class BringForward(unittest.TestCase):
    """LightBurn comes to the front only while the superboxes window has focus. Window calls are stubbed."""

    def setUp(self):
        self.real = {n: getattr(serve, n) for n in ("main_window", "window_title", "foreground_window", "raise_window")}
        self.raised = []
        self.focused = "superboxes"
        self.appears_after = 0          # main_window() calls until LightBurn's window exists
        self.calls = 0

        self.open_before = None         # main window of a LightBurn that was already open

        def main_window(pid=None):
            if pid is None:
                return self.open_before
            self.calls += 1
            return 111 if self.calls > self.appears_after else None

        serve.main_window = main_window
        serve.foreground_window = lambda: 222
        serve.window_title = lambda h: self.focused if h == 222 else "x - LightBurn"
        serve.raise_window = self.raised.append

    def tearDown(self):
        for n, f in self.real.items():
            setattr(serve, n, f)

    class Proc:
        def __init__(self, quits=False):
            self.pid, self.quits = 1, quits

        def poll(self):
            return 0 if self.quits else None

    def test_raised_while_the_app_has_focus(self):
        self.appears_after = 3
        self.assertTrue(serve.bring_forward(self.Proc(), timeout=2, poll=0.01))
        self.assertEqual(self.raised, [111])

    def test_handed_to_the_open_lightburn(self):
        # LightBurn was open: the new one passes the file on and quits, the open one comes forward
        self.appears_after, self.open_before = 10 ** 6, 333
        self.assertTrue(serve.bring_forward(self.Proc(quits=True), timeout=2, poll=0.01))
        self.assertEqual(self.raised, [333])

    def test_left_alone_when_you_moved_on(self):
        self.focused = "Elements - Visual Studio Code"
        self.assertFalse(serve.bring_forward(self.Proc(), timeout=1, poll=0.01))
        self.assertEqual(self.raised, [])

    def test_gives_up_when_no_window_comes(self):
        self.appears_after = 10 ** 6
        self.assertFalse(serve.bring_forward(self.Proc(), timeout=0.1, poll=0.01))
        self.assertEqual(self.raised, [])


class Endpoint(unittest.TestCase):
    """The HTTP side: only the app's own page gets an answer."""

    @classmethod
    def setUpClass(cls):
        cls.calls = []
        cls.real = serve.open_in_lightburn
        serve.open_in_lightburn = lambda req: cls.calls.append(req) or {"ok": True, "path": "x", "root": "y"}
        cls.server = serve.http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(serve.Handler, directory=os.path.dirname(__file__)))
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        serve.open_in_lightburn = cls.real

    def post(self, headers, path=serve.OPEN_LIGHTBURN, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = body or json.dumps({"folder": "f"})
        h = {"Host": "localhost:%d" % self.port, "Content-Type": "application/json", **headers}
        c.request("POST", path, body=body, headers={k: v for k, v in h.items() if v is not None})
        r = c.getresponse()
        return r.status, r.read()

    def test_the_app_page_gets_an_answer(self):
        n = len(self.calls)
        status, body = self.post({"Origin": "http://localhost:%d" % self.port, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(len(self.calls), n + 1)

    def test_other_sites_are_refused(self):
        n = len(self.calls)
        for headers in ({"Origin": "https://example.com", "Sec-Fetch-Site": "cross-site"},
                        {"Content-Type": "text/plain"},                        # a form or no-cors fetch
                        {"Host": "evil.example:%d" % self.port},               # DNS rebinding
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.post(headers)[0], 403)
        self.assertEqual(self.post({}, path="/api/other")[0], 404)
        self.assertEqual(len(self.calls), n)

    def test_a_box_endpoint_for_the_app_only(self):
        status, body = self.post({"Origin": "http://localhost:%d" % self.port}, path=serve.BOX,
                                 body=json.dumps({"op": "hello"}))
        self.assertEqual((status, json.loads(body)), (200, {"ok": True}))
        self.assertEqual(self.post({"Sec-Fetch-Site": "cross-site"}, path=serve.BOX,
                                   body=json.dumps({"op": "hello"}))[0], 403)
        big = json.dumps({"op": "hello", "pad": "x" * 200000})     # a box's files are bigger than 64 kB
        self.assertEqual(json.loads(self.post({}, path=serve.BOX, body=big)[1]), {"ok": True})

    def test_a_too_big_request_gets_an_answer(self):
        n = len(self.calls)
        app = {"Origin": "http://localhost:%d" % self.port, "Sec-Fetch-Site": "same-origin"}
        status, body = self.post(app, body=json.dumps({"folder": "f" * 200000}))
        self.assertEqual((status, json.loads(body)), (200, {"ok": False, "error": "request too big"}))
        self.assertEqual(len(self.calls), n)

    def get(self, path, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path, headers={"Host": host or "localhost:%d" % self.port})
        r = c.getresponse()
        return r.status, r.read()

    def test_logos_come_from_the_folder_to_this_pc_only(self):
        import tempfile
        real = serve.LOGO_DIR
        with tempfile.TemporaryDirectory() as d:
            for name in ("a.svg", "b c.svg", "notes.txt"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write("<svg/>")
            serve.LOGO_DIR = d
            try:
                status, body = self.get(serve.LOGOS)
                self.assertEqual((status, json.loads(body)), (200, ["a.svg", "b c.svg"]))
                self.assertEqual(self.get(serve.LOGOS + "/b%20c.svg"), (200, b"<svg/>"))
                self.assertEqual(self.get(serve.LOGOS + "/notes.txt")[0], 404)          # only .svg
                self.assertEqual(self.get(serve.LOGOS + "/..%2Fserve.py")[0], 404)       # no paths
                self.assertEqual(self.get(serve.LOGOS, host="evil.example:%d" % self.port)[0], 403)
            finally:
                serve.LOGO_DIR = real


if __name__ == "__main__":
    unittest.main()
