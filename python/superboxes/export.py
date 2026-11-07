"""Placed parts -> one LightBurn .lbrn2 project (through the evlaser writer, one page per sheet) and one SVG per sheet.

Every sheet follows the eVlaser rules: the user's layers and values, CUT last, holes before outlines, T1 shows the
sheet and the 390 mm reach line, a Notes popup with the instructions, origin = sheet lower-left, Absolute Coords.
"""
import datetime
import re
from xml.sax.saxutils import escape

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import MultiLineString

from evlaser import geom as G, lbrn, machine as M

from . import kerf
from . import sheets as S
from . import strokefont

LABEL_H = 2.5          # cap height of part labels, mm
MARK_H = 3.0           # cap height of the maker's mark, mm


def mark_text(when=None):
    """SG + month + last two digits of the year of the cut, the month without a leading zero (eVlaser): October 2026
    -> SG1026, August 2026 -> SG826. The stamp case uses this one too."""
    when = when or datetime.date.today()
    return "SG%d%02d" % (when.month, when.year % 100)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "box"


# ------------------------------------------------------------------ marks and labels on a part
def label_lines(p):
    out = []
    for text, x, y, fs, align in p.labels:
        for k, line in enumerate(reversed(text.split("\n"))):
            out.append(strokefont.text(line, x, y + k * 1.4 * fs, min(LABEL_H, 0.7 * fs), align))
    return MultiLineString([ls for m in out for ls in m.geoms]) if out else None


def mark_spot(p, text, thickness, height=MARK_H):
    """Lower-left corner for `text` on part p: inside the part, clear of holes, finger zones (thickness + 1.5 mm
    from every edge) and nearest to the middle. None when there's no room even at 2 mm."""
    if p.shape is None or p.shape.is_empty:
        return None
    for h in (height, 2.0):
        w = strokefont.width(text, h)
        inner = p.shape.buffer(-(thickness + 1.5))
        if inner.is_empty:
            continue
        c = inner.centroid
        x0, y0, x1, y1 = inner.bounds
        # candidate centres on a 1 mm grid, nearest to the middle first, tested in vectorised batches: the
        # first batch with a fit holds the nearest one (a big back panel has 200 000 candidates)
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1e-9, 1.0), np.arange(y0, y1 + 1e-9, 1.0))
        xs, ys = xs.ravel(), ys.ravel()
        order = np.argsort(np.hypot(xs - c.x, ys - c.y), kind="stable")
        hw, hh = w / 2 + 0.8, h / 2 + 0.8
        for k in range(0, len(order), 512):
            idx = order[k:k + 512]
            boxes = shapely.box(xs[idx] - hw, ys[idx] - hh, xs[idx] + hw, ys[idx] + hh)
            fits = np.nonzero(shapely.contains(inner, boxes))[0]
            if len(fits):
                i = idx[fits[0]]
                return xs[i] - w / 2, ys[i] - h / 2, h
    return None


def _area(p):
    return p.shape.area if p.shape is not None else 0.0


def bottom_part(parts):
    """Where the maker's mark goes by default: a part named bottom/floor/base (the biggest, so a drawer's outer
    box wins over its inner one), else a plate with fingers on all four sides, else the biggest part. Lid parts
    never: the mark belongs on an underside ("lid bottom" is the lid's inner plate)."""
    body = [p for p in parts if not re.search(r"\blid\b|\bbrim\b", p.name, re.I)] or parts
    named = [p for p in body if re.search(r"\b(bottom|floor|base)\b", p.name, re.I)]
    if named:
        return max(named, key=_area).index
    plates = [p for p in body if any(w["kind"] == "rect" and w["edges"].lower() == "ffff" for w in p.walls)]
    if plates:
        return max(plates, key=_area).index
    return max(body, key=_area).index


_last_spot = {}       # (box type, part index, text) -> where the mark went in the last full build


def decorations(parts, opts, thickness, box=None, draft=False):
    """{part index: [(layer, MultiLineString)]} for part labels and the maker's mark, plus warnings.
    draft (while a slider is being dragged): the mark keeps the spot of the last full build of this box type
    instead of searching a new one (the search is the slowest step on a big part), or is left out if it no longer
    fits."""
    deco, warnings = {}, []
    labels_on = M.LINE if opts.get("labels_engrave") else M.REF
    for p in parts:
        ll = label_lines(p)
        if ll is not None:
            deco.setdefault(p.index, []).append((labels_on, ll))
    mark = opts.get("mark") or {}
    if mark.get("enabled", True) and parts:
        text = mark.get("text") or mark_text()
        idx = mark.get("part")
        if idx is None or idx >= len(parts):
            idx = bottom_part(parts)
        if draft:
            spot = _last_spot.get((box, idx, text))
            if spot and (spot[0] + strokefont.width(text, spot[2]) > parts[idx].w or spot[1] + spot[2] > parts[idx].h):
                spot = None
            if spot:
                deco.setdefault(idx, []).append((M.LINE, strokefont.text(text, *spot)))
            return deco, warnings
        spot = mark_spot(parts[idx], text, thickness)
        _last_spot.clear()
        _last_spot[(box, idx, text)] = spot
        if spot:
            x, y, h = spot
            deco.setdefault(idx, []).append((M.LINE, strokefont.text(text, x, y, h)))
        else:
            warnings.append("No room for the maker's mark %s on %s - pick another part." % (text, parts[idx].name))
    return deco, warnings


# ------------------------------------------------------------------ placing
def ev_part(p, deco, closed_cuts=True):
    """The part as evlaser items, in its own coordinates. closed_cuts=False leaves out the closed cut outlines
    (per-axis mode replaces them by the compensated region after placing)."""
    e = G.Part(p.name)
    cuts = p.subpaths[M.CUT] if closed_cuts else [s for s in p.subpaths[M.CUT] if not s[2]]
    if cuts:
        e.add(M.CUT, "bez", cuts)
    if p.subpaths[M.LINE]:
        e.add(M.LINE, "bez", p.subpaths[M.LINE])
    if p.subpaths[M.REF]:
        e.add(M.REF, "bez", p.subpaths[M.REF])
    for layer, lines in deco:
        e.add(layer, "lines", lines)
    return e


def placed(e, p, pl):
    """Rotate about the part's lower-left corner, then move: 90° CCW maps (x, y) -> (h - y, x)."""
    if pl["rot"] % 360 == 90:
        return e.transformed(90, pl["x"] + p.h, pl["y"])
    if pl["rot"] % 360 == 180:
        return e.transformed(180, pl["x"] + p.w, pl["y"] + p.h)
    if pl["rot"] % 360 == 270:
        return e.transformed(270, pl["x"], pl["y"] + p.w)
    return e.transformed(0, pl["x"], pl["y"])


def _on_sheet(g, p, pl):
    rot = pl["rot"] % 360
    g = affinity.rotate(g, rot, origin=(0, 0)) if rot else g
    dx, dy = {0: (0, 0), 90: (p.h, 0), 180: (p.w, p.h), 270: (0, p.w)}[rot]
    return affinity.translate(g, pl["x"] + dx, pl["y"] + dy)


def comp_of(p, comp):
    """(bx, by) per-axis burn for part p, or None when boxes.py applied one burn value itself."""
    return p.comp or comp


def placed_shape(p, pl, comp=None):
    """The part's cut outline (burn included) where it sits on the sheet."""
    g = _on_sheet(p.outline if p.outline is not None else p.shape, p, pl)
    c = comp_of(p, comp)
    return kerf.offset_region(g, *c) if c else g


def placed_part(p, pl, deco, comp=None):
    """evlaser Part on the sheet. Per-axis mode: the closed cut outlines become the compensated region, grown by
    bx along the machine's X and by along Y after the part is rotated into place. A part that places itself (the
    stamp case's boards: stampcase.parts.BoardPart) does so."""
    if hasattr(p, "placed_ev"):
        return p.placed_ev(pl)
    c = comp_of(p, comp)
    if not c:
        return placed(ev_part(p, deco), p, pl)
    e = placed(ev_part(p, deco, closed_cuts=False), p, pl)
    e.add(M.CUT, "poly", placed_shape(p, pl, c))
    return e


def check_layout(parts, placements, sheet, comp=None):
    """Problems with a layout, as text: parts outside the area, cut outlines closer than the 1.5 mm gap."""
    problems = []
    x0, y0, x1, y1 = S.area(sheet)
    by_sheet = {}
    for pl in placements:
        p = parts[pl["part"]]
        w, h = S.rotated_size(p.w, p.h, pl["rot"])
        if pl["x"] < x0 - 1e-3 or pl["y"] < y0 - 1e-3 or pl["x"] + w > x1 + 1e-3 or pl["y"] + h > y1 + 1e-3:
            problems.append("%s sticks out of the cutting area on sheet %d" % (p.name, pl["sheet"] + 1))
        by_sheet.setdefault(pl["sheet"], []).append((p, placed_shape(p, pl, comp)))
    for n, items in by_sheet.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                d = items[i][1].distance(items[j][1])
                if d < M.GAP - 0.2:
                    problems.append("%s and %s are %.1f mm apart on sheet %d (min %.1f)"
                                    % (items[i][0].name, items[j][0].name, d, n + 1, M.GAP))
    return problems


# ------------------------------------------------------------------ files
def material_layers(material, frame=False):
    """(key, material, layers). frame: add the rest-piece cuts after CUT, on their own layer with CUT's values."""
    key = material.get("key", "poplar3.6")
    if key not in M.MATERIALS:
        key = "poplar3.6"
    use = {M.CUT: "through" if frame else "through, runs last", M.LINE: "labels, mark", M.FILL: "small fills"}
    layers = M.layers(key, use)
    if frame:
        cut = next(st for i, _, st in layers if i == M.CUT)
        layers.append((S.FRAME_LAYER, "%d CUT frame - frees the rest pieces, runs last" % (len(layers) + 1), cut))
    return key, M.MATERIALS[key], layers


def rest_part(parts, on_sheet, sheet, comp=None):
    """(pieces, Part with the cuts that free them, or None) for one sheet. on_sheet: its placements."""
    outlines = [placed_shape(parts[pl["part"]], pl, comp) for pl in on_sheet]
    pieces = S.rest_pieces([o.bounds for o in outlines], sheet, [parts[pl["part"]].name for pl in on_sheet])
    lines = S.frame_lines(pieces, outlines, sheet)
    if lines is None:
        return [], None
    e = G.Part("rest pieces")
    e.add(S.FRAME_LAYER, "lines", lines)
    return pieces, e


def _pieces_txt(pieces):
    return ", ".join("%s %.0f x %.0f mm" % ((p.name,) + p.size) for p in pieces)


def kept_layers(xml):
    """Layer settings from the previous version of a sheet, if LightBurn saved it (the user's machine-side
    changes: values, a switched-off fill sub-layer). {} when it's our own unchanged file or missing."""
    if not xml or not lbrn_saved(xml):
        return {}
    return lbrn.saved_layers_text(xml)


def lbrn_saved(xml):
    return "AskForSendName" in xml[:600]


def _time_txt(minutes):
    return ", ".join("%s %.1f min" % (k.split(" - ")[0], v) for k, v in minutes.items()) or "-"


def project_files(name, title, parts, placements, deco, material, sheet, notes_extra="", previous=None, comp=None,
                  rest_cuts=True):
    """The whole job as ONE LightBurn project, one page per sheet (LightBurn 2.2 pages), plus one SVG per sheet.
    {"lbrn2": (filename, text), "svgs": [(filename, text)], "sheets": [{"parts", "minutes", "offcut", "pieces"}],
    "kept": bool}. previous: text of the project's existing .lbrn2 - if LightBurn saved it, its layers are carried
    over. Layers belong to the project in LightBurn, so the carry-over covers every page. rest_cuts: a last layer
    cuts each sheet's rest wood free as rectangles (sheets.rest_pieces)."""
    st = S.sheet_tuple(sheet)
    n_sheets = max((pl["sheet"] for pl in placements), default=-1) + 1
    sizes = [(p.w, p.h) for p in parts]
    sheets = []
    for n in range(n_sheets):
        on = [pl for pl in placements if pl["sheet"] == n]
        evs = [placed_part(parts[pl["part"]], pl, deco.get(pl["part"], []), comp) for pl in on]
        G.check_sheet(evs, st, name="sheet %d" % (n + 1))     # before the rest-piece cuts: they reach the edges
        pieces, frame = rest_part(parts, on, sheet, comp) if rest_cuts else ([], None)
        sheets.append((evs, frame, pieces))
    key, mat, layers = material_layers(material, frame=any(frame for _, frame, _ in sheets))
    pages, svgs, info = [], [], []
    for n, (evs, frame, pieces) in enumerate(sheets):
        page = evs + ([frame] if frame else [])
        pages.append(("Sheet %d" % (n + 1), page))
        svgs.append(("%02d_%s.svg" % (n + 1, slug(name)), svg(page, st, title)))
        info.append({"parts": len(evs), "minutes": G.job_time(page, layers),
                     "offcut": S.offcut(placements, sizes, sheet, n),
                     "pieces": [{"name": p.name, "w": round(p.size[0], 1), "h": round(p.size[1], 1)} for p in pieces]
                     if frame else [],
                     "rest": _pieces_txt(pieces) if frame else ""})

    def rest(s):
        return ("rest pieces: " + s["rest"]) if s["rest"] else "offcut %g x %.0f mm across the top" % (st[0], s["offcut"])

    extra = (notes_extra + "\n") if notes_extra else ""
    if n_sheets == 1:
        s = info[0]
        notes = ("%s - 1 sheet.\n"
                 "Parts: %d. Estimated time: %s (rough - LightBurn's Preview has the real number).\n"
                 "%s.\n"
                 % (title, s["parts"], _time_txt(s["minutes"]), rest(s)[0].upper() + rest(s)[1:]))
    else:
        notes = ("%s - %d sheets, one page each (LightBurn 2.2 or newer). Each page is one sheet: open it with the "
                 "tabs over the workspace or in the Pages panel, then Start - only the page shown is cut.\n"
                 % (title, n_sheets))
        notes += "".join("Sheet %d: %d part%s, %s, %s.\n"
                         % (n + 1, s["parts"], "" if s["parts"] == 1 else "s", _time_txt(s["minutes"]), rest(s))
                         for n, s in enumerate(info))
        notes += "Times are rough - LightBurn's Preview has the real number.\n"
    if any(s["rest"] for s in info):
        notes += ("The last layer (CUT frame) cuts the rest pieces free once the parts are done. Switch its Output "
                  "off to keep a sheet whole.\n")
    notes += extra + "After regenerating, reopen this file in LightBurn, or you'll cut the old geometry.\n"
    keep = kept_layers(previous)
    if keep:
        notes += "Layer settings carried over from your LightBurn-saved version of this project.\n"
    notes += lbrn.common_notes(mat["label"], st)
    lb = lbrn.render_pages(pages, layers, notes, st, material_height=material.get("thickness", mat["thickness"]),
                           keep=keep)
    return {"lbrn2": ("%s.lbrn2" % slug(name), lb), "svgs": svgs, "sheets": info, "kept": bool(keep)}


def total_minutes(sheets):
    """Minutes per layer summed over all sheets."""
    out = {}
    for s in sheets:
        for k, v in s["minutes"].items():
            out[k] = out.get(k, 0.0) + v
    return out


def files_result(proj):
    """export()/calibration_export() result: the one .lbrn2 project, the SVG sheets and the per-sheet numbers."""
    fname, lb = proj["lbrn2"]
    out = [{"name": fname, "kind": "lbrn2", "content": lb, "minutes": total_minutes(proj["sheets"])}]
    for (sname, svg), s in zip(proj["svgs"], proj["sheets"]):
        out.append({"name": sname, "kind": "svg", "content": svg, "minutes": s["minutes"], "offcut": s["offcut"]})
    return {"ok": True, "files": out, "kept": proj["kept"],
            "sheets": [{"minutes": s["minutes"], "offcut": round(s["offcut"], 1), "pieces": s["pieces"]}
                       for s in proj["sheets"]]}


SVG_COLOURS = {M.CUT: "#ff0000", M.LINE: "#0000ff", M.FILL: "#000000", S.FRAME_LAYER: "#ff00ff"}


def _svg_path(item):
    kind = item[1]
    d = []
    if kind == "bez":
        for start, segs, closed in item[2]:
            d.append("M%.3f %.3f" % start)
            for c1, c2, e in segs:
                if c1 is None:
                    d.append("L%.3f %.3f" % e)
                else:
                    d.append("C%.3f %.3f %.3f %.3f %.3f %.3f" % (c1 + c2 + e))
            if closed:
                d.append("Z")
    elif kind == "lines":
        for ls in lbrn._lines(item[2]):
            cs = list(ls.coords)
            d.append("M%.3f %.3f" % cs[0] + "".join("L%.3f %.3f" % c for c in cs[1:]))
    elif kind == "poly":
        for q in lbrn._polys(item[2]):
            for ring in [q.exterior] + list(q.interiors):
                cs = list(ring.coords)
                d.append("M%.3f %.3f" % cs[0] + "".join("L%.3f %.3f" % c for c in cs[1:]) + "Z")
    elif kind == "circle":
        (cx, cy), r = item[2], item[3]
        d.append("M%.3f %.3fa%.3f %.3f 0 1 0 %.3f 0a%.3f %.3f 0 1 0 %.3f 0" % (cx - r, cy, r, r, 2 * r, r, r, -2 * r))
    return " ".join(d)


def svg(evs, sheet, title):
    """Sheet-sized SVG in mm, Y flipped so it matches LightBurn's view. Red = cut, blue = line engrave, magenta = the
    rest-piece cuts (after the parts). The T1 tool layer is left out: other programs would cut it."""
    sw, sh, _ = sheet
    groups = {M.CUT: [], M.LINE: [], M.FILL: [], S.FRAME_LAYER: []}
    for e in evs:
        for it in e.items:
            if it[0] in groups:
                d = _svg_path(it)
                if d:
                    groups[it[0]].append(d)
    body = []
    # engrave layers first, cut last - same order as the LightBurn file
    for layer, name in ((M.FILL, "FILL"), (M.LINE, "LINE"), (M.CUT, "CUT"), (S.FRAME_LAYER, "FRAME")):
        if groups[layer]:
            body.append('  <g id="%s" fill="none" stroke="%s" stroke-width="0.1">\n%s\n  </g>'
                        % (name, SVG_COLOURS[layer], "\n".join('    <path d="%s"/>' % d for d in groups[layer])))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %g %g">\n'
            '  <title>%s</title>\n'
            ' <g transform="translate(0 %g) scale(1 -1)">\n%s\n </g>\n</svg>\n'
            % (sw, sh, sw, sh, escape(title), sh, "\n".join(body)))
