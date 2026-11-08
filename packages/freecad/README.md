# freecad

Workshop drawings from your own 3D parts: `facet run freecad.plano
<piece>.toml` runs a FreeCAD script headless on the part and gives back
`<guion>.pdf` plus one PNG per page. It belongs to the **`cad`** facet and
writes the **`document`** kind, so a person opens the PDF and an agent reads
the pages from the preview file.

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

`freecad.plano` runs the guion as `<guion> <out_dir>/<name> <pieza>`, the
lab's output-prefix convention: the script must write `<name>.pdf` beside it.
The runner then rasterizes the pages with poppler's `pdftoppm` into
`preview/page-NN.png` and writes `<name>.pdf.preview.json` in the core
document shape `{preview, kind, summary, page_count, pages}` — no new schema
or viewer. The verbs run inside the host application, so a Windows FreeCAD
cannot see WSL's poppler-utils: there the tools are called back through
`wsl.exe` with the paths translated (`\\wsl.localhost\…` and `C:\…` both
round-trip).

## A piece

```toml
[inputs]
guion = "plano-escuadra.py"
pieza = "escuadra.step"
```

`guion` is a FreeCAD script that opens `pieza`, builds the TechDraw page and
writes the PDF; `pieza` is the STEP or FreeCAD document it opens. Both are
resolved relative to the piece.

## When to use it

- **TechDraw drawings**: views, dimensions and a paginated PDF from the 3D
  model.
- **Assemblies**: constraints between parts that CadQuery's `Assembly` does
  not express.
- **FEM**: a study on a part.
- **By hand**: open the model in the FreeCAD GUI and finish it yourself.

If the deliverable is a solid, an STL or a DXF, use `cad` instead. If it is a
photo or a tour, use `blender`.
