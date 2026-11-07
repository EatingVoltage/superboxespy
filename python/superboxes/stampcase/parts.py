"""A stamp case's boards as superboxes parts, so they go through the same sheets, packer, 3D and export as every box
type's parts (.grill/stamp-case-merge.md: one packer, one sheet view).

A board's items (layout.Layout.pages) are in design coordinates; the part's own coordinates put the board's
lower-left corner at (margin, margin), the margin leaving room for the kerf. The sheet view and 3D draw the items as
designed; placed_ev() is what LightBurn gets: rotated onto the sheet, then kerf applied per machine axis by role -
outlines grow, pockets shrink, magnet holes and engravings stay as drawn.
"""
import numpy as np
from shapely import affinity
from shapely.geometry import Point
from shapely.ops import unary_union

from evlaser import geom as G
from evlaser import machine as M

from ..capture import _poly_json, _r, _sub_json
from . import config as C
from . import shapes as S

KERF = {"outline": S.kerf_outline, "hole": S.kerf_hole}
CIRCLE_SEGS = 16   # quad_segs for magnet holes in the 3D and sheet view (LightBurn gets true circles)


def _rings(g):
    polys = list(g.geoms) if hasattr(g, "geoms") else [g]
    for p in polys:
        if p.is_empty:
            continue
        yield p.exterior
        yield from p.interiors


def _lines(g):
    if g.is_empty:
        return []
    return list(g.geoms) if hasattr(g, "geoms") else [g]


def _subpaths(items):
    """[(start, [(None, None, end)], closed)] per item, in the evlaser 'bez' format the sheet view reads."""
    out = []
    for _role, _layer, kind, *data in items:
        if kind == "poly":
            for ring in _rings(data[0]):
                pts = [tuple(p) for p in np.asarray(ring.coords)]
                out.append((pts[0], [(None, None, p) for p in pts[1:]], True))
        elif kind == "lines":
            for ls in _lines(data[0]):
                pts = [tuple(p) for p in np.asarray(ls.coords)]
                if len(pts) > 1:
                    out.append((pts[0], [(None, None, p) for p in pts[1:]], False))
        elif kind == "circle":
            ring = Point(data[0]).buffer(data[1], quad_segs=CIRCLE_SEGS).exterior
            pts = [tuple(p) for p in np.asarray(ring.coords)]
            out.append((pts[0], [(None, None, p) for p in pts[1:]], True))
    return out


class BoardPart:
    """One board, duck-typed like capture.Part (index, name, w, h, shape, outline, comp, subpaths, to_json) plus
    placed_ev() for the export."""

    def __init__(self, index, key, title, items, rect, margin):
        x0, y0, x1, y1 = rect
        self.index, self.key, self.name = index, key, title
        self.margin = margin
        self.ox, self.oy = x0 - margin, y0 - margin            # design -> part: subtract
        self.w, self.h = x1 - x0 + 2 * margin, y1 - y0 + 2 * margin
        self.items = [(role, layer, kind, *self._local(kind, data)) for role, layer, kind, *data in items]
        outline = next(it[3] for it in self.items if it[0] == "outline")
        holes = [it[3] for it in self.items if it[0] == "hole"]
        holes += [Point(it[3]).buffer(it[4], quad_segs=CIRCLE_SEGS) for it in self.items if it[0] == "magnet"]
        self.outline = outline                                # as designed; check_layout grows it by comp
        self.shape = outline.difference(unary_union(holes)) if holes else outline
        self.comp = (C.BURN_X, C.BURN_Y)
        cut = [it for it in self.items if it[1] == M.CUT]
        line = [it for it in self.items if it[1] == M.LINE]
        self.subpaths = {M.CUT: _subpaths(cut), M.LINE: _subpaths(line), M.REF: []}
        self.labels, self.walls, self.children = [], [], []

    def _local(self, kind, data):
        if kind == "circle":
            (x, y), r = data
            return [(x - self.ox, y - self.oy), r]
        return [affinity.translate(data[0], -self.ox, -self.oy)] + list(data[1:])

    def to_json(self):
        return {
            "index": self.index, "name": self.name, "w": _r(self.w), "h": _r(self.h), "key": self.key,
            "paths": {str(k): [_sub_json(s) for s in v] for k, v in self.subpaths.items() if v},
            "labels": [], "shape": _poly_json(self.shape), "area": round(self.shape.area, 2), "children": [],
            "walls": [], "origin": [_r(self.ox), _r(self.oy)],
        }

    def placed_ev(self, pl):
        """evlaser Part on the sheet: rotated about the part's lower-left corner and moved as superboxes places
        every part (export.placed), then kerf per axis on outline and pockets, after turning."""
        e = G.Part(self.name)
        for _role, layer, kind, *data in self.items:
            e.add(layer, kind, *data)
        rot = pl["rot"] % 360
        if rot == 90:
            e = e.transformed(90, pl["x"] + self.h, pl["y"])
        elif rot == 180:
            e = e.transformed(180, pl["x"] + self.w, pl["y"] + self.h)
        elif rot == 270:
            e = e.transformed(270, pl["x"], pl["y"] + self.w)
        else:
            e = e.transformed(0, pl["x"], pl["y"])
        roles = [it[0] for it in self.items]
        e.items = [(it[0], it[1], KERF[r](it[2])) if r in KERF else it for r, it in zip(roles, e.items)]
        return e


def board_parts(lay):
    """The case's boards, bottom to top, as parts."""
    margin = max(C.BURN_X, C.BURN_Y)
    return [BoardPart(i, key, title, items, lay.rect, margin) for i, (key, title, items) in enumerate(lay.pages())]
