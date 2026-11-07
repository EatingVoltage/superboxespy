"""A free region sampled on a grid: fast answers to "where does a w x h rectangle fit" and "which points are free"."""
import numpy as np
import shapely
from shapely.geometry import box

from evlaser.textures import _ring_edges


def inside_grid(region, xs, ys):
    """Which points of the grid xs x ys lie inside `region`, by scanlines: a point is inside when an odd number of ring
    edges cross its row left of it; points on the boundary are outside. shapely.contains_xy's answer exactly, in a few
    numpy passes: 3-7x faster on a stamp case's boards, where it was a fifth of a build (2026-11-07)."""
    ny, nx = len(ys), len(xs)
    ok = np.zeros((ny, nx), bool)
    p0, p1 = _ring_edges(region)
    if not len(p0):
        return ok
    cross = (p0[:, 1][None, :] <= ys[:, None]) != (p1[:, 1][None, :] <= ys[:, None])
    r, e = np.nonzero(cross)
    x = p0[e, 0] + (ys[r] - p0[e, 1]) / (p1[e, 1] - p0[e, 1]) * (p1[e, 0] - p0[e, 0])
    diff = np.zeros((ny, nx + 1), np.int32)
    np.add.at(diff, (r, np.searchsorted(xs, x, side="right")), 1)
    ok = (np.cumsum(diff[:, :-1], 1) & 1).astype(bool)
    # the boundary itself is outside (exact comparisons, as contains_xy's: a point 1e-16 inside is inside): points
    # an edge crosses exactly, and points on an edge along their row
    near = np.clip(np.searchsorted(xs, x), 0, nx - 1)
    for k in (near, np.clip(near - 1, 0, nx - 1)):
        hit = xs[k] == x
        ok[r[hit], k[hit]] = False
    flat = np.nonzero(p0[:, 1] == p1[:, 1])[0]
    for i in flat:
        row = np.nonzero(ys == p0[i, 1])[0]
        if len(row):
            lo, hi = sorted((p0[i, 0], p1[i, 0]))
            ok[row[0], (xs >= lo) & (xs <= hi)] = False
    return ok


class FreeGrid:
    def __init__(self, free, rect, res=0.5):
        x0, y0, x1, y1 = rect
        self.res, self.free = res, free
        self.xs = np.arange(x0, x1 + res / 2, res)
        self.ys = np.arange(y0, y1 + res / 2, res)
        X, Y = np.meshgrid(self.xs, self.ys)
        shapely.prepare(free)
        self.ok = inside_grid(free, self.xs, self.ys) if not free.is_empty else np.zeros(X.shape, bool)
        self.X, self.Y = X, Y

    def _integral(self):
        """Summed-area table of the taken cells, made once per grid: rect_spot is asked many sizes in a row."""
        if getattr(self, "_integ", None) is None:
            ny, nx = self.ok.shape
            self._integ = np.zeros((ny + 1, nx + 1), np.int32)
            self._integ[1:, 1:] = np.cumsum(np.cumsum(~self.ok, 0), 1)
        return self._integ

    def points(self):
        return np.c_[self.X[self.ok], self.Y[self.ok]]

    def rect_spot(self, w, h, cx, cy, tries=40):
        """Centre of a free w x h rectangle nearest to (cx, cy), or None."""
        r = self.res
        kw, kh = int(np.ceil(w / r)) + 1, int(np.ceil(h / r)) + 1
        ny, nx = self.ok.shape
        if kw > nx or kh > ny:
            return None
        integ = self._integral()
        s = integ[kh:, kw:] - integ[:-kh, kw:] - integ[kh:, :-kw] + integ[:-kh, :-kw]
        iy, ix = np.nonzero(s == 0)
        if not len(iy):
            return None
        px = self.xs[ix] + (kw - 1) * r / 2
        py = self.ys[iy] + (kh - 1) * r / 2
        order = np.argsort(np.hypot(px - cx, py - cy))
        for k in order[:tries]:
            x, y = float(px[k]), float(py[k])
            if self.free.contains(box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)):
                return x, y
        return None
