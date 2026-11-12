"""The symbol library's test sheet (.grill/symbol-library.md), built with the app's own Python: six symbols at 5, 8,
12 and 20 mm, each as Line and as Solid, one plate per symbol, labelled in eV Sans, the maker's mark on each.

    .venv/Scripts/python scripts/symbol_test_sheet.py OUT_DIR

Writes OUT_DIR/00_symbol-test.lbrn2 (LightBurn-saved layers in an existing one are kept), its SVG and two PNG
previews (layer colours, engraved-wood look). Needs public/symbols.json (npm run symbols). The symbols are drawn by
faces.py exactly as a face item would be, so what the sheet shows is what a box gets.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

from shapely import affinity                                          # noqa: E402
from shapely.geometry import box as rect                              # noqa: E402

from evlaser import machine as M, preview                              # noqa: E402  (numpy + Pillow: CPython only)
from superboxes import calibration as C, export as X, faces as F, sheets as S   # noqa: E402

SYMBOLS = ["lucide:usb", "lucide:midi-port", "lucide:power", "lucide:headphones", "lucide:screw",
           "tabler:circuit-resistor"]
SIZES = [5, 8, 12, 20]
MAT = {"key": "poplar3.6", "thickness": 3.7, "burn": 0.1}

EDGE, LABEL_W, COL_GAP, ROW_GAP = 4.0, 16.0, 5.0, 5.0      # mm on a plate
SMALL, TITLE = 2.5, 3.0                                    # cap heights: size and row labels, the title line
ROW_H = max(SIZES)

NOTES = (
    "00 symbol test - the symbol library's six test symbols, each at 5, 8, 12 and 20 mm (its 24-unit grid).\n"
    "Top row LINE: one pass along each line's centre (LINE layer). Bottom row SOLID: the lines at their drawn width, "
    "filled (FILL layer; 20 mm and less is filled, above that the app hatches).\n"
    "Cut it with your normal layers. Then report back:\n"
    "1. The smallest size that still reads, in LINE and in SOLID (MIDI's five pins, the screw's thread, the resistor's "
    "zigzag).\n"
    "2. Which looks right as the default for panel labels: LINE or SOLID.\n"
    "3. Anything that chars into a blob (SOLID at 5 mm) or comes out too faint (LINE at 5 mm).\n"
    "The app then sets the smallest size it allows and the default style.")


def _text(text, size, x, y, anchor="bl"):
    """eV Sans text as the face editor engraves it (faces._block), its anchor spot at (x, y): outlines on LINE."""
    polys, _lines, _fill = F._block({"kind": "text", "text": text, "size": size, "anchor": anchor})
    bx = F._spot(polys.bounds, anchor)
    return F._outline_lines(affinity.translate(polys, x - bx[0], y - bx[1]))


def _symbol(entry, size, style, cx, cy):
    """The symbol as faces.py places a face item: [(layer, geometry)] centred on (cx, cy)."""
    item = {"kind": "symbol", "symbol": entry["id"], "path": entry["d"], "path_fill": entry.get("f", ""),
            "size": size, "style": style}
    polys, lines, fill = F._block(item)
    move = lambda g: affinity.translate(g, cx, cy)
    out = []
    engraved = [g for g in (F._outline_lines(polys), lines) if not g.is_empty]
    if engraved:
        out.append((M.LINE, move(engraved[0] if len(engraved) == 1 else F.unary_union(engraved))))
    if not fill.is_empty:
        out.append((M.FILL, move(fill)))
    return out


def plate(index, entry, mark):
    """One symbol's plate: its LINE row over its SOLID row, the sizes under them, its name and the mark on top."""
    cols, x = [], EDGE + LABEL_W
    for s in SIZES:
        cols.append(x + s / 2)
        x += s + COL_GAP
    w = x - COL_GAP + EDGE
    y_sizes = EDGE
    y_solid = y_sizes + SMALL + 2.5 + ROW_H / 2
    y_line = y_solid + ROW_H + ROW_GAP
    y_title = y_line + ROW_H / 2 + 4.0
    h = y_title + TITLE + EDGE
    p = C._part(index, "symbol test " + entry["id"], w, h)
    p.subpaths[M.CUT] = [C._rect_sub(0, 0, w, h)]
    p.shape = rect(0, 0, w, h)
    deco = []
    for style, cy in (("line", y_line), ("solid", y_solid)):
        deco.append((M.LINE, _text(style.upper(), SMALL, EDGE, cy, "l")))
        for s, cx in zip(SIZES, cols):
            deco += _symbol(entry, s, style, cx, cy)
    for s, cx in zip(SIZES, cols):
        deco.append((M.LINE, _text(str(s), SMALL, cx, y_sizes, "b")))
    name, kit = entry["id"].split(":")[1], entry["id"].split(":")[0].capitalize()
    deco.append((M.LINE, _text("%s · %s" % (name, kit), TITLE, EDGE, y_title + TITLE, "tl")))   # by its top: p's tail
    deco.append((M.LINE, X.mark_lines(mark, w - EDGE - X.mark_width(mark, X.MARK_H), y_title, X.MARK_H)))
    return p, deco


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(HERE, "..", "public", "symbols.json"), encoding="utf-8") as f:
        index = {s["id"]: s for s in json.load(f)["symbols"]}
    mark = X.mark_text()
    parts, deco = [], {}
    for k, sid in enumerate(SYMBOLS):
        p, d = plate(k, index[sid], mark)
        parts.append(p)
        deco[k] = d
    placements, too_big = S.pack([(p.w, p.h) for p in parts], S.A3, allow_rotate=False)
    assert not too_big, too_big
    lb_path = os.path.join(out, "00_symbol-test.lbrn2")
    previous = open(lb_path, encoding="utf-8").read() if os.path.exists(lb_path) else None
    proj = X.project_files("symbol-test", "00 symbol test", parts, placements, deco, MAT, S.A3, notes_extra=NOTES,
                           previous=previous)
    with open(lb_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(proj["lbrn2"][1])
    for _name, svg in proj["svgs"]:
        with open(os.path.join(out, "00_symbol-test.svg"), "w", encoding="utf-8", newline="\n") as f:
            f.write(svg)
    evs = [X.placed_part(parts[pl["part"]], pl, deco.get(pl["part"], [])) for pl in placements]
    st = S.sheet_tuple(S.A3)
    preview.render_sheet(os.path.join(out, "00_symbol-test.png"), evs, st)
    x1 = max(pl["x"] + parts[pl["part"]].w for pl in placements) + 3
    y1 = max(pl["y"] + parts[pl["part"]].h for pl in placements) + 3
    preview.render_wood(os.path.join(out, "00_symbol-test_wood.png"), evs, x1, y1, bg=preview.WOOD)
    mins = proj["sheets"][0]["minutes"]
    per = ", ".join("%s %.1f" % (k, v) for k, v in mins.items())
    print("wrote", lb_path, "| %d plates, about %.1f min (%s), kept LightBurn layers: %s"
          % (len(parts), sum(mins.values()), per, proj["kept"]))


if __name__ == "__main__":
    main()
