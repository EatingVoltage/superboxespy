"""Core checks for the Python side. Run: .venv/Scripts/python -m unittest discover -s tests -v"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

import shapely                                       # noqa: E402

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

    def test_rest_pieces_never_touch_a_part(self):
        """Every type: the rest pieces are clear of the parts and of each other, big enough, and their cuts never run
        into a part (they may only meet its cut) nor above the reach limit."""
        sw, sh, usable = S.sheet_tuple(S.A3)
        for name in catalog.GENERATORS:
            with self.subTest(name=name):
                parts, info = capture.render(name, ui_params(name), 3.6, 0.1)
                placements, _ = S.pack([(p.w, p.h) for p in parts])
                for n in range(max(pl["sheet"] for pl in placements) + 1):
                    on = [pl for pl in placements if pl["sheet"] == n]
                    outlines = [X.placed_shape(parts[pl["part"]], pl) for pl in on]
                    pieces, frame = X.rest_part(parts, on, S.A3)
                    self.assertEqual(pieces[0].name, "top rest piece")
                    boxes = [shapely.box(*p.rect) for p in pieces]
                    for k, b in enumerate(boxes):
                        self.assertGreaterEqual(min(pieces[k].size), S.FRAME_MIN_PIECE)
                        for o in outlines:
                            self.assertLess(b.intersection(o).area, 1e-6, pieces[k].name)
                        for c in boxes[k + 1:]:
                            self.assertLess(b.intersection(c).area, 1e-6)
                    lines = frame.items[0][2]
                    for o in outlines:
                        self.assertLess(lines.intersection(o.buffer(-0.05)).length, 1e-9)
                    x0, y0, x1, y1 = lines.bounds
                    self.assertGreaterEqual(x0, -1e-9)
                    self.assertGreaterEqual(y0, -1e-9)
                    self.assertLessEqual(x1, sw + S.FRAME_OVERSHOOT + 1e-9)
                    self.assertLessEqual(y1, usable)

    def test_sheet_view_draws_the_same_rest_pieces(self):
        """src/sheetview.ts keeps a copy of rest_pieces to draw them while parts are dragged, from the parts' boxes:
        on every type it finds the pieces the export cuts from the outlines, within half a mm."""
        node = shutil.which("node")
        if not node:
            self.skipTest("no Node.js")
        mat = {"key": "poplar3.6", "thickness": 3.7, "kerf_x": 0.33, "kerf_y": 0.26, "burn_x": 0.165, "burn_y": 0.13}
        cases, want = [], []
        for name in catalog.GENERATORS:
            req = {"generator": name, "params": ui_params(name), "material": mat, "options": {}}
            parts, info = api._render(req)
            b = api.build(req)
            sheets = list(range(len(b["sheets"])))
            cases.append({"parts": [{"name": p["name"], "w": p["w"], "h": p["h"]} for p in b["parts"]],
                          "placements": b["placements"], "sheet": S.A3, "sheets": sheets})
            want.append([[[q.name] + list(q.rect) for q in X.rest_part(parts, [pl for pl in b["placements"]
                                                                              if pl["sheet"] == n], S.A3,
                                                                        info["comp"])[0]] for n in sheets])
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "cases.json")
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(cases, fh)
            run = subprocess.run([node, "--experimental-transform-types", "--no-warnings",
                                  os.path.join(os.path.dirname(__file__), "rest_pieces.mjs"), f],
                                 capture_output=True, text=True, timeout=60,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode and "transform-types" in run.stderr:
            self.skipTest("this Node.js can't run TypeScript")
        self.assertEqual(run.returncode, 0, run.stderr)
        got = json.loads(run.stdout)
        for name, g, w in zip(catalog.GENERATORS, got, want):
            for n, (gs, ws) in enumerate(zip(g, w)):
                with self.subTest(name=name, sheet=n + 1):
                    self.assertEqual([q[0] for q in gs], [q[0] for q in ws])
                    for q, r in zip(gs, ws):
                        for u, v in zip(q[1:], r[1:]):
                            self.assertAlmostEqual(u, v, delta=0.5)

    def test_rest_pieces_of_a_ragged_layout(self):
        """Parts of three heights side by side: a piece beside each step, a thin band joins its neighbour."""
        boxes = [(3, 3, 100, 200), (101.5, 3, 150, 125), (151.5, 3, 200, 120)]
        pieces = S.rest_pieces(boxes, S.A3, ["tall", "middle", "short"])
        self.assertEqual([(p.name, tuple(round(v, 3) for v in p.rect)) for p in pieces], [
            ("top rest piece", (0, 200, 297, 420)),
            ("right rest piece", (200, 0, 297, 125)),     # the 5 mm band over "short" joins the one below
            ("rest piece beside the tall", (100, 125, 297, 200)),
        ])
        # nothing worth cutting: the parts fill the sheet up to the reach limit
        self.assertEqual(S.rest_pieces([(3, 3, 294, 390)], S.A3), [])

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
        self.assertEqual(set(re.findall(r'CutIndex="(\d+)"', lb)), {"1", "2", "7", "30"})
        # CUT after the engraving, then the rest-piece cuts (C07, CUT's values) last of all
        prios = dict(re.findall(r'<index Value="(\d+)"/>\s*<name Value="[^"]*"/>(?:\s*<\w+ Value="[^"]*"/>)*?\s*<priority Value="(\d+)"/>', lb))
        self.assertGreater(int(prios["2"]), int(prios["1"]))
        self.assertGreater(int(prios["7"]), int(prios["2"]))
        self.assertIn('<name Value="4 CUT frame - frees the rest pieces, runs last"/>', lb)
        self.assertEqual(lb.count('<speed Value="12.5"/>'), 2)
        self.assertIn("Rest pieces: top rest piece 297 x ", lb)
        self.assertEqual(res["sheets"][0]["pieces"][0]["name"], "top rest piece")
        self.assertIn('<maxPower Value="100"/>', lb)
        self.assertIn('<speed Value="12.5"/>', lb)
        self.assertIn("Start From: Absolute Coords", lb)
        self.assertIn('Optimize_InnerToOuter Value="1"', lb)

    def test_rest_cuts_can_be_switched_off(self):
        res = api.export({**self.req, "options": {"rest_cuts": False}})
        lb = [f for f in res["files"] if f["kind"] == "lbrn2"][0]["content"]
        self.assertEqual(set(re.findall(r'CutIndex="(\d+)"', lb)), {"1", "2", "30"})
        self.assertIn('<name Value="3 CUT red - through, runs last"/>', lb)
        self.assertIn("Offcut 297 x ", lb)
        self.assertNotIn("frame", lb)
        self.assertEqual(res["sheets"][0]["pieces"], [])

    def test_lightburn_saved_layers_survive_a_rebuild(self):
        first = [f for f in api.export(self.req)["files"] if f["kind"] == "lbrn2"][0]["content"]
        # what LightBurn does when the user saves: header gains AskForSendName, CUT speed changed by hand
        saved = first.replace('<LightBurnProject ', '<LightBurnProject AskForSendName="True" ', 1)
        saved = saved.replace('<speed Value="12.5"/>', '<speed Value="11"/>')
        res = api.export({**self.req, "previous": saved})
        lb = [f for f in res["files"] if f["kind"] == "lbrn2"][0]["content"]
        self.assertIn('<speed Value="11"/>', lb)
        self.assertIn("carried over", lb)
        res2 = api.export({**self.req, "previous": first})   # our own file: nothing to keep
        lb2 = [f for f in res2["files"] if f["kind"] == "lbrn2"][0]["content"]
        self.assertIn('<speed Value="12.5"/>', lb2)

    def test_one_project_with_a_page_per_sheet(self):
        req = {"generator": "ABox", "params": ui_params("ABox", x=250, y=250, h=250), "material": MAT,
               "options": {}}
        b = api.build(req)
        n = len(b["sheets"])
        self.assertGreater(n, 1)
        req["layout"] = b["placements"]
        res = api.export(req)
        self.assertTrue(res["ok"], res.get("error"))
        lbs = [f for f in res["files"] if f["kind"] == "lbrn2"]
        self.assertEqual(len(lbs), 1)
        self.assertEqual(lbs[0]["name"], "abox.lbrn2")
        lb = lbs[0]["content"]
        self.assertIn('AppVersion="2.2.00"', lb)
        self.assertIn('CurrentPage="0" Page0Name="Sheet 1"', lb)
        self.assertEqual(re.findall(r'SubType="Page" Name="([^"]+)"', lb), ["Sheet %d" % k for k in range(2, n + 1)])
        self.assertEqual(lb.count("<CutSetting "), len(set(re.findall(r'CutIndex="(\d+)"', lb))))   # layers once
        self.assertEqual(lb.count("<Notes "), 1)
        self.assertIn("%d sheets, one page each" % n, lb)
        self.assertEqual(len([f for f in res["files"] if f["kind"] == "svg"]), n)
        self.assertEqual(len(res["sheets"]), n)
        # every part sits on its page once: one group per part plus the T1 sheet and the rest-piece cuts per page
        self.assertEqual(len(re.findall(r'<Shape Type="Group">', lb)), len(b["parts"]) + 2 * n)

    def test_t1_stays_inside_the_machine_area(self):
        # LightBurn's Select All takes T1 too; anything past the 390 mm reach makes it warn "out of bounds"
        lb = [f for f in api.export(self.req)["files"] if f["kind"] == "lbrn2"][0]["content"]
        ys = [float(y) for verts in re.findall(r'CutIndex="30"[^>]*>\s*<XForm>[^<]*</XForm>\s*<VertList>([^<]*)', lb)
              for y in re.findall(r"V-?[\d.]+ (-?[\d.]+)", verts)]
        self.assertTrue(ys)
        self.assertLessEqual(max(ys), 390.0)
        self.assertNotIn("V297 420", lb)

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
        self.assertEqual(X.mark_text(datetime.date(2027, 3, 1)), "SG327")   # no leading zero (eVlaser)


class Faces(unittest.TestCase):
    """The face editor's items on the closed box (python/superboxes/faces.py), on the CANVAS example: an ABox with the
    over-the-top lid."""

    def req(self, x=240, items=None):
        return {"generator": "ABox", "params": ui_params("ABox", x=x, y=170, h=90, Lid_style="overthetop"),
                "material": MAT, "options": {}, "faces": {"top": items or []}}

    def test_the_shoebox_lid_sits_on_the_box(self):
        req = self.req()
        parts, info = api._render(req)
        asm = api.build(req)["assembly"]
        mats = [a["m"] if a["group"] != "loose" else None for a in asm["parts"]]
        self.assertTrue(all(m is not None for m in mats))
        self.assertEqual(assembly.clashes(parts, mats, info["thickness"]), [])
        self.assertEqual(assembly.loose_parts(parts, mats, info["thickness"]), [])
        lid = [a for a in asm["parts"] if a["group"] == "lid"]
        self.assertEqual(len(lid), 5)
        self.assertTrue(all(a["motion"] == lid[0]["motion"] and a["motion"]["dir"] == [0, 0, 1] for a in lid))

    def test_faces_of_the_closed_box(self):
        b = api.build(self.req())
        names = {f: b["parts"][v["part"]]["name"] for f, v in b["faces"].items()}
        self.assertEqual(set(names), {"top", "bottom", "front", "back", "left", "right"})
        self.assertEqual(names["top"], "lid top")
        self.assertNotIn("lid", names["front"])              # the wall, not the lid's rim
        top = b["faces"]["top"]
        # the finished wood, a ruler's reading: the cut path's box less the burn on both sides
        self.assertAlmostEqual(top["w"], b["parts"][top["part"]]["w"] - 2 * MAT["burn"], places=2)

    def test_items_keep_their_anchor_when_the_box_grows(self):
        items = [{"id": "logo", "kind": "logo", "logo": "none.svg", "size": 20, "anchor": "tl", "dx": 14, "dy": -14},
                 {"id": "t", "kind": "text", "text": "CANVAS SYNTH", "size": 18, "bold": True, "anchor": "c"},
                 {"id": "s", "kind": "text", "text": "STARTER KIT\nBASE18", "size": 6, "anchor": "br", "dx": -14, "dy": 14}]
        for x in (240, 280):
            with self.subTest(x=x):
                f = api.build(self.req(x, items))["faces"]["top"]
                got = {i["id"]: i for i in f["items"]}
                x0, y0, x1, y1 = got["t"]["bounds"]
                self.assertAlmostEqual((x0 + x1) / 2, f["w"] / 2, places=3)          # still centred
                self.assertAlmostEqual((y0 + y1) / 2, f["h"] / 2, places=3)
                x0, y0, x1, y1 = got["s"]["bounds"]
                self.assertAlmostEqual(f["w"] - x1, 14, places=3)                     # 14 mm from the right
                self.assertAlmostEqual(y0, 14, places=3)
                self.assertFalse(got["t"]["bad"] or got["s"]["bad"])

    def test_an_item_in_the_finger_joints_is_refused(self):
        req = self.req(items=[{"id": "t", "kind": "text", "text": "EDGE", "size": 8, "anchor": "bl", "dx": 1, "dy": 1}])
        b = api.build(req)
        self.assertTrue(b["faces"]["top"]["items"][0]["bad"])
        req["layout"] = b["placements"]
        res = api.export(req)
        self.assertFalse(res["ok"])
        self.assertIn("top", res["error"])

    def test_every_face_reads_right_from_outside(self):
        """Every type: a face's part is placed turned, never mirrored (a cut part can't mirror), so what the editor
        draws engraves the right way round; and every face is in view, not an inner part behind a wall."""
        import numpy as np
        for name in catalog.GENERATORS:
            with self.subTest(name=name):
                b = api.build({"generator": name, "params": ui_params(name), "material": MAT, "options": {}})
                for role, f in b["faces"].items():
                    m = np.asarray(b["assembly"]["parts"][f["part"]]["m"]).reshape(3, 4)
                    self.assertGreater(np.linalg.det(m[:, :3]), 0, role)
                    self.assertTrue(f["free"], role)
        b = api.build({"generator": "Console2", "params": ui_params("Console2"), "material": MAT, "options": {}})
        self.assertNotIn("Guide", [b["parts"][f["part"]]["name"] for f in b["faces"].values()])

    def test_the_lid_rims_cover_the_walls_top(self):
        b = api.build(self.req())
        front = b["faces"]["front"]
        ys = [y for ring in front["covered"] for _x, y in ring]
        rim = next(p for p in b["parts"] if p["name"] == "lid front")["h"]
        self.assertAlmostEqual(min(ys), front["h"] - (rim - 3.6), delta=1.5)    # the rim's height down from the top
        self.assertAlmostEqual(max(ys), front["h"], delta=0.01)
        req = self.req()
        req["faces"] = {"front": [{"id": "t", "kind": "text", "text": "HIDDEN", "size": 6, "anchor": "t", "dy": -8}]}
        self.assertTrue(api.build(req)["faces"]["front"]["items"][0]["bad"])
        req["faces"]["front"][0]["dy"] = -30
        self.assertFalse(api.build(req)["faces"]["front"]["items"][0]["bad"])

    def test_the_mark_goes_under_the_box_and_out_of_the_way(self):
        b = api.build({"generator": "HingeBox", "params": ui_params("HingeBox"), "material": MAT, "options": {}})
        self.assertTrue(b["faces"]["bottom"]["fixed"])                 # was on the hinged lid before 2026-11-07
        self.assertFalse(b["faces"]["top"]["fixed"])
        req = self.req()
        mid = {"id": "t", "kind": "text", "text": "MADE IN AUSTRIA", "size": 10, "anchor": "c"}
        req["faces"] = {"bottom": [mid]}
        f = api.build(req)["faces"]["bottom"]
        x0, y0, x1, y1 = f["items"][0]["bounds"]
        mark = [p for line in f["fixed"] for p in line]
        self.assertTrue(mark)
        self.assertFalse(any(x0 - 1 < x < x1 + 1 and y0 - 1 < y < y1 + 1 for x, y in mark))

    SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="20mm" viewBox="0 0 40 20">'
           '<g transform="translate(2 2)"><rect width="16" height="16"/><circle cx="28" cy="8" r="7"/>'
           '<polygon points="10,4 14,12 6,12"/><line x1="0" y1="18" x2="36" y2="18"/></g><text>not drawn</text></svg>')

    def test_an_imported_svg(self):
        from superboxes import svgart
        lines, rings = svgart.parse(self.SVG)
        self.assertEqual(len(rings), 3)                           # rect, circle, triangle; the line isn't closed
        self.assertEqual(len(lines.geoms), 4)
        self.assertAlmostEqual(svgart.height_mm(self.SVG), 20.0)
        x0, y0, x1, y1 = lines.bounds
        self.assertAlmostEqual(x1 - x0, 36, places=3)
        self.assertAlmostEqual(y1 - y0, 18, places=3)
        self.assertLess(y0, 0)                                    # Y up: the SVG's top is the highest
        item = {"id": "a", "kind": "svg", "svg": self.SVG, "size": 18, "anchor": "c"}
        outline = api.build(self.req(items=[item]))["faces"]["top"]["items"][0]
        bx0, by0, bx1, by1 = outline["bounds"]
        self.assertAlmostEqual(by1 - by0, 18, places=3)
        self.assertAlmostEqual(bx1 - bx0, 36, places=3)           # its own proportions
        hatched = api.build(self.req(items=[dict(item, style="hatch")]))["faces"]["top"]["items"][0]
        self.assertGreater(len(hatched["lines"]), 10 * len(outline["lines"]))
        req = self.req(items=[{"id": "b", "kind": "svg", "svg": "<html/>", "size": 20, "anchor": "c"}])
        got = api.build(req)["faces"]["top"]["items"][0]
        self.assertEqual((got["bad"], got["error"]), (True, "not an SVG file"))
        req["layout"] = api.build(req)["placements"]
        self.assertIn("can't be read", api.export(req)["error"])

    def hole_req(self, items, mat=MAT):
        req = self.req()
        req["material"] = mat
        req["faces"] = {"front": items}
        return req

    def test_holes_cut_through_at_their_finished_size(self):
        import math
        pot = {"id": "pot", "kind": "hole", "shape": "round", "d": 7.2, "anchor": "c", "dx": -30, "dy": -10}
        oled = {"id": "oled", "kind": "hole", "shape": "rect", "w": 24.85, "h": 9.49, "r": 0.71, "anchor": "c",
                "dx": 30, "dy": -10}
        plain = api.build(self.hole_req([]))
        b = api.build(self.hole_req([pot, oled]))
        f = b["faces"]["front"]
        self.assertFalse(any(i["bad"] for i in f["items"]))
        part, before = b["parts"][f["part"]], plain["parts"][f["part"]]
        holes = math.pi * 3.6 ** 2 + 24.85 * 9.49 - (4 - math.pi) * 0.71 ** 2
        self.assertAlmostEqual(before["area"] - part["area"], holes, delta=0.2)    # the 3D's wood has them
        # boxes.py burns its own paths: a hole's cut path runs the burn inside it, a true circle (four arcs)
        circle = part["paths"]["2"][-2]
        self.assertEqual(len(circle["segs"]), 4)
        xs = [circle["start"][0]] + [s[-2] for s in circle["segs"]]
        self.assertAlmostEqual((max(xs) - min(xs)) / 2, 3.6 - MAT["burn"], places=3)
        # the parts are cached between builds: a build without holes has none
        self.assertEqual(api.build(self.hole_req([]))["parts"][f["part"]]["area"], before["area"])
        # per axis, the export grows the wood by the burn: the hole's cut path is that much inside, per axis
        req = self.hole_req([pot], {"key": "poplar3.6", "thickness": 3.6, "burn": 0.1675, "burn_x": 0.185,
                                    "burn_y": 0.15})
        b = api.build(req)
        req["layout"] = b["placements"]
        self.assertTrue(api.export(req)["ok"])
        parts, info = api._render(req)
        parts = api._decorations(req, parts, assembly.assemble("ABox", parts, 3.6, req["layout"]), info)[0]
        pi = b["faces"]["front"]["part"]
        pl = next(q for q in req["layout"] if q["part"] == pi)
        region = X.placed_shape(parts[pi], pl, info["comp"])
        hole = min(region.interiors, key=lambda r: abs(r.envelope.area - 7.2 ** 2)).envelope.bounds
        w, h = hole[2] - hole[0], hole[3] - hole[1]               # machine axes, however the part lies
        self.assertAlmostEqual(w, 7.2 - 2 * 0.185, delta=0.02)
        self.assertAlmostEqual(h, 7.2 - 2 * 0.15, delta=0.02)

    def test_holes_keep_wood_between_them_and_engraving_off_them(self):
        pot = {"id": "a", "kind": "hole", "shape": "round", "d": 7.2, "anchor": "c", "dx": -30, "dy": -10}
        near = dict(pot, id="b", dx=-21)                        # 9 mm apart: 1.8 mm of wood
        text = {"id": "t", "kind": "text", "text": "VOL", "size": 4, "anchor": "c", "dx": -30, "dy": -10}
        got = {i["id"]: i["bad"] for i in api.build(self.hole_req([pot, near, text]))["faces"]["front"]["items"]}
        self.assertEqual(got, {"a": True, "b": True, "t": True})
        got = {i["id"]: i["bad"] for i in api.build(self.hole_req([pot, dict(near, dx=-19), dict(text, dy=2)]))
               ["faces"]["front"]["items"]}
        self.assertEqual(got, {"a": False, "b": False, "t": False})

    def test_edge_connectors_sit_at_the_board(self):
        usb = {"id": "usb", "kind": "hole", "shape": "rect", "w": 10.2, "h": 4.26, "r": 2.13, "board": True,
               "lift": -0.5, "anchor": "c", "dx": 20, "dy": 30}
        req = self.req()
        req["faces"] = {"back": [usb], "top": [dict(usb, id="top")]}
        got = api.build(req)["faces"]
        self.assertEqual(got["back"]["items"][0]["error"], "set the board's height on this wall")
        self.assertEqual(got["top"]["items"][0]["error"], "only on a wall of a box with a floor")
        req["boards"] = {"back": 8.0}
        back = api.build(req)["faces"]["back"]
        x0, y0, x1, y1 = back["items"][0]["bounds"]
        self.assertAlmostEqual(back["board"] - back["floor"], 8.0, places=3)
        self.assertAlmostEqual(y0, back["board"] - 0.5, places=3)               # dy is ignored: it sits at the board
        self.assertAlmostEqual(y1, back["board"] + 3.76, places=3)
        self.assertAlmostEqual((x0 + x1) / 2, back["w"] / 2 + 20, places=3)     # dx is its own
        self.assertFalse(back["items"][0]["bad"])
        del req["faces"]["top"]                             # (red: it would block the export)
        req["layout"] = api.build(req)["placements"]
        self.assertTrue(api.export(req)["ok"])

    def test_a_thumb_notch_cuts_into_a_plain_edge(self):
        import math
        from shapely.geometry import Polygon
        from evlaser import svgpath
        notch = {"id": "n", "kind": "hole", "shape": "notch", "d": 40, "anchor": "t", "dx": 0, "dy": 0}
        req = self.req()
        req["faces"] = {"front": [notch], "left": [dict(notch, id="m", anchor="b")],
                        "right": [dict(notch, id="c", anchor="c")]}
        b = api.build(req)
        got = {r: b["faces"][r]["items"][0] for r in ("front", "left", "right")}
        self.assertFalse(got["front"]["bad"])
        self.assertTrue(got["left"]["bad"])                          # the floor's finger joint along that edge
        self.assertEqual(got["right"]["error"], "drag it onto the top or bottom edge")
        fp = b["faces"]["front"]["part"]
        plain = api.build(self.req())["parts"][fp]
        self.assertAlmostEqual(plain["area"] - b["parts"][fp]["area"], math.pi * 20 ** 2 / 2, delta=1.0)
        # boxes.py burns its own paths: the notch's cut path runs the burn inside the finished notch (radius r - burn),
        # and the outline's own cut path the burn outside the edge, so a strip that wide goes too
        parts, info = api._render(req)
        parts = api._decorations(req, parts, assembly.assemble("ABox", parts, 3.6), info)[0]
        before, _ = api._render(self.req())
        outer = lambda q: max((Polygon(svgpath.flatten(sp, 6)).buffer(0) for sp in q.subpaths[M.CUT] if sp[2]),
                              key=lambda g: g.area)
        lost = outer(before[fp]).area - outer(parts[fp]).area
        r = 20 - MAT["burn"]
        self.assertAlmostEqual(lost, math.pi * r ** 2 / 2 + 2 * r * MAT["burn"], delta=0.5)
        req["faces"] = {"front": [notch]}
        req["layout"] = b["placements"]
        self.assertTrue(api.export(req)["ok"])

    def test_the_lid_is_engraved_as_seen_from_outside(self):
        req = self.req(items=[{"id": "t", "kind": "text", "text": "CANVAS", "size": 12, "anchor": "c"}])
        b = api.build(req)
        top = b["faces"]["top"]
        part = b["parts"][top["part"]]
        engraved = [d for d in part["deco"] if d["layer"] == M.LINE]
        self.assertTrue(engraved)
        # the lid lies on the box unturned (x -> X, y -> Y), so its own drawing is the view from above, unmirrored
        xs = [p[0] for d in engraved for line in d["lines"] for p in line]
        self.assertAlmostEqual((min(xs) + max(xs)) / 2, part["w"] / 2, delta=0.05)
        req["layout"] = b["placements"]
        res = api.export(req)
        self.assertTrue(res["ok"], res.get("error"))


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
        self.assertEqual(set(re.findall(r'CutIndex="(\d+)"', lb)), {"1", "2", "7", "30"})

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
                body = [pl for pl in asm["parts"] if pl["kind"] == "wall" and pl["group"] == "body"]
                self.assertEqual(len(body), 5)
                # the over-the-top lid goes on the box (the face editor's example); the others lie beside it
                lid = [pl for pl in asm["parts"] if pl["kind"] == "wall" and pl["group"] == "lid"]
                self.assertEqual(len(lid), 5 if style == "overthetop" else 0)
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
