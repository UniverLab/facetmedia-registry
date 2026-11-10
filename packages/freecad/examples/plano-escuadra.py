"""Workshop drawing of the escuadra bracket: three views on one A3 sheet.

Runs inside freecadcmd as ``plano-escuadra.py <out_dir>/<name> <pieza>`` and
writes ``<prefix>-01.svg``: front, top and right views of the part projected
with ``TechDraw.projectToSVG``, laid out from the shape's ``BoundBox`` on one
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

#: (label, projection direction, plane axes into the shape's BoundBox).
VIEWS = (
    ("alzado", (0, -1, 0), ("x", "z")),
    ("planta", (0, 0, 1), ("x", "y")),
    ("perfil", (1, 0, 0), ("y", "z")),
)


def _scale_label(scale: float) -> str:
    """A drafting scale label: ``1:N`` when reduced, ``N:1`` when enlarged."""
    if scale < 1:
        return f"escala 1:{1 / scale:.2f}"
    return f"escala {scale:.2f}:1"


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <out_dir>/<name> <pieza>")
    prefix, pieza = sys.argv[1], sys.argv[2]

    import FreeCAD
    import Part
    import TechDraw

    shape = Part.read(pieza)
    box = shape.BoundBox
    extents = {"x": box.XLength, "y": box.YLength, "z": box.ZLength}
    corners = {"x": box.XMin, "y": box.YMin, "z": box.ZMin}

    area_x0 = FRAME_MM
    area_y0 = FRAME_MM
    area_w = SHEET_WIDTH_MM - 2 * FRAME_MM
    area_h = SHEET_HEIGHT_MM - 2 * FRAME_MM - TITLE_HEIGHT_MM - GAP_MM
    cell_w = (area_w - 2 * GAP_MM) / len(VIEWS)

    fragments = [
        TechDraw.projectToSVG(shape, FreeCAD.Vector(*direction)) for _, direction, _ in VIEWS
    ]
    fits = [
        min(cell_w / extents[u], area_h / extents[v])
        for _, _, (u, v) in VIEWS
        if extents[u] > 0 and extents[v] > 0
    ]
    if not fits:
        raise SystemExit(f"cannot lay out the part {pieza}: empty bounding box")
    scale = min(fits)

    placed = []
    for position, ((label, _, (u, v)), fragment) in enumerate(zip(VIEWS, fragments)):
        view_w, view_h = extents[u] * scale, extents[v] * scale
        cell_x0 = area_x0 + position * (cell_w + GAP_MM)
        corner_u, corner_v = corners[u], corners[v]
        tx = cell_x0 + (cell_w - view_w) / 2 - scale * corner_u
        ty = area_y0 + (area_h + view_h) / 2 + scale * corner_v
        placed.append(
            f'<g transform="translate({tx:.3f} {ty:.3f}) scale({scale:.4f} {-scale:.4f})"'
            f' fill="none" stroke="black" stroke-width="{0.35 / scale:.4f}">'
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
        + "".join(placed) +
        f'<text x="{FRAME_MM:g}" y="{SHEET_HEIGHT_MM - FRAME_MM - 6:g}"'
        f' font-size="5" font-family="sans-serif">{saxutils.escape(title)}</text>'
        f"</svg>\n"
    )
    Path(f"{prefix}-01.svg").write_text(sheet, encoding="utf-8")


main()
