"""LightBurn files as logos for the face editor (.grill/logo-library.md).

A .lbrn2 in the logos folder is one logo: its first page as LightBurn draws it (later pages are groups with
SubType="Page" and are left out). Shapes on a fill layer (Scan, Offset Fill) are areas, filled even-odd as LightBurn
fills them; shapes on a line layer (Cut) are strokes; Scan+Cut is both. Text is LightBurn's own outline of it, the
BackupPath every Text shape carries, so no font is read. Bitmaps, Image and Tool layers and layers whose output is
off are left out. Coordinates are LightBurn's: mm, y up.

The file format, as LightBurn 2 writes it: a shape's XForm "a b c d e f" maps (x, y) to (a x + c y + e, b x + d y + f)
and a group's applies to its children; a Text's BackupPath is drawn by the Text's XForm (its own XForm is that,
already made absolute). A Path's VertList is "V x y" per vertex with its two Bezier handles (c0 leaves
the vertex, c1 arrives at it; "c0x1" alone means none), its PrimList "L i j" / "B i j" segments or "LineClosed"; a
path without them reuses the lists of an earlier path with the same VertID / PrimID."""
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.ops import unary_union

FILL_TYPES = {"Scan", "Offset Fill"}
BOTH_TYPES = {"Scan+Cut"}
SKIP_TYPES = {"Image", "Tool"}
STEPS = 12                       # points per Bezier segment
ROUND = 72                       # points per ellipse

_NUM = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
_VERT = re.compile(r"V%s %s(?:c0x%s(?:c0y%s)?)?(?:c1x%s(?:c1y%s)?)?" % ((_NUM,) * 6))
_PRIM = re.compile(r"([LB])(\d+) (\d+)")
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class Art:
    lines: MultiLineString       # strokes: shapes on line layers
    fill: MultiPolygon           # areas: closed shapes on fill layers
    skipped: int = 0             # bitmaps left out

    @property
    def empty(self):
        return self.lines.is_empty and self.fill.is_empty

    @property
    def bounds(self):
        return unary_union([g for g in (self.lines, self.fill) if not g.is_empty]).bounds


def _xform(el):
    x = el.find("XForm")
    if x is None or not (x.text or "").strip():
        return IDENTITY
    v = [float(t) for t in x.text.split()]
    return tuple(v) if len(v) == 6 else IDENTITY


def _mul(m, n):
    """m after n."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _apply(m, pts):
    a, b, c, d, e, f = m
    return [(a * x + c * y + e, b * x + d * y + f) for x, y in pts]


def _verts(text):
    out = []
    for g in _VERT.finditer(text or ""):
        x, y = float(g.group(1)), float(g.group(2))
        c0 = (float(g.group(3)), float(g.group(4))) if g.group(4) is not None else None
        c1 = (float(g.group(5)), float(g.group(6))) if g.group(6) is not None else None
        out.append((x, y, c0, c1))
    return out


def _prims(text, n):
    t = (text or "").strip()
    if t.startswith("LineClosed"):
        return [("L", i, (i + 1) % n) for i in range(n)]
    if t.startswith("LineOpen"):
        return [("L", i, i + 1) for i in range(n - 1)]
    return [(k, int(i), int(j)) for k, i, j in _PRIM.findall(t)]


def _bez(p0, c1, c2, p1):
    out = []
    for k in range(1, STEPS + 1):
        t = k / STEPS
        mt = 1 - t
        out.append((mt ** 3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p1[0],
                    mt ** 3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p1[1]))
    return out


def _chain_end(pts, at, last):
    """A chain as [(points, closed)]: closed when it ends where it started; ending on a vertex it passed (a tail
    into a loop, as LightBurn draws some paths) the loop is closed and the tail before it open."""
    if at[0][0] == last or pts[0] == pts[-1]:
        return [(pts, True)]
    k = next((n for v, n in at[1:] if v == last), None)
    if k is None:
        return [(pts, False)]
    return [(pts[:k + 1], False), (pts[k:], True)]


def _path(verts, prims):
    """[(points, closed)] of a path: its segments chained in order."""
    chains, cur, at, last = [], None, None, None
    for kind, i, j in prims:
        if i >= len(verts) or j >= len(verts):
            continue
        if cur is None or i != last:
            if cur is not None:
                chains += _chain_end(cur, at, last)
            cur, at = [verts[i][:2]], [(i, 0)]
        a, b = verts[i], verts[j]
        if kind == "B":
            cur += _bez(a[:2], a[2] or a[:2], b[3] or b[:2], b[:2])
        else:
            cur.append(b[:2])
        at.append((j, len(cur) - 1))
        last = j
    if cur is not None:
        chains += _chain_end(cur, at, last)
    return chains


def _rect(w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    if r <= 1e-9:
        return [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    pts = []
    for cx, cy, a0 in ((w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
                       (-w / 2 + r, -h / 2 + r, 180)):
        pts += [(cx + r * math.cos(math.radians(a0 + 90 * k / 8)), cy + r * math.sin(math.radians(a0 + 90 * k / 8)))
                for k in range(9)]
    return pts


def _ngon(n, rx, ry, inner=None):
    """A regular polygon (or star, `inner` the inner radius ratio) with a vertex straight up."""
    n = max(3, n)
    k = 2 if inner else 1
    pts = []
    for i in range(n * k):
        t = math.pi / 2 + 2 * math.pi * i / (n * k)
        s = inner if inner and i % 2 else 1.0
        pts.append((rx * s * math.cos(t), ry * s * math.sin(t)))
    return pts


def _num(el, name, default=0.0):
    try:
        return float(el.get(name))
    except (TypeError, ValueError):
        return default


class _Reader:
    def __init__(self, root):
        self.layers = {}
        for cs in root.findall("CutSetting"):
            idx = cs.find("index")
            out = cs.find("doOutput")
            if idx is not None:
                off = out is not None and out.get("Value") in ("0", "False", "false")
                self.layers[int(idx.get("Value"))] = None if off else cs.get("type")
        # every shared list, first: a path on a layer that's left out (or on another page) may hold the one that a
        # drawn path reuses
        self.verts, self.prims = {}, {}
        for el in root.iter("Shape"):
            vl, pl = el.find("VertList"), el.find("PrimList")
            if vl is not None and el.get("VertID") is not None:
                self.verts.setdefault(el.get("VertID"), _verts(vl.text))
            if pl is not None and el.get("PrimID") is not None:
                self.prims.setdefault(el.get("PrimID"), pl.text)
        self.strokes, self.rings = [], []
        self.skipped = 0
        self.missing = 0                           # paths whose lists no earlier path had

    def kind(self, el):
        """"fill", "line", "both" or None (left out) for a shape's layer."""
        try:
            idx = int(el.get("CutIndex"))
        except (TypeError, ValueError):
            return "line"
        if idx not in self.layers:
            return "line"
        t = self.layers[idx]
        if t is None or t in SKIP_TYPES:
            return None
        return "fill" if t in FILL_TYPES else "both" if t in BOTH_TYPES else "line"

    def add(self, kind, chains):
        for pts, closed in chains:
            if len(pts) < 2:
                continue
            if kind in ("line", "both"):
                self.strokes.append(LineString(pts + [pts[0]] if closed and pts[0] != pts[-1] else pts))
            if kind in ("fill", "both") and closed and len(pts) >= 3:     # LightBurn fills closed shapes only
                self.rings.append(pts)

    def path_chains(self, el, m):
        vid, pid = el.get("VertID"), el.get("PrimID")
        vl, pl = el.find("VertList"), el.find("PrimList")
        if vl is None and vid not in self.verts or pl is None and pid not in self.prims:
            self.missing += 1
        verts = _verts(vl.text) if vl is not None else self.verts.get(vid, [])
        prims = _prims(pl.text if pl is not None else self.prims.get(pid, ""), len(verts))
        return [(_apply(m, pts), closed) for pts, closed in _path(verts, prims)]

    def shape(self, el, parent):
        t = el.get("Type")
        if t == "Group":
            if el.get("SubType") == "Page":        # another page of the project
                return
            m = _mul(parent, _xform(el))
            for c in el.findall("Children/Shape"):
                self.shape(c, m)
            return
        if t == "Bitmap":
            self.skipped += 1
            return
        kind = self.kind(el)
        if kind is None:
            return
        m = _mul(parent, _xform(el))
        if t == "Path":
            self.add(kind, self.path_chains(el, m))
        elif t == "Text":
            bp = el.find("BackupPath")
            if bp is not None:     # the outline about the text's own origin (its XForm is that one, made absolute)
                self.add(kind, self.path_chains(bp, m))
        elif t == "Rect":
            self.add(kind, [(_apply(m, _rect(_num(el, "W"), _num(el, "H"), _num(el, "Cr"))), True)])
        elif t == "Ellipse":
            rx, ry = _num(el, "Rx"), _num(el, "Ry")
            pts = [(rx * math.cos(2 * math.pi * k / ROUND), ry * math.sin(2 * math.pi * k / ROUND)) for k in range(ROUND)]
            self.add(kind, [(_apply(m, pts), True)])
        elif t == "Polygon":
            self.add(kind, [(_apply(m, _ngon(int(_num(el, "N", 6)), _num(el, "Rx"), _num(el, "Ry"))), True)])
        elif t == "Star":
            inner = _num(el, "Ra", 0.5)
            self.add(kind, [(_apply(m, _ngon(int(_num(el, "N", 5)), _num(el, "Rx"), _num(el, "Ry"),
                                             inner if 0 < inner < 1 else 0.5)), True)])


def _even_odd(rings):
    """The area LightBurn fills: every closed ring toggles inside and outside."""
    region = Polygon()
    for r in rings:
        p = Polygon(r).buffer(0)
        if not p.is_empty:
            region = region.symmetric_difference(p)
    polys = [g for g in (region.geoms if hasattr(region, "geoms") else [region]) if isinstance(g, Polygon) and not g.is_empty]
    return MultiPolygon(polys)


@lru_cache(maxsize=32)
def _parse(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError("not a LightBurn file (%s)" % e)
    if root.tag != "LightBurnProject":
        raise ValueError("not a LightBurn file")
    rd = _Reader(root)
    for el in root.findall("Shape"):
        rd.shape(el, IDENTITY)
    return Art(MultiLineString([s for s in rd.strokes if s.length > 0]), _even_odd(rd.rings), rd.skipped)


def parse(text):
    """The drawing of a .lbrn2 file's text as an Art. Raises ValueError for text that isn't a LightBurn project."""
    return _parse(text)


@lru_cache(maxsize=32)
def _load(path, stamp):
    with open(path, encoding="utf-8") as f:
        return parse(f.read())


def load(path):
    """The drawing of a .lbrn2 file, read again when the file changes."""
    st = os.stat(path)
    return _load(path, (st.st_mtime_ns, st.st_size))
