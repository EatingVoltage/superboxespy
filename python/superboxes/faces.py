"""Faces: what the face editor puts on a box's outside (.grill/face-editor.md).

A face is a role on the closed box - top, bottom, front, back, left, right - held by the placed part whose engraved
side looks that way. The assembly turns every part's engraved side (the side up on the laser) out of the box and
places it right-handed, so a part's own drawing, seen from outside, is never mirrored: whatever is drawn in part
coordinates and engraved face up reads right on the finished box.

The editor works in the face's view: seen from outside, x to the right, y up, where up is the box's up for a wall,
its back for the top and its front for the bottom (tip the box toward you to read it); (0, 0) is the lower-left corner
of the part's outline. Items are mm in that view:

    {"id", "kind": "text" | "logo", "text", "logo" (a house logo's file name), "size" (cap height or logo height, mm),
     "bold", "style": "outline" | "hatch", "rot": 0 | 90 | 180 | 270,
     "anchor": "tl" | "t" | "tr" | "l" | "c" | "r" | "bl" | "b" | "br", "dx", "dy"}

The item's own anchor point (the same spot of its bounding box) sits (dx, dy) from the face's anchor point, so it
keeps its place when the box changes size; text lines align to the anchor's side. An item must stay inside the free
area: the outline less thickness + 1.5 mm from every edge (finger joints), as for the maker's mark.
"""
from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import MultiLineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

from evlaser import lbrn, machine as M, textures

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

    def to_view(self, g):
        a, b, c, d = self.rot.ravel()
        return affinity.affine_transform(g, [a, b, c, d, *self.off])

    def to_part(self, g):
        inv = np.linalg.inv(self.rot)
        o = -inv @ self.off
        a, b, c, d = inv.ravel()
        return affinity.affine_transform(g, [a, b, c, d, *o])


def find(parts, asm, t):
    """{role: Face} for the closed box: per role the biggest placed part whose engraved side looks that way."""
    best = {}
    for p, pl in zip(parts, asm.get("parts", [])):
        if pl.get("group") == "loose" or pl.get("kind") != "wall" or p.shape is None or p.shape.is_empty:
            continue
        m = np.asarray(pl["m"], float).reshape(3, 4)
        n = m[:, 2] / np.linalg.norm(m[:, 2])
        role = next((r for r in ROLES if float(n @ NORMAL[r]) > 0.99), None)
        if role and (role not in best or p.shape.area > best[role][0].shape.area):
            best[role] = (p, m)
    out = {}
    for role, (p, m) in best.items():
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
        out[role] = face
    return out


# ------------------------------------------------------------------ items
def _block(item):
    """(polygons, lines) of an item at its own origin, before it's anchored: text outlines (with their hatch lines
    for "hatch"), or a logo's strokes."""
    size = max(0.5, float(item.get("size") or 8.0))
    rot = int(item.get("rot") or 0) % 360
    if item.get("kind") == "logo":
        lines = SS.logo(item.get("logo") or "", 0, 0, size, rot=rot)
        return MultiPolygon(), lines
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
    the 3D and LightBurn, and {role: face info} for the editor: the face's size, outline and free area, and per item
    its bounds, whether it's clear of the edges, and its lines in view coordinates)."""
    faces = find(parts, asm, t)
    deco, info = {}, {}
    for role, face in faces.items():
        items_out = []
        for item in (faces_req or {}).get(role, []):
            got = place(item, face)
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
                      "outline": _rings(face.outline), "free": _rings(face.free), "items": items_out}
    return deco, info


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
    """Text for the export's refusal: items that run into an edge or a finger joint."""
    return ["An item on the %s runs into its edge or a finger joint" % role
            for role, f in info.items() for it in f["items"] if it["bad"]]

