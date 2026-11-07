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
