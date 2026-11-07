"""Convert stampcaser's .stampcase files into superboxes box files (.sbox), once (.grill/stamp-case-merge.md).

    .venv/Scripts/python scripts/convert_stampcase.py FILE.stampcase [...] [--force]

Writes <name>.sbox next to each file and leaves the .stampcase alone (stampcaser keeps working until the parity
test passes). An existing .sbox is only replaced with --force. (Run on 2026-11-07, when boxes were still .box.json:
those three files were renamed to .sbox the same day.)
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from superboxes import catalog                       # noqa: E402
from superboxes.stampcase import GENERATOR, config as C, model  # noqa: E402


def box_config(case, name, source, today=None):
    """The box file's dict for a stamp case. params = the case itself (model.Case.to_dict without its version)."""
    params = case.to_dict()
    params.pop("version", None)
    today = today or datetime.date.today()
    return {
        "app": "superboxespy", "version": 1, "name": name, "generator": GENERATOR,
        "boxes_version": catalog.boxes_version(),
        "params": params,
        # a stamp case takes kerf / 2 per axis and no fit (the 1 mm of air is the fit); stampcaser's fixed values
        "material": {"key": C.MATERIAL, "thickness": C.THICKNESS, "fit": "press",
                     "burn": round((C.KERF_X + C.KERF_Y) / 4, 4), "burn_x": C.KERF_X / 2, "burn_y": C.KERF_Y / 2,
                     "kerf_x": C.KERF_X, "kerf_y": C.KERF_Y},
        "sheet": {"name": "A3", "w": 297, "h": 420, "usable": 390},
        "layout": None,
        "options": {"labels_engrave": False, "mark": {"enabled": True, "text": None, "part": None}},
        "notes": "Converted from %s on %s." % (os.path.basename(source), today.isoformat()),
        "saved": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def convert(path, force=False):
    stem = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(os.path.dirname(os.path.abspath(path)), stem + ".sbox")
    if os.path.exists(out) and not force:
        raise FileExistsError("%s exists (use --force to replace it)" % out)
    case = model.Case.load(path)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(box_config(case, stem, path), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for f in a.files:
        print("wrote", convert(f, a.force))


if __name__ == "__main__":
    main()
