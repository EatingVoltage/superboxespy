"""3D assembly: where every part sits in the finished box, and which parts collide.

A part is placed by a 3x4 matrix that maps its sheet coordinates (px, py) plus the material depth z (0 = the
face down on the laser bed, t = the engraved top face) into the box. For a wall it's built from the frame boxes.py
reports at the wall's inner corner (capture._record_walls): the wall's inner face goes where the box needs it,
and the slab grows outward by the thickness, so the engraved face looks out of the box.

Rule for the axes: seen from outside the box, the wall's u axis points right, v up and the normal N at the viewer.
That keeps every placement right-handed and puts engravings (labels, the maker's mark) on the outside.

Per box type an assembler returns the placement of each part it knows; anything it doesn't know is laid out flat
beside the box ("loose") so nothing disappears silently.
"""
import math

import numpy as np
import shapely

X, Y, Z = np.eye(3)


def rect(p):
    """The part's rectangularWall record, or None."""
    return next((w for w in p.walls if w["kind"] == "rect"), None)


def wall_matrix(wall, origin, u, v, n):
    """3x4 matrix for a wall whose inner corner (0, 0) goes to `origin`, wall u -> u, wall v -> v, depth -> n."""
    a, b, c, d, e, f = wall["frame"]
    minv = np.linalg.inv(np.array([[a, b], [d, e]]))
    uv = np.column_stack([u, v]) @ minv                    # piece xy -> world (3x2)
    t = np.asarray(origin, float) - uv @ np.array([c, f])
    return np.column_stack([uv[:, 0], uv[:, 1], np.asarray(n, float), t])


def flat_matrix(x, y, rot=0):
    """Part lying on the floor at sheet position (x, y): like the sheet, seen from above."""
    r = np.radians(rot)
    ca, sa = np.cos(r), np.sin(r)
    return np.array([[ca, -sa, 0, x], [sa, ca, 0, y], [0, 0, 1, 0]], float)


def _place(kind, m, explode=(0, 0, 0), group="body", motion=None):
    return {"kind": kind, "m": [round(float(v), 5) for v in np.asarray(m).ravel()],
            "explode": [round(float(v), 4) for v in explode], "group": group, "motion": motion}


def _cavity(lo, hi, cells=(), front=None, back=None):
    """The clear inside of the closed box in world coordinates, for the 3D's dimensions. cells: compartments (_cell);
    front/back: inside height at the front and back of a sloped box."""
    out = {"lo": [round(float(v), 3) for v in lo], "hi": [round(float(v), 3) for v in hi], "cells": list(cells)}
    if front is not None:
        out["front"], out["back"] = round(float(front), 3), round(float(back), 3)
    return out


def _cell(lo, hi, size):
    """A compartment: its clear opening or floor as a box (lo, hi; flat in one axis) and its clear size."""
    r = lambda vs: [round(float(v), 3) for v in vs]
    return {"lo": r(lo), "hi": r(hi), "size": r(size)}


def _regions(hwalls, vwalls, lx, ly):
    """TrayLayout compartments: grid cells (row, col) joined where no wall separates them. Row 0 is the top row;
    hwalls[k][c] is the wall on top of row k in column c, vwalls[r][k] the wall left of column k in row r."""
    parent = {(r, c): (r, c) for r in range(ly) for c in range(lx)}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for r in range(ly):
        for c in range(lx):
            if c + 1 < lx and not vwalls[r][c + 1]:
                parent[find((r, c))] = find((r, c + 1))
            if r + 1 < ly and not hwalls[r + 1][c]:
                parent[find((r, c))] = find((r + 1, c))
    groups = {}
    for cell in parent:
        groups.setdefault(find(cell), []).append(cell)
    return sorted(groups.values())


# ------------------------------------------------------------------ box types
def abox(parts, t, attrs=None):
    """ABox: front/back walls (F side edges), left/right walls (f side edges), bottom 'ffff'. boxes.py labels
    every lid part ("lid top", "lid brim", ...) and none of the body, so unlabeled walls are the body; lid parts
    stay loose for now. The cavity is x * y * h with its corner at the origin, Z up."""
    body = [(p, rect(p)) for p in parts if rect(p) and not p.labels]
    plates = [o for o in body if o[1]["edges"].lower() == "ffff"]
    fb = [o for o in body if o[1]["edges"][1] == "F" and o[1]["edges"][3] == "F" and o not in plates]
    lr = [o for o in body if o[1]["edges"][1] == "f" and o[1]["edges"][3] == "f" and o not in plates]
    if len(fb) != 2 or len(lr) != 2:
        return {}
    x, h = fb[0][1]["x"], fb[0][1]["y"]
    y = lr[0][1]["x"]
    e = max(x, y, h) * 0.35   # explode distance at the slider's end
    out = {
        fb[0][0].index: _place("wall", wall_matrix(fb[0][1], (0, 0, 0), X, Z, -Y), -Y * e),          # front
        fb[1][0].index: _place("wall", wall_matrix(fb[1][1], (x, y, 0), -X, Z, Y), Y * e),           # back
        lr[0][0].index: _place("wall", wall_matrix(lr[0][1], (0, y, 0), -Y, Z, -X), -X * e),         # left
        lr[1][0].index: _place("wall", wall_matrix(lr[1][1], (x, 0, 0), Y, Z, X), X * e),            # right
    }
    if plates:
        out[plates[0][0].index] = _place("wall", wall_matrix(plates[0][1], (x, 0, 0), -X, Y, -Z), -Z * e)  # bottom
    return {"parts": out, "size": [x, y, h], "inside": _cavity((0, 0, 0), (x, y, h))}


def _by_label(parts, prefix):
    return [p for p in parts if p.name.startswith(prefix) and rect(p)]


def _cumulative(sections, t):
    """Positions of the dividers between sections: start of each divider's slab."""
    out, pos = [], 0.0
    for s in sections[:-1]:
        pos += s
        out.append(pos)
        pos += t
    return out


def typetray(parts, t, attrs):
    """TypeTray: bottom, front, back (drawn mirrored), left/right side, inner x walls between the rows, inner y
    walls between the columns. Inner walls are half-lapped (slots from the top in x walls, from the bottom in y).
    Positions along a wall are measured from its u = 0 end, so every x-wall runs u -> +X and every y-wall u -> +Y
    (the right side's holes are drawn mirrored: u -> -Y). Mirrored drawings give left-handed placements - fine."""
    sx, sy = attrs.get("sx"), attrs.get("sy")
    one = lambda prefix: next(iter(_by_label(parts, prefix)), None)
    bottom, front, back, left, right = (one(n) for n in ("bottom", "front", "back", "left side", "right side"))
    if not (sx and sy and front and back and left and right):
        return {}
    x = sum(sx) + t * (len(sx) - 1)
    y = sum(sy) + t * (len(sy) - 1)
    h = rect(front)["y"]
    e = max(x, y, h) * 0.35
    out = {
        front.index: _place("wall", wall_matrix(rect(front), (0, 0, 0), X, Z, -Y), -Y * e),
        back.index: _place("wall", wall_matrix(rect(back), (0, y, 0), X, Z, Y), Y * e),
        left.index: _place("wall", wall_matrix(rect(left), (0, 0, 0), Y, Z, -X), -X * e),
        right.index: _place("wall", wall_matrix(rect(right), (x, y, 0), -Y, Z, X), X * e),
    }
    if bottom:
        out[bottom.index] = _place("wall", wall_matrix(rect(bottom), (0, 0, 0), X, Y, -Z), -Z * e)
    for p, yy in zip(_by_label(parts, "inner x"), _cumulative(sy, t)):
        out[p.index] = _place("wall", wall_matrix(rect(p), (0, yy, 0), X, Z, Y), Z * e * 1.3)
    for p, xx in zip(_by_label(parts, "inner y"), _cumulative(sx, t)):
        out[p.index] = _place("wall", wall_matrix(rect(p), (xx, 0, 0), Y, Z, X), Z * e * 1.9)
    starts = lambda secs: [sum(secs[:k]) + k * t for k in range(len(secs))]
    cells = [_cell((x0, y0, 0), (x0 + w, y0 + d, 0), (w, d))
             for x0, w in zip(starts(sx), sx) for y0, d in zip(starts(sy), sy)] if len(sx) * len(sy) > 1 else []
    return {"parts": out, "size": [x, y, h], "inside": _cavity((0, 0, 0), (x, y, h), cells=cells)}


def slidingdrawer(parts, t, attrs):
    """SlidingDrawer: an outer case open at the front (Y = 0) and a drawer inside it with `play` all round, its
    front panel flush with the opening. Outer cavity x * y * h; the drawer rests on the case bottom and slides
    out along -Y."""
    outer_bottom, outer_top = (next(iter(_by_label(parts, n)), None) for n in ("out box bottom", "out box top"))
    out_walls = _by_label(parts, "out box wall")
    in_walls = _by_label(parts, "in box wall")
    in_bottom = next(iter(_by_label(parts, "in box bottom")), None)
    if not (outer_bottom and outer_top and len(out_walls) == 3 and len(in_walls) == 4 and in_bottom):
        return {}
    y, x = rect(outer_bottom)["x"], rect(outer_bottom)["y"]
    h = rect(out_walls[0])["y"]
    p = attrs.get("play", 0.15) * t
    side_l, side_r, back = out_walls
    e = max(x, y, h) * 0.35
    out = {
        outer_bottom.index: _place("wall", wall_matrix(rect(outer_bottom), (0, 0, 0), Y, X, -Z), -Z * e),
        outer_top.index: _place("wall", wall_matrix(rect(outer_top), (0, 0, h), Y, X, Z), Z * e),
        side_l.index: _place("wall", wall_matrix(rect(side_l), (0, 0, 0), Y, Z, -X), -X * e),
        side_r.index: _place("wall", wall_matrix(rect(side_r), (x, 0, 0), Y, Z, X), X * e),
        back.index: _place("wall", wall_matrix(rect(back), (0, y, 0), X, Z, Y), Y * e),
    }
    d_back, d_left, d_right, d_front = in_walls
    x2, hi = rect(d_back)["x"], rect(d_back)["y"]
    y2 = rect(d_left)["x"]
    ox, oy, oz = p + t, t, t                     # drawer cavity corner: front panel flush with the opening
    slide = {"type": "slide", "dir": [0, -1, 0], "max": round(y2 * 0.75, 2)}
    de = -Y * e * 0.6                            # the drawer comes apart in front of the case
    drawer = {
        d_back.index: _place("wall", wall_matrix(rect(d_back), (ox, oy + y2, oz), X, Z, Y), de + Y * e * 0.3, "drawer", slide),
        d_left.index: _place("wall", wall_matrix(rect(d_left), (ox, oy, oz), Y, Z, -X), de - X * e * 0.4, "drawer", slide),
        d_right.index: _place("wall", wall_matrix(rect(d_right), (ox + x2, oy, oz), Y, Z, X), de + X * e * 0.4, "drawer", slide),
        d_front.index: _place("wall", wall_matrix(rect(d_front), (ox, oy, oz), X, Z, -Y), de - Y * e * 0.4, "drawer", slide),
        in_bottom.index: _place("wall", wall_matrix(rect(in_bottom), (ox, oy, oz), Y, X, -Z), de - Z * e * 0.4, "drawer", slide),
    }
    out.update(drawer)
    # inside = what the drawer holds
    return {"parts": out, "size": [x, y, h], "inside": _cavity((ox, oy, oz), (ox + x2, oy + y2, oz + hi))}


def _named(parts, word):
    return [p for p in parts if word in p.name and rect(p)]


def hobbycase(parts, t, attrs):
    """HobbyCase, standing upright: X width, Z height, Y depth from the front (Y = 0) to the back panel.
    The back panel ("base plate") carries the shelf slots and the slots of the double walls between columns;
    outer walls, top and bottom reach to the front, the inner double walls, shelves and rails are inset 2 t.
    Which slot gets a shelf and which a rail set is the builder's choice: shelves are spread evenly here."""
    unit_w, unit_h = attrs.get("unit_w"), attrs.get("unit_h")
    rows, shelves_n = attrs.get("rows"), attrs.get("shelves_n")
    back = next(iter(_named(parts, "base plate")), None)
    bottom = next(iter(_named(parts, "bottom (")), None)
    top = next(iter(_named(parts, "top (")), None)
    left = next(iter(_named(parts, "left")), None)
    right = next(iter(_named(parts, "right")), None)
    inner = _named(parts, "vertical wall")
    if not (unit_w and unit_h and rows and back and bottom and top and left and right):
        return {}
    W, H = rect(back)["x"], rect(back)["y"]                 # inside width, inside height
    d_out, d_in = rect(left)["x"], rect(inner[0])["x"] if inner else rect(left)["x"]
    y0 = d_out - d_in                                       # where the inset parts start
    e = max(W, H, d_out) * 0.25
    out = {
        back.index: _place("wall", wall_matrix(rect(back), (0, d_out, 0), X, Z, Y), Y * e),
        bottom.index: _place("wall", wall_matrix(rect(bottom), (0, d_out, 0), X, -Y, -Z), -Z * e),
        top.index: _place("wall", wall_matrix(rect(top), (0, d_out, H), X, -Y, Z), Z * e),
        left.index: _place("wall", wall_matrix(rect(left), (0, d_out, 0), -Y, Z, -X), -X * e),
        right.index: _place("wall", wall_matrix(rect(right), (W, d_out, 0), -Y, Z, X), X * e),
    }
    starts = [sum(unit_w[:c]) + c * 2 * t for c in range(len(unit_w))]
    for k, p in enumerate(inner):                           # pairs back to back at each column boundary
        b = starts[k // 2 + 1] - 2 * t + (k % 2) * t
        out[p.index] = _place("wall", wall_matrix(rect(p), (b, d_out, 0), -Y, Z, X), -Y * e * 1.2 + X * (k % 2 - 0.5) * e * 0.4)
    slots = rows - 1
    z_of = lambda r: r * unit_h + (r - 1) * t               # lower face of the slot above row r (1 .. rows-1)
    shelves = _named(parts, "shelf")
    rails = [p for p in parts if not p.labels and rect(p) and rect(p)["edges"] == "feSe"]
    si = ri = 0
    for c, (c0, w) in enumerate(zip(starts, unit_w)):
        n = shelves_n[c] if shelves_n and c < len(shelves_n) else 0
        chosen = {round((k + 1) * (slots + 1) / (n + 1)) for k in range(n)} if n else set()
        for r in range(1, slots + 1):
            z = z_of(r)
            if r in chosen and si < len(shelves):
                p = shelves[si]
                si += 1
                out[p.index] = _place("wall", wall_matrix(rect(p), (c0, y0, z), X, Y, Z), -Y * e * 1.6)
            elif ri + 2 < len(rails) + 0:
                side_a, back_r, side_b = rails[ri:ri + 3]
                ri += 3
                out[side_a.index] = _place("wall", wall_matrix(rect(side_a), (c0, y0, z), Y, X, Z), -Y * e * 1.6)
                out[back_r.index] = _place("wall", wall_matrix(rect(back_r), (c0 + 4 * t, d_out, z), X, -Y, Z), -Y * e * 1.6)
                out[side_b.index] = _place("wall", wall_matrix(rect(side_b), (c0 + w, y0, z), Y, -X, Z), -Y * e * 1.6)
    cover = next(iter(_named(parts, "cover plate")), None)
    if cover:
        out[cover.index] = _place("wall", wall_matrix(rect(cover), (-t, 0, -t), X, Z, -Y), -Y * e * 2.2, "lid",
                                  {"type": "slide", "dir": [0, -0.6, 0.8], "max": round(H * 0.85, 2)})
    floors = [r * (unit_h + t) for r in range(rows)]
    cells = [_cell((c0, 0, z), (c0 + w, 0, z + unit_h), (w, unit_h))          # each slot's opening, at the front
             for c0, w in zip(starts, unit_w) for z in floors]
    return {"parts": out, "size": [W, d_out, H], "inside": _cavity((0, 0, 0), (W, d_out, H), cells=cells)}


def _segments(flags):
    """[(start, end)] runs of True in a list - the wall segments TrayLayout draws along one grid line."""
    out, i, n = [], 0, len(flags)
    while i < n:
        while i < n and not flags[i]:
            i += 1
        if i == n:
            break
        j = i
        while j < n and flags[j]:
            j += 1
        out.append((i, j))
        i = j
    return out


def traylayout(parts, t, attrs):
    """TrayLayout: walls along the grid lines of the layout, in the order boxes.py draws them - all horizontal
    lines from the top line (0) down to the bottom line, segment by segment, then all vertical lines left to
    right - and the base plate underneath, flush with the outer walls (corner joints)."""
    xs, ys = attrs.get("x"), attrs.get("y")
    hwalls, vwalls = attrs.get("hwalls"), attrs.get("vwalls")
    walls = [p for p in parts if rect(p)]
    plate = next((p for p in parts if not rect(p)), None)
    if not (xs and ys and hwalls and vwalls):
        return {}
    lx, ly = len(xs), len(ys)
    X_tot = sum(xs) + (lx - 1) * t
    Y_tot = sum(ys) + (ly - 1) * t
    col0 = lambda c: sum(xs[:c]) + c * t                       # left inner face of column c
    vline = lambda k: col0(k) - t                               # slab start of vertical line k
    row0 = lambda r: sum(ys[r + 1:]) + (ly - 1 - r) * t         # bottom of row r (row 0 is at the top)
    hline = lambda k: row0(k) + ys[k] if k < ly else -t         # slab start of line k: on top of row k
    e = max(X_tot, Y_tot) * 0.3
    out, it = {}, iter(walls)
    for k in range(ly + 1):
        for a, b in _segments(hwalls[k]):
            p = next(it, None)
            if p is None:
                return {}
            y0 = hline(k)
            if k == ly:            # bottom outer wall: inner face at y = 0, material below
                m = wall_matrix(rect(p), (col0(a), 0, 0), X, Z, -Y)
            else:
                m = wall_matrix(rect(p), (col0(a), y0, 0), X, Z, Y)
            out[p.index] = _place("wall", m, (Y if k < ly / 2 else -Y) * e * (1 if k in (0, ly) else 0.5) + Z * e * (0 if k in (0, ly) else 0.8))
    for k in range(lx + 1):
        for a, b in _segments([row[k] for row in vwalls]):
            p = next(it, None)
            if p is None:
                return {}
            top = row0(a) + ys[a]
            if k == 0:             # left outer wall: inner face at x = 0, material to the left
                m = wall_matrix(rect(p), (0, top, 0), -Y, Z, -X)
            else:
                m = wall_matrix(rect(p), (vline(k), top, 0), -Y, Z, X)
            out[p.index] = _place("wall", m, (X if k > lx / 2 else -X) * e * (1 if k in (0, lx) else 0.5) + Z * e * (0 if k in (0, lx) else 1.2))
    if plate is not None and plate.shape is not None:
        sx0, sy0 = plate.shape.bounds[:2]
        m = np.array([[1, 0, 0, -(sx0 + t)], [0, 1, 0, -(sy0 + t)], [0, 0, -1, 0]], float)
        out[plate.index] = _place("wall", m, -Z * e)
    cells = []
    for cs in _regions(hwalls, vwalls, lx, ly):
        rs, cl = [r for r, _ in cs], [c for _, c in cs]
        r0, r1, c0, c1 = min(rs), max(rs), min(cl), max(cl)
        if len(cs) != (r1 - r0 + 1) * (c1 - c0 + 1):
            continue                   # an L-shaped compartment has no single width x depth
        x0, x1 = col0(c0), col0(c1) + xs[c1]
        y0, y1 = row0(r1), row0(r0) + ys[r0]
        cells.append(_cell((x0, y0, 0), (x1, y1, 0), (x1 - x0, y1 - y0)))
    h = attrs.get("h", 0)
    return {"parts": out, "size": [X_tot, Y_tot, max(h, attrs.get("hi", 0))],
            "inside": _cavity((0, 0, 0), (X_tot, Y_tot, h), cells=cells if len(cells) > 1 else [])}


def _square_holes(p, t, tol=0.3):
    """Centres (piece coords) of the t x t holes in a part - where cabinet-hinge eyes go through a wall."""
    out = []
    for poly in (p.shape.geoms if hasattr(p.shape, "geoms") else [p.shape]):
        for r in poly.interiors:
            x0, y0, x1, y1 = r.bounds
            if abs(x1 - x0 - t) < tol and abs(y1 - y0 - t) < tol:
                out.append(((x0 + x1) / 2, (y0 + y1) / 2))
    return out


def _eye_axes(p):
    """A cabinet-hinge eye: (bore centre, tail direction, inside direction) in its piece coordinates. The tail runs
    from the round eye to the tab; the tab is offset from the bore towards the inside of the box."""
    bore = min((r for poly in ([p.shape] if not hasattr(p.shape, "geoms") else p.shape.geoms) for r in poly.interiors),
               key=lambda r: r.length, default=None)
    if bore is None:
        return None
    b = np.array(bore.centroid.coords[0])
    off = np.array(p.shape.centroid.coords[0]) - b
    if abs(off[1]) >= abs(off[0]):
        tail, side = np.array([0.0, np.sign(off[1])]), np.array([np.sign(off[0]) or 1.0, 0.0])
    else:
        tail, side = np.array([np.sign(off[0]), 0.0]), np.array([0.0, np.sign(off[1]) or 1.0])
    return b, tail, side


def _eye_matrix(p, axis_pt, x0, tail_world, inside_world):
    """Piece (px, py, z) -> world for an eye plate whose bore sits on the hinge axis at axis_pt (any x), lying in
    the plane x = x0 .. x0 + t."""
    b, tail, side = _eye_axes(p)
    # world = axis_pt + (q . tail) * tail_world + (q . side) * inside_world + z * X, with q = piece - bore
    A = np.column_stack([tail_world, inside_world]) @ np.array([tail, side])    # 3x2: piece xy -> world
    T = np.array([x0, axis_pt[1], axis_pt[2]], float) - A @ b
    return np.column_stack([A[:, 0], A[:, 1], X, T])


def hingebox(parts, t, attrs):
    """HingeBox: an ABox-like body (front, back, sides with corner joints, bottom), a lid of the same footprint on
    top (lid walls + top plate) and cabinet hinges at the back: eye plates through square holes in the back wall
    (3 per hinge) and the lid's back wall (2 per hinge), their bores on one axis along the outer back edge at the
    top of the body (Y = y + t, Z = h). The lid swings back around that axis."""
    walls = [p for p in parts if rect(p)]
    eyes = [p for p in parts if not rect(p) and p.shape is not None and _eye_axes(p)]
    if len(walls) != 10 or attrs.get("splitlid"):
        return {}
    front, side_a, side_b, back, lback, lside_a, lside_b, lfront, bottom, ltop = walls
    x, h = rect(front)["x"], rect(front)["y"]
    y = rect(side_a)["x"]
    hl = rect(lback)["y"]
    e = max(x, y, h) * 0.35
    hinge = {"type": "hinge", "point": [0, y + t, h], "axis": [1, 0, 0], "max": 105}
    out = {
        front.index: _place("wall", wall_matrix(rect(front), (0, 0, 0), X, Z, -Y), -Y * e),
        back.index: _place("wall", wall_matrix(rect(back), (x, y, 0), -X, Z, Y), Y * e),
        side_a.index: _place("wall", wall_matrix(rect(side_a), (0, y, 0), -Y, Z, -X), -X * e),
        side_b.index: _place("wall", wall_matrix(rect(side_b), (x, 0, 0), Y, Z, X), X * e),
        bottom.index: _place("wall", wall_matrix(rect(bottom), (x, 0, 0), -X, Y, -Z), -Z * e),
    }
    lid_up = Z * e * 1.6
    lid = {
        lfront.index: wall_matrix(rect(lfront), (0, 0, h), X, Z, -Y),
        lback.index: wall_matrix(rect(lback), (x, y, h), -X, Z, Y),
        lside_a.index: wall_matrix(rect(lside_a), (0, y, h), -Y, Z, -X),
        lside_b.index: wall_matrix(rect(lside_b), (x, 0, h), Y, Z, X),
        ltop.index: wall_matrix(rect(ltop), (0, 0, h + hl), X, Y, Z),
    }
    spread = {lfront.index: -Y, lback.index: Y, lside_a.index: -X, lside_b.index: X, ltop.index: Z}
    for i, m in lid.items():
        out[i] = _place("wall", m, lid_up + spread[i] * e * 0.4, "lid", hinge)
    # eyes: world X of every square hole, body first (eyes hang down), then lid (eyes stand up)
    def hole_xs(wall):
        M = np.array(out[wall.index]["m"]).reshape(3, 4)
        return sorted((M @ [cx, cy, 0, 1])[0] for cx, cy in _square_holes(wall, t))
    axis_pt = (0.0, y + t, h)
    slots = [(xx, -Z, "body") for xx in hole_xs(back)] + [(xx, Z, "lid") for xx in hole_xs(lback)]
    for p, (xc, tail, group) in zip(eyes, slots):
        m = _eye_matrix(p, axis_pt, xc - t / 2, tail, -Y)
        if group == "lid":
            out[p.index] = _place("flat", m, lid_up + Y * e * 0.5, "lid", hinge)
        else:
            out[p.index] = _place("flat", m, Y * e * 1.5, "body")
    return {"parts": out, "size": [x, y, h + hl], "inside": _cavity((0, 0, 0), (x, y, h + hl))}


def integratedhingebox(parts, t, attrs):
    """IntegratedHingeBox: a chest hinge cut into the walls. The body sides end 3 t below the body's top with a
    round knuckle; the hole in each knuckle holds a disc (cut from it) that turns with the lid. The lid sides stand
    on the knuckles (their curved notch wraps round them), the lid front and back hang from the lid top, and the
    lid back's pins reach into the discs. Axis: along X at the outer back face, at the height of the front wall
    (Y = y + t, Z = h) - read from where the round holes land."""
    walls = [p for p in parts if rect(p)]
    if len(walls) != 10:
        return {}
    side_a, lside_a, side_b, lside_b, front, back, lfront, lback, bottom, ltop = walls
    x, h = rect(front)["x"], rect(front)["y"]
    y = rect(side_a)["x"]
    hl = rect(lfront)["y"]
    lid_side_z = h + hl - rect(lside_a)["y"]                 # lid sides end at the lid top's inner face
    e = max(x, y, h) * 0.35
    hinge = {"type": "hinge", "point": [0, y + t, h], "axis": [1, 0, 0], "max": 100}
    out = {
        front.index: _place("wall", wall_matrix(rect(front), (0, 0, 0), X, Z, -Y), -Y * e),
        back.index: _place("wall", wall_matrix(rect(back), (x, y, 0), -X, Z, Y), Y * e),
        side_a.index: _place("wall", wall_matrix(rect(side_a), (0, y, 0), -Y, Z, -X), -X * e),
        side_b.index: _place("wall", wall_matrix(rect(side_b), (x, 0, 0), Y, Z, X), X * e),
        bottom.index: _place("wall", wall_matrix(rect(bottom), (0, 0, 0), Y, X, -Z), -Z * e),
    }
    lid_up = Z * e * 1.6
    lid = {
        lside_a.index: (wall_matrix(rect(lside_a), (0, y, lid_side_z), -Y, Z, -X), -X),
        lside_b.index: (wall_matrix(rect(lside_b), (x, 0, lid_side_z), Y, Z, X), X),
        lfront.index: (wall_matrix(rect(lfront), (x, 0, h + hl), -X, -Z, -Y), -Y),
        lback.index: (wall_matrix(rect(lback), (0, y, h + hl), X, -Z, Y), Y),
        ltop.index: (wall_matrix(rect(ltop), (0, 0, h + hl), Y, X, Z), Z),
    }
    for i, (m, d) in lid.items():
        out[i] = _place("wall", m, lid_up + d * e * 0.4, "lid", hinge)
    for side in (side_a, side_b):        # the discs sit in the knuckles and turn with the lid
        out[side.index]["children"] = [dict(_place("wall", out[side.index]["m"], out[side.index]["explode"], "lid", hinge))
                                       for _ in side.children]
    return {"parts": out, "size": [x, y, h + hl], "inside": _cavity((0, 0, 0), (x, y, h + hl))}


def _round_hole_center(p, M):
    """World centre of the biggest round hole in part p (a chest-hinge knuckle), placed by matrix M."""
    best = None
    for poly in (p.shape.geoms if hasattr(p.shape, "geoms") else [p.shape]):
        for r in poly.interiors:
            x0, y0, x1, y1 = r.bounds
            if abs((x1 - x0) - (y1 - y0)) < 0.5 and (best is None or x1 - x0 > best[0]):
                best = (x1 - x0, ((x0 + x1) / 2, (y0 + y1) / 2))
    if best is None:
        return None
    return np.array(M).reshape(3, 4) @ [best[1][0], best[1][1], 0, 1]


def _edge_rec(p, char):
    return next((w for w in p.walls if w["kind"] == "edge" and w.get("char") == char), None)


def piratechest(parts, t, attrs):
    """PirateChest: a box with a chest hinge at the back (as IntegratedHingeBox) and a lid shaped like half a
    regular polygon over the depth y: lid back (vertical, short), n-2 slanted top panels, lid front (vertical,
    long), and two polygon lid sides. The lid sides are drawn by PirateChest itself; their hinge bottom edge (p / P)
    is probed for their frame. Lid profile, in the left lid side's own coordinates (u from the back, v up from
    the hinge level): back (0, 0)-(0, s/2), front (y, -hy2)-(y, s/2), polygon arc between."""
    n = int(attrs.get("n", 5))
    by = {p.name: p for p in parts}
    need = ("Bottom", "front", "back", "left", "right", "lid back", "lid front", "lid left", "lid right")
    if any(k not in by for k in need):
        return {}
    bottom, front, back, left, right = (by[k] for k in need[:5])
    lback, lfront, lleft, lright = (by[k] for k in need[5:])
    tops = [p for p in parts if p.name == "lid top" and rect(p)]
    el, er = _edge_rec(lleft, "p"), _edge_rec(lright, "P")
    if not (el and er and len(tops) == n - 2):
        return {}
    x, h = rect(front)["x"], rect(front)["y"]
    y = rect(left)["x"]
    e = max(x, y, h) * 0.35
    out = {
        bottom.index: _place("wall", wall_matrix(rect(bottom), (0, 0, 0), X, Y, -Z), -Z * e),
        front.index: _place("wall", wall_matrix(rect(front), (0, 0, 0), X, Z, -Y), -Y * e),
        back.index: _place("wall", wall_matrix(rect(back), (x, y, 0), -X, Z, Y), Y * e),
        right.index: _place("wall", wall_matrix(rect(right), (x, 0, 0), Y, Z, X), X * e),
        left.index: _place("wall", wall_matrix(rect(left), (0, y, 0), -Y, Z, -X), -X * e),
    }
    axis = _round_hole_center(left, out[left.index]["m"])
    if axis is None:
        return {}
    ay, az = axis[1], axis[2]
    side = 2 * math.tan(math.radians(180.0 / (2 * (n - 1)))) * (y / 2)
    # hinge level (start of the left lid side's base): t in front of the axis, hy2 above it - as in
    # IntegratedHingeBox, where the same chest hinge puts the lid sides' frame there
    zb = az + _hy2(lleft, el)
    hinge = {"type": "hinge", "point": [0, ay, az], "axis": [1, 0, 0], "max": 100}
    lid_up = Z * e * 1.6
    # lid sides: their probed bottom-edge frames; left: u -> -Y from the back, right: u -> +Y from the front
    out[lleft.index] = _place("wall", _frame_matrix(el, (0, y, zb), -Y, Z, -X), lid_up - X * e * 0.4, "lid", hinge)
    out[lright.index] = _place("wall", _frame_matrix(er, (x, 0, zb - _hy2(lleft, el)), Y, Z, X), lid_up + X * e * 0.4, "lid", hinge)
    # lid profile in world YZ: from the hinge (back, bottom) over the top to the front, bottom
    a = 180.0 / (n - 1)
    pts = [(y, zb), (y, zb + side / 2)]                  # back vertical
    heading = 180.0 - 90.0                               # pointing up, then turning towards the front
    cy, cz = pts[-1]
    for k in range(n - 2):
        heading += a                                     # turn towards -Y
        ang = math.radians(heading)
        cy, cz = cy + side * math.cos(ang), cz + side * math.sin(ang)
        pts.append((cy, cz))
    pts.append((0.0, zb - _hy2(lleft, el)))              # front vertical down to the lid's base
    centre = np.array([0, y / 2, zb])
    segs = list(zip(pts[:-1], pts[1:]))
    panels = [lback] + tops + [lfront]
    for p, ((y0, z0), (y1, z1)) in zip(panels, segs):
        d = np.array([0, y1 - y0, z1 - z0])
        d /= np.linalg.norm(d)
        nrm = np.array([0, d[2], -d[1]])
        if nrm @ (np.array([0, y0, z0]) - centre) < 0:
            nrm = -nrm
        out[p.index] = _place("wall", wall_matrix(rect(p), (0, y0, z0), X, d, nrm), lid_up + nrm * e * 0.4, "lid", hinge)
    for side_part in (left, right):
        out[side_part.index]["children"] = [dict(_place("wall", out[side_part.index]["m"], out[side_part.index]["explode"],
                                                        "lid", hinge)) for _ in side_part.children]
    clear = min(pts[1][1], pts[-2][1])       # tops of the lid's back and front: the dome starts above them
    return {"parts": out, "size": [x, y, h], "inside": _cavity((0, 0, 0), (x, y, clear))}


def _hy2(p, rec):
    """How far a chest-hinge lid side's base dips below the start of its hinge edge (play + pin + strength):
    the distance from the probed edge start down to the lowest point of the part."""
    return rec["frame"][5] - p.shape.bounds[1]


def _frame_matrix(rec, origin, u, v, n):
    return wall_matrix(rec, origin, u, v, n)


def _polygon(borders):
    """Corners of a boxes.py borders list ([length, angle, length, angle, ...]), starting at (0, 0) heading +u."""
    pts, cx, cy, heading = [(0.0, 0.0)], 0.0, 0.0, 0.0
    for i in range(0, len(borders) - 1, 2):
        length, angle = borders[i], borders[i + 1]
        cx += length * math.cos(math.radians(heading))
        cy += length * math.sin(math.radians(heading))
        pts.append((cx, cy))
        heading += angle if isinstance(angle, (int, float)) else angle[0]
    return pts


def _profile_walls(sides, strips, borders, x, to_world, e, t):
    """Side panels drawn with polygonWall(borders) and the strip walls of polygonWalls(borders, x) around them.
    to_world(u, v) -> (Y, Z) maps the side's own coordinates (u along the first border, v inwards) into the box.
    A strip's recorded frame is the start of its bottom edge line, which for its corner-joint ('F') edges is the
    outer face of the side panel: the strips span X = -t .. x + t, the side panels sit in the outer t at each end."""
    out = {}
    pts = _polygon(borders)
    (y0, z0), (y1, z1) = to_world(0, 0), to_world(1, 0)
    (y2, z2) = to_world(0, 1)
    U = np.array([0, y1 - y0, z1 - z0])
    V = np.array([0, y2 - y0, z2 - z0])
    for p, (xx, n) in zip(sides, ((0.0, -X), (x, X))):
        rec = next(w for w in p.walls if w["kind"] == "poly")
        out[p.index] = _place("wall", wall_matrix(rec, (xx, y0, z0), U, V, n), n * e)
    world = [np.array([0.0, *to_world(u, v)]) for u, v in pts]
    centre = sum(world[:-1]) / (len(world) - 1)
    for k, p in enumerate(strips):
        rec = next(w for w in p.walls if w["kind"] == "strip")
        a, b = world[k], world[k + 1]
        d = (b - a) / np.linalg.norm(b - a)
        nrm = np.array([0, d[2], -d[1]])
        if nrm @ (a - centre) < 0:
            nrm = -nrm
        out[p.index] = _place("wall", wall_matrix(rec, a - X * t, d, X, nrm), nrm * e)
    return out, world


def console(parts, t, attrs):
    """Console: two side panels (polygonWall) and the walls around their profile (polygonWalls): bottom, front,
    the slanted panel, top, back. The profile starts at the back bottom corner and runs to the front along the
    bottom: the side's u is -Y from the back (Y = y), v is up."""
    sides = [p for p in parts if any(w["kind"] == "poly" for w in p.walls)]
    strips = sorted((p for p in parts if any(w["kind"] == "strip" for w in p.walls)),
                    key=lambda p: next(w["seq"] for w in p.walls if w["kind"] == "strip"))
    if len(sides) != 2 or not strips:
        return {}
    borders = next(w for w in sides[0].walls if w["kind"] == "poly")["borders"]
    y = borders[0]
    x = next(w for w in strips[0].walls if w["kind"] == "strip")["y"]
    e = max(x, y) * 0.35
    out, world = _profile_walls(sides, strips, borders, x, lambda u, v: (y - u, v), e, t)
    zs = [p[2] for p in world]
    side_h = lambda yy: max(p[2] for p in world if abs(p[1] - yy) < 1e-6)
    return {"parts": out, "size": [x, y, max(zs)],
            "inside": _cavity((0, 0, 0), (x, y, max(zs)), front=side_h(0.0), back=side_h(y))}


def _move_rec(p):
    return next((w for w in p.walls if w["kind"] == "move"), None)


def console2(parts, t, attrs):
    """Console2: Console's profile (back bottom -> front -> slanted panel -> top -> back), drawn by its own side()
    with the stackable bottom edge: the side's base line is the stackable edge's width (wS) below the profile's
    bottom, so world Z = 0 is the profile's bottom and the feet reach down to -wS.
    Shell: floor, front (lying on its side in the drawing, reaching into the feet), glued panel on the sides'
    slanted edges, top, a bottom strip at the back, the removable back wall above it (u from the top), two guides
    standing on the back wall's inner face. Panel frame: two lips along the sides under the panel, two cross beams
    at its ends. The panel springs, back-wall latches and their clamps stay loose."""
    by = {}
    for p in parts:
        by.setdefault(p.name, []).append(p)
    need = ("Left Side", "Right Side", "Floor", "Front", "Panel", "Top")
    if any(k not in by for k in need) or "Back Wall" not in by:
        return {}
    left, right, floor, front, panel, top = (by[k][0] for k in need)
    angle = float(attrs.get("angle", 50))
    y_prof = rect(floor)["x"]
    x = rect(floor)["y"]
    fh = float(attrs.get("front_height", 30))
    # the stackable feet: the front wall's drawing is its own height plus the feet
    wS = _feet_from(front)
    # profile corners in world (Y from the front, Z up from the profile bottom)
    panel_len = rect(panel)["x"]
    p2 = np.array([0.0, 0.0, fh])
    p3 = p2 + panel_len * np.array([0.0, math.cos(math.radians(angle)), math.sin(math.radians(angle))])
    e = max(x, y_prof) * 0.35
    out = {}
    # sides: drawing origin = move frame; the base line starts t in from the back, wS below the profile bottom
    for p, xx, n in ((left, 0.0, -X), (right, x, X)):
        rec = _move_rec(p)
        out[p.index] = _place("wall", wall_matrix(rec, (xx, y_prof + t, -wS), -Y, Z, n), n * e)
    out[floor.index] = _place("wall", wall_matrix(rect(floor), (0, y_prof, 0), -Y, X, -Z), -Z * e)
    out[front.index] = _place("wall", wall_matrix(rect(front), (0, 0, -wS), Z, X, -Y), -Y * e)
    pd = (p3 - p2) / np.linalg.norm(p3 - p2)
    pn = np.array([0.0, -pd[2], pd[1]])                       # outward: up and towards the front
    narrow = rect(panel)["y"] < x - t                         # removable, not glued: x - 2t between the sides
    out[panel.index] = _place("wall", wall_matrix(rect(panel), p2 + X * (t if narrow else 0.0), pd, X, pn),
                              pn * e * 1.4, "lid",
                              {"type": "slide", "dir": [0, float(pn[1]), float(pn[2])], "max": round(3 * t + 25, 1)})
    z_top = float(p3[2])
    out[top.index] = _place("wall", wall_matrix(rect(top), (0, y_prof, z_top), -Y, X, Z), Z * e)
    back = by["Back Wall"][0]
    if "Bottom Back" in by:                                    # removable back wall
        bb = by["Bottom Back"][0]
        out[bb.index] = _place("wall", wall_matrix(rect(bb), (0, y_prof, t), -Z, X, Y), Y * e)
        out[back.index] = _place("wall", wall_matrix(rect(back), (0, y_prof, z_top), -Z, X, Y), Y * e * 1.6, "lid",
                                 {"type": "slide", "dir": [0, 1, 0], "max": round(4 * t + 20, 1)})
        guides = by.get("Guide", [])
        z_b = z_top - rect(back)["x"]
        for g, xx in zip(guides, (0.0, x - t)):
            out[g.index] = _place("wall", wall_matrix(rect(g), (xx, y_prof, z_b), -Y, Z, X), Y * e * 0.8 + Z * e * 0.3)
    else:                                                      # fixed back wall: drawn from the top down
        out[back.index] = _place("wall", wall_matrix(rect(back), (0, y_prof, z_top), -Z, X, Y), Y * e)
    # panel frame: lips along the sides under the panel, cross beams across its two ends
    unlabeled = [p for p in parts if not p.labels and _move_rec(p)]
    lips = [p for p in unlabeled if abs(max(p.w, p.h) - panel_len) < 1.0 and min(p.w, p.h) < 4 * t
            and not narrow]                                    # the non-glued lips are built differently: loose
    beams = [p for p in unlabeled if abs(max(p.w, p.h) - (x + 2 * t - 2.05 * t)) < 1.0]
    inward = -pn
    for p, xx in zip(lips, (0.0, x - t)):
        out[p.index] = _place("flat", wall_matrix(_move_rec(p), p2 + X * xx, pd, inward, X),
                              pn * e * 1.4 + inward * e * 0.3, "lid", out[panel.index]["motion"])
    for p, uu in zip(beams, (0.0, panel_len - t)):
        rec = _move_rec(p)
        out[p.index] = _place("flat", wall_matrix(rec, p2 + pd * (uu + t), X, inward, -pd),
                              pn * e * 1.4 + inward * e * 0.6, "lid", out[panel.index]["motion"])
    return {"parts": out, "size": [x, y_prof, z_top],
            "inside": _cavity((0, 0, 0), (x, y_prof, z_top), front=fh, back=z_top)}


def _feet_from(front):
    """Height of Console2's stackable feet: the front wall is drawn from the feet up (its frame starts there)."""
    r = rect(front)
    # the drawing spans the feet plus the wall's own height; burn sits outside both
    return round(front.shape.bounds[2] - front.shape.bounds[0] - r["x"], 4)


ASSEMBLERS = {"ABox": abox, "TypeTray": typetray, "SlidingDrawer": slidingdrawer, "HobbyCase": hobbycase,
              "TrayLayout": traylayout, "HingeBox": hingebox, "IntegratedHingeBox": integratedhingebox,
              "PirateChest": piratechest, "Console": console, "Console2": console2}


def _sheet_matrix(p, pl, sheet_w):
    """Flat on the floor exactly where the part sits on its sheet; sheets side by side."""
    rot = pl["rot"] % 360
    dx, dy = {0: (0, 0), 90: (p.h, 0), 180: (p.w, p.h), 270: (0, p.w)}[rot]
    return flat_matrix(pl["sheet"] * (sheet_w + 30) + pl["x"] + dx, pl["y"] + dy, rot)


def extent(parts, placed, t):
    """World bounding box {"lo", "hi"} of the placed parts as assembled (lid closed, nothing exploded): the box's
    outside as the calipers will read it (the 3D solids have the burn taken off). None without placed parts."""
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for p in parts:
        if p.index not in placed or p.shape is None or p.shape.is_empty:
            continue
        xy = np.concatenate([np.asarray(g.exterior.coords)[:, :2]
                             for g in (p.shape.geoms if hasattr(p.shape, "geoms") else [p.shape])])
        pts = np.concatenate([np.column_stack([xy, np.full(len(xy), z), np.ones(len(xy))]) for z in (0.0, t)])
        world = pts @ _matrix(placed[p.index]["m"]).T
        lo, hi = np.minimum(lo, world.min(0)), np.maximum(hi, world.max(0))
    if not np.isfinite(lo).all():
        return None
    return {"lo": [round(float(v), 3) for v in lo], "hi": [round(float(v), 3) for v in hi]}


def assemble(name, parts, t, placements=None, sheet_w=297.0, attrs=None):
    """{"kind": "assembled"|"flat", "parts": [placement per part index], "size": [x, y, h] | None,
        "outside": extent() | None, "inside": _cavity() | None}.
    Without an assembler for `name` the parts lie flat as on the sheets; parts an assembler doesn't place
    (lids, for now) lie in a row in front of the box."""
    fn = ASSEMBLERS.get(name)
    known = fn(parts, t, attrs or {}) if fn else {}
    placed = known.get("parts", {}) if known else {}
    size = known.get("size") if known else None
    on_sheet = {pl["part"]: pl for pl in placements or []}
    out = []
    cx = 0.0
    y0 = -(size[1] * 0.6 + 40) if size else 0.0
    for p in parts:
        if p.index in placed:
            out.append(placed[p.index])
        elif not placed and p.index in on_sheet:
            out.append(_place("flat", _sheet_matrix(p, on_sheet[p.index], sheet_w), group="loose"))
        else:
            out.append(_place("flat", flat_matrix(cx, y0 - p.h), group="loose"))
            cx += p.w + 6
    return {"kind": "assembled" if placed else "flat", "parts": out, "size": size,
            "outside": extent(parts, placed, t) if placed else None,
            "inside": known.get("inside") if placed else None}


# ------------------------------------------------------------------ collisions
def _matrix(m):
    return np.asarray(m, float).reshape(3, 4)


def clashes(parts, matrices, t, step=1.0, tol=0.25):
    """Pairs of parts whose material overlaps in the given pose (matrices: 12 floats per part, or None to skip).
    Parts that only touch (finger in its slot) don't count: both solids are shrunk by `tol` first.
    Returns [{"a": i, "b": j, "points": [[x, y, z], ...]}] with up to 40 sample points per pair."""
    solids = []
    for p, m in zip(parts, matrices):
        if m is None or p.shape is None or p.shape.is_empty:
            solids.append(None)
            continue
        core = p.shape.buffer(-tol)
        if core.is_empty:
            solids.append(None)
            continue
        M = _matrix(m)
        x0, y0, x1, y1 = core.bounds
        xs, ys = np.meshgrid(np.arange(x0 + step / 2, x1, step), np.arange(y0 + step / 2, y1, step))
        xs, ys = xs.ravel(), ys.ravel()
        inside = shapely.contains_xy(core, xs, ys)
        xs, ys = xs[inside], ys[inside]
        zs = np.array([tol + 1e-3, t / 2, t - tol - 1e-3])
        pts = np.concatenate([np.column_stack([xs, ys, np.full_like(xs, z), np.ones_like(xs)]) for z in zs])
        world = pts @ M.T
        corners = np.array([[bx, by, bz, 1] for bx in (x0, x1) for by in (y0, y1) for bz in (0, t)]) @ M.T
        solids.append({"M": M, "core": core, "world": world, "lo": corners.min(0), "hi": corners.max(0)})
    found = []
    for i, a in enumerate(solids):
        if a is None:
            continue
        for j in range(i + 1, len(solids)):
            b = solids[j]
            if b is None or np.any(a["hi"] < b["lo"] - tol) or np.any(b["hi"] < a["lo"] - tol):
                continue
            A = b["M"][:, :3]
            local = (a["world"] - b["M"][:, 3]) @ np.linalg.inv(A).T
            zin = (local[:, 2] > tol) & (local[:, 2] < t - tol)
            if not zin.any():
                continue
            cand = np.nonzero(zin)[0]
            hit = cand[shapely.contains_xy(b["core"], local[cand, 0], local[cand, 1])]
            if len(hit):
                sample = a["world"][hit[:: max(1, len(hit) // 40)]][:40]
                found.append({"a": i, "b": j, "count": int(len(hit)),
                              "points": [[round(float(v), 2) for v in q] for q in sample]})
    return found


def loose_parts(parts, matrices, t, gap=0.3, step=2.0):
    """Indices of placed parts that touch no other placed part (closer than `gap`): something floating in the
    assembly, which the overlap check alone can't see."""
    placed = [(i, p, _matrix(m)) for i, (p, m) in enumerate(zip(parts, matrices))
              if m is not None and p.shape is not None and not p.shape.is_empty]
    samples = {}
    for i, p, M in placed:
        pts = []
        for poly in (p.shape.geoms if hasattr(p.shape, "geoms") else [p.shape]):
            for ring in [poly.exterior] + list(poly.interiors):
                n = max(4, int(ring.length / step))
                pts += [ring.interpolate(k / n, normalized=True).coords[0] for k in range(n)]
        pts = np.array(pts)
        world = np.concatenate([np.column_stack([pts, np.full(len(pts), z), np.ones(len(pts))]) @ M.T
                                for z in (0.0, t)])
        samples[i] = world
    lonely = []
    for i, p, M in placed:
        best = np.inf
        for j, q, N in placed:
            if j == i:
                continue
            local = (samples[i] - N[:, 3]) @ np.linalg.inv(N[:, :3]).T
            dz = np.maximum(0, np.maximum(-local[:, 2], local[:, 2] - t))
            dxy = shapely.distance(q.shape, shapely.points(local[:, :2]))
            best = min(best, float(np.min(np.hypot(dxy, dz))))
            if best < gap:
                break
        if best >= gap:
            lonely.append(i)
    return lonely
