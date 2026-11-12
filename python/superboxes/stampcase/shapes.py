"""Geometry of one case: pocket holes with their finger notch, name strips, the board with the eV cut corner,
per-axis kerf, eV Sans text and the eatingVoltage logo. Shapely, mm, Y up."""
import os
import xml.etree.ElementTree as ET
from functools import lru_cache

import shapely
from shapely import affinity
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box
from shapely.ops import unary_union

from evlaser import geom as G, svgpath, typeset

from ..kerf import offset_region
from ..svgart import SKIP, fit, mul, parse_transform
from . import config as C

Q = 16  # quad_segs: arcs as smooth as the old file's Béziers


# ------------------------------------------------------------------ pockets
def notch_centre(p, air):
    """Where the notch's centre sits along its side, measured from the side's low end."""
    return _notch_centre(*p.hole_size(air), p.notch_side, p.notch_end)


def _notch_centre(hw, hh, side, end):
    side_len = hh if side in ("left", "right") else hw
    c = min(C.NOTCH_FROM_END, side_len / 2)
    return c if end == "low" else side_len - c


def hole(p, air):
    """The pocket as drawn (before kerf): stamp + air, R3 corners, the half-ellipse finger notch with R3 rounds."""
    return affinity.translate(_hole0(*p.hole_size(air), p.notch_side, p.notch_end), p.x, p.y)


@lru_cache(maxsize=4096)
def _hole0(hw, hh, side, end):
    rect = G.rounded_rect(hw, hh, C.POCKET_R)
    c = _notch_centre(hw, hh, side, end)
    centre, (a, b) = {
        "right": ((hw, c), (C.NOTCH_OUT, C.NOTCH_HALF)),
        "left": ((0, c), (C.NOTCH_OUT, C.NOTCH_HALF)),
        "top": ((c, hh), (C.NOTCH_HALF, C.NOTCH_OUT)),
        "bottom": ((c, 0), (C.NOTCH_HALF, C.NOTCH_OUT)),
    }[side]
    ell = affinity.scale(Point(centre).buffer(1, quad_segs=2 * Q), a, b, origin=centre)
    r = C.NOTCH_FILLET
    return unary_union([rect, ell]).buffer(r, quad_segs=Q).buffer(-r, quad_segs=Q)


def strip(p, air, depth=C.LABEL_STRIP):
    """The room auto layout keeps for the pocket's name (B) along its preferred side, `depth` deep."""
    hw, hh = p.hole_size(air)
    s = depth
    return {
        "top": box(p.x, p.y + hh, p.x + hw, p.y + hh + s),
        "bottom": box(p.x, p.y - s, p.x + hw, p.y),
        "right": box(p.x + hw, p.y, p.x + hw + s, p.y + hh),
        "left": box(p.x - s, p.y, p.x, p.y + hh),
    }[p.label_side()]


def footprint_bounds(p, air):
    """The bounds of hole + name strip, roughly what a pocket claims on the top board, without building their union."""
    return tuple(shapely.total_bounds([hole(p, air), strip(p, air)]).tolist())


# ------------------------------------------------------------------ board
def board(x0, y0, x1, y1):
    """Board outline with R5 corners and the eV cut corner at the top right."""
    k = C.CORNER_CUT
    poly = Polygon([(x0, y0), (x1, y0), (x1, y1 - k), (x1 - k, y1), (x0, y1)])
    return poly.buffer(-C.BOARD_R, quad_segs=Q).buffer(C.BOARD_R, quad_segs=Q)


# ------------------------------------------------------------------ kerf
def _ellipse_offset(region, d):
    """Minkowski sum (d = +1) or difference (d = -1) with the kerf ellipse (BURN_X, BURN_Y): the laser's spot isn't
    round, so a cut path moves its own amount in X and in Y."""
    return offset_region(region, C.BURN_X, C.BURN_Y, quad_segs=4, sign=d)


def kerf_outline(poly):
    """Cut path for an outline: grown by half the kerf, so the part comes out at its drawn size."""
    return _ellipse_offset(poly, +1)


def kerf_hole(poly):
    """Cut path for a hole: shrunk by half the kerf, so the hole comes out at its drawn size."""
    return _ellipse_offset(poly, -1)


# ------------------------------------------------------------------ text
@lru_cache(maxsize=None)
def font(name):
    return typeset.Font(name, extra_dirs=[C.FONT_DIR])


def tracking(cap):
    return C.TRACKING_SMALL if cap < 3.0 else C.TRACKING


def text_width(s, cap, face=C.FONT_REGULAR):
    return font(face).width(s, cap, tracking(cap)) if s else 0.0


def fit_cap(s, max_w, cap, min_cap, face=C.FONT_REGULAR):
    """Largest cap height <= cap that fits max_w (never below min_cap) and whether it fits."""
    w = text_width(s, cap, face)
    if w <= max_w or w == 0:
        return cap, True
    fitted = cap * max_w / w
    return max(fitted, min_cap), fitted >= min_cap


def text(s, cx, cy, cap, face=C.FONT_REGULAR, rot=0):
    """Outline polygons of one line, its cap height centred on (cx, cy). rot 90 reads bottom to top."""
    if not s.strip():
        return Polygon()
    return affinity.translate(_text0(s, cap, face, rot), cx, cy)


@lru_cache(maxsize=2048)
def _text0(s, cap, face, rot):
    """The outlines centred on the origin: names don't change between two edits, so every rebuild reuses them
    (a third of a 16-stamp build was rebuilding glyph outlines, 2026-11-07)."""
    g = font(face).text(s, 0, -cap / 2, cap, align="center", tracking=tracking(cap))
    return affinity.rotate(g, rot, origin=(0, 0)) if rot else g


# ------------------------------------------------------------------ logo
def logo_files(kinds=(".svg",), key=None):
    """The logos folders' files ending in one of `kinds`, sorted (by `key`). The stamp case takes SVGs only; the face
    editor's library .lbrn2 as well (faces.logos)."""
    names = set()
    for d in C.LOGO_DIRS:
        try:
            names.update(f for f in os.listdir(d) if f.lower().endswith(kinds))
        except OSError:
            pass
    return sorted(names, key=key)


def logo_path(name):
    """The logo file `name` from the first LOGO_DIRS folder that has it, else None."""
    return next((p for p in (os.path.join(d, name) for d in C.LOGO_DIRS) if os.path.exists(p)), None)


def logo_raw(path):
    """Every drawn path of a line-art SVG as polylines, Y up, in the SVG's own units; read again when the file
    changes (as lbrnart.load)."""
    st = os.stat(path)
    return _logo_raw(path, (st.st_mtime_ns, st.st_size))


@lru_cache(maxsize=32)
def _logo_raw(path, _stamp):
    root = ET.parse(path).getroot()
    lines = []

    def walk(el, m):
        tag = el.tag.split("}")[-1]
        if tag in SKIP:
            return
        m = mul(m, parse_transform(el.get("transform")))
        if tag == "path" and el.get("d"):
            for sub in svgpath.parse(el.get("d")):
                pts = [(m[0] * x + m[2] * y + m[4], -(m[1] * x + m[3] * y + m[5])) for x, y in svgpath.flatten(sub, 10)]
                if len(pts) > 1:
                    if sub[2] and pts[0] != pts[-1]:
                        pts.append(pts[0])
                    lines.append(LineString(pts))
        for ch in el:
            walk(ch, m)

    walk(root, [1, 0, 0, 1, 0, 0])
    return MultiLineString(lines)


def logo(name, cx, cy, height, rot=0):
    """The logo's strokes as engraving lines, `height` tall, centred on (cx, cy)."""
    path = logo_path(name)
    if not path:
        return MultiLineString()
    g = logo_raw(path)
    if g.is_empty:
        return g
    g = affinity.affine_transform(g, fit(g.bounds, height))
    if rot:
        g = affinity.rotate(g, rot, origin=(0, 0))
    return affinity.translate(g, cx, cy)


def logo_aspect(name):
    path = logo_path(name)
    if not path:
        return 2.5
    x0, y0, x1, y1 = logo_raw(path).bounds
    return (x1 - x0) / (y1 - y0)
