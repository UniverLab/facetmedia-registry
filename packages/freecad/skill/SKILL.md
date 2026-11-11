---
name: freecad
description: Draw workshop plans from a 3D part with scripted FreeCAD TechDraw, driving the FreeCAD you already have through freecadcmd.
---
# freecad

`freecad.drawing` runs the piece's FreeCAD script headless in `freecadcmd` on the
`part` part and turns the SVG sheets it writes into a paginated PDF with
FreeCAD's own Qt, returning the PDF plus the sheets as assets: a person opens
the PDF, an agent reads the PNG pages `facet preview` renders from the preview
file.

## When to use

- When a part needs a workshop drawing: TechDraw views, dimensions and a
  paginated PDF derived from the 3D model.
- When the work needs assemblies with constraints, FEM or a part opened by
  hand: FreeCAD does what CadQuery does not.
- When the CAD itself is the deliverable: a solid, an STL or a DXF belongs to
  the `cad` package, not here. This package never installs FreeCAD.

## Pieces

```toml
[inputs]
script = "plano-escuadra.py"
part = "escuadra.step"
```

`script` is a FreeCAD Python script run as `<script> <out_dir>/<name> <part>`,
where `<name>` is the script's stem; it must write `<name>-01.svg`,
`<name>-02.svg`, … — consecutive two-digit numbers from 01, each sheet with
`width` and `height` in millimetres on its `<svg>` tag. `part` is the part
file the script opens, both resolved relative to the piece. `run` renders the
sheets into `<name>.pdf` with FreeCAD's bundled Qt and returns the PDF plus
the sheets as assets. Copy `examples/plano-escuadra.py`, which draws the
`escuadra.step` bracket on one A3 landscape sheet.

## Judging the result

`verify` checks the PDF's page count and each sheet's millimetre size.
`preview <name>.pdf` renders the page PNGs from the sheets beside the PDF
and writes the core document shape `{preview, kind, summary, page_count,
pages}` beside it. A person then opens the PDF: a missing view, a dimension
off the geometry or an empty sheet is caught by eye.

## Pitfalls

- FreeCAD is never installed: point `facet config set freecad.path` at 1.1.4
  or newer, or set `FREECAD_EXE`; a missing host is `machine_cannot`.
- `freecadcmd` exits 0 when a script raises: the runner's wrapper reports the
  traceback and a non-zero exit, so a failed drawing never looks like a pass;
  the invocation, sys.argv and the lookup order are in references/wrapper.md.
- The script receives an output prefix without extension, not a file name:
  write `<prefix>-01.svg`, `<prefix>-02.svg`, … yourself, one per page.
