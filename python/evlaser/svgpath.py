"""Minimal SVG path parser -> list of subpaths made of cubic Bezier segments.

A subpath is (start_point, [(c1, c2, end), ...], closed). Lines become degenerate cubics
flagged with c1 = c2 = None so they can be written as straight LightBurn primitives.
"""
import math
import re

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _tokens(d):
    for t in _TOKEN.findall(d):
        yield t


def _arc_to_cubics(p0, rx, ry, phi_deg, large, sweep, p1):
    """Endpoint-parameterised SVG arc -> list of (c1, c2, end) cubics."""
    x1, y1 = p0
    x2, y2 = p1
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        return [(None, None, p1)]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cphi, sphi = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cphi * dx + sphi * dy
    y1p = -sphi * dx + cphi * dy
    lam = (x1p ** 2) / rx ** 2 + (y1p ** 2) / ry ** 2
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cphi * cxp - sphi * cyp + (x1 + x2) / 2
    cy = sphi * cxp + cphi * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi
    n = max(1, int(math.ceil(abs(dth) / (math.pi / 2) - 1e-9)))
    step = dth / n
    k = 4 / 3 * math.tan(step / 4)
    out = []

    def pt(t):
        x, y = rx * math.cos(t), ry * math.sin(t)
        return (cphi * x - sphi * y + cx, sphi * x + cphi * y + cy)

    def deriv(t):
        x, y = -rx * math.sin(t), ry * math.cos(t)
        return (cphi * x - sphi * y, sphi * x + cphi * y)

    t = th1
    for i in range(n):
        a, b = t, t + step
        pa, pb = pt(a), pt(b)
        da, db = deriv(a), deriv(b)
        c1 = (pa[0] + k * da[0], pa[1] + k * da[1])
        c2 = (pb[0] - k * db[0], pb[1] - k * db[1])
        end = p1 if i == n - 1 else pb
        out.append((c1, c2, end))
        t = b
    return out


def parse(d):
    toks = list(_tokens(d))
    i = 0
    subpaths = []
    cur = None  # [start, segs, closed]
    pos = (0.0, 0.0)
    start = (0.0, 0.0)
    last_c2 = None  # for S
    last_q = None  # for T
    cmd = None

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    def is_num():
        return i < len(toks) and not toks[i].isalpha()

    def begin(p):
        nonlocal cur
        if cur is not None and cur[1]:
            subpaths.append(tuple(cur))
        cur = [p, [], False]

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
        elif cmd is None:
            raise ValueError("path data must start with a command")
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = pos if rel else (0.0, 0.0)
        if c == "Z":
            if cur is not None:
                if cur[1] and (abs(pos[0] - start[0]) > 1e-9 or abs(pos[1] - start[1]) > 1e-9):
                    cur[1].append((None, None, start))
                cur[2] = True
                subpaths.append(tuple(cur))
                cur = None
            pos = start
            last_c2 = last_q = None
            cmd = None if not is_num() else cmd
            continue
        if c == "M":
            p = (ox + num(), oy + num())
            begin(p)
            pos = start = p
            cmd = "l" if rel else "L"
            last_c2 = last_q = None
            continue
        if cur is None:
            begin(pos)
            start = pos
        if c == "L":
            p = (ox + num(), oy + num())
            cur[1].append((None, None, p))
            pos = p
            last_c2 = last_q = None
        elif c == "H":
            x = num() + (pos[0] if rel else 0.0)
            p = (x, pos[1])
            cur[1].append((None, None, p))
            pos = p
            last_c2 = last_q = None
        elif c == "V":
            y = num() + (pos[1] if rel else 0.0)
            p = (pos[0], y)
            cur[1].append((None, None, p))
            pos = p
            last_c2 = last_q = None
        elif c == "C":
            c1 = (ox + num(), oy + num())
            c2 = (ox + num(), oy + num())
            p = (ox + num(), oy + num())
            cur[1].append((c1, c2, p))
            pos, last_c2, last_q = p, c2, None
        elif c == "S":
            c1 = (2 * pos[0] - last_c2[0], 2 * pos[1] - last_c2[1]) if last_c2 else pos
            c2 = (ox + num(), oy + num())
            p = (ox + num(), oy + num())
            cur[1].append((c1, c2, p))
            pos, last_c2, last_q = p, c2, None
        elif c == "Q":
            q = (ox + num(), oy + num())
            p = (ox + num(), oy + num())
            c1 = (pos[0] + 2 / 3 * (q[0] - pos[0]), pos[1] + 2 / 3 * (q[1] - pos[1]))
            c2 = (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1]))
            cur[1].append((c1, c2, p))
            pos, last_q, last_c2 = p, q, None
        elif c == "T":
            q = (2 * pos[0] - last_q[0], 2 * pos[1] - last_q[1]) if last_q else pos
            p = (ox + num(), oy + num())
            c1 = (pos[0] + 2 / 3 * (q[0] - pos[0]), pos[1] + 2 / 3 * (q[1] - pos[1]))
            c2 = (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1]))
            cur[1].append((c1, c2, p))
            pos, last_q, last_c2 = p, q, None
        elif c == "A":
            rx, ry, rot = num(), num(), num()
            large, sweep = int(num()), int(num())
            p = (ox + num(), oy + num())
            cur[1].extend(_arc_to_cubics(pos, rx, ry, rot, large, sweep, p))
            pos = p
            last_c2 = last_q = None
        else:
            raise ValueError("unsupported command " + cmd)
    if cur is not None and cur[1]:
        subpaths.append(tuple(cur))
    return subpaths


def flatten(subpath, tol_steps=12):
    """Subpath -> list of points (polyline). Cubics are sampled uniformly."""
    p0, segs, _closed = subpath
    pts = [p0]
    cur = p0
    for c1, c2, end in segs:
        if c1 is None:
            pts.append(end)
        else:
            for k in range(1, tol_steps + 1):
                t = k / tol_steps
                mt = 1 - t
                x = mt ** 3 * cur[0] + 3 * mt ** 2 * t * c1[0] + 3 * mt * t ** 2 * c2[0] + t ** 3 * end[0]
                y = mt ** 3 * cur[1] + 3 * mt ** 2 * t * c1[1] + 3 * mt * t ** 2 * c2[1] + t ** 3 * end[1]
                pts.append((x, y))
        cur = end
    return pts


def load_icon(path):
    """game-icons.net SVG -> foreground subpaths in 512x512 units (y down)."""
    with open(path, encoding="utf-8") as f:
        svg = f.read()
    ds = re.findall(r'<path[^>]*\sd="([^"]+)"', svg)
    fg = [d for d in ds if d.strip() not in ("M0 0h512v512H0z",)]
    subs = []
    for d in fg:
        subs.extend(parse(d))
    return subs
