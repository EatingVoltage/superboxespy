# Grill: live 3D while dragging, X/Y/Z dimensions, auto-fit
Date: 2026-10-12

## Intent
Watch the box change in 3D while dragging a parameter slider, next to the sheets, with its real size written on
it, and never lose it out of frame. Also animate it: lid/drawer and explode, plus a "show assembly" loop.

## Constraints
- Builds run in Pyodide on one worker. Native build per call: ABox ~8 ms, TypeTray ~30 ms, HobbyCase ~96 ms
  (half of it outline-to-JSON, a third maker's-mark placement); Pyodide is 2-4x slower.
- The 3D solids already have the burn taken off (capture._shape), so measuring them gives the finished size.

## Key decisions
- Decision: Sheets and 3D merge into one split view (2D left, 3D right), draggable divider remembered,
  double-click a half to maximise it / back to split. Explode and lid sliders sit under the 3D half. Calibration
  stays its own tab. Reason: the 3D could never update during a drag while it sat behind the Sheets tab.
  Alternative rejected: picture-in-picture inset, a third "Both" tab.
- Decision: the 3D also has to be faster and was. During a drag: re-pack sheets, update 3D and dimensions,
  **skip maker's-mark placement and the overlap check**; on release a full build. Target in the real app: at
  least 10 updates/s for ABox-sized boxes, at least 4/s for HobbyCase, measured before/after. Rejected: freezing
  the sheets during drags; "nothing lags".
- Decision: animation = a ▶/⏸ per slider (Explode, Open) that sweeps 0→100→0 in a loop, **plus** a "show
  assembly" ▶ that loops like the gallery hover: exploded → assemble → open/close → explode. Grabbing a 3D slider
  or ⏸ stops it where it is; the overlap check runs on the pose it stops at, not during playback. No turntable.
- Decision: types without a hinge/slide (ABox, TypeTray, TrayLayout, Console) keep the lid slider and its ▶
  hidden, as now. ABox lid parts are not placed in 3D. Rejected: lift-off motion for ABox lids.
- Decision: dimensions show **finished outside size and inside size**: `X 50.0 (in 42.8)`, one decimal, burn
  removed (calipers on the finished box), closed and assembled; loose parts and pose don't change them.
  Rejected: outside only, current-pose bounds.
- Decision: "inside" is the whole cavity ignoring dividers; boxes with compartments (TypeTray, TrayLayout,
  HobbyCase) also get each compartment's clear width × depth printed on its floor. Sloped Console/Console2: inside
  height at front and back. Inside is defined per type (the assemblies' current `size` is cavity for some types,
  outside for others) and each type gets a test that inside matches its parameters.
- Decision: CAD dimension lines with arrows and extension lines on the three outside-box edges facing the camera
  (switching as you orbit), drawn on top, screen-facing labels at fixed text size, fading out while exploded or
  open, with a show/hide toggle. Rejected: corner readout, both.
- Decision: on every rebuild (also mid-drag) the camera keeps the user's orbit angle and glides (~150 ms) zoom and
  pan to fit; a manual zoom is overridden by the next parameter change. "Fit view" also resets the angle to the
  default 3/4 view. Rejected: pausing auto-fit after manual camera moves, an auto-fit lock toggle.
- Decision: the fit covers the **whole motion envelope** (closed, fully exploded, fully open) plus dimension
  labels and loose parts, so explode/open/animations never move the camera. Loose parts (Console2's 8) are
  fitted but never measured. Rejected: fitting closed only; following the pose.

## Surfaced assumptions
- The 3D looked as if it rebuilt on every slider tick, but nothing updated during a real drag: the 40 ms debounce
  restarted with every input event (~16 ms apart), and `py.latest` threw away every result that a newer request
  had overtaken - during a drag, all of them. Found by driving the app in headless Chrome.
- The camera re-fitted only when the box type or part count changed.
- Explode and Open lid sliders already existed under the 3D view; Open is hidden on types without motion.
- An idle 3D drawing every frame took CPU from the Python worker (a 30 ms build took 180 ms).
- "Outside" in boxes.py isn't always the outside: ABox and TypeTray with finger-hole bottoms stand on walls that
  reach below the floor (TypeTray "100 outside" is 103.7 tall). The measured dimension shows it.

## Open questions
- HobbyCase reaches ~2 updates/s while dragging (target was 4): most of what's left is boxes.py's own drawing and
  the overlap check (1.2 s) blocking the worker after each release. A second worker for the check, or a cheaper
  check, would be next.
- TypeTray reaches ~7/s (target 10), again mostly boxes.py.

## Out of scope
- Placing ABox lids in 3D / lift-off motion.
- Turntable camera during the assembly loop.
- Dimensions on the 2D sheets.
