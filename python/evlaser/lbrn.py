"""Writes LightBurn .lbrn2 project files (LightBurn 2.x XML, the way LightBurn 2.1.04 saves its own).

Items come from geom.Part: (layer, 'poly'|'lines'|'circle'|'bez', ...). Lines are cleaned before writing:
LightBurn flags zero-length and duplicate segments ("duplicates" warning), so every polyline is exploded onto a
0.001 mm grid, de-duplicated and merged back into chains.
"""
import glob
import os
import re
from xml.sax.saxutils import quoteattr

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon, box
from shapely.ops import linemerge

GRID = 1000  # snap grid for de-duplication: 0.001 mm


def _f(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


class _Ids:
    n = 0

    @classmethod
    def next(cls):
        cls.n += 1
        return cls.n


def _path_xml(layer, loops, indent):
    """loops: list of (vertices, prims_kind, closed). vertices = [(x, y, c0|None, c1|None)],
    prims_kind[i] = 'L' or 'B' for the segment leaving vertex i."""
    verts, prims = [], []
    base = 0
    for vs, kinds, closed in loops:
        n = len(vs)
        for x, y, c0, c1 in vs:
            v = "V%s %s" % (_f(x), _f(y))
            v += ("c0x%sc0y%s" % (_f(c0[0]), _f(c0[1]))) if c0 else "c0x1"
            v += ("c1x%sc1y%s" % (_f(c1[0]), _f(c1[1]))) if c1 else "c1x1"
            verts.append(v)
        last = n if closed else n - 1
        for i in range(last):
            j = (i + 1) % n
            prims.append("%s%d %d" % (kinds[i], base + i, base + j))
        base += n
    i = _Ids.next()
    return ('%s<Shape Type="Path" CutIndex="%d" VertID="%d" PrimID="%d">\n'
            '%s    <XForm>1 0 0 1 0 0</XForm>\n'
            '%s    <VertList>%s</VertList>\n'
            '%s    <PrimList>%s</PrimList>\n'
            '%s</Shape>\n') % (indent, layer, i, i, indent, indent, "".join(verts), indent, "".join(prims), indent)


def _key(p):
    return (round(p[0] * GRID), round(p[1] * GRID))


SAME = 0.005  # points closer than this are one point (LightBurn flags shorter segments as duplicates)


def _same(a, b):
    return abs(a[0] - b[0]) < SAME and abs(a[1] - b[1]) < SAME


def _near(a, b, tol=0.02):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _ring_loop(coords, closed=True):
    """Polyline loop without zero-length segments (consecutive points equal on the 0.001 mm grid)."""
    pts = []
    for p in coords:
        if not pts or not _same(p, pts[-1]):
            pts.append(p)
    if closed and len(pts) > 1 and _same(pts[0], pts[-1]):
        pts = pts[:-1]
    return ([(x, y, None, None) for x, y in pts], ["L"] * len(pts), closed)


def _clean_lines(g):
    """Open/closed polylines with no zero-length and no duplicate segments. LightBurn flags both as duplicates."""
    # 3 um simplification removes the micro-segments left by intersection points; it can fold a chain
    # back onto itself, so the de-duplication runs again afterwards
    return _dedupe([ls.simplify(0.003) for ls in _dedupe(_lines(g))])


def _dedupe(lines):
    """Explode to segments on the 0.001 mm grid, drop zero-length ones and repeats, merge back into chains."""
    seen, segs = set(), []
    for ls in lines:
        cs = list(ls.coords)
        for a, b in zip(cs, cs[1:]):
            ka, kb = _key(a), _key(b)
            if _same(a, b):
                continue
            k = (ka, kb) if ka < kb else (kb, ka)
            if k in seen:
                continue
            seen.add(k)
            segs.append(((ka[0] / GRID, ka[1] / GRID), (kb[0] / GRID, kb[1] / GRID)))
    if not segs:
        return []
    return _lines(linemerge(MultiLineString(segs)))


def _polys(g):
    if isinstance(g, Polygon):
        return [g] if not g.is_empty else []
    if isinstance(g, (MultiPolygon, GeometryCollection)):
        out = []
        for h in g.geoms:
            out += _polys(h)
        return out
    return []


def _lines(g):
    if isinstance(g, LineString):
        return [g] if not g.is_empty else []
    if isinstance(g, (MultiLineString, GeometryCollection)):
        out = []
        for h in g.geoms:
            out += _lines(h)
        return out
    return []


def _bez_loop(sub):
    start, segs, closed = sub
    # drop zero-length straight segments (LightBurn reports them as duplicates)
    kept, cur = [], start
    for seg in segs:
        if _same(seg[2], cur) and (seg[0] is None or (_near(seg[0], cur) and _near(seg[1], cur))):
            continue  # zero-length line or stub curve
        kept.append(seg)
        cur = seg[2]
    segs = kept
    # vertices: start + segment ends; drop the final end when it closes onto start
    pts = [start] + [s[2] for s in segs]
    closes = closed and _same(pts[-1], pts[0])
    if closes:
        pts = pts[:-1]
    n = len(pts)
    c0 = [None] * n
    c1 = [None] * n
    kinds = []
    for i, (a, b, _end) in enumerate(segs):
        if i >= n and not closes:
            break
        j = (i + 1) % n
        if a is None:
            kinds.append("L")
        else:
            kinds.append("B")
            c0[i] = a
            c1[j] = b
    if closed and not closes:
        kinds.append("L")
    verts = [(p[0], p[1], c0[i], c1[i]) for i, p in enumerate(pts)]
    return (verts, kinds, closed)


def _item_xml(it, indent):
    layer, kind = it[0], it[1]
    out = []
    if kind == "poly":
        for p in _polys(it[2]):
            loops = [_ring_loop(p.exterior.coords)] + [_ring_loop(r.coords) for r in p.interiors]
            out.append(_path_xml(layer, loops, indent))
    elif kind == "lines":
        loops = []
        for ls in _clean_lines(it[2]):
            cs = list(ls.coords)
            ring = len(cs) > 3 and _same(cs[0], cs[-1])
            loops.append(_ring_loop(cs, closed=ring))
        if loops:
            out.append(_path_xml(layer, loops, indent))
    elif kind == "circle":
        (cx, cy), r = it[2], it[3]
        out.append('%s<Shape Type="Ellipse" CutIndex="%d" Rx="%s" Ry="%s">\n%s    <XForm>1 0 0 1 %s %s</XForm>\n%s</Shape>\n'
                   % (indent, layer, _f(r), _f(r), indent, _f(cx), _f(cy), indent))
    elif kind == "bez":
        out.append(_path_xml(layer, [_bez_loop(s) for s in it[2]], indent))
    return "".join(out)


def _cut_setting(index, name, priority, s):
    """s = {"type": LightBurn mode ("Cut" = line, "Scan" = fill), "values": [(tag, value)],
    "sub": [(mode, [(tag, value)])]} - written the way LightBurn 2.1 saves its own layers (speed in mm/s)."""
    lines = ['    <CutSetting type="%s">' % s["type"],
             '        <index Value="%d"/>' % index,
             '        <name Value=%s/>' % quoteattr(name)]
    lines += ['        <%s Value="%s"/>' % (tag, v) for tag, v in s["values"]]
    lines += ['        <priority Value="%d"/>' % priority,
              '        <tabCount Value="1"/>',
              '        <tabCountMax Value="1"/>']
    for k, (mode, vals) in enumerate(s.get("sub", []), 1):
        lines.append('        <SubLayer type="%s" index="%d">' % (mode, k))
        lines += ['            <%s Value="%s"/>' % (tag, v) for tag, v in vals]
        lines.append('        </SubLayer>')
    lines.append('    </CutSetting>')
    return "\n".join(lines) + "\n"


HEADER = '''<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="2.1.04" DeviceName="" FormatVersion="1" MaterialHeight="%s" MirrorX="False" MirrorY="False">
    <VariableText>
        <Start Value="0"/>
        <End Value="999"/>
        <Current Value="0"/>
        <Increment Value="1"/>
        <AutoAdvance Value="0"/>
    </VariableText>
    <UIPrefs>
        <Optimize_ByLayer Value="0"/>
        <Optimize_ByGroup Value="-1"/>
        <Optimize_ByPriority Value="1"/>
        <Optimize_WhichDirection Value="0"/>
        <Optimize_InnerToOuter Value="1"/>
        <Optimize_ByDirection Value="0"/>
        <Optimize_ReduceTravel Value="1"/>
        <Optimize_HideBacklash Value="0"/>
        <Optimize_ReduceDirChanges Value="0"/>
        <Optimize_ChooseCorners Value="0"/>
        <Optimize_AllowReverse Value="1"/>
        <Optimize_RemoveOverlaps Value="0"/>
        <Optimize_OptimalEntryPoint Value="0"/>
        <Optimize_OverlapDist Value="0.025"/>
    </UIPrefs>
'''


def write(path, parts, layers, notes, sheet, material_height=3.6, keep=None, ref_layer=30):
    """Write one sheet to `path`; see render()."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(parts, layers, notes, sheet, material_height, keep, ref_layer))


def render(parts, layers, notes, sheet, material_height=3.6, keep=None, ref_layer=30):
    """One sheet as .lbrn2 text. layers: [(index, name, settings)] in run order (machine.layers()); only layers that carry
    items are written. keep: {index: CutSetting XML} from saved_layers() - those layers are written exactly as the
    user saved them in LightBurn (only the run order is renewed), so a rebuild never wipes their machine-side changes.
    sheet = (w, h, usable h): drawn on the never-output T1 layer, with the reach limit line when usable < h."""
    sw, sh, usable = sheet
    keep = keep or {}
    used = sorted({it[0] for p in parts for it in p.items})
    body = [HEADER % _f(material_height)]
    prio = 0
    for index, name, settings in layers:
        if index in used:
            if index in keep:
                body.append(re.sub(r'(<priority Value=")\d+', r"\g<1>%d" % prio, keep[index], count=1))
            else:
                body.append(_cut_setting(index, name, prio, settings))
            prio += 1
    body.append('    <CutSetting type="Tool">\n        <index Value="%d"/>\n        <name Value="T1"/>\n'
                '        <priority Value="%d"/>\n    </CutSetting>\n' % (ref_layer, prio))
    ref = [(ref_layer, "poly", box(0, 0, sw, sh))]
    if usable < sh:
        ref.append((ref_layer, "lines", LineString([(0, usable), (sw, usable)])))
    body.append('    <Shape Type="Group">\n        <XForm>1 0 0 1 0 0</XForm>\n        <Children>\n')
    for it in ref:
        body.append(_item_xml(it, " " * 12))
    body.append('        </Children>\n    </Shape>\n')
    for p in parts:
        body.append('    <Shape Type="Group">\n        <XForm>1 0 0 1 0 0</XForm>\n        <Children>\n')
        for it in p.items:
            body.append(_item_xml(it, " " * 12))
        body.append('        </Children>\n    </Shape>\n')
    body.append('    <Notes ShowOnLoad="1" Notes=%s/>\n' % quoteattr(notes).replace("\n", "&#10;"))
    body.append('</LightBurnProject>\n')
    return "".join(body)


# ------------------------------------------------------------ files the user saved in LightBurn
def saved_by_lightburn(path):
    """True when LightBurn (not this writer) saved the file last: LightBurn adds AskForSendName to the header."""
    with open(path, encoding="utf-8", errors="replace") as f:
        head = f.read(600)
    return "AskForSendName" in head


def lightburn_saves(folder):
    """All .lbrn2 files in `folder` that LightBurn saved (incl. *_backup.lbrn2), newest first. Run this before
    every rebuild: these carry the user's machine-side changes (values, switched-off sub-layers, ...)."""
    files = [f for f in glob.glob(os.path.join(folder, "*.lbrn2")) if saved_by_lightburn(f)]
    return sorted(files, key=os.path.getmtime, reverse=True)


def saved_version(folder, name):
    """Newest LightBurn-saved file of ONE sheet: <name>.lbrn2 or <name>_backup.lbrn2, else None. Carry layers
    over per sheet - a sub-layer switched off on one sheet (e.g. fill off on a long back job) is that sheet's
    choice, not the material's. A change that shows up on every sheet is a material value: put it in machine.py."""
    cands = [os.path.join(folder, name + s + ".lbrn2") for s in ("", "_backup")]
    cands = [f for f in cands if os.path.exists(f) and saved_by_lightburn(f)]
    return max(cands, key=os.path.getmtime) if cands else None


def saved_layers(path):
    """{layer index: CutSetting XML block} of a LightBurn-saved file (tool layers skipped). Pass to write(keep=)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return saved_layers_text(f.read())


def saved_layers_text(xml):
    """saved_layers() for file contents already in memory (the browser reads them)."""
    out = {}
    for m in re.finditer(r'    <CutSetting type="(\w+)">.*?</CutSetting>\n', xml, re.S):
        if m.group(1) == "Tool":
            continue
        idx = re.search(r'<index Value="(\d+)"', m.group(0))
        if idx:
            out[int(idx.group(1))] = m.group(0).replace("\r\n", "\n")
    return out


def common_notes(material_label, sheet, extra=""):
    """The block every sheet's Notes popup ends with."""
    sw, sh, usable = sheet
    limit = ("T1 (not output) shows the sheet and the %g mm reach limit." % usable) if usable < sh \
        else "T1 (not output) shows the sheet."
    return ("Material: %s.\n"
            "Layers: black = FILL, blue = LINE, red = CUT. Run order is top to bottom; CUT always last.\n"
            "%s Sheet lower-left corner = workspace 0,0. Start From: Absolute Coords.%s"
            % (material_label, limit, ("\n" + extra) if extra else ""))
