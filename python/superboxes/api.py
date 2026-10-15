"""JSON in, JSON out: the functions the web worker calls (and the tests).

build(req)   -> parts, placements on sheets, warnings - everything the 2D preview needs
export(req)  -> the .lbrn2 / .svg files for the current layout
A request:
    {"generator": "ABox", "params": {...},
     "material": {"key": "poplar3.6", "thickness": 3.7, "burn": 0.1,
                  "burn_x": 0.07, "burn_y": 0.09},   # optional: per-axis burn, see kerf.py
     "sheet": {"name": "A3", "w": 297, "h": 420, "usable": 390},
     "layout": [placement, ...]       # hand-placed parts to keep (build) / the full layout (export)
     "options": {"labels_engrave": false, "mark": {"enabled": true, "text": null, "part": null}},
     "draft": true}                   # build only: a slider is being dragged - the mark keeps its last spot
"""
import json
import traceback

from evlaser import machine as M

from . import assembly, capture, catalog, export as X, kerf, sheets as S

_cache = {}


def _render(req):
    """(parts, info). Per-axis kerf mode: boxes.py draws without burn and every part keeps room for the
    compensation (the bigger of the two burns all round); info["comp"] = (bx, by) is applied at export."""
    mat = req.get("material") or {}
    comp = kerf.per_axis(mat)
    key = json.dumps([req["generator"], req.get("params", {}), mat.get("thickness"), mat.get("burn"), comp],
                     sort_keys=True)
    if key not in _cache:
        if len(_cache) > 8:
            _cache.clear()
        t = float(mat.get("thickness", 3.7))
        if comp:
            parts, info = capture.render(req["generator"], req.get("params", {}), t, 0.0, margin=max(comp))
            info["comp"] = comp
        else:
            parts, info = capture.render(req["generator"], req.get("params", {}), t, float(mat.get("burn", 0.1)))
            info["comp"] = None
        _cache[key] = (parts, info)
    return _cache[key]


def _valid_locked(parts, layout, sheet):
    """Hand-placed parts that are still inside the area and clear of each other (sizes may have changed)."""
    keep = []
    x0, y0, x1, y1 = S.area(sheet)
    for pl in layout or []:
        if pl.get("part", -1) >= len(parts):
            continue
        p = parts[pl["part"]]
        w, h = S.rotated_size(p.w, p.h, pl["rot"])
        if pl["x"] < x0 - 1e-3 or pl["y"] < y0 - 1e-3 or pl["x"] + w > x1 + 1e-3 or pl["y"] + h > y1 + 1e-3:
            continue
        clash = False
        for q in keep:
            qw, qh = S.rotated_size(parts[q["part"]].w, parts[q["part"]].h, q["rot"])
            if q["sheet"] == pl["sheet"] and pl["x"] < q["x"] + qw + M.GAP - 1e-3 and q["x"] < pl["x"] + w + M.GAP - 1e-3 \
                    and pl["y"] < q["y"] + qh + M.GAP - 1e-3 and q["y"] < pl["y"] + h + M.GAP - 1e-3:
                clash = True
                break
        if not clash:
            keep.append({k: pl[k] for k in ("part", "sheet", "x", "y", "rot")})
    return keep


def _title(req):
    p = req.get("params", {})
    vals = []
    for num, sec in (("x", "sx"), ("y", "sy"), ("h", None)):
        if isinstance(p.get(num), (int, float)) and not isinstance(p.get(num), bool):
            vals.append("%g" % p[num])
        elif sec and p.get(sec):
            vals.append(str(p[sec]))
    dims = " x ".join(vals)
    return "%s%s" % (req["generator"], (" " + dims + (" outside" if p.get("outside") else " inside")) if dims else "")


def build(req):
    sheet = req.get("sheet") or S.A3
    parts, info = _render(req)
    locked = _valid_locked(parts, req.get("layout"), sheet)
    warnings = []
    if req.get("layout") and len(locked) < len([p for p in req["layout"] if p.get("part", -1) < len(parts)]):
        warnings.append("Some hand-placed parts no longer fit where they were and were packed again.")
    placements, too_big = S.pack([(p.w, p.h) for p in parts], sheet, locked=locked)
    for i in too_big:
        _sw, _sh, usable = S.sheet_tuple(sheet)
        warnings.append("%s is %.0f x %.0f mm - bigger than the %g x %g cutting area. Make the box smaller."
                        % (parts[i].name, parts[i].w, parts[i].h, sheet["w"] - 2 * M.EDGE,
                           min(usable, sheet["h"] - M.EDGE) - M.EDGE))
    opts = req.get("options") or {}
    deco, w2 = X.decorations(parts, opts, info["thickness"], req["generator"], bool(req.get("draft")))
    warnings += w2
    sizes = [(p.w, p.h) for p in parts]
    n_sheets = max((pl["sheet"] for pl in placements), default=-1) + 1
    out_parts = []
    for p in parts:
        j = p.to_json()
        j["deco"] = [{"layer": layer, "lines": [[[round(x, 3), round(y, 3)] for x, y in ls.coords] for ls in m.geoms]}
                     for layer, m in deco.get(p.index, [])]
        out_parts.append(j)
    asm = assembly.assemble(req["generator"], parts, info["thickness"], placements, float(sheet["w"]),
                            info.get("attrs"))
    return {
        "ok": True, "title": _title(req), "parts": out_parts, "placements": placements, "too_big": too_big,
        "assembly": asm,
        "sheets": [{"index": n, "offcut": round(S.offcut(placements, sizes, sheet, n), 1)} for n in range(n_sheets)],
        "warnings": warnings, "info": info, "boxes_version": catalog.boxes_version(),
        "mark": (opts.get("mark") or {}).get("text") or X.mark_text(),
    }


def export(req):
    """Files for the layout in req["layout"] (the full layout as shown). Refuses a layout that breaks the rules."""
    sheet = req.get("sheet") or S.A3
    parts, info = _render(req)
    layout = req.get("layout")
    if not layout:
        layout, too_big = S.pack([(p.w, p.h) for p in parts], sheet)
        if too_big:
            return {"ok": False, "error": "Some parts are bigger than the cutting area."}
    missing = set(range(len(parts))) - {pl["part"] for pl in layout}
    if missing:
        return {"ok": False, "error": "Parts without a place on a sheet: %s" % ", ".join(parts[i].name for i in sorted(missing))}
    problems = X.check_layout(parts, layout, sheet, info["comp"])
    if problems:
        return {"ok": False, "error": "Layout breaks the sheet rules:\n" + "\n".join(problems)}
    opts = req.get("options") or {}
    deco, _w = X.decorations(parts, opts, info["thickness"], req["generator"])
    mat = req.get("material") or {}
    fit = mat.get("fit_note") or (("burn X %.3f / Y %.3f mm (per axis)" % info["comp"]) if info["comp"]
                                  else "burn %.2f mm" % info["burn"])
    name = req.get("name") or req["generator"]
    mark = opts.get("mark") or {}
    if mark.get("enabled", True):
        mi = mark.get("part")
        mi = mi if mi is not None and mi < len(parts) else X.bottom_part(parts)
        mark_note = "Maker's mark %s on %s (LINE): assemble it with the mark facing out." % (
            mark.get("text") or X.mark_text(), parts[mi].name)
    else:
        mark_note = "No maker's mark."
    files = X.sheet_files(name, _title(req), parts, layout, deco, mat, sheet,
                          notes_extra="Fit: %s. %s" % (fit, mark_note), previous=req.get("previous"),
                          comp=info["comp"])
    out = []
    for fname, lb, svg, minutes, off in files:
        out.append({"name": fname, "kind": "lbrn2", "content": lb, "minutes": minutes, "offcut": off})
        out.append({"name": fname.replace(".lbrn2", ".svg"), "kind": "svg", "content": svg})
    return {"ok": True, "files": out}


def clash(req):
    """Overlapping parts in the pose the 3D view shows: req["matrices"] = 12 floats per part (or null)."""
    parts, info = _render(req)
    found = assembly.clashes(parts, req.get("matrices") or [], info["thickness"])
    return {"ok": True, "clashes": found}


def call(fn, req_json):
    """Entry point for the worker: never raises, errors come back as {"ok": false, "error": ...}."""
    try:
        req = json.loads(req_json) if req_json else {}
        if fn == "catalog":
            res = {"ok": True, "generators": catalog.catalog(), "boxes_version": catalog.boxes_version(),
                   "materials": {k: {"label": v["label"], "thickness": v["thickness"],
                                     "placeholder": sorted(v["placeholder"])} for k, v in M.MATERIALS.items()}}
        elif fn == "schema":
            res = {"ok": True, "groups": catalog.schema(req["generator"])}
        elif fn == "build":
            res = build(req)
        elif fn == "export":
            res = export(req)
        elif fn == "clash":
            res = clash(req)
        elif fn in ("kerf_sheet", "comb_sheet", "calibration_export"):
            from . import calibration
            res = getattr(calibration, fn)(req)
        else:
            res = {"ok": False, "error": "unknown call %s" % fn}
    except Exception as e:  # the generator's own messages ("Lid not high enough to fit hinge") are useful
        res = {"ok": False, "error": str(e) or type(e).__name__, "trace": traceback.format_exc()}
    return json.dumps(res)
