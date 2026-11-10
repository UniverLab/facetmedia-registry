"""Workshop drawing of the escuadra bracket: three views on one A3 sheet.

Runs inside freecadcmd as ``plano-escuadra.py <out_dir>/<name> <pieza>`` and
writes ``<prefix>-01.svg``: front, top and right views of the part projected
with ``TechDraw.projectToSVG``, laid out from each view's projected bounds at the largest drafting scale
that fits, on one
420x297 mm landscape sheet inside a 10 mm frame, with the part file name and
the scale as the title.
"""

import sys
import xml.sax.saxutils as saxutils
from pathlib import Path

SHEET_WIDTH_MM = 420.0
SHEET_HEIGHT_MM = 297.0
FRAME_MM = 10.0
TITLE_HEIGHT_MM = 18.0
GAP_MM = 10.0

#: Drafting scales, largest first; the sheet uses the largest that fits.
SCALES = (10.0, 5.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01)
#: Visible edges' line weight on the sheet, in mm.
LINE_MM = 0.35

#: (label, projection direction): front, plan and side views.
VIEWS = (
    ("alzado", (0, -1, 0)),
    ("planta", (0, 0, 1)),
    ("perfil", (1, 0, 0)),
)


def _scale_label(scale: float) -> str:
    """A drafting scale label: ``1:N`` when reduced, ``N:1`` when enlarged."""
    if scale < 1:
        return f"escala 1:{1 / scale:g}"
    return f"escala {scale:g}:1"


def _fit_scale(sizes: list[tuple[float, float]], cell_w: float, cell_h: float) -> float:
    """The largest drafting scale at which every view fits its cell."""
    for scale in SCALES:
        if all(w * scale <= cell_w and h * scale <= cell_h for w, h in sizes):
            return scale
    return SCALES[-1]


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <out_dir>/<name> <pieza>")
    prefix, pieza = sys.argv[1], sys.argv[2]

    import FreeCAD
    import Part
    import TechDraw

    shape = Part.read(pieza)
    area_x0 = FRAME_MM + GAP_MM
    area_y0 = FRAME_MM + GAP_MM
    area_w = SHEET_WIDTH_MM - 2 * (FRAME_MM + GAP_MM)
    area_h = SHEET_HEIGHT_MM - 2 * (FRAME_MM + GAP_MM) - TITLE_HEIGHT_MM
    cell_w = (area_w - (len(VIEWS) - 1) * GAP_MM) / len(VIEWS)

    views = []
    for label, direction in VIEWS:
        vector = FreeCAD.Vector(*direction)
        # project() and projectToSVG() share the view plane: (x, y) in the
        # projection is (x, -y) in the SVG fragment, which flips y itself.
        bounds = TechDraw.project(shape, vector)[0].BoundBox
        if bounds.XLength <= 0 or bounds.YLength <= 0:
            raise SystemExit(f"cannot lay out the part {pieza}: the {label} view is empty")
        views.append((label, TechDraw.projectToSVG(shape, vector), bounds))
    scale = _fit_scale([(b.XLength, b.YLength) for _, _, b in views], cell_w, area_h)

    placed = []
    for position, (label, fragment, bounds) in enumerate(views):
        cell_x0 = area_x0 + position * (cell_w + GAP_MM)
        tx = cell_x0 + (cell_w - bounds.XLength * scale) / 2 - scale * bounds.XMin
        ty = area_y0 + (area_h - bounds.YLength * scale) / 2 + scale * bounds.YMax
        # The fragment sets its own stroke-width in model units; keep LINE_MM on paper.
        fragment = fragment.replace('stroke-width="1.0"', f'stroke-width="{LINE_MM / scale:.4f}"')
        placed.append(
            f'<g transform="translate({tx:.3f} {ty:.3f}) scale({scale:g})">'
            f"<!-- {label} -->{fragment}</g>"
        )

    title = f"{Path(pieza).name} · {_scale_label(scale)}"
    sheet = (
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{SHEET_WIDTH_MM:g}mm" height="{SHEET_HEIGHT_MM:g}mm"'
        f' viewBox="0 0 {SHEET_WIDTH_MM:g} {SHEET_HEIGHT_MM:g}">'
        f'<rect x="0" y="0" width="{SHEET_WIDTH_MM:g}" height="{SHEET_HEIGHT_MM:g}"'
        f' fill="white"/>'
        f'<rect x="{FRAME_MM:g}" y="{FRAME_MM:g}"'
        f' width="{SHEET_WIDTH_MM - 2 * FRAME_MM:g}"'
        f' height="{SHEET_HEIGHT_MM - 2 * FRAME_MM:g}"'
        f' fill="none" stroke="black" stroke-width="0.5"/>'
        + "".join(placed)
        + f'<text x="{FRAME_MM + 6:g}" y="{SHEET_HEIGHT_MM - FRAME_MM - 6:g}"'
        f' font-size="5" font-family="sans-serif">{saxutils.escape(title)}</text>'
        f"</svg>\n"
    )
    Path(f"{prefix}-01.svg").write_text(sheet, encoding="utf-8")


main()
