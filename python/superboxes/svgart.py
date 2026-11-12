"""Imported SVG art for the face editor (.grill/face-editor.md): every drawn shape of an SVG as engraving lines, and
its closed shapes as areas for a hatch. The SVG text travels inside the box file, so a box stands on its own.

Paths and the basic shapes (rect, circle, ellipse, line, polyline, polygon) are drawn; text, images and clip paths
aren't (convert text to paths before importing). Y points up, in the SVG's own units; faces.py scales the result.

The transform helpers here are shared: the stamp case's logo (stampcase/shapes.py) and LightBurn's XForms
(lbrnart.py) compose them the same way."""
import math
import re
import xml.etree.ElementTree as ET
from functools import lru_cache

from shapely.geometry import LineString, MultiLineString, Polygon

from evlaser import svgpath

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": 25.4 / 96, "": 25.4 / 96}
_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)")
SKIP = ("defs", "symbol", "marker", "pattern", "metadata", "namedview", "clipPath", "mask", "title", "desc")


def mul(a, b):
    """The affine [a b c d e f] (x -> (a x + c y + e, b x + d y + f)) of a after b."""
    return [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]]


def parse_transform(s):
    """An SVG transform attribute as one affine [a b c d e f]."""
    m = [1, 0, 0, 1, 0, 0]
    for kind, args in _TRANSFORM.findall(s or ""):
        v = [float(t) for t in re.split(r"[\s,]+", args.strip()) if t]
        if kind == "matrix":
            t = v
        elif kind == "translate":
            t = [1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0]
        elif kind == "scale":
            t = [v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0]
        else:
            a = math.radians(v[0])
            t = [math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0]
            if len(v) == 3:
                cx, cy = v[1], v[2]
                t = mul(mul([1, 0, 0, 1, cx, cy], t), [1, 0, 0, 1, -cx, -cy])
        m = mul(m, t)
    return m


def fit(bounds, size):
    """The affine that scales art with these bounds to `size` tall (flat art: as wide) and centres it on (0, 0)."""
    x0, y0, x1, y1 = bounds
    k = size / (y1 - y0) if y1 > y0 else size / max(x1 - x0, 1e-9)
    return [k, 0, 0, k, -(x0 + x1) / 2 * k, -(y0 + y1) / 2 * k]


def _f(el, name, default=0.0):
    m = _NUM.match((el.get(name) or "").strip())
    return float(m.group()) if m else default


def _shape_d(el, tag):
    """A basic shape as path data, or None."""
    if tag == "rect":
        x, y, w, h = _f(el, "x"), _f(el, "y"), _f(el, "width"), _f(el, "height")
        return "M%g %gh%gv%gh%gz" % (x, y, w, h, -w) if w > 0 and h > 0 else None
    if tag in ("circle", "ellipse"):
        cx, cy = _f(el, "cx"), _f(el, "cy")
        rx = _f(el, "r") if tag == "circle" else _f(el, "rx")
        ry = _f(el, "r") if tag == "circle" else _f(el, "ry")
        if rx <= 0 or ry <= 0:
            return None
        return "M%g %gA%g %g 0 1 0 %g %gA%g %g 0 1 0 %g %gz" % (cx - rx, cy, rx, ry, cx + rx, cy, rx, ry, cx - rx, cy)
    if tag == "line":
        return "M%g %gL%g %g" % (_f(el, "x1"), _f(el, "y1"), _f(el, "x2"), _f(el, "y2"))
    if tag in ("polyline", "polygon"):
        v = [float(n) for n in _NUM.findall(el.get("points") or "")]
        if len(v) < 4:
            return None
        pts = " ".join("%g %g" % (v[i], v[i + 1]) for i in range(0, len(v) - 1, 2))
        return "M" + pts + ("z" if tag == "polygon" else "")
    return None


@lru_cache(maxsize=32)
def parse(text):
    """(lines, closed rings) of an SVG's drawing, Y up, in its own units. Raises ValueError for text that isn't SVG."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError("not an SVG file (%s)" % e)
    if root.tag.split("}")[-1] != "svg":
        raise ValueError("not an SVG file")
    lines, rings = [], []

    def walk(el, m):
        tag = el.tag.split("}")[-1]
        if tag in SKIP or tag in ("text", "image", "style", "script"):
            return
        m = mul(m, parse_transform(el.get("transform")))
        d = el.get("d") if tag == "path" else _shape_d(el, tag)
        if d:
            for sub in svgpath.parse(d):
                pts = [(m[0] * x + m[2] * y + m[4], -(m[1] * x + m[3] * y + m[5])) for x, y in svgpath.flatten(sub, 10)]
                if len(pts) < 2:
                    continue
                if sub[2] and pts[0] != pts[-1]:
                    pts.append(pts[0])
                lines.append(LineString(pts))
                if sub[2] and len(pts) >= 4:
                    rings.append(pts)
        for ch in el:
            walk(ch, m)

    walk(root, [1, 0, 0, 1, 0, 0])
    return MultiLineString(lines), tuple(tuple(r) for r in rings)


def area(rings):
    """The closed shapes as one region, holes by even-odd (a letter's counter, a ring's middle)."""
    region = Polygon()
    for r in rings:
        p = Polygon(r).buffer(0)
        if not p.is_empty:
            region = region.symmetric_difference(p)
    return region


def height_mm(text):
    """The art's height in mm if the SVG says it in real units (height="40mm"), else None."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    m = re.fullmatch(r"\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*(mm|cm|in|pt|pc)\s*", root.get("height") or "")
    return float(m.group(1)) * _UNITS[m.group(2)] if m else None

