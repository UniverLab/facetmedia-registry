# blender

Scenes and animations from **your own Blender script**: `facet run
blender.scene <piece>.toml` renders one PNG from a Python script you write,
and `blender.animation` renders one MP4 from the same kind of script. facet
owns only the output — the resolution, the engine and its samples, the seed,
the exposure, and for an animation the frame range and rate. The script owns
every creative choice: the world, the lights, the materials, the camera, the
keyframes.

This package wraps **headless Blender** (Cycles on the GPU, Eevee for
animation) and drives it: wrap the best tool, never reimplement it. The
`blender.assets` capability fetches the Poly Haven skies, textures and models
a script may want to light and dress the scene with.

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

The runner is Blender's script, so `run` and `doctor` use `bpy` directly and
need Blender; `blender.assets` needs none — it is standard-library Python and
`urllib` — and `verify` and `preview` answer under plain Python too.

## The script contract

facet starts from `bpy.ops.wm.read_factory_settings(use_empty=True)`, then runs
the piece's script with `runpy.run_path`, with the script's own directory as the
working directory. The script's globals carry:

- `FACET_ASSETS`: the Poly Haven root `blender.assets` fills, so fetched skies,
  textures and models arrive without a download inside the script.
- `FACET_PIECE_DIR`: the script's directory, which is how an example finds the
  glb or stl beside it, e.g. `f"{FACET_PIECE_DIR}/estudio.glb"`.

The script must leave `scene.camera` set. A run without one fails loudly, and so
does a script that raises: the message names the script, the exception type and
the last traceback lines.

After the script, facet applies its output settings, **overriding** whatever the
script set: the resolution at 100 %, the engine and its samples (Cycles on the
GPU through the runner's helper, then its samples and seed; Eevee with TAA
render samples), the seed, and the exposure. An animation also gets the frame
range `1..frames`, the `fps`, and the MP4 block (FFMPEG/MPEG4/H264, `HIGH`, no
file extension), then the output path. Everything else stays the script's: the
world, the lights, the materials, the colour-management look and view
transform, the keyframes.

The script runs **unsandboxed with the person's permissions**, like any code the
agent writes: it can read and write what the person can, so review it like a
shell command, not like a prompt.

## The glTF route

A CAD model arrives as the **glTF** `.glb` from a CadQuery `Assembly`, never
STEP:

```python
import cadquery as cq

estudio = cq.Assembly(name="estudio")
estudio.add(piso, name="piso")
estudio.add(muros, name="muros")
estudio.export("estudio.glb")  # glTF binary: one element per piece, with its name
```

- **Never STEP.** Blender does not open STEP without an extra plugin, and a
  glTF carries the piece names a script can dress by. This is why the route is
  `cad.solid` script → `Assembly.export(...glb)` → `blender.scene`.
- **One element per piece, named.** `Assembly.export` writes one glTF node per
  added element with the name it was added under; the examples match a
  material to each name prefix (`muros`, `vidrio-*`, `cama`, ...).
- **The model is in millimetres, Y-up.** CadQuery models in mm, so the scripts
  scale each top-level piece by `0.001` to metres; a model exported in metres
  comes out a thousand times too small. The glTF root also arrives turned -90°
  about X, and every piece inherits that turn: the examples clear each piece's
  parent (keeping its world transform) and bake its rotation and scale into its
  mesh before dressing it.

## Examples

The three examples are starting points an agent **copies and edits**. Each is a
piece TOML plus a Python script, and each keeps every creative choice in one
`DATA` dict at the top — light positions and power, materials, camera framing
and path — so editing values is enough.

### `examples/study-photo/` — the daylight architectural photo

`study-photo.toml` (`blender.scene`, Cycles at 1600x1000, exposure -0.6) and
`study_photo.py`, over the study `estudio.glb` that `estudio.py` (shipped
beside it) exports from CadQuery:

```toml
[inputs]
script = "study_photo.py"
name = "estudio"
width = 1600
height = 1000
engine = "cycles"
samples = 128
exposure = -0.6
```

The script imports the glb, scales it to metres, dresses each piece by name
prefix and builds the approved daylight look from `DATA`: a sun at azimuth 210°
and elevation 32°, a sky texture washing from the same direction at strength
0.2, `AgX - Medium High Contrast`, and an orthographic camera at azimuth -40°
and elevation 48° with the scale fitted to the whole model. Glass is Principled
with **alpha 0.2**, roughness 0.02 **and `surface_render_method = "BLENDED"`**:
see-through by transparency, which Eevee and Cycles both draw. Refraction
(transmission 1.0) renders as an opaque dark panel in Eevee without ray-traced
transmission, so the examples do not use it.

### `examples/product/` — one metal part in a studio

`product.toml` (`blender.scene`, Cycles at 1200x1200, exposure 0) and
`product.py`, over `part.stl` (a 10x20x30 mm box from `cad.solid`). The script
imports the STL, scales it from millimetres to metres, measures its bounding box
and frames it from that radius at a 50 mm lens. The metal is fully metallic
satin aluminium (roughness 0.22). What makes it read as metal is contrast: a
near-black world, a dark glossy floor, and three square area lights (a key
softbox, a fill and a rim strip) whose reflections run across the faces. A
bright, even world turns the metal into flat grey plastic; a small lamp in a
black world gives a black box with a blown top. Energies are a few watts:
a part a few centimetres across under 30 W burns to white.

### `examples/tour/` — the study on a camera orbit

`tour.toml` (`blender.animation`, Eevee at 1280x720, 240 frames at 24 fps,
exposure -0.4) and `tour.py`, which imports `../study-photo/estudio.glb`. The
scene is the study photo's look; the camera glides from the move's start triple
(azimuth -75°, elevation 55°, distance 14 m) to its end triple (-15°, 40°,
10.5 m) with the lab's smoothstep `t*t*(3-2*t)`, so it leaves and arrives
gently like a crane. A 30 mm lens frames the study. One `location` and one
`rotation_euler` keyframe per frame is what makes Blender interpolate the move.
The script sets Eevee's screen-space ray tracing (`SCREEN`), fast GI and
shadows; facet sets the frame range, the rate and the exposure.

### `examples/scene/` — the minimal scripted piece

`scene.toml` and `animation.toml` share `build.py`: a plane, three Principled
primitives, two lights and a camera keyframed over frames 1..120, so the same
file stills and animates.

## Assets

`blender.assets` (kind `text`, generic preview) fetches Poly Haven files — skies,
textures and models, all CC0. A piece gives a required `name` — the receipt is
`<name>.assets.json` — and lists ids with an optional pinned `res` (`1k`, `2k`,
`4k`; the lab defaults are 2k for skies and textures, 1k for models):

```toml
[inputs]
name = "estudio-dressing"
assets = [
  { id = "kloppenheim_06_puresky", res = "2k" },
  { id = "aerial_grass_rock", res = "2k" },
  { id = "shrub_02", res = "1k" },
]
```

The runner fetches the list **once** into the shared models dir,
`<home>/models/blender/polyhaven/<id>/`, with the exact mechanism in
`polyhaven.py`: the type comes from `info/<id>`, the file records from
`files/<id>`, files already present with the right size are skipped and every
download is md5-checked, and the names are fixed — `sky.hdr`,
`diff.jpg`/`nor_gl.jpg`/`rough.jpg` (the first `col_*` colour variant for
textures), `<id>.gltf` plus its includes. Models reporting more than 4,000,000
polygons are refused with the id and count named. The run writes one asset,
`<name>.assets.json`, the receipt of ids, file paths, bytes and md5s; `verify`
re-measures every listed file on disk and `preview` writes
`<name>.assets.json.preview.json` for the generic viewer. No manifest
`[[models]]` entries: the URLs and md5s are dynamic per file record and cannot
be pinned statically, so the runner — not the core downloader — performs the
fetch.

## Verification and doctor

`verify` measures the file, never the look. A scripted still's PNG header (the
IHDR, which needs no third-party module inside Blender) must parse and measure
exactly the piece's `width` and `height`; the metrics carry `width` and
`height`, and a file that is not a PNG carries `error` and fails. A scripted
animation is probed from its MP4 boxes instead — `ftyp`, `moov/mvhd` for the
timescale and duration, `avc1` for the size, `stts` for the frame count —
against the piece's own width, height, frames and fps.

A still whose luminance is flat fails the run itself as a uniform image, and the
record's properties carry its mean and standard deviation.

`facet preview <name>.png` writes `<name>.png.preview.json` for the `image`
kind with `name`, `prompt` (the script and the engine), `seed`, `width` and
`height`; a clip gets the video kind's file from the probe's measurements.

`facet doctor blender` reports the `host_app` check alone: a host-app package's
engine check *is* the application's resolution and version probe, so Blender
missing or below 5.2 fails `machine_cannot` with the `facet config set
blender.path` fix. The package's own `doctor` verb runs inside the host — facet
never reaches it for a host-app engine — and reports `bpy` with the running
Blender's version.

## Machine cost

`requirements` in the manifest: **GPU**, **4 GB RAM**, **0.1 GB disk**,
`exclusive = true` (a Cycles render owns the GPU) on `linux` — Blender lives on
the Windows host behind WSL. No environment build, and Blender is never
installed; `blender.assets` is the one download — versioned CC0 assets that
arrive into the models dir and are re-verified on every fetch.

## Running an example

```sh
facet run blender.scene packages/blender/examples/study-photo/study-photo.toml --out build/
facet run blender.scene packages/blender/examples/product/product.toml --out build/
facet run blender.animation packages/blender/examples/tour/tour.toml --out build/
```

`script` is resolved relative to the piece file, so run the TOML from the
example folder that carries its script and model. The record lands beside the
output as `<name>.png.facet.json` or `<name>.mp4.facet.json`.
