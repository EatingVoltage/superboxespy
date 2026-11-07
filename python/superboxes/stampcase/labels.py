"""Where each pocket's name (B) goes on the top pocket board. It tries the pocket's preferred side first, then the
other sides, at every position along each side, and shrinks down to LABEL_MIN_CAP before giving up. Text keeps
TEXT_CUT of wood to every cut and to the other names, so hand-nested pockets only need room for the text itself,
not for a reserved strip."""
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon

from . import config as C
from . import shapes as S
from .model import OPPOSITE

SIDES = ("left", "right", "bottom", "top")
STEP = 1.0          # mm between candidate positions along a side


def side_order(p):
    """The pocket's own choice (label_pos) first: beside the notch, the opposite side, or the far end."""
    opposite = OPPOSITE[p.notch_side]
    far = p.far_end()
    near = OPPOSITE[far]
    return {"notch": [p.notch_side, opposite, far, near],
            "side": [opposite, p.notch_side, far, near],
            "end": [far, p.notch_side, opposite, near]}[p.label_pos]


def _candidates(rect, side, along, across, prefer, offsets):
    """Boxes (x0, y0, x1, y1, offset rank, distance from `prefer`) of a text `along` long and `across` thick, next to
    `rect` on `side`, at each distance in `offsets` from the side."""
    rx0, ry0, rx1, ry1 = rect
    vertical = side in ("left", "right")
    lo, hi = (ry0, ry1) if vertical else (rx0, rx1)
    if hi - lo > along:
        centres = np.arange(lo + along / 2, hi - along / 2 + 1e-9, STEP)
    else:
        centres = np.array([(lo + hi) / 2])
    out = []
    for k, d in enumerate(offsets):
        for c in centres:
            far = abs(c - prefer)
            if side == "right":
                out.append((rx1 + d, c - along / 2, rx1 + d + across, c + along / 2, k, far))
            elif side == "left":
                out.append((rx0 - d - across, c - along / 2, rx0 - d, c + along / 2, k, far))
            elif side == "top":
                out.append((c - along / 2, ry1 + d, c + along / 2, ry1 + d + across, k, far))
            else:
                out.append((c - along / 2, ry0 - d - across, c + along / 2, ry0 - d, k, far))
    return np.array(out)


def place(lay, blockers, allowed):
    """Set g.label / g.label_box / g.label_cap / g.label_fits on every pocket of `lay`.
    blockers: geometry no name may touch (magnets with their clearance, the top block); allowed: where a name may
    go without making the board bigger. A name outside it grows the board, so it's only used when nothing inside fits."""
    holes = shapely.STRtree([g.hole for g in lay.pockets]) if lay.pockets else None
    if blockers is not None and not blockers.is_empty:
        shapely.prepare(blockers)
    shapely.prepare(allowed)
    ax0, ay0, ax1, ay1 = allowed.bounds
    placed = []
    for g in lay.pockets:
        p = g.pocket
        g.label, g.label_box, g.label_cap, g.label_fits = Polygon(), None, 0.0, True
        name = p.name.strip()
        if not name:
            continue
        others = shapely.STRtree(placed) if placed else None
        cap = C.LABEL_CAP
        while True:
            hit = _best(g, lay.case.air, name, cap, holes, others, blockers, allowed, (ax0, ay0, ax1, ay1))
            if hit is not None or cap <= C.LABEL_MIN_CAP + 1e-6:
                break
            cap = max(C.LABEL_MIN_CAP, cap * 0.9)
        if hit is None:
            g.label_fits = False
            continue
        g.label, g.label_box, g.label_cap = hit[0], hit[1], cap
        placed.append(hit[1])


def _near(boxes, tree, d):
    """Mask: the boxes closer than d to anything in tree (an STRtree, or None for nothing). A tree query instead of
    the distance to the union of all pockets: 10x faster on a 9-pocket case (2026-11-07)."""
    near = np.zeros(len(boxes), bool)
    if tree is not None:
        near[tree.query(boxes, predicate="dwithin", distance=d)[0]] = True
    return near


def _best(g, air, name, cap, holes, others, blockers, allowed, abounds):
    t0 = S.text(name, 0, 0, cap)
    tx0, ty0, tx1, ty1 = t0.bounds
    along, across = tx1 - tx0, ty1 - ty0
    rect = g.rect.bounds
    p = g.pocket
    rows = []
    for rank, side in enumerate(side_order(p)):
        lo = rect[1] if side in ("left", "right") else rect[0]
        hi = rect[3] if side in ("left", "right") else rect[2]
        if side == p.notch_side:
            # right beside the finger notch, the text centred in the notch's depth
            prefer = lo + S.notch_centre(p, air)
            offsets = (max(C.TEXT_CUT, (C.NOTCH_OUT - across) / 2), C.TEXT_CUT, 2.5)
        else:
            prefer = (lo + hi) / 2
            offsets = (C.TEXT_CUT, C.LABEL_PAD, 2.5)
        c = _candidates(rect, side, along, across, prefer, offsets)
        rows.append(np.c_[c, np.full(len(c), rank)])
    cand = np.vstack(rows)
    boxes = shapely.box(cand[:, 0], cand[:, 1], cand[:, 2], cand[:, 3])
    ok = ~_near(boxes, holes, C.TEXT_CUT - 1e-6) & ~_near(boxes, others, C.TEXT_CUT - 1e-6)
    if blockers is not None and not blockers.is_empty:
        ok &= ~shapely.intersects(boxes, blockers)
    if not ok.any():
        return None
    inside = shapely.contains(allowed, boxes)
    ax0, ay0, ax1, ay1 = abounds
    grow = (np.maximum(0, ax0 - cand[:, 0]) + np.maximum(0, cand[:, 2] - ax1) +
            np.maximum(0, ay0 - cand[:, 1]) + np.maximum(0, cand[:, 3] - ay1))
    grow[inside] = 0.0
    # best: inside the board, preferred side, least growth, nearest the preferred spot, preferred offset
    key = np.lexsort((cand[:, 4], cand[:, 5], grow, cand[:, 6], grow > 1e-6, ~ok))
    i = key[0]
    x0, y0, x1, y1, _, _, rank = cand[i]
    side = side_order(g.pocket)[int(rank)]
    rot = 90 if side in ("left", "right") else 0
    t = affinity.rotate(t0, rot, origin=(0, 0)) if rot else t0
    bx0, by0, bx1, by1 = t.bounds
    t = affinity.translate(t, (x0 + x1) / 2 - (bx0 + bx1) / 2, (y0 + y1) / 2 - (by0 + by1) / 2)
    return t, shapely.box(x0, y0, x1, y1)
