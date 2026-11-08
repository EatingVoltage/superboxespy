# Grill: the face editor
Date: 2026-11-07

## Intent
Decorate a box's faces: text, logos, imported SVG, later holes, on all 11 types, as one face editor (decided in
`.grill/stamp-case-merge.md`, step 6). Worked through on a dev example, an eV product box for the CANVAS SYNTH starter
kit; the process is discussed along the way, not settled up front.

## Constraints
- superboxespy is public GPLv3: only OFL fonts ship (eV Sans, ELEMENTS Sans). Licensed fonts (Adam, CANVAS's own)
  never enter the repo. The eV logos stay private and come through `serve.py`, as for the stamp case.
- eVlaser: line first (outlines on LINE), drawn hatch on LINE to darken, fill only for small accents (up to ~20 mm),
  the time per sheet stated at hand-over; the maker's mark stays one 3 mm string on an underside.
- The laser engraves the face that lies up on the sheet.

## Key decisions
- Decision: an item keeps its **anchor** when the box changes size: it pins to the nearest of 9 spots where it's
  dropped (corners, edge middles, centre), keeps its size, and dragging snaps to the spots; what no longer fits or runs
  into a finger joint turns red. Reason: a centred title stays centred, a corner logo stays in its corner. Rejected:
  scaling with the face, fixed mm (the stamp case's dragged blocks today), auto layout until moved.
- Decision: **outside faces only**, for now: each part has one decorated face, cut face up in one pass. Inside faces
  (a message under the lid) come later as their own step, once the outside works on a real cut. Rejected for now:
  two-sided two-page jobs (flip against a stop, like CANVAS's base32 step 1 / step 2 files), inside instead of outside.
- Decision: **eV Sans only** (the brand font; Regular and Bold, as shipped with the stamp case). Rejected: the other
  house fonts at runtime through `serve.py` (Adam, ELEMENTS Sans, Wonderful Snowflake, THE BOLD FONT), every font in
  the folder.
- Decision: **one face end to end first**: the CANVAS lid with the eV logo and "CANVAS SYNTH", anchors, text and logo,
  the 3D showing it, export with the decorated side up, then a test cut of that lid. Walls (with the mirroring a wall
  may need to lie outside up), every type, SVG import and holes follow once the cut looks right. Rejected: text on
  every face of every type first, everything before any cut.

- Decision (2026-11-08): holes are for **device panels** first: part presets plus a plain round and a rounded
  rectangle of any size. Rejected for now: product-box cut-outs (thumb notch, window, hand hold), plain shapes only.
- Decision (2026-11-08): the presets come from Samuel's **parts library** (DeviceWizard's eatingVoltageLibrary), read
  at runtime by `serve.py` like the logos: every part's latest revision, its confirmed front-plate hole or window.
  Private, never in the repo, always current. Rejected: a built-in table (it drifts), plain shapes only, and for now
  turning the library's jack / USB-C case notches into wall holes (needs the board's height in the box).

- Decision (2026-11-08): edge connectors' wall openings come from the library too, placed by a **board height per
  wall** (the board's top above the inside floor, set once per wall): every edge connector on that wall lines up with
  the board and only moves sideways. Rejected: library sizes placed by hand, typed shapes only.
- Decision (2026-11-08): **inside faces** as two pages with a flip (page 1 engraves the inside mirrored, the sheet
  turned over left-right against a corner stop, page 2 engraves the outside and cuts); a registration test cut
  first. Rejected: one side per part, later.
- Decision (2026-11-08): the **thumb notch** first among product-box cut-outs (a half-round notch in an edge to lift
  a lid). Rejected: a hand-hold preset alone (the rounded rectangle makes one), later.

## Progress
- 2026-11-07, the first slice: ABox's over-the-top lid sits on the box in the 3D (lifts off, no clashes); `faces.py`
  finds the closed box's six faces and turns items into LINE engraving on the part, unmirrored (the assembly already
  turns every engraved side out, right-handed, so walls need no mirroring either); the editor offers the Top tab
  (text, logos, anchors, red at the edges, undo). Python places items on all six faces; the editor shows only the
  top until the lid is cut. Example file: `CANVAS STARTER KIT.sbox`.
- 2026-11-07, all faces, before the lid's cut (Samuel: "continue"): a face can be covered on the closed box (the
  over-the-top lid's rims over the walls' top): every placed part wholly outside a face's plane is projected onto it
  and kept clear of; a part less than half in view isn't a face (Console2's inner guide). The maker's mark goes on
  the bottom face and keeps clear of the items there (it was on HingeBox's lid). SVG import (svgart.py). Every tab
  is offered.
- Found on the way: the assembly placed many parts mirrored (2 of ABox's, 23 of HobbyCase's), which a cut part can't
  be, so their engraving showed back to front in the 3D and the editor would have engraved it so. A part symmetric
  across x or y is now placed turned instead (the same solid); the three that aren't (Console's and Console2's right
  sides, Console2's back wall) stay flagged and get no face: they'd need cutting mirrored.

- 2026-11-08, holes: the library's 18 confirmed panel holes and windows as presets (`serve.py` /api/parts), plus round
  and rounded rectangle; cut through the part on a copy (the parts are cached), in the 3D and on the sheets.

- 2026-11-08, edge connectors: the library's six side connectors as wall openings at a board height per wall.

## Defaults set without asking
- An edge connector's opening: its library notch's width where the notch runs out past the body (the measured fit
  at the board's edge), from 0.5 below the board's top to 0.5 above the part (the library's own air, DeviceWizard
  D-60), ends fully rounded (the jack comes out a 6.0 circle on its tube's axis).
- A hole's size is the finished hole: drawn at it when the export compensates the kerf per axis, else the burn inside
  it, as boxes.py's own holes. True circles and rounded corners (Bezier) in LightBurn.
- At least 2 mm of wood between two holes (HOLE_WEB); an engraving across a hole is red. Duplicating a hole puts the
  copy beside it (a row of pots), text below.
- Anchor distances are measured from the finished box's outside edges (what a ruler reads on the closed box). The
  finger-joint strip along a joined edge (thickness + 1.5 mm) is a keep-out: it turns an item red, never moves it.
- Text alignment follows the anchor: left anchors left-align, centre centres, right anchors right-align.
- Styles per item, from the eVlaser rules: outline (LINE, the default), hatched (outline + drawn hatch on LINE), fill
  (FILL, warned above ~20 mm). Each item shows its time.
- An imported SVG is stored inside the `.sbox`, so the file stands alone; house logos go by name (private, this PC).
- A decorated `.sbox` is the template: Save as, change the size and the text, the anchors keep the layout.
- Faces are named by role from where the 3D puts the part (top, bottom, front, back, left, right), not by part
  number: ABox's body parts are only "part 1".."part 5", and roles survive a size change. Per role the biggest part
  facing that way (the front wall, not the lid's rim in front of it).
- A face is shown as seen from outside: up is the box's up on a wall, its back on the top, its front on the bottom
  (tip the box toward you); x to the right.
- Its size is the finished wood (a ruler's reading), the cut path less the burn.
- New text: centred, "TEXT", 10 mm caps, outline. New logo: top left, 15 mm in, 20 mm high, a `lite` logo.
- The example box: ABox 240 x 170 x 90 with the over-the-top lid (`Lid_style` overthetop, a shoebox lid of a
  248 x 178 top and 19 mm rims), sized for the 225 mm BASE18 rails, the module bags, cables, jig and manual.

## Surfaced assumptions
- ABox's lid parts weren't placed in the 3D (every lid style lay "loose" beside the box): the slice put the
  over-the-top lid on the box, with a lift motion. The ontop lid has the same part names at the box's own width and
  stays loose, like the other styles.
- The "walls need mirroring" worry of `.grill/stamp-case-merge.md` was half right: the assembly turns every engraved
  side out, but placed many parts mirrored. Symmetric parts are now placed turned; three asymmetric ones would need a
  mirrored cut and get no face (see Progress).
- CANVAS's own brand font is Adam; on this box its text is eV Sans.

## Open questions
- The test cut: the lid alone (Cut Selected Graphics in LightBurn) or the whole CANVAS box (about two sheets).
- How big the logo and title look best on a 248 x 178 lid, and whether the title reads better outlined or hatched:
  the test cut decides. Files ready: `C:\Projects\Laser lightburn\CANVAS STARTER KIT\` (`.sbox` and `.lbrn2`; the
  lid is on sheet 1, ~6.6 min, 0.7 of it engraving; burn X 0.185 / Y 0.15, the measured profile).
- What tells the cut lid is right (proposed 2026-11-07, not yet answered): the title reads cleanly from arm's length,
  the 0.8 mm crosshatch is even without scorching or cutting in, the logo's double lines stay apart, nothing reaches
  the finger joints. What's off gets fixed in the editor (hatch spacing, outline instead of hatch, sizes) before the
  walls.

## Out of scope (for now)
- Inside faces and two-sided jobs.
- Fonts other than eV Sans.
- Product-box cut-outs (thumb notch, window, hand hold) and wall holes for edge connectors (jacks, USB-C).
