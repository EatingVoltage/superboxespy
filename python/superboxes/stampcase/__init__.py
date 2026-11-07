"""The stamp case: a magnet-closed case for rubber stamps, base + pocket boards + lid. Ported from stampcaser 1.0.0
(2026-11-07, .grill/stamp-case-merge.md); not a boxes.py generator, so it has its own model and layout, and the api
routes the "StampCase" type here.

model (the case, = a .box.json's params) -> layout.Layout (pockets, names, magnets, blocks, problems, the boards'
items) -> build (boards on sheets, the LightBurn project). pack and magnets place things automatically.
"""
GENERATOR = "StampCase"
