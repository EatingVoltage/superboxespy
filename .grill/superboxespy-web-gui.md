# Grill: superboxespy — boxes.py as a local web GUI with 3D, A3 sheets and LightBurn output
Date: 2026-10-11

## Intent
Build my own box generator on top of boxes.py (florianfesti/boxes): live sliders, 2D and 3D preview, A3 sheet
layout, saved box configs, and output straight to LightBurn files in my layers (or SVG). Today I use the hosted
boxes.py (`pickingbox_2x3.lbrn2` came from it: TypeTray, 3.6 mm, burn 0.14). Its gaps: no live preview, no 3D,
LightBurn output on the wrong layers (outer cut → C00 black, inner → C01 blue, i.e. FILL/LINE in my scheme), no
packing onto my 297 × 390 area, settings only as a URL.

The 3D preview is for **checking and looking**: real parts, moving, with overlaps shown in red.

## Constraints
- Static site, runs entirely in the browser (boxes.py in Pyodide). Just me for now, but ready to host later
  without a rewrite. Works offline (Pyodide bundled). Started by `start.bat`.
- Laser rules from the eVlaser skill apply: Falcon2 40 W, LightBurn 2.1.04, poplar ply 3.6 mm, layers C00 FILL
  black / C01 LINE blue / C02 CUT red (last) / T1 tool, layout limit 297 × 390 portrait, 3 mm edge, 1.5 mm gap,
  origin lower-left with Absolute Coords, maker's mark SG+MMYY, line-first engraving.
- boxes.py is GPLv3, so this project is GPLv3.
- Main browser is Brave, which disables the File System Access API by default: enable
  `brave://flags/#file-system-access-api` or use Chrome/Edge. Plain downloads as a fallback.

## Key decisions
- Box types: Console, Console2, HingeBox, IntegratedHingeBox, PirateChest, SlidingDrawer, HobbyCase,
  TrayLayout, TypeTray, plus **ABox first** (50 mm outside, small tester). Reason: the box types actually built.
  Alternative rejected: all 190 generators (3D per type is hand-written; it doesn't scale).
- 3D: real cut outlines extruded to thickness and assembled per type, with sliders for lid opening, drawer travel
  and exploded view. Overlap check runs live on whatever pose the sliders show and turns clashing parts red.
  Rejected: plain boards (wouldn't catch the Console2 latch/panel clash); swept-volume collision (too costly).
- GUI: sliders with number fields; list editors for section inputs (TypeTray sx/sy, HobbyCase); a grid editor
  for TrayLayout. Upstream's many edge/hinge settings sit under "advanced".
- Config: one `.box.json` per box in a folder picked once (e.g. `C:\Projects\Laser lightburn\boxes\`) holding
  generator, every parameter, material, thickness, kerf/fit, hand-placed sheet layout, notes, and the boxes.py
  version (warn when the generator changed). Also a share link with the config in the URL. Browser storage only
  for a "recent" list.
- Calibration routine for kerf (I couldn't say how 0.14 fitted): (1) kerf strips in X and Y measured with
  calipers, warn if X/Y differ by more than ~0.03; (2) finger-joint comb around it, pick a **press-fit** and a
  **glue-fit** winner, chosen per box with a toggle; (3) thickness by calipers. Saved per material. Hole presets
  are fits too: hole combs centred on caliper measurements.
- Sheets: one box per job by default, packed from the lower-left so the offcut is one clean strip (size shown in
  Notes); a job can run on an "offcut W × H". **Sheet jobs** (several boxes with quantities on shared sheets)
  are an option from the start; a job embeds snapshots of its box configs (refresh button). Parts bigger than
  297 × 390 are an error, never auto-split.
- Hole editor on any flat face, with presets (pot, jack, button, USB-C, display), keep-out zones around
  joints/hinges/latches shown in red.
- **Full panel designer**: text in my fonts (`C:\Projects\eating voltage Fonts`), logos (`slogo*.svg`), SVG
  import, fills — with the line-first rule (warn on fills over ~20 mm, show engrave time per sheet).
- Output: LightBurn `.lbrn2` per sheet in my layers and values (CUT last, inner before outer, Notes popup, T1
  sheet outline + 390 reach line), and SVG.
- Maker's mark `SG` + MMYY of the cut, once per box on the bottom, LINE layer. Part labels on T1 (screen only),
  with a toggle to engrave them.
- Build order: (1) one type end to end — sliders, 2D, LightBurn/SVG, A3 packing, config, calibration sheet;
  (2) 3D for it, then the other types one by one; (3) hole editor, panel designer, sheet jobs.
- Stack: Vite + TypeScript + three.js, boxes.py vendored at upstream commit `b82a6c9` with an update script.

## Surfaced assumptions
- boxes.py has no 3D model at all; generators only draw flat parts, so every 3D assembly is new code.
- The hosted boxes.py already exports lbrn2 and SVG; the value of this tool is preview, my layers, packing,
  calibration and configs — not the export itself.
- burn = 0.14 for 3.6 poplar was never measured.
- The eVlaser skill says "no eV font or logo files yet" — they exist in `C:\Projects\eating voltage Fonts`.

## Open questions
- How tight should joints be by default — press fit or glue fit? (Answered by the calibration cut.)
- What goes into the first console: which device, which panel parts and their measured sizes.
- Whether X/Y kerf differ enough on the Falcon2 to need per-axis compensation.

## Out of scope
- The other ~180 boxes.py generators.
- Collision checking along the whole motion path (only the poses you drag through are checked).
- Automatically splitting parts larger than the work area.
- KiCad import of panel holes (later, maybe).
