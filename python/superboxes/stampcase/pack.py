"""Automatic pocket layout, after the first case: rows of upright pockets, the tallest stamps together. Three ways
to give every name room, tried in turn with every row length. The layout whose boards need the fewest sheets wins
(sheets.py: boards share a sheet when they fit), then the smallest board (names beside the notch win a near tie):
- "notch": every notch points the same way and each name sits beside its own notch, in the gap the notch needs anyway;
- "side" / "end": neighbours mirrored so their notches interlock in one gap, names in their own strip.
New and duplicated stamps go into free space without moving anything else.

Spacing rules (the same the layout checks): holes C.WEB apart; a name strip never on a hole or on another strip."""
import math

from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union

from . import config as C
from . import shapes as S
from . import sheets as SH
from .layout import auto_top_block, board_rect, mark_text, top_block_geo

MODES = ("notch", "side", "end")
NOT_NOTCH_PENALTY = 1.03   # a strip layout must beat names-beside-the-notch by more than 3 % of board area


def _set(p, side, end, x, y):
    p.notch_side, p.notch_end, p.x, p.y = side, end, x, y


def _group(ps, air):
    """(holes, name strips) of some pockets; a name beside its notch needs no strip of its own."""
    holes = unary_union([S.hole(p, air) for p in ps]) if ps else Polygon()
    strips = [S.strip(p, air) for p in ps if p.label_pos != "notch"]
    return holes, unary_union(strips) if strips else Polygon()


def _clear(a, b):
    """May group a sit where it is next to group b?"""
    (ha, sa), (hb, sb) = a, b
    if ha.is_empty or hb.is_empty:
        return True
    if ha.distance(hb) < C.WEB - 1e-6:
        return False
    for g, h in ((sa, hb), (ha, sb), (sa, sb)):
        if not g.is_empty and not h.is_empty and g.intersection(h).area > 1e-6:
            return False
    return True


def _shift(group, dx, dy):
    return tuple(affinity.translate(g, dx, dy) for g in group)


def _interlocks(a, b, air):
    """Can a's notch (right, near its bottom) and b's (left, near its top) share one gap, rows bottom-aligned?"""
    ha, hb = a.hole_size(air)[1], b.hole_size(air)[1]
    ca = min(C.NOTCH_FROM_END, ha / 2)
    cb = hb - min(C.NOTCH_FROM_END, hb / 2)
    return cb - ca >= 2 * C.NOTCH_SPAN + C.WEB


def _gap(a, b, interlocked):
    """Hole-to-hole gap between a (left) and b (right) in one row."""
    an, bn = a.notch_side == "right", b.notch_side == "left"
    if an and bn and interlocked:
        return C.NOTCH_OUT + C.WEB                # the two notches share the gap
    notch = C.NOTCH_OUT * (an + bn)
    strips = C.LABEL_STRIP * ((a.label_pos != "notch" and a.label_side() == "right") +
                              (b.label_pos != "notch" and b.label_side() == "left"))
    return max(C.WEB + notch, strips + notch)


def _row(pockets, air, mode):
    """Lay out one row at y = 0 from x = 0; returns its (holes, strips)."""
    pairs = [(pockets[k], pockets[k + 1]) for k in range(0, len(pockets) - 1, 2)]
    alternate = mode != "notch" and all(_interlocks(a, b, air) for a, b in pairs)
    for k, p in enumerate(pockets):
        p.label_pos = mode
        if alternate and k % 2:
            _set(p, "left", "high", 0.0, 0.0)
        else:
            _set(p, "right", "low", 0.0, 0.0)
    x = 0.0
    for k, p in enumerate(pockets):
        if k:
            x += _gap(pockets[k - 1], p, alternate)
        p.x = x
        x += p.hole_size(air)[0]
    # the analytic gaps never need more, but nudge if they do
    for k in range(1, len(pockets)):
        before = _group(pockets[:k], air)
        while not _clear(_group([pockets[k]], air), before):
            for q in pockets[k:]:
                q.x += 0.5
    return _group(pockets, air)


def _stack(rows):
    """Vertical offsets: each row as low as it goes while keeping clear of the rows below."""
    offsets, placed = [], None
    for g in rows:
        if placed is None:
            offsets.append(0.0)
            placed = g
            continue
        ok = lambda dy: _clear(_shift(g, 0, dy), placed)
        top = max(h.bounds[3] for h in placed if not h.is_empty)
        bottom = min(h.bounds[1] for h in g if not h.is_empty)
        dy = top - bottom + C.WEB
        steps = 0
        while steps < 40 and ok(dy - 1.0):
            dy -= 1.0
            steps += 1
        lo, hi = dy - 1.0, dy
        for _ in range(6):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if ok(mid) else (mid, hi)
        offsets.append(hi)
        moved = _shift(g, 0, hi)
        placed = tuple(unary_union([a, b]) for a, b in zip(placed, moved))
    return offsets


def _board_of(case, pockets):
    air = case.air
    mark = mark_text()
    holes, strips = _group(pockets, air)
    content = unary_union([S.footprint(p, air) for p in pockets])
    top = top_block_geo(case, *auto_top_block(case, content.bounds, mark), mark)
    extra = [(strips, C.TEXT_EDGE - C.TEXT_CUT)] if not strips.is_empty else []
    x0, y0, x1, y1 = board_rect(unary_union([holes, top.region]), extra)
    return x1 - x0, y1 - y0


def _sheets(case, w, h):
    """Sheets the case's boards take at w x h; a board too big for one goes last."""
    return SH.sheet_count(w, h, case.board_count) or math.inf


def repack(case):
    """Lay every pocket out fresh; the top board's block, the lid's title and logo and the magnets go back to auto."""
    air = case.air
    for p in case.pockets:
        if p.w > p.h:
            p.w, p.h = p.h, p.w
    order = sorted(case.pockets, key=lambda p: (-p.h, -p.w))
    best = None
    for mode in MODES:
        for per_row in range(1, len(order) + 1):
            rows = [order[i:i + per_row] for i in range(0, len(order), per_row)]
            geos = [_row(r, air, mode) for r in rows]
            offsets = _stack(geos)
            for r, dy in zip(rows, offsets):
                for p in r:
                    p.y += dy
            snapshot = [(p, p.notch_side, p.notch_end, p.label_pos, p.x, p.y) for p in order]
            w, h = _board_of(case, order)
            area = w * h * (1.0 if mode == "notch" else NOT_NOTCH_PENALTY)
            score = (_sheets(case, w, h), round(area), abs(w - h))
            if best is None or score < best[0]:
                best = (score, snapshot)
    if best:
        for p, side, end, label_pos, x, y in best[1]:
            _set(p, side, end, round(x, 3), round(y, 3))
            p.label_pos = label_pos
    case.top_block.placed = False
    case.lid_title.placed = case.lid_logo.placed = False
    case.magnets_auto = True
    case.magnets = []


def place_new(case, pocket, near=None):
    """Put `pocket` (already in case.pockets) into free space: next to an existing pocket, where the boards need
    the fewest sheets and grow least; ties go to the spot nearest `near` (the pocket it was duplicated from)."""
    air = case.air
    if pocket.w > pocket.h:
        pocket.w, pocket.h = pocket.h, pocket.w
    others = [p for p in case.pockets if p is not pocket]
    if not others:
        _set(pocket, "right", "low", 0.0, 0.0)
        return
    rest = _group(others, air)
    block = None
    if case.top_block.placed:
        tb = case.top_block
        block = top_block_geo(case, tb.x, tb.y, tb.size, tb.rot, mark_text()).region.buffer(C.BLOCK_WOOD)
    hw, hh = pocket.hole_size(air)
    nx, ny = near.centre(air) if near else (0.0, 0.0)
    best = None
    for o in others:
        fx0, fy0, fx1, fy1 = S.footprint(o, air).bounds
        starts = [((fx1 + C.WEB, o.y), (1, 0)), ((fx0 - C.WEB - hw, o.y), (-1, 0)),
                  ((o.x, fy1 + C.WEB), (0, 1)), ((o.x, fy0 - C.WEB - hh), (0, -1))]
        for (x, y), (dx, dy) in starts:
            for side, end in (("right", "low"), ("left", "high")):
                _set(pocket, side, end, x, y)
                for _ in range(40):
                    mine = _group([pocket], air)
                    if _clear(mine, rest) and (block is None or not mine[0].intersects(block)):
                        break
                    pocket.x += dx
                    pocket.y += dy
                else:
                    continue
                w, h = _board_of(case, case.pockets)
                cx, cy = pocket.centre(air)
                score = (_sheets(case, w, h), round(w * h), ((cx - nx) ** 2 + (cy - ny) ** 2) ** 0.5)
                if best is None or score < best[0]:
                    best = (score, (side, end, pocket.x, pocket.y))
    if best:
        _set(pocket, *best[1])
