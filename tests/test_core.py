"""Core checks for the Python side. Run: .venv/Scripts/python -m unittest discover -s tests -v"""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

from evlaser import machine as M                     # noqa: E402
from superboxes import api, assembly, calibration, capture, catalog, export as X, sheets as S, traylayout  # noqa: E402

MAT = {"key": "poplar3.6", "thickness": 3.6, "burn": 0.1}


def ui_params(name, **over):
    """Every parameter with its default, the way the UI sends them."""
    p = {q["name"]: q["default"] for g in catalog.schema(name) for q in g["params"]}
    p.update(over)
    return p


class Generators(unittest.TestCase):
    def test_every_type_renders_with_ui_params(self):
        for name in catalog.GENERATORS:
            with self.subTest(name=name):
                parts, _info = capture.render(name, ui_params(name), 3.6, 0.1)
                self.assertTrue(parts)
                for p in parts:
                    self.assertGreater(p.w, 0)
                    self.assertGreater(p.h, 0)

    def test_abox_outside_size(self):
        parts, _ = capture.render("ABox", ui_params("ABox", x=50, y=50, h=50, outside=True), 3.6, 0.1)
        self.assertEqual(len(parts), 5)
        for p in parts:   # 50 mm outside + 0.1 burn on both sides
            self.assertAlmostEqual(p.w, 50.2, places=2)
            self.assertAlmostEqual(p.h, 50.2, places=2)

    def test_console_walls_are_separate_pieces(self):
        parts, _ = capture.render("Console", ui_params("Console"), 3.6, 0.1)
        self.assertTrue(all(max(p.w, p.h) < 390 for p in parts))

    def test_nested_outline_matches_the_overlay(self):
        # the fast even-odd (nesting) must give the region the running symmetric_difference gave
        from shapely.geometry import Polygon
        for name in ("HobbyCase", "IntegratedHingeBox", "TrayLayout"):
            parts, _ = capture.render(name, ui_params(name), 3.6, 0.1)
            for p in parts:
                with self.subTest(name=name, part=p.name):
                    slow = Polygon()
                    for ring in capture._rings(p.subpaths[capture.CUT]):
                        if len(ring) >= 4:
                            slow = slow.symmetric_difference(Polygon(ring).buffer(0))
                    self.assertLess(slow.symmetric_difference(p.outline).area, 1e-6 * max(1, slow.area))

    def test_wall_frames_recorded(self):
        parts, _ = capture.render("ABox", ui_params("ABox", x=50, y=50, h=50), 3.6, 0.1)
        self.assertTrue(all(p.walls for p in parts))
        bottom = [p for p in parts if assembly.rect(p)["edges"] == "ffff"]
        self.assertEqual(len(bottom), 1)
        a, b, c, d, e, f = assembly.rect(bottom[0])["frame"]
        self.assertAlmostEqual(c, 3.7, places=3)   # thickness + burn
        self.assertAlmostEqual(f, 3.7, places=3)


class Sheets(unittest.TestCase):
    def assert_rules(self, parts, placements, sheet=S.A3):
        self.assertEqual(X.check_layout(parts, placements, sheet), [])

    def test_packing_obeys_sheet_rules(self):
        for name in catalog.GENERATORS:
            with self.subTest(name=name):
                parts, _ = capture.render(name, ui_params(name), 3.6, 0.1)
                placements, too_big = S.pack([(p.w, p.h) for p in parts])
                fitting = [p for p in placements]
                self.assertEqual(len(fitting) + len(too_big), len(parts))
                self.assert_rules(parts, fitting)

    def test_offcut_is_a_strip_at_the_top(self):
        parts, _ = capture.render("ABox", ui_params("ABox", x=50, y=50, h=50), 3.6, 0.1)
        placements, _ = S.pack([(p.w, p.h) for p in parts])
        self.assertTrue(all(pl["y"] < 10 for pl in placements))   # one row along the bottom edge
        self.assertGreater(S.offcut(placements, [(p.w, p.h) for p in parts], S.A3, 0), 300)

    def test_hand_placed_parts_are_kept_when_valid(self):
        req = {"generator": "ABox", "params": ui_params("ABox", x=50, y=50, h=50), "material": MAT}
        b = api.build(req)
        moved = dict(b["placements"][0], x=200.0, y=200.0)
        b2 = api.build({**req, "layout": [moved]})
        got = [p for p in b2["placements"] if p["part"] == moved["part"]][0]
        self.assertEqual((got["x"], got["y"]), (200.0, 200.0))
        bad = dict(moved, x=280.0)   # sticks out on the right
        b3 = api.build({**req, "layout": [bad]})
        got = [p for p in b3["placements"] if p["part"] == moved["part"]][0]
        self.assertNotEqual(got["x"], 280.0)

    def test_rotation_keeps_the_box(self):
        parts, _ = capture.render("ABox", ui_params("ABox", x=80, y=50, h=30), 3.6, 0.1)
        p = parts[0]
        for rot in (0, 90, 180, 270):
            pl = {"part": 0, "sheet": 0, "x": 20.0, "y": 30.0, "rot": rot}
            e = X.placed(X.ev_part(p, []), p, pl)
            x0, y0, x1, y1 = e.bounds()
            w, h = S.rotated_size(p.w, p.h, rot)
            self.assertAlmostEqual(x0, 20.0, places=2)
            self.assertAlmostEqual(y0, 30.0, places=2)
            self.assertAlmostEqual(x1 - x0, w, places=2)
            self.assertAlmostEqual(y1 - y0, h, places=2)


class Export(unittest.TestCase):
    def setUp(self):
        self.req = {"generator": "ABox", "params": ui_params("ABox", x=50, y=50, h=50), "material": MAT,
                    "options": {}}
        b = api.build(self.req)
        self.req["layout"] = b["placements"]

    def test_lightburn_layers(self):
        res = api.export(self.req)
        self.assertTrue(res["ok"], res.get("error"))
        lb = [f for f in res["files"] if f["kind"] == "lbrn2"][0]["content"]
        self.assertEqual(set(re.findall(r'CutIndex="(\d+)"', lb)), {"1", "2", "30"})
        # CUT runs last: highest priority among output layers
        prios = dict(re.findall(r'<index Value="(\d+)"/>\s*<name Value="[^"]*"/>(?:\s*<\w+ Value="[^"]*"/>)*?\s*<priority Value="(\d+)"/>', lb))
        self.assertGreater(int(prios["2"]), int(prios["1"]))
        self.assertIn('<maxPower Value="100"/>', lb)
        self.assertIn('<speed Value="12.5"/>', lb)
        self.assertIn("Start From: Absolute Coords", lb)
        self.assertIn('Optimize_InnerToOuter Value="1"', lb)

    def test_lightburn_saved_layers_survive_a_rebuild(self):
        first = [f for f in api.export(self.req)["files"] if f["kind"] == "lbrn2"][0]["content"]
        # what LightBurn does when the user saves: header gains AskForSendName, CUT speed changed by hand
        saved = first.replace('MirrorY="False">', 'MirrorY="False" AskForSendName="True">', 1)
        saved = saved.replace('<speed Value="12.5"/>', '<speed Value="11"/>')
        res = api.export({**self.req, "previous": {"0": saved}})
        lb = [f for f in res["files"] if f["kind"] == "lbrn2"][0]["content"]
        self.assertIn('<speed Value="11"/>', lb)
        self.assertIn("carried over", lb)
        res2 = api.export({**self.req, "previous": {"0": first}})   # our own file: nothing to keep
        lb2 = [f for f in res2["files"] if f["kind"] == "lbrn2"][0]["content"]
        self.assertIn('<speed Value="12.5"/>', lb2)

    def test_svg_has_no_tool_layer(self):
        res = api.export(self.req)
        svg = [f for f in res["files"] if f["kind"] == "svg"][0]["content"]
        self.assertIn('id="CUT"', svg)
        self.assertNotIn("#999", svg)
        self.assertIn('width="297mm"', svg)

    def test_bad_layout_is_refused(self):
        bad = [dict(p) for p in self.req["layout"]]
        bad[1]["x"] = bad[0]["x"] + 1   # on top of part 0
        bad[1]["y"] = bad[0]["y"]
        res = api.export({**self.req, "layout": bad})
        self.assertFalse(res["ok"])
        self.assertIn("apart", res["error"])

    def test_mark_on_the_bottom(self):
        parts, _ = capture.render("ABox", self.req["params"], 3.6, 0.1)
        i = X.bottom_part(parts)
        self.assertEqual(assembly.rect(parts[i])["edges"], "ffff")
        deco, warnings = X.decorations(parts, {}, 3.6)
        self.assertEqual(warnings, [])
        self.assertTrue(any(layer == M.LINE for layer, _ in deco[i]))

    def test_mark_keeps_its_spot_while_dragging(self):
        full = api.build({**self.req, "layout": None})
        drag = api.build({**self.req, "layout": None, "params": {**self.req["params"], "x": 52}, "draft": True})
        lines = lambda b: [d["lines"] for p in b["parts"] for d in p["deco"] if d["layer"] == M.LINE]
        self.assertEqual(lines(drag), lines(full))      # same spot, no new search
        other = api.build({**self.req, "generator": "TypeTray", "params": ui_params("TypeTray"), "layout": None,
                           "draft": True})
        self.assertEqual(lines(other), [])               # no full build of this type yet: no mark while dragging

    def test_mark_never_on_a_lid(self):
        for style in ("flat", "overthetop", "ontop", "flatbrim"):
            with self.subTest(style=style):
                parts, _ = capture.render("ABox", ui_params("ABox", x=50, y=50, h=50, Lid_style=style), 3.6, 0.1)
                p = parts[X.bottom_part(parts)]
                self.assertNotRegex(p.name, r"(?i)lid|brim")
                self.assertEqual(assembly.rect(p)["edges"], "ffff")

    def test_mark_text(self):
        import datetime
        self.assertEqual(X.mark_text(datetime.date(2026, 10, 11)), "SG1026")
        self.assertEqual(X.mark_text(datetime.date(2027, 3, 1)), "SG0327")


class Calibration(unittest.TestCase):
    def test_kerf_math(self):
        self.assertAlmostEqual(calibration.kerf_from(98.5), 0.15)
        self.assertAlmostEqual(calibration.kerf_from(100), 0.0)

    def test_kerf_strips(self):
        parts, _deco = calibration.kerf_parts()
        x, y = parts
        self.assertEqual((x.w, x.h), (100.0, 16.0))
        self.assertEqual((y.w, y.h), (16.0, 100.0))
        self.assertEqual(len(x.subpaths[M.CUT]), 10)   # outline + 9 separating cuts

    def test_comb_values_lean_tight(self):
        self.assertEqual(calibration.comb_values(0.07), [0.03, 0.05, 0.07, 0.09, 0.11, 0.13])

    def test_comb_sheet(self):
        r = calibration.comb_sheet({"material": MAT})
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["parts"]), 18)
        names = [p["name"] for p in r["parts"]]
        self.assertIn("fit A 0.10", names)
        res = calibration.calibration_export({"which": "comb", "material": MAT})
        self.assertTrue(res["ok"])

    def test_kerf_strips_never_rotated(self):
        r = calibration.kerf_sheet({})
        self.assertTrue(all(pl["rot"] == 0 for pl in r["placements"]))


class PerAxisKerf(unittest.TestCase):
    MAT = {"key": "poplar3.6", "thickness": 3.6, "burn": 0.08, "burn_x": 0.065, "burn_y": 0.09}

    def test_ellipse_offset(self):
        from shapely.geometry import box
        from superboxes import kerf
        g = kerf.offset_region(box(0, 0, 10, 10).difference(box(4, 4, 6, 6)), 0.05, 0.1)
        for got, want in zip(g.bounds, (-0.05, -0.1, 10.05, 10.1)):
            self.assertAlmostEqual(got, want, places=6)
        for got, want in zip(g.interiors[0].bounds, (4.05, 4.1, 5.95, 5.9)):   # holes shrink
            self.assertAlmostEqual(got, want, places=6)

    def test_equal_burns_stay_with_boxes(self):
        from superboxes import kerf
        self.assertIsNone(kerf.per_axis({"burn_x": 0.07, "burn_y": 0.0702}))
        self.assertEqual(kerf.per_axis(self.MAT), (0.065, 0.09))

    def test_compensation_follows_the_machine_axes(self):
        req = {"generator": "ABox", "params": ui_params("ABox", x=60, y=40, h=30), "material": self.MAT}
        parts, info = api._render(req)
        self.assertEqual(info["comp"], (0.065, 0.09))
        for p in parts[:2]:
            for rot in (0, 90, 180, 270):
                pl = {"part": p.index, "sheet": 0, "x": 20.0, "y": 20.0, "rot": rot}
                nom = X._on_sheet(p.outline, p, pl).bounds
                got = X.placed_shape(p, pl, info["comp"]).bounds
                self.assertAlmostEqual((got[2] - got[0]) - (nom[2] - nom[0]), 0.13, places=4)
                self.assertAlmostEqual((got[3] - got[1]) - (nom[3] - nom[1]), 0.18, places=4)
                # the compensated outline stays inside the part's box on the sheet
                w, h = S.rotated_size(p.w, p.h, rot)
                self.assertGreaterEqual(got[0], 20.0 - 1e-6)
                self.assertLessEqual(got[3], 20.0 + h + 1e-6)

    def test_export_writes_compensated_cuts(self):
        req = {"generator": "ABox", "params": ui_params("ABox", x=50, y=50, h=50), "material": self.MAT,
               "options": {}}
        req["layout"] = api.build(req)["placements"]
        res = api.export(req)
        self.assertTrue(res["ok"], res.get("error"))
        lb = [f for f in res["files"] if f["kind"] == "lbrn2"][0]["content"]
        self.assertIn("per axis", lb)
        self.assertEqual(set(re.findall(r'CutIndex="(\d+)"', lb)), {"1", "2", "30"})

    def test_comb_per_axis(self):
        spec = calibration.comb_spec({"kerf": {"x": 0.14, "y": 0.18}})
        self.assertEqual(spec["mode"], "axis")
        self.assertEqual(spec["values"], [-0.04, -0.02, 0.0, 0.02, 0.04, 0.06])
        parts, _deco = calibration.comb_parts(3.6, spec)
        self.assertEqual(len(parts), 21)                       # 6 rows + the turned check row
        self.assertEqual([p.rot for p in parts[-3:]], [90, 90, 90])
        self.assertEqual(parts[0].comp, (0.03, 0.05))          # kerf/2 - 0.04 per axis
        layout = calibration.comb_layout(parts, S.A3)
        self.assertEqual(X.check_layout(parts, layout, S.A3), [])
        self.assertEqual(calibration.comb_spec({"kerf": {"x": 0.14, "y": 0.14}})["mode"], "iso")


class TrayLayoutSync(unittest.TestCase):
    def test_walls_survive_size_change(self):
        t = traylayout.sync(None, "40*3", "30*2")
        lines = t.split("\n")
        i = [k for k, line in enumerate(lines) if line.startswith("+")][1]
        lines[i] = lines[i][:1] + " " + lines[i][2:]
        t2 = traylayout.sync("\n".join(lines), "50:40:30", "35*2")
        self.assertTrue(t2.split("\n")[i].startswith("+ +"))
        self.assertIn("50.0mm", t2)


class Assembly(unittest.TestCase):
    def outer_bounds(self, parts, asm):
        import numpy as np
        pts = []
        for p, pl in zip(parts, asm["parts"]):
            M = np.array(pl["m"]).reshape(3, 4)
            x0, y0, x1, y1 = p.shape.bounds
            pts += [M @ [bx, by, bz, 1] for bx in (x0, x1) for by in (y0, y1) for bz in (0, 3.6)]
        pts = np.array(pts)
        return pts.max(0) - pts.min(0)

    def test_abox_assembles_without_clashes(self):
        for dims in ({"x": 50, "y": 50, "h": 50}, {"x": 140, "y": 90, "h": 60}):
            with self.subTest(**dims):
                parts, _ = capture.render("ABox", ui_params("ABox", outside=True, **dims), 3.6, 0.1)
                asm = assembly.assemble("ABox", parts, 3.6)
                self.assertEqual(asm["kind"], "assembled")
                self.assertTrue(all(pl["group"] == "body" for pl in asm["parts"]))
                self.assertEqual(assembly.clashes(parts, [pl["m"] for pl in asm["parts"]], 3.6), [])
                size = self.outer_bounds(parts, asm)
                for got, want in zip(size, (dims["x"], dims["y"], dims["h"])):
                    self.assertAlmostEqual(got, want, places=2)

    def test_abox_lids_never_misplace_the_body(self):
        for style in ("none", "flat", "chest", "overthetop", "ontop", "flatbrim", "flatfang"):
            with self.subTest(style=style):
                parts, _ = capture.render("ABox", ui_params("ABox", x=60, y=50, h=40, Lid_style=style), 3.6, 0.1)
                asm = assembly.assemble("ABox", parts, 3.6)
                self.assertEqual(sum(pl["kind"] == "wall" for pl in asm["parts"]), 5)
                ms = [pl["m"] if pl["kind"] == "wall" else None for pl in asm["parts"]]
                self.assertEqual(assembly.clashes(parts, ms, 3.6), [])

    def test_every_type_assembles_cleanly(self):
        # the acceptance rule from the gallery grill: all parts in place, no clashes, nothing floating
        loose_ok = {"Console2": 8}       # panel springs, latches, latch clamps: not placed yet
        for name in catalog.GENERATORS:
            with self.subTest(name=name):
                parts, info = capture.render(name, ui_params(name), 3.7, 0.1)
                asm = assembly.assemble(name, parts, 3.7, attrs=info["attrs"])
                self.assertEqual(asm["kind"], "assembled")
                loose = [pl for pl in asm["parts"] if pl["group"] == "loose"]
                self.assertEqual(len(loose), loose_ok.get(name, 0))
                ms = [pl["m"] if pl["group"] != "loose" else None for pl in asm["parts"]]
                self.assertEqual(assembly.clashes(parts, ms, 3.7), [])
                self.assertEqual(assembly.loose_parts(parts, ms, 3.7), [])

    def test_dimensions_match_the_parameters(self):
        # what the 3D writes on the box: the outside as measured, the inside as the cavity
        size = lambda b: [round(h - l, 2) for l, h in zip(b["lo"], b["hi"])]
        build = lambda name, **p: (lambda r: (r["assembly"], r["info"]["attrs"]))(
            api.build({"generator": name, "params": ui_params(name, **p), "material": MAT, "options": {}}))
        asm, _ = build("ABox", x=50, y=60, h=40, outside=True)
        self.assertEqual(size(asm["outside"]), [50, 60, 40])
        asm, _ = build("ABox", x=50, y=60, h=40, outside=False)
        self.assertEqual(size(asm["inside"]), [50, 60, 40])
        self.assertEqual(size(asm["outside"])[:2], [50 + 2 * 3.6, 60 + 2 * 3.6])
        asm, attrs = build("TypeTray", sx="30*2", sy="40*3", h=50, outside=False)
        self.assertEqual(sorted(tuple(c["size"]) for c in asm["inside"]["cells"]), [(30, 40)] * 6)
        self.assertEqual(size(asm["inside"]), [60 + 3.6, 120 + 2 * 3.6, 50])
        asm, attrs = build("HingeBox", x=80, y=60, h=50, outside=False)
        self.assertGreater(size(asm["inside"])[2], 50)            # lid closed: body plus the lid's height
        asm, _ = build("Console2", front_height=35)
        self.assertEqual(asm["inside"]["front"], 35)
        self.assertEqual(build("ABox")[0]["inside"]["cells"], [])  # one compartment: nothing to label
        for name in catalog.GENERATORS:
            with self.subTest(name=name):
                asm, _ = build(name)
                lo, hi = asm["outside"]["lo"], asm["outside"]["hi"]
                for a, b in zip(asm["inside"]["lo"], lo):
                    self.assertGreaterEqual(a, b - 1e-6)
                for a, b in zip(asm["inside"]["hi"], hi):
                    self.assertLessEqual(a, b + 1e-6)

    def test_traylayout_compartments_follow_the_walls(self):
        p = ui_params("TrayLayout")
        r = api.build({"generator": "TrayLayout", "params": p, "material": MAT, "options": {}})
        self.assertEqual(len(r["assembly"]["inside"]["cells"]), 9)
        hw, vw = r["info"]["attrs"]["hwalls"], r["info"]["attrs"]["vwalls"]
        self.assertEqual(len(assembly._regions(hw, vw, 3, 3)), 9)
        vw = [row[:] for row in vw]
        vw[0][1] = False                    # no wall between the first two cells of the top row
        regions = assembly._regions(hw, vw, 3, 3)
        self.assertEqual(len(regions), 8)
        self.assertIn([(0, 0), (0, 1)], regions)

    def test_misplaced_wall_clashes(self):
        import numpy as np
        parts, _ = capture.render("ABox", ui_params("ABox", x=50, y=50, h=50), 3.6, 0.1)
        asm = assembly.assemble("ABox", parts, 3.6)
        ms = [np.array(pl["m"]) for pl in asm["parts"]]
        ms[3][3] += 2.0   # x translation of the left wall: 2 mm into the box
        self.assertTrue(assembly.clashes(parts, ms, 3.6))

    def test_unknown_types_lie_flat(self):
        parts, _ = capture.render("HingeBox", ui_params("HingeBox"), 3.6, 0.1)
        asm = assembly.assemble("NoAssemblerForThis", parts, 3.6)   # the fallback for types without 3D
        self.assertEqual(asm["kind"], "flat")
        self.assertEqual(len(asm["parts"]), len(parts))

    def test_islands_stay_with_their_part(self):
        # the rectangle cut inside IntegratedHingeBox's round hinge hole must stay in that wall on the sheet,
        # and the ring between them is a loose hinge disc for the 3D
        parts, _ = capture.render("IntegratedHingeBox", ui_params("IntegratedHingeBox"), 3.7, 0.1)
        self.assertTrue(all(max(p.w, p.h) > 20 for p in parts))
        self.assertEqual(sum(len(p.children) for p in parts), 2)

    def test_traylayout_plate_is_one_part(self):
        parts, _ = capture.render("TrayLayout", ui_params("TrayLayout"), 3.7, 0.1)
        self.assertEqual(len(parts), 9)   # 8 walls + the base plate in one piece


class Api(unittest.TestCase):
    def test_errors_come_back_as_json(self):
        r = json.loads(api.call("build", json.dumps({"generator": "PirateChest", "params": {"n": 2},
                                                      "material": MAT})))
        self.assertFalse(r["ok"])
        self.assertIn("n", r["error"])


if __name__ == "__main__":
    unittest.main()
