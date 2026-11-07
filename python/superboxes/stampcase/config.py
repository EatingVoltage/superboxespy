"""The fixed numbers of a stamp case, all in mm. Values taken from the first case (canvas kits stamps holder.lbrn2,
cut 2026-06) or measured say so; decisions are in C:\\Projects\\stampcaser\\.grill\\stamp-case-designer.md (ported
from stampcaser 1.0.0, 2026-11-07, see .grill/stamp-case-merge.md)."""
import os

from evlaser import machine as M

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
# the house logos are private and never ship with this public app: Samuel's folder natively, /logos inside Pyodide
# (the page fetches them from serve.py and writes them there). Without either, a case simply has no logo.
LOGO_DIRS = (r"C:\Projects\eating voltage Fonts\logos", "/logos")

MATERIAL = "poplar3.6"                   # eVlaser key: poplar sold as 4 mm
THICKNESS = M.MATERIALS[MATERIAL]["thickness"]
SHEET = M.MATERIALS[MATERIAL]["sheet"]
# kerf per axis: the material profile's, set by use_material() for every request. These defaults are the values
# measured 2026-10-11 (superboxespy 00a) that stampcaser had fixed in.
KERF_X, KERF_Y = 0.33, 0.26
BURN_X, BURN_Y = KERF_X / 2, KERF_Y / 2  # each cut path moves this far into the waste. No fit on top: the 1 mm of air
#                                          around a stamp is the fit, and magnet holes are drawn without any offset


def use_material(material):
    """Take thickness and kerf from the request's material ({"key", "thickness", "kerf_x", "kerf_y"}); missing values
    keep the defaults above."""
    global MATERIAL, THICKNESS, SHEET, KERF_X, KERF_Y, BURN_X, BURN_Y
    material = material or {}
    if material.get("key") in M.MATERIALS:
        MATERIAL = material["key"]
        SHEET = M.MATERIALS[MATERIAL]["sheet"]
    THICKNESS = float(material.get("thickness") or M.MATERIALS[MATERIAL]["thickness"])
    kx, ky = material.get("kerf_x"), material.get("kerf_y")
    KERF_X = float(kx if kx is not None else ky if ky is not None else 0.33)
    KERF_Y = float(ky if ky is not None else kx if kx is not None else 0.26)
    BURN_X, BURN_Y = KERF_X / 2, KERF_Y / 2

# pockets
AIR = 1.0                # air around a stamp, per side (user)
POCKET_R = 3.0           # corner radius (first case)
NOTCH_OUT = 12.0         # finger notch: a half-ellipse centred on the wall, 12 out (first case: 12.06) ...
NOTCH_HALF = 9.0         # ... and 18 wide along it (first case: 9.01 a side) ...
NOTCH_FILLET = 3.0       # ... with R3 rounds where it meets the wall (first case)
NOTCH_FROM_END = 24.85   # notch centre from the pocket's end (first case); short sides get it centred
NOTCH_SPAN = NOTCH_HALF + 2.8  # half the notch's length along the wall, rounds included (first case: 11.77)
WEB = 5.0                # least wood between two cuts (user 2026-10-24: 3, the first case's notch tip to the
                         # next pocket, made walls too thin)

# board
RIM = 6.0                # wood around the contents
BOARD_R = 5.0            # corner radius (first case)
CORNER_CUT = 23.6        # the eV cut corner, top right: 45 degrees, this far back along each edge (first case)
# where boards go on a sheet and how big they may be: sheets.py (max_board: 290.7 x 386.7, either way round)

# magnets: 3 x 4 mm, pressed in without glue into the top pocket board and the lid
MAGNET_D = 2.6           # drawn, no kerf offset: holds without glue (measured, eVlaser fits table 2026-10-24)
MAGNET_R = MAGNET_D / 2
MAGNET_WOOD = 1.5        # least wood between a magnet hole and any other cut or text
MAGNET_COVER = 95.0      # auto placement: no spot on the board further than this from a magnet
                         # (gives 12 on a full A3 case; the first case had 11 and held well)

# text, all eV Sans, engraved as outlines on LINE
FONT_REGULAR = "eVSans-Regular"
FONT_BOLD = "eVSans-Bold"
LABEL_CAP = 4.0          # pocket name on the top board (B) and the lid (C)
LABEL_MIN_CAP = 2.5      # smallest before the GUI warns
LABEL_PAD = 1.5          # the lid's names (C): wood above and below them
TEXT_EDGE = 3.0          # least wood between any text and the board's edge
TEXT_CUT = 1.0           # least wood between engraved text and any cut, or another name
LABEL_STRIP = TEXT_CUT + 1.3 * LABEL_CAP + TEXT_CUT   # room a name needs off a side (descenders included)
BASE_CAP = 8.0           # pocket name on the base (A), inside the pocket; shrinks to fit
BASE_PAD = 3.0
TRACKING = 0.035         # em, body text (eVlaser)
TRACKING_SMALL = 0.06    # em, below 3 mm caps
TITLE_HATCH = 0.8        # lid title: outline + crosshatch at +-45 degrees, lines this far apart (user 2026-10-24;
                         # was 1.5)
TITLE_MAX_CAP = 30.0
TITLE_MIN_CAP = 8.0
TOP_CAP = 8.0            # project name on the top board
MARK_CAP = 3.0           # maker's mark (eVlaser)
LOGO_PER_CAP = 1.6       # logo height per cap height of the text next to it
BLOCK_WOOD = 1.0         # least wood between a text block and anything else

# boards share a sheet when they fit (sheets.py, user 2026-10-24), eVlaser's EDGE to the sheet edges and GAP apart.
# The rest wood is cut free with short cuts along the boards' own edges, so it falls apart into rectangles without
# any extra strip (user 2026-10-24); on their own layer, run after the boards
FRAME_LAYER = 7          # the first case's extra-cut layer (C07, cut values, ran after C02)
FRAME_MIN_PIECE = 10.0   # a rest piece narrower than this isn't cut free
SHEET_HINT = 20.0        # the GUI points out a board this much smaller that would save a sheet
FRAME_OVERSHOOT = 2.0    # past the sheet's right edge, so the cut goes through it

SNAP = 0.5               # GUI drag grid
