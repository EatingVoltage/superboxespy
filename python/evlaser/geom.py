"""Parts, icons, corner profiles, test combs, sheet checks and a rough job-time estimate.

A Part is a bag of items per layer:
    (layer, 'poly', Polygon|MultiPolygon)      filled region (FILL/HATCH) or closed outline (LINE/CUT)
    (layer, 'lines', LineString|MultiLineString) open polylines (LINE)
    (layer, 'circle', (cx, cy), r)             written as a true LightBurn ellipse
    (layer, 'bez', [subpath, ...])             Bezier curves (svgpath subpaths, in mm) - icons
Build each part around (0, 0), then place it with part.transformed(angle, x, y).
"""
import math
import os

from shapely import affinity
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from . import machine as M
from . import svgpath


class Part:
    def __init__(self, name):
        self.name = name
        self.items = []

    def add(self, layer, kind, *data):
        self.items.append((layer, kind) + data)
        return self

    def transformed(self, angle_deg=0.0, dx=0.0, dy=0.0):
        p = Part(self.name)
        a = math.radians(angle_deg)
        ca, sa = math.cos(a), math.sin(a)

        def tp(pt):
            x, y = pt
            return (ca * x - sa * y + dx, sa * x + ca * y + dy)

        for it in self.items:
            layer, kind = it[0], it[1]
            if kind in ("poly", "lines"):
                g = affinity.rotate(it[2], angle_deg, origin=(0, 0)) if angle_deg else it[2]
                p.items.append((layer, kind, affinity.translate(g, dx, dy)))
            elif kind == "circle":
                p.items.append((layer, kind, tp(it[2]), it[3]))
            elif kind == "bez":
                subs = []
                for start, segs, closed in it[2]:
                    subs.append((tp(start),
                                 [(tp(c1) if c1 else None, tp(c2) if c2 else None, tp(e)) for c1, c2, e in segs],
                                 closed))
                p.items.append((layer, kind, subs))
        return p

    def bounds(self):
        xs, ys = [], []
        for it in self.items:
            kind = it[1]
            if kind in ("poly", "lines"):
                b = it[2].bounds
                xs += [b[0], b[2]]
                ys += [b[1], b[3]]
            elif kind == "circle":
                (cx, cy), r = it[2], it[3]
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
            elif kind == "bez":
                for sp in it[2]:
                    for x, y in svgpath.flatten(sp, 4):
                        xs.append(x)
                        ys.append(y)
        return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------------------ icons
_icon_cache = {}


def icon(svg_path, size, angle_deg=0.0, view=512.0):
    """game-icons.net style SVG (viewBox 0 0 512 512, y down) -> subpaths scaled to `size` mm, centred on (0,0),
    Y up, rotated. Put them on FILL as ('bez', ...) - they stay true curves in LightBurn."""
    if svg_path not in _icon_cache:
        _icon_cache[svg_path] = svgpath.load_icon(svg_path)
    s = size / view
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)

    def tp(pt):
        x, y = (pt[0] - view / 2) * s, (view / 2 - pt[1]) * s
        return (ca * x - sa * y, sa * x + ca * y)

    return [(tp(start), [(tp(c1) if c1 else None, tp(c2) if c2 else None, tp(e)) for c1, c2, e in segs], closed)
            for start, segs, closed in _icon_cache[svg_path]]


def icon_region(svg_path, size, steps=8):
    """Icon as a shapely region (even-odd of its subpaths), centred on (0,0) - for stencils, cut-outs, clipping."""
    geo = Polygon()
    for sp in icon(svg_path, size):
        ring = svgpath.flatten(sp, steps)
        if len(ring) > 2:
            geo = geo.symmetric_difference(Polygon(ring).buffer(0))
    return geo


# ---------------------------------------------------------- corner profiles
# Superellipse quarter instead of a circle: exponent 2 = circle; 4 = curvature zero where it leaves the edge
# (a flat ramp) and highest at the apex. Sliding parts with it find their way past small offsets instead of
# snagging. Measured winner for sliding 37 mm tiles: setback 7 mm, exponent 4 (labyrinth corner test).
SLIDE_CORNER = (7.0, 4)


def _corner_curve(v, a, b, d_in, d_out, n, steps=40):
    """Superellipse quarter replacing the convex vertex v. a = incoming edge direction, b = outgoing."""
    e1 = (-a[0], -a[1])
    cx = v[0] + d_in * e1[0] + d_out * b[0]
    cy = v[1] + d_in * e1[1] + d_out * b[1]
    pts = []
    for k in range(steps + 1):
        th = (math.pi / 2) * k / steps
        c = max(math.cos(th), 0.0) ** (2 / n)
        s = max(math.sin(th), 0.0) ** (2 / n)
        pts.append((cx - d_out * c * b[0] - d_in * s * e1[0], cy - d_out * c * b[1] - d_in * s * e1[1]))
    return pts


def profile_corners(poly, spec_of):
    """Replace convex right-angle corners of a hole-free polygon by superellipse corners.
    spec_of(vertex) -> (setback, exponent) or None. Setbacks are clamped on short edges."""
    pts = list(orient(poly, 1.0).exterior.coords)[:-1]
    m = len(pts)

    def unit(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length), length

    specs = []
    for i in range(m):
        a, _ = unit(pts[i - 1], pts[i])
        b, _ = unit(pts[i], pts[(i + 1) % m])
        convex_right = a[0] * b[1] - a[1] * b[0] > 0.99
        specs.append(spec_of(pts[i]) if convex_right else None)
    out = []
    for i in range(m):
        if specs[i] is None:
            out.append(pts[i])
            continue
        a, la = unit(pts[i - 1], pts[i])
        b, lb = unit(pts[i], pts[(i + 1) % m])
        d, n = specs[i]
        d_in = min(d, la * (0.5 if specs[i - 1] else 1.0) - 0.05)
        d_out = min(d, lb * (0.5 if specs[(i + 1) % m] else 1.0) - 0.05)
        out.extend(_corner_curve(pts[i], a, b, d_in, d_out, n))
    return Polygon(out)


def profiled_square(size, spec, cx=0.0, cy=0.0):
    h = size / 2
    return profile_corners(box(cx - h, cy - h, cx + h, cy + h), lambda v: spec)


def rounded_rect(w, h, r, x0=0.0, y0=0.0):
    """Plain constant-radius rectangle (panels, plates)."""
    return box(x0, y0, x0 + w, y0 + h).buffer(-r).buffer(r, quad_segs=16)


# ----------------------------------------------------------- label digits
_SEG = {  # 7-segment strokes on a 2 x 4 box (x 0..2, y 0..4)
    "a": [(0, 4), (2, 4)], "b": [(2, 4), (2, 2)], "c": [(2, 2), (2, 0)], "d": [(0, 0), (2, 0)],
    "e": [(0, 0), (0, 2)], "f": [(0, 2), (0, 4)], "g": [(0, 2), (2, 2)],
}
_DIGITS = {"C": "adef", "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
           "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g"}


def stroke_text(s, cx, y, height):
    """Single-stroke 7-segment digits (0-9, '.', '-', 'C') for LINE-engraved labels on test pieces.
    Centred on cx, baseline y. Fast to engrave, no font needed."""
    k = height / 4
    adv = {".": 1.2}
    width = sum(adv.get(ch, 3.0) for ch in s) - 1.0
    x = cx - width * k / 2
    lines = []
    for ch in s:
        if ch == ".":
            lines.append(LineString([(x + 0.1 * k, y), (x + 0.5 * k, y)]))
        else:
            for sg in _DIGITS[ch]:
                (ax, ay), (bx, by) = _SEG[sg]
                lines.append(LineString([(x + ax * k, y + ay * k), (x + bx * k, y + by * k)]))
        x += adv.get(ch, 3.0) * k
    return MultiLineString(lines)


def num(v):
    """0.3 -> '0.3', 0.25 -> '0.25', 3.0 -> '3.0'."""
    s = ("%.2f" % v).rstrip("0")
    return s + "0" if s.endswith(".") else s


# ------------------------------------------------------------- test combs
# Rules (from the labyrinth, where two combs sat around the wrong value): measure the real part with calipers
# first and centre the comb on that, never on the nominal size; for a first fit in a new material go tighter
# than feels right; cut the comb with exactly the production CUT settings, kerf offset included.
def notch_comb(part_w, plays, corner=None, depth=16.0, margin=4.0, plate_h=30.0, label_h=4.0):
    """Plate with one open notch per play value: notch width = part_w + play (total play in mm, engraved below).
    Slide the real part (cut on the same sheet) through each; pick the one that slides freely without wobble.
    corner = (setback, exponent) profiles the notch mouths like the real channel. Origin = lower-left."""
    cell = part_w + max(plays) + 8.0
    plate_w = 2 * margin + len(plays) * cell
    plate = box(0, 0, plate_w, plate_h)
    labels = []
    for k, c in enumerate(plays):
        w = part_w + c
        cx = margin + cell / 2 + k * cell
        plate = plate.difference(box(cx - w / 2, plate_h - depth, cx + w / 2, plate_h + 1))
        labels.append(stroke_text(num(c), cx, 4.0, label_h))
    if corner:
        plate = profile_corners(plate, lambda v: corner)
    p = Part("notch comb %s" % "/".join(num(c) for c in plays))
    p.add(M.CUT, "poly", plate)
    p.add(M.LINE, "lines", unary_union(labels))
    return p


def hole_comb(diameters, pitch=None, margin=4.0, label_h=3.0):
    """Strip with one hole per diameter, labelled. For pins, skewers, shafts, bolts, magnets, LEDs. Origin = lower-left."""
    dmax = max(diameters)
    pitch = pitch or max(dmax + 5.0, 11.0)
    w = 2 * margin + len(diameters) * pitch
    h = margin + label_h + 3.0 + dmax + margin
    p = Part("hole comb %s" % "/".join(num(d) for d in diameters))
    labels = []
    for k, d in enumerate(diameters):
        x = margin + pitch / 2 + k * pitch
        p.add(M.CUT, "circle", (x, h - margin - dmax / 2), d / 2)
        labels.append(stroke_text(num(d), x, margin, label_h))
    p.add(M.CUT, "poly", rounded_rect(w, h, 2.0))
    p.add(M.LINE, "lines", unary_union(labels))
    return p


def slot_comb(thickness, deltas=(-0.1, -0.05, 0.0, 0.05, 0.1), depth=10.0, margin=4.0, label_h=3.0):
    """Plate with open slots of width thickness + delta (the slot width is engraved). Push an offcut of the same
    sheet into each; pick the one that holds without force. One comb per material - the thickness holds well."""
    pitch = 10.0
    widths = [thickness + d for d in deltas]
    w = 2 * margin + len(widths) * pitch
    h = margin + label_h + 3.0 + depth
    plate = box(0, 0, w, h)
    labels = []
    for k, sw in enumerate(widths):
        x = margin + pitch / 2 + k * pitch
        plate = plate.difference(box(x - sw / 2, h - depth, x + sw / 2, h + 1))
        labels.append(stroke_text(num(sw), x, margin, label_h))
    p = Part("slot comb %s" % "/".join(num(s) for s in widths))
    p.add(M.CUT, "poly", plate)
    p.add(M.LINE, "lines", unary_union(labels))
    return p


# ------------------------------------------------------------------ layout
def grid_positions(n_cols, n_rows, cell, x0, y0, gap=M.GAP):
    """Centres of an n_cols x n_rows grid of square cells, lower-left cell first."""
    for j in range(n_rows):
        for i in range(n_cols):
            yield (x0 + cell / 2 + i * (cell + gap), y0 + cell / 2 + j * (cell + gap))


def check_sheet(parts, sheet, name="sheet", edge=M.EDGE, gap=M.GAP, ref_layer=M.REF):
    """Asserts: every part inside the sheet with `edge` margin and below the reach limit; outer cut outlines at
    least `gap` apart (parts nested inside another part's hole are fine). Reference-only parts are skipped."""
    sw, sh, usable = sheet
    parts = [p for p in parts if not all(it[0] == ref_layer for it in p.items)]
    for p in parts:
        x0, y0, x1, y1 = p.bounds()
        assert x0 >= edge - 1e-6 and y0 >= edge - 1e-6, (name, p.name, p.bounds())
        assert x1 <= sw - edge + 1e-6 and y1 <= min(usable, sh - edge) + 1e-6, (name, p.name, p.bounds())
    cuts = []
    for p in parts:
        for it in p.items:
            if it[0] == M.CUT and it[1] in ("poly", "circle"):
                g = it[2] if it[1] == "poly" else Point(it[2]).buffer(it[3])
                cuts.append((p.name, g))
    outers = [(n, g) for n, g in cuts if not any(g.within(o.buffer(0.01)) for _, o in cuts if o is not g)]
    for i in range(len(outers)):
        for j in range(i + 1, len(outers)):
            d = outers[i][1].distance(outers[j][1])
            assert d >= gap - 0.2, (name, outers[i][0], outers[j][0], d)


# --------------------------------------------------------------- job time
def _scan_seconds(regions, interval, speed, overscan, dy=0.5):
    """LightBurn fills a layer row by row; each row runs from the first to the last shape it meets (gaps are
    crossed with the laser off, empty rows skipped). Sampled every dy mm, scaled to the real interval."""
    g = unary_union(regions)
    if g.is_empty:
        return 0.0
    x0, y0, x1, y1 = g.bounds
    span, y = 0.0, y0 + dy / 2
    while y < y1:
        hit = g.intersection(LineString([(x0 - 1, y), (x1 + 1, y)]))
        if not hit.is_empty:
            b = hit.bounds
            span += b[2] - b[0]
        y += dy
    return span * (dy / interval) / speed * overscan


def job_time(parts, layers, overscan=1.4):
    """Rough minutes per layer: path length / speed for the Line pass, plus the Scan (fill) sub-layer if the
    layer has one (row spans x rows / speed, times `overscan` for acceleration and turnarounds). Travel ignored.
    A first guess for the hand-over message - LightBurn's Preview gives the real number."""
    from . import lbrn
    out = {}
    for index, name, s in layers:
        speed = dict(s["values"]).get("speed")
        line_mm, regions = 0.0, []
        sub = [dict(v) for mode, v in s.get("sub", []) if mode == "Scan"]
        for p in parts:
            for it in p.items:
                if it[0] != index:
                    continue
                kind = it[1]
                if kind == "lines":
                    line_mm += sum(ls.length for ls in lbrn._lines(it[2]))
                elif kind == "poly":
                    line_mm += sum(r.length for q in lbrn._polys(it[2]) for r in [q.exterior] + list(q.interiors))
                    regions.append(it[2])
                elif kind == "circle":
                    line_mm += 2 * math.pi * it[3]
                elif kind == "bez":
                    rings = [svgpath.flatten(sp, 8) for sp in it[2]]
                    line_mm += sum(LineString(r).length for r in rings if len(r) > 1)
                    regions += [Polygon(r).buffer(0) for r in rings if len(r) > 2]
        scan_s = sum(_scan_seconds(regions, v["interval"], v["speed"], overscan) for v in sub) if regions else 0.0
        if line_mm or scan_s:
            out[name] = round((line_mm / speed if speed else 0) / 60 + scan_s / 60, 1)
    return out
