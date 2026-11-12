"""Everything a case turns into: board, pockets, names, magnets, text blocks, the problems that block a build, and
the engraving and cut items of each board. The GUI draws a Layout, the build writes it."""
import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from ..export import mark_text  # noqa: F401 - the eVlaser maker's mark, the app's one definition (pack.py uses it)
from . import config as C
from . import labels as LB
from . import magnets as MG
from . import shapes as S
from . import sheets as SH
from .grid import FreeGrid
from evlaser import geom as G
from evlaser import machine as M
from evlaser import textures


@dataclass
class PocketGeo:
    pocket: object
    hole: Polygon
    rect: Polygon            # the hole without its notch
    strip: Polygon           # where auto layout keeps room for the name
    footprint: Polygon       # hole + strip: what auto layout spaces apart
    label: object = None     # B: the name next to its pocket, top pocket board (placed by labels.place)
    label_box: Polygon = None
    label_fits: bool = True
    lid_band: Polygon = None  # C: the lid's name, across the top end of the pocket's area
    lid_label: object = None
    base_label: object = None


@dataclass
class BlockGeo:
    polys: object = None     # text outlines
    lines: object = None     # logo strokes, hatch
    region: Polygon = None   # what it claims
    size: float = 0.0
    rot: int = 0
    x: float = 0.0
    y: float = 0.0


@dataclass
class Problem:
    level: str               # "error" blocks the build, "warning" doesn't
    text: str
    refs: list = field(default_factory=list)   # pocket ids, "magnet:<i>", "top_block", "lid_title", "lid_logo"


# ------------------------------------------------------------------ blocks
def top_block_parts(case, size, mark):
    """(kind, geometry, width) of the top board's block, laid out along X and centred on 0: logo, name, mark."""
    parts = []
    lh = size * C.LOGO_PER_CAP
    parts.append(("logo", lh, lh * S.logo_aspect(case.logo)))
    if case.project.strip():
        parts.append(("name", size, S.text_width(case.project, size, C.FONT_BOLD)))
    parts.append(("mark", C.MARK_CAP, S.text_width(mark, C.MARK_CAP, C.FONT_BOLD)))
    return parts


def top_block_extent(case, size, mark):
    """(length along the block, thickness across it)."""
    parts = top_block_parts(case, size, mark)
    gap = 0.6 * size
    return sum(w for _, _, w in parts) + gap * (len(parts) - 1), max(h for _, h, _ in parts)


def _block_region(length, thick, x, y, rot):
    region = box(-length / 2, -thick / 2, length / 2, thick / 2)
    if rot:
        region = affinity.rotate(region, rot, origin=(0, 0))
    return affinity.translate(region, x, y)


def top_block_region(case, x, y, size, rot, mark):
    """What the top board's block claims (top_block_geo's region), without drawing its text and logo."""
    return _block_region(*top_block_extent(case, size, mark), x, y, rot)


def top_block_geo(case, x, y, size, rot, mark):
    parts = top_block_parts(case, size, mark)
    gap = 0.6 * size
    length = sum(w for _, _, w in parts) + gap * (len(parts) - 1)
    cur = -length / 2
    polys, lines = [], []
    for kind, h, w in parts:
        cx = cur + w / 2
        if kind == "logo":
            lines.append(S.logo(case.logo, cx, 0, h))
        else:
            polys.append(S.text(case.project if kind == "name" else mark, cx, 0, h, C.FONT_BOLD))
        cur += w + gap
    polys, lines = unary_union(polys), unary_union(lines)
    region = _block_region(length, max(h for _, h, _ in parts), x, y, rot)
    if rot:
        polys, lines = (affinity.rotate(g, rot, origin=(0, 0)) for g in (polys, lines))
    polys, lines = (affinity.translate(g, x, y) for g in (polys, lines))
    return BlockGeo(polys, lines, region, size, rot, x, y)


def auto_top_block(case, content, mark):
    """Default spot of the top board's block: along the right side of the pockets when they stand taller than
    wide (like the first case's title), else under them; it shrinks to the side's length."""
    x0, y0, x1, y1 = content
    rot = 90 if (y1 - y0) >= (x1 - x0) else 0
    side = (y1 - y0) if rot else (x1 - x0)
    size = C.TOP_CAP
    while size > 3.0 and top_block_extent(case, size, mark)[0] > side:
        size *= 0.95
    _, thick = top_block_extent(case, size, mark)
    if rot:
        return (x1 + C.WEB + thick / 2, (y0 + y1) / 2, size, 90)
    return ((x0 + x1) / 2, y0 - C.WEB - thick / 2, size, 0)


def title_geo(case, x, y, size, rot=0):
    polys = S.text(case.project, x, y, size, C.FONT_BOLD, rot=rot)
    if polys.is_empty:
        return BlockGeo(polys, None, box(x - 1, y - 1, x + 1, y + 1), size, rot, x, y)
    hatch = textures.line_hatch(polys, C.TITLE_HATCH, angles=(45, -45))
    x0, y0, x1, y1 = polys.bounds
    return BlockGeo(polys, hatch, box(x0, y0, x1, y1), size, rot, x, y)


def logo_geo(case, x, y, size, rot=0):
    lines = S.logo(case.logo, x, y, size, rot=rot)
    w = size * S.logo_aspect(case.logo)
    if rot:
        w, size = size, w
    return BlockGeo(None, lines, box(x - w / 2, y - size / 2, x + w / 2, y + size / 2), size, rot, x, y)


# ------------------------------------------------------------------ board
def board_rect(content, extra=()):
    """Board rectangle around `content` with a rim of wood (C.RIM); `extra` = [(geometry, margin)] keep their own
    margin (names: C.TEXT_EDGE). Grown up and right until the cut corner keeps those margins too."""
    parts = [(content, C.RIM)] + [(g, m) for g, m in extra if g is not None and not g.is_empty]
    x0 = min(g.bounds[0] - m for g, m in parts)
    y0 = min(g.bounds[1] - m for g, m in parts)
    x1 = max(g.bounds[2] + m for g, m in parts)
    y1 = max(g.bounds[3] + m for g, m in parts)
    need = -1e9
    for g, m in parts:
        pts = np.array(shapely.get_coordinates(g))
        if len(pts):
            need = max(need, (pts[:, 0] + pts[:, 1]).max() + m * 2 ** 0.5)
    need += C.CORNER_CUT - (x1 + y1)
    if need > 0:
        x1 += need / 2
        y1 += need / 2
    return x0, y0, x1, y1


# ------------------------------------------------------------------ the layout
class Layout:
    def __init__(self, case, day=None):
        self.case = case
        self.mark = mark_text(day)
        self.problems = []
        air = case.air
        self.pockets = []
        for p in case.pockets:
            hw, hh = p.hole_size(air)
            hole = S.hole(p, air)
            strip = S.strip(p, air)
            self.pockets.append(PocketGeo(p, hole, G.rounded_rect(hw, hh, C.POCKET_R, p.x, p.y), strip,
                                          unary_union([hole, strip])))
        self.by_id = {g.pocket.id: g for g in self.pockets}

        # board: wraps the pockets and the top block
        if self.pockets:
            content = unary_union([g.footprint for g in self.pockets]).bounds
        else:
            content = (0.0, 0.0, 100.0, 60.0)
        tb = case.top_block
        if tb.placed:
            self.top = top_block_geo(case, tb.x, tb.y, tb.size, tb.rot, self.mark)
        else:
            self.top = top_block_geo(case, *auto_top_block(case, content, self.mark), self.mark)
        base = unary_union([g.hole for g in self.pockets] + [self.top.region])

        # names (B) go where there's room; the board then wraps holes, block and names
        manual = None if case.magnets_auto else [tuple(m) for m in case.magnets]
        blockers = [self.top.region.buffer(C.TEXT_CUT)]
        blockers += [Point(m).buffer(C.MAGNET_R + 0.5) for m in manual or []]
        LB.place(self, unary_union(blockers), S.board(*board_rect(base)).buffer(-C.TEXT_EDGE))
        names = [g.label_box for g in self.pockets if g.label_box is not None]
        self.rect = board_rect(base, [(unary_union(names), C.TEXT_EDGE)] if names else ())
        self.board = S.board(*self.rect)
        for g in self.pockets:
            self._names(g)

        # magnets
        self.magnets = MG.auto(self) if manual is None else manual

        # lid
        self.title, self.logo = self._lid_blocks()
        self._check()

    # -------------------------------------------------------------- board
    @property
    def size(self):
        x0, y0, x1, y1 = self.rect
        return x1 - x0, y1 - y0

    # -------------------------------------------------------------- names
    def _names(self, g):
        p = g.pocket
        name = p.name.strip()
        hw, hh = p.hole_size(self.case.air)
        # C: on the lid, horizontal across the top end of the pocket's area, so titles can use the rows' middles
        g.lid_band = box(p.x, p.y + hh - C.LABEL_STRIP, p.x + hw, p.y + hh)
        cap, _ = S.fit_cap(name, hw - 2 * C.LABEL_PAD, C.LABEL_CAP, C.LABEL_MIN_CAP)
        g.lid_label = S.text(name, p.x + hw / 2, p.y + hh - C.LABEL_STRIP / 2, cap)
        # A: on the base, inside the pocket, as large as fits (up to BASE_CAP), along the pocket's long side
        pad = C.BASE_PAD
        best = None
        for rot, length, across in ((0, hw, hh), (90, hh, hw)):
            c, _ok = S.fit_cap(name, length - 2 * pad, min(C.BASE_CAP, across - 2 * pad), C.LABEL_MIN_CAP)
            if best is None or c > best[1] + 0.25:
                best = (rot, c)
        rot, cap = best
        g.base_label = S.text(name, p.x + hw / 2, p.y + hh / 2, cap, rot=rot)

    # -------------------------------------------------------------- lid
    def _lid_free(self):
        """Lid area a title or logo may use: inside the rim, off the pocket names (C) and the magnets."""
        taken = [g.lid_band.buffer(C.BLOCK_WOOD) for g in self.pockets]
        taken += [Point(m).buffer(C.MAGNET_R + C.MAGNET_WOOD) for m in self.magnets]
        return self.board.buffer(-C.RIM).difference(unary_union(taken)) if taken else self.board.buffer(-C.RIM)

    def _lid_blocks(self):
        case = self.case
        t, l = case.lid_title, case.lid_logo
        if not (t.placed and l.placed):
            spot = self._find_lid_spot()
        title = title_geo(case, t.x, t.y, t.size, t.rot) if t.placed else title_geo(case, *spot["title"])
        logo = logo_geo(case, l.x, l.y, l.size, l.rot) if l.placed else logo_geo(case, *spot["logo"])
        return title, logo

    def _find_lid_spot(self):
        """Largest title that fits a free stretch of the lid, with the logo above it or beside it; along the
        board's long side when that gives the larger title."""
        case = self.case
        x0, y0, x1, y1 = self.rect
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        grid = FreeGrid(self._lid_free(), self.rect)
        aspect = S.logo_aspect(case.logo)
        per_cap = S.text_width(case.project, 1.0, C.FONT_BOLD) if case.project.strip() else 0.0
        # the title's real height per mm of cap: round letters (C, G, O, S) overshoot the cap height
        tall = S.text(case.project, 0, 0, 1.0, C.FONT_BOLD).bounds if per_cap else (0, 0, 0, 1.0)
        found = []
        for rot in (0, 90):
            length = (x1 - x0 if rot == 0 else y1 - y0) - 2 * C.RIM
            cap = min(C.TITLE_MAX_CAP, length / per_cap if per_cap else C.TITLE_MAX_CAP)
            while cap >= C.TITLE_MIN_CAP * 0.6:
                hit = self._try_lid(grid, cap, per_cap, max(1.0, tall[3] - tall[1]), aspect, rot, cx, cy)
                if hit:
                    found.append((cap * (1.0 if rot == 0 else 0.85), hit))   # horizontal wins unless clearly smaller
                    break
                cap *= 0.93
        if found:
            return max(found, key=lambda f: f[0])[1]
        cap = C.TITLE_MIN_CAP
        return {"title": (cx, cy - cap, cap, 0), "logo": (cx, cy + cap, cap * C.LOGO_PER_CAP, 0)}

    def _try_lid(self, grid, cap, per_cap, per_cap_h, aspect, rot, cx, cy):
        lh, tw, th = cap * C.LOGO_PER_CAP, per_cap * cap, per_cap_h * cap
        lw = lh * aspect
        # (along, across, logo offset, title offset) in the title's own frame: stacked, then side by side
        for gl, ga, lo, to in ((max(tw, lw), lh + 0.5 * cap + th, (0, (0.5 * cap + th) / 2), (0, -(lh + 0.5 * cap) / 2)),
                               (lw + 0.8 * cap + tw, max(lh, th), (-(0.8 * cap + tw) / 2, 0), ((lw + 0.8 * cap) / 2, 0))):
            gw, gh = (gl, ga) if rot == 0 else (ga, gl)
            spot = grid.rect_spot(gw, gh, cx, cy)
            if spot:
                x, y = spot
                if rot:   # turn the offsets with the block: (u, v) -> (-v, u)
                    lo, to = (-lo[1], lo[0]), (-to[1], to[0])
                return {"title": (x + to[0], y + to[1], cap, rot), "logo": (x + lo[0], y + lo[1], lh, rot)}
        return None

    # -------------------------------------------------------------- problems
    def _check(self):
        P = self.problems
        w, h = self.size
        if not SH.per_sheet(w, h):
            P.append(Problem("error", "Board %.1f x %.1f mm is larger than the sheet allows (%.1f x %.1f, either way "
                             "round)." % ((w, h) + SH.max_board())))
        for g in self.pockets:
            p = g.pocket
            if p.w <= 0 or p.h <= 0:
                P.append(Problem("error", "%s: width and height must be above 0." % _nm(p), [p.id]))
            if not p.name.strip():
                P.append(Problem("warning", "A pocket has no name.", [p.id]))
            elif not g.label_fits:
                P.append(Problem("error", "No room for the name of %s on the top board, even at %.1f mm: give it "
                                 "about %.0f mm of free wood along one side." % (
                                     _nm(p), C.LABEL_MIN_CAP, C.LABEL_MIN_CAP + 2 * C.TEXT_CUT + 1), [p.id]))
        depth = self.case.pocket_boards * C.THICKNESS
        thick = [g.pocket for g in self.pockets if g.pocket.thickness and g.pocket.thickness > depth + 1e-6]
        if thick:
            need = math.ceil(max(p.thickness for p in thick) / C.THICKNESS - 1e-6)
            for p in thick:
                P.append(Problem("error", "%s is %.1f mm thick, the pockets are %.1f mm deep: the lid won't close. "
                                 "Use %d pocket boards." % (_nm(p), p.thickness, depth, need), [p.id]))
        tree = shapely.STRtree([g.hole for g in self.pockets])
        for i, g in enumerate(self.pockets):
            for j in tree.query(g.hole.buffer(C.WEB)):
                if j <= i:
                    continue
                d = g.hole.distance(self.pockets[j].hole)
                if d < C.WEB - 0.01:
                    a, b = g.pocket, self.pockets[j].pocket
                    P.append(Problem("error", "Only %.1f mm of wood between %s and %s (need %.1f)."
                                     % (d, _nm(a), _nm(b), C.WEB), [a.id, b.id]))
        self._check_top()
        self._check_magnets()
        self._check_lid()
        if not self.case.project.strip():
            P.append(Problem("warning", "No project name: the lid has no title."))

    def _check_top(self):
        reg = self.top.region
        for g in self.pockets:
            if reg.distance(g.hole) < C.BLOCK_WOOD - 0.01 or (
                    g.label_box is not None and reg.distance(g.label_box) < C.BLOCK_WOOD - 0.01):
                self.problems.append(Problem("error", "The logo/name block on the top board touches %s." % _nm(g.pocket),
                                             ["top_block", g.pocket.id]))

    def _check_magnets(self):
        P = self.problems
        r, wood = C.MAGNET_R, C.MAGNET_WOOD
        edge = self.board.exterior
        if len(self.magnets) < 3:
            P.append(Problem("warning", "Only %d magnets: the lid may not hold." % len(self.magnets)))
        for i, m in enumerate(self.magnets):
            ref = "magnet:%d" % i
            pt = Point(m)
            if not self.board.contains(pt) or pt.distance(edge) < r + wood - 0.01:
                P.append(Problem("error", "Magnet %d is too close to the board's edge." % (i + 1), [ref]))
            for g in self.pockets:
                if pt.distance(g.hole) < r + wood - 0.01:
                    P.append(Problem("error", "Magnet %d is too close to %s." % (i + 1, _nm(g.pocket)), [ref, g.pocket.id]))
                elif g.label_box is not None and pt.distance(g.label_box) < r + 0.5 - 0.01:
                    P.append(Problem("error", "Magnet %d sits on the name of %s." % (i + 1, _nm(g.pocket)),
                                     [ref, g.pocket.id]))
            if pt.distance(self.top.region) < r + C.BLOCK_WOOD - 0.01:
                P.append(Problem("error", "Magnet %d sits on the top board's logo/name block." % (i + 1),
                                 [ref, "top_block"]))
            for j in range(i + 1, len(self.magnets)):
                if pt.distance(Point(self.magnets[j])) < 2 * r + wood - 0.01:
                    P.append(Problem("error", "Magnets %d and %d are too close." % (i + 1, j + 1),
                                     [ref, "magnet:%d" % j]))

    def _check_lid(self):
        P = self.problems
        inner = self.board.buffer(-C.RIM / 2)
        for key, geo, what in (("lid_title", self.title, "title"), ("lid_logo", self.logo, "logo")):
            if geo.region is None or (geo.polys is not None and geo.polys.is_empty and key == "lid_title"):
                continue
            if not inner.contains(geo.region):
                P.append(Problem("error", "The lid's %s runs off the board." % what, [key]))
            for g in self.pockets:
                if geo.region.distance(g.lid_band) < C.BLOCK_WOOD - 0.01:
                    P.append(Problem("error", "The lid's %s covers the name of %s." % (what, _nm(g.pocket)),
                                     [key, g.pocket.id]))
            for i, m in enumerate(self.magnets):
                if geo.region.distance(Point(m)) < C.MAGNET_R + C.MAGNET_WOOD - 0.01:
                    P.append(Problem("error", "The lid's %s covers magnet %d." % (what, i + 1), [key, "magnet:%d" % i]))
        if self.case.project.strip() and self.title.region.distance(self.logo.region) < C.BLOCK_WOOD - 0.01:
            P.append(Problem("error", "The lid's title and logo overlap.", ["lid_title", "lid_logo"]))

    @property
    def errors(self):
        return [p for p in self.problems if p.level == "error"]

    # -------------------------------------------------------------- boards to cut
    def pages(self):
        """[(key, title, items)] bottom to top. items = (role, layer, kind, *data) in design coordinates, before
        kerf; role is "outline", "hole" or "magnet" (cut) or "engrave"."""
        n = self.case.pocket_boards
        out = [("base", "Base", self._base())]
        for k in range(1, n + 1):
            key = "pocket%d" % k
            top = key == self.case.top_key
            title = "Top pocket board" if top else ("Pocket board %d" % k if n > 2 else "Lower pocket board")
            out.append((key, title, self._pocket_board(top)))
        out.append(("lid", "Lid", self._lid()))
        return out

    def _outline(self):
        return [("outline", M.CUT, "poly", self.board)]

    def _base(self):
        items = [("engrave", M.LINE, "poly", g.base_label) for g in self.pockets if not g.base_label.is_empty]
        return items + self._outline()

    def _pocket_board(self, top):
        items = []
        if top:
            items += [("engrave", M.LINE, "poly", g.label) for g in self.pockets if not g.label.is_empty]
            items += _block_items(self.top)
        items += [("hole", M.CUT, "poly", g.hole) for g in self.pockets]
        if top:
            items += [("magnet", M.CUT, "circle", m, C.MAGNET_R) for m in self.magnets]
        return items + self._outline()

    def _lid(self):
        items = [("engrave", M.LINE, "poly", g.lid_label) for g in self.pockets if not g.lid_label.is_empty]
        if self.case.project.strip():
            items += _block_items(self.title)
        items += _block_items(self.logo)
        items += [("magnet", M.CUT, "circle", m, C.MAGNET_R) for m in self.magnets]
        return items + self._outline()


def _block_items(b):
    out = []
    if b.polys is not None and not b.polys.is_empty:
        out.append(("engrave", M.LINE, "poly", b.polys))
    if b.lines is not None and not b.lines.is_empty:
        out.append(("engrave", M.LINE, "lines", b.lines))
    return out


def _nm(p):
    return '"%s"' % p.name.strip() if p.name.strip() else "a pocket without a name"
