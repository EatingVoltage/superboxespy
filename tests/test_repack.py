"""Re-pack lays out only the layouts that could still win (pack.repack); it must pick what trying every one would.
Run: .venv/Scripts/python -m unittest tests.test_repack -v"""
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

from superboxes.stampcase import config as C, model, pack  # noqa: E402

MAT = {"key": "poplar3.6", "thickness": 3.7, "kerf_x": 0.33, "kerf_y": 0.26}


def _case(sizes):
    case = model.Case(project="TEST SET")
    for i, (w, h) in enumerate(sizes):
        case.pockets.append(model.Pocket(name="Stamp %d" % (i + 1), w=w, h=h))
    return case


def _every_layout(case):
    """What Re-pack picked before it skipped any: every mode and row length laid out, the best score first."""
    for p in case.pockets:
        if p.w > p.h:
            p.w, p.h = p.h, p.w
    order = sorted(case.pockets, key=lambda p: (-p.h, -p.w))
    best = None
    for mode in pack.MODES:
        for per_row in range(1, len(order) + 1):
            rows = [order[i:i + per_row] for i in range(0, len(order), per_row)]
            pack._stack(rows, [pack._row(r, case.air, mode) for r in rows], case.air)
            snapshot = [(p.id, p.notch_side, p.notch_end, p.label_pos, round(p.x, 3), round(p.y, 3)) for p in order]
            w, h = pack._board_of(case, order)
            area = w * h * (1.0 if mode == "notch" else pack.NOT_NOTCH_PENALTY)
            score = (pack._sheets(case, w, h), round(area), abs(w - h))
            if best is None or score < best[0]:
                best = (score, snapshot)
            least = pack._least_board(order, per_row, mode, case.air)   # (moves the pockets: after the snapshot)
            if least is not None:
                assert least[0] <= w and least[1] <= h, (mode, per_row, least, (w, h))
    return best[1]


class Repack(unittest.TestCase):
    def setUp(self):
        C.use_material(MAT)

    def check(self, sizes):
        case = _case(sizes)
        want = _every_layout(case)
        pack.repack(case)
        got = [(p.id, p.notch_side, p.notch_end, p.label_pos, p.x, p.y)
               for p in sorted(case.pockets, key=lambda p: (-p.h, -p.w))]
        self.assertEqual(got, want)

    def test_skipping_layouts_picks_what_trying_all_picks(self):
        rng = random.Random(3)
        for n in (1, 5, 14, 24):
            with self.subTest(n=n):
                self.check([(round(rng.uniform(12, 70), 1), round(rng.uniform(15, 80), 1)) for _ in range(n)])

    def test_when_nothing_fits_a_sheet_the_smallest_still_wins(self):
        self.check([(200, 300)] * 3)

    def test_tiny_stamps(self):
        self.check([(3, 3), (30, 40), (4, 5)] * 2)


if __name__ == "__main__":
    unittest.main()
