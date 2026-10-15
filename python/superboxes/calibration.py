"""Calibration sheets: 00a kerf strips, 00b finger-joint fit comb.

00a - kerf: one strip of 10 bars cut along X, one along Y, raw geometry (no burn). Pushed together, the 10 bars of
      a strip measure 100 - 10 x kerf, so kerf = (100 - L) / 10. A diode's spot isn't round, so X and Y are
      measured separately.
00b - fit comb: boxes.py's own finger joints at several burn values around the measured kerf / 2, cut with the
      production settings (eVlaser fit rule 3). Per burn value three plates: A has fingers, B the corner
      counterpart, C finger holes (the bottom-into-wall slot). Pick a press-fit and a glue-fit winner.
"""
from shapely.geometry import LineString, MultiLineString, Polygon, box as rect

from boxes import Boxes, edges
from boxes.drawing import Context

from evlaser import machine as M

from . import capture, export as X, sheets as S, strokefont

BAR, BARS, STRIP_W = 10.0, 10, 16.0


def _part(index, name, w, h):
    p = capture.Part(index)
    p.name, p.w, p.h = name, w, h
    return p


def _rect_sub(x0, y0, x1, y1):
    return ((x0, y0), [(None, None, (x1, y0)), (None, None, (x1, y1)), (None, None, (x0, y1)),
                       (None, None, (x0, y0))], True)


def _line_sub(a, b):
    return (a, [(None, None, b)], False)


def kerf_parts():
    """Two strips of 10 bars: bars 10 mm along X (strip X) and along Y (strip Y). Engraved 'X' / 'Y' on bar 1."""
    L = BAR * BARS
    px = _part(0, "kerf strip X", L, STRIP_W)
    px.subpaths[M.CUT] = [_rect_sub(0, 0, L, STRIP_W)] + [_line_sub((BAR * k, 0), (BAR * k, STRIP_W))
                                                          for k in range(1, BARS)]
    py = _part(1, "kerf strip Y", STRIP_W, L)
    py.subpaths[M.CUT] = [_rect_sub(0, 0, STRIP_W, L)] + [_line_sub((0, BAR * k), (STRIP_W, BAR * k))
                                                          for k in range(1, BARS)]
    for p in (px, py):
        p.shape = rect(0, 0, p.w, p.h)
    deco = {0: [(M.LINE, strokefont.text("X", BAR / 2, STRIP_W / 2 - 2, 4, "center"))],
            1: [(M.LINE, strokefont.text("Y", STRIP_W / 2, BAR / 2 - 2, 4, "center"))]}
    return [px, py], deco


def kerf_from(length):
    """Kerf from the measured length of 10 bars pushed together."""
    return (BAR * BARS - float(length)) / BARS


class FitTest(Boxes):
    """Three 40 x 20 plates: A fingers (f), B corner counterpart (F), C finger holes (h)."""

    def __init__(self):
        Boxes.__init__(self)
        self.addSettingsArgs(edges.FingerJointSettings)

    def render(self):
        self.rectangularWall(40, 20, "eefe", move="right", label="A")
        self.rectangularWall(40, 20, "eeFe", move="right", label="B")
        self.rectangularWall(40, 20, "eehe", move="right", label="C")


def comb_values(center, step=0.02, below=2, above=3, positive=True):
    """Values around `center`, one step more on the tight side: 'for a first fit go tighter than feels right'.
    Isotropic mode: absolute burn values around kerf/2. Per-axis mode: fit offsets delta around 0."""
    vals = [round(center + k * step, 3) for k in range(-below, above + 1)]
    return [v for v in vals if v > 0] if positive else vals


def comb_spec(req):
    """How the comb is made. With different X and Y kerf: per-axis compensation (bx = kx/2 + delta,
    by = ky/2 + delta) and the comb varies delta. Otherwise one burn value per row, around kerf/2."""
    k = req.get("kerf") or {}
    kx, ky = k.get("x"), k.get("y")
    if kx is not None and ky is not None and abs(float(kx) - float(ky)) >= 1e-3:
        kx, ky = float(kx), float(ky)
        deltas = [d for d in comb_values(0.0, positive=False) if kx / 2 + d > 0 and ky / 2 + d > 0]
        return {"mode": "axis", "kx": kx, "ky": ky, "values": deltas}
    mat = req.get("material") or {}
    center = float(req.get("center") or mat.get("burn") or 0.1)
    return {"mode": "iso", "values": comb_values(center)}


def _fit_plates(thickness, burn, margin=0.0):
    """The three plates (A, B, C) as captured parts, drawn by boxes.py with one burn value."""
    box = FitTest()
    box.parseArgs(["--thickness=%r" % float(thickness), "--burn=%r" % float(burn), "--reference=0",
                   "--labels=0", "--format=svg"])
    surface = capture._Capture()
    ctx = Context(surface)
    box.formats.getSurface = lambda fmt: (surface, ctx)
    box.open()
    box.render()
    box.ctx.stroke()
    box.ctx = None
    plates = []
    for sp in surface.parts:
        if not sp.pathes:
            continue
        raw = capture.Part(0)
        for path in sp.pathes:
            path.faster_edges(box.inner_corners)
            for sub in capture._subpaths(path):
                raw.subpaths[capture._layer(path.params["rgb"])].append(sub)
        if raw.subpaths[M.CUT]:
            plates += capture._pieces(raw, burn, margin=margin)
    return plates


def comb_parts(thickness, spec):
    """Per value a row A B C. Per-axis mode adds a check row turned 90 degrees at delta 0: with the right
    compensation it fits exactly like the unturned delta 0 row."""
    parts, deco = [], {}
    rows = [(v, 0) for v in spec["values"]]
    if spec["mode"] == "axis":
        rows.append((0.0, 90))
    for v, rot in rows:
        if spec["mode"] == "axis":
            comp = (round(spec["kx"] / 2 + v, 4), round(spec["ky"] / 2 + v, 4))
            plates = _fit_plates(thickness, 0.0, margin=max(comp))
            tag = "%+.2f" % v
        else:
            comp = None
            plates = _fit_plates(thickness, v)
            tag = "%.2f" % v
        for letter, p in zip("ABC", plates):
            p.index = len(parts)
            p.comp = comp
            p.rot = rot
            name = letter + ("90" if rot else "")
            p.name = "fit %s %s" % (name, tag)
            c = p.shape.centroid
            deco[p.index] = [(M.LINE, strokefont.text("%s %s" % (name, tag), c.x, c.y - 1.5, 3, "center"))]
            parts.append(p)
    return parts, deco


def comb_layout(parts, sheet, per_row=3):
    """One row per value (A B C), loosest at the bottom; rows fill two columns, so the offcut stays a clean
    strip across the top. Parts with p.rot = 90 (the check row) are placed turned."""
    x0, y0, x1, _y1 = S.area(sheet)

    def size(p):
        return S.rotated_size(p.w, p.h, getattr(p, "rot", 0))

    rows = [parts[i:i + per_row] for i in range(0, len(parts), per_row)]
    row_w = max(sum(size(p)[0] for p in r) + M.GAP * (len(r) - 1) for r in rows)
    cols = 2 if 2 * row_w + 2 * M.GAP <= x1 - x0 else 1
    per_col = -(-len(rows) // cols)
    placements = []
    for c in range(cols):
        cy = y0
        for r in rows[c * per_col:(c + 1) * per_col]:
            cx = x0 + c * (row_w + 2 * M.GAP)
            for p in r:
                w, _h = size(p)
                placements.append({"part": p.index, "sheet": 0, "x": cx, "y": cy, "rot": getattr(p, "rot", 0)})
                cx += w + M.GAP
            cy += max(size(p)[1] for p in r) + M.GAP
    return placements


def _layout(parts, sheet, comb):
    if comb:
        return comb_layout(parts, sheet), []
    # never rotated: the X strip must stay along X and the Y strip along Y
    return S.pack([(p.w, p.h) for p in parts], sheet, allow_rotate=False)


def _preview(parts, deco, sheet, notes, comb=False):
    placements, too_big = _layout(parts, sheet, comb)
    out = []
    for p in parts:
        j = p.to_json()
        j["deco"] = [{"layer": layer, "lines": [[[round(x, 3), round(y, 3)] for x, y in ls.coords] for ls in m.geoms]}
                     for layer, m in deco.get(p.index, [])]
        out.append(j)
    n = max((pl["sheet"] for pl in placements), default=-1) + 1
    sizes = [(p.w, p.h) for p in parts]
    return {"ok": True, "parts": out, "placements": placements, "too_big": too_big, "notes": notes,
            "sheets": [{"index": k, "offcut": round(S.offcut(placements, sizes, sheet, k), 1)} for k in range(n)],
            "warnings": []}


KERF_NOTES = ("00a kerf test - cut this before anything else.\n"
              "1. Cut it with your normal CUT layer (it's raw geometry, no burn correction).\n"
              "2. Strip X: push its 10 bars together end to end, the way they were cut, and measure the total "
              "length along X with calipers. Same for strip Y along Y.\n"
              "3. Measure the sheet thickness with calipers in three spots.\n"
              "4. Enter the three numbers in superboxes > Calibration. kerf = (100 - length) / 10.")

COMB_NOTES = ("00b fit comb - cut after the kerf test, with the production CUT settings.\n"
              "Each burn value has three plates: A (fingers), B (corner counterpart), C (finger holes).\n"
              "Try A into B (corner joint) and A into C (bottom-into-wall slot) for every value.\n"
              "Press fit = goes together by hand pressure, holds without glue, nothing cracks.\n"
              "Glue fit = slides together with light pressure, a little play, needs glue.\n"
              "Enter both winners in superboxes > Calibration.")


COMB_NOTES_AXIS = ("00b fit comb, per axis - cut after the kerf test, with the production CUT settings.\n"
                   "Your spot isn't round, so every cut is compensated per axis: burn X = kerf X / 2 + fit, "
                   "burn Y = kerf Y / 2 + fit. The value on each plate is the fit offset.\n"
                   "Each row has three plates: A (fingers), B (corner counterpart), C (finger holes).\n"
                   "Try A into B (corner joint) and A into C (bottom-into-wall slot) for every value.\n"
                   "The row marked A90 B90 C90 is turned 90 degrees at fit +0.00: it should feel exactly like the "
                   "+0.00 row. If it doesn't, tell Claude.\n"
                   "Press fit = goes together by hand pressure, holds without glue, nothing cracks.\n"
                   "Glue fit = slides together with light pressure, a little play, needs glue.\n"
                   "Enter both winners in superboxes > Calibration.")


def _sheet(req):
    return req.get("sheet") or S.A3


def kerf_sheet(req):
    parts, deco = kerf_parts()
    return _preview(parts, deco, _sheet(req), KERF_NOTES)


def comb_sheet(req):
    mat = req.get("material") or {}
    spec = comb_spec(req)
    parts, deco = comb_parts(float(mat.get("thickness", 3.7)), spec)
    res = _preview(parts, deco, _sheet(req), COMB_NOTES, comb=True)
    res.update(values=spec["values"], mode=spec["mode"])
    return res


def calibration_export(req):
    which = req.get("which", "kerf")
    sheet = _sheet(req)
    mat = req.get("material") or {}
    if which == "kerf":
        parts, deco = kerf_parts()
        name, title, notes = "kerf-test", "00a kerf test", KERF_NOTES
    else:
        spec = comb_spec(req)
        parts, deco = comb_parts(float(mat.get("thickness", 3.7)), spec)
        if spec["mode"] == "axis":
            title = "00b fit comb, per axis (kerf X %.3f / Y %.3f, fit %+.2f to %+.2f)" % (
                spec["kx"], spec["ky"], spec["values"][0], spec["values"][-1])
            notes = COMB_NOTES_AXIS
        else:
            title = "00b fit comb (burn %.2f to %.2f)" % (spec["values"][0], spec["values"][-1])
            notes = COMB_NOTES
        name = "fit-comb"
    placements, too_big = _layout(parts, sheet, which != "kerf")
    files = X.sheet_files(name, title, parts, placements, deco, mat, sheet, notes_extra=notes)
    out = []
    prefix = "00a" if which == "kerf" else "00b"
    for fname, lb, svg, minutes, off in files:
        base = "%s_%s" % (prefix, name) + ("" if len(files) == 1 else "_" + fname[:2])
        out.append({"name": base + ".lbrn2", "kind": "lbrn2", "content": lb, "minutes": minutes})
        out.append({"name": base + ".svg", "kind": "svg", "content": svg})
    return {"ok": True, "files": out}
