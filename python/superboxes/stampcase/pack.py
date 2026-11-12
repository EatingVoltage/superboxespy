"""Automatic pocket layout, after the first case: rows of upright pockets, the tallest stamps together. Three ways
to give every name room, tried in turn with every row length. The layout whose boards need the fewest sheets wins
(sheets.py: boards share a sheet when they fit), then the smallest board (names beside the notch win a near tie):
- "notch": every notch points the same way and each name sits beside its own notch, in the gap the notch needs anyway;
- "side" / "end": neighbours mirrored so their notches interlock in one gap, names in their own strip.
New and duplicated stamps go into free space without moving anything else.

Spacing rules (the same the layout checks): holes C.WEB apart; a name strip never on a hole or on another strip."""
import math

import shapely
from shapely import affinity
from shapely.geometry import GeometryCollection, Polygon
from shapely.ops import unary_union

from . import config as C
from . import shapes as S
from . import sheets as SH
from .layout import auto_top_block, board_rect, mark_text, top_block_region

MODES = ("notch", "side", "end")
NOT_NOTCH_PENALTY = 1.03   # a strip layout must beat names-beside-the-notch by more than 3 % of board area


def _set(p, side, end, x, y):
    p.notch_side, p.notch_end, p.x, p.y = side, end, x, y


def _group(ps, air):
    """(holes, name strips) of some pockets; a name beside its notch needs no strip of its own."""
    if len(ps) == 1:
        p = ps[0]
        return S.hole(p, air), S.strip(p, air) if p.label_pos != "notch" else Polygon()
    holes = unary_union([S.hole(p, air) for p in ps]) if ps else Polygon()
    strips = [S.strip(p, air) for p in ps if p.label_pos != "notch"]
    return holes, unary_union(strips) if strips else Polygon()


def _box_gap(a, b):
    """How far apart two bounding boxes are (0 when they touch or overlap): no point of the shapes is nearer."""
    return math.hypot(max(b[0] - a[2], a[0] - b[2], 0.0), max(b[1] - a[3], a[1] - b[3], 0.0))


def _box_overlap(a, b):
    """The area two bounding boxes share: the shapes in them can't share more."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _clear(a, b):
    """May group a sit where it is next to group b? The bounding boxes answer most asks without the geometry (exactly:
    a box gap of WEB means the holes are at least that far apart, boxes that share no area hold shapes that share
    none)."""
    (ha, sa), (hb, sb) = a, b
    if ha.is_empty or hb.is_empty:
        return True
    if _box_gap(ha.bounds, hb.bounds) < C.WEB - 1e-6 and ha.distance(hb) < C.WEB - 1e-6:
        return False
    for g, h in ((sa, hb), (ha, sb), (sa, sb)):
        if (not g.is_empty and not h.is_empty and _box_overlap(g.bounds, h.bounds) > 1e-6
                and g.intersection(h).area > 1e-6):
            return False
    return True


class _Others:
    """Other pockets (at least one) to ask _clear's question of many times: may a group sit next to all of them? Each
    ask looks at the pieces near the group only. Against their union, _clear's bounding-box test never answered (the
    union's box holds every spot next to them) and every ask measured the exact distance to all of them: most of an
    Add on a big case (2026-11-12)."""

    def __init__(self, ps, air):
        self.holes = [S.hole(p, air) for p in ps]
        self.strips = [S.strip(p, air) for p in ps if p.label_pos != "notch"]
        self.htree = shapely.STRtree(self.holes)
        self.stree = shapely.STRtree(self.strips) if self.strips else None

    def clear(self, group):
        """_clear(group, (the holes' union, the strips' union))."""
        h, s = group
        if h.is_empty:
            return True
        if len(self.htree.query(h, predicate="dwithin", distance=C.WEB - 1e-6)):
            return False
        return not any(_overlaps(g, tree, pieces) for g, tree, pieces in (
            (s, self.htree, self.holes), (h, self.stree, self.strips), (s, self.stree, self.strips)))


def _overlaps(g, tree, pieces):
    """Does g share area (as _clear counts it) with the union of `pieces` (in `tree`)? Only those it touches count."""
    if g.is_empty or tree is None:
        return False
    hit = tree.query(g, predicate="intersects")
    if not len(hit):
        return False
    other = pieces[hit[0]] if len(hit) == 1 else unary_union([pieces[i] for i in sorted(hit)])
    return g.intersection(other).area > 1e-6


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


def _row_x(pockets, air, mode):
    """One row's notches and name places, and x from the analytic gaps, at y = 0 from x = 0; returns where its last
    hole ends."""
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
    return x


def _row(pockets, air, mode):
    """Lay out one row at y = 0 from x = 0; returns its (holes, strips)."""
    _row_x(pockets, air, mode)
    # the analytic gaps never need more, but nudge if they do: each pocket against each one before it (the same as
    # against their union, without building it per pocket)
    done = []
    for k, p in enumerate(pockets):
        g = _group([p], air)
        while k and not all(_clear(g, q) for q in done):
            for q in pockets[k:]:
                q.x += 0.5
            g = _group([p], air)
        done.append(g)
    return _group(pockets, air)


def _stack(rows, groups, air):
    """Move each row (its pockets at y = 0, `groups` their (holes, strips) from _row) up, as low as it goes while
    keeping clear of the rows below."""
    for k, (r, g) in enumerate(zip(rows, groups)):
        if not k:
            continue
        below = _Others([p for q in rows[:k] for p in q], air)
        ok = lambda dy: below.clear(_shift(g, 0, dy))
        top = float(shapely.total_bounds(below.holes + below.strips)[3])
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
        for p in r:
            p.y += hi


def _board_of(case, pockets):
    """The board's size for these pockets. board_rect reads only bounds and the largest x + y, the same for a plain
    collection of the shapes as for their union, so none is built (the unions were a third of a Re-pack), and of
    the top block only the region it claims."""
    air = case.air
    mark = mark_text()
    holes = [S.hole(p, air) for p in pockets]
    every_strip = [S.strip(p, air) for p in pockets]
    strips = [g for p, g in zip(pockets, every_strip) if p.label_pos != "notch"]
    content = tuple(shapely.total_bounds(holes + every_strip).tolist())     # the footprints' bounds
    top = top_block_region(case, *auto_top_block(case, content, mark), mark)
    extra = [(GeometryCollection(strips), C.TEXT_EDGE - C.TEXT_CUT)] if strips else []
    x0, y0, x1, y1 = board_rect(GeometryCollection(holes + [top]), extra)
    return x1 - x0, y1 - y0


def _sheets(case, w, h):
    """Sheets the case's boards take at w x h; a board too big for one goes last."""
    return SH.sheet_count(w, h, case.board_count) or math.inf


def _least_board(order, per_row, mode, air):
    """(width, height) the board of rows of `per_row` pockets can't come out below: each row as long as its analytic
    gaps make it (_row only ever nudges further apart), and each row's first pocket (at x = 0, so straight edges
    over straight edges) at least WEB above the row below's first one (_stack); RIM all round. None for pockets too
    small for that (a hole no wider than its corners). Sets the pockets' notches and x as _row does."""
    rows = [order[i:i + per_row] for i in range(0, len(order), per_row)]
    if any(min(p.hole_size(air)) <= 2 * C.POCKET_R + 1e-6 for p in order):
        return None
    return (max(_row_x(r, air, mode) for r in rows) + 2 * C.RIM - 1e-3,
            sum(r[0].hole_size(air)[1] for r in rows) + (len(rows) - 1) * (C.WEB - 1e-6) + 2 * C.RIM - 1e-3)


def _least_score(case, order, per_row, mode):
    """The (sheets, area) of the score a layout can't come out below: those of its least board (fewer sheets and
    less area than any real one: sheets only grow with the board)."""
    least = _least_board(order, per_row, mode, case.air)
    if least is None:
        return (0, 0)
    w, h = least
    return (_sheets(case, w, h), round(w * h * (1.0 if mode == "notch" else NOT_NOTCH_PENALTY)))


def repack(case):
    """Lay every pocket out fresh; the top board's block, the lid's title and logo and the magnets go back to auto.
    Every mode with every row length competes: the best score wins, the first of them (MODES, then row length) on
    a tie. They're laid out most promising first, and once the least a layout could score is worse than the best
    so far, it and the rest can't win and aren't laid out (most of a big Re-pack was layouts that couldn't fit a
    sheet, 2026-11-12)."""
    air = case.air
    for p in case.pockets:
        if p.w > p.h:
            p.w, p.h = p.h, p.w
    order = sorted(case.pockets, key=lambda p: (-p.h, -p.w))
    runs = sorted((_least_score(case, order, per_row, mode), i, mode, per_row)
                  for i, (mode, per_row) in enumerate((m, n) for m in MODES for n in range(1, len(order) + 1)))
    best = None
    for least, i, mode, per_row in runs:
        if best is not None and least > best[0][:2]:
            break
        rows = [order[k:k + per_row] for k in range(0, len(order), per_row)]
        _stack(rows, [_row(r, air, mode) for r in rows], air)
        snapshot = [(p, p.notch_side, p.notch_end, p.label_pos, p.x, p.y) for p in order]
        w, h = _board_of(case, order)
        area = w * h * (1.0 if mode == "notch" else NOT_NOTCH_PENALTY)
        score = (_sheets(case, w, h), round(area), abs(w - h))
        if best is None or (score, i) < best[:2]:
            best = (score, i, snapshot)
    if best:
        for p, side, end, label_pos, x, y in best[2]:
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
    rest = _Others(others, air)
    block = None
    if case.top_block.placed:
        tb = case.top_block
        block = top_block_region(case, tb.x, tb.y, tb.size, tb.rot, mark_text()).buffer(C.BLOCK_WOOD)
    hw, hh = pocket.hole_size(air)
    nx, ny = near.centre(air) if near else (0.0, 0.0)
    best = None
    for o in others:
        fx0, fy0, fx1, fy1 = S.footprint_bounds(o, air)
        starts = [((fx1 + C.WEB, o.y), (1, 0)), ((fx0 - C.WEB - hw, o.y), (-1, 0)),
                  ((o.x, fy1 + C.WEB), (0, 1)), ((o.x, fy0 - C.WEB - hh), (0, -1))]
        for (x, y), (dx, dy) in starts:
            for side, end in (("right", "low"), ("left", "high")):
                _set(pocket, side, end, x, y)
                for _ in range(40):
                    mine = _group([pocket], air)
                    if rest.clear(mine) and (block is None or not mine[0].intersects(block)):
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
