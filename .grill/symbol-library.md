# Grill: the symbol library
Date: 2026-11-12

## Intent
Engrave open-source symbols on box faces, picked from one library with a search bar and the recently used ones on
top. Two uses: **device panel labels** (USB, MIDI, power, headphones, in/out next to the parts library's holes) and
**contents labels** (organiser and drawer fronts: screws, cables, tools, components).

## Constraints
- superboxespy is public GPLv3: the sets must allow shipping in the repo, with their license files.
- eVlaser: line first; FILL only for small accents (~20 mm), hatch above (the logo rule).
- The private logos stay as they are: read through `serve.py`, never in the repo.
- Nothing may raise a window while working (global CLAUDE.md).

## Key decisions
- Decision: the sets are **Lucide (ISC) + Tabler outline (MIT)**, both line icons on a 24 grid with a 2-unit stroke.
  Reason: Lucide alone has `midi-port` (5-pin DIN), `usb-c-port` and `screw`; Tabler adds breadth (5,233 icons,
  circuit symbols like resistor and capacitor). Alternative considered: Lucide alone (~2,000), Material Symbols
  (solid shapes, no MIDI, no screw), Tabler alone (no MIDI, no screw).
- Decision: **Tabler's Brand category (378 company logos) is left out**. Reason: the drawings are MIT but the marks
  are trademarks; and it keeps brand noise out of searches. Alternative considered: keep all, keep a few.
- Decision: a symbol is engraved **per item as Line or Solid**, chosen in its bar. Line (the default): one pass
  along each stroke's centre on LINE. Solid: the strokes at their drawn width, FILL up to 20 mm high, hatched above.
  Alternative considered: always Line, always Solid, the outline of each stroke (edges ~0.5 mm apart blur at panel
  sizes).
- Decision: a symbol is a **free item placed by hand**, like a logo (drag, size, pin to an anchor). Reason: works for
  panels and drawer fronts alike. Alternative considered: attached to its hole (moves with it, parts-library holes
  suggesting their symbol).
- Decision: **one library for logos and symbols**: Recent first, then the logos, then the symbols, with one search
  box over all of it. Alternative considered: a Symbol button of its own, one popover with two tabs.
- Decision: with the search box **empty, no symbols are listed**: Recent, the logos and a hint to type. Typing
  searches names and tags. Alternative considered: category chips to browse, everything A-Z.
- Decision: **Recent is the last 16 placed**, logos and symbols mixed, newest first, kept in this browser across all
  boxes; it counts a drop, a click or a Change..., not a look. Alternative considered: this box's own first, a file
  kept by `serve.py`.
- Decision: a `.sbox` keeps a placed symbol as **its name and its drawing** (`lucide:midi-port` + its path data).
  Reason: a box always engraves what was placed, whatever a later update of the set does; the name keeps Change...
  and Recent working. Alternative considered: name only.
- Decision: a **symbol test sheet comes first**: usb, midi-port, power, headphones, screw, circuit-resistor at 5, 8,
  12 and 20 mm, each in Line and Solid, labelled; listed in `todo.md`. Its result sets the smallest size allowed and
  which style is the default.
- Decision: **faces only**: the stamp case's lid keeps its own SVG logo list.

## Defaults set without asking
- The face bar's Logo button becomes **Library** (it now holds both).
- A new symbol lands like a logo (dropped where it's let go, or clicked to the top left) at **10 mm high**, Line.
- Search: every typed word must match the start of a word in the name or a tag; results in the library's order
  (Recent, logos, symbols), symbols ranked name match before tag match, the first 120 shown with a "type more" hint.
  The search box has the focus when the library opens; Enter places the first result, Esc closes.
- Both sets' versions of the same idea are shown (they're drawn differently); a tile's tooltip names its set.
- A zero-length stroke (Lucide's dots: `M12 18h.01`, the MIDI port's pins) is a dot: a small circle the stroke's
  width across in Line, a round spot in Solid.
- Change... swaps a placed symbol or logo for any library entry (symbol for logo too), keeping its place and height.
- The sets are pinned (`lucide-static` 1.72.0, `@tabler/icons` 3.51.0) and turned into one index at build time;
  their license files ship with it and the README credits them.

## Progress
- 2026-11-12, built: `scripts/build-symbols.mjs` turns the pinned sets into `public/symbols.json` (6,907 symbols:
  Lucide 2,052 without its 304 alias files, Tabler 4,855 without 378 brands; 2.0 MB, 0.43 MB gzipped, read on the
  library's first open); `faces.py` draws a "symbol" item (Line, Solid through the logo's `_filled`); the face bar's
  **Library** popover (search, Recent, logos, symbols); `scripts/symbol_test_sheet.py` writes the test sheet to
  `C:\Projects\Laser lightburn\SYMBOL TEST\` (about 10 min, 6.8 of it FILL). Driven in headless Chrome: search, drop,
  Solid, Recent, Change... to a symbol, to a logo and back, save and reopen.
- Found on the way: Lucide writes an arc's flags run together (`a1 1 0 01-1 1`), which `evlaser.svgpath` reads as one
  number; the index spells them out (the shared parser stays as the skill has it). Lucide draws rounded rects with
  `rx`, which `svgart`'s basic shapes ignore: the index turns every element into path data itself.
- Set while building: a symbol's size is its **24-unit grid**, not its drawing's height (a row of symbols at one size
  looks one size; the drawing sits about 2 units inside the grid). Changing a symbol for a logo keeps the number.
  A shape that's filled and stroked (Lucide's dots) is outlined once in Line. The symbol data in the box is
  `symbol`, `path`, `path_fill` (a hole already uses `d`).

## Surfaced assumptions
- None of the four sets checked has a 3.5 mm jack symbol; in/out on a jack is text plus an arrow symbol.
- Lucide's package has search tags but no categories; Tabler has both.
- A line icon's centre line engraved on LINE is thinner than on screen (the laser's ~0.15 mm line against a stroke of
  1/12 of the symbol's size): the test sheet shows whether Line still reads at 5 mm.

## Open questions
- The smallest symbol that reads, and whether Line or Solid is the better default: the test sheet decides.

## Out of scope
- Symbols attached to holes.
- Tabler's filled icons, Material Symbols, Phosphor.
- Brand logos from Tabler.
- The stamp case's lid.
- Browsing by category.
