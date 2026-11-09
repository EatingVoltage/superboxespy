# Grill: the logo library
Date: 2026-11-08

## Intent
Drag vector logos from a library onto a box's faces, engraved; size them and move them there. The face editor already
had logos (a dropdown of the 9 eV SVGs, a typed height, drag with anchors); what's new is a library of Samuel's own
brand marks, made where they already live (LightBurn), dragged in, and sized by hand.

## Constraints
- The logos stay private: read at runtime through `serve.py` from `C:\Projects\eating voltage Fonts\logos`, never in
  the public repo (as `.grill/face-editor.md`, `.grill/stamp-case-merge.md`).
- eVlaser: line first; FILL only for small accents (~20 mm); a logo's Cut layer never cuts through on a box.
- Nothing may raise a window while working (global CLAUDE.md): previews and checks render headless.

## Key decisions
- Decision: the library holds **Samuel's own brand marks** (eV, CANVAS, ELEMENTS, ...). Reason: what goes on his boxes.
  Alternative considered: panel symbols (USB, MIDI, jack), customers' logos, the eV versions only.
- Decision: the library **reads .lbrn2 directly**, next to the existing SVGs. Reason: the marks live in LightBurn with
  live text; no export step. Alternative considered: SVG export into the folder, an Add-to-library button, dropping
  files from Explorer into one box.
- Decision: **one file is one logo**; a box links to the file name. A logo from a poster gets copied into a file of
  its own. Reason: a file name is stable. First decided as "named groups", on my claim that LightBurn names groups:
  it doesn't (2.1's Shape Properties has no name; the only `Name`s in Samuel's files are pages, `SubType="Page"`).
  Alternative considered: one logo per page (renaming pages unverified), every group by position (an edited file can
  swap which group a box engraves).
- Decision: the library is **the existing logos folder**, `C:\Projects\eating voltage Fonts\logos`. Reason: one
  private place for brand art, already served. Alternative considered: a new `Laser lightburn\logos`, all of
  `Laser lightburn` (74 files of jigs and cases).
- Decision: live text is drawn from the **BackupPath** LightBurn stores with every Text shape. Reason: exactly what
  LightBurn engraves, no licensed font files read. Alternative considered: rendering Adam etc. with fontTools.
- Decision: **engraving follows the file's layers**: Scan shapes are filled, Line / Cut shapes are outlines on LINE;
  per placed logo an "outline only" switch. Reason: the logo's design intent is in the file. Alternative considered:
  outline / hatch per logo ignoring layers, real FILL always.
- Decision: a logo's filled shapes go on **FILL while the placed logo is 20 mm high or less, a drawn hatch on LINE
  above**. Reason: a 0.8 mm hatch breaks up in 3-5 mm letters (CANVAS's MODULAR SYSTEM); eVlaser allows FILL for
  small accents. Measured on the height set, the number seen. Alternative considered: always hatch with a warning,
  the longer side (the 3.5:1 CANVAS logo would never fill), per filled shape (fill and hatch mixed in one logo).
- Decision: a box **links the logo by name**: a changed file changes every box using it; a missing file or group
  turns the item red. Reason: fix a logo once. Alternative considered: a copy in the `.sbox` (as Import SVG), a copy
  with an update notice.
- Decision: the library is a **popover from Add logo**: drag a tile onto the face, or click it. Reason: takes no room
  when closed. Alternative considered: a strip above the bar, a column beside the face.
- Decision: **corner handles resize every engraving item** (library logos, imported SVGs, text's cap height),
  proportions locked, 0.5 mm steps, the typed height stays. Holes keep typed sizes only (a part's hole stays exact).
  Alternative considered: logos only, holes too.
- Decision: **moving stays as it is** (drag, arrows, pin to the nearest of 9 spots, R for 90°). Alternative
  considered: any-angle rotation, snapping to other items, mirroring.
- Decision: the **stamp case keeps its SVG logos**; its list never shows .lbrn2 entries.
- Decision: seed the folder with copies of `canvas logo.lbrn2` and `eatingVoltage logo.lbrn2` (originals stay in
  `C:\Projects\Laser lightburn`).

## Progress
- 2026-11-08, built: `lbrnart.py` reads a .lbrn2 (all 74 files in `C:\Projects\Laser lightburn` read with every
  shared list found; canvas logo, eatingVoltage logo, the ELEMENTS poster drawn as their thumbnails show); a logo item
  links .svg or .lbrn2 by name; small fills go to FILL as polygons (time estimate, the inside page and the 3D fill
  them); the library popover with drag in, click and Change…; corner handles on text, logos and SVGs. Driven in
  headless Chrome on a copy of `CANVAS STARTER KIT.sbox`: dropped at 20 mm filled, sized to 42.5 mm hatched, swapped;
  console clean. Seeded: `canvas logo.lbrn2`, `eatingVoltage logo.lbrn2` (that file holds the logo twice, one framed:
  trim it to one in LightBurn).
- Found on the way: a LightBurn path can run a tail into its loop (the CANVAS V: vertex 0 -> 1, then a loop back to
  1): the loop is filled, the tail isn't. A Text's BackupPath XForm already holds its groups' moves.

## Defaults set without asking
- The popover closes as a drag starts, so the whole face is the drop target; the logo's centre lands under the
  pointer and pins to the nearest spot. A click adds it at the old default (top left, 15 mm in, 20 mm high).
- Resizing keeps the corner opposite the dragged handle in place; the item re-pins afterwards.
- Previews are drawn from the vectors (the same drawing that's engraved, not LightBurn's thumbnail), filled shapes
  shown filled.
- A file with several pages is its first page (the other pages are `SubType="Page"` groups).
- Layer types: Scan and Offset Fill are filled; Cut and Line are outlines; Scan+Cut is both. Image layers, bitmaps
  and tool layers are skipped; an entry with nothing drawable isn't listed.
- A selected logo's bar has Change… (the popover, swapping the logo in place), the height, and "As drawn" /
  "Outline only" when it has filled shapes.
- Existing boxes' SVG logo items keep working unchanged; an SVG logo is outlines.

## Surfaced assumptions
- The brand marks didn't exist as files the app could read: only the eV logo was an SVG; CANVAS, eatingVoltage.com
  and the ELEMENTS art live in .lbrn2 with Adam / Wonderful Snowflake text.
- `canvas logo.lbrn2` is drawn as 97.5 × 27.8 mm (3.5:1), all on one Scan layer; at 20 mm high its MODULAR SYSTEM
  letters come out about 4.5 mm.
- `eatingVoltage logo 2.lbrn2` holds a bitmap: not vector, skipped.
- Every Text shape carries LightBurn's own outline of it (`BackupPath`, with the Text's transform); groups' transforms
  apply to their children; most paths reuse an earlier one's points by `VertID` / `PrimID`.
- Face items engraved only on LINE so far; FILL comes with this.

## Open questions
- There's no ELEMENTS mark as one piece: `elements Promo.lbrn2` is a poster. Samuel copies the mark into a file of its
  own when he wants it.
- Whether 20 mm of fill reads right next to hatched items, and the fill's time on a 70 mm wide logo: the CANVAS lid's
  test cut decides.

## Out of scope
- Panel symbols, customers' logos.
- Any-angle rotation, snapping between items, mirroring.
- The stamp case's lid logo.
