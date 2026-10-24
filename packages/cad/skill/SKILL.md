---
name: cad
description: 3D parts and 2D plans from CadQuery or ezdxf scripts, verified by volume, bounding box and DXF audit.
---
# cad

Run your own CadQuery or ezdxf script inside the package environment and get
CAD assets back, checked: `cad.solid` executes a CadQuery script and writes
`<name>.step`, `<name>.stl` and `<name>.svg` (the `cad` kind, shown in the
CAD viewer); `cad.drawing` executes an ezdxf script and writes `<name>.dxf`,
`<name>.svg` and `<name>.png`. The part is verified by volume and bounding
box; the plan by a clean DXF audit and its layers. CPU only.

The script is the input and the source of truth: facet runs it unchanged, as
`<env python> -I <script> <out_dir>/<name>`, and the script writes its files
to `sys.argv[1]` plus the extension. Nothing is passed in beyond that stem.

## When to use

- A part or a plan that must be exact and versionable: the geometry lives in
  a script you can diff, review and re-run, not in a GUI session.
- `cad.solid` for 3D: a bracket, a spacer, an enclosure — STEP for CAD, STL
  for printing, a line view to look at.
- `cad.drawing` for 2D: a floor plan, a drill template, a panel layout —
  DXF for CAD, SVG and PNG to look at.
- Not for FreeCAD or Blender modelling (out of scope for v0.1), and not for
  passing parameters into the script: to change the part, change the script.

## Pieces

The lab's escuadra (L bracket) with its volume pinned (`examples/escuadra.toml`):

```toml
[inputs]
script = "escuadra.py"
name = "escuadra"
expect-volume-mm3 = 20805
```

Its script skeleton — place features in absolute coordinates and write to
the stem the runner passes:

```python
import sys
from pathlib import Path

import cadquery as cq

part = cq.Workplane("XZ").polyline([(0, 0), (60, 0), (60, 5), (0, 5)]).close().extrude(-40)
# Holes in absolute coordinates, one cylinder per hole, then cut:
# hole = cq.Solid.makeCylinder(3.25, 15, cq.Vector(45, 20, -5), cq.Vector(0, 0, 1))
# part = part.cut(hole)

out = Path(sys.argv[1])
cq.exporters.export(part, str(out.with_suffix(".step")))
```

A 6 × 4.5 m study plan with its layers pinned
(`examples/plano-estudio.toml`):

```toml
[inputs]
script = "plano-estudio.py"
name = "plano-estudio"
expect-layers = [
  { layer = "muros" },
  { layer = "aberturas" },
  { layer = "mobiliario" },
  { layer = "cotas" },
  { layer = "textos" },
]
```

Its script skeleton:

```python
import sys
from pathlib import Path

import ezdxf

doc = ezdxf.new("R2018", setup=True, units=6)  # 6 = metres
doc.layers.add("muros")
msp = doc.modelspace()
msp.add_lwpolyline([(0, 0), (6, 0), (6, 4.5), (0, 4.5)], close=True, dxfattribs={"layer": "muros"})

out = Path(sys.argv[1])
doc.saveas(out.with_suffix(".dxf"))
```

Run a piece with `facet run cad.solid <piece.toml> --out build/`; without
`--out` the assets land in the piece's directory. The runner completes what
the script leaves out (a missing STL, SVG or PNG view), so writing only the
required file is fine.

## Judging the result

- Set `expect-volume-mm3` (with `volume-rel-tol`, default 0.1 %) or
  `expect-bbox-mm` (one `{ x, y, z }` item — `expect-bbox-mm = [{ x = 60,
  y = 40, z = 50 }]` — with `bbox-abs-tol-mm`, default 0.01 mm) so `verify`
  can fail: it re-imports the STEP, checks `isValid()`, at least one solid,
  and the volume and bbox against those expectations. A wrong feature that
  keeps the volume right shows up in `expect-bbox-mm`; one that keeps both
  right shows up in the view.
- `facet preview <name>.step` writes `solid` with `valid`, `volume_mm3`,
  `bbox_mm`, `faces`, `solids` and `holes`. To fix a misplaced feature,
  read `holes`: each has its `center_mm`, `diameter_mm` and `axis`, so a
  hole at (47, 20, 2.5) instead of (45, 20, 2.5) names the constant to
  change. Then look at the view image (`<name>.view.png`, a shaded
  isometric) — the shape is judged visually.
- For drawings, `verify` audits the DXF with 0 errors and 0 fixes and
  checks every `expect-layers` layer is defined; the preview's `drawing`
  carries `units`, `entities`, `layers` with entity counts and the `audit`,
  so an empty layer (0 entities) or a missing one is visible at a glance.
- The STL, SVG and PNG views pass when they parse: a corrupt mesh or view
  fails `verify` even when the STEP or DXF is perfect.

## Pitfalls

- Place holes and features in **absolute coordinates** (a
  `cq.Solid.makeCylinder` at a known point, then `cut`): a hole positioned
  relative to a face that shifts does not change the volume, so nothing
  betrays it — the lab's rule after measuring the escuadra by hand.
- The script runs with the caller's rights, exactly as `uv run` would: it
  is your code, chosen by you, and facet does not sandbox it further.
- A missing host library (the GL/X stack the OCP kernel links against)
  shows up in `facet doctor cad` as a failed `cadquery` check, with the fix
  `sudo apt install libgl1 libx11-6`.
- The first `facet pull cad` downloads about 560 MB (cadquery-ocp and VTK
  are the bulk; unpacked the environment is about 5 GB); later runs are
  offline.
- Keep the script beside the piece: `inputs = [script]` hashes it into every
  record, so the record names exactly the code that made the part.
