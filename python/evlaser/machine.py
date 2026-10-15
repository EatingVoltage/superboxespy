"""The user's laser setup: machine, sheets, materials and their LightBurn layers.

Source of truth for layer values. SKILL.md mirrors them; if the two disagree, this file wins (then fix SKILL.md).
All coordinates in the toolchain are mm, Y up, origin = lower-left corner of the sheet = LightBurn workspace 0,0.
"""
MACHINE = "Creality Falcon2 40 W diode"
LIGHTBURN = "2.1.04"

# LightBurn palette indices. The colours are the user's fixed rule:
# black = fill engrave, blue = line engrave, red = cut, green = hatch. T1 (30) is a tool layer, never output.
FILL, LINE, CUT, HATCH, REF = 0, 1, 2, 3, 30

# sheet = (width, height, usable height). LightBurn's device profile is a generic "GRBL" one set to 355 x 390
# and the user keeps it, so nothing goes above Y 390 even though an A3 sheet is 420 tall (the rest is offcut).
A3 = (297.0, 420.0, 390.0)
A4 = (210.0, 297.0, 297.0)
EDGE = 3.0               # min distance between a part and the sheet edge
GAP = 1.5                # min gap between two cut parts

# "Cut" = LightBurn Line mode, "Scan" = Fill mode. Speeds in mm/s (that is how LightBurn 2.1 stores them).
_FILL_SUB = ("Scan", [("minPower", 10), ("maxPower", 10), ("maxPower2", 10), ("speed", 100), ("interval", 0.22)])

MATERIALS = {
    "poplar3.6": {   # key kept from the first batch; the sheets now measure 3.7 (user, 2026-10-11)
        "label": "poplar ply 3.7 mm (sold as 4 mm), A3",
        "thickness": 3.7,
        "sheet": A3,
        # the user's own values, entered in LightBurn on 2026-10-11
        "layers": [
            (FILL, "FILL black", {"type": "Cut", "values": [("maxPower", 35), ("maxPower2", 20), ("speed", 133)],
                                  "sub": [_FILL_SUB]}),
            (LINE, "LINE blue", {"type": "Cut", "values": [("maxPower", 42), ("maxPower2", 20), ("speed", 133)]}),
            # confirmed 2026-10-11: one pass cuts through 3.6 poplar, no problems
            (CUT, "CUT red", {"type": "Cut", "values": [("maxPower", 100), ("maxPower2", 20), ("speed", 12.5)]}),
        ],
        "placeholder": set(),
    },
    "card": {
        "label": "card 250-300 g/m2, A4",
        "thickness": 0.4,
        "sheet": A4,
        # PLACEHOLDER: never tested. The ply cut (100 % at 12.5 mm/s) would set card on fire.
        "layers": [
            (LINE, "LINE blue", {"type": "Cut", "values": [("maxPower", 10), ("maxPower2", 10), ("speed", 100)]}),
            (CUT, "CUT red", {"type": "Cut", "values": [("maxPower", 10), ("maxPower2", 10), ("speed", 100)]}),
        ],
        "placeholder": {LINE, CUT},
    },
}

DEFAULT_USE = {FILL: "small fills", LINE: "line engraving", CUT: "through, runs last", HATCH: "hatch"}


def layers(material, use=None):
    """[(index, name, settings)] in run order, ready for lbrn.write. `use` = {index: what is on it}, which goes
    into the layer name so the user can tell layers apart at a glance. Placeholder layers say so in their name."""
    m = MATERIALS[material]
    use = {**DEFAULT_USE, **(use or {})}
    out = []
    for n, (index, short, settings) in enumerate(m["layers"], 1):
        name = "%d %s - %s" % (n, short, use[index])
        if index in m["placeholder"]:
            name += " - PLACEHOLDER, set your own values"
        out.append((index, name, settings))
    return out
