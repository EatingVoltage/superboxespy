"""Packing parts onto sheets: bottom-left first, so what's left is one clean strip across the top of the sheet.

Placement = {"part": index, "sheet": n, "x": .., "y": .., "rot": 0|90}: (x, y) is the lower-left corner of the
part's (rotated) bounding box on the sheet, mm from the sheet's lower-left corner = LightBurn workspace 0,0.
Rotation is 90° counter-clockwise about the part's own lower-left corner, then shifted back into the box.

Rules from the eVlaser setup: 3 mm from the sheet edge, 1.5 mm between parts, nothing above the 390 mm reach
line. A part that fits in neither orientation is an error, never split.
"""
from dataclasses import dataclass

from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, unary_union

from evlaser import lbrn, machine as M

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


# How parts may turn: each one as suits it best, or all turned / all upright where they fit. Turning every part
# alike is what puts equal parts in a grid (stampcaser's boards: 4 a sheet turned, 2 upright).
TURNS = ("free", "turned", "upright")


def pack(sizes, sheet=A3, edge=M.EDGE, gap=M.GAP, locked=(), allow_rotate=True):
    """sizes: [(w, h)] per part index. locked: placements to keep as they are (hand-placed parts).
    Returns (placements, too_big): placements for every part that fits, too_big = indices that never fit.
    Every part order is tried with every turn policy; the fewest sheets win, then the lowest last sheet (the
    biggest clean offcut). Ties keep the first found, so "free" turning wins unless another is strictly better."""
    best = None
    for turn in (TURNS if allow_rotate else ("upright",)):
        for order in ORDERS:
            placements, too_big = _pack_once(sizes, sheet, edge, gap, locked, allow_rotate, order, turn)
            n = max((p["sheet"] for p in placements), default=-1) + 1
            last = max((p["y"] + rotated_size(*sizes[p["part"]], p["rot"])[1]
                        for p in placements if p["sheet"] == n - 1), default=0.0)
            score = (n, last)
            if best is None or score < best[0]:
                best = (score, placements, too_big)
    return best[1], best[2]


def _pack_once(sizes, sheet, edge, gap, locked, allow_rotate, order, turn="free"):
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
        if turn != "free" and len(orients) == 2:
            want = orients[1] if turn == "turned" else orients[0]
            if want[1] <= x1 - x0 + 1e-6 and want[2] <= y1 - y0 + 1e-6:    # that way round fits the sheet
                orients = [want]
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


def keep_locked(sizes, layout, sheet):
    """Hand-placed parts (placements) that are still inside the area and clear of each other: sizes may have changed
    since they were placed. sizes: [(w, h)] per part index."""
    keep = []
    x0, y0, x1, y1 = area(sheet)
    for pl in layout or []:
        if pl.get("part", -1) >= len(sizes):
            continue
        w, h = rotated_size(*sizes[pl["part"]], pl["rot"])
        if pl["x"] < x0 - 1e-3 or pl["y"] < y0 - 1e-3 or pl["x"] + w > x1 + 1e-3 or pl["y"] + h > y1 + 1e-3:
            continue
        clash = False
        for q in keep:
            qw, qh = rotated_size(*sizes[q["part"]], q["rot"])
            if (q["sheet"] == pl["sheet"] and pl["x"] < q["x"] + qw + M.GAP - 1e-3 and q["x"] < pl["x"] + w + M.GAP - 1e-3
                    and pl["y"] < q["y"] + qh + M.GAP - 1e-3 and q["y"] < pl["y"] + h + M.GAP - 1e-3):
                clash = True
                break
        if not clash:
            keep.append({k: pl[k] for k in ("part", "sheet", "x", "y", "rot")})
    return keep


def place(sizes, layout, sheet, noun="parts"):
    """A build's layout, for every type: (placements, too_big, warnings, sheets [{"index", "offcut"}]). The hand-placed
    parts in `layout` that still fit stay (keep_locked), the rest is packed around them; warnings: that some had to
    move."""
    locked = keep_locked(sizes, layout, sheet)
    warnings = []
    if layout and len(locked) < len([p for p in layout if p.get("part", -1) < len(sizes)]):
        warnings.append("Some hand-placed %s no longer fit where they were and were packed again." % noun)
    placements, too_big = pack(sizes, sheet, locked=locked)
    n_sheets = max((pl["sheet"] for pl in placements), default=-1) + 1
    sheets = [{"index": n, "offcut": round(offcut(placements, sizes, sheet, n), 1)} for n in range(n_sheets)]
    return placements, too_big, warnings, sheets


# ------------------------------------------------------------------ rest pieces
# The rest wood is cut free as rectangles once the parts are done (stampcaser, user 2026-10-24; every type since
# .grill/stamp-case-merge.md): short cuts carry the parts' own edges out to the sheet's edges, on their own layer.
FRAME_LAYER = 7          # C07 with CUT's values, run last: stampcaser's frame layer, the first case's extra-cut layer
FRAME_MIN_PIECE = 10.0   # a rest piece narrower than this isn't cut free
FRAME_OVERSHOOT = 2.0    # horizontal cuts run past the sheet's right edge, so they go through it
FRAME_STEP = 0.5         # right ends closer than this make one piece, not a step


@dataclass
class Piece:
    name: str
    rect: tuple         # (x0, y0, x1, y1) on the sheet: edges on cut paths or sheet edges, x1 the sheet's right edge

    @property
    def size(self):
        x0, y0, x1, y1 = self.rect
        return x1 - x0, y1 - y0


def rest_pieces(boxes, sheet, names=None):
    """The rectangles of rest wood worth keeping beside the parts on one sheet, for any layout. boxes: (x0, y0, x1,
    y1) of each part's cut path; names: the parts' names, for the Notes. First the full-width piece above the highest
    part, then the pieces right of the parts, band by band from the bottom: a band ends at a part's top edge and its
    piece starts at the right end of the parts in it. Bands whose right ends are within FRAME_STEP make one piece; a
    band thinner than FRAME_MIN_PIECE joins the neighbour that wastes the least wood. Pieces need FRAME_MIN_PIECE both
    ways, and a piece whose cut would run above the reach limit stays with the sheet. On stampcaser's grids this
    gives stampcaser's pieces (tests/test_stampcase.py)."""
    sw, sh, usable = sheet_tuple(sheet)
    if not boxes:
        return []
    top = max(b[3] for b in boxes)
    out = []
    if top <= usable - 0.5:
        out.append(Piece("top rest piece", (0.0, top, sw, sh)))
    tops = []                    # the parts' top edges, those within a micron as one (the highest)
    for t in sorted(b[3] for b in boxes):
        if tops and t - tops[-1] < 1e-3:
            tops[-1] = t
        else:
            tops.append(t)
    bands, y0 = [], 0.0          # [y0, y1, right end, the part that sets it]
    for t in tops:
        inside = [i for i, b in enumerate(boxes) if b[1] < t - 1e-3 and b[3] > y0 + 1e-3]
        if not inside:           # a part thinner than a micron: nothing ends here
            continue
        i = max(inside, key=lambda i: (boxes[i][2], boxes[i][3]))
        bands.append([y0, t, boxes[i][2], i])
        y0 = t

    def join(k):                 # bands k and k + 1 become one, right of the parts of both
        a, b = bands[k], bands[k + 1]
        r = b if b[2] >= a[2] - 1e-9 else a
        bands[k:k + 2] = [[a[0], b[1], r[2], r[3]]]

    def waste(k):                # wood joining bands k and k + 1 leaves with the sheet
        a, b = bands[k], bands[k + 1]
        low = a if a[2] < b[2] else b
        return abs(a[2] - b[2]) * (low[1] - low[0])

    k = 0
    while k + 1 < len(bands):
        if abs(bands[k][2] - bands[k + 1][2]) < FRAME_STEP:
            join(k)
        else:
            k += 1
    while len(bands) > 1:
        thin = [k for k, b in enumerate(bands) if b[1] - b[0] < FRAME_MIN_PIECE]
        if not thin:
            break
        k = thin[0]
        join(min((j for j in (k - 1, k) if 0 <= j < len(bands) - 1), key=waste))
    for k, (y0, y1, x0, i) in enumerate(bands):
        if sw - x0 >= FRAME_MIN_PIECE and y1 - y0 >= FRAME_MIN_PIECE and y1 <= usable - 0.5:
            name = ("right rest piece" if k == 0 else
                    "rest piece beside the %s" % (names[i].lower() if names else "part %d" % (i + 1)))
            out.append(Piece(name, (x0, y0, sw, y1)))
    return out


def frame_lines(pieces, outlines, sheet):
    """The cuts that free the rest pieces: every edge of every piece that isn't a sheet edge, minus where it runs
    on a part's own cut (outlines: the parts' cut outlines on the sheet). Horizontal cuts overshoot the sheet's right
    edge so they go through. None if there's nothing to cut."""
    sw, sh, _usable = sheet_tuple(sheet)
    xe = sw + FRAME_OVERSHOOT
    segs = []
    for p in pieces:
        x0, y0, x1, y1 = p.rect
        if y0 > 1e-6:
            segs.append(LineString([(x0, y0), (xe, y0)]))
        if y1 < sh - 1e-6:
            segs.append(LineString([(x0, y1), (xe, y1)]))
        if x0 > 1e-6:
            segs.append(LineString([(x0, y0), (x0, y1)]))
    if not segs:
        return None
    near = unary_union([o.buffer(0.01) for o in outlines])     # stop where a cut meets a part's own cut
    rest = lbrn._lines(unary_union(segs).difference(near))
    keep = [g for g in lbrn._lines(linemerge(rest)) if g.length > 0.5] if rest else []
    return MultiLineString(keep) if keep else None
