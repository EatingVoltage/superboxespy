"""Boards on sheets (user 2026-10-24: "if it fits, put more than one piece on one page ... be economical with wood
stock"). All of a case's boards are the same size, so a sheet holds a grid of them, turned 90 degrees when that fits
more. Sheets are filled in board order, as full as they go, so only the last one has room to spare; each sheet's
grid is the one that leaves the biggest rest piece. The rest wood is then cut free as rectangles: the full-width
piece above the boards and the pieces to their right.

Positions here are cut paths in sheet coordinates (board size + kerf), lower-left corners."""
import math
from dataclasses import dataclass

from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, unary_union

from . import config as C
from evlaser import lbrn
from evlaser import machine as M


@dataclass
class Spot:
    board: int          # index into the case's boards (base, pocket boards, lid)
    rot: bool           # turned 90 degrees counter-clockwise
    x: float            # cut path lower-left on the sheet
    y: float


@dataclass
class Piece:
    name: str
    rect: tuple         # (x0, y0, x1, y1) on the sheet: edges on cut paths or sheet edges, x1 the sheet's right edge

    @property
    def size(self):
        x0, y0, x1, y1 = self.rect
        return x1 - x0, y1 - y0


def _room():
    """(width, height) the cut paths may use: eVlaser's EDGE from the sheet's edges, and below the reach limit."""
    sw, sh, usable = C.SHEET
    return sw - 2 * M.EDGE, min(usable, sh - M.EDGE) - M.EDGE


def max_board():
    """The largest board, upright; turned, the two swap."""
    rx, ry = _room()
    return rx - C.KERF_X, ry - C.KERF_Y


def path_size(w, h, rot):
    """Machine size of a w x h board's cut path. Kerf is per machine axis, so turning swaps the sizes, not the kerf."""
    return (h if rot else w) + C.KERF_X, (w if rot else h) + C.KERF_Y


def grid(w, h, rot):
    """(columns, rows) of w x h boards that fit on one sheet."""
    rx, ry = _room()
    pw, ph = path_size(w, h, rot)
    return max(int((rx + M.GAP + 1e-6) // (pw + M.GAP)), 0), max(int((ry + M.GAP + 1e-6) // (ph + M.GAP)), 0)


def per_sheet(w, h):
    return max(c * r for c, r in (grid(w, h, False), grid(w, h, True)))


def sheet_count(w, h, n):
    """Sheets for n boards of w x h, or None when one doesn't fit at all."""
    k = per_sheet(w, h)
    return math.ceil(n / k) if k else None


def hint(w, h, n, most=C.SHEET_HINT):
    """(how much smaller, "narrower"|"shorter", sheets then) for the smallest single cut in board width or height,
    up to `most`, that saves a sheet; else None. For the GUI, while pockets are arranged by hand."""
    now = sheet_count(w, h, n)
    if not now or now == 1:
        return None
    rx, ry = _room()
    best = None
    for rot in (False, True):
        cols, rows = grid(w, h, rot)
        # the design size at which one more column (or row) fits; machine X is the board's width unless turned
        for need, along_x in (((rx + M.GAP) / (cols + 1) - M.GAP - C.KERF_X, True),
                              ((ry + M.GAP) / (rows + 1) - M.GAP - C.KERF_Y, False)):
            narrower = along_x != rot
            d = float((w if narrower else h) - need + 0.05)
            if d <= 0 or d > most:
                continue
            then = sheet_count(w - d, h, n) if narrower else sheet_count(w, h - d, n)
            if then and then < now and (best is None or d < best[0]):
                best = (d, "narrower" if narrower else "shorter", then)
    return best


def _grid_spots(w, h, rot, cols, first, m):
    pw, ph = path_size(w, h, rot)
    return [Spot(first + k, rot, M.EDGE + (k % cols) * (pw + M.GAP), M.EDGE + (k // cols) * (ph + M.GAP))
            for k in range(m)]


def rest_pieces(spots, w, h, titles=None):
    """The rectangles of rest wood worth keeping around boards laid out row by row from the bottom left: the
    full-width piece above them, then the pieces right of each run of rows that end in the same place. Pieces need
    FRAME_MIN_PIECE both ways; a piece whose cut would run above the reach limit stays with the sheet."""
    sw, sh, usable = C.SHEET
    if not spots:
        return []
    pw, ph = path_size(w, h, spots[0].rot)
    by_y = {}
    for s in spots:
        by_y.setdefault(round(s.y, 3), []).append(s)
    # (top, right end, last board) of each row, bottom up
    rows = [(y + ph, last.x + pw, last) for y, r in sorted(by_y.items()) for last in [max(r, key=lambda s: s.x)]]
    top = rows[-1][0]
    out = []
    if top <= usable - 0.5:
        out.append(Piece("top rest piece", (0.0, top, sw, sh)))
    k = 0
    while k < len(rows):
        j = k
        while j + 1 < len(rows) and abs(rows[j + 1][1] - rows[k][1]) < 0.01:
            j += 1
        x0, y0, y1 = rows[k][1], (rows[k - 1][0] if k else 0.0), rows[j][0]
        if sw - x0 >= C.FRAME_MIN_PIECE and y1 - y0 >= C.FRAME_MIN_PIECE and y1 <= usable - 0.5:
            if k == 0:
                name = "right rest piece"
            else:
                beside = rows[j][2].board
                name = "rest piece beside the %s" % (titles[beside].lower() if titles else "board %d" % (beside + 1))
            out.append(Piece(name, (x0, y0, sw, y1)))
        k = j + 1
    return out


def frame_lines(pieces, outlines):
    """The cuts that free the rest pieces: every edge of every piece that isn't a sheet edge, minus where it runs
    on a board's own cut. Horizontal cuts overshoot the sheet's right edge so they go through. None if no cut."""
    sw, sh, usable = C.SHEET
    xe = sw + C.FRAME_OVERSHOOT
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
    near = unary_union([o.buffer(0.01) for o in outlines])     # stop where a cut meets a board's own cut
    rest = lbrn._lines(unary_union(segs).difference(near))
    keep = [g for g in lbrn._lines(linemerge(rest)) if g.length > 0.5] if rest else []
    return MultiLineString(keep) if keep else None


def arrange(w, h, n):
    """[[Spot]] per sheet for n boards of w x h: sheets filled in board order, as full as they go; each sheet's grid
    (turned or not, how many columns) the one that leaves the biggest rest piece."""
    k = per_sheet(w, h)
    if not k:
        return []
    grids = [(rot,) + grid(w, h, rot) for rot in (False, True)]
    out = []
    for first in range(0, n, k):
        m = min(k, n - first)
        best = None
        for rot, cols, rows in grids:
            for c in range(1, min(cols, m) + 1):
                if math.ceil(m / c) > rows:
                    continue
                spots = _grid_spots(w, h, rot, c, first, m)
                areas = tuple(sorted(-round(a * b) for a, b in (p.size for p in rest_pieces(spots, w, h)))) or (0,)
                if best is None or (areas, rot) < best[0]:
                    best = ((areas, rot), spots)
        out.append(best[1])
    return out
