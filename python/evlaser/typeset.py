"""Outline text from an installed font: glyphs -> shapely polygons in mm, with class kerning and word wrap.

Lessons: engraving spreads every edge by about the same amount, so small text needs relatively more tracking
(labyrinth: 0.035 em body, 0.06 em at 1.6 mm caps, with a tight display font). Check glyph coverage up front -
Font.text raises on a missing glyph; SUBST maps the usual offenders.
"""
import glob
import os

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

SUBST = {"ß": "ss", "–": "-", "—": "-", "’": "'"}  # fallbacks, used only when the font lacks the glyph


def _find_font(name, extra_dirs=()):
    dirs = list(extra_dirs) + [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")]
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*")):
            if os.path.basename(f).lower().startswith(name.lower()) and f.lower().endswith((".otf", ".ttf")):
                return f
    raise FileNotFoundError("font '%s' not found in %s" % (name, dirs))


class _FlatPen(BasePen):
    """Collects contours as point lists, curves flattened into `n` segments."""

    def __init__(self, glyphset, n=10):
        super().__init__(glyphset)
        self.n, self.contours, self.cur = n, [], []

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self.cur[-1]
        for i in range(1, self.n + 1):
            t = i / self.n
            u = 1 - t
            self.cur.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                             u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))

    def _qCurveToOne(self, p1, p2):
        p0 = self.cur[-1]
        for i in range(1, self.n + 1):
            t = i / self.n
            u = 1 - t
            self.cur.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                             u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))

    def _closePath(self):
        if len(self.cur) > 2:
            self.contours.append(self.cur)
        self.cur = []

    _endPath = _closePath


def _signed_area(pts):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2


class Font:
    def __init__(self, name, extra_dirs=()):
        """name = start of the font file name; searched in extra_dirs (e.g. the project's _generator/fonts),
        then the user and system font folders."""
        self.path = _find_font(name, extra_dirs)
        self.f = TTFont(self.path)
        self.cmap = self.f.getBestCmap()
        self.gs = self.f.getGlyphSet()
        self.hmtx = self.f["hmtx"]
        self.cap = self.f["OS/2"].sCapHeight or self.f["head"].unitsPerEm * 0.7
        self._geo = {}
        self._kern = self._load_kern()

    def _load_kern(self):
        """Pair kerning from GPOS PairPos (format 1 + 2): {(left glyph, right glyph): x advance}."""
        out = {}
        if "GPOS" not in self.f:
            return out
        table = self.f["GPOS"].table
        for lookup in table.LookupList.Lookup:
            subs = lookup.SubTable
            if lookup.LookupType == 9:
                subs = [s.ExtSubTable for s in subs]
            elif lookup.LookupType != 2:
                continue
            for st in subs:
                if getattr(st, "LookupType", 2) != 2:
                    continue
                cov = st.Coverage.glyphs
                if st.Format == 1:
                    for g1, ps in zip(cov, st.PairSet):
                        for rec in ps.PairValueRecord:
                            v = getattr(rec.Value1, "XAdvance", 0) if rec.Value1 else 0
                            if v:
                                out.setdefault((g1, rec.SecondGlyph), v)
                elif st.Format == 2:
                    cd1, cd2 = st.ClassDef1.classDefs, st.ClassDef2.classDefs
                    names = self.f.getGlyphOrder()
                    by_c2 = {}
                    for g in names:
                        by_c2.setdefault(cd2.get(g, 0), []).append(g)
                    for g1 in cov:
                        row = st.Class1Record[cd1.get(g1, 0)].Class2Record
                        for c2, rec in enumerate(row):
                            v = getattr(rec.Value1, "XAdvance", 0) if rec.Value1 else 0
                            if v:
                                for g2 in by_c2.get(c2, []):
                                    out.setdefault((g1, g2), v)
        return out

    def gname(self, ch):
        if ord(ch) not in self.cmap:
            raise KeyError("glyph missing for %r in %s" % (ch, self.path))
        return self.cmap[ord(ch)]

    def glyph(self, g):
        """Glyph outline in font units (non-zero fill: outer contours minus holes)."""
        if g not in self._geo:
            pen = _FlatPen(self.gs)
            self.gs[g].draw(pen)
            cs = [c for c in pen.contours if abs(_signed_area(c)) > 1]
            if not cs:
                self._geo[g] = None
            else:
                outer_sign = 1 if _signed_area(max(cs, key=lambda c: abs(_signed_area(c)))) > 0 else -1
                outers = [Polygon(c).buffer(0) for c in cs if _signed_area(c) * outer_sign > 0]
                holes = [Polygon(c).buffer(0) for c in cs if _signed_area(c) * outer_sign < 0]
                geo = unary_union(outers)
                if holes:
                    geo = geo.difference(unary_union(holes))
                self._geo[g] = geo
        return self._geo[g]

    def clean(self, s):
        """Substitute only the characters this font has no glyph for."""
        return "".join(SUBST.get(ch, ch) if ord(ch) not in self.cmap else ch for ch in s)

    def _run(self, s, tracking):
        """[(glyph name, x offset in font units)], total advance."""
        s = self.clean(s)
        x, out, prev = 0.0, [], None
        upm = self.f["head"].unitsPerEm
        for ch in s:
            g = self.gname(ch)
            if prev is not None:
                x += self._kern.get((prev, g), 0) + tracking * upm
            out.append((g, x))
            x += self.hmtx[g][0]
            prev = g
        return out, x

    def width(self, s, cap, tracking=0.0):
        return self._run(s, tracking)[1] * cap / self.cap

    def text(self, s, x, y, cap, align="left", tracking=0.0, tol=0.008):
        """Outline polygons of one line. (x, y) = baseline anchor, cap = cap height in mm."""
        run, w = self._run(s, tracking)
        k = cap / self.cap
        x0 = {"left": x, "center": x - w * k / 2, "right": x - w * k}[align]
        polys = []
        for g, gx in run:
            geo = self.glyph(g)
            if geo is None:
                continue
            geo = affinity.affine_transform(geo, [k, 0, 0, k, x0 + gx * k, y])
            polys.append(geo.simplify(tol))
        return unary_union(polys) if polys else MultiPolygon()


def wrap(font, words, width, cap, first_indent=0.0, tracking=0.0):
    """Greedy word wrap -> list of (line text, x indent)."""
    lines, cur, indent = [], [], first_indent
    for w in words.split():
        trial = " ".join(cur + [w])
        if cur and font.width(trial, cap, tracking) > width - indent:
            lines.append((" ".join(cur), indent))
            cur, indent = [w], 0.0
        else:
            cur.append(w)
    if cur:
        lines.append((" ".join(cur), indent))
    return lines
