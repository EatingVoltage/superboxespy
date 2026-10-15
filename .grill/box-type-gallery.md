# Grill: box type gallery with 3D thumbnails
Date: 2026-10-12

## Intent
Replace the box-type dropdown with a gallery of thumbnails that show each type **in my material and style**
(3.7 poplar, laser-darkened edges, the app's lighting), consistent across all ten types. The point is a
consistent look, not just recognising the type (the upstream photos would already do that).

## Key decisions
- Decision: real 3D renders for all ten types, so the nine missing 3D assemblies get built **now**, before the
  gallery. Reason: consistency everywhere. Alternatives rejected: upstream photos (mixed backgrounds and
  materials), flat-parts placeholders.
- Decision: each assembly is accepted only when the overlap check reports no clashes with all parts in place (the
  test ABox passed) and the outer size matches the box.
- Decision: thumbnails animate **on hover / keyboard focus only**. At rest a tile shows the box **exploded**. On
  hover the parts **assemble quickly**, then the box **turns slowly** and plays its motion (lid opens and closes,
  drawer slides; boxes without either just turn). On leaving, the box **explodes again**. (Refined mid-build:
  first idea was a still in the most telling pose.) Alternative rejected: all tiles looping at once.
- Decision: thumbnails show each type with its default parameters in the current material, not the last-used
  settings of that type. (Option "your own box, live" was not chosen.)
- Decision: the 3D tab gets the same motions: Open lid / drawer slider for the types that have one.

## Surfaced assumptions
- Upstream boxes.py ships photos of all ten types (`static/samples/<Type>-thumb.jpg`), but in mixed styles.
- "Opening" only exists for HingeBox, IntegratedHingeBox, PirateChest, SlidingDrawer (and ABox lid styles).

## Out of scope
- Live thumbnails that follow the current settings.
- Rendering all ~190 upstream generators.
