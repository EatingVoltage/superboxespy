"""Automatic magnet holes: one near each corner, then more wherever the board is still more than MAGNET_COVER from a
magnet, so a big board gets about one every 100 mm along its edges and some where the strips between pockets
cross. Every hole keeps MAGNET_WOOD of wood to pockets, names, the top board's block and the edge."""
import numpy as np
from shapely.ops import unary_union

from . import config as C
from .grid import FreeGrid

MIN_SPACING = 20.0   # never two magnets closer than this


def free_region(lay):
    r = C.MAGNET_R
    keep = r + C.MAGNET_WOOD
    taken = [g.hole.buffer(keep) for g in lay.pockets]
    taken += [g.label_box.buffer(r + 0.5) for g in lay.pockets if g.label_box is not None]
    taken.append(lay.top.region.buffer(r + C.BLOCK_WOOD))
    return lay.board.buffer(-keep).difference(unary_union(taken))


def auto(lay):
    cand = FreeGrid(free_region(lay), lay.rect, res=1.0).points()
    if not len(cand):
        return []
    cover = FreeGrid(lay.board, lay.rect, res=4.0).points()
    x0, y0, x1, y1 = lay.rect
    k = C.CORNER_CUT / 2
    chosen = []

    def spaced():
        if not chosen:
            return np.ones(len(cand), bool)
        ch = np.array(chosen)
        return np.min(np.hypot(cand[:, None, 0] - ch[None, :, 0], cand[:, None, 1] - ch[None, :, 1]), 1) >= MIN_SPACING

    for corner in ((x0, y0), (x1, y0), (x0, y1), (x1 - k, y1 - k)):
        d = np.hypot(cand[:, 0] - corner[0], cand[:, 1] - corner[1])
        d[~spaced()] = np.inf
        i = int(np.argmin(d))
        if d[i] < 40.0:
            chosen.append(tuple(cand[i]))

    active = np.ones(len(cover), bool)
    for _ in range(100):
        if chosen:
            ch = np.array(chosen)
            dmin = np.min(np.hypot(cover[:, None, 0] - ch[None, :, 0], cover[:, None, 1] - ch[None, :, 1]), 1)
        else:
            dmin = np.full(len(cover), np.inf)
        dmin[~active] = 0
        w = int(np.argmax(dmin))
        if dmin[w] <= C.MAGNET_COVER:
            break
        d = np.hypot(cand[:, 0] - cover[w, 0], cand[:, 1] - cover[w, 1])
        d[~spaced()] = np.inf
        i = int(np.argmin(d))
        if not np.isfinite(d[i]) or d[i] > dmin[w] - 5.0:
            active[w] = False      # no magnet can get closer to that spot than the ones it has
            continue
        chosen.append(tuple(cand[i]))
    return [(round(float(x), 3), round(float(y), 3)) for x, y in chosen]


def nearest_free(lay, x, y):
    """The free magnet spot nearest to (x, y), for a magnet the user adds."""
    cand = FreeGrid(free_region(lay), lay.rect, res=0.5).points()
    if not len(cand):
        return None
    if lay.magnets:
        ch = np.array(lay.magnets)
        far = np.min(np.hypot(cand[:, None, 0] - ch[None, :, 0], cand[:, None, 1] - ch[None, :, 1]), 1) \
            >= 2 * C.MAGNET_R + C.MAGNET_WOOD
        cand = cand[far]
        if not len(cand):
            return None
    i = int(np.argmin(np.hypot(cand[:, 0] - x, cand[:, 1] - y)))
    return float(cand[i, 0]), float(cand[i, 1])

