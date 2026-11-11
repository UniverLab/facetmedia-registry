# blender

Daylight architectural photos of your own CAD: `facet run blender.photo
<piece>.toml` takes the glTF that CadQuery's `Assembly` exported and gives back
`<model>-photo.png` at 1600x1000 — the lab's study renders in about 11 s on the
GPU. It belongs to the **`image`** facet and writes the **`image`** kind, so the
photo shows through the image viewer.

This package wraps **headless Blender** (Cycles, GPU) and drives its render
recipe: wrap the best tool, never reimplement it.

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

The runner is Blender's script, so `blender.photo` and `doctor` use `bpy`
directly and need Blender; `blender.assets` needs none — it is standard-library
Python and `urllib` — and `verify` and `preview` answer under plain Python too.

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
  `cad.solid` script → `Assembly.export(...glb)` → `blender.photo`.
- **One element per piece, named.** `Assembly.export` writes one glTF node per
  added element with the name it was added under; that name is what the runner
  matches its materials against.
- **The model is in millimetres, Y-up.** CadQuery models in mm; the runner
  scales each top-level piece by `0.001` so Blender works in metres. A model
  exported in metres comes out a thousand times too small. The glTF root also
  arrives turned -90° about X, and every piece inherits that turn: before any
  material goes on, the runner clears each piece's parent (keeping its world
  transform) and bakes its rotation and scale into its mesh, so a piece's own
  normals are its world normals and a box-projected texture lands on its face
  instead of smearing into streaks. Piece names never change, so the prefixes
  still match.

## Materials by name prefix

Each mesh takes the material whose name is a **prefix** of the mesh's own
name, case-insensitively: `muros` dresses `muros`, `vidrio-1` and `vidrio-2`
are glass. The lab's set (`MATERIALS` in `escena.py`) is colour, roughness and
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
| `pavimento` | neutral grey | 0.90 | — |

**A piece left without a prefix fails the run loudly**: the runner raises
`RuntimeError("piezas sin material: [...])` naming every undressed piece, and
nothing is rendered half-dressed. Add the prefix (or rename the piece) rather
than letting Blender's default grey stand in.

## People for scale

`blender.photo` and `blender.tour` can stand **generated people** in the
scene, which is what gives the model its scale: a door, a bed or a table only
reads as its real size next to a person.

The people are **built once, outside this package**: a `people.blend` made
with MPFB 2.0.18, the MakeHuman CC0 asset pack and traits 0-1 — one collection
per person, arms lowered 40 degrees, the skeleton root at the collection's
base. This package never generates people, never needs the MPFB add-on and
never downloads an asset pack: loading a linked collection needs no add-on.

```toml
[inputs]
model = "estudio.glb"
people-blend = "people.blend"          # resolved relative to the piece
people = [
  { name = "luis", x = 3.0,  y = 2.6,  rotation = 90 },
  { name = "ana",  x = 4.5,  y = 3.85, rotation = 180 },
  { name = "sara", x = 1.45, y = -1.3, rotation = 180 },
]
```

- `people-blend` is the prebuilt collection `.blend`, resolved relative to
  the piece file. The core resolves it **before the runner starts**, so a
  missing file is refused with the path's `not_found` wording instead of a
  failed render.
- `people` is one item per person: `name` is the collection's name in the
  blend, `x` and `y` are metres in the scene's own axes, and `rotation` is a turn
  about Z in degrees from the **-y facing** the collections have by default.
  The triple above is the reference example, never a default:
  without `people` nobody stands in the scene.
- Each collection is loaded with `bpy.data.libraries.load`, linked into the
  scene, and its **single parentless root** is stood at `(x, y, floor_z)`.
  `floor_z` is the floor plane's own level, the lowest mesh minus one
  millimetre, so people stand on the ground the sun casts its shadow on.
- People arrive in metres and are **never scaled or turned with the model**.
  They load **after** the materials are dressed, so their own MPFB skin and
  clothing materials are never checked against the prefix set and never
  cleared.
- A `name` the blend does not hold fails the run with
  `<name> is not a collection in <blend> (has: [...])`; a collection without
  exactly one root fails with `<name>: expected one root object, found <n>`.
  Both reach the caller as `runner_failed`. Nobody is silently dropped.

## Cars for scale

The same two capabilities can **park cars** in the scene, which is what gives
the model its urban scale: a study reads as a street scene only next to
vehicles.

The cars are **built once, outside this package**: a `cars.blend` made from
the Quaternius Cars Pack (CC0) — one collection per car, hung from an anchor
`EMPTY` at the car's base centre, every car facing **-y**. This package never
generates cars, never checks for a pack and never downloads one: loading a
linked collection needs no add-on.

```toml
[inputs]
model = "estudio.glb"
cars-blend = "cars.blend"            # resolved relative to the piece
cars = [
  { name = "sedan",      x = -2.7, y = 0.8 },
  { name = "camioneta",  x = -5.1, y = 0.8 },
  { name = "compacto",   x = 1.0,  y = -2.0, rotation = 90 },
]
```

- `cars-blend` is the prebuilt car-collection `.blend`, resolved relative to
  the piece file. The core resolves it **before the runner starts**, so a
  missing file is refused with the path's `not_found` wording instead of a
  failed render.
- `cars` is one item per car: `name` is the collection's name in the blend,
  `x` and `y` are metres in the scene's own axes, and `rotation` is a turn about Z
  in degrees from the **-y facing** the collections have by default. The
  placements above — sedan and camioneta on the car-entry pavement by the left
  wall, plus a turned compacto — are the reference example, never a default:
  without `cars` no car parks.
- Each collection is loaded with `bpy.data.libraries.load` after the materials
  are dressed — the pack's own paint and glass materials carry no piece prefix
  — linked into the scene, and its **single parentless root** (the anchor
  `EMPTY` at the base centre) is stood at `(x, y, floor_z)`, `floor_z` being
  the floor plane's level, the lowest mesh minus one millimetre. Cars arrive in
  metres and are **never scaled or turned with the model**.
- The failures are the people's, verbatim: an unknown `name` raises
  `<name> is not a collection in <blend> (has: [...])` and a collection
  without exactly one root raises `<name>: expected one root object, found
  <n>`; both reach the caller as `runner_failed`.
- Cars read as scale only if they stay **about 1.5 m** from a wall or each
  other: pack a row flush against the facade and the eye reads them as
  centimetre models, which is the opposite of the point.

## Dressing the scene

Both scenes can render the **fetched Poly Haven sky, textures and plants** the
lab's render used: `sky` (one `{ id, rotation, strength }` item), `textures` (one
`{ prefix, id, size, hue, saturation, value }` item per prefix) and
`plants` (one `{ id, x, y, rotation }` item per plant). Without them the procedural
sky, the flat colours and the empty ground stay exactly as they are.

```toml
[inputs]
model = "estudio.glb"
sky = [{ id = "kloppenheim_06_puresky", rotation = 200, strength = 1.0 }]
textures = [
  { prefix = "suelo", id = "aerial_grass_rock", size = 3.0, hue = 0.5, saturation = 1.0, value = 0.9 },
]
plants = [
  { id = "shrub_02", x = 7.4, y = 2.25, rotation = 90 },
]
```

- The HDRI id is the last part of its polyhaven.com URL. With `sky` the scene
  has **no `sol` lamp**: the HDRI lights the render and `use_sun_shadow` pulls
  the shadows out of it.
- A texture item box-projects `diff.jpg` at `size` metres through the
  hue/saturation/value adjust; `rough.jpg` drives the roughness and a 0.15
  bump. `nor_gl.jpg` is never loaded: the models carry no UVs. Every piece
  takes its prefix's texture, the model's own walls and slabs (`muros`, `piso`)
  as well as the ground plane. `prefix` values are the piece names in your own
  CAD model, so they keep that model's spelling (the example names are its
  content, not this package's vocabulary). A prefix without an item keeps its
  flat colour, and two items with the same `prefix` fail the run with
  `textures: prefix repeated: <prefix>`.
- Plants stand at `(x, y, floor_z)` like people and cars, after the dressing.
  Plant models are heavy (`potted_plant_01` is about 96k polygons,
  `island_tree_01` about 3.7M), so use few.
- A referenced id must already be fetched: a missing folder or file fails the
  run with `missing <id>/<file>: fetch it with blender.assets
  [[inputs.assets]] with id = "<id>" and res = "<res>"` (`2k` for a sky or
  texture, `1k` for a model). Photo and tour never download; fetch the set
  first with one `blender.assets` piece (see `## Assets` below).

## The exposure rule

The scene is lit by a sun plus a sky texture washing from the same direction —
unless `sky` dresses it, when the fetched HDRI is the light and there is no
`sol` lamp (see "Dressing the scene").
That pair over-exposes easily, so the view transform is **`AgX - Medium High
Contrast`** with **exposure -0.6**, which keeps the sun and the sky wash from
washing the colours out. Brighten a dark photo by moving the sun or lowering
the exposure, not by raising it: at -0.6 the render already carries the lab's
daylight, and a positive exposure clips the walls to white.

Cycles runs on the GPU (`compute_device_type` OPTIX, falling back to CUDA,
then CPU) at **128 samples with denoise**, the recipe the lab measured at about
8-10 s per 1600x1000 frame.

## Piece fields

What `facet describe blender.photo --json` reports for this manifest:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `model` | path | yes | — | the `.glb` from CadQuery's `Assembly`, relative to the piece file |
| `camera` | array | no | the lab's axonometric view | one item: `{ azimuth = -40, elevation = 48, scale }` (degrees for the two angles; `scale` is the orthographic scale in metres, and when omitted it is fitted to the whole model with a 10% margin) |
| `rotation` | number | no | `0` | turn of the whole model about Z in degrees; the sun stays put |
| `exposure` | number | no | `-0.6` | stops under `AgX - Medium High Contrast` |
| `people-blend` | path | no | — | the prebuilt MPFB collection `.blend`, relative to the piece file |
| `people` | array | no | `[]` | one item per person: `{ name, x, y, rotation = 0 }` (metres, degrees about Z) |
| `cars-blend` | path | no | — | the prebuilt car-collection `.blend`, relative to the piece file |
| `cars` | array | no | `[]` | one item per car: `{ name, x, y, rotation = 0 }` (metres, degrees about Z) |
| `sky` | array | no | `[]` — the procedural sky and `sol` lamp stay | one item: `{ id, rotation = 200, strength = 1.0 }` — the fetched Poly Haven HDRI, which then replaces the lamp |
| `textures` | array | no | `[]` | one item per dressed prefix: `{ prefix, id, size = 2.0, hue = 0.5, saturation = 1.0, value = 1.0 }` |
| `plants` | array | no | `[]` | one item per plant: `{ id, x, y, rotation = 0 }` (metres, degrees about Z) |

`blender.tour` takes the same `people-blend`, `people`, `cars-blend`,
`cars`, `sky`, `textures` and `plants` fields; the rest of its row set is
in "Camera tours".

## Product photos

`facet run blender.product <piece>.toml` photographs one CAD part the way a
catalogue does: the **STL** that `cad.solid` writes beside the piece is
imported, scaled from millimetres to metres, dressed in a metal and shot on
Cycles at **1200x1200** under two studio area lights against a dark backdrop.
The approved reference is a brushed-aluminium product photo (about 10 s).

```toml
[inputs]
part = "escuadra.stl"
material = "brushed-aluminum"  # or "steel"
backdrop = "graphite"             # or "concrete"
exposure = -0.2                  # stops: darker when the metal burns
fill = 0.6                       # frame height the part spans: higher when it is small
light = 1.0                      # multiplies the light plan: higher when it is flat
```

- `part` is the `.stl` `cad.solid` exports beside the piece (60 x 40 x 10 mm
  for the reference bracket), resolved relative to the piece file. The runner
  measures its bounding box after the import, so nothing about the part's size
  is assumed.
- `material` is `brushed-aluminum` (brushed aluminium: metallic 1, roughness
  0.38) or `steel` (steel: metallic 1, roughness 0.22). An unknown name fails
  the run loudly (`material desconocido`), so a part is never left in Blender's
  default grey.
- `backdrop` is `graphite` (near black) or `concrete` (dark grey). Both stay dark
  on purpose: metal needs contrast to read as metal, and a light cyclorama
  flattens the highlight the photo exists for.
- `exposure` is -3 to 3 stops, **-0.2** by default: lower it when the shot comes
  out too bright or burnt, raise it when it is too dark.
- `fill` is 0.2 to 0.95, **0.6** by default: the fraction of the frame's height
  the part's bounding sphere spans. Raise it when the part looks too small,
  lower it when the frame crops it.
- `light` is 0.1 to 10, **1.0** by default: a multiplier on the energy the
  light plan derives from the part's span. Raise it when the shot is flat,
  lower it when the highlights are harsh. The lights' distance does not move.

**The light rule.** A fixed studio light burns a small piece out, so the two
area lights are derived from the part's longest side. A 6 cm piece gets
**4 W lights 0.50 m away**; the energy scales with the part and is clamped to
**2-6 W**, the distance to **0.15-2 m**. `light` multiplies that energy and
leaves the distance alone. The keys sit at azimuth -35°/elevation 55° and
azimuth 145°/elevation 25° around the part's centre, and each square light's
size is its own distance, which keeps the highlight soft.

The exposure is **-0.2** under `AgX - Medium High Contrast` on Cycles
(OPTIX, then CUDA, then CPU) at 128 samples with denoise: darker than the
daylight photo because the studio's lights sit close to the part. The camera is
a 50 mm perspective view three-quarters on, its distance computed from `fill`,
the part's bounding radius (half the diagonal of its box) and the lens's
vertical field of view on a 36 mm sensor: `distance = radius / (fill x 0.36)`.
The 6 cm bracket sits at about 0.17 m, and the clip start stays under the
part's nearest point, so a small part is never clipped.

One `blender.product` run writes `<part>-product.png` (`image/png`) at
1200x1200 with properties `width`, `height`, `samples`, `exposure`, `fill`,
`light`, `material` and `backdrop`; the `part` is the hashed input. `verify`
measures the header against 1200x1200 and `preview` writes the image kind's
file with the material, the backdrop and the part in its prompt.

## Assets

One `blender.photo` run writes one asset:

- `<model>-photo.png` (`image/png`) at 1600x1000, `kind = "image"`, the `model`
  as the hashed input, and properties `width`, `height`, `samples`,
  `exposure` and `rotation`.

`tool` is `{"name": "blender", "version": "5.2.2 LTS"}` — the build that
actually rendered.

`blender.assets` is the second capability (kind `text`, generic preview): a
piece gives a required `name` — the receipt is `<name>.assets.json` — and lists
Poly Haven asset ids — skies, textures and models, all CC0 — with an optional
pinned `res` (`1k`, `2k`, `4k`; the lab defaults are 2k for skies and textures,
1k for models). The runner fetches the list **once** into the
shared models dir, `<home>/models/blender/polyhaven/<id>/`, with the exact
mechanism in `polyhaven.py`: the type comes
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

## Camera tours

`facet run blender.tour <piece>.toml` moves a camera through the same
daylight scene the photo uses and writes `<model>-tour.mp4`
(1280x720, 24 fps, 10 s by default). The camera starts at the piece's start
triple and glides to its end triple with a smoothstep, `t*t*(3-2*t)`: it leaves
and arrives gently, like a crane, instead of starting and stopping dead.

```toml
[inputs]
model = "estudio.glb"
azimuth = [{ start = -75, end = -15 }]    # degrees
elevation = [{ start = 55, end = 40 }]   # degrees above the floor
distance = [{ start = 14.0, end = 10.5 }]  # metres from the model's centre
focal = 30                                # millimetres
seconds = 10
fps = 24
seed = 0
```

**Eevee, never Cycles.** A tour is 240 frames. Cycles renders that in about
45 minutes; Eevee does the same 240 frames at 1280x720 in **about 100 s**, and
the quality holds because the scene is static and only the camera moves. Cycles
stays the still-photo engine, where every frame is looked at.

The recipe is fixed, and it is the lab's:
`scene.render.engine = "BLENDER_EEVEE"`, `taa_render_samples = 32`,
`use_raytracing` with `SCREEN`, `use_fast_gi`, `use_shadows`, exposure **-0.4**
under **`AgX - Medium High Contrast`**, 1280x720. One `location` and one
`rotation_euler` keyframe per frame is what makes Blender interpolate the move.

The clip is written by Blender itself: `media_type = "VIDEO"`,
`file_format = "FFMPEG"`, `ffmpeg.format = "MPEG4"`, `codec = "H264"`,
`constant_rate_factor = "HIGH"`, then `render(animation=True)` — no frame
sequence on disk and no second encoder.

`verify` reads the MP4's own boxes with the standard library alone (`ftyp`,
`moov/mvhd` for the timescale and duration, `avc1` for the size, `stts` for the
frame count): width 1280, height 720, the entry's `fps`, and
`seconds x fps` frames. A file that does not parse fails with the parse error
as its metric, never an exception. `preview` writes
`<clip>.mp4.preview.json` for the video viewer, with the probe's measurements
and the prompt line
`<stem> · camera tour · azimuth <start>→<end> · <frames>f @ <fps>fps`.

## Scripted scenes

`facet run blender.scene <piece>.toml` renders one PNG from the piece's own
Blender script, and `blender.animation` renders one MP4 from it. The recipes
above fix the scene; the script builds it — a plane, three primitives, two
lights and a camera in `examples/scene/build.py`, keyframed over frames
1..120 so the same file stills and animates:

```toml
[inputs]
script = "build.py"
name = "estudio-script"
```

The contract the runner enforces, in order:

- It starts from `bpy.ops.wm.read_factory_settings(use_empty=True)` and
  executes the script with `runpy.run_path`, with the script's own directory
  as the working directory. The script's globals carry `FACET_ASSETS` (the
  Poly Haven root `blender.assets` fills) and `FACET_PIECE_DIR` (the script's
  directory), so skies and textures arrive through `blender.assets`, never a
  download inside the script. Paths go through the host conversion the other
  capabilities use, so a Windows host Blender opens them.
- The script must set `scene.camera`. A run without one fails loudly, and so
  does a script that raises: the message names the script, the exception type
  and the last traceback lines.
- After the script, the runner applies facet's output settings, overriding
  whatever the script set: the resolution at 100 %, the engine and its
  samples (Cycles on the GPU through the runner's helper, then its samples
  and seed; Eevee with TAA render samples), the seed, and the exposure. An
  animation also gets the frame range 1..`frames`, the `fps`, and the tour's
  MP4 block (FFMPEG/MPEG4/H264, `HIGH`, no file extension), then the output
  path. Everything else stays the script's: the world, the lights, the
  materials, the colour-management look and view transform, the keyframes.
- A still whose luminance is flat fails the run as a uniform image — check
  the camera's framing and the lights — and the run records its mean and
  standard deviation. facet verifies only the file: the PNG's size, or the
  MP4's width, height, frames and fps. Aesthetics are the agent's, never the
  verifier's.

The script runs **unsandboxed with the person's permissions**, like any code
the agent writes: it can read and write what the person can, so review it
like a shell command, not like a prompt.

## Verification and doctor

`verify` measures the PNG header (the IHDR, which needs no third-party module
inside Blender): the file must parse as a PNG and measure exactly 1600x1000 for
`blender.photo`, or 1200x1200 for `blender.product`. The metrics carry `width`
and `height`; a file that is not a PNG carries `error` and fails. For
`blender.tour` it probes the MP4's boxes instead, carrying `width`,
`height`, `frames` and `fps`. `blender.scene` verifies the PNG against the
piece's own width and height, and `blender.animation` probes the MP4 against
the piece's own width, height, frames and fps — the file, never the look.

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
`estudio-photo.png` came from):

```toml
[inputs]
model = "estudio.glb"
```

Run it with `scripts/try-package.sh blender photo packages/blender/examples/estudio.toml`.
The record lands beside the photo as `estudio-photo.png.facet.json`.
