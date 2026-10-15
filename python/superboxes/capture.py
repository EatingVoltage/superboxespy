"""Run a boxes.py generator and capture its parts as clean geometry on the eatingVoltage layers.

boxes.py draws every part with a pen colour; this maps those colours onto the user's fixed layers:
    black (outer cut), blue (inner cut), magenta/yellow/white (extra cuts)  -> CUT  (red C02)
    green (etching), cyan (deep etching)                                   -> LINE (blue C01)
    red (annotations: part labels, guide lines)                            -> T1   (never output)
Each part comes back normalised to its own bounding box (lower-left = 0,0), Y up, in mm, with:
    subpaths  [(start, [(c1|None, c2|None, end)], closed)]  per layer - true Beziers, the evlaser 'bez' format
    labels    [(text, x, y, size, align)]                   - the generator's part labels
    shape     shapely Polygon of the cut part (outer contour minus holes), burn removed - for 3D and checks
"""
import inspect
import math

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import MultiLineString, MultiPolygon, Point, Polygon
from shapely.ops import linemerge, unary_union

from boxes.drawing import Context, Surface

from . import catalog
from evlaser import machine as M

CUT, LINE, REF = M.CUT, M.LINE, M.REF
EPS = 1e-4


def _layer(rgb):
    r, g, b = rgb.red, rgb.green, rgb.blue
    if (r, g, b) == (255, 0, 0):
        return REF
    if (r, g, b) in ((0, 255, 0), (0, 255, 255)):
        return LINE
    return CUT


class _Capture(Surface):
    """A surface that keeps the parts as drawn (Y up, no padding) instead of writing a file."""
    invert_y = False


class Part:
    def __init__(self, index):
        self.index = index
        self.name = "part %d" % (index + 1)
        self.subpaths = {CUT: [], LINE: [], REF: []}
        self.labels = []
        self.shape = None       # cut region without the burn: the part as designed (3D, checks)
        self._outline = None
        self._outline_from_cuts = False
        self.w = self.h = 0.0
        self.walls = []         # where the part was drawn: rect / poly / strip / move records (_record_walls)
        self.comp = None        # (bx, by) per-axis burn for this part, if it differs from the material's (fit comb)
        self.children = []      # loose pieces cut out of this part's holes (hinge discs), for the 3D

    @property
    def outline(self):
        """Cut region as cut, burn included: spacing on the sheet. Only the export needs it, so it's made then."""
        if self._outline is None and self._outline_from_cuts:
            self._outline = _shape(self.subpaths[CUT], 0)
        return self._outline

    @outline.setter
    def outline(self, g):
        self._outline = g

    def to_json(self):
        return {
            "index": self.index, "name": self.name, "w": round(self.w, 4), "h": round(self.h, 4),
            "paths": {str(k): [_sub_json(s) for s in v] for k, v in self.subpaths.items() if v},
            "labels": [{"text": t, "x": x, "y": y, "size": s, "align": a} for t, x, y, s, a in self.labels],
            "shape": _poly_json(self.shape),
            "area": round(self.shape.area, 2) if self.shape is not None else 0.0,
            "children": [_poly_json(c) for c in self.children],
            "walls": [dict({"kind": w["kind"], "x": _r(w["x"]), "y": _r(w["y"]), "edges": w["edges"],
                            "label": w["label"], "frame": [_r(v) for v in w["frame"]]},
                           **({"borders": w["borders"]} if "borders" in w else {})) for w in self.walls],
        }


def _r(v):
    return round(v, 4)


def _sub_json(sub):
    # all numbers rounded in one numpy call, then cut back into segments: per-number round() was a third of a build
    start, segs, closed = sub
    flat = list(start)
    for c1, c2, e in segs:
        if c1 is None:
            flat += e
        else:
            flat += (*c1, *c2, *e)
    vals = np.round(np.asarray(flat, float), 4).tolist()
    out, k = [], 2
    for c1, _c2, _e in segs:
        n = 2 if c1 is None else 6
        out.append(vals[k:k + n])
        k += n
    return {"start": vals[:2], "segs": out, "closed": closed}


def _ring_json(ring):
    return np.round(np.asarray(ring.coords)[:-1, :2], 4).tolist()


def _poly_json(poly):
    if poly is None or poly.is_empty:
        return None
    polys = list(poly.geoms) if hasattr(poly, "geoms") else [poly]
    return [{"outer": _ring_json(p.exterior), "holes": [_ring_json(r) for r in p.interiors]} for p in polys]


def flatten(sub, steps=8):
    """Subpath -> list of points (Beziers sampled with `steps` segments)."""
    start, segs, _closed = sub
    pts = [start]
    cur = start
    for c1, c2, e in segs:
        if c1 is None:
            pts.append(e)
        else:
            for k in range(1, steps + 1):
                t = k / steps
                mt = 1 - t
                pts.append((mt ** 3 * cur[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * e[0],
                            mt ** 3 * cur[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * e[1]))
        cur = e
    return pts


def _subpaths(path):
    """boxes.py path commands -> subpaths. 'C' stores the end point first, then both control points."""
    subs, start, segs, cur = [], None, [], None
    for c in path.path:
        op = c[0]
        if op == "M":
            if start is not None and segs:
                subs.append((start, segs))
            start, segs, cur = (c[1], c[2]), [], (c[1], c[2])
        elif op == "L":
            if start is None:
                start = cur = (c[1], c[2])
                continue
            segs.append((None, None, (c[1], c[2])))
            cur = (c[1], c[2])
        elif op == "C":
            segs.append(((c[3], c[4]), (c[5], c[6]), (c[1], c[2])))
            cur = (c[1], c[2])
    if start is not None and segs:
        subs.append((start, segs))
    out = []
    for start, segs in subs:
        end = segs[-1][2]
        closed = abs(end[0] - start[0]) < EPS and abs(end[1] - start[1]) < EPS
        out.append((start, segs, closed))
    return out


def _texts(path):
    out = []
    for c in path.path:
        if c[0] != "T":
            continue
        m, text, params = c[3], c[4], c[5]
        if not text.strip():
            continue
        fs = params.get("fs", 4)
        align = {"middle": "center", "end": "right"}.get(params.get("align", "left"), "left")
        out.append((text, m.c, m.f, fs, align))
    return out


def _move(sub, dx, dy):
    start, segs, closed = sub
    t = lambda p: (p[0] + dx, p[1] + dy) if p is not None else None
    return (t(start), [(t(c1), t(c2), t(e)) for c1, c2, e in segs], closed)


def _rings(subs):
    """Closed rings of a part's cut contours. Some generators draw an outline as separate open edges (TrayLayout's
    base plate), so open subpaths are joined end to end (on a 1 µm grid) into rings first."""
    rings = [flatten(s, 6) for s in subs if s[2]]
    opens = [flatten(s, 6) for s in subs if not s[2]]
    if opens:
        snap = lambda pts: [(round(x, 3), round(y, 3)) for x, y in pts]
        merged = linemerge(MultiLineString([snap(o) for o in opens if len(o) > 1]))
        for ls in (merged.geoms if hasattr(merged, "geoms") else [merged]):
            cs = list(ls.coords)
            if len(cs) > 3 and cs[0] == cs[-1]:
                rings.append(cs)
    return rings


def _nested(polys):
    """Even-odd region of simple polygons that nest without crossing: one inside an odd number of others is a
    hole in its smallest container. Nesting is read from one point per polygon; if any rings cross, touch or
    repeat, the result isn't valid and this returns None - symmetric_difference decides those. One spatial query
    instead of a running symmetric_difference, which slowed down with every hole (HobbyCase's back panel)."""
    if any(p.geom_type != "Polygon" or len(p.interiors) for p in polys):
        return None
    if len(polys) == 1:
        return polys[0]
    tree = shapely.STRtree(polys)
    inp, cont = tree.query(shapely.point_on_surface(polys), predicate="within")
    keep = inp != cont
    inp, cont = inp[keep], cont[keep]
    area = np.array([p.area for p in polys])
    depth = np.bincount(inp, minlength=len(polys))
    parent = np.full(len(polys), -1)
    for i, j in zip(inp.tolist(), cont.tolist()):
        if area[j] <= area[i] + EPS:          # identical rings: they cancel out, leave it to the overlay
            return None
        if parent[i] < 0 or area[j] < area[parent[i]]:
            parent[i] = j
    holes = {}
    for i, j in enumerate(parent.tolist()):
        if depth[i] % 2:
            holes.setdefault(j, []).append(polys[i].exterior)
    out = [Polygon(p.exterior, holes.get(i, [])) for i, p in enumerate(polys) if depth[i] % 2 == 0]
    geo = out[0] if len(out) == 1 else MultiPolygon(out)
    return geo if geo.is_valid else None


_shapes = {}     # outline moved to the origin -> its region: copies of one part, and parts a drag doesn't change


def _shape(subs, burn):
    """Even-odd region of the cut contours, shrunk by the burn so parts meet at their nominal faces. Remembered by
    outline (wherever it was drawn): HobbyCase draws 18 identical walls, and its 252-hole back panel stays the same
    while the depth slider moves."""
    rings = [r for r in _rings(subs) if len(r) >= 4]
    if not rings:
        return Polygon()
    x0, y0 = rings[0][0]
    key = (round(burn, 6), tuple(tuple((round(x - x0, 4), round(y - y0, 4)) for x, y in r) for r in rings))
    geo = _shapes.get(key)
    if geo is None:
        geo = _region([[(x - x0, y - y0) for x, y in r] for r in rings], burn)
        if len(_shapes) > 400:
            _shapes.clear()
        _shapes[key] = geo
    return affinity.translate(geo, x0, y0)


def _region(rings, burn):
    polys = []
    for ring in rings:
        p = Polygon(ring)
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty:
            polys.append(p)
    geo = _nested(polys) if polys else None
    if geo is None:
        geo = Polygon()
        for p in polys:
            geo = geo.symmetric_difference(p)
    if burn > 0 and not geo.is_empty:
        geo = geo.buffer(-burn, join_style="mitre")
    return geo


def _frame(box):
    m = box.ctx._m
    return (m.a, m.b, m.c, m.d, m.e, m.f)


class _EdgeProbe:
    """Stands in for an edge object and notes the drawing frame every time it is drawn (polygonWalls' bottom)."""

    def __init__(self, box, edge, on_call):
        self._box, self._edge, self._on_call = box, edge, on_call

    def __getattr__(self, name):
        return getattr(self._edge, name)

    def __call__(self, length, *a, **kw):
        self._on_call(_frame(self._box), length)
        return self._edge(length, *a, **kw)


def _record_walls(box, log):
    """Hook boxes.py so every part knows where it was drawn. Each record: kind, frame (drawing matrix as
    a, b, c, d, e, f), the boxes.py part it went into, and what the kind needs:
      rect   rectangularWall: inner size x, y, edge chars. Callback 0 fires at the inner corner of the bottom edge
             (independent of the edge type, burn included): (0..x, 0..y) in the frame is the wall's inner face.
      poly   polygonWall: the closed borders list. Callback 0 fires at the first corner, on the outline + burn.
      strip  one wall of polygonWalls: length x, height y; the frame is the start of its bottom edge.
      move   any part: the origin of the box the part is drawn in (after move() made room), size x, y."""
    def rec(kind, **kw):
        r = {"kind": kind, "frame": None, "part": None, "x": 0.0, "y": 0.0, "edges": "", "label": ""}
        r.update(kw)
        return r

    def with_corner_callback(cb, r, n_edges):
        def call(n):
            if n == 0:
                r["frame"] = _frame(box)
                r["part"] = box.ctx._dwg._p
            if cb is None:
                return
            if hasattr(cb, "__getitem__"):
                try:
                    f = cb[n]
                except (KeyError, IndexError):
                    return
                if f and callable(f):
                    f()
            elif callable(cb):
                cb(n)
        return [lambda n=n: call(n) for n in range(n_edges)]

    rect, rect_sig = box.rectangularWall, inspect.signature(box.rectangularWall)

    def rectangular_wall(*args, **kw):
        bound = rect_sig.bind(*args, **kw)
        a = bound.arguments
        chars = "".join(e if isinstance(e, str) and len(e) == 1 else (getattr(e, "char", None) or "?")
                        for e in a.get("edges", "eeee"))
        r = rec("rect", x=float(a["x"]), y=float(a["y"]), edges=chars, label=a.get("label") or "")
        a["callback"] = with_corner_callback(a.get("callback"), r, 4)
        log.append(r)
        return rect(*bound.args, **bound.kwargs)

    poly, poly_sig = box.polygonWall, inspect.signature(box.polygonWall)

    def polygon_wall(*args, **kw):
        bound = poly_sig.bind(*args, **kw)
        a = bound.arguments
        borders = box._closePolygon(list(a["borders"]))
        r = rec("poly", borders=[b if isinstance(b, (int, float)) else list(b) for b in borders],
                label=a.get("label") or "")
        a["callback"] = with_corner_callback(a.get("callback"), r, len(borders) // 2)
        log.append(r)
        return poly(*bound.args, **bound.kwargs)

    walls_fn, walls_sig = box.polygonWalls, inspect.signature(box.polygonWalls)

    def polygon_walls(*args, **kw):
        bound = walls_sig.bind(*args, **kw)
        a = bound.arguments
        h = float(a["h"])

        def on_bottom(frame, length):
            log.append(rec("strip", frame=frame, part=box.ctx._dwg._p, x=float(length), y=h))

        bottom = a.get("bottom", "F")
        a["bottom"] = _EdgeProbe(box, box.edges.get(bottom, bottom), on_bottom)
        return walls_fn(*bound.args, **bound.kwargs)

    move = box.move

    def move_hook(x, y, where, before=False, label=""):
        skip = move(x, y, where, before=before, label=label)
        if before and not skip:
            log.append(rec("move", frame=_frame(box), part=box.ctx._dwg._p, x=float(x), y=float(y),
                           label=label or "", where=where or ""))
        return skip

    box.rectangularWall = rectangular_wall
    box.polygonWall = polygon_wall
    box.polygonWalls = polygon_walls
    box.move = move_hook


def _probe_edges(box, log, chars):
    """Note the frame at the start of every drawn edge of these types (after open(), when edges exist):
    kind "edge", the char, its length as x. PirateChest draws its polygon lid sides itself; their chest-hinge
    bottom edge (p / P) is the only reliable handle on where they are."""
    for ch in chars:
        edge = box.edges.get(ch)
        if edge is None:
            continue

        def on_call(frame, length, ch=ch):
            log.append({"kind": "edge", "char": ch, "frame": frame, "part": box.ctx._dwg._p, "x": float(length),
                        "y": 0.0, "edges": "", "label": ""})

        box.edges[ch] = _EdgeProbe(box, edge, on_call)


def render(name, params, thickness, burn, labels=True, margin=0.0):
    """Run generator `name` with `params` ({dest: value}) -> (parts, info). Raises ValueError with the
    generator's own message when the parameters don't make a box. margin: room left around every part's drawing
    (per-axis kerf mode draws without burn and grows the cut outline at export - see kerf.py)."""
    box = catalog.new_box(name)
    layout = None
    if name == "TrayLayout":
        from . import traylayout
        layout = traylayout.sync(params.get("layout"), params.get("sx", "50*3"), params.get("sy", "50*3"))
        params = {**params, "layout": layout}
    # params are keyed by argparse dest; some flags differ from their dest (--gripheight -> gh)
    flags = {a.dest: a.option_strings[0] for a in box.argparser._actions if a.option_strings}
    args = []
    for k, v in params.items():
        if k in catalog.APP_OWNED or k not in flags:
            continue
        if isinstance(v, bool):
            v = "1" if v else "0"
        args.append("%s=%s" % (flags[k], v))
    args += ["--thickness=%r" % float(thickness), "--burn=%r" % float(burn), "--reference=0",
             "--labels=%d" % (1 if labels else 0), "--format=svg", "--qr_code=0", "--debug=0"]
    try:
        box.parseArgs(args)
    except SystemExit as e:  # argparse reports bad values by exiting
        raise ValueError("invalid parameters: %s" % " ".join(args)) from e
    surface = _Capture()
    ctx = Context(surface)
    box.formats.getSurface = lambda fmt: (surface, ctx)
    walls = []
    _record_walls(box, walls)
    box.open()
    _probe_edges(box, walls, "pP")
    box.render()
    box.ctx.stroke()
    box.ctx = None
    for i, w in enumerate(walls):     # drawing order: pieces of one drawing get re-sorted by position later
        w["seq"] = i

    parts = []
    for group, sp in enumerate(surface.parts):
        if not sp.pathes:
            continue
        raw = Part(0)
        for path in sp.pathes:
            path.faster_edges(box.inner_corners)
            layer = _layer(path.params["rgb"])
            raw.labels += _texts(path)
            for sub in _subpaths(path):
                raw.subpaths[layer].append(sub)
        if not (raw.subpaths[CUT] or raw.subpaths[LINE]):
            continue   # annotation-only leftovers
        mine = [w for w in walls if w["frame"] is not None and w["part"] is sp]
        for p in _pieces(raw, burn, mine, margin):
            p.index = len(parts)
            p.group = group
            if not p.labels:
                p.name = "part %d" % (p.index + 1)
            parts.append(p)
    info = {"cli": box.metadata.get("cli_short", ""), "thickness": float(thickness), "burn": float(burn),
            "inner_corners": box.inner_corners, "attrs": _attrs(box)}
    if layout is not None:
        info["layout"] = layout
    return parts, info


ATTRS = ("x", "y", "h", "hi", "sx", "sy", "lidheight", "splitlid", "front_height", "angle", "n", "play",
         "unit_w", "unit_h", "unit_d", "rows", "shelves_n", "outside", "removable_backwall", "removable_panel",
         "glued_panel", "inner_depth", "outside_depth", "inside_w", "inside_h", "cols")


def _attrs(box):
    """The generator's own values after render() - sizes already adjusted for outside measurements, sections as
    lists. The 3D assemblers place walls from these (python/superboxes/assembly.py)."""
    out = {}
    for k in ATTRS:
        v = getattr(box, k, None)
        if isinstance(v, bool) or isinstance(v, (int, float)):
            out[k] = v
        elif isinstance(v, (list, tuple)) and all(isinstance(e, (int, float)) for e in v):
            out[k] = list(v)
    for k in ("hwalls", "vwalls"):                     # TrayLayout's wall grid
        v = getattr(box, k, None)
        if isinstance(v, list) and v and isinstance(v[0], list):
            out[k] = [[bool(e) for e in row] for row in v]
    return out


def _inside_point(rec):
    """A point well inside the wall a record describes, in drawing coordinates: which piece it belongs to is
    unambiguous there (a frame's own origin can sit on the joint with the neighbouring piece)."""
    a, b, c, d, e, f = rec["frame"]
    if rec["kind"] == "poly":
        xs = [0.0]
        ys = [0.0]
        cx = cy = heading = 0.0
        borders = rec.get("borders") or []
        for i in range(0, len(borders) - 1, 2):
            ang = borders[i + 1] if isinstance(borders[i + 1], (int, float)) else borders[i + 1][0]
            cx += borders[i] * math.cos(math.radians(heading))
            cy += borders[i] * math.sin(math.radians(heading))
            xs.append(cx)
            ys.append(cy)
            heading += ang
        u, v = sum(xs) / len(xs), sum(ys) / len(ys)
    elif rec["kind"] == "edge":
        u, v = rec["x"] / 2, 1.0
    else:
        u, v = rec["x"] / 2, rec["y"] / 2
    return (a * u + b * v + c, d * u + e * v + f)


def _discs(main, islands, burn):
    """Physical parts cut out of a part's holes. Cutting only separates material: a hole with something cut out
    of it again (a ring around an island) leaves a loose piece - a disc with a hole, which IntegratedHingeBox uses
    as its hinge. Plain holes and islands are scrap. Only the 3D needs these; the cut paths are unaffected."""
    if not islands or not hasattr(main, "interiors"):
        return []
    out = []
    for ring in main.interiors:
        hole = Polygon(ring)
        inside = [i for i in islands if hole.contains(i.representative_point())]
        if inside:
            disc = hole.buffer(-max(2 * burn, 0.05)).difference(unary_union(inside))
            if not disc.is_empty:
                out.append(disc)
    return out


def _pieces(raw, burn, walls=(), margin=0.0):
    """One boxes.py part can hold several separate pieces (Console draws all its walls in one go). Split by the
    cut region's connected components, then normalise each piece to its own bounding box."""
    shape = _shape(raw.subpaths[CUT], burn)
    comps = [g for g in (shape.geoms if hasattr(shape, "geoms") else [shape]) if not g.is_empty]
    # A region inside another region's hole is cut out of that part, so it stays with it on the sheet
    # (IntegratedHingeBox: the rectangle inside the round hinge hole). roots = (main region, [islands])
    comps.sort(key=lambda g: -Polygon(g.exterior).area)
    roots = []
    for g in comps:
        for r in roots:
            if Polygon(r[0].exterior).contains(g.representative_point()):
                r[1].append(g)
                break
        else:
            roots.append((g, []))
    if len(roots) <= 1:
        groups = [(raw.subpaths, raw.labels, roots[0] if roots else (shape, []), list(walls))]
    else:
        roots.sort(key=lambda r: (-r[0].bounds[1], r[0].bounds[0]))   # top row first, like the drawing order
        polys = [r[0] for r in roots]
        hulls = [Polygon(g.exterior).buffer(burn + 0.05) for g in polys]

        def owner(pt):
            q = Point(pt)
            for i, h in enumerate(hulls):
                if h.contains(q):
                    return i
            return min(range(len(hulls)), key=lambda i: hulls[i].distance(q))

        groups = [({CUT: [], LINE: [], REF: []}, [], roots[i], []) for i in range(len(polys))]
        for layer, subs in raw.subpaths.items():
            for s in subs:
                groups[owner(s[0])][0][layer].append(s)
        for lab in raw.labels:
            groups[owner((lab[1], lab[2]))][1].append(lab)
        for w in walls:
            groups[owner(_inside_point(w))][3].append(w)
    out = []
    for subpaths, labels, (piece_shape, islands), piece_walls in groups:
        drawn = subpaths[CUT] + subpaths[LINE]
        if not drawn:
            continue
        pts = [pt for s in drawn for pt in flatten(s, 4)]
        x0 = min(x for x, _ in pts) - margin
        y0 = min(y for _, y in pts) - margin
        x1 = max(x for x, _ in pts) + margin
        y1 = max(y for _, y in pts) + margin
        p = Part(0)
        p.subpaths = {k: [_move(s, -x0, -y0) for s in v] for k, v in subpaths.items()}
        p.labels = [(t, x - x0, y - y0, fs, a) for t, x, y, fs, a in labels]
        p.w, p.h = x1 - x0, y1 - y0
        p.shape = affinity.translate(piece_shape, -x0, -y0)
        p._outline_from_cuts = True
        p.children = [affinity.translate(c, -x0, -y0) for c in _discs(piece_shape, islands, burn)]
        for w in piece_walls:
            a, b, c, d, e, f = w["frame"]
            p.walls.append({**{k: v for k, v in w.items() if k != "part"}, "frame": (a, b, c - x0, d, e, f - y0)})
        if p.labels:
            p.name = " ".join(t for t, *_ in p.labels).replace("\n", " ")
        out.append(p)
    return out
