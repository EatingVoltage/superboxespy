"""Imported SVG art for the face editor (.grill/face-editor.md): every drawn shape of an SVG as engraving lines, and
its closed shapes as areas for a hatch. The SVG text travels inside the box file, so a box stands on its own.

Paths and the basic shapes (rect, circle, ellipse, line, polyline, polygon) are drawn; text, images and clip paths
aren't (convert text to paths before importing). Y points up, in the SVG's own units; faces.py scales the result."""
import re
import xml.etree.ElementTree as ET
from functools import lru_cache

from shapely.geometry import LineString, MultiLineString, Polygon

from evlaser import svgpath

from .stampcase.shapes import _SKIP, _mul, _parse_transform

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": 25.4 / 96, "": 25.4 / 96}


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
        if tag in _SKIP or tag in ("text", "image", "style", "script"):
            return
        m = _mul(m, _parse_transform(el.get("transform")))
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

