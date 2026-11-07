# blender

Daylight architectural photos of your own CAD: `facet run blender.foto
<piece>.toml` takes the glTF that CadQuery's `Assembly` exported and gives back
`<model>-foto.png` at 1600x1000 — the lab's study renders in about 11 s on the
GPU. It belongs to the **`image`** facet and writes the **`image`** kind, so the
photo shows through the image viewer.

This is the lab's rule to wrap the best tool and never reimplement it: the
package wraps **headless Blender** (Cycles, GPU) and drives the render recipe
the lab already approved in `projects/prueba-render-arq/estudio.py`.

## The host contract

Blender cannot be isolated, so the package declares the core's `host-app`
engine and facet drives the Blender **you already have**:

```toml
[engine]
type = "host-app"

[engine.host_app]
app = "blender"
min_version = "5.2"
config_key = "blender.path"
env = "BLENDER_EXE"
```

- The binary is looked up in this order: `blender.path` in `<home>/config.toml`
  (written by `facet config set blender.path /path/to/blender`), then
  `BLENDER_EXE`, then `blender` on `PATH`. Windows paths are fine:
  `facet config set blender.path "/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"`.
- `facet pull blender` downloads nothing and builds no environment. It
  resolves the binary, probes `blender --version` and compares the first dotted
  version against `5.2`. `5.2` is a two-component minimum, so `5.2.2 LTS`
  passes (the installed build the lab's `docs/software-dedicado.md` records).
- A missing or too-old Blender is `machine_cannot`, because no pull changes it:
  the message names every location tried (or the version found) and the fix is
  exactly `facet config set blender.path /path/to/blender`. **Nothing is ever
  installed on the host.**
- facet runs `blender -b --factory-startup --python-exit-code 1 --python
  runner.py -- <verb> --input <request> --result <result>`: headless, a factory
  scene, and — the flag the lab's `tools/blender.sh` insists on — an exit code
  of 1 when the script raises, so a failed scene never looks like a pass. When
  the resolved binary is a `.exe` under WSL, facet converts every path
  argument through `wslpath -w`.

The runner is Blender's script, so it uses `bpy` directly. The `run` and
`doctor` verbs need Blender; `verify` and `preview` read the PNG header alone
and answer under plain Python too.

## The glTF route

The input is the **glTF** `.glb` from a CadQuery `Assembly`, never STEP:

```python
import cadquery as cq

estudio = cq.Assembly(name="estudio")
estudio.add(piso, name="piso")
estudio.add(muros, name="muros")
estudio.export("estudio.glb")  # glTF binary: one element per piece, with its name
```

- **Never STEP.** Blender does not open STEP without an extra plugin, and a
  glTF carries the piece names the materials need. This is why the route is
  `cad.solid` script → `Assembly.export(...glb)` → `blender.foto`.
- **One element per piece, named.** `Assembly.export` writes one glTF node per
  added element with the name it was added under; that name is what the runner
  matches its materials against.
- **The model is in millimetres, Y-up.** CadQuery models in mm; the runner
  scales each top-level piece by `0.001` so Blender works in metres. A model
  exported in metres comes out a thousand times too small.

## Materials by name prefix

Each mesh takes the material whose name is a **prefix** of the mesh's own
name, case-insensitively: `muros` dresses `muros`, `vidrio-1` and `vidrio-2`
are glass. The lab's set (`MATERIALS` in `runner.py`) is colour, roughness and
transmission per prefix:

| Prefix | Colour | Roughness | Transmission |
|--------|--------|-----------|--------------|
| `muros` | warm off-white | 0.90 | — |
| `piso` | walnut | 0.45 | — |
| `vidrio` | pale blue | 0.02 | 1.0 (IOR 1.45) |
| `cama` | slate blue | 0.85 | — |
| `almohada` | near white | 0.80 | — |
| `mesa` | dark oak | 0.40 | — |
| `sillas` | orange | 0.55 | — |
| `suelo` | pale grey | 0.95 | — |

**A piece left without a prefix fails the run loudly**: the runner raises
`RuntimeError("piezas sin material: [...])` naming every undressed piece, and
nothing is rendered half-dressed. Add the prefix (or rename the piece) rather
than letting Blender's default grey stand in.

## The exposure rule

The scene is lit by a sun plus a sky texture washing from the same direction.
That pair over-exposes easily, so the view transform is **`AgX - Medium High
Contrast`** with **exposure -0.6**, which keeps the sun and the sky wash from
washing the colours out. Brighten a dark photo by moving the sun or lowering
the exposure, not by raising it: at -0.6 the render already carries the lab's
daylight, and a positive exposure clips the walls to white.

Cycles runs on the GPU (`compute_device_type` OPTIX, falling back to CUDA,
then CPU) at **128 samples with denoise**, the recipe the lab measured at about
8-10 s per 1600x1000 frame.

## Piece fields

What `facet describe blender.foto --json` reports for this manifest:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `model` | path | yes | — | the `.glb` from CadQuery's `Assembly`, relative to the piece file |
| `camera` | array | no | the lab's axonometric view | one item: `{ azimut = -40, elevacion = 48, escala = 11.5 }` (degrees; orthographic scale in metres) |
| `giro` | number | no | `0` | turn of the whole model about Z in degrees; the sun stays put |
| `exposure` | number | no | `-0.6` | stops under `AgX - Medium High Contrast` |

## Assets

One `blender.foto` run writes one asset:

- `<model>-foto.png` (`image/png`) at 1600x1000, `kind = "image"`, the `model`
  as the hashed input, and properties `width`, `height`, `samples`,
  `exposure` and `giro`.

`tool` is `{"name": "blender", "version": "5.2.2 LTS"}` — the build that
actually rendered.

`blender.assets` is the second capability (kind `text`, generic preview): a
piece names Poly Haven asset ids — skies, textures and models, all CC0 — with
an optional pinned `res` (`1k`, `2k`, `4k`; the lab defaults are 2k for skies
and textures, 1k for models). The runner fetches the list **once** into the
shared models dir, `<home>/models/blender/polyhaven/<id>/`, with the lab's
exact mechanism (`polyhaven.py`, ported from the Grafics lab): the type comes
from `info/<id>`, the file records from `files/<id>`, files already present
with the right size are skipped and every download is md5-checked, and the
names are fixed — `sky.hdr`, `diff.jpg`/`nor_gl.jpg`/`rough.jpg` (the first
`col_*` colour variant for textures), `<id>.gltf` plus its includes. Models
reporting more than 4,000,000 polygons are refused with the id and count
named. The run writes one asset, `<name>.assets.json`, the receipt of ids,
file paths, bytes and md5s; `verify` re-measures every listed file on disk
and `preview` writes `<name>.assets.json.preview.json` for the generic
viewer. No manifest `[[models]]` entries: the URLs and md5s are dynamic per
file record and cannot be pinned statically, so the runner — not the core
downloader — performs the fetch.

## Verification and doctor

`verify` measures the PNG header (the IHDR, which needs no third-party module
inside Blender): the file must parse as a PNG and measure exactly 1600x1000.
The metrics carry `width` and `height`; a file that is not a PNG carries
`error` and fails.

`facet preview <name>.png` writes `<name>.png.preview.json` for the `image`
kind with `name`, `prompt` (the recipe line: model, view, turning, exposure),
`seed`, `width` and `height`, and shows the photo.

`facet doctor blender` reports the `host_app` check alone: a host-app
package's engine check *is* the application's resolution and version probe,
so Blender missing or below 5.2 fails `machine_cannot` with the
`facet config set blender.path` fix. The package's own `doctor` verb — which
facet never reaches for a host-app engine — reports the Blender-side modules
when the entry is run directly (`python runner.py doctor --input <request>
--result <result>` launches the host Blender first):

- `bpy` (quick): the running Blender's Python imports, with its version.
- `gltf` (quick): `bpy.ops.import_scene.gltf` exists, so the import route works.
- `cycles` (quick): the Cycles add-on is present, with its device type.
- `gpu` (when the request asks `depth = "full"`): Cycles lists an OptiX or
  CUDA device; without one it falls back to CPU and the recipe no longer
  meets its 11 s.

## Machine cost

`requirements` in the manifest: **GPU**, **4 GB RAM**, **0.1 GB disk**,
`exclusive = true` (a Cycles render owns the GPU) on `linux` — Blender lives
on the Windows host behind WSL. Still no environment build and Blender is
never installed; `blender.assets` is the one download — versioned CC0 assets
that arrive into the models dir and are re-verified on every fetch.

## Example

`examples/estudio.toml` renders the lab's study (`estudio.glb`, shipped beside
the piece and regenerated by `estudio.py` — the model the approved
`estudio-foto.png` came from):

```toml
[inputs]
model = "estudio.glb"
```

Run it with `scripts/try-package.sh blender foto packages/blender/examples/estudio.toml`.
The record lands beside the photo as `estudio-foto.png.facet.json`.
