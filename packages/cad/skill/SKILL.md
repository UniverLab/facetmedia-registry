---
name: cad
description: 3D parts and 2D plans from CadQuery or ezdxf scripts, verified by volume, bounding box and DXF audit.
---
# cad

Run your own CadQuery or ezdxf script inside the package environment and get
CAD assets back, checked: `cad.solid` executes a CadQuery script and writes
`<name>.step`, `<name>.stl` and `<name>.svg`, plus the optional `<name>.glb`
the script writes (the `cad` kind, shown in the
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

The lab's L bracket with its volume pinned (`examples/bracket.toml`):

```toml
[inputs]
script = "bracket.py"
name = "bracket"
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
(`examples/floor-plan.toml`):

```toml
[inputs]
script = "floor-plan.py"
name = "floor-plan"
expect-layers = [
  { layer = "walls" },
  { layer = "openings" },
  { layer = "furniture" },
  { layer = "dimensions" },
  { layer = "labels" },
]
```

Its script skeleton:

```python
import sys
from pathlib import Path

import ezdxf

doc = ezdxf.new("R2018", setup=True, units=6)  # 6 = metres
doc.layers.add("walls")
msp = doc.modelspace()
msp.add_lwpolyline([(0, 0), (6, 0), (6, 4.5), (0, 4.5)], close=True, dxfattribs={"layer": "walls"})

out = Path(sys.argv[1])
doc.saveas(out.with_suffix(".dxf"))
```

Run a piece with `facet run cad.solid <piece.toml> --out build/`; without
`--out` the assets land in the piece's directory. The runner completes what
the script leaves out (a missing STL, SVG or PNG view), so writing only the
required file is fine.

## Model for blender

Blender reads glTF, not STEP. When the model is headed for blender, have the
script also export an `Assembly` to `<out>.glb` in millimetres, Y-up, with
one named element per piece. A scene script dresses each piece by the start
of its element name; the study example uses `muros`, `piso`,
`vidrio-*`, `cama`, `almohada`, `mesa` and `sillas` (see the blender skill's
`examples/study/`):

```python
import cadquery as cq

assembly = cq.Assembly(name="study")
assembly.add(muros, name="muros")
assembly.add(losa, name="losa")
assembly.export(str(out.with_suffix(".glb")))
```

facet keeps the `<name>.glb` the script writes as one more asset of the
piece; it never generates one itself.

## Judging the result

- Set `expect-volume-mm3` (with `volume-rel-tol`, default 0.1 %) or
  `expect-bbox-mm` (one `{ x, y, z }` item — `expect-bbox-mm = [{ x = 60,
  y = 40, z = 50 }]` — with `bbox-abs-tol-mm`, default 0.01 mm) so `verify`
  can fail: it re-imports the STEP, checks `isValid()`, at least one solid,
  and the volume and bbox against those expectations. A wrong feature that
  keeps the volume right shows up in `expect-bbox-mm`; one that keeps both
  right shows up in the view.
- Aim for exactly one solid in every part: a stray second body (a leftover
  cutter, a duplicated feature) passes `verify` today but is a modelling
  defect — read the `solids` count in the preview and delete the extra body
  before calling the part done.
- `facet preview <name>.step` writes `solid` with `valid`, `volume_mm3`,
  `bbox_mm`, `faces`, `solids` and `holes`. To fix a misplaced feature,
  read `holes`: each has its `center_mm`, `diameter_mm` and `axis`, so a
  hole at (47, 20, 2.5) instead of (45, 20, 2.5) names the constant to
  change. Then look at the view image (`<name>.view.png`, a shaded
  isometric) — the shape is judged visually.
- A passing check is not proof the shape is right: a boolean on touching or
  near-touching faces can succeed with the wrong region kept while
  `isValid()` still passes, so after every geometry change re-read the
  volume, the bbox and the view together and ask whether all three moved
  the way the edit should have moved them.
- After every geometry change, re-render and re-read the view and compare
  it against the previous view — scalars plus a fresh look catch what
  either alone misses — and re-import the STEP to confirm the exported
  file still builds the same volume. On curved or lofted solids allow a
  wider volume drift (about a percent, not the default tenth of a percent),
  because the kernel's own measurement runs high on splines.
- For drawings, `verify` audits the DXF with 0 errors and 0 fixes and
  checks every `expect-layers` layer is defined; the preview's `drawing`
  carries `units`, `entities`, `layers` with entity counts and the `audit`,
  so an empty layer (0 entities) or a missing one is visible at a glance.
- Dimensions on a drawing must be measured from the geometry, never retyped:
  dimension entities reference the points on the part, so editing the model
  moves the values instead of leaving stale numbers beside changed shapes.
  A number copied by hand onto a drawing is a defect even when it happens
  to match today.
- The STL, SVG and PNG views pass when they parse: a corrupt mesh or view
  fails `verify` even when the STEP or DXF is perfect.

## Pitfalls

- Place holes and features in **absolute coordinates** (a
  `cq.Solid.makeCylinder` at a known point, then `cut`): a hole positioned
  relative to a face that shifts does not change the volume, so nothing
  betrays it — the lab's rule after measuring the bracket by hand. More
  generally, a selector that matches nothing, or more than intended, builds
  the wrong part without an error: prefer stable references (`.tag()` and
  workplanes built from tags) for anything positioned off other features,
  and keep the absolute-coordinate rule for holes.
- Round edges before joining, not after: put broad fillets on the
  primitives first, and after a boolean only round by naming an explicit
  point near the edge (`NearestToPointSelector`). A wide selector such as
  "all vertical edges" run after a union or cut is the most common kernel
  crash, because it catches small edges the boolean created.
- The kernel's common failures have known fixes — an error catalogue with
  one-line repairs lives in references/failures.md; read the matching row
  before restructuring a script around a traceback.
- Mind the extrusion direction: an `XZ` workplane extrudes toward `-Y`, so
  a feature drawn on it grows the opposite way from a first guess, and a
  detached-looking solid is usually this sign error. Never place a part by
  reading `bounding_box()` off curved or lofted geometry either: it can
  report several times too wide, so use it to check size, not position.
- Start every script with a named parameters block — lengths in
  millimetres, each with its unit, derived values computed below it, one
  function per feature — and keep literal numbers out of the body. When a
  dimension mates with something real, look it up (a datasheet, two
  agreeing sources), write the source beside the parameter, and mark
  estimates as estimates so a guess never poses as a specification.
- Save STEP as `.step`, never `.stp`: the exporter can silently write
  nothing under the short extension. Never call `show()` (or import a
  viewer) in a script either: it hangs with no display, and facet always
  runs headless with `-I`.
- For drawings, name the unit in the file, not just in your head: the ezdxf
  calls are unitless and the `$INSUNITS` header only tells CAD programs
  what the numbers mean, so set it deliberately for the piece and confirm
  the scale in the preview — an audit-clean file can still be drawn a
  thousand times off. Define every layer, linetype and style the file
  references, and keep the audit at 0 errors and 0 fixes: a fix the auditor
  applies silently can hide a file another program refuses to open.
- Drawing practice that survives real shops lives in
  references/drawing.md: layers carry machine intent (cut vs marking),
  machine-read text goes down as outlines, cut profiles stay closed with no
  duplicates, the model is framed for whoever opens the file next, and a
  current-version file uses that version's entity set.
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
- Where facet differs from common public advice: broad-fillet-last is the
  popular rule, but facet rounds primitives first because wide selectors
  after booleans are the top crash source. Public guides assert exactly one
  solid while facet's `verify` still accepts at least one, so count the
  solids yourself. Public guides check DXF header units in tooling while
  facet's `verify` does not, so set and eyeball the scale yourself.

Sources for the practices above — one row per source, with what was taken
from it — are listed in references/sources.md.
