"""Copy of the eVlaser toolchain (~/.claude/skills/eVlaser/scripts/evlaser): machine, geom, lbrn, svgpath.

Frozen into superboxespy so the app runs in the browser (Pyodide) without the skill folder. Changes against the
skill copy: lbrn.render() returns the file as a string (write() still writes it) and lbrn.saved_layers_text()
reads saved layers from a string, nothing else. When the skill
copy learns something new (material values, writer fixes), copy it over and keep that one change.
"""
