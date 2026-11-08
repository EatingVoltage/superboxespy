# Grill: stampcaser merged into superboxes
Date: 2026-11-07

## Intent
One app for everything laser-cut in a box shape: stampcaser's magnet-closed stamp case becomes an 11th type in
superboxes. Wanted: one app to start and learn, one codebase to maintain (evlaser, kerf, sheets, LightBurn writer once),
and the stamp case in 3D. Not wanted yet: stamp-case boards and box parts on the same sheet (sheet jobs).

## Constraints
- superboxes is the base: browser app, boxes.py in Pyodide, `serve.py` does what a browser can't (start LightBurn,
  write files by full path).
- Every stamp-case rule from `C:\Projects\stampcaser\.grill\stamp-case-designer.md` carries over unchanged (pocket,
  notch, 5 mm web, names A/B/C, magnets, cut corner, lid title, rest-piece cuts).
- Material values come from superboxes' profile. Today they equal stampcaser's hardcoded ones (3.7 mm, kerf X 0.33 /
  Y 0.26), so geometry doesn't move. Pockets get kerf / 2 per axis and no fit (the 1 mm air is the fit); magnet holes
  stay Ø2.6 drawn, no offset.
- superboxespy is public GPLv3. The eV logos are private and never enter the repo.

## Key decisions
- Decision: superboxes absorbs stampcaser; the stamp case is a box type in the gallery. Reason: one app, one codebase,
  3D for free. Alternatives rejected: boxes.py inside the PySide6 app, a shared core with two front-ends, a launcher.
- Decision: stampcaser stays installed until a **parity test** passes: the converted ELEMENTS REV.C PACKAGING and
  MINIPUNK MAXIPUNK cases build the same cut geometry in both apps. Then the stampcaser repo is archived (README points
  here) and the exe uninstalled.
- Decision: every `.stampcase` is converted once to `.box.json` (ELEMENTS REV.C PACKAGING, MINIPUNK MAXIPUNK,
  stampcaser's `first-cut/pages check`). Only `.box.json` exists from then on; superboxes never reads `.stampcase`.
  (Box files became `.sbox` the same day, see below; the three were renamed.)
  Alternative rejected: superboxes opening `.stampcase` files directly.
- Decision: the port starts now; first-cut findings (shared sheets, turned boards, rest cuts are still unconfirmed)
  are fixed once, in superboxes. stampcaser only gets a fix if a case must be cut before the merge is done.
- Decision: layout A. The side panel holds the stamp list and case settings; the 2D half becomes the board editor
  with tabs Base / Lower / Top / Lid / Sheets; the 3D stays right. Rejected: three panes, editing in 3D.
- Decision: optional stamp **thickness** (called thickness, since width x height is the stamp's face). Empty by
  default, so adding a stamp is still name, width, height. With it: the stamp shows in 3D in its pocket, one thicker
  than the pocket depth (boards x 3.7) is a lid clash, and the problems list suggests the pocket-board count.
- Decision: GPLv3 for the ported code. Logos load at runtime from `C:\Projects\eating voltage Fonts\logos`, served by
  `serve.py`; without the folder a case has no logo. eV Sans (OFL) ships.
- Decision: one packer and one sheet view for all 11 types. Stamp-case boards are draggable parts like box parts.
  stampcaser's ranking (fewest sheets, then board area, quarter turns) and its rest-piece cuts on C07 move into the
  shared code; every type gets rest-piece cuts as an export option, default on. Alternatives rejected: stamp case
  keeping its own packer.
- Decision (2026-11-07, step 5): box files are **`.sbox`**, an extension of their own, so a double-click opens them:
  Windows picks a program by the last extension only, and a `.box.json` is a `.json` to it. `.box.json` files still
  open and save as `.sbox`; the five on this PC were renamed (the three converted cases, the ELEMENTS export in
  `Laser lightburn`, a download). Rejected: superboxes taking over `.json` (passing other JSON on to VS Code), a
  right-click entry only, no association.
- Decision: double-clicking a box file opens it in superboxes (the Start-menu install registers it; the launcher
  hands the file to `serve.py`, which opens an app window on it).
- Decision: files live next to their `.box.json`. New boxes default to the picked folder as now; a box opened or
  saved anywhere (double-click, Open..., Save as...) saves and exports beside its own file. `serve.py` writes, because it
  knows the full path. The converted cases stay in their project folders.
- Decision: editor speed. While dragging, TypeScript keeps the item on the grid and checks web and magnet clearance
  itself (red at once); on release Python runs the full layout. Target: release to updated editor and 3D within
  300 ms in Chrome for a 16-stamp case, measured with a bench script. Measured start: native layout 490 ms for
  9 stamps, so Pyodide starts at 1-2 s. Never a frozen UI: "checking..." while it runs.
- Decision: app-wide undo / redo (Ctrl+Z / Ctrl+Y): snapshots of the box JSON, one step per slider drag, cleared when
  another box opens.
- Decision: the **panel designer is built now**, as one face editor in the 2D half, for all 11 types: text (eV Sans,
  outline / crosshatch / fill), logos, SVG import (engrave), and holes / cuts (the hole editor with presets and
  keep-outs at joints). A stamp case's boards are its faces; a box shows a tab per wall. The stamp case's own blocks
  (title, logo, top block, names) are the first users of it. Rejected: shared primitives only, porting as-is.

## Defaults set without asking
- The stamp case's maker's mark stays on the top pocket board, readable from above (its own exception); **Mark here**
  still moves it.
- LightBurn: superboxes' explicit **Open in LightBurn** replaces stampcaser's open-when-idle build.
- Gallery tile: a default case of a handful of stamps; at rest exploded, on hover the boards stack and the lid lifts.
- A box's home (step 5, 2026-11-07): Open... and Save as... are Windows' own dialogs, shown by `serve.py` over the app
  window (IFileDialog: it starts in the box's folder and keeps a last folder of its own; the older GetOpenFileName
  started in whatever folder another Python program used last). Save, the exports and Open in LightBurn write beside
  the box file; files are named after the box name, so renaming saves a new `<name>.sbox` beside the old one.
  New boxes and share links have no home and use the picked folder. A chip next to the name shows the box's folder.
- Rest pieces for any layout (step 4, 2026-11-07): stampcaser's rule made general. The full-width piece above the
  highest part, then bands from the bottom, each ending at a part's top edge, with a piece right of the parts in it.
  Bands whose right ends are within 0.5 mm make one piece; a band under 10 mm joins the neighbour that wastes less.
  Pieces stay square, as stampcaser's did across a board's cut corner, so a cut along an edge with finger notches
  frees the bits in the notches (the other choice: pieces with teeth, nothing loose). The sheet view keeps a copy of
  the rule in TypeScript, from the parts' boxes, to follow a drag; a test checks it against Python on every type.

## Build order
Steps 1-5 and the conversion (7) done 2026-11-07, with logos through `serve.py`. stampcaser retired 2026-11-08
(Samuel: "retire now", before a stamp case had been cut from superboxes): its last record committed, the repo archived
on GitHub with its README pointing here, the exe uninstalled with its own uninstall (Start menu, `.stampcase` file
type, Installed apps entry, program folder). `C:\Projects\stampcaser` stays for the parity tests.
1. Python core: stampcaser's model, shapes, layout, pack, magnets, labels into `python/superboxes/stampcase/`; the two
   evlaser copies merged (typeset, textures, svgpath come over); fonttools in Pyodide; the converter; the parity test.
2. The type end to end: catalog entry, api, sheets, LightBurn export, 3D assembly (explode, lid lift, magnets, stamps).
3. The board editor in TypeScript (layout A), keys R / F / E / N, Ctrl+D, Del, magnets, problems list.
4. One packer with rest-piece cuts for all types.
5. Undo, `serve.py` writing beside the file, double-click a box file (`.sbox`).
6. Face editor for all types: text, logos, SVG, then holes.
7. Convert the three `.stampcase` files, parity, retire stampcaser.

## Surfaced assumptions
- Double-click: Windows picks a file's program by its last extension only, so `x.box.json` is a `.json` file to it;
  a double-click can't reach superboxes without superboxes handling `.json` files (found 2026-11-07, step 5; hence
  `.sbox`). On this PC `.json` had no default program (Windows asks; VS Code, Notepad, Firefox, KiCad were picked).
- stampcaser picked a desktop app because "a browser app can't start programs"; superboxes' `serve.py` since does.
- stampcaser's `LICENSE` said all rights reserved and its repo is private; merging changes that for the code.
- Text on a box wall only reads right if the decorated face lies up on the sheet; parts get flipped for it, using the
  wall frames `capture` already records.

## Open questions
- Whether 300 ms after release is reachable in Pyodide, or what has to move to TypeScript. Measured 2026-11-07 after
  a first pass (scanline hatch, STRtree name checks, cached glyph outlines, one summed-area table per grid): native
  1.36 s -> 0.14 s for ELEMENTS (9 stamps); Pyodide 1.2 s -> 0.2 s, 16 stamps 0.32 s, Re-pack of 16 2.7 s
  (repeated on an idle PC: a first run under load read 0.5 / 0.75 s). 9 stamps meet the target; 16 are just over.
  Answered 2026-11-07, second pass, all in Python: the free-space grids by scanline instead of contains_xy (the same
  points exactly), the boards' paths straight to JSON; 16 stamps 0.25-0.27 s in Pyodide, 9 stamps 0.19 s. Re-pack of
  16: bounding boxes answer most clearance asks, no unions just for a size; 2.8 s -> 1.7 s, the same layouts.
  2026-11-08: the same smoke test read 0.47 / 0.56 s and Re-pack 3.2 s, for the 2026-11-07 code (b70ac90, built in a
  worktree) and the current code alike, while native Python ran as fast as the day before: the PC, not the code.
  Still open: the 300 ms measured in Chrome itself.
- How "Auto-Launch Files in Running Copy" behaves when LightBurn is open (untested in both apps).

## Out of scope
- Stamp-case boards and box parts sharing sheets (sheet jobs stays on the roadmap).
- Reading `.stampcase` files after the one-off conversion.
- Publishing the eV logos.
