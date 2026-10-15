"""The box types this app offers, and their parameters as UI widgets (sliders, toggles, lists).

Only these generators are loaded; the other ~180 boxes.py generators stay in the vendored package unused.
"""
import argparse
import importlib
import math

import boxes
from boxes import ArgparseEdgeType, BoolArg, argparseInts, argparseSections

# name -> module. Order = menu order. ABox is the first fully supported type (2D, export, 3D).
GENERATORS = {
    "ABox": "boxes.generators.abox",
    "TypeTray": "boxes.generators.typetray",
    "TrayLayout": "boxes.generators.traylayout",
    "HingeBox": "boxes.generators.hingebox",
    "IntegratedHingeBox": "boxes.generators.integratedhingebox",
    "PirateChest": "boxes.generators.piratechest",
    "SlidingDrawer": "boxes.generators.slidingdrawer",
    "Console": "boxes.generators.console",
    "Console2": "boxes.generators.console2",
    "HobbyCase": "boxes.generators.hobbycase",
}

# Set by the app, never shown: thickness and burn come from the material + fit, the rest from the app itself.
APP_OWNED = {"thickness", "burn", "format", "output", "reference", "debug", "qr_code", "spacing", "labels",
             "input", "language"}

# Slider ranges that the generic rule gets wrong (mm unless noted).
RANGES = {
    "x": (10, 390, 0.5), "y": (10, 390, 0.5), "h": (5, 390, 0.5), "hi": (0, 390, 0.5),
    "lidheight": (0, 200, 0.5), "front_height": (0, 200, 0.5), "splitlid": (0, 390, 0.5),
    "angle": (0, 90, 0.5), "n": (3, 12, 1), "play": (0, 0.5, 0.01),
    "unit_d": (20, 390, 0.5), "unit_h": (10, 200, 0.5), "rows": (1, 20, 1),
    "radius": (0, 50, 0.5), "gripheight": (0, 100, 0.5), "gripwidth": (0, 100, 0.5),
    "back_height": (0, 200, 0.5), "tabs": (0, 5, 0.1),
}


def generator_class(name):
    if name not in GENERATORS:
        raise KeyError("unknown box type %r" % name)
    cls = getattr(importlib.import_module(GENERATORS[name]), name)
    cls.UI = "web"   # TrayLayout adds a file --input otherwise
    return cls


def new_box(name):
    return generator_class(name)()


def _nice_ceil(v):
    if v <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if m * p >= v:
            return m * p
    return 10 * p


def _range(dest, kind, default):
    key = dest.split("_", 1)[1] if "_" in dest and dest.split("_", 1)[0][:1].isupper() else dest
    if dest in RANGES:
        return RANGES[dest]
    if key in RANGES and key not in ("x", "y", "h"):
        return RANGES[key]
    d = float(default or 0)
    if kind == "int":
        return (0, max(10, int(_nice_ceil(abs(d) * 4))), 1)
    if "angle" in key:
        return (0, 180 if d > 90 else 90, 0.5)
    if "play" in key or "tolerance" in key:
        return (0, 1, 0.01)
    hi = _nice_ceil(abs(d) * 4) if d else 10.0
    step = 0.01 if hi <= 1 else 0.05 if hi <= 10 else 0.5 if hi <= 200 else 1.0
    return (0, hi, step)


def _kind(action):
    t = action.type
    if isinstance(t, BoolArg):
        return "bool"
    if isinstance(t, ArgparseEdgeType):
        return "edge"
    if t is argparseSections:
        return "sections"
    if t is argparseInts:
        return "ints"
    if action.choices:
        return "choice"
    if t is float:
        return "float"
    if t is int:
        return "int"
    return "text"


def _default(action, kind):
    d = action.default
    if kind == "bool":
        return bool(BoolArg()(d)) if isinstance(d, str) else bool(d)
    if kind in ("sections", "ints") and isinstance(d, list):
        return ":".join("%g" % v for v in d)
    if kind in ("float", "int") and isinstance(d, str):
        try:
            return float(d) if kind == "float" else int(d)
        except ValueError:
            return d
    return d


def _help(action):
    h = (action.help or "").split(" [\U0001F6C8]")[0]
    return h.strip()


def schema(name):
    """Parameter groups for the UI: [{title, advanced, params: [{name, kind, default, help, min, max, step,
    choices}]}]. The generator's own group first, then the general settings, then edge/hinge/lid settings."""
    box = new_box(name)
    groups = []
    for g in box.argparser._action_groups:
        params = []
        for a in g._group_actions:
            if a.dest in APP_OWNED or a.dest == "help" or isinstance(a, argparse._HelpAction):
                continue
            kind = _kind(a)
            p = {"name": a.dest, "kind": kind, "default": _default(a, kind), "help": _help(a)}
            if kind in ("float", "int"):
                lo, hi, step = _range(a.dest, kind, p["default"])
                p.update(min=lo, max=hi, step=step)
            if kind == "choice":
                p["choices"] = [str(c) for c in a.choices]
                p["default"] = str(a.default)
            if kind == "edge":
                p["choices"] = list(a.type.edges)
                p["labels"] = {e: ArgparseEdgeType.names.get(e, "") for e in a.type.edges}
            params.append(p)
        if not params:
            continue
        title = g.title or ""
        own = title.endswith(" Settings") and title.startswith(name)
        groups.append({"title": "Box" if own else title.replace("Settings for ", "").strip(),
                       "advanced": not own and title != "Default Settings", "params": params})
    groups.sort(key=lambda g: (g["advanced"], g["title"] != "Box"))
    return groups


def info(name):
    box = new_box(name)
    return {"name": name, "short": box.metadata["short_description"], "description": box.metadata["description"],
            "group": box.ui_group}


def catalog():
    return [info(n) for n in GENERATORS]


def boxes_version():
    import os
    path = os.path.join(os.path.dirname(boxes.__file__), "UPSTREAM_COMMIT")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().split()[0]
    except OSError:
        return "unknown"
