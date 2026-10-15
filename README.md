# superboxes

boxes.py as a local web app for the Falcon2: sliders, live 2D sheets, 3D preview with an overlap check,
A3 packing, saved boxes, and LightBurn files straight in your layers (or SVG).

boxes.py itself runs unchanged inside the browser (Pyodide, Python 3.14), pinned to upstream commit `b82a6c9`
(2026-10-11). Nothing leaves your machine: the app is served from `localhost` and works offline.

> **Very early state of development.** Built around one laser (a Creality Falcon2), and it changes daily.
> Expect bugs, missing pieces and changes that break saved boxes. Check every part before you cut it.

## Start

Double-click **`start.bat`**. It serves the app on `http://localhost:5198` and opens it in its own Chrome window
(Edge if there's no Chrome). The first start builds the app, which needs Node.js and Python.

**Pick folder** (top right) once, e.g. `C:\Projects\Laser lightburn`. From then on every export goes to
`<folder>/<box name>/`: the `.lbrn2` sheets, the `.svg` sheets and the box's `.box.json`. The measured material
values go to `<folder>/materials.json`.
Chrome and Edge can do this out of the box. **Brave can't until you enable `brave://flags/#file-system-access-api`.**
Without a folder, files are downloaded instead (several as a zip).

## Before the first real box: calibrate

The burn (kerf correction) for 3.6 poplar has never been measured. The app says **unconfirmed** in red until it has.

1. **Calibration tab → Get 00a kerf test.** Two strips of ten 10 mm bars, one along X and one along Y. About a
   minute of cutting.
2. Push each strip's 10 bars tightly together, end to end, and measure the total length with calipers. Measure the
   sheet thickness in three spots. Enter all three and press **Save measurements**. kerf = (100 − length) / 10.
3. **Get 00b fit comb.** Six values, one step more on the tight side. Each value has three plates: **A** fingers,
   **B** corner counterpart, **C** finger holes. Try A in B and A in C.
4. Enter the **press fit** winner (holds without glue, nothing cracks) and the **glue fit** winner (slides
   together, a little play), as engraved on the plates. If a winner sits at the end of the comb, cut another comb.

Every box then uses burn = kerf / 2 + the fit chosen in the side panel (Press fit / Glue fit).

**Per-axis kerf.** The Falcon2's spot isn't round, so kerf X and kerf Y differ. When they do, every cut is
compensated per machine axis: burn X = kerf X / 2 + fit, burn Y = kerf Y / 2 + fit. A slanted edge gets a value in
between, because technically each part is offset by an ellipse, not a circle. This happens after the part is placed
on the sheet, so a wall rotated 90° still gets the right value per edge. boxes.py only knows one burn value, so in
this mode it draws the parts without burn and `python/superboxes/kerf.py` applies the offset at export. The side
panel shows **Burn X … · Y …**.
The per-axis 00b comb varies only the fit (−0.04 … +0.06, engraved as `+0.02` etc.). Its last row, **A90 B90 C90**,
is the +0.00 plates turned 90°. With correct compensation they fit exactly like the +0.00 row.

## Making a box

- **Box type** button at the top left opens the **gallery**: one tile per type, rendered in your material. At rest
  each box shows exploded. When you hover a tile (or tab to it), the parts assemble quickly, then the box turns and
  opens its lid, drawer or cover. Leaving the tile explodes it again. Arrow keys move between tiles, Enter picks,
  Esc closes. Tiles show each type with its default sizes and are rebuilt when the material thickness changes.
- **Sliders** come with a number field. Typing a value beyond the slider's range is fine, and the slider stretches.
  Compartment lists (TypeTray `sx`/`sy`, HobbyCase) are edited as chips: `+` adds one, `×` removes one, or type
  `50*3:30`. TrayLayout's wall grid is the text box: delete a `-` or `|` to remove a wall, put an `X` in a cell to
  drop its floor. Changing sizes keeps your wall edits; changing the number of columns or rows starts a new grid.
- **Advanced** holds boxes.py's finger-joint, hinge and lid settings.
- **Sheets & 3D tab:** the sheets on the left, the 3D on the right, both following a slider while you drag it.
  Drag the divider (or focus it and use the arrow keys) to share the space; it's remembered. Double-click empty
  space on the sheets, or the 3D, to let that side fill the view; double-click again to split.
- **Sheets:** parts are packed from the lower left, so what's left is one clean strip across the top (its size
  is in the sheet caption and in LightBurn's Notes). Drag parts to rearrange them, including onto another sheet.
  **R** rotates, the arrow keys nudge (Shift = 10 mm), PgUp/PgDn moves a part to another sheet. Anything closer than
  1.5 mm to another part or 3 mm to the edge, or above the 390 mm reach line, turns red and blocks the export.
  **Re-pack** forgets your arrangement. Hand-placed parts stay put when you change sliders, as long as they still fit.
- **3D:** orbit with the mouse. **Explode** pulls the box apart, **Open lid** / **Pull drawer** / **Lift cover**
  moves what moves. **▶** next to a slider plays it back and forth; **▶ Show assembly** loops: the parts come
  together, the lid opens and closes, the box comes apart again. Grabbing a slider or **⏸** stops where it is.
- **Dimensions** on the 3D: the finished outside (what calipers read on the closed box) and the inside, e.g.
  `50.0 in 42.6`. Sloped consoles give the inside height at the front and the back; a SlidingDrawer's inside is the
  drawer's. Boxes with compartments show each one's clear size on its floor (HobbyCase: each slot's opening), when
  it fits on screen. The lines fade out while the box is open or exploded. The **Dimensions** switch hides them.
- **The camera follows the box:** after every change it keeps your viewing angle and glides so the whole box fits,
  with room for every pose the sliders reach, so exploding or opening never moves it. **Fit view** also turns back
  to the 3/4 view.
- **Overlap check:** once the 3D is still (slider released, animation stopped), Python checks the pose: parts that
  overlap by more than touching turn red, with red dots where they do. "✓ no parts overlap" means every finger sits
  in its slot. While you drag, the maker's mark stays where it was and the check waits until you let go.
- **Maker's mark** `SG` + month + year of the cut (`SG1026`) goes on the bottom, on the LINE layer, never on a lid.
  **Mark here** in the part bar under the sheets moves it to the selected part.
  **Engrave part labels** is off by default: labels then only sit on T1 (shown in LightBurn, never cut).

## Saving and sharing

- **Save** (Ctrl+S) writes `<box name>.box.json`. It holds every parameter, not just the changed ones, plus the
  material, burn, fit, your sheet arrangement, the mark and your notes, and the boxes.py commit it was made with.
  Opening a box made with another boxes.py version shows a warning: check the parts before cutting.
- **Open** reads a `.box.json`. **Recent** lists the last 12 saved boxes in this browser.
- **Share link** copies a link that holds the whole box (compressed into the URL).
- A box opened with other material values than your current profile keeps its own values and says so, with a
  button to switch to the profile.

## What LightBurn gets

One `.lbrn2` per sheet: `01_<name>.lbrn2`, `02_…`. Calibration sheets are `00a_kerf-test` and `00b_fit-comb` in
`00_calibration/`.

| Colour | Layer | Mode | poplar 3.6 values | Used for |
|---|---|---|---|---|
| blue C01 | 2 LINE | Line | 42 % · 133 mm/s | maker's mark, engraved labels, etching from boxes.py |
| red C02 | 3 CUT | Line | 100 % · 12.5 mm/s, 1 pass, no kerf offset | every cut (boxes.py's outer and inner cuts), runs last |
| T1 | tool | never output | | sheet outline, 390 mm reach line, part labels |

Values come from the eVlaser toolchain (`python/evlaser/machine.py`). Holes are cut before outlines
(Inner-to-Outer), the origin is the sheet's lower-left corner, **Start From: Absolute Coords**. Each file opens
with a Notes popup giving the box, the sheet, the estimated time, the offcut size, the fit and where the mark is.

**Your LightBurn changes survive a re-export.** If LightBurn saved a sheet (`01_x.lbrn2`, or its `_backup`), the
next export into the folder keeps that sheet's layer settings and only replaces the geometry. **Reopen the files in
LightBurn after exporting, or you'll cut the old geometry.**

The SVG has red cut lines and blue engrave lines on a 297 × 420 mm page, Y flipped so it matches LightBurn. T1 is
left out, because other programs would cut it.

## Status and what's next

Done:
- the 10 box types with sliders, 2D sheets, packing, LightBurn and SVG export, saving and share links (2026-10-11)
- calibration: kerf X/Y with per-axis compensation, fit comb, press-fit and glue-fit winners per material
  (2026-10-11; measured: kerf X 0.33 / Y 0.26, press fit +0.02)
- 3D assembly for all 10 types, with explode, the open slider (lids on their hinges, drawer, covers, Console2's
  panel and back wall) and the live overlap check. Each type is tested at its default and other sizes: no clashes,
  nothing floating, motion clean (2026-10-12)
- the box type gallery (2026-10-12, see `.grill/box-type-gallery.md`)
- sheets and 3D side by side, live while dragging, dimensions in the 3D, auto-fit, ▶ animations (2026-10-12, see
  `.grill/live-3d-dimensions-autofit.md`). Updates per second while dragging, in Chrome on the RTX 3080 Ti: ABox 30,
  HingeBox 10, TypeTray 7, HobbyCase 2 (`node scripts/drag-bench.mjs draft` measures the Python + 3D part)

Not placed in 3D yet: Console2's panel springs, back-wall latches and latch clamps (8 small parts). They lie in front
of the box. ABox's lid parts lie beside the box for the lid styles that have them.

Next, in this order (agreed 2026-10-11, see `.grill/superboxespy-web-gui.md`):
1. A hole editor on any face (pot, jack, button, USB-C, display presets; holes that hit joints turn red),
   then a panel designer (text in your fonts, logos, SVG import, fills under the line-first rule), then sheet jobs
   (several boxes on shared sheets).
2. A grid editor for TrayLayout instead of the text box.

## For development

```
npm install && npm run setup      # Pyodide + packages into public/pyodide (offline from then on)
npm run dev                       # http://localhost:5199, re-packs python/ on every .py save
npm run build                     # dist/ - what start.bat serves
.venv/Scripts/python -m unittest discover -s tests -v     # Python tests (python -m venv .venv;
                                                          #   pip install shapely affine qrcode pillow)
node scripts/pyodide-smoke.mjs    # the Python side inside Pyodide, like the browser runs it
node scripts/drag-bench.mjs draft # cost of one slider tick per box type (Pyodide build + 3D solids)
.venv/Scripts/python scripts/preview_sheets.py OUT_DIR    # PNG previews of sheets + calibration
python scripts/update_boxes.py [commit]                   # newer boxes.py, then tests
```

| Path | What |
|---|---|
| `python/boxes/` | boxes.py, vendored unchanged (`UPSTREAM_COMMIT`) |
| `python/superboxes/` | `catalog` (types, slider schema), `capture` (runs a generator and keeps each part, its walls' frames and their outlines), `sheets` (packing), `export` (LightBurn/SVG, mark, labels, sheet checks), `assembly` (3D placement, overlap check), `kerf` (per-axis compensation), `calibration`, `traylayout`, `api` (JSON for the worker) |
| `python/evlaser/` | copy of the eVlaser toolchain (`lbrn` writer, `machine` values, `geom`); see its `__init__` for the two changes |
| `src/` | the page: `main` (state, wiring), `worker` + `py` (Pyodide in a web worker), `params` (sliders), `sheetview` (2D), `view3d` (three.js), `calibration`, `config`, `files`, `materials` |

How the 3D knows where parts go: `capture` hooks boxes.py while it draws and records a frame per part:
- **`rectangularWall`:** the wall's callback 0, which fires at its inner corner.
- **`polygonWall`:** its first corner and the border list.
- **`polygonWalls`:** the start of each strip's bottom edge.
- **Chest-hinge lid sides (`p`/`P` edges):** the start of the edge.
- **Every other part:** the origin `move()` gives it.

`assembly` has one assembler per type. It maps those frames into the box from the generator's own values: sections,
hinge axes taken from where the knuckle holes land, and the lid profile. Seen from outside, a wall's u points right,
v up, and the material grows outward.

`assembly.clashes` samples each part's material (shrunk by 0.25 mm, so touching doesn't count) and tests it against
every other part. `assembly.loose_parts` finds parts that touch nothing. `tests/test_core.py` requires all ten types
to pass both.

Cut paths separate material, they don't remove it. A region cut out of a part's hole stays with that part on the
sheet: IntegratedHingeBox's rectangle sits inside the round hinge hole. The ring between them is a loose piece
(the hinge disc), which the 3D draws as a child of the wall.

## Licence

superboxes © 2026 eatingVoltage. Free software under the GNU GPL, version 3 or later (see [LICENSE](LICENSE)),
because boxes.py (© Florian Festi and contributors) is GPLv3. No warranty. Bundled: Pyodide (MPL-2.0), numpy,
shapely (BSD), affine (BSD), qrcode (BSD, `python/_vendor/qrcode/LICENSE`), three.js (MIT), JSZip (MIT).

The headings use LEMON MILK (MARSNEV) when `public/fonts/LEMONMILK-Medium.otf` exists. Its licence doesn't allow
passing the font on, so it isn't in this repo; without it the headings use your system font.
