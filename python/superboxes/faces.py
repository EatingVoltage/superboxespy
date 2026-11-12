"""Faces: what the face editor puts on a box's outside (.grill/face-editor.md).

A face is a role on the closed box - top, bottom, front, back, left, right - held by the placed part whose engraved
side looks that way. The assembly turns every part's engraved side (the side up on the laser) out of the box and
places it right-handed, so a part's own drawing, seen from outside, is never mirrored: whatever is drawn in part
coordinates and engraved face up reads right on the finished box.

The editor works in the face's view: seen from outside, x to the right, y up, where up is the box's up for a wall,
its back for the top and its front for the bottom (tip the box toward you to read it); (0, 0) is the lower-left corner
of the part's outline. Items are mm in that view:

    {"id", "kind": "text" | "logo" | "svg" | "hole", "text", "logo" (a file in the logos folder: .svg strokes, or a
     LightBurn .lbrn2, lbrnart.py), "svg" (an imported SVG's text, svgart.py), "name" (its file name), "size" (cap
     height, or a logo's or SVG's height, mm), "bold", "style": "outline" | "hatch" (a .lbrn2 logo: "outline" for
     outlines only, else as drawn), "rot": 0 | 90 | 180 | 270,
     a hole: "shape": "round" (with "d") | "rect" (with "w", "h", "r") | "notch" (a thumb notch: "d", its centre on
     the face's top or bottom edge, by the anchor's row), "part" (the library part it's for),
     "anchor": "tl" | "t" | "tr" | "l" | "c" | "r" | "bl" | "b" | "br", "dx", "dy"}

The item's own anchor point (the same spot of its bounding box) sits (dx, dy) from the face's anchor point, so it
keeps its place when the box changes size; text lines align to the anchor's side. An item must stay inside the free
area: the outline less thickness + 1.5 mm from every edge (finger joints), as for the maker's mark.

Inside faces ("top.in", "front.in", ...: .grill/face-editor.md, two pages with a flip) are the same parts seen from
inside the box: the outside view mirrored left to right, up the same. Their items engrave the part's other side (the
face down on the laser) and come out as "inside" decorations, which the export puts on a page of their own, mirrored
for the sheet turned over left to right. What lies inside a face (the floor, the side walls' ends, a partition) is
kept clear there, as a lid's rim is outside. Holes and notches go through anyway: they belong to the outside.

A logo links to its file by name (.grill/logo-library.md): change the file and every box using it follows; a file
that's gone turns the item red. A .lbrn2 logo engraves as drawn: its line layers as outlines on LINE, its filled
shapes on FILL while the logo is FILL_MAX high or less, above that their outlines and a drawn hatch on LINE
(eVlaser: line first, fill for small accents).

A hole is cut through the part (CUT): its size is the finished hole, the kerf taken care of like boxes.py's own holes,
and it keeps HOLE_WEB of wood to the next hole. A hole with "board" is an edge connector's opening in a wall: it sits
at the board's height on that wall (the request's "boards": {role: mm of the board's top above the inside floor}),
"lift" from the board's top to the opening's bottom, and only moves sideways. It becomes part of the part (with_holes), so the 3D, the sheets and
the maker's mark see it; an engraving across a hole is red.
"""
import copy
import math
import os

from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import MultiLineString, MultiPoint, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from evlaser import lbrn, machine as M, svgpath, textures

from . import lbrnart, svgart
from .capture import coords_json
from .export import rings
from .stampcase import config as SC, shapes as SS

X, Y, Z = np.eye(3)
NORMAL = {"top": Z, "bottom": -Z, "front": -Y, "back": Y, "left": -X, "right": X}
UP = {"top": Y, "bottom": -Y, "front": Z, "back": Z, "left": Z, "right": Z}
ROLES = tuple(NORMAL)
ANCHORS = ("tl", "t", "tr", "l", "c", "r", "bl", "b", "br")
HATCH = SC.TITLE_HATCH           # mm between hatch lines, +-45 degrees (the stamp case's lid title)
LINE_GAP = 1.4                   # line pitch of multi-line text, in cap heights
KEEP_OUT = 1.5                   # mm beyond the thickness kept clear along every edge (finger joints)
HOLE_WEB = 2.0                   # mm of wood at least between two holes
EDGE_AIR = 0.5                   # an edge connector's opening starts this far below the board's top (serve.EDGE_AIR)
ARC = 0.5522847498               # cubic Bezier handle for a quarter circle
FILL_MAX = 20.0                  # mm: a logo this high or less engraves its filled shapes on FILL, a taller one hatched
LOGO_KINDS = (".svg", ".lbrn2")


@dataclass
class Face:
    role: str
    part: int                    # part index
    rot: np.ndarray              # 2x2: part xy -> view xy
    off: np.ndarray              # view = rot @ part + off
    w: float
    h: float
    outline: object              # the part's shape in view coordinates
    free: object                 # where items may go, view coordinates
    covered: object = None       # what other parts cover of it on the closed box (a lid's rim), view coordinates
    inside: bool = False         # seen from inside the box (the part's other side)
    floor: object = None         # a wall's: the box's inside floor, view y (where a board's height counts from)

    def to_view(self, g):
        a, b, c, d = self.rot.ravel()
        return affinity.affine_transform(g, [a, b, c, d, *self.off])

    def to_part(self, g):
        inv = np.linalg.inv(self.rot)
        o = -inv @ self.off
        a, b, c, d = inv.ravel()
        return affinity.affine_transform(g, [a, b, c, d, *o])


_found = {}      # find()'s faces by its inputs: api._render caches the parts, so a face edit finds the same faces again


def find(parts, asm, t):
    """{role: Face} for the closed box: per role the biggest placed part whose engraved side looks that way and that
    is at least half in view (an inner guide behind a side wall isn't a face). A part the assembly could only place
    mirrored (assembly._turn_not_mirror) is left out: it would have to be cut mirrored for its engraving to face out.
    The faces are shared between calls with the same parts and assembly: nothing changes a Face once it's made."""
    key = (id(parts), t, repr([(pl.get("group"), pl.get("kind"), pl.get("mirrored"), pl.get("m"))
                               for pl in asm.get("parts", [])]), repr((asm.get("inside") or {}).get("lo")))
    hit = _found.get(key)
    if hit is not None and hit[0] is parts:      # the parts are held below, so their id can't be reused meanwhile
        return hit[1]
    out = _find(parts, asm, t)
    if len(_found) > 8:
        _found.clear()
    _found[key] = (parts, out)
    return out


def _find(parts, asm, t):
    cands = {}
    for p, pl in zip(parts, asm.get("parts", [])):
        if (pl.get("group") == "loose" or pl.get("kind") != "wall" or pl.get("mirrored") or p.shape is None
                or p.shape.is_empty):
            continue
        m = np.asarray(pl["m"], float).reshape(3, 4)
        n = m[:, 2] / np.linalg.norm(m[:, 2])
        role = next((r for r in ROLES if float(n @ NORMAL[r]) > 0.99), None)
        if role:
            cands.setdefault(role, []).append((p, m))
    out = {}
    for role, found in cands.items():
        for p, m in sorted(found, key=lambda c: -c[0].shape.area):
            face = _face(role, p, m, parts, asm, t)
            if face.covered.area <= 0.5 * face.outline.area:
                out[role] = face
                inner = _face(role, p, m, parts, asm, t, inside=True)
                if inner.covered.area <= 0.5 * inner.outline.area:     # a drawer's floor: the drawer sits on it
                    out[role + ".in"] = inner
                break
    return out


def _face(role, p, m, parts, asm, t, inside=False):
    up = UP[role]
    right = np.cross(up, NORMAL[role]) * (-1 if inside else 1)     # from inside, the outside's left is on the right
    rot = np.array([[right @ m[:, 0], right @ m[:, 1]], [up @ m[:, 0], up @ m[:, 1]]])
    face = Face(role + (".in" if inside else ""), p.index, rot, np.zeros(2), 0, 0, None, None, inside=inside)
    outline = face.to_view(p.shape)
    x0, y0, x1, y1 = outline.bounds
    face.off = np.array([-x0, -y0])
    face.outline = affinity.translate(outline, -x0, -y0)
    face.w, face.h = x1 - x0, y1 - y0
    face.free = face.outline.buffer(-(t + KEEP_OUT))            # as the maker's mark keeps clear (export.mark_spot)
    face.covered = _covered(face, m, parts, asm, t, right, up)
    if not face.covered.is_empty:
        face.free = face.free.difference(face.covered.buffer(KEEP_OUT))
    lo = (asm.get("inside") or {}).get("lo")
    if lo is not None and role in ("front", "back", "left", "right") and not inside:
        face.floor = lo[2] - m[2, 3] + face.off[1]          # view y = Z . world - Z . origin + offset
    return face


def _covered(face, m, parts, asm, t, right, up):
    """What other parts cover of the face on the closed box, view coordinates (axes right, up): every placed part
    whose material lies wholly outside the face's outer plane (an over-the-top lid's rim in front of a wall); seen from
    inside, every one inside its inner plane but for the fingers it puts into the face (the floor, the side walls'
    ends, a partition). Each as the hull of its outline projected onto the face."""
    n = NORMAL[face.role.split(".")[0]]
    d0 = t + n @ m[:, 3]                       # the outer face: n . x there (n is the matrix's depth column)
    d_in = n @ m[:, 3]                         # the inner face
    regions = []
    for q, ql in zip(parts, asm.get("parts", [])):
        if q.index == face.part or ql.get("group") == "loose" or q.shape is None or q.shape.is_empty:
            continue
        mq = np.asarray(ql["m"], float).reshape(3, 4)
        polys = list(q.shape.geoms) if hasattr(q.shape, "geoms") else [q.shape]
        xy = np.concatenate([np.asarray(g.exterior.coords)[:, :2] for g in polys])
        pts = np.concatenate([np.column_stack([xy, np.full(len(xy), z), np.ones(len(xy))]) for z in (0.0, t)]) @ mq.T
        depth = pts @ n
        # inside: it reaches the inner face (its fingers at most through it) and lies inside; the floor under a lid
        # doesn't reach the lid, so it covers nothing there
        if (face.inside and not (d_in - 0.05 <= depth.max() <= d_in + t + 0.05 and depth.min() < d_in - 0.05)
                or not face.inside and depth.min() < d0 - 0.05):
            continue
        vx = pts @ right - right @ m[:, 3] + face.off[0]
        vy = pts @ up - up @ m[:, 3] + face.off[1]
        regions.append(MultiPoint(np.column_stack([vx, vy])).convex_hull)
    return unary_union(regions).intersection(face.outline) if regions else Polygon()


# ------------------------------------------------------------------ items
def _block(item):
    """(polygons, lines, fill) of an item at its own origin, before it's anchored: text outlines (with their hatch
    lines for "hatch"), a logo's strokes and areas, an imported SVG's lines. Polygons are engraved as outlines on
    LINE, fill on FILL."""
    size = max(0.5, float(item.get("size") or 8.0))
    rot = int(item.get("rot") or 0) % 360
    if item.get("kind") == "logo":
        return _logo(item, size, rot)
    if item.get("kind") == "svg":
        return MultiPolygon(), _svg(item, size, rot), MultiPolygon()
    rows = [r for r in str(item.get("text") or "").split("\n")]
    if not any(r.strip() for r in rows):
        return MultiPolygon(), MultiLineString(), MultiPolygon()
    font = SS.font(SC.FONT_BOLD if item.get("bold") else SC.FONT_REGULAR)
    col = (item.get("anchor") or "c")[-1]
    align = {"l": "left", "r": "right"}.get(col, "center")
    polys = [font.text(r, 0, -k * LINE_GAP * size, size, align=align, tracking=SS.tracking(size))
             for k, r in enumerate(rows) if r.strip()]
    g = unary_union(polys)
    if rot:
        g = affinity.rotate(g, rot, origin=(0, 0))
    hatch = textures.line_hatch(g, HATCH, angles=(45, -45)) if item.get("style") == "hatch" else MultiLineString()
    return g, hatch, MultiPolygon()


def _logo(item, size, rot):
    """A logo from the logos folder, `size` tall and centred on the origin, as (polygons, lines, fill): an SVG's
    strokes; a LightBurn file's strokes, and its filled shapes as fill up to FILL_MAX, above it as polygons with a
    hatch (or as polygons alone for "outline"). Raises ValueError when the file is gone or draws nothing."""
    name = item.get("logo") or ""
    path = SS.logo_path(name) if name.lower().endswith(LOGO_KINDS) else None
    if not path:
        raise ValueError("%s isn't in the logos folder" % (name or "the logo"))
    if name.lower().endswith(".svg"):
        lines = SS.logo(name, 0, 0, size, rot=rot)
        if lines.is_empty:
            raise ValueError("%s draws nothing" % name)
        return MultiPolygon(), lines, MultiPolygon()
    art = lbrnart.load(path)
    if art.empty:
        raise ValueError("%s has nothing to engrave (bitmaps aren't)" % name)
    fit = svgart.fit(art.bounds, size)
    lines, fill = affinity.affine_transform(art.lines, fit), affinity.affine_transform(art.fill, fit)
    if rot:
        lines, fill = affinity.rotate(lines, rot, origin=(0, 0)), affinity.rotate(fill, rot, origin=(0, 0))
    if fill.is_empty:
        return MultiPolygon(), lines, MultiPolygon()
    if item.get("style") == "outline":
        return fill, lines, MultiPolygon()
    if size <= FILL_MAX + 1e-9:
        return MultiPolygon(), lines, fill
    return fill, unary_union([lines, textures.line_hatch(fill, HATCH, angles=(45, -45))]), MultiPolygon()


def _svg(item, size, rot):
    """An imported SVG's lines, `size` tall and centred on the origin; hatched, its closed shapes get the hatch too."""
    lines, rings = svgart.parse(item.get("svg") or "")
    if lines.is_empty:
        return MultiLineString()
    fit = svgart.fit(lines.bounds, size)
    out = affinity.affine_transform(lines, fit)
    if item.get("style") == "hatch" and rings:
        region = affinity.affine_transform(svgart.area(rings), fit)
        if not region.is_empty:
            out = unary_union([out, textures.line_hatch(region, HATCH, angles=(45, -45))])
    return affinity.rotate(out, rot, origin=(0, 0)) if rot else out


def _hole_dims(item):
    """("round", r), ("notch", r) or ("rect", w, h, r) of a hole as drawn on the face (turned a quarter: w and h
    swap)."""
    if item.get("shape") == "notch":
        return "notch", max(1.0, float(item.get("d") or 30) / 2)
    if item.get("shape") == "rect":
        w, h = max(0.5, float(item.get("w") or 10)), max(0.5, float(item.get("h") or 5))
        if int(item.get("rot") or 0) % 180:
            w, h = h, w
        return "rect", w, h, min(max(0.0, float(item.get("r") or 0)), w / 2, h / 2)
    return "round", max(0.25, float(item.get("d") or 6) / 2)


def _hole_poly(dims, cx=0.0, cy=0.0, shrink=0.0):
    if dims[0] in ("round", "notch"):
        return Point(cx, cy).buffer(dims[1] - shrink, quad_segs=32)
    _, w, h, r = dims
    w, h, r = w - 2 * shrink, h - 2 * shrink, max(0.0, r - shrink)
    core = box(cx - w / 2 + r, cy - h / 2 + r, cx + w / 2 - r, cy + h / 2 - r)
    return core.buffer(r, quad_segs=16) if r > 1e-9 else core


def _hole_sub(dims, cx, cy, shrink=0.0):
    """The hole's cut path in the 'bez' format (start, [(c1, c2, end)], closed): a true circle, or a rectangle with
    rounded corners, `shrink` inside the finished size."""
    if dims[0] == "round":
        r = dims[1] - shrink
        k = ARC * r
        pts = [((cx + r, cy + k), (cx + k, cy + r), (cx, cy + r)), ((cx - k, cy + r), (cx - r, cy + k), (cx - r, cy)),
               ((cx - r, cy - k), (cx - k, cy - r), (cx, cy - r)), ((cx + k, cy - r), (cx + r, cy - k), (cx + r, cy))]
        return (cx + r, cy), pts, True
    _, w, h, r = dims
    w, h, r = w - 2 * shrink, h - 2 * shrink, max(0.0, r - shrink)
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    k = ARC * r
    segs = [(None, None, (x1 - r, y0))]
    if r:
        segs.append(((x1 - r + k, y0), (x1, y0 + r - k), (x1, y0 + r)))
    segs.append((None, None, (x1, y1 - r)))
    if r:
        segs.append(((x1, y1 - r + k), (x1 - r + k, y1), (x1 - r, y1)))
    segs.append((None, None, (x0 + r, y1)))
    if r:
        segs.append(((x0 + r - k, y1), (x0, y1 - r + k), (x0, y1 - r)))
    segs.append((None, None, (x0, y0 + r)))
    if r:
        segs.append(((x0, y0 + r - k), (x0 + r - k, y0), (x0 + r, y0)))
    return (x0 + r, y0), segs, True


def _spot(bounds, anchor):
    """The anchor's point on a rectangle (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = bounds
    col, row = (anchor[-1] if anchor[-1] in "lr" else "c"), (anchor[0] if anchor[0] in "tb" else "c")
    return ({"l": x0, "c": (x0 + x1) / 2, "r": x1}[col], {"b": y0, "c": (y0 + y1) / 2, "t": y1}[row])


def place(item, face):
    """The item on the face, view coordinates: (polygons, lines, bounds, fill) or None when it draws nothing. A
    hole's polygon is the hole itself."""
    if item.get("kind") == "hole":
        polys, lines, fill = _hole_poly(_hole_dims(item)), MultiLineString(), MultiPolygon()
    else:
        polys, lines, fill = _block(item)
    geo = [g for g in (polys, lines, fill) if not g.is_empty]
    if not geo:
        return None
    bounds = unary_union(geo).bounds
    anchor = item.get("anchor") if item.get("anchor") in ANCHORS else "c"
    fx, fy = _spot((0, 0, face.w, face.h), anchor)
    ix, iy = _spot(bounds, anchor)
    dx, dy = fx + float(item.get("dx") or 0) - ix, fy + float(item.get("dy") or 0) - iy
    move = lambda g: affinity.translate(g, dx, dy)
    x0, y0, x1, y1 = bounds
    return move(polys), move(lines), (x0 + dx, y0 + dy, x1 + dx, y1 + dy), move(fill)


def _outline_lines(polys):
    return MultiLineString(rings(polys))


def _round(g):
    """Lines as [[x, y], ...] lists, for drawing."""
    return coords_json(lbrn._lines(g), 2)


def _failed(item, error, hole=True):
    """An item's face info when it can't go on the face: red, with why."""
    out = {"id": item.get("id"), "bounds": None, "bad": True, "lines": [], "error": error}
    if hole:
        out["hole"] = True
    return out


def _lifted(got, dy):
    """A placed hole (place's polygons, lines, bounds, fill) moved up by dy."""
    poly, lines, (x0, y0, x1, y1), fill = got
    return affinity.translate(poly, 0, dy), lines, (x0, y0 + dy, x1, y1 + dy), fill


def decorate(parts, asm, faces_req, t, boards=None):
    """The face editor's items as decorations: ({part index: [(layer, lines, or FILL's polygons)]} in part
    coordinates, for the sheets,
    the 3D and LightBurn; {role: face info} for the editor: the face's size, outline, free area and what covers it,
    and per item its bounds, whether it's clear of the edges, and its lines in view coordinates; {role: Face};
    {part index: [(dims, centre)]} the holes, part coordinates, for with_holes; {part index: [(layer, lines)]} what
    the inside faces engrave on the parts' other side, part coordinates). boards: {role: the board's top above
    the inside floor, mm} for the edge connectors' openings on that wall."""
    faces = find(parts, asm, t)
    deco, info, holes, deco_in = {}, {}, {}, {}
    cut_parts = {}                                     # part index: its holes, part coordinates (inside faces avoid them)
    for role, face in faces.items():
        items_out = []
        reqs = (faces_req or {}).get(role, [])
        # the holes first: an engraving across one is red
        cut = []
        board = (boards or {}).get(role)
        for item in (it for it in reqs if it.get("kind") == "hole"):
            if face.inside:
                items_out.append(_failed(item, "a hole goes through: put it on the outside"))
                continue
            got = place(item, face)
            if not got:
                continue
            if item.get("shape") == "notch":              # its centre on the top or bottom edge, by the anchor's row
                row = (item.get("anchor") or "c")[0]
                if row not in "tb":
                    items_out.append(_failed(item, "drag it onto the top or bottom edge"))
                    continue
                got = _lifted(got, (face.h if row == "t" else 0.0) - (got[2][1] + got[2][3]) / 2)
            if item.get("board"):                      # an edge connector: at the board, only its x is the item's
                if face.floor is None or not isinstance(board, (int, float)):
                    items_out.append(_failed(item, "set the board's height on this wall" if face.floor is not None
                                             else "only on a wall of a box with a floor"))
                    continue
                got = _lifted(got, face.floor + board + float(item.get("lift", -EDGE_AIR)) - got[2][1])
            cut.append((item, got[0], got[2]))
        here = []
        for item, poly, bounds in cut:
            others = [q for it, q, _b in cut if it is not item]
            dims = _hole_dims(item)
            near = any(poly.distance(q) < HOLE_WEB - 1e-6 for q in others)
            if dims[0] == "notch":
                shown = poly.intersection(face.outline)
                bad = near or not _notch_ok(poly, dims[1], face, t)
            else:
                shown = poly
                bad = near or not face.free.contains(poly)
            centre = face.to_part(Point((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2))
            holes.setdefault(face.part, []).append((_turned(dims, face), (centre.x, centre.y)))
            here.append(shown)
            items_out.append({"id": item.get("id"), "bounds": [round(v, 2) for v in shown.bounds], "bad": bad,
                              "hole": True, "lines": _round(_outline_lines(shown))})
        if here:
            cut_parts[face.part] = unary_union([cut_parts.get(face.part, Polygon())] + [face.to_part(g) for g in here])
        elif face.inside and face.part in cut_parts:     # the outside's holes, seen from inside
            here = [face.to_view(cut_parts[face.part])]
        holes_view = unary_union(here).buffer(1.0) if here else None
        for item in (it for it in reqs if it.get("kind") != "hole"):
            try:
                got = place(item, face)
            except ValueError as e:                     # an imported file that isn't SVG, a logo that's gone
                items_out.append(_failed(item, str(e), hole=False))
                continue
            if got is None:
                items_out.append({"id": item.get("id"), "bounds": None, "bad": False, "lines": []})
                continue
            polys, lines, bounds, fill = got
            engraved = unary_union([g for g in (_outline_lines(polys), lines) if not g.is_empty])
            bad = not face.free.contains(box(*bounds)) or (holes_view is not None and (
                holes_view.intersects(engraved) or holes_view.intersects(fill)))
            out = (deco_in if face.inside else deco).setdefault(face.part, [])
            if not engraved.is_empty:
                out.append((M.LINE, face.to_part(engraved)))
            if not fill.is_empty:                      # a small logo's filled shapes (FILL outlines and fills them)
                out.append((M.FILL, face.to_part(fill)))
            items_out.append({"id": item.get("id"), "bounds": [round(v, 2) for v in bounds], "bad": bad,
                              "lines": _round(engraved), "fill": _rings(fill)})
        info[role] = {"part": face.part, "w": round(face.w, 2), "h": round(face.h, 2),
                      "outline": _rings(face.outline), "free": _rings(face.free), "covered": _rings(face.covered),
                      "items": items_out, "fixed": [],
                      "floor": None if face.floor is None else round(face.floor, 2),
                      "board": None if face.floor is None or not isinstance(board, (int, float))
                      else round(face.floor + board, 2)}
    return deco, info, faces, holes, deco_in


def _notch_ok(disc, r, face, t):
    """A thumb notch cuts a half disc out of a plain, straight edge (no finger joints there), clear of the joints at
    its sides and leaving the wood's keep-out at the far edge."""
    half = disc.intersection(face.outline).area
    x0, _y0, x1, _y1 = face.free.bounds if not face.free.is_empty else (0, 0, 0, 0)
    dx0, _dy0, dx1, _dy1 = disc.bounds
    return (abs(half - math.pi * r * r / 2) < 0.03 * math.pi * r * r / 2 and dx0 >= x0 - 1e-6 and dx1 <= x1 + 1e-6
            and 2 * r <= face.h - (t + KEEP_OUT))


def _notched(subs, cut):
    """The cut paths with the closed one `cut` crosses (the outline) cut back by it, as a polyline; None when no closed
    path crosses it."""
    out = list(subs)
    for k, sp in enumerate(subs):
        if not sp[2]:
            continue
        ring = svgpath.flatten(sp, 6)
        if len(ring) < 4:
            continue
        poly = Polygon(ring).buffer(0)
        if poly.intersects(cut) and not poly.contains(cut):
            left = poly.difference(cut)
            left = max(left.geoms, key=lambda g: g.area) if hasattr(left, "geoms") else left
            pts = [tuple(c) for c in left.exterior.coords]
            out[k] = (pts[0], [(None, None, c) for c in pts[1:]], True)
            return out
    return None


def _turned(dims, face):
    """A hole's dimensions in part coordinates: the face's view is the part turned by quarters, so w and h swap
    when it's turned a quarter."""
    if dims[0] == "rect" and abs(face.rot[0, 0]) < 0.5:
        return ("rect", dims[2], dims[1], dims[3])
    return dims


def with_holes(parts, holes, per_axis, burn):
    """The parts with the face editor's holes cut, as copies (the parts are cached between builds). Each hole goes
    into the part's shape (the 3D, the maker's mark) and its cut paths: drawn at its finished size when the export
    compensates the kerf per axis, else `burn` inside it, as boxes.py draws its own holes."""
    if not holes:
        return parts
    out = list(parts)
    shrink = 0.0 if per_axis else burn
    for i, hs in holes.items():
        p = copy.copy(parts[i])
        p.subpaths = {k: list(v) for k, v in p.subpaths.items()}
        cut = []
        for dims, (cx, cy) in hs:
            if dims[0] == "notch":                     # the outline itself is cut back, not a hole added
                notched = _notched(p.subpaths[M.CUT], _hole_poly(dims, cx, cy, shrink))
                if notched is None:
                    continue
                p.subpaths[M.CUT] = notched
            else:
                p.subpaths[M.CUT].append(_hole_sub(dims, cx, cy, shrink))
            cut.append(_hole_poly(dims, cx, cy))
        region = unary_union(cut)
        p.shape = p.shape.difference(region)
        if getattr(p, "_outline_from_cuts", False):
            p._outline = None
        elif getattr(p, "_outline", None) is not None:
            p._outline = p._outline.difference(unary_union([_hole_poly(d, x, y, shrink) for d, (x, y) in hs]))
        out[i] = p
    return out


def footprints(deco):
    """{part index: the area its items take (their boxes, part coordinates)}, for the maker's mark to keep clear of."""
    return {i: unary_union([box(*g.bounds) for _, g in items if not g.is_empty]) for i, items in deco.items()}


def show_fixed(info, faces, deco):
    """What else is engraved on a face (the maker's mark, LINE), in view coordinates, for the editor to show."""
    for role, face in faces.items():
        if face.inside:                                # the mark and labels are on the outside
            continue
        lines = [face.to_view(g) for layer, g in deco.get(face.part, []) if layer == M.LINE and not g.is_empty]
        info[role]["fixed"] = [ln for g in lines for ln in _round(g)]


def _rings(g):
    """Polygon rings as [[x, y], ...] lists (outer rings and holes alike), for drawing."""
    return coords_json(rings(g), 2)


def logos():
    """The logos folder's logos on this PC, .svg and .lbrn2 (serve.py hands them over; none without it). The stamp
    case lists its own: SVGs only."""
    return SS.logo_files(LOGO_KINDS, key=str.lower)


PREVIEW = 0.004                  # simplify the library's previews by this much of the logo's size


def _d(g, close):
    """SVG path data of lines (or of polygons' rings, closed), y up as drawn."""
    return "".join("M" + "L".join("%.2f %.2f" % c for c in r.coords) + ("Z" if close else "")
                   for r in (rings(g) if close else lbrn._lines(g)))


def library():
    """The logo library for the face editor's Add logo: per logo its file, its size as drawn (w, h, mm), whether it
    has filled shapes, and a preview (path data of its strokes and of its filled areas, y up); a file that can't be
    read comes with its error instead. Files read before are read again when they changed (the worker has just copied
    the folder again)."""
    out = []
    for name in logos():
        e = {"logo": name, "label": os.path.splitext(name)[0]}
        try:
            if name.lower().endswith(".svg"):
                lines, fill = SS.logo_raw(SS.logo_path(name)), MultiPolygon()
            else:
                art = lbrnart.load(SS.logo_path(name))
                lines, fill = art.lines, art.fill
            geo = [g for g in (lines, fill) if not g.is_empty]
            if not geo:
                raise ValueError("nothing to engrave")
            x0, y0, x1, y1 = unary_union(geo).bounds
            tol = PREVIEW * max(x1 - x0, y1 - y0)
            e.update(w=round(x1 - x0, 2), h=round(y1 - y0, 2), box=[round(v, 2) for v in (x0, y0, x1, y1)],
                     fills=not fill.is_empty, lines=_d(lines.simplify(tol), False), fill=_d(fill.simplify(tol), True))
        except (OSError, ValueError, TypeError) as err:
            e["error"] = str(err) or type(err).__name__
        out.append(e)
    return out


def problems(info):
    """Text for the export's refusal: items that run into an edge or a finger joint, files that aren't SVG."""
    return ["%s on the %s %s" % ("A hole" if it.get("hole") else "An item", role,
                                 "can't be read: " + it["error"] if it.get("error")
                                 else "runs into its edge, a finger joint, a hole or what covers it")
            for role, f in info.items() for it in f["items"] if it["bad"]]

