"""JSON in, JSON out: the functions the web worker calls (and the tests).

build(req)   -> parts, placements on sheets, warnings - everything the 2D preview needs
export(req)  -> the .lbrn2 / .svg files for the current layout
A request:
    {"generator": "ABox", "params": {...},
     "material": {"key": "poplar3.6", "thickness": 3.7, "burn": 0.1,
                  "burn_x": 0.07, "burn_y": 0.09},   # optional: per-axis burn, see kerf.py
     "sheet": {"name": "A3", "w": 297, "h": 420, "usable": 390},
     "layout": [placement, ...]       # hand-placed parts to keep (build) / the full layout (export)
     "options": {"labels_engrave": false, "mark": {"enabled": true, "text": null, "part": null},
                 "rest_cuts": true},          # a last layer cuts the rest wood free (sheets.rest_pieces)
     "faces": {"top": [item, ...], ...},      # the face editor's items per face (faces.py)
     "boards": {"front": 6.6, ...},           # per wall: the board's top above the inside floor, mm (faces.py)
     "draft": true}                   # build only: a slider is being dragged - the mark keeps its last spot
"""
import json
import traceback

from evlaser import machine as M

from . import assembly, capture, catalog, export as X, faces as F, kerf, sheets as S

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
    return S.keep_locked([(p.w, p.h) for p in parts], layout, sheet)


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


def _stampcase(req):
    """The stamp case's api when req is for one, else None (it isn't a boxes.py generator)."""
    if req.get("generator") == "StampCase":
        from .stampcase import api as sc
        return sc
    return None


def build(req):
    sc = _stampcase(req)
    if sc:
        return sc.build(req)
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
    sizes = [(p.w, p.h) for p in parts]
    n_sheets = max((pl["sheet"] for pl in placements), default=-1) + 1
    asm = assembly.assemble(req["generator"], parts, info["thickness"], placements, float(sheet["w"]),
                            info.get("attrs"))
    parts, deco, face_info, w2 = _decorations(req, parts, asm, info, bool(req.get("draft")))
    warnings += w2
    out_parts = []
    for p in parts:
        j = p.to_json()
        j["deco"] = [{"layer": layer, "lines": [[[round(x, 3), round(y, 3)] for x, y in ls.coords] for ls in m.geoms]}
                     for layer, m in deco.get(p.index, [])]
        out_parts.append(j)
    return {
        "ok": True, "title": _title(req), "parts": out_parts, "placements": placements, "too_big": too_big,
        "assembly": asm,
        "sheets": [{"index": n, "offcut": round(S.offcut(placements, sizes, sheet, n), 1)} for n in range(n_sheets)],
        "warnings": warnings, "info": info, "boxes_version": catalog.boxes_version(),
        "mark": (opts.get("mark") or {}).get("text") or X.mark_text(), "faces": face_info, "logos": F.logos(),
    }


def _mark_part(face_info):
    """Where the maker's mark goes unless it was put on a part: the closed box's bottom face (eVlaser: on an
    underside), else None (export.bottom_part decides)."""
    return (face_info.get("bottom") or {}).get("part")


def _decorations(req, parts, asm, info, draft=False):
    """(parts, deco, face info, warnings): the parts with the face editor's holes cut (copies), what's engraved on
    each - labels, the maker's mark (clear of the face editor's items and holes on its part) and the face editor's
    items (req["faces"]) - and the faces for the editor, each with the mark's lines if it's there."""
    face_deco, face_info, found, holes = F.decorate(parts, asm, req.get("faces"), info["thickness"], req.get("boards"))
    parts = F.with_holes(parts, holes, bool(info.get("comp")), float(info.get("burn") or 0.0))
    deco, warnings = X.decorations(parts, req.get("options") or {}, info["thickness"], req["generator"], draft,
                                   avoid=F.footprints(face_deco), default_part=_mark_part(face_info))
    F.show_fixed(face_info, found, deco)
    for i, items in face_deco.items():
        deco.setdefault(i, []).extend(items)
    return parts, deco, face_info, warnings


def export(req):
    """Files for the layout in req["layout"] (the full layout as shown). Refuses a layout that breaks the rules."""
    sc = _stampcase(req)
    if sc:
        return sc.export(req)
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
    asm = assembly.assemble(req["generator"], parts, info["thickness"], layout, float(sheet["w"]), info.get("attrs"))
    parts, deco, face_info, _w = _decorations(req, parts, asm, info)
    bad = F.problems(face_info)
    if bad:
        return {"ok": False, "error": "Move these first:\n" + "\n".join(bad)}
    mat = req.get("material") or {}
    fit = mat.get("fit_note") or (("burn X %.3f / Y %.3f mm (per axis)" % info["comp"]) if info["comp"]
                                  else "burn %.2f mm" % info["burn"])
    name = req.get("name") or req["generator"]
    mark = opts.get("mark") or {}
    if mark.get("enabled", True):
        mi = mark.get("part")
        mi = mi if mi is not None and mi < len(parts) else (_mark_part(face_info) if _mark_part(face_info) is not None
                                                            else X.bottom_part(parts))
        mark_note = "Maker's mark %s on %s (LINE): assemble it with the mark facing out." % (
            mark.get("text") or X.mark_text(), parts[mi].name)
    else:
        mark_note = "No maker's mark."
    proj = X.project_files(name, _title(req), parts, layout, deco, mat, sheet,
                           notes_extra="Fit: %s. %s" % (fit, mark_note), previous=req.get("previous"),
                           comp=info["comp"], rest_cuts=opts.get("rest_cuts", True))
    return X.files_result(proj)


def clash(req):
    """Overlapping parts in the pose the 3D view shows: req["matrices"] = 12 floats per part (or null)."""
    sc = _stampcase(req)
    if sc:
        _case, _lay, parts = sc._parts(req)
        return {"ok": True, "clashes": assembly.clashes(parts, req.get("matrices") or [], sc.C.THICKNESS)}
    parts, info = _render(req)
    found = assembly.clashes(parts, req.get("matrices") or [], info["thickness"])
    return {"ok": True, "clashes": found}


def call(fn, req_json):
    """Entry point for the worker: never raises, errors come back as {"ok": false, "error": ...}."""
    try:
        req = json.loads(req_json) if req_json else {}
        if fn == "catalog":
            from .stampcase import api as sc
            res = {"ok": True, "generators": catalog.catalog() + [sc.info()], "boxes_version": catalog.boxes_version(),
                   "materials": {k: {"label": v["label"], "thickness": v["thickness"],
                                     "placeholder": sorted(v["placeholder"])} for k, v in M.MATERIALS.items()}}
        elif fn == "schema":
            # the stamp case has no sliders: its side panel is the stamp list (src/stampcase.ts)
            res = {"ok": True, "groups": [] if _stampcase(req) else catalog.schema(req["generator"])}
        elif fn == "build":
            res = build(req)
        elif fn == "export":
            res = export(req)
        elif fn == "clash":
            res = clash(req)
        elif fn == "stampcase_op":
            from .stampcase import api as sc
            res = sc.op(req)
        elif fn in ("kerf_sheet", "comb_sheet", "calibration_export"):
            from . import calibration
            res = getattr(calibration, fn)(req)
        else:
            res = {"ok": False, "error": "unknown call %s" % fn}
    except Exception as e:  # the generator's own messages ("Lid not high enough to fit hinge") are useful
        res = {"ok": False, "error": str(e) or type(e).__name__, "trace": traceback.format_exc()}
    return json.dumps(res)
