# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["cadquery==2.8.0"]
# ///
"""L-shaped mounting bracket, parametric, in CadQuery: the reference pattern for 3D parts.

Exports STEP (CAD), STL (3D printing) and a line SVG view. Runs natively on Linux.
Verified: volume 20,806 mm³ (hand calculation 20,805) and hole centres at (45, 20, 2.5) and (2.5, 20, 35);
the same part in FreeCAD is bracket-freecad.py.
Usage: uv run bracket.py [output-without-extension]"""

import sys
from pathlib import Path

import cadquery as cq

DATA = {
    "width": 40.0,  # mm, along the fold
    "base_flange": 60.0,  # mm, horizontal flange
    "wall_flange": 50.0,  # mm, vertical flange
    "thickness": 5.0,  # mm
    "inner_radius": 4.0,  # mm, fold fillet on the inside
    "hole_diameter": 6.5,  # mm, for an M6 screw
    "hole_margin": 15.0,  # mm, from the end of each flange
}
d = DATA

# L profile in the XZ plane, extruded across the width (Y).
profile = (
    cq.Workplane("XZ")
    .polyline(
        [
            (0, 0),
            (d["base_flange"], 0),
            (d["base_flange"], d["thickness"]),
            (d["thickness"], d["thickness"]),
            (d["thickness"], d["wall_flange"]),
            (0, d["wall_flange"]),
        ]
    )
    .close()
    .extrude(-d["width"])
)
# Inner fillet: the only edge parallel to Y at x = z = thickness.
bracket = (
    profile.edges("|Y")
    .edges(cq.selectors.NearestToPointSelector((d["thickness"], d["width"] / 2, d["thickness"])))
    .fillet(d["inner_radius"])
)
# Holes in absolute coordinates (a hole placed relative to a face would not change the volume if misplaced,
# so nothing would give it away): one per leg, centred across the width.
r, t, V = d["hole_diameter"] / 2, d["thickness"], cq.Vector
base_hole = cq.Solid.makeCylinder(
    r, 3 * t, V(d["base_flange"] - d["hole_margin"], d["width"] / 2, -t), V(0, 0, 1)
)
wall_hole = cq.Solid.makeCylinder(
    r, 3 * t, V(-t, d["width"] / 2, d["wall_flange"] - d["hole_margin"]), V(1, 0, 0)
)
bracket = bracket.cut(base_hole).cut(wall_hole)

solid = bracket.val()
if not solid.isValid():
    raise RuntimeError("The resulting geometry is not valid")

output = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_suffix(""))
cq.exporters.export(bracket, str(output.with_suffix(".step")))
cq.exporters.export(bracket, str(output.with_suffix(".stl")), tolerance=0.05, angularTolerance=0.2)
cq.exporters.export(
    bracket,
    str(output.with_suffix(".svg")),
    opt={"projectionDir": (1.2, -1, 0.8), "showHidden": False, "width": 600, "height": 450},
)
print(f"volume {solid.Volume():.0f} mm³ · faces {len(solid.Faces())}")
for ext in ("step", "stl", "svg"):
    print(f"{ext.upper():4} {output.with_suffix('.' + ext)}")
