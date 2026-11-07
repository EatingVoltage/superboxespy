"""A stamp case as the user edits it, saved as a .stampcase file (JSON).

Design coordinates are mm, Y up, with no fixed origin: the board wraps whatever is placed, and the build moves it
onto the sheet. A pocket's (x, y) is its hole's lower-left corner, notch not included.
"""
import json
import uuid
from dataclasses import asdict, dataclass, field

from . import config as C

SIDES = ("left", "right", "bottom", "top")
OPPOSITE = {"left": "right", "right": "left", "bottom": "top", "top": "bottom"}
CCW = {"right": "top", "top": "left", "left": "bottom", "bottom": "right"}
VERSION = 1


def _id():
    return uuid.uuid4().hex[:8]


@dataclass
class Pocket:
    name: str = ""
    w: float = 40.0              # stamp size along X as placed, air not included
    h: float = 60.0              # along Y
    x: float = 0.0
    y: float = 0.0
    notch_side: str = "right"
    notch_end: str = "low"       # the end of its side the notch sits near: low = smaller coordinate
    label_pos: str = "notch"     # its name (B): "notch" = beside the finger notch, "side" = along the opposite
    #                              side, "end" = on the end away from the notch
    id: str = field(default_factory=_id)
    thickness: float = 0.0       # the stamp's own thickness, optional (0 = not given): the 3D shows it in its pocket
    #                              and a stamp thicker than the pockets are deep is an error (stamp-case-merge)

    def hole_size(self, air):
        return self.w + 2 * air, self.h + 2 * air

    def centre(self, air):
        hw, hh = self.hole_size(air)
        return self.x + hw / 2, self.y + hh / 2

    def set_centre(self, cx, cy, air):
        hw, hh = self.hole_size(air)
        self.x, self.y = cx - hw / 2, cy - hh / 2

    def rotate(self, air):
        """90 degrees counter-clockwise about its centre; the notch turns with it."""
        cx, cy = self.centre(air)
        if self.notch_side in ("left", "right"):
            self.notch_end = "high" if self.notch_end == "low" else "low"
        self.notch_side = CCW[self.notch_side]
        self.w, self.h = self.h, self.w
        self.set_centre(cx, cy, air)

    def flip_notch(self):
        self.notch_side = OPPOSITE[self.notch_side]

    def swap_notch_end(self):
        self.notch_end = "high" if self.notch_end == "low" else "low"

    def cycle_label(self):
        self.label_pos = {"notch": "side", "side": "end"}.get(self.label_pos, "notch")

    def label_side(self):
        """The side of the hole its name (B) prefers."""
        if self.label_pos == "notch":
            return self.notch_side
        if self.label_pos == "side":
            return OPPOSITE[self.notch_side]
        return self.far_end()

    def far_end(self):
        """The end of the pocket away from its notch."""
        if self.notch_side in ("left", "right"):
            return "top" if self.notch_end == "low" else "bottom"
        return "right" if self.notch_end == "low" else "left"


@dataclass
class Block:
    """A draggable group of text and logo. (x, y) = its centre."""
    x: float = 0.0
    y: float = 0.0
    size: float = 8.0            # cap height of its text, or a logo's height
    rot: int = 0                 # 0 or 90 (reads bottom to top)
    placed: bool = False         # False: the layout picks the spot


@dataclass
class Case:
    project: str = ""
    pocket_boards: int = 2
    air: float = C.AIR
    logo: str = "slogo_30mm_lite.svg"
    pockets: list = field(default_factory=list)
    magnets: list = field(default_factory=list)     # [[x, y]] hole centres
    magnets_auto: bool = True                        # False once the user adds, moves or deletes one
    top_block: Block = field(default_factory=lambda: Block(size=C.TOP_CAP, rot=90))   # logo + name + mark
    lid_title: Block = field(default_factory=lambda: Block(size=24.0))
    lid_logo: Block = field(default_factory=lambda: Block(size=24.0))

    def pocket(self, pid):
        return next((p for p in self.pockets if p.id == pid), None)

    @property
    def board_count(self):
        """Base, the pocket boards, lid."""
        return self.pocket_boards + 2

    @property
    def top_key(self):
        """The top pocket board: the names, the logo block and the magnets go on it."""
        return "pocket%d" % self.pocket_boards

    # ------------------------------------------------------------------ files
    def to_dict(self):
        d = asdict(self)
        d["version"] = VERSION
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d.pop("version", None)
        known = cls.__dataclass_fields__
        case = cls(**{k: v for k, v in d.items() if k in known and k not in
                      ("pockets", "top_block", "lid_title", "lid_logo")})
        case.pockets = [Pocket(**{k: v for k, v in p.items() if k in Pocket.__dataclass_fields__})
                        for p in d.get("pockets", [])]
        for k in ("top_block", "lid_title", "lid_logo"):
            if k in d:
                setattr(case, k, Block(**{a: v for a, v in d[k].items() if a in Block.__dataclass_fields__}))
        case.magnets = [list(m) for m in case.magnets]
        return case

    def save(self, path):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.to_dict(), f, indent=1, ensure_ascii=False)
            f.write("\n")

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def copy(self):
        return Case.from_dict(json.loads(json.dumps(self.to_dict())))
