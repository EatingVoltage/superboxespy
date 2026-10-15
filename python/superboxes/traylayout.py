"""TrayLayout's layout text, kept in step with the column (sx) and row (sy) sizes.

boxes.py's TrayLayout is a two-step generator: a text grid of walls and floors, edited by hand. Here the sizes
always come from sx/sy, and the walls/floors from the text - so dragging a size slider keeps the hand-edited
walls, and changing the number of columns or rows starts a fresh grid.
"""
from boxes import argparseSections
from boxes.generators.traylayout import TrayLayout, TrayLayoutFile


def _walls(text, nx, ny):
    """(hwalls, vwalls, floors) parsed from `text` if it has nx columns and ny rows, else None."""
    if not text or not text.strip():
        return None
    t = TrayLayout.__new__(TrayLayout)   # parse() only sets attributes, no drawing setup needed
    try:
        t.parse(text.split("\n"))
    except (ValueError, IndexError):
        return None
    if len(t.x) != nx or len(t.y) != ny:
        return None
    # parse() pads floors with an extra column and row - drop them again
    return t.hwalls, t.vwalls, [row[:-1] for row in t.floors[:-1]]


def sync(text, sx, sy):
    xs = argparseSections(str(sx))
    ys = argparseSections(str(sy))
    f = TrayLayoutFile()
    f.fillDefault(xs, ys)
    kept = _walls(text, len(xs), len(ys))
    if kept:
        f.hwalls, f.vwalls, f.floors = kept
    return str(f)
