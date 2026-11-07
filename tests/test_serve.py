"""serve.py's Open in LightBurn endpoint. LightBurn itself is never started: the launch is replaced by a recorder.
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

    def post(self, headers, path=serve.OPEN_LIGHTBURN):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps({"folder": "f"})
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


if __name__ == "__main__":
    unittest.main()
