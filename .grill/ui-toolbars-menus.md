# Grill: toolbars, menus and buttons
Date: 2026-11-09

## Intent
Make the UI clear and streamlined. What set it off: Samuel looked for a toolbar and didn't find one. The face tools
sat in a bar under the face that wrapped to three rows, mixed with the selected item's settings and a paragraph of
help. The goal: every view keeps its tools in one predictable place, every menu works the same way, and there is one
obvious main action.

## Constraints
- **Open in LightBurn** is the button pressed every session: it stays one click.
- Other sessions edit the same working tree. The logo-library work (uncommitted on 2026-11-09: `lbrnart.py`,
  `faceeditor.ts`, `main.ts`, `style.css`, …) gets committed by its own session first. The rework builds on top of
  it in the shared tree, one commit per step: top bar → tabs → 2D toolbar → 3D toolbar → toggles → side panel.

## Key decisions
- Decision: **a toolbar at the top of the 2D view**, right under its tabs, with words rather than icons, its tools
  changing with the tab. Sheets: Re-pack, − / +. Face: Text, Logo, SVG, Hole ▾, then Outside | Inside at the right
  end, then ?. Stamp-case boards: Magnet, Re-pack stamps, Auto magnets. Reason: it sits next to what it acts on, and
  words fit at half the window's width. Alternatives considered: a vertical icon strip like LightBurn's (needs
  icons, takes width from a half view); a full-width strip under the top bar (far from the drawing).
- Decision: **the bar under a view shows only the selection's settings**, and is empty or one short line when
  nothing is selected. Reason: tools and properties stop sharing one wrapping bar.
- Decision: **the board height lives on edge connectors**: it shows in a connector's bar and is asked for when the
  first connector goes on a wall. A wall without connectors never shows it. Alternative considered: the wall's own
  settings in the bottom bar when nothing is selected.
- Decision: **no help text in the bars**. A tooltip names each tool's shortcut ("Rotate · R"). A ? at the toolbar's
  end (and the ? key) opens a card with the tab's shortcuts and what the dashed line and the grey area mean. A line
  stays in the bar only when something is wrong (red). Alternatives considered: one short line of hints at all
  times; tooltips only.
- Decision: **one dropdown component for every ▾** (File, Hole). ▾ opens a menu of words; a panel opens only for
  things you need to see (the logo library, the box-type gallery). **Hole ▾** is a grouped menu with each size
  beside its name: shapes (Round, Rectangle, Thumb notch), Parts library, Edge connectors (walls only). The hole
  lands in the face's centre. Alternative considered: a tile panel like the logo library.
- Decision: **top bar = [type ▾] [name] in <folder> … [File ▾] [Save] [Open in LightBurn]**. File ▾ holds New,
  Open…, Save as…, Copy share link; Export: LightBurn file only, SVGs one per sheet; the Recent boxes as a list; the
  folder (Pick folder). The only amber button is Open in LightBurn, a plain button with no ▾. Alternatives
  considered: keeping New / Open / Recent / Save visible with a ⋯ menu; a desktop menu bar; a split button with the
  exports behind its ▾.
- Decision: **one row of tabs** (Sheets | Front | Back | …). The **Sheets & 3D | Calibration** row goes. Calibration
  opens from **Calibrate…** in the Material section and fills the work area until Back. Alternatives considered:
  keeping both rows; Calibration in File ▾.
- Decision: **the stamp case follows the same frame**: Sheets is the first tab, then Base, the pocket boards, Lid;
  its boards get the toolbar. Typing in stamps (name, W, H) stays in the side panel, because that is entering
  measurements, like the sliders. Alternatives considered: a Stamp button in the toolbar too; leaving the stamp case
  alone until it merges into the face editor.
- Decision: **the 3D mirrors the 2D**: a toolbar on top with [▶ Assembly] [Dimensions] [Fit view], and the pose
  sliders with their ▶ and the overlap line at the bottom. Alternatives considered: leaving the bar as it is;
  controls floating over the 3D.
- Decision: **two kinds of toggle**. A switch is an on/off setting saved with the box (side panel). A segmented
  control picks one of 2–4. In toolbars, a view or format on/off (Dimensions, Bold) is a button lit amber while on,
  like ▶. No checkboxes. Alternatives considered: leaving the mix; switches everywhere.
- Decision: **side panel reordered**. Box comes first. Material folds to one line once it's measured
  ("Poplar 3.7 · press · ● measured ▸"), which opens to material, fit and Calibrate…; it stays open, with its
  notice, while the material is unconfirmed or a box file brings its own values. Engraving & notes moves up under
  Box as **Mark & notes**. Cutting and the 12 boxes.py groups fold into one **Advanced** at the bottom, closed.
  Alternatives considered: tabs inside the side panel; only giving boxes.py's names readable labels.

## Surfaced assumptions
- Samuel expects a tool app's frame: tools along the top of the canvas, the selection's settings next to it. That's
  LightBurn's frame, laid out horizontally and with words.
- Save and Open in LightBurn are the buttons he uses every session. New, Open / Recent, Share link, SVG and the
  plain .lbrn2 export are occasional and can go one level deeper.
- Calibration is done once per material; it isn't a place you work in.

## Open questions
- Readable labels for boxes.py's raw names (Gh, Gw, RoundedTriangleEdge, "h — Edge (parallel Finger Joint
  Holes)"): not decided this round.
- Undo / redo buttons in a toolbar, or the keyboard only (as now).
- Seen in a headless screenshot: after switching from the Front face to StampCase, the 2D half showed the board and
  the sheets stacked. Check whether it's a bug while giving the stamp case the new frame.

## Out of scope
- Merging the stamp case's board editor into the face editor (still its own editor, per todo.md).
- Icons on the toolbar buttons.
