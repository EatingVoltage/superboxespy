"""What LightBurn's Notes say about a stamp case. The project itself is superboxes' (export.project_files): the
boards are parts that place themselves on the sheets (parts.BoardPart.placed_ev), packed by the shared packer."""
from .. import export as X


def what(lay, board):
    """What happens to one board, for the Notes."""
    if board.key == "base":
        return "engrave + cut. Each stamp's name where its pocket goes. Face up as cut."
    if board.key == "lid":
        return "engrave + cut. Title, logo and every stamp's name over its pocket. %d magnet holes." % len(lay.magnets)
    if board.key == lay.case.top_key:
        return ("engrave + cut. Stamp names, project name, logo and maker's mark %s. %d magnet holes: press a 3 x 4 mm "
                "magnet into each, flush with the top face, no glue." % (lay.mark, len(lay.magnets)))
    return "cut only: the pockets."


def notes_extra(lay, parts, placements):
    """The stamp case's part of the Notes: the case, each board by sheet, assembly."""
    w, h = lay.size
    name = lay.case.project.strip() or "(no project name)"
    out = ['STAMP CASE "%s": %d boards of %.0f x %.0f mm, %d pockets.' % (name, len(parts), w, h, len(lay.pockets))]
    for n in sorted({pl["sheet"] for pl in placements}):
        on = [pl for pl in placements if pl["sheet"] == n]
        out.append("Sheet %d:" % (n + 1))
        out += ["- %s%s: %s" % (parts[pl["part"]].name, ", turned a quarter" if pl["rot"] % 180 else "",
                                what(lay, parts[pl["part"]])) for pl in on]
    out.append("Assembly: glue the base and the pocket boards, cut corners together, edges flush. Lid magnets: stand a "
               "magnet on each magnet of the top pocket board (it snaps on the right way round), lay the lid over them "
               "with the cut corners together and press it down flat.")
    return "\n".join(out)


def project_files(lay, parts, placements, sheet, name, material, previous=None, rest_cuts=True):
    """export.project_files for a stamp case: one LightBurn project, a page per sheet, plus the SVG sheets."""
    return X.project_files(name, "Stamp case " + (lay.case.project.strip() or name), parts, placements, {}, material,
                           sheet, notes_extra=notes_extra(lay, parts, placements), previous=previous,
                           rest_cuts=rest_cuts)
