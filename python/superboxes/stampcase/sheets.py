"""How many of a case's boards fit a sheet (user 2026-10-24: "if it fits, put more than one piece on one page ... be
economical with wood stock"). All of a case's boards are the same size, so a sheet holds a grid of them, turned 90
degrees when that fits more: the board editor's sheet count and its "a little smaller saves a sheet" hint, and the
auto layout's score. Where the boards really go, and the rest pieces cut free around them, is the shared packer's
business (superboxes/sheets.py).

Sizes here are cut paths (board size + kerf)."""
import math

from . import config as C
from evlaser import machine as M


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
