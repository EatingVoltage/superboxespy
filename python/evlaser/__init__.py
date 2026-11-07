"""Copy of the eVlaser toolchain (~/.claude/skills/eVlaser/scripts/evlaser): machine, geom, lbrn, svgpath, typeset,
textures, preview.

Frozen into superboxespy so the app runs in the browser (Pyodide) without the skill folder. It is the one copy for
every box type: stampcaser's copy was merged in on 2026-11-07 (typeset, textures, the faster outer-contour test in
geom.check_sheet, preview.render_sheet returning its canvas). Changes against the skill copy: lbrn.render() returns
the file as a string (write() still writes it), lbrn.render_pages() returns a LightBurn 2.2 project with a page per
sheet as a string, lbrn.saved_layers_text() reads saved layers from a string, preview.render_sheet() saves only when
given a path. When the skill copy learns something new (material values, writer fixes), copy it over and keep these
changes.
"""
