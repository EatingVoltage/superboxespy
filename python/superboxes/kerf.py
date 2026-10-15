"""Per-axis kerf compensation: the Falcon2's spot isn't round, so it cuts wider in one axis than the other.

Measured on the 00a strips: kerf X (width of a cut seen along X) and kerf Y. A part comes out at its nominal size
when every cut edge is moved out by half the kerf *in the direction of that edge's normal* - for a spot shaped like
an ellipse with semi-axes kx/2 and ky/2 that is the Minkowski sum of the part with that ellipse. The fit on top of it
(press / glue) is one offset delta, the same in every direction:  bx = kx/2 + delta,  by = ky/2 + delta.

This has to happen in machine coordinates, after a part is rotated onto the sheet: a wall turned 90 degrees swaps
which of its edges run along X. boxes.py itself only knows one burn value, so in per-axis mode it draws the parts
without burn and the offset is applied here, at export.
"""
from shapely import affinity

QUAD_SEGS = 3   # segments per quarter of the (tiny) corner ellipse: ~0.05 mm chords, plenty for a 0.1 mm radius


def offset_region(region, bx, by, quad_segs=QUAD_SEGS):
    """Minkowski sum of `region` with an axis-aligned ellipse of semi-axes bx (along X) and by (along Y).
    Outlines grow, holes shrink - exactly what a burn correction does."""
    if region is None or region.is_empty:
        return region
    if bx <= 0 or by <= 0:
        raise ValueError("per-axis burn must be positive (got X %.3f, Y %.3f)" % (bx, by))
    if abs(bx - by) < 1e-9:
        return region.buffer(bx, quad_segs=quad_segs)
    unit = affinity.scale(region, 1.0 / bx, 1.0 / by, origin=(0, 0))
    return affinity.scale(unit.buffer(1.0, quad_segs=quad_segs), bx, by, origin=(0, 0))


def per_axis(material):
    """(bx, by) when the request asks for per-axis compensation (burn_x and burn_y given and different),
    else None - then boxes.py applies one burn value itself, with true curves."""
    bx, by = material.get("burn_x"), material.get("burn_y")
    if bx is None or by is None:
        return None
    bx, by = float(bx), float(by)
    if abs(bx - by) < 5e-4:
        return None
    return bx, by
