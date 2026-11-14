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
script = "bracket-plan.py"
part = "bracket.step"
```

`script` is a FreeCAD Python script run as `<script> <out_dir>/<name> <part>`,
where `<name>` is the script's stem; it must write `<name>-01.svg`,
`<name>-02.svg`, … — consecutive two-digit numbers from 01, each sheet with
`width` and `height` in millimetres on its `<svg>` tag. `part` is the part
file the script opens, both resolved relative to the piece. `run` renders the
sheets into `<name>.pdf` with FreeCAD's bundled Qt and returns the PDF plus
the sheets as assets. Copy `examples/bracket-plan.py`, which draws the
`bracket.step` bracket on one A3 landscape sheet.

The bundled example takes the light route: it projects the part's views
straight onto a hand-laid sheet, with no document. A drawing that carries
dimensions or standard sheet furniture follows the document shape in
references/techdraw.md instead: open the part, check it is worth drawing,
recompute, then build one page per sheet from a pinned SVG template with a
projection group (front, top, side and isometric views, third-angle) at an
explicit scale — and nothing GUI-side, ever.

## Judging the result

`verify` checks the PDF's page count and each sheet's millimetre size.
`preview <name>.pdf` renders the page PNGs from the sheets beside the PDF
and writes the core document shape `{preview, kind, summary, page_count,
pages}` beside it. A person then opens the PDF: a missing view, a dimension
off the geometry or an empty sheet is caught by eye.

Do not stop at what `verify` checks: page count and sheet size pass on an
empty sheet too. Re-open the rendered PNG pages and confirm each sheet
actually shows the part — views present, dimensions legible and attached to
the geometry, no blank pages. Dimensions must be measured from the model
edges they annotate, never typed in by hand: a retyped number stays behind
the day the model changes, while a measured one moves with it. Keep
dimension text clear of views and leaders, and re-read the PDF after every
change, the way the model side re-reads its view.

## Pitfalls

- FreeCAD is never installed: point `facet config set freecad.path` at 1.1.4
  or newer, or set `FREECAD_EXE`; a missing host is `machine_cannot`.
- `freecadcmd` exits 0 when a script raises: the runner's wrapper reports the
  traceback and a non-zero exit, so a failed drawing never looks like a pass;
  the invocation, sys.argv and the lookup order are in references/wrapper.md.
- Recompute after every structural change in a document-based script:
  downstream features otherwise keep consuming the previous shape with no
  error until the export looks wrong, so call `doc.recompute()` before
  projecting anything.
- Never import or call GUI modules headless: GUI imports fail silently
  without a display and selection-driven macros have nothing to select, so
  drive everything explicitly (`Import.export` for whole documents, never
  the GUI-only import calls) and wire each object by name.
- Check the part before drawing it: confirm the opened file's units look
  like millimetres (a bracket-sized bbox, not a room-sized one), refuse an
  empty or invalid solid before projecting views, and compare the STEP mass
  after a round trip when the part matters — an invalid solid draws clean
  views of nothing.
- The script receives an output prefix without extension, not a file name:
  write `<prefix>-01.svg`, `<prefix>-02.svg`, … yourself, one per page.
- Where facet differs from common public advice: some guides expect
  `freecadcmd` itself to exit non-zero on script errors, but observed
  behaviour varies by version, so facet keeps its wrapper, which forces a
  non-zero exit either way. Public drawing guides check sheet content in
  tooling while facet's `verify` checks page count and size only, so
  confirm each sheet is non-empty yourself in the rendered pages.

Sources for the practices above — one row per source, with what was taken
from it — are listed in references/sources.md.
