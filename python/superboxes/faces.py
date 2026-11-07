"""Faces: what the face editor puts on a box's outside (.grill/face-editor.md).

A face is a role on the closed box - top, bottom, front, back, left, right - held by the placed part whose engraved
side looks that way. The assembly turns every part's engraved side (the side up on the laser) out of the box and
places it right-handed, so a part's own drawing, seen from outside, is never mirrored: whatever is drawn in part
coordinates and engraved face up reads right on the finished box.

The editor works in the face's view: seen from outside, x to the right, y up, where up is the box's up for a wall,
its back for the top and its front for the bottom (tip the box toward you to read it); (0, 0) is the lower-left corner
of the part's outline. Items are mm in that view:

    {"id", "kind": "text" | "logo" | "svg", "text", "logo" (a house logo's file name), "svg" (an imported SVG's
     text, svgart.py), "name" (its file name), "size" (cap height, or a logo's or SVG's height, mm),
     "bold", "style": "outline" | "hatch", "rot": 0 | 90 | 180 | 270,
     "anchor": "tl" | "t" | "tr" | "l" | "c" | "r" | "bl" | "b" | "br", "dx", "dy"}

The item's own anchor point (the same spot of its bounding box) sits (dx, dy) from the face's anchor point, so it
keeps its place when the box changes size; text lines align to the anchor's side. An item must stay inside the free
area: the outline less thickness + 1.5 mm from every edge (finger joints), as for the maker's mark.
"""
from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import MultiLineString, MultiPoint, MultiPolygon, Polygon, box
from shapely.ops import unary_union

from evlaser import lbrn, machine as M, textures

from . import svgart
from .stampcase import config as SC, shapes as SS

X, Y, Z = np.eye(3)
NORMAL = {"top": Z, "bottom": -Z, "front": -Y, "back": Y, "left": -X, "right": X}
UP = {"top": Y, "bottom": -Y, "front": Z, "back": Z, "left": Z, "right": Z}
ROLES = tuple(NORMAL)
ANCHORS = ("tl", "t", "tr", "l", "c", "r", "bl", "b", "br")
HATCH = SC.TITLE_HATCH           # mm between hatch lines, +-45 degrees (the stamp case's lid title)
LINE_GAP = 1.4                   # line pitch of multi-line text, in cap heights
KEEP_OUT = 1.5                   # mm beyond the thickness kept clear along every edge (finger joints)


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

    def to_view(self, g):
        a, b, c, d = self.rot.ravel()
        return affinity.affine_transform(g, [a, b, c, d, *self.off])

    def to_part(self, g):
        inv = np.linalg.inv(self.rot)
        o = -inv @ self.off
        a, b, c, d = inv.ravel()
        return affinity.affine_transform(g, [a, b, c, d, *o])


def find(parts, asm, t):
    """{role: Face} for the closed box: per role the biggest placed part whose engraved side looks that way and that
    is at least half in view (an inner guide behind a side wall isn't a face). A part the assembly could only place
    mirrored (assembly._turn_not_mirror) is left out: it would have to be cut mirrored for its engraving to face out."""
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
                break
    return out


def _face(role, p, m, parts, asm, t):
    up = UP[role]
    right = np.cross(up, NORMAL[role])
    rot = np.array([[right @ m[:, 0], right @ m[:, 1]], [up @ m[:, 0], up @ m[:, 1]]])
    face = Face(role, p.index, rot, np.zeros(2), 0, 0, None, None)
    outline = face.to_view(p.shape)
    x0, y0, x1, y1 = outline.bounds
    face.off = np.array([-x0, -y0])
    face.outline = affinity.translate(outline, -x0, -y0)
    face.w, face.h = x1 - x0, y1 - y0
    face.free = face.outline.buffer(-(t + KEEP_OUT))            # as the maker's mark keeps clear (export.mark_spot)
    face.covered = _covered(face, m, parts, asm, t)
    if not face.covered.is_empty:
        face.free = face.free.difference(face.covered.buffer(KEEP_OUT))
    return face


def _covered(face, m, parts, asm, t):
    """What other parts cover of the face on the closed box, view coordinates: every placed part whose material lies
    wholly outside the face's outer plane (an over-the-top lid's rim in front of a wall), as the hull of its outline
    projected onto the face."""
    n = NORMAL[face.role]
    up = UP[face.role]
    right = np.cross(up, n)
    d0 = t + n @ m[:, 3]                       # the outer face: n . x there (n is the matrix's depth column)
    regions = []
    for q, ql in zip(parts, asm.get("parts", [])):
        if q.index == face.part or ql.get("group") == "loose" or q.shape is None or q.shape.is_empty:
            continue
        mq = np.asarray(ql["m"], float).reshape(3, 4)
        polys = list(q.shape.geoms) if hasattr(q.shape, "geoms") else [q.shape]
        xy = np.concatenate([np.asarray(g.exterior.coords)[:, :2] for g in polys])
        pts = np.concatenate([np.column_stack([xy, np.full(len(xy), z), np.ones(len(xy))]) for z in (0.0, t)]) @ mq.T
        if (pts @ n).min() < d0 - 0.05:
            continue
        vx = pts @ right - right @ m[:, 3] + face.off[0]
        vy = pts @ up - up @ m[:, 3] + face.off[1]
        regions.append(MultiPoint(np.column_stack([vx, vy])).convex_hull)
    return unary_union(regions).intersection(face.outline) if regions else Polygon()


# ------------------------------------------------------------------ items
def _block(item):
    """(polygons, lines) of an item at its own origin, before it's anchored: text outlines (with their hatch lines
    for "hatch"), or a logo's strokes."""
    size = max(0.5, float(item.get("size") or 8.0))
    rot = int(item.get("rot") or 0) % 360
    if item.get("kind") == "logo":
        lines = SS.logo(item.get("logo") or "", 0, 0, size, rot=rot)
        return MultiPolygon(), lines
    if item.get("kind") == "svg":
        return MultiPolygon(), _svg(item, size, rot)
    rows = [r for r in str(item.get("text") or "").split("\n")]
    if not any(r.strip() for r in rows):
        return MultiPolygon(), MultiLineString()
    font = SS.font(SC.FONT_BOLD if item.get("bold") else SC.FONT_REGULAR)
    col = (item.get("anchor") or "c")[-1]
    align = {"l": "left", "r": "right"}.get(col, "center")
    polys = [font.text(r, 0, -k * LINE_GAP * size, size, align=align, tracking=SS.tracking(size))
             for k, r in enumerate(rows) if r.strip()]
    g = unary_union(polys)
    if rot:
        g = affinity.rotate(g, rot, origin=(0, 0))
    hatch = textures.line_hatch(g, HATCH, angles=(45, -45)) if item.get("style") == "hatch" else MultiLineString()
    return g, hatch


def _svg(item, size, rot):
    """An imported SVG's lines, `size` tall and centred on the origin; hatched, its closed shapes get the hatch too."""
    lines, rings = svgart.parse(item.get("svg") or "")
    if lines.is_empty:
        return MultiLineString()
    x0, y0, x1, y1 = lines.bounds
    k = size / (y1 - y0) if y1 > y0 else size / max(x1 - x0, 1e-9)
    fit = [k, 0, 0, k, -(x0 + x1) / 2 * k, -(y0 + y1) / 2 * k]
    out = affinity.affine_transform(lines, fit)
    if item.get("style") == "hatch" and rings:
        region = affinity.affine_transform(svgart.area(rings), fit)
        if not region.is_empty:
            out = unary_union([out, textures.line_hatch(region, HATCH, angles=(45, -45))])
    return affinity.rotate(out, rot, origin=(0, 0)) if rot else out


def _spot(bounds, anchor):
    """The anchor's point on a rectangle (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = bounds
    col, row = (anchor[-1] if anchor[-1] in "lr" else "c"), (anchor[0] if anchor[0] in "tb" else "c")
    return ({"l": x0, "c": (x0 + x1) / 2, "r": x1}[col], {"b": y0, "c": (y0 + y1) / 2, "t": y1}[row])


def place(item, face):
    """The item on the face, view coordinates: (polygons, lines, bounds) or None when it draws nothing."""
    polys, lines = _block(item)
    geo = [g for g in (polys, lines) if not g.is_empty]
    if not geo:
        return None
    bounds = unary_union(geo).bounds
    anchor = item.get("anchor") if item.get("anchor") in ANCHORS else "c"
    fx, fy = _spot((0, 0, face.w, face.h), anchor)
    ix, iy = _spot(bounds, anchor)
    dx, dy = fx + float(item.get("dx") or 0) - ix, fy + float(item.get("dy") or 0) - iy
    move = lambda g: affinity.translate(g, dx, dy)
    x0, y0, x1, y1 = bounds
    return move(polys), move(lines), (x0 + dx, y0 + dy, x1 + dx, y1 + dy)


def _outline_lines(polys):
    return MultiLineString([r for q in lbrn._polys(polys) for r in [q.exterior, *q.interiors]]) if not polys.is_empty \
        else MultiLineString()


def _round(g):
    return [[[round(x, 2), round(y, 2)] for x, y in ls.coords] for ls in lbrn._lines(g)]


def decorate(parts, asm, faces_req, t):
    """The face editor's items as decorations: ({part index: [(layer, lines)]} in part coordinates, for the sheets,
    the 3D and LightBurn; {role: face info} for the editor: the face's size, outline, free area and what covers it,
    and per item its bounds, whether it's clear of the edges, and its lines in view coordinates; {role: Face})."""
    faces = find(parts, asm, t)
    deco, info = {}, {}
    for role, face in faces.items():
        items_out = []
        for item in (faces_req or {}).get(role, []):
            try:
                got = place(item, face)
            except ValueError as e:                     # an imported file that isn't SVG
                items_out.append({"id": item.get("id"), "bounds": None, "bad": True, "lines": [], "error": str(e)})
                continue
            if got is None:
                items_out.append({"id": item.get("id"), "bounds": None, "bad": False, "lines": []})
                continue
            polys, lines, bounds = got
            engraved = unary_union([g for g in (_outline_lines(polys), lines) if not g.is_empty])
            bad = not face.free.contains(box(*bounds))
            deco.setdefault(face.part, []).append((M.LINE, face.to_part(engraved)))
            items_out.append({"id": item.get("id"), "bounds": [round(v, 2) for v in bounds], "bad": bad,
                              "lines": _round(engraved)})
        info[role] = {"part": face.part, "w": round(face.w, 2), "h": round(face.h, 2),
                      "outline": _rings(face.outline), "free": _rings(face.free), "covered": _rings(face.covered),
                      "items": items_out, "fixed": []}
    return deco, info, faces


def footprints(deco):
    """{part index: the area its items take (their boxes, part coordinates)}, for the maker's mark to keep clear of."""
    return {i: unary_union([box(*g.bounds) for _, g in items if not g.is_empty]) for i, items in deco.items()}


def show_fixed(info, faces, deco):
    """What else is engraved on a face (the maker's mark, LINE), in view coordinates, for the editor to show."""
    for role, face in faces.items():
        lines = [face.to_view(g) for layer, g in deco.get(face.part, []) if layer == M.LINE and not g.is_empty]
        info[role]["fixed"] = [ln for g in lines for ln in _round(g)]


def _rings(g):
    """Polygon rings as [[x, y], ...] lists (outer rings and holes alike), for drawing."""
    if g is None or g.is_empty:
        return []
    polys = list(g.geoms) if hasattr(g, "geoms") else [g]
    return [[[round(x, 2), round(y, 2)] for x, y in r.coords] for q in polys if isinstance(q, Polygon)
            for r in [q.exterior, *q.interiors]]


def logos():
    """The house logos on this PC (serve.py hands them over; none without it)."""
    return SS.logo_files()


def problems(info):
    """Text for the export's refusal: items that run into an edge or a finger joint, files that aren't SVG."""
    return ["An item on the %s %s" % (role, "can't be read: " + it["error"] if it.get("error")
                                      else "runs into its edge, a finger joint or what covers it")
            for role, f in info.items() for it in f["items"] if it["bad"]]

