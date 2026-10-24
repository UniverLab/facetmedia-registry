# cad

3D parts and 2D plans from scripts you write yourself: `facet run cad.solid
<script.py>` runs a CadQuery script unchanged inside the package environment
and gives back `<name>.step`, `<name>.stl` and `<name>.svg`; `facet run
cad.drawing <script.py>` runs an ezdxf script and gives back `<name>.dxf`,
`<name>.svg` and `<name>.png`. The part is checked by its volume and bounding
box against what the piece expects; the plan is checked by a clean DXF audit
and its layers. It belongs to the **`cad`** facet and writes the **`cad`**
kind, so both show through the CAD viewer. CPU only: no GPU is ever touched.

The input is the script itself, because everything is script and versionable.
This is the lab's rule to wrap the best tool and never reimplement it: this
package wraps CadQuery (3D) and ezdxf (2D) — the two tools the lab adopted
after archiving cadSpec — and runs the exact script the lab already wrote.

The script runs with the caller's rights, exactly as `uv run` would: it is
the caller's code, chosen by the caller. facet does not sandbox it further.

## Piece fields

The fields below are what `facet describe cad.solid --json` and `facet
describe cad.drawing --json` report for this manifest.

`cad.solid` — 3D part from a CadQuery script: STEP, STL and a line view:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `script` | path | yes | — | CadQuery script; must write `<name>.step`, may write `.stl` and `.svg` |
| `name` | string | yes | — | matches `[a-z0-9][a-z0-9-]*`; the asset base name |
| `expect-volume-mm3` | number | no | — | expected volume; verify fails outside `volume-rel-tol` |
| `volume-rel-tol` | number | no | `0.001` | relative tolerance on the volume, 0 to 0.1 |
| `expect-bbox-mm` | array | no | — | expected bounding box `[x, y, z]` in mm, each a number |
| `bbox-abs-tol-mm` | number | no | `0.01` | absolute tolerance per side, in mm |

`cad.drawing` — 2D plan from an ezdxf script: DXF with an audit, SVG and PNG
views:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `script` | path | yes | — | ezdxf script; must write `<name>.dxf`, may write `.svg` and `.png` |
| `name` | string | yes | — | matches `[a-z0-9][a-z0-9-]*`; the asset base name |
| `expect-layers` | array | no | — | layers the DXF must define; each item is `{ layer = "..." }` |

The core's field names never carry an underscore (`manifest._NAME_RE`), so
the piece spells the expectations `expect-volume-mm3`, `expect-bbox-mm` and
`expect-layers`, exactly as Whisper spells `expect-text`.

## Script contract

The lab's existing convention, which both example scripts already follow:

- The script is run as `<env python> -I <script> <out_dir>/<name>`, with its
  own directory as the working directory. It writes its files to that stem
  plus an extension: `sys.argv[1]` is the stem, and `Path(sys.argv[1]
  ).with_suffix(".step")` is the file.
- For `cad.solid` it must write `<name>.step` and may write `<name>.stl` and
  `<name>.svg`. For `cad.drawing` it must write `<name>.dxf` and may write
  `<name>.svg` and `<name>.png`.
- Whatever the script leaves out, the runner completes: a missing STL is
  exported from the STEP (`tolerance=0.05`, `angularTolerance=0.2`), a
  missing SVG is projected (`projectionDir (1.2, -1, 0.8)`, hidden lines
  off, 600×450), a missing SVG or PNG view of a DXF is rendered on white.
- A script run that exits non-zero, or a required file that is missing, is a
  runner error carrying the script's stderr tail. The script's own `print`
  output goes to the log.
- Parameters are not passed into the script: the script is the source of
  truth. To change the part, change the script.

The script runs with the caller's rights, exactly as `uv run` would. facet
does not sandbox it further.

## Assets

One `cad.solid` run writes three assets, each with the same record data
(`kind = "cad"`, `inputs = [script]`, so the script's hash enters the
record; `seed = null`):

- `<name>.step` (`model/step`) — the part. Its properties are `volume_mm3`,
  `bbox_mm` (`[x, y, z]` in mm), `faces` and `solids`.
- `<name>.stl` (`model/stl`) — the print mesh, written by the script or by
  the runner at the lab's tolerances.
- `<name>.svg` (`image/svg+xml`) — the line view.

One `cad.drawing` run writes `<name>.dxf` (`image/vnd.dxf`), `<name>.svg`
and `<name>.png` (`image/png`), sharing the DXF's properties: `entities`,
`layers` (the defined layer names) and `units`.

`tool` is `{"name": "cadquery", "version": "2.8.0"}` for a part and
`{"name": "ezdxf", "version": "1.4.4"}` for a plan — the kernel that
actually ran, pinned by the manifest and the lock.

## Verification and doctor

`verify` re-imports the assets; nothing is trusted from the run:

- **STEP**: `isValid()` is true, there is at least one solid, and when the
  piece carries `expect-volume-mm3` the volume is within `volume-rel-tol`
  (relative) and when it carries `expect-bbox-mm` every side is within
  `bbox-abs-tol-mm` (absolute). The metrics carry `volume_mm3`, `bbox_mm`,
  `faces`, `solids` and, when expected, `volume_diff_rel` and
  `bbox_diff_mm`.
- **STL and SVG**: non-empty and parseable — the STL meshes to at least one
  triangle, the SVG parses as XML.
- **DXF**: `ezdxf.readfile`, then `audit()` with 0 errors and 0 fixes, and
  every `expect-layers` layer present. The metrics carry `entities`,
  `layers`, `errors`, `fixes` and `missing_layers`.
- **PNG**: opens with matplotlib's image reader.

The verification belongs to the STEP or the DXF asset; the derived views
pass when they parse.

`facet preview <name>.step` writes `<name>.step.preview.json` (the `cad`
schema) with `solid` — `valid`, `volume_mm3`, `bbox_mm`, `faces`, `solids`
and `holes` (every full-revolution cylindrical face with its centre,
diameter and axis, deduplicated; a fillet is a partial cylinder and is not a
hole) — and a shaded isometric `views` entry (`<name>.view.png`, 1200×900,
Lambert-shaded, returned to the agent as an image because the shape is
judged visually). `facet preview <name>.dxf` writes `drawing` — `units`,
`entities`, `layers` with entity counts and the `audit` result — and shows
the PNG plan view. A summary reads like
`escuadra · valid · 20 806 mm³ · 2 holes Ø6.5`.

`facet doctor cad` runs the package's own checks, each `{name, ok, detail,
fix}`:

- `cadquery` (quick): CadQuery and its OCP kernel import, with versions; on
  an `ImportError` naming a shared object the fix is the manifest's
  `host_hint`.
- `ezdxf` (quick): imports, with its version.
- `matplotlib` (quick): imports with the Agg backend.
- `step` (full): a 10 mm box exports to STEP in a temporary directory and
  reads back valid with one solid.
- `dxf` (full): a single line exports to DXF and reads back with one entity
  and a clean audit.

## Licences

cadquery (Apache-2.0), cadquery-ocp (Apache-2.0), the OpenCASCADE kernel
inside cadquery-ocp (LGPL-2.1-only WITH OCCT-exception-1.0), ezdxf (MIT)
and matplotlib (PSF-2.0). No models: the input is a script, and the output
is the caller's own geometry — the tool chain does not license it.

## Host libraries

The OCP and VTK extension modules link against the host's GL and X stack
(confirmed with `ldd` on the loaded modules): `libGL.so.1`, `libGLX.so.0`,
`libGLdispatch.so.0`, `libX11.so.6`, `libXau.so.6`, `libXdmcp.so.6` and
`libxcb.so.1`. They live in `requirements.host_libs` in the manifest; a
machine missing one sees it in `facet doctor cad` with the fix
`sudo apt install libgl1 libx11-6` (`host_hint`).

## Machine cost

`requirements` in the manifest: **no GPU**, **2 GB RAM**, **1.5 GB disk**,
`exclusive = false` — two parts can be modelled at once — on `linux`. The
first `facet pull cad` downloads about 560 MB (the wheels: cadquery-ocp and
VTK are the bulk); unpacked the environment is about 5 GB, because OCP and
VTK ship every extension module. Later runs are offline.

## Example

`examples/escuadra.py` and `examples/escuadra.toml`: the lab's escuadra de
montaje (L bracket, CadQuery 2.8.0), verified by its volume:

```toml
[inputs]
script = "escuadra.py"
name = "escuadra"
expect-volume-mm3 = 20805
```

`examples/plano-estudio.py` and `examples/plano-estudio.toml`: the lab's
6 × 4.5 m study plan (ezdxf 1.4.4 + matplotlib), verified by its five layers
and a clean audit:

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

Run them with `scripts/try-package.sh cad solid
packages/cad/examples/escuadra.toml` and `scripts/try-package.sh cad drawing
packages/cad/examples/plano-estudio.toml`; the script prints the run, the
preview, the doctor report and the skill. The records land beside the assets
as `escuadra.step.facet.json` and its siblings.

The lab's runs (24 October 2026, 12 cores, no GPU): `facet run cad.solid`
took 6.1 s and `facet run cad.drawing` 3.2 s with the environment already
pulled; the escuadra measured 20 805.5
mm³ — 0.0025 % off the piece's 20 805, far inside the 0.1 % tolerance — and
its two Ø6.5 holes sit at (45, 20, 2.5) and (2.5, 20, 35), exactly the
hand-checked centres. A variant with `expect-volume-mm3 = 30000` exits 3
with `volume_diff_rel = 0.306`; a script that raises exits 9 with
`runner_failed` carrying its message. The STEP record reads (abridged: the
file also carries the bytes, creation time, licence section, registry
provenance, params digest and the other two assets' records):

```json
{"id": "sha256:1480c0c3e727fc2c32ba6ddc9267b6d95a44caac1419f019ab8358ad5f13fb86", "kind": "cad", "mime": "model/step", "name": "escuadra", "path": "escuadra.step", "properties": {"bbox_mm": [60.0, 40.0, 50.0], "faces": 11, "solids": 1, "volume_mm3": 20805.514451}, "provenance": {"capability": "cad.solid", "inputs": [{"id": "sha256:bd1acd2f9c9e97e183bb641796c8ce043fc05bee16346c381181c0e217768223"}], "models": [], "package": {"lock_sha256": "377db64843a34f8583109bcd5c2046dbaf1d9780b853bdd1e0a6b457a50786a8", "name": "cad", "version": "0.1.0"}, "params": {"bbox-abs-tol-mm": 0.01, "expect-volume-mm3": 20805, "name": "escuadra", "volume-rel-tol": 0.001}, "seed": null, "tool": {"name": "cadquery", "version": "2.8.0"}}, "record": 1, "verification": {"metrics": {"bbox_mm": [60.0, 40.0, 50.0], "faces": 11, "holes": [{"axis": [1.0, 0.0, 0.0], "center_mm": [2.5, 20.0, 35.0], "diameter_mm": 6.5}, {"axis": [0.0, 0.0, 1.0], "center_mm": [45.0, 20.0, 2.5], "diameter_mm": 6.5}], "solids": 1, "volume_diff_rel": 2.5e-05, "volume_mm3": 20805.514451}, "status": "passed", "thresholds": {"bbox_abs_tol_mm": null, "volume_rel_tol": 0.001}, "verifier": "cadquery"}}
```

The plan: 22 entities, 7 defined layers, audit 0 errors 0
fixes, every `expect-layers` layer present, and its PNG and SVG views
completed by the runner. `facet preview` summarises the part as
`escuadra · valid · 20 806 mm³ · 2 holes Ø6.5` and the plan as
`plano-estudio · 22 entities · 5 layers · audit clean`; both previews pass
`schemas/preview/cad.schema.json` and open in the CAD viewer.
`facet doctor cad --json` reports `healthy: true` after the pull (5 package
checks at `full` depth, the `host_libs` readiness check loading all seven
declared sonames included), and `facet skill cad` prints the skill with this
machine's state.
