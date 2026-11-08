---
name: freecad
description: Draw workshop plans from a 3D part with scripted FreeCAD TechDraw, driving the FreeCAD you already have through freecadcmd.
---
# freecad

`freecad.plano` runs the piece's FreeCAD script headless in `freecadcmd` on the
`pieza` part and turns the PDF it writes into a paginated document: a person
opens the PDF, an agent reads the PNG pages from the preview file.

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
guion = "plano-escuadra.py"
pieza = "escuadra.step"
```

`guion` is a FreeCAD Python script run as `<guion> <out_dir>/<name> <pieza>`,
where `<name>` is the guion's stem; it must write `<name>.pdf`. `pieza` is the
part file the script opens, both resolved relative to the piece. `run` writes
`<name>.pdf` and `preview/page-NN.png` in the output directory.

## Judging the result

`verify` counts the PDF's pages and passes only a drawing with at least one
page. `preview` writes the core document shape `{preview, kind, summary,
page_count, pages}` beside the PDF. A person then opens the PDF: a missing
view, a dimension off the geometry or an empty sheet is caught by eye.

## Pitfalls

- FreeCAD is never installed: point `facet config set freecad.path` at 1.1.4
  or newer, or set `FREECAD_EXE`; a missing host is `machine_cannot`.
- `freecadcmd` exits 0 when a script raises: the runner's wrapper reports the
  traceback and a non-zero exit, so a failed drawing never looks like a pass;
  the invocation, sys.argv and the lookup order are in references/wrapper.md.
- The script receives an output prefix without extension, not a file name:
  write `<prefix>.pdf` yourself.
