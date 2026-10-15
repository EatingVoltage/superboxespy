"""PNG previews: a sheet in layer colours (what LightBurn will show) and an engraved-wood render (what the piece
will look like). Look at every preview before handing files over - it's the cheapest test there is."""
import numpy as np
from PIL import Image, ImageDraw

from . import machine as M
from . import svgpath
from .lbrn import _lines, _polys

SHEET_COL = {M.HATCH: (120, 190, 120), M.FILL: (0, 0, 0), M.LINE: (30, 80, 230), M.CUT: (230, 30, 30),
             M.REF: (150, 150, 150)}
WOOD = (226, 196, 150)     # raw poplar
BURN = (92, 58, 30)        # engraved


class Canvas:
    def __init__(self, w_mm, h_mm, s, bg):
        self.s, self.h_mm = s, h_mm
        self.img = Image.new("RGB", (int(w_mm * s) + 1, int(h_mm * s) + 1), bg)
        self.draw = ImageDraw.Draw(self.img)

    def P(self, x, y):
        return (x * self.s, (self.h_mm - y) * self.s)

    def mask_for(self, item):
        """Even-odd fill mask of a 'poly' or 'bez' item -> (bool array, x0, y0) in pixel space."""
        rings = []
        if item[1] == "poly":
            for p in _polys(item[2]):
                rings += [list(p.exterior.coords)] + [list(r.coords) for r in p.interiors]
        elif item[1] == "bez":
            rings = [svgpath.flatten(sp, 6) for sp in item[2]]
        rings = [[self.P(x, y) for x, y in r] for r in rings if len(r) > 2]
        if not rings:
            return None
        xs = [x for r in rings for x, _ in r]
        ys = [y for r in rings for _, y in r]
        x0, y0 = max(0, int(min(xs)) - 1), max(0, int(min(ys)) - 1)
        x1, y1 = min(self.img.size[0], int(max(xs)) + 2), min(self.img.size[1], int(max(ys)) + 2)
        if x1 <= x0 or y1 <= y0:
            return None
        m = np.zeros((y1 - y0, x1 - x0), bool)
        for r in rings:
            im = Image.new("1", (x1 - x0, y1 - y0), 0)
            ImageDraw.Draw(im).polygon([(x - x0, y - y0) for x, y in r], fill=1)
            m ^= np.array(im)
        return m, x0, y0

    def fill(self, mres, colour, pattern=None):
        if mres is None:
            return
        m, x0, y0 = mres
        if pattern is not None:
            m = m & pattern[y0:y0 + m.shape[0], x0:x0 + m.shape[1]]
        a = np.array(self.img.crop((x0, y0, x0 + m.shape[1], y0 + m.shape[0])))
        a[m] = colour
        self.img.paste(Image.fromarray(a), (x0, y0))
        self.draw = ImageDraw.Draw(self.img)

    def outline(self, item, colour, width=1):
        kind = item[1]
        if kind == "poly":
            for p in _polys(item[2]):
                for r in [p.exterior] + list(p.interiors):
                    self.draw.line([self.P(x, y) for x, y in r.coords], fill=colour, width=width)
        elif kind == "lines":
            for ls in _lines(item[2]):
                self.draw.line([self.P(x, y) for x, y in ls.coords], fill=colour, width=width)
        elif kind == "circle":
            (cx, cy), r = item[2], item[3]
            x0, y0 = self.P(cx - r, cy + r)
            x1, y1 = self.P(cx + r, cy - r)
            self.draw.ellipse([x0, y0, x1, y1], outline=colour, width=width)
        elif kind == "bez":
            for sp in item[2]:
                self.draw.line([self.P(x, y) for x, y in svgpath.flatten(sp, 6)], fill=colour, width=width)


def render_sheet(path, parts, sheet, s=3.0):
    """Sheet in layer colours; the area above the reach limit is grey."""
    sw, sh, usable = sheet
    c = Canvas(sw, sh, s, (255, 255, 255))
    c.draw.rectangle([c.P(0, sh), c.P(sw, 0)], fill=(245, 235, 215))
    if usable < sh:
        c.draw.rectangle([c.P(0, sh), c.P(sw, usable)], fill=(225, 225, 225))
    for layer in (M.HATCH, M.FILL, M.LINE, M.CUT):
        for p in parts:
            for it in p.items:
                if it[0] != layer:
                    continue
                if layer in (M.HATCH, M.FILL) and it[1] in ("poly", "bez"):
                    c.fill(c.mask_for(it), SHEET_COL[layer])
                else:
                    c.outline(it, SHEET_COL[layer])
    for p in parts:
        for it in p.items:
            if it[0] == M.REF:
                c.outline(it, SHEET_COL[M.REF])
    c.img.save(path)


def hatch_pattern(c, spacing_mm=0.5):
    w, h = c.img.size
    px = max(2, int(round(spacing_mm * c.s * 1.4142)))
    yy, xx = np.mgrid[0:h, 0:w]
    return ((xx + yy) % px == 0) | ((xx - yy) % px == 0)


def wood_part(c, part, hatch_pat=None, line_w=0.15):
    """Engraved-wood look of one (already placed) part. Parts are opaque: later parts cover earlier ones."""
    for it in part.items:
        if it[0] == M.CUT and it[1] == "poly":
            c.fill(c.mask_for(it), WOOD)
    for it in part.items:
        if it[0] == M.HATCH and it[1] == "poly" and hatch_pat is not None:
            c.fill(c.mask_for(it), BURN, hatch_pat)
    for it in part.items:
        if it[0] == M.FILL and it[1] in ("poly", "bez"):
            c.fill(c.mask_for(it), BURN)
    for it in part.items:
        if it[0] == M.LINE:
            c.outline(it, BURN, max(1, int(c.s * line_w)))
    for it in part.items:
        if it[0] == M.CUT:
            c.outline(it, (60, 40, 20), 1)


def render_wood(path, parts, w_mm, h_mm, s=6.0, bg=(70, 70, 70)):
    """Engraved-wood render of placed parts on a w x h canvas (assembled product, close-ups)."""
    c = Canvas(w_mm, h_mm, s, bg)
    pat = hatch_pattern(c)
    for p in parts:
        wood_part(c, p, pat)
    c.img.save(path)
    return c
