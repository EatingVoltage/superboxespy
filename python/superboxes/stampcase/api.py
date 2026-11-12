"""JSON in, JSON out for the stamp case; superboxes.api routes generator "StampCase" here.

A request is superboxes' (api.py) with params = the case (model.Case.to_dict) and material carrying the profile's
kerf: {"key", "thickness", "kerf_x", "kerf_y"}. A stamp case takes kerf / 2 per axis and no fit.

build(req)  -> what every type returns (parts = the boards, placements on sheets, assembly for the 3D) plus
               "stampcase": the design-coordinate geometry the board editor draws and hit-tests, and the problems.
export(req) -> the LightBurn project; refuses while the case has errors or the layout breaks the sheet rules.
op(req)     -> {"params": the changed case} for the edits that need Python's placement: add, duplicate, repack,
               add_magnet. Every other edit the page makes to the case JSON itself.
"""
import json
import os

from .. import export as X
from .. import sheets as S
from ..assembly import _cavity, _cell, _place, extent
from ..capture import _poly_json
from ..catalog import boxes_version
from . import GENERATOR
from . import build as B
from . import config as C
from . import layout as L
from . import magnets as MG
from . import model
from . import pack
from . import parts as P
from . import shapes as SHP
from . import sheets as SH

LIFT = 45.0          # mm the lid lifts off at the 3D's Open slider's end


def info():
    return {"name": GENERATOR, "short": "Magnet-closed case for rubber stamps",
            "description": "A pocket per stamp with a finger notch, names engraved three times, magnets in the top "
                           "board and the lid. Ported from stampcaser.", "group": "Stamp"}


def _case(req):
    C.use_material(req.get("material"))
    return model.Case.from_dict(req.get("params") or {})


def _title(case):
    name = case.project.strip() or "stamp case"
    return "Stamp case %s, %d stamp%s" % (name, len(case.pockets), "" if len(case.pockets) == 1 else "s")


# ------------------------------------------------------------------ 3D
def assembly(lay, parts):
    """The boards stacked flat, base at Z 0, the lid on top; explode spreads them upwards, Open lifts the lid. extras:
    the magnets as small cylinders and the stamps that have a thickness as blocks in their pockets (red if too
    thick)."""
    t = C.THICKNESS
    w, h = lay.size
    step = max(12.0, 0.12 * max(w, h))
    placed = {}
    out = []
    for i, p in enumerate(parts):
        m = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, i * t]]
        lid = p.key == "lid"
        pl = _place("flat", m, (0, 0, i * step), "lid" if lid else "body",
                    {"type": "slide", "dir": [0, 0, 1], "max": LIFT} if lid else None)
        placed[p.index] = pl
        out.append(pl)
    ox, oy = parts[0].ox, parts[0].oy
    n = lay.case.pocket_boards
    floor, top = t, (n + 1) * t
    cells = []
    for g in lay.pockets:
        x0, y0, x1, y1 = g.rect.bounds
        cells.append(_cell((x0 - ox, y0 - oy, floor), (x1 - ox, y1 - oy, top), [x1 - x0, y1 - y0]))
    if lay.pockets:
        bx0 = min(c["lo"][0] for c in cells)
        by0 = min(c["lo"][1] for c in cells)
        bx1 = max(c["hi"][0] for c in cells)
        by1 = max(c["hi"][1] for c in cells)
        inside = _cavity((bx0, by0, floor), (bx1, by1, top), cells)
    else:
        inside = None
    extras = []
    top_i = n          # the top pocket board's index: base 0, pocket boards 1..n
    for x, y in lay.magnets:
        for board in (top_i, n + 1):          # one in the top pocket board, its partner in the lid
            extras.append({"kind": "cylinder", "at": [round(x - ox, 3), round(y - oy, 3), board * t + (t - 4.0) / 2],
                           "r": 1.5, "h": 4.0, "part": board, "color": "magnet"})
    depth = n * t
    for g in lay.pockets:
        th = g.pocket.thickness
        if th and th > 0:
            x0, y0, x1, y1 = g.rect.bounds
            a = C.AIR
            extras.append({"kind": "box", "lo": [round(x0 + a - ox, 3), round(y0 + a - oy, 3), floor],
                           "hi": [round(x1 - a - ox, 3), round(y1 - a - oy, 3), floor + th], "part": 0,
                           "color": "stamp", "bad": th > depth + 1e-6, "name": g.pocket.name})
    return {"kind": "assembled", "parts": out, "size": [round(w, 2), round(h, 2), round((n + 2) * t, 2)],
            "outside": extent(parts, placed, t), "inside": inside, "extras": extras}


# ------------------------------------------------------------------ editor
def _block_json(geo, block):
    return {"region": _poly_json(geo.region), "x": geo.x, "y": geo.y, "size": geo.size, "rot": geo.rot,
            "placed": block.placed}


def editor(lay, parts):
    case = lay.case
    w, h = lay.size
    n = len(parts)
    sheets = SH.sheet_count(w, h, n)
    hint = SH.hint(w, h, n)
    return {
        "rect": list(lay.rect), "origin": [parts[0].ox, parts[0].oy],
        "boards": [{"key": p.key, "title": p.name, "part": p.index} for p in parts],
        "top_key": case.top_key,
        "pockets": [{"id": g.pocket.id, "hole": _poly_json(g.hole), "label_box": _poly_json(g.label_box)}
                    for g in lay.pockets],
        "magnets": [[round(x, 3), round(y, 3)] for x, y in lay.magnets],
        "magnet_r": C.MAGNET_R,
        "blocks": {"top_block": _block_json(lay.top, case.top_block), "lid_title": _block_json(lay.title, case.lid_title),
                   "lid_logo": _block_json(lay.logo, case.lid_logo)},
        "problems": [{"level": p.level, "text": p.text, "refs": p.refs} for p in lay.problems],
        "size": [round(w, 2), round(h, 2)], "max_board": [round(v, 1) for v in SH.max_board()],
        "per_sheet": SH.per_sheet(w, h), "sheets": sheets,
        "hint": list(hint) if hint else None,
        "depth": round(case.pocket_boards * C.THICKNESS, 2),
        "logos": SHP.logo_files(),
        "snap": C.SNAP, "web": C.WEB, "magnet_wood": C.MAGNET_WOOD,
    }


# ------------------------------------------------------------------ calls
_cache = {}


def _parts(req):
    """(case, layout, boards) for req, kept for the next call with the same case and material (the 3D's overlap check
    right after a build, an export), as superboxes.api keeps a box's parts. Nothing changes them once made."""
    case = _case(req)                    # sets the material every later step reads (config.use_material)
    logo = SHP.logo_path(case.logo)
    st = os.stat(logo) if logo else None
    key = json.dumps([req.get("params") or {}, req.get("material") or {}, X.mark_text(), logo,
                      [st.st_mtime_ns, st.st_size] if st else None], sort_keys=True)
    if key not in _cache:
        if len(_cache) > 8:
            _cache.clear()
        lay = L.Layout(case)
        _cache[key] = case, lay, P.board_parts(lay)
    return _cache[key]


def build(req):
    sheet = req.get("sheet") or S.A3
    case, lay, parts = _parts(req)
    placements, too_big, warnings, sheets = S.place([(p.w, p.h) for p in parts], req.get("layout"), sheet, "boards")
    for i in too_big:
        warnings.append("%s is %.0f x %.0f mm: bigger than the cutting area." % (parts[i].name, parts[i].w, parts[i].h))
    out_parts = []
    for p in parts:
        j = p.to_json()
        j["deco"] = []
        out_parts.append(j)
    return {
        "ok": True, "title": _title(case), "parts": out_parts, "placements": placements, "too_big": too_big,
        "assembly": assembly(lay, parts), "sheets": sheets, "warnings": warnings,
        "info": {"cli": "", "thickness": C.THICKNESS, "burn": round((C.BURN_X + C.BURN_Y) / 2, 4),
                 "comp": [C.BURN_X, C.BURN_Y]},
        "boxes_version": boxes_version(), "mark": lay.mark, "stampcase": editor(lay, parts),
    }


def export(req):
    sheet = req.get("sheet") or S.A3
    case, lay, parts = _parts(req)
    if lay.errors:
        return {"ok": False, "error": "The case has problems to fix first:\n" + "\n".join(p.text for p in lay.errors)}
    layout, refused = X.export_layout(parts, req.get("layout"), sheet, noun="boards",
                                      too_big="A board is bigger than the cutting area.")
    if refused:
        return {"ok": False, "error": refused}
    name = req.get("name") or (case.project.strip() or "stamp case")
    proj = B.project_files(lay, parts, layout, sheet, name, {"key": C.MATERIAL, "thickness": C.THICKNESS},
                           previous=req.get("previous"),
                           rest_cuts=(req.get("options") or {}).get("rest_cuts", True))
    return X.files_result(proj)


def op(req):
    """{"op": "add", "pocket": {name, w, h, thickness}} | {"op": "duplicate", "ids": [...]} | {"op": "repack"} |
    {"op": "add_magnet", "x", "y"} -> {"ok", "params", "select": [ids]}."""
    case = _case(req)
    what = req.get("op")
    select = []
    if what == "add":
        d = req.get("pocket") or {}
        p = model.Pocket(name=str(d.get("name", "")).strip(), w=float(d.get("w", 40)), h=float(d.get("h", 60)),
                         thickness=float(d.get("thickness") or 0))
        case.pockets.append(p)
        pack.place_new(case, p)
        select = [p.id]
    elif what == "duplicate":
        for pid in req.get("ids") or []:
            s = case.pocket(pid)
            if s is None:
                continue
            p = model.Pocket(name=s.name, w=s.w, h=s.h, notch_side=s.notch_side, notch_end=s.notch_end,
                             label_pos=s.label_pos, thickness=s.thickness)
            case.pockets.append(p)
            pack.place_new(case, p, near=s)
            select.append(p.id)
    elif what == "repack":
        pack.repack(case)
    elif what == "add_magnet":
        lay = L.Layout(case)
        spot = MG.nearest_free(lay, float(req["x"]), float(req["y"]))
        if spot is None:
            return {"ok": False, "error": "No room for a magnet there."}
        if case.magnets_auto:
            case.magnets = [list(m) for m in lay.magnets]
            case.magnets_auto = False
        case.magnets.append([round(spot[0], 3), round(spot[1], 3)])
        select = ["magnet:%d" % (len(case.magnets) - 1)]
    else:
        return {"ok": False, "error": "unknown stamp case op %r" % what}
    params = case.to_dict()
    params.pop("version", None)
    return {"ok": True, "params": params, "select": select}

