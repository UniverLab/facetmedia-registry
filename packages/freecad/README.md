# freecad

Workshop drawings from your own 3D parts: `facet run freecad.drawing
<piece>.toml` runs a FreeCAD script headless on the part and gives back
`<script>.pdf` plus its SVG sheets. It belongs to the **`cad`** facet and
writes the **`document`** kind, so a person opens the PDF and an agent reads
the pages from the preview file. The script draws SVG sheets; the runner
turns them into the PDF with FreeCAD's own Qt and returns the sheets as
assets, so nothing is ever installed on the host.

This is the lab's rule to wrap the best tool and never reimplement it: the
package drives the **FreeCAD you already have**, for what CadQuery does not
do — TechDraw drawings, assemblies with constraints, FEM, or a part opened by
hand. The CAD itself stays in the `cad` package.

## The host contract

FreeCAD cannot be isolated, so the package declares the core's `host-app`
engine and facet drives the FreeCAD **you already have**:

```toml
[engine]
type = "host-app"

[engine.host_app]
app = "freecad"
min_version = "1.1.4"
config_key = "freecad.path"
env = "FREECAD_EXE"
```

- The binary is looked up in this order: `freecad.path` in `<home>/config.toml`
  (written by `facet config set freecad.path /path/to/freecad`), then
  `FREECAD_EXE`, then `freecadcmd` or `freecad` on `PATH`. Windows paths are
  fine: `facet config set freecad.path "/mnt/c/Program Files/FreeCAD 1.1/bin/freecadcmd.exe"`.
- `facet pull freecad` downloads nothing and builds no environment. It
  resolves the binary, probes `freecadcmd --version` and compares the first
  dotted version against `1.1.4`.
- A missing or too-old FreeCAD is `machine_cannot`, because no pull changes
  it: the message names every location tried (or the version found) and the
  fix is exactly `facet config set freecad.path /path/to/freecad`.
  **Nothing is ever installed on the host.**

## The wrapper

`freecadcmd` exits 0 and prints nothing when a script raises. The package
ships the lab's `tools/freecad_run.py` as `freecad_run.py`: it runs the target
with `runpy`, prints the traceback and exits 1 on failure. The runner also
converts every slash-bearing argument with `wslpath -w` when the binary is a
`.exe`, keeps bare names unchanged, and retries once only on a WSL interop
failure (`UtilAcceptVsock`). A real script failure surfaces as
`runner_failed` with the tail of the output.

`freecad.drawing` runs the script as `<script> <out_dir>/<name> <part>`, the
lab's output-prefix convention: the script must write its sheets as
`<name>-01.svg`, `<name>-02.svg`, … beside it — consecutive two-digit numbers
from 01, each sheet carrying `width` and `height` in millimetres on its
`<svg>` tag (see `examples/plano-escuadra.py`). The runner then renders the
sheets with FreeCAD's bundled Qt (`QSvgRenderer` into `QPdfWriter` at
300 dpi) and returns `<name>.pdf` plus one image asset per sheet, so the
sheets stay beside the PDF as editable sources. `facet preview <name>.pdf`
renders the page PNGs from those sheets into `preview/page-NN.png` at
150 dpi and writes `<name>.pdf.preview.json` in the core document shape
`{preview, kind, summary, page_count, pages}` — no new schema or viewer.

## A piece

```toml
[inputs]
script = "plano-escuadra.py"
part = "escuadra.step"
```

`script` is a FreeCAD script that opens `part`, builds the TechDraw views
with `TechDraw.projectToSVG` and writes one SVG sheet per page;
`examples/plano-escuadra.py` draws the `escuadra.step` bracket on one A3
landscape sheet and is the model to copy. `part` is the STEP or FreeCAD
document it opens. Both are resolved relative to the piece.

## When to use it

- **TechDraw drawings**: views, dimensions and a paginated PDF from the 3D
  model.
- **Assemblies**: constraints between parts that CadQuery's `Assembly` does
  not express.
- **FEM**: a study on a part.
- **By hand**: open the model in the FreeCAD GUI and finish it yourself.

If the deliverable is a solid, an STL or a DXF, use `cad` instead. If it is a
photo or a tour, use `blender`.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `freecad.drawing` — `examples/plano.toml`: `facet example freecad.drawing --run`

Needs a person-installed FreeCAD and `freecadcmd`.
