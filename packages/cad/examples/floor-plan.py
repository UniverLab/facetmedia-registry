# /// script
# requires-python = ">=3.11"
# dependencies = ["ezdxf==1.4.4", "matplotlib==3.11.2"]
# ///
"""2D plan of a 6 x 4.5 m study with ezdxf: walls, a door with swing, windows, furniture and dimensions.
Exports DXF (units: metres), SVG and PNG previews, and audits the DXF.
Usage: uv run floor-plan.py [output-without-extension]
The same field test cadspec ran on 2026-10-09."""

import math
import sys
from pathlib import Path

import ezdxf
from ezdxf import colors
from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg
from ezdxf.addons.drawing import matplotlib as draw_mpl
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration

DATA = {
    "width": 6.0,  # m, interior
    "depth": 4.5,  # m, interior
    "wall": 0.15,  # m, thickness
    "door_x": 1.0,  # m, hinge on the south wall
    "door_width": 0.9,  # m
    "windows": {"width": 1.2, "n": 2},  # spread over the north wall
    "table": {"center": (4.2, 2.6), "radius": 0.5, "chairs": 4},
    "bed": {"origin": (0.3, 2.3), "width": 1.4, "length": 2.0},
}
LAYERS = {  # name: (true colour, line weight in hundredths of mm)
    "walls": ("#1d1510", 50),
    "openings": ("#8a6a2c", 25),
    "furniture": ("#6b5a43", 18),
    "dimensions": ("#6b5a43", 13),
    "labels": ("#1d1510", 13),
}

d = DATA
doc = ezdxf.new("R2018", setup=True, units=6)  # 6 = metres
for name, (hex_color, weight) in LAYERS.items():
    layer = doc.layers.add(name, lineweight=weight)
    layer.rgb = colors.RGB.from_hex(hex_color)  # true colour (code 420), not ACI index alone
msp = doc.modelspace()
W, H, t = d["width"], d["depth"], d["wall"]

# Walls: outer and inner outline; the door gap cuts the south wall.
p0, p1 = d["door_x"], d["door_x"] + d["door_width"]
for off in (0.0, t):
    x0, y0, x1, y1 = -off, -off, W + off, H + off
    msp.add_lwpolyline(
        [(p1, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0), (p0, y0)], dxfattribs={"layer": "walls"}
    )
for x in (p0, p1):  # jambs
    msp.add_line((x, 0), (x, -t), dxfattribs={"layer": "walls"})

# Door: leaf open at 90 degrees plus its swing.
msp.add_line((p0, 0), (p0, d["door_width"]), dxfattribs={"layer": "openings"})
msp.add_arc((p0, 0), d["door_width"], 0, 90, dxfattribs={"layer": "openings"})

# Windows spread evenly over the north wall (linear array).
v = d["windows"]
step = W / v["n"]
for i in range(v["n"]):
    cx = step * (i + 0.5)
    a, b = cx - v["width"] / 2, cx + v["width"] / 2
    msp.add_lwpolyline(
        [(a, H), (b, H), (b, H + t), (a, H + t)], close=True, dxfattribs={"layer": "openings"}
    )
    msp.add_line((a, H + t / 2), (b, H + t / 2), dxfattribs={"layer": "openings"})

# Round table with chairs in a polar array.
m = d["table"]
msp.add_circle(m["center"], m["radius"], dxfattribs={"layer": "furniture"})
for i in range(m["chairs"]):
    ang = 2 * math.pi * i / m["chairs"] + math.pi / 4
    cx = m["center"][0] + (m["radius"] + 0.3) * math.cos(ang)
    cy = m["center"][1] + (m["radius"] + 0.3) * math.sin(ang)
    s = 0.2
    pts = [
        (
            cx + s * math.cos(ang + k * math.pi / 2 + math.pi / 4) * math.sqrt(2),
            cy + s * math.sin(ang + k * math.pi / 2 + math.pi / 4) * math.sqrt(2),
        )
        for k in range(4)
    ]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "furniture"})

# Bed with a pillow.
c = d["bed"]
(cx0, cy0), cw, cl = c["origin"], c["width"], c["length"]
msp.add_lwpolyline(
    [(cx0, cy0), (cx0 + cw, cy0), (cx0 + cw, cy0 + cl), (cx0, cy0 + cl)],
    close=True,
    dxfattribs={"layer": "furniture"},
)
msp.add_lwpolyline(
    [
        (cx0 + 0.1, cy0 + cl - 0.45),
        (cx0 + cw - 0.1, cy0 + cl - 0.45),
        (cx0 + cw - 0.1, cy0 + cl - 0.1),
        (cx0 + 0.1, cy0 + cl - 0.1),
    ],
    close=True,
    dxfattribs={"layer": "furniture"},
)

# Interior and door dimensions.
style = doc.dimstyles.get("EZDXF")
style.dxf.dimtxt = 0.15  # text height in m
style.dxf.dimasz = 0.1  # arrows
style.dxf.dimdec = 2
style.dxf.dimzin = 0  # keep zeros: 0.90 and 6.00, not .9 and 6
style.dxf.dimlfac = 1  # the EZDXF style carries 100 (m to cm); here dimensions are in metres
style.dxf.dimdsep = ord(".")  # English decimal separator
dim = {"dimstyle": "EZDXF", "dxfattribs": {"layer": "dimensions"}}
msp.add_linear_dim(base=(0, -0.8), p1=(0, 0), p2=(W, 0), **dim).render()
msp.add_linear_dim(base=(W + 0.8, 0), p1=(W, 0), p2=(W, H), angle=90, **dim).render()
msp.add_linear_dim(base=(0, -0.45), p1=(p0, 0), p2=(p1, 0), **dim).render()

msp.add_text("STUDY", height=0.25, dxfattribs={"layer": "labels"}).set_placement(
    (W / 2, H / 2 - 0.6), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
)
msp.add_text(f"{W * H:.2f} m²", height=0.15, dxfattribs={"layer": "labels"}).set_placement(
    (W / 2, H / 2 - 0.95), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
)

output = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_suffix(""))
doc.saveas(output.with_suffix(".dxf"))

# Audit: what a strict reader (AutoCAD, ODA) would reject.
reloaded = ezdxf.readfile(output.with_suffix(".dxf"))
audit = reloaded.audit()
print(
    f"DXF  {output.with_suffix('.dxf')}  ({len(reloaded.modelspace())} entities, "
    f"{len(audit.errors)} errors, {len(audit.fixes)} fixes in the audit)"
)

# Preview: parchment ground with each layer's own colours.
config = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR)
backend = svg.SVGBackend()
Frontend(RenderContext(reloaded), backend, config=config).draw_layout(reloaded.modelspace())
page = layout.Page(0, 0, layout.Units.mm, margins=layout.Margins.all(10))
output.with_suffix(".svg").write_text(backend.get_string(page))
print(f"SVG  {output.with_suffix('.svg')}")
draw_mpl.qsave(
    reloaded.modelspace(), str(output.with_suffix(".png")), bg="#f4f0ea", dpi=200, config=config
)
print(f"PNG  {output.with_suffix('.png')}")
