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
from evlaser import lbrn
from evlaser import machine as M

from .. import export as X
from ..capture import _poly_json, _r
from . import config as C
from . import shapes as S

KERF = {"outline": S.kerf_outline, "hole": S.kerf_hole}
CIRCLE_SEGS = 16   # quad_segs for magnet holes in the 3D and sheet view (LightBurn gets true circles)


def _polylines(items):
    """(points (n, 2), closed) of every ring and line of the items, as the laser draws them."""
    for _role, _layer, kind, *data in items:
        if kind == "poly":
            for ring in X.rings(data[0]):
                yield np.asarray(ring.coords)[:, :2], True
        elif kind == "lines":
            for ls in lbrn._lines(data[0]):
                if len(ls.coords) > 1:
                    yield np.asarray(ls.coords)[:, :2], False
        elif kind == "circle":
            yield np.asarray(Point(data[0]).buffer(data[1], quad_segs=CIRCLE_SEGS).exterior.coords), True


def _subpaths(items):
    """[(start, [(None, None, end)], closed)] per item, in the evlaser 'bez' format."""
    return [(tuple(a[0]), [(None, None, tuple(p)) for p in a[1:]], closed) for a, closed in _polylines(items)]


def _paths_json(items):
    """The items as the sheet view's and the 3D's paths, [{"start", "segs", "closed"}]: straight from the point
    arrays, rounded once (going through _subpaths and capture._sub_json was a quarter of a 16-stamp build)."""
    out = []
    for a, closed in _polylines(items):
        v = np.round(a, 3).tolist()
        out.append({"start": v[0], "segs": v[1:], "closed": closed})
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
        self.labels, self.walls, self.children = [], [], []

    def _by_layer(self):
        return {M.CUT: [it for it in self.items if it[1] == M.CUT], M.LINE: [it for it in self.items if it[1] == M.LINE]}

    @property
    def subpaths(self):
        """Like capture.Part's, for anything duck-typed that asks: the boards themselves don't need them (their
        export is placed_ev, their JSON _paths_json)."""
        return {**{k: _subpaths(v) for k, v in self._by_layer().items()}, M.REF: []}

    def _local(self, kind, data):
        if kind == "circle":
            (x, y), r = data
            return [(x - self.ox, y - self.oy), r]
        return [affinity.translate(data[0], -self.ox, -self.oy)] + list(data[1:])

    def to_json(self):
        return {
            "index": self.index, "name": self.name, "w": _r(self.w), "h": _r(self.h), "key": self.key,
            "paths": {str(k): _paths_json(v) for k, v in self._by_layer().items() if v},
            "labels": [], "shape": _poly_json(self.shape), "area": round(self.shape.area, 2), "children": [],
            "walls": [], "origin": [_r(self.ox), _r(self.oy)],
        }

    def placed_ev(self, pl):
        """evlaser Part on the sheet: rotated about the part's lower-left corner and moved as superboxes places
        every part (export.placed), then kerf per axis on outline and pockets, after turning."""
        e = G.Part(self.name)
        for _role, layer, kind, *data in self.items:
            e.add(layer, kind, *data)
        e = X.placed(e, self, pl)
        roles = [it[0] for it in self.items]
        e.items = [(it[0], it[1], KERF[r](it[2])) if r in KERF else it for r, it in zip(roles, e.items)]
        return e


def board_parts(lay):
    """The case's boards, bottom to top, as parts."""
    margin = max(C.BURN_X, C.BURN_Y)
    return [BoardPart(i, key, title, items, lay.rect, margin) for i, (key, title, items) in enumerate(lay.pages())]
