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

**Start menu:** after the first build, run `powershell -ExecutionPolicy Bypass -File scripts\add-to-start-menu.ps1`
once. The **superboxes** entry starts the app without a console window. The server keeps running in the background,
and starting the entry again opens another window on it.

**Pick folder** (top right) once, e.g. `C:\Projects\Laser lightburn`. From then on every export goes to
`<folder>/<box name>/`: the LightBurn project (one page per sheet), the `.svg` sheets and the box's `.sbox`. The measured material
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
- **Sheets:** parts are packed from the lower left, so what's left is mostly one clean piece across the top. Drag
  parts to rearrange them, including onto another sheet.
  **R** rotates, the arrow keys nudge (Shift = 10 mm), PgUp/PgDn moves a part to another sheet. Anything closer than
  1.5 mm to another part or 3 mm to the edge, or above the 390 mm reach line, turns red and blocks the export.
  **Re-pack** forgets your arrangement. Hand-placed parts stay put when you change sliders, as long as they still fit.
- **Rest pieces:** the rest wood is cut free as rectangles once the parts are done (on by default; **Cut the rest
  pieces free** under Engraving & notes). The sheets show each piece with its size and the dashed magenta cuts that
  free it, and follow while you drag. The cuts carry the parts' own edges out to the sheet's edges: the full width
  above the highest part (the **top rest piece**), then right of the parts, a piece per step in their right edge.
  A piece needs 10 mm both ways, and a cut never runs above the reach line. The pieces come off square, so where a
  part's top or right edge has finger notches, the cut across them frees the small bits of wood in the notches too.
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
- **Maker's mark** `SG` + month + year of the cut (`SG1026`) goes on the bottom face of the closed box (or a bottom
  part when the box has no assembly), on the LINE layer, never on a lid, and out of the way of what you put there.
  **Mark here** in the part bar under the sheets moves it to the selected part.
  **Engrave part labels** is off by default: labels then only sit on T1 (shown in LightBurn, never cut).
- **Text, logos and SVG on the faces** (the face editor: `.grill/face-editor.md`). Beside **Sheets** there's a tab
  per face of the closed box (Top, Front, Back, Left, Right, Bottom), each seen from outside: a wall with the box's
  up on top, the top with the front toward you, the bottom tipped toward you. **Add text** (eV Sans, Regular or Bold,
  outline or hatched, several lines), **Add logo** (the eV logos through `serve.py`) or **Import SVG** (line art: its
  paths and shapes; convert text to paths first; its own size if the file says it in mm; the file is kept in the box),
  then drag it. Where you drop an item it pins to the nearest corner, edge middle or the centre and keeps its distance
  from it, so a centred title stays centred and a corner logo stays in its corner when the box changes size; text
  lines align to that side. The dashed line keeps the thickness + 1.5 mm off the edges and finger joints, and off
  what covers a face on the closed box (grey: an over-the-top lid's rim over the walls): an item across it turns red
  and blocks the export. **R** rotates, the arrow keys nudge (Shift 10 mm), **Ctrl+D** duplicates, **Del** deletes.
  The items engrave on LINE on the side that faces out, and show on the 3D and the sheets. A face the box only has
  as a part that would need cutting mirrored (Console's and Console2's right sides, Console2's back wall) isn't
  offered.
- **Holes for device panels**: **Add hole…** on a face gives a round or rounded-rectangle hole of any size, or the
  panel hole of a part from your parts library (`%USERPROFILE%\eatingVoltageLibrary`, DeviceWizard's: every part with
  a confirmed front-plate hole or window, read by `serve.py`, never in this repo): RK09 pots, toggles, buttons, rotary
  switches, slide pots, the OLED window... The size is the finished hole: the kerf is taken care of as for boxes.py's
  own holes (true circles and rounded corners in LightBurn). A hole cuts through the part on the sheets and in the 3D,
  keeps 2 mm of wood to the next hole, and an engraving across it turns red. **Duplicate** puts the copy beside it.
  Jacks and USB-C at a board's edge aren't in the library as wall holes yet: use a round or rectangle there.

## The stamp case

**StampCase** in the gallery is a magnet-closed case for rubber stamps: a base, pocket boards with a pocket per stamp,
a lid. It came from stampcaser (`C:\Projects\stampcaser`, 1.0.0), merged in on 2026-11-07
(`.grill/stamp-case-merge.md`); its rules (pocket and finger notch, 5 mm of wood between pockets, names engraved
three times, magnets, the eV cut corner, the hatched lid title) are stampcaser's, unchanged
(`C:\Projects\stampcaser\.grill\stamp-case-designer.md`).

- **Side panel:** the project name (the lid's title), how many pocket boards (2 make pockets 7.4 mm deep), the logo,
  and the stamps. Type a stamp's name, width and height **as measured** and press Enter: 1 mm of air goes on every
  side and the pocket lands in free space. Each stamp's row edits its name and size; the **t** field takes its
  thickness if you want it checked (empty is fine). **Re-pack stamps** (Ctrl+P) lays every pocket out from scratch:
  fewest sheets, then the smallest board. **Auto magnets** (Ctrl+M) hands the magnets back to the app.
- **Check** lists what blocks the cut (red) and what's only a warning; click one to see it. Under it: the board
  size, how many boards a sheet takes, and when a board a few mm smaller would save a sheet.
- **The 2D half** has a tab per board (Base, pocket boards, Lid) and **Sheets**. Drag pockets, magnets and the text
  blocks; anything too close to something else turns red while you drag. **R** rotates (a pocket or a block),
  **F** moves the finger notch to the other side, **E** to the other end, **N** says where the stamp's name prefers to
  go (beside the notch, the opposite side, the far end), **Ctrl+D** duplicates, **Del** deletes, arrow keys nudge.
  Double-click free wood on the top pocket board or the lid for a magnet. Wheel zooms, the middle button pans,
  Ctrl+0 fits.
- **3D:** the boards stacked, **Explode** spreads them, **Lift cover** takes the lid off. Magnets show in their
  holes; a stamp with a thickness sits in its pocket, red when it's too thick for the lid to close.
- **Material:** a stamp case takes the profile's kerf, half of it per axis on outlines and pockets, and **no fit**:
  the 1 mm of air is the fit. Magnet holes are drawn at Ø2.6 without any offset (3 × 4 mm magnets, pressed in).
- **Logos** come from `C:\Projects\eating voltage Fonts\logos`, through `serve.py`; they never ship with the app.
  Under `npm run dev` or without that folder a case has no logo.
- The boards go on the sheets like any box's parts, so you can drag them there too.
- `scripts/convert_stampcase.py` turned stampcaser's `.stampcase` files into box files (done once, 2026-11-07).

## Saving and sharing

- **A box is a `.sbox` file** (JSON). **Double-click one** to open it here: `scripts/add-to-start-menu.ps1`
  registers `.sbox` for you, and the box opens in an app window (on the server that's already running, if there is
  one; `serve.py <file>` does the same). Boxes saved before 2026-11-07 are `.box.json`: they still open and save as
  `.sbox` (a `.box.json` is a `.json` file to Windows, so a double-click could never reach it).
- **Save** (Ctrl+S) writes `<box name>.sbox`. It holds every parameter, not just the changed ones, plus the
  material, burn, fit, your sheet arrangement, the mark and your notes, and the boxes.py commit it was made with.
  Opening a box made with another boxes.py version shows a warning: check the parts before cutting.
- **Open** reads a box. **Recent** lists the last 12 saved boxes in this browser.
- **A box keeps its files beside it.** Opened with **Open** (Windows' own dialog) or saved with **Save as…**
  (Ctrl+Shift+S), or double-clicked, a box lives where its `.sbox` is: the chip next to its name shows the folder,
  and **Save**, the exports and **Open in LightBurn** write into that folder (`<name>.sbox`, `<name>.lbrn2`,
  `NN_<name>.svg`). So `C:\Projects\ELEMENTS SYNTH\hw\packaging\ELEMENTS REV.C PACKAGING.sbox` exports right there.
  **Recent** reads such a box from its file again. `serve.py` does the reading and writing (a browser never learns
  full paths): it writes only `.sbox`, `.lbrn2` and `.svg` files beside a box, for this PC's own page. New boxes and boxes
  from a share link go to the picked folder, `<folder>/<box name>/`, as before. Under `npm run dev` there's no
  `serve.py`, so Open is the browser's and everything goes to the picked folder.
- **Share link** copies a link that holds the whole box (compressed into the URL).
- A box opened with other material values than your current profile keeps its own values and says so, with a
  button to switch to the profile.

## What LightBurn gets

**One LightBurn project per box, `<name>.lbrn2`, with one page per A3 sheet** ("Sheet 1", "Sheet 2", …: the tabs over
the workspace or the Pages panel). Pages need **LightBurn 2.2** or newer; older versions show every sheet's parts on
top of each other. Open a page, then Start: **only the page shown is cut** (checked 2026-11-07 in LightBurn 2.2.01
by saving G-code from page 1 and page 2: each held only its own page). With **Cut Selected Graphics** on, select
first; Select All takes only the page shown. Layers and the Notes belong to the project, so they're the same on every
page. Calibration sheets are `00a_kerf-test` and `00b_fit-comb` in
`00_calibration/`.

- **Export as LightBurn** writes the project (beside the box's own file, or with a folder: into
  `<folder>/<box name>/`, plus the `.sbox`).
- **Open in LightBurn** does the same, then opens the project in LightBurn. It needs a picked folder (it asks for
  one if there isn't one yet) and the app started from `start.bat` or the Start menu entry, because `serve.py` starts
  LightBurn: a browser can't. The browser also never learns the folder's full path, only its name, so `serve.py`
  looks for a folder by that name in your home folder and near the top of each fixed drive (e.g.
  `C:\Projects\Laser lightburn`). It opens the file only if it's byte for byte the one just written. If it can't
  find the folder, the app asks for its path once and remembers it. LightBurn comes to the front once its window is
  up, but only if the superboxes window still has focus by then. With LightBurn already open, the project opens in
  that LightBurn, which first asks whether to save the project it has open, as a double-click on the file would.

| Colour | Layer | Mode | poplar 3.6 values | Used for |
|---|---|---|---|---|
| blue C01 | 2 LINE | Line | 42 % · 133 mm/s | maker's mark, engraved labels, etching from boxes.py |
| red C02 | 3 CUT | Line | 100 % · 12.5 mm/s, 1 pass, no kerf offset | every cut (boxes.py's outer and inner cuts) |
| C07 | 4 CUT frame | Line | CUT's values | the rest-piece cuts, run last; switch its Output off to keep a sheet whole |
| T1 | tool | never output | | sheet outline up to the 390 mm reach (its top edge is the reach line), part labels |

Values come from the eVlaser toolchain (`python/evlaser/machine.py`). Holes are cut before outlines
(Inner-to-Outer), the origin is the sheet's lower-left corner, **Start From: Absolute Coords**. The project opens
with a Notes popup giving the box, each sheet's parts, estimated time and rest pieces, the fit and where the mark is.

**Your LightBurn changes survive a re-export.** If LightBurn saved the project (`x.lbrn2`, or its `_backup`), the
next export into the folder keeps its layer settings and only replaces the geometry. Boxes exported before pages
have one `01_x.lbrn2` per sheet: their saved layers carry over to the first project, and the export reminds you to
delete the old files. **Reopen the project in LightBurn after exporting, or you'll cut the old geometry.**

The SVG export stays one file per sheet (`01_<name>.svg`, `02_…`): red cut lines, blue engrave lines and the
rest-piece cuts in magenta on a 297 × 420 mm page, Y flipped so it matches LightBurn. T1 is left out, because other programs would cut it.

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

- the stamp case, stampcaser merged in: an 11th type with its board editor, 3D, the shared packer (which now also
  tries every part turned / upright, so it never needs more sheets than stampcaser did), undo / redo for every type,
  logos through `serve.py` (2026-11-07, see `.grill/stamp-case-merge.md`). `tests/test_stampcase.py` checks every
  existing case against stampcaser itself, board by board, kerf included.
- rest-piece cuts for every type, stampcaser's C07 frame layer made general (2026-11-07): on stampcaser's own sheets
  they are stampcaser's pieces and cuts; the sheet view's copy of the rule is checked against the export's.
- a box keeps its files beside its own file, a `.sbox` that opens with a double-click: Open and Save as… are
  Windows' dialogs through `serve.py`, which reads and writes there (2026-11-07). `tests/test_serve.py` runs the real
  dialogs on a desktop that's never shown.

Not placed in 3D yet: Console2's panel springs, back-wall latches and latch clamps (8 small parts). They lie in front
of the box. ABox's over-the-top lid sits on the box (Lift cover takes it off); its other lid styles' parts lie
beside the box.

Next, in this order (agreed 2026-11-07, see `.grill/stamp-case-merge.md`):
1. The CANVAS starter-kit box's lid test cut (`.grill/face-editor.md`), then the face editor's next steps: wall holes
   for edge connectors from the library's case notches, inside faces. The stamp case keeps its own board editor for
   now.
2. Retire stampcaser once a case has been cut from here.
3. Sheet jobs (several boxes on shared sheets), a grid editor for TrayLayout.

A stamp-case build after an edit met its 300 ms: 0.19 s for 9 stamps, 0.25-0.27 s for 16; Re-pack of 16 took 1.7 s
(Pyodide under Node, `node scripts/pyodide-smoke.mjs`, 2026-11-07). On 2026-11-08 the same PC read about twice that
for the old and the new code alike (native Python unchanged), so check it in Chrome on a quiet PC before relying on it.

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
| `python/superboxes/` | `catalog` (types, slider schema), `capture` (runs a generator and keeps each part, its walls' frames and their outlines), `sheets` (packing, rest pieces), `export` (LightBurn/SVG, mark, labels, sheet checks), `assembly` (3D placement, overlap check), `kerf` (per-axis compensation), `calibration`, `traylayout`, `api` (JSON for the worker); `stampcase/` (the stamp case: `model`, `layout`, `pack`, `magnets`, `labels`, `parts` = its boards as parts, `api`) |
| `python/evlaser/` | copy of the eVlaser toolchain (`lbrn` writer, `machine` values, `geom`); see its `__init__` for the two changes |
| `src/` | the page: `main` (state, wiring), `worker` + `py` (Pyodide in a web worker), `params` (sliders), `sheetview` (2D, with a copy of the rest-piece rule), `view3d` (three.js), `calibration`, `config`, `files`, `materials`, `stampcase` (the stamp case's side panel and board editor) |

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
