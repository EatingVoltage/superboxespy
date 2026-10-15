"""Packing parts onto sheets: bottom-left first, so what's left is one clean strip across the top of the sheet.

Placement = {"part": index, "sheet": n, "x": .., "y": .., "rot": 0|90}: (x, y) is the lower-left corner of the
part's (rotated) bounding box on the sheet, mm from the sheet's lower-left corner = LightBurn workspace 0,0.
Rotation is 90° counter-clockwise about the part's own lower-left corner, then shifted back into the box.

Rules from the eVlaser setup: 3 mm from the sheet edge, 1.5 mm between parts, nothing above the 390 mm reach
line. A part that fits in neither orientation is an error, never split.
"""
from evlaser import machine as M

A3 = {"name": "A3", "w": 297.0, "h": 420.0, "usable": 390.0}


def sheet_tuple(sheet):
    return (float(sheet["w"]), float(sheet["h"]), float(min(sheet.get("usable", sheet["h"]), sheet["h"])))


def area(sheet, edge=M.EDGE):
    """Usable rectangle (x0, y0, x1, y1) for part bounding boxes."""
    sw, sh, usable = sheet_tuple(sheet)
    return (edge, edge, sw - edge, min(usable, sh - edge))


def rotated_size(w, h, rot):
    return (h, w) if rot % 180 else (w, h)


def fits(w, h, sheet, edge=M.EDGE):
    x0, y0, x1, y1 = area(sheet, edge)
    return (w <= x1 - x0 + 1e-6 and h <= y1 - y0 + 1e-6) or (h <= x1 - x0 + 1e-6 and w <= y1 - y0 + 1e-6)


class _MaxRects:
    """MaxRects bin with the bottom-left rule: lowest top edge first, then leftmost."""

    def __init__(self, x0, y0, x1, y1):
        self.free = [(x0, y0, x1, y1)]

    def find(self, w, h):
        best = None
        for fx0, fy0, fx1, fy1 in self.free:
            if w <= fx1 - fx0 + 1e-9 and h <= fy1 - fy0 + 1e-9:
                key = (fy0 + h, fx0)
                if best is None or key < best[0]:
                    best = (key, fx0, fy0)
        return None if best is None else (best[1], best[2])

    def occupy(self, x0, y0, x1, y1):
        out = []
        for f in self.free:
            fx0, fy0, fx1, fy1 = f
            if x0 >= fx1 or x1 <= fx0 or y0 >= fy1 or y1 <= fy0:
                out.append(f)
                continue
            if x0 > fx0:
                out.append((fx0, fy0, x0, fy1))
            if x1 < fx1:
                out.append((x1, fy0, fx1, fy1))
            if y0 > fy0:
                out.append((fx0, fy0, fx1, y0))
            if y1 < fy1:
                out.append((fx0, y1, fx1, fy1))
        # drop free rectangles contained in another one
        out = [a for i, a in enumerate(out)
               if not any(j != i and b[0] <= a[0] and b[1] <= a[1] and b[2] >= a[2] and b[3] >= a[3]
                          and (b != a or j < i) for j, b in enumerate(out))]
        self.free = out


# Part orders the packer tries; the result with the fewest sheets (then the lowest last sheet) wins.
ORDERS = (
    lambda s: (-max(s), -min(s)),     # longest side first
    lambda s: (-s[0] * s[1],),        # biggest area first
    lambda s: (-s[1], -s[0]),         # tallest first
    lambda s: (-s[0], -s[1]),         # widest first
    lambda s: (-min(s), -max(s)),     # thickest first
)


def pack(sizes, sheet=A3, edge=M.EDGE, gap=M.GAP, locked=(), allow_rotate=True):
    """sizes: [(w, h)] per part index. locked: placements to keep as they are (hand-placed parts).
    Returns (placements, too_big): placements for every part that fits, too_big = indices that never fit."""
    best = None
    for order in ORDERS:
        placements, too_big = _pack_once(sizes, sheet, edge, gap, locked, allow_rotate, order)
        n = max((p["sheet"] for p in placements), default=-1) + 1
        last = max((p["y"] + rotated_size(*sizes[p["part"]], p["rot"])[1]
                    for p in placements if p["sheet"] == n - 1), default=0.0)
        score = (n, last)
        if best is None or score < best[0]:
            best = (score, placements, too_big)
    return best[1], best[2]


def _pack_once(sizes, sheet, edge, gap, locked, allow_rotate, order):
    x0, y0, x1, y1 = area(sheet, edge)
    # every rectangle grows by the gap on its right and top; the bin grows by the same so the last
    # part may touch the edge margin
    bins = []

    def new_bin():
        b = _MaxRects(x0, y0, x1 + gap, y1 + gap)
        bins.append(b)
        return b

    placements = {}
    locked = [dict(p) for p in locked if p["part"] < len(sizes)]
    for p in locked:
        while len(bins) <= p["sheet"]:
            new_bin()
        w, h = rotated_size(*sizes[p["part"]], p["rot"])
        bins[p["sheet"]].occupy(p["x"], p["y"], p["x"] + w + gap, p["y"] + h + gap)
        placements[p["part"]] = p
    too_big = [i for i, (w, h) in enumerate(sizes) if i not in placements and not fits(w, h, sheet, edge)]
    todo = [i for i in range(len(sizes)) if i not in placements and i not in too_big]
    todo.sort(key=lambda i: order(sizes[i]) + (i,))
    for i in todo:
        w, h = sizes[i]
        orients = [(0, w, h)] + ([(90, h, w)] if allow_rotate and abs(w - h) > 1e-6 else [])
        done = False
        for n, b in enumerate(bins):
            best = None
            for rot, rw, rh in orients:
                pos = b.find(rw + gap, rh + gap)
                if pos and (best is None or (pos[1] + rh, pos[0]) < best[0]):
                    best = ((pos[1] + rh, pos[0]), rot, rw, rh, pos)
            if best:
                _key, rot, rw, rh, (px, py) = best
                b.occupy(px, py, px + rw + gap, py + rh + gap)
                placements[i] = {"part": i, "sheet": n, "x": px, "y": py, "rot": rot}
                done = True
                break
        if not done:
            b = new_bin()
            fitting = [o for o in orients if b.find(o[1] + gap, o[2] + gap)]
            rot, rw, rh = min(fitting, key=lambda o: o[2])
            px, py = b.find(rw + gap, rh + gap)
            b.occupy(px, py, px + rw + gap, py + rh + gap)
            placements[i] = {"part": i, "sheet": len(bins) - 1, "x": px, "y": py, "rot": rot}
    return [placements[i] for i in sorted(placements)], too_big


def offcut(placements, sizes, sheet, n, edge=M.EDGE):
    """Height of the clean strip left above the parts on sheet n (full sheet width), in mm."""
    sw, sh, _usable = sheet_tuple(sheet)
    top = 0.0
    for p in placements:
        if p["sheet"] == n:
            _w, h = rotated_size(*sizes[p["part"]], p["rot"])
            top = max(top, p["y"] + h)
    return max(0.0, sh - top - M.GAP)
