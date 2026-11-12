"""The stamp case (ported from stampcaser 1.0.0). Run: .venv/Scripts/python -m unittest tests.test_stampcase -v

Parity: until stampcaser is retired, every existing case must come out of superboxes with the same cut and engrave
geometry as out of stampcaser (.grill/stamp-case-merge.md). Those tests need C:\\Projects\\stampcaser and the case
files in their project folders, and skip without them (the cases are private and never enter this repo).
"""
import datetime
import importlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from shapely.geometry import MultiLineString  # noqa: E402

from superboxes.stampcase import config as C, layout as L, model, pack, parts as P  # noqa: E402

STAMPCASER = r"C:\Projects\stampcaser"
CASES = [r"C:\Projects\ELEMENTS SYNTH\hw\packaging\ELEMENTS REV.C PACKAGING.stampcase",
         r"C:\Projects\MINIPUNK\hardware\MINIPUNK MAXIPUNK.stampcase",
         r"C:\Projects\stampcaser\first-cut\pages check.stampcase"]
DAY = datetime.date(2026, 11, 7)
MAT = {"key": "poplar3.6", "thickness": 3.7, "kerf_x": 0.33, "kerf_y": 0.26}


def sample_case(n=6):
    case = model.Case(project="TEST SET")
    for i in range(n):
        case.pockets.append(model.Pocket(name="Stamp %d" % (i + 1), w=30 + 5 * (i % 3), h=40 + 10 * (i % 2)))
    pack.repack(case)
    return case


def _old():
    """stampcaser's own modules, or None when it isn't on this PC."""
    if not os.path.isdir(os.path.join(STAMPCASER, "stampcaser")):
        return None
    if STAMPCASER not in sys.path:
        sys.path.append(STAMPCASER)
    return {m: importlib.import_module("stampcaser." + m) for m in ("model", "layout", "build")}


def _geom_diff(a, b):
    """How far apart two items' geometries are: area of the symmetric difference for regions, Hausdorff distance for
    lines and points."""
    if a.is_empty and b.is_empty:
        return 0.0
    if a.geom_type in ("Polygon", "MultiPolygon") and b.geom_type in ("Polygon", "MultiPolygon"):
        return a.symmetric_difference(b).area
    return a.hausdorff_distance(b)


def _items(part):
    """(layer, kind, geometry) of a placed evlaser Part, circles as their buffered region."""
    out = []
    for it in part.items:
        layer, kind, *data = it
        if kind == "circle":
            from shapely.geometry import Point
            g = Point(data[0]).buffer(data[1], quad_segs=16)
        else:
            g = data[0]
        out.append((layer, kind, g))
    return out


class Port(unittest.TestCase):
    def setUp(self):
        C.use_material(MAT)

    def test_sample_case_builds(self):
        case = sample_case()
        lay = L.Layout(case, DAY)
        self.assertEqual(lay.errors, [], [p.text for p in lay.errors])
        self.assertEqual(len(P.board_parts(lay)), case.board_count)

    def test_material_comes_from_the_request(self):
        C.use_material({"key": "poplar3.6", "thickness": 3.7, "kerf_x": 0.2, "kerf_y": 0.2})
        try:
            self.assertAlmostEqual(C.BURN_X, 0.1)
            self.assertAlmostEqual(C.BURN_Y, 0.1)
        finally:
            C.use_material(MAT)
        self.assertAlmostEqual(C.BURN_X, 0.165)
        self.assertAlmostEqual(C.BURN_Y, 0.13)

    def test_mark_has_no_leading_zero(self):
        self.assertEqual(L.mark_text(datetime.date(2026, 8, 1)), "SG826")
        self.assertEqual(L.mark_text(datetime.date(2026, 10, 1)), "SG1026")

    def test_shared_packer_never_needs_more_sheets_than_stampcaser(self):
        """One packer for every type (stamp-case-merge): it must match stampcaser's grid for stamp-case boards."""
        import random
        from superboxes import sheets as S
        from superboxes.stampcase import sheets as SH
        rng = random.Random(1)
        cases = [sample_case()]
        for k in range(10):
            case = model.Case(project="R%d" % k)
            for i in range(rng.randint(1, 14)):
                case.pockets.append(model.Pocket(name="S%d" % i, w=rng.uniform(20, 90), h=rng.uniform(20, 90)))
            pack.repack(case)
            cases.append(case)
        for k, case in enumerate(cases):
            lay = L.Layout(case)
            w, h = lay.size
            if not SH.per_sheet(w, h):
                continue
            parts = P.board_parts(lay)
            pl, _ = S.pack([(p.w, p.h) for p in parts], S.A3)
            with self.subTest(case=k, board=(round(w), round(h))):
                self.assertLessEqual(max(x["sheet"] for x in pl) + 1, SH.sheet_count(w, h, len(parts)))

    def test_box_file_round_trip(self):
        import convert_stampcase as CV
        case = sample_case(4)
        cfg = CV.box_config(case, "test set", "test set.stampcase", DAY)
        self.assertEqual(cfg["generator"], "StampCase")
        self.assertEqual(model.Case.from_dict(cfg["params"]).to_dict(), case.to_dict())


class Parity(unittest.TestCase):
    """The same case, built by stampcaser and by superboxes: same board, magnets and problems, and every board's cut
    and engrave geometry as LightBurn gets it (kerf per axis after turning), upright and turned a quarter. Where the
    boards sit on the sheets is the shared packer's business now (stamp-case-merge: one packer), so the boards are
    compared aligned on their cut outline."""

    @classmethod
    def setUpClass(cls):
        cls.old = _old()

    def setUp(self):
        if self.old is None:
            self.skipTest("stampcaser isn't on this PC")
        C.use_material(MAT)

    def _compare(self, path):
        from shapely import affinity
        old_case = self.old["model"].Case.load(path)
        new_case = model.Case.load(path)
        old_lay = self.old["layout"].Layout(old_case, DAY)
        new_lay = L.Layout(new_case, DAY)
        self.assertEqual([p.text for p in new_lay.problems], [p.text for p in old_lay.problems])
        for a, b in zip(new_lay.rect, old_lay.rect):
            self.assertAlmostEqual(a, b, places=6)
        self.assertEqual(len(new_lay.magnets), len(old_lay.magnets))
        for m, n in zip(new_lay.magnets, old_lay.magnets):
            self.assertAlmostEqual(m[0], n[0], places=6)
            self.assertAlmostEqual(m[1], n[1], places=6)
        old_pages = old_lay.pages()
        new_parts = P.board_parts(new_lay)
        self.assertEqual([p.name for p in new_parts], [t for _, t, _ in old_pages])
        spot = importlib.import_module("stampcaser.sheets").Spot
        for rot in (0, 90):
            for part, (_key, title, items) in zip(new_parts, old_pages):
                old_ev, old_outline = self.old["build"]._placed(title, items, old_lay.rect, spot(0, bool(rot), 50, 60))
                new_ev = part.placed_ev({"part": part.index, "sheet": 0, "x": 50, "y": 60, "rot": rot})
                ni, oi = _items(new_ev), _items(old_ev)
                self.assertEqual([(l, k) for l, k, _ in ni], [(l, k) for l, k, _ in oi], title)
                n_out = next(g for (l, k, g), it in zip(ni, part.items) if it[0] == "outline")
                dx = old_outline.bounds[0] - n_out.bounds[0]
                dy = old_outline.bounds[1] - n_out.bounds[1]
                for (l, k, g), (_l, _k, h) in zip(ni, oi):
                    d = _geom_diff(affinity.translate(g, dx, dy), h)
                    self.assertLess(d, 1e-6, "%s, turned %d: layer %d %s off by %g" % (title, rot, l, k, d))

    def test_every_existing_case(self):
        found = [p for p in CASES if os.path.exists(p)]
        if not found:
            self.skipTest("no .stampcase files on this PC")
        for path in found:
            with self.subTest(case=os.path.basename(path)):
                self._compare(path)

    def test_rest_pieces(self):
        """superboxes' rest pieces work for any layout; on stampcaser's own sheets (its grids, its boards) they are
        stampcaser's pieces, cut by the same lines."""
        from superboxes import sheets as S
        cases = [p for p in CASES if os.path.exists(p)] + [None]
        for path in cases:
            case = self.old["model"].Case.load(path) if path else None
            if case is None:     # a small case: two boards to a sheet, with a piece beside them
                case = self.old["model"].Case.from_dict(sample_case(4).to_dict())
            for sheet in self.old["build"].sheets_of(self.old["layout"].Layout(case, DAY)):
                with self.subTest(case=os.path.basename(path or "sample"), sheet=sheet.n):
                    outlines = [b.outline for b in sheet.boards]
                    pieces = S.rest_pieces([o.bounds for o in outlines], S.A3, [b.title for b in sheet.boards])
                    self.assertEqual([p.name for p in pieces], [p.name for p in sheet.pieces])
                    for p, q in zip(pieces, sheet.pieces):    # edges on the cut outline, not on its nominal box
                        for a, b in zip(p.rect, q.rect):
                            self.assertAlmostEqual(a, b, delta=1e-3)
                    lines = S.frame_lines(pieces, outlines, S.A3)
                    if sheet.frame is None:
                        self.assertIsNone(lines)
                    else:
                        # within the 0.01 mm where a frame cut meets a board's cut: at a rounded corner, a line a
                        # micron higher leaves that zone a few microns further along
                        self.assertLess(_geom_diff(lines, sheet.frame.items[0][2]), 0.01)


class Api(unittest.TestCase):
    """The stamp case through superboxes' api, as the page calls it."""

    def call(self, fn, req):
        import json
        from superboxes import api
        res = json.loads(api.call(fn, json.dumps(req)))
        self.assertTrue(res.get("ok"), res.get("error", "") + res.get("trace", ""))
        return res

    def req(self, case):
        params = case.to_dict()
        params.pop("version")
        return {"generator": "StampCase", "params": params, "material": MAT,
                "sheet": {"name": "A3", "w": 297, "h": 420, "usable": 390}}

    def test_in_the_catalog(self):
        names = [g["name"] for g in self.call("catalog", {})["generators"]]
        self.assertEqual(names[-1], "StampCase")
        self.assertEqual(self.call("schema", {"generator": "StampCase"})["groups"], [])

    def test_build_and_export(self):
        r = self.req(sample_case())
        b = self.call("build", r)
        self.assertEqual([p["name"] for p in b["parts"]], ["Base", "Lower pocket board", "Top pocket board", "Lid"])
        self.assertEqual(len(b["placements"]), 4)
        self.assertEqual(b["stampcase"]["problems"], [])
        self.assertEqual(b["assembly"]["parts"][3]["group"], "lid")
        e = self.call("export", dict(r, layout=b["placements"], name="test set"))
        lb = [f for f in e["files"] if f["kind"] == "lbrn2"]
        self.assertEqual(len(lb), 1)
        import html
        self.assertIn('STAMP CASE "TEST SET"', html.unescape(lb[0]["content"]))

    def test_export_refuses_errors(self):
        case = sample_case(2)
        case.pockets[1].x = case.pockets[0].x + 1        # on top of each other
        case.pockets[1].y = case.pockets[0].y
        from superboxes import api
        import json
        res = json.loads(api.call("export", json.dumps(self.req(case))))
        self.assertFalse(res["ok"])
        self.assertIn("wood between", res["error"])

    def test_ops(self):
        case = sample_case(2)
        r = self.req(case)
        added = self.call("stampcase_op", dict(r, op="add", pocket={"name": "New", "w": 20, "h": 30}))
        self.assertEqual(len(added["params"]["pockets"]), 3)
        new_id = added["select"][0]
        dup = self.call("stampcase_op", dict(r, params=added["params"], op="duplicate", ids=[new_id]))
        self.assertEqual(len(dup["params"]["pockets"]), 4)
        lay = L.Layout(model.Case.from_dict(dup["params"]))
        self.assertEqual(lay.errors, [], [p.text for p in lay.errors])
        rp = self.call("stampcase_op", dict(r, params=dup["params"], op="repack"))
        self.assertEqual(len(rp["params"]["pockets"]), 4)

    def test_thick_stamp_is_an_error(self):
        case = sample_case(2)
        case.pockets[0].thickness = 9.0
        lay = L.Layout(case)
        self.assertTrue(any("thick" in p.text and "3 pocket boards" in p.text for p in lay.errors))
        case.pocket_boards = 3
        self.assertFalse(any("thick" in p.text for p in L.Layout(case).problems))


if __name__ == "__main__":
    unittest.main()
