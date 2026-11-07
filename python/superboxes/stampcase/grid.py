"""A free region sampled on a grid: fast answers to "where does a w x h rectangle fit" and "which points are free"."""
import numpy as np
import shapely
from shapely.geometry import box


class FreeGrid:
    def __init__(self, free, rect, res=0.5):
        x0, y0, x1, y1 = rect
        self.res, self.free = res, free
        self.xs = np.arange(x0, x1 + res / 2, res)
        self.ys = np.arange(y0, y1 + res / 2, res)
        X, Y = np.meshgrid(self.xs, self.ys)
        shapely.prepare(free)
        self.ok = shapely.contains_xy(free, X, Y) if not free.is_empty else np.zeros(X.shape, bool)
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
