"""Vector line textures: Voronoi cobbles, brick courses (top view + perspective faces), weeds, line hatch.

Everything returns shapely line geometry (LineString / MultiLineString) for the LINE layer.
"""
import math
import random

import numpy as np

from shapely import affinity
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point, box
from shapely.ops import linemerge, nearest_points, unary_union, voronoi_diagram

COBBLE = 3.5             # mean cobble size
BRICK_H = 2.2            # course height (top view)
BRICK_L = 5.5            # brick length
FACE_COURSES = 2         # brick courses visible on a wall face
LINE_W = 0.15            # engraved line width (laser spot) - lines are treated as areas this wide
SHADE_GAP = 0.6          # clear wood between two shading lines on a wall face
WEED_MASK = 0.35         # texture is cut back this far around weed strokes


def lines_of(g):
    """Flatten any geometry into a list of LineStrings."""
    if g is None or g.is_empty:
        return []
    t = g.geom_type
    if t == "LineString":
        return [g]
    if t == "LinearRing":
        return [LineString(g.coords)]
    if t in ("MultiLineString", "GeometryCollection"):
        return [ls for h in g.geoms for ls in lines_of(h)]
    if t == "Polygon":
        return [LineString(r.coords) for r in [g.exterior] + list(g.interiors)]
    if t == "MultiPolygon":
        return [ls for h in g.geoms for ls in lines_of(h)]
    return []


def multiline(parts, min_len=0.15):
    ls = [l for p in parts for l in lines_of(p) if l.length >= min_len]
    if not ls:
        return MultiLineString()
    merged = linemerge(MultiLineString(ls))
    return MultiLineString([l for l in lines_of(merged) if l.length >= min_len])


def scaled(g, s):
    return affinity.scale(g, s, s, origin=(0, 0))


# ---------------------------------------------------------------- cobbles
def cobbles(region, rng, size=COBBLE, relax=3):
    """Voronoi joint lines inside `region` (single shared lines). Random seeds, lightly relaxed:
    even stone sizes without the honeycomb look."""
    if region.is_empty:
        return MultiLineString()
    x0, y0, x1, y1 = region.bounds
    pad = size * 1.5
    env = box(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    n = int((x1 - x0 + 2 * pad) * (y1 - y0 + 2 * pad) / (size * size * 0.87))
    pts = [(rng.uniform(x0 - pad, x1 + pad), rng.uniform(y0 - pad, y1 + pad)) for _ in range(n)]
    for _ in range(relax):
        cells = voronoi_diagram(MultiPoint(pts), envelope=env)
        pts = []
        for c in cells.geoms:
            c = c.intersection(env)
            if not c.is_empty:
                pts.append((c.centroid.x, c.centroid.y))
    cells = voronoi_diagram(MultiPoint(pts), envelope=env)
    edges = unary_union([c.boundary for c in cells.geoms])
    return edges.intersection(region.buffer(-0.08))


# ------------------------------------------------------------ brick rows
def _joints_on_rows(base_region, area, n_rows, row_h, rng, start=0.0, join="round"):
    """Head joints for courses offset outward from base_region, clipped to area.
    Joints sit on the mid line of each row, perpendicular to it, staggered per row."""
    out = []
    bnd = base_region.boundary
    for i in range(n_rows):
        mid = base_region.buffer(start + (i + 0.5) * row_h, join_style=join).boundary.intersection(area)
        off0 = (BRICK_L / 2) * (i % 2) + rng.uniform(0, 0.6)
        for ml in lines_of(mid):
            d = off0
            while d < ml.length:
                m = ml.interpolate(d + rng.uniform(-0.3, 0.3))
                f = nearest_points(bnd, m)[0]
                vx, vy = m.x - f.x, m.y - f.y
                n = math.hypot(vx, vy)
                if n > 1e-6:
                    vx, vy = vx / n * row_h / 2, vy / n * row_h / 2
                    seg = LineString([(m.x - vx, m.y - vy), (m.x + vx, m.y + vy)]).intersection(area)
                    out.append(seg)
                d += BRICK_L
    return out


def brick_top(floor_k, top, rng, row_h=BRICK_H):
    """Top view bricks on wall tops: courses offset from the (perspective-scaled) floor outline."""
    if top.is_empty:
        return MultiLineString()
    far = max(abs(v) for v in top.bounds) * 2
    n_rows = int(far / row_h) + 1
    courses = [floor_k.buffer(i * row_h).boundary.intersection(top) for i in range(1, n_rows)]
    joints = _joints_on_rows(floor_k, top, n_rows, row_h, rng)
    return multiline(courses + joints)


def brick_face(base_lines, faces, k, rng, courses=FACE_COURSES):
    """Side view bricks on wall faces in central perspective (camera above the tile centre).
    Height z in 0..1 maps to radial scale s(z) = H / (H - z) with s(1) = k."""
    H = k / (k - 1)

    def s(z):
        return H / (H - z)

    area = faces.buffer(0.02)
    out, joints = [], []
    for c in range(1, courses):
        out.append(scaled(base_lines, s(c / courses)).intersection(area))
    for c in range(courses):
        s0, s1 = s(c / courses), s((c + 1) / courses)
        for bl in lines_of(base_lines):
            d = (BRICK_L / 2) * (c % 2) + rng.uniform(0, 0.6)
            while d < bl.length:
                p = bl.interpolate(d + rng.uniform(-0.3, 0.3))
                joints += lines_of(LineString([(p.x * s0, p.y * s0), (p.x * s1, p.y * s1)]).intersection(area))
                d += BRICK_L
    shade = face_shading(base_lines, area, k, joints)
    return multiline(out + joints + shade)


def face_shading(base_lines, area, k, obstacles, step=0.1, min_len=0.8):
    """Shading lines on wall faces, rising perpendicular from the floor joint across the face band.
    Each line is treated as an area LINE_W wide; between areas there is at least SHADE_GAP of clear wood.
    Candidates are tried every `step` mm along the floor joint; a candidate is trimmed where it would come
    closer than the gap to an accepted shading line (converging corners, rondel arcs) or to a head joint
    running nearly parallel (crossing joints are fine), and dropped when less than `min_len` survives.
    That gives dynamic spacing: even where the face is straight, thinned where lines converge, never touching."""
    clear = SHADE_GAP + LINE_W + 0.01   # centre line to centre line (+ margin for buffer approximation)
    cell = 2.0
    grid = {}

    def keys(b):
        for i in range(int(math.floor((b[0] - clear) / cell)), int(math.floor((b[2] + clear) / cell)) + 1):
            for j in range(int(math.floor((b[1] - clear) / cell)), int(math.floor((b[3] + clear) / cell)) + 1):
                yield (i, j)

    def direction(g):
        (x0, y0), (x1, y1) = g.coords[0], g.coords[-1]
        return math.atan2(y1 - y0, x1 - x0)

    def add(g, always_blocks):
        item = (g, g.buffer(clear, cap_style="round"), always_blocks, direction(g))
        for kk in keys(g.bounds):
            grid.setdefault(kk, []).append(item)

    def near_parallel(a, b, limit=math.radians(35)):
        d = abs(a - b) % math.pi
        return min(d, math.pi - d) < limit

    for g in obstacles:
        add(g, False)
    reach = (k - 1) * max(abs(v) for v in area.bounds) + 1.0
    out = []
    for bl in lines_of(base_lines):
        d = 0.0
        while d <= bl.length:
            p = bl.interpolate(d)
            q = bl.interpolate(min(d + 0.05, bl.length)) if d + 0.05 <= bl.length else bl.interpolate(d - 0.05)
            d += step
            tx, ty = q.x - p.x, q.y - p.y
            tn = math.hypot(tx, ty)
            if tn < 1e-9:
                continue
            nx, ny = -ty / tn, tx / tn
            if not area.contains(Point(p.x + nx * 0.3, p.y + ny * 0.3)):
                nx, ny = -nx, -ny
            cand = LineString([(p.x, p.y), (p.x + nx * reach, p.y + ny * reach)]).intersection(area)
            if cand.is_empty:
                continue
            near = {id(it): it for kk in keys(cand.bounds) for it in grid.get(kk, ())}.values()
            a = math.atan2(ny, nx)
            blocking = [buf for g, buf, always, ga in near
                        if (always or near_parallel(a, ga)) and g.distance(cand) < clear]
            if blocking:
                cand = cand.difference(unary_union(blocking))
            # a shading line must rise from the floor joint; free upper fragments would read as dashes
            pieces = [l for l in lines_of(cand) if l.length >= min_len and l.distance(p) < 0.05]
            if not pieces:
                continue
            piece = pieces[0]
            out.append(piece)
            add(piece, True)
    return out


def brick_band(inner_region, band, rng, row_h, start, n_rows):
    """Bricks in a band (frame): n_rows courses offset from inner_region, mitred corners."""
    courses = [inner_region.buffer(start + i * row_h, join_style="mitre").boundary.intersection(band)
               for i in range(1, n_rows)]
    joints = _joints_on_rows(inner_region, band, n_rows, row_h, rng, start, "mitre")
    return multiline(courses + joints)


# --------------------------------------------------------------- hatching
def _ring_edges(region):
    """(P0, P1): every edge of every ring of a (Multi)Polygon as two (n, 2) arrays."""
    polys = list(region.geoms) if hasattr(region, "geoms") else [region]
    a, b = [], []
    for p in polys:
        if p.is_empty:
            continue
        for ring in [p.exterior] + list(p.interiors):
            c = np.asarray(ring.coords)[:, :2]
            a.append(c[:-1])
            b.append(c[1:])
    if not a:
        return np.empty((0, 2)), np.empty((0, 2))
    return np.concatenate(a), np.concatenate(b)


def line_hatch(region, spacing, angles=(45, -45)):
    """Parallel lines `spacing` apart at each angle, clipped to `region`. A scanline: each line meets the ring edges
    at sorted points and runs inside between pairs (even-odd), all lines of an angle in one numpy pass. Same lines as
    intersecting each one with the region, about 50x faster on a lid title (superboxespy, 2026-11-07)."""
    out = []
    if region is None or region.is_empty:
        return MultiLineString()
    cx, cy = region.centroid.x, region.centroid.y
    r = max(region.bounds[2] - region.bounds[0], region.bounds[3] - region.bounds[1])
    p0, p1 = _ring_edges(region)
    for a in angles:
        t = math.radians(a)
        dx, dy = math.cos(t), math.sin(t)
        nx, ny = -dy, dx
        ks = []
        k = -r
        while k <= r:                       # the same offsets as stepping line by line
            ks.append(k)
            k += spacing
        ks = np.asarray(ks)
        # edges in the line's frame: u along the lines, v across (line k is v == k)
        u0 = (p0[:, 0] - cx) * dx + (p0[:, 1] - cy) * dy
        u1 = (p1[:, 0] - cx) * dx + (p1[:, 1] - cy) * dy
        v0 = (p0[:, 0] - cx) * nx + (p0[:, 1] - cy) * ny
        v1 = (p1[:, 0] - cx) * nx + (p1[:, 1] - cy) * ny
        cross = (v0[None, :] <= ks[:, None]) != (v1[None, :] <= ks[:, None])     # half-open: each vertex once
        li, ei = np.nonzero(cross)
        if not len(li):
            continue
        dv = v1[ei] - v0[ei]
        u = u0[ei] + (ks[li] - v0[ei]) * (u1[ei] - u0[ei]) / dv
        order = np.lexsort((u, li))
        li, u = li[order], u[order]
        for line in np.unique(li):
            us = np.clip(u[li == line], -r, r)
            ox, oy = cx + nx * ks[line], cy + ny * ks[line]
            for s, e in zip(us[0::2], us[1::2]):
                if e > s:
                    out.append(LineString([(ox + dx * s, oy + dy * s), (ox + dx * e, oy + dy * e)]))
    return multiline(out)


# ------------------------------------------------------------------ weeds
def _bend_stroke(x, y, a, length, bend, steps=8):
    pts = [(x, y)]
    for i in range(steps):
        a += bend / steps
        x += math.cos(a) * length / steps
        y += math.sin(a) * length / steps
        pts.append((x, y))
    return LineString(pts)


def _blade(x, y, a, length, bend, width, steps=10):
    """Closed, tapering, curved grass blade outline."""
    spine = _bend_stroke(x, y, a, length, bend, steps).coords
    left, right = [], []
    for i in range(len(spine) - 1):
        (x0, y0), (x1, y1) = spine[i], spine[i + 1]
        n = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = -(y1 - y0) / n, (x1 - x0) / n
        w = width / 2 * (1 - i / (len(spine) - 1)) ** 0.8
        left.append((x0 + nx * w, y0 + ny * w))
        right.append((x0 - nx * w, y0 - ny * w))
    return LineString(left + [spine[-1]] + right[::-1] + [left[0]])


def grass_tuft(rng):
    """Arching blade outlines fanning out of a root at (0,0), growing towards +y."""
    out = []
    n = rng.randint(4, 6)
    for i in range(n):
        spread = -60 + 120 * (i + rng.uniform(0.2, 0.8)) / n
        a = math.radians(90 + spread)
        bend = math.radians(spread * 0.6 + rng.uniform(-10, 10))
        out.append(_blade(rng.uniform(-0.4, 0.4), 0, a, rng.uniform(3.0, 5.5), bend, rng.uniform(0.55, 0.75)))
    return out


def _leaf(length, width, teeth, a, x0=0.0, y0=0.0):
    """Closed leaf outline from (x0,y0) pointing at angle a; serrated, or smooth when teeth == 0."""
    pts_l, pts_r = [], []
    steps = teeth * 2 if teeth else 10
    for i in range(steps + 1):
        t = i / steps
        w = width * math.sin(math.pi * t) * ((1.0 if i % 2 else 0.55) if teeth else 1.0)
        pts_l.append((t * length, w))
        pts_r.append((t * length, -w))
    pts = pts_l + pts_r[::-1][1:]
    ca, sa = math.cos(a), math.sin(a)
    return LineString([(x0 + ca * x - sa * y, y0 + sa * x + ca * y) for x, y in pts])


def dandelion(rng):
    """Top-view rosette of serrated leaves around (0,0)."""
    n = rng.randint(6, 8)
    a0 = rng.uniform(0, math.tau)
    return [_leaf(rng.uniform(2.4, 3.6), rng.uniform(0.45, 0.65), rng.randint(3, 4), a0 + math.tau * i / n
                  + rng.uniform(-0.2, 0.2)) for i in range(n)]


def creeper(rng):
    """Stem along +x with alternating small leaves."""
    length = rng.uniform(5.0, 7.0)
    stem = _bend_stroke(0, 0, math.radians(rng.uniform(-10, 10)), length, math.radians(rng.uniform(-30, 30)), 12)
    out = [stem]
    d, side = 0.9, 1
    while d < length - 0.4:
        p = stem.interpolate(d)
        q = stem.interpolate(min(d + 0.1, stem.length))
        a = math.atan2(q.y - p.y, q.x - p.x) + side * math.radians(55)
        out.append(_leaf(rng.uniform(1.4, 1.9), 0.5, 0, a, p.x, p.y))
        d += rng.uniform(1.1, 1.4)
        side = -side
    return out


WEEDS = [grass_tuft, dandelion, creeper]


def place(strokes, x, y, angle):
    """Rotate weed strokes so local +y points along `angle`, then move the root to (x, y)."""
    return [affinity.translate(affinity.rotate(s, math.degrees(angle) - 90, origin=(0, 0)), x, y) for s in strokes]
