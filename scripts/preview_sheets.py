"""Dev check (CPython): build sheets the way the app does and render PNG previews in layer colours.

    .venv/Scripts/python scripts/preview_sheets.py OUT_DIR [ABox '{"x":50,"y":50,"h":50}']

Writes NN_*.lbrn2/.svg/.png for the box plus the 00a/00b calibration sheets. Look at every PNG.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

from evlaser import preview                                  # noqa: E402  (numpy + Pillow: CPython only)
from superboxes import api, calibration, capture, export as X, sheets as S   # noqa: E402

MAT = {"key": "poplar3.6", "thickness": 3.6, "burn": 0.1}


def render(out, name, parts, placements, deco):
    st = S.sheet_tuple(S.A3)
    n = max(pl["sheet"] for pl in placements) + 1
    for k in range(n):
        evs = [X.placed_part(parts[pl["part"]], pl, deco.get(pl["part"], []))
               for pl in placements if pl["sheet"] == k]
        path = os.path.join(out, "%s_%02d.png" % (name, k + 1))
        preview.render_sheet(path, evs, st)
        print("wrote", path)


def main():
    out = sys.argv[1]
    gen = sys.argv[2] if len(sys.argv) > 2 else "ABox"
    params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {"x": 50, "y": 50, "h": 50, "outside": True}
    os.makedirs(out, exist_ok=True)
    req = {"generator": gen, "params": params, "material": MAT, "options": {}}
    b = api.build(req)
    req["layout"] = b["placements"]
    e = api.export(req)
    assert e["ok"], e
    for f in e["files"]:
        with open(os.path.join(out, f["name"]), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f["content"])
    parts, info = capture.render(gen, params, MAT["thickness"], MAT["burn"])
    deco, _ = X.decorations(parts, {}, MAT["thickness"])
    render(out, X.slug(gen), parts, b["placements"], deco)
    kp, kd = calibration.kerf_parts()
    render(out, "00a_kerf", kp, S.pack([(p.w, p.h) for p in kp], S.A3, allow_rotate=False)[0], kd)
    cp, cd = calibration.comb_parts(MAT["thickness"], calibration.comb_spec({"material": MAT}))
    render(out, "00b_comb", cp, calibration.comb_layout(cp, S.A3), cd)
    axis = calibration.comb_spec({"material": MAT, "kerf": {"x": 0.14, "y": 0.18}})
    cp, cd = calibration.comb_parts(MAT["thickness"], axis)
    render(out, "00b_comb_axis", cp, calibration.comb_layout(cp, S.A3), cd)


if __name__ == "__main__":
    main()
