---
name: blender
description: Scenes and animations from your own Blender script through a host Blender, with facet owning only the output settings, plus the Poly Haven assets to light it.
---
# Blender

`blender.scene` renders one PNG from a Blender Python script you write, and
`blender.animation` renders one MP4 from the same kind of script. **facet owns
only the output**: the resolution, the engine and its samples, the seed, the
exposure, and for an animation the frame range and rate. **The script owns
every creative choice**: the world, the lights, the materials, the camera and
the keyframes.

facet never installs Blender: it drives the one you already have. Name it once
with `facet config set blender.path /path/to/blender` (or `BLENDER_EXE`, or
put `blender` on `PATH`); `facet doctor blender` fails with `machine_cannot`
and that exact command when it is missing or older than 5.2.

## When to use

- When a person should see the CAD part or the flat model as architecture, a
  product shot or a walkthrough: write the scene as a script. Nothing about
  the look is facet's, so a noir interior or a white cyclorama is as easy as
  daylight.
- When the model is a `cad.solid` piece: the glTF `Assembly.export` writes
  keeps one element per piece with its name, and the script can dress each
  piece by that name. Import it, scale it from millimetres (`0.001`) and go.
- When you want a starting point rather than a blank file: the three examples
  here are scripts you **copy and edit**. Each keeps every creative choice in
  one `DATA` dict at the top, so you change values, not code:
  - `examples/study/` — the daylight architectural photo of the study
    (`study.toml`, `study.py`, `study.glb`).
  - `examples/product/` — one metal part under three softboxes in a dark
    studio (`product.toml`, `product.py`, `part.stl`).
  - `examples/tour/` — the study on a camera orbit, in Eevee
    (`tour.toml`, `tour.py`).
  `examples/scene/` is the minimal scripted piece: a plane, three primitives,
  two lights and a keyframed camera.
- When the scene needs fetched textures, skies or plant models:
  `blender.assets` downloads Poly Haven files once into the shared models dir
  and the script reads them from `FACET_ASSETS`.
- Not for stills from prompts (use `comfy.still`), and not for a line view of a
  part (use `cad.solid`'s SVG).

## Pieces

A scripted still, the minimal form:

```toml
[inputs]
script = "build.py"
name = "study-script"
```

An animation from the same script:

```toml
[inputs]
script = "build.py"
name = "study-animated"
frames = 240
fps = 24
```

`script` is resolved relative to the piece file and must set `scene.camera`.
`name` writes `<name>.png` or `<name>.mp4`. `width`/`height` (64..4096,
1920x1080), `engine` (`cycles` for a still, `eevee` for an animation),
`samples` (128 for Cycles, 64 for Eevee TAA), `exposure` (-5..5) and `seed`
are facet's: the runner applies them after the script, overriding whatever it
set. An animation also takes `frames` (1..1440, 120) and `fps` (1..60, 24).

The example pieces are the fastest way to see a full one; copy the folder, edit
its `DATA` and run the TOML beside it:

```toml
[inputs]
script = "study.py"
name = "study"
width = 1600
height = 1000
engine = "cycles"
samples = 128
exposure = -0.6
```

The script contract: facet starts from an empty factory scene, runs the script
with its own directory as the working directory, and hands it two globals —
`FACET_ASSETS` (the Poly Haven root `blender.assets` fills) and
`FACET_PIECE_DIR` (the script's directory, which is how an example finds its
glb or stl). The script must leave `scene.camera` set. A run without one, or a
script that raises, fails loudly with the script's name and the traceback tail.
`skill/references/scene.md` has the full contract, including the warning that
the script runs unsandboxed with the person's permissions.

Fetched assets come first, as their own piece:

```toml
[inputs]
name = "study-dressing"
assets = [
  { id = "kloppenheim_06_puresky", res = "2k" },
  { id = "aerial_grass_rock", res = "2k" },
  { id = "shrub_02", res = "1k" },
]
```

The id is the last part of the asset's polyhaven.com URL; `res` pins the level
(2k by default for skies and textures, 1k for models).

## Judging the result

`verify` measures the file, never the look: a scripted still's PNG header
against the piece's own `width` and `height`, and a scripted animation's MP4
boxes (width, height, frames, fps) against the piece's own values. A still
whose luminance is flat fails the run itself as a uniform image — check the
camera's framing and the lights. `preview` writes the image or video kind's
`<asset>.preview.json` beside the file.

Beyond the measurement, a person judges the frame: the model stands on its
floor, the light falls from where the script says, materials read as what they
are (glass see-through, metal with a highlight), and the camera frames what it
was meant to. Aesthetics are yours, never the verifier's.

`facet doctor blender` resolves the host Blender (`blender.path`,
`BLENDER_EXE`, `PATH`) and fails `machine_cannot` below 5.2.

## Pitfalls

- **The script, not facet, decides the light.** Do not look for an `exposure`
  default that fixes a dark frame: set the sun, the lamps and the world in
  `DATA`, and use `exposure` in the TOML only as a final trim.
- **Glass by alpha, not refraction.** Transmission 1.0 renders as an opaque
  dark panel in Eevee. Give the glass alpha below 1 (0.2 in the examples) and
  `surface_render_method = "BLENDED"`; Cycles draws it the same way.
- **Metal reads by contrast.** A metal reflects its surroundings: in a black
  world with one small lamp it is a black box, in a bright even world it is grey
  plastic. A dark world with a few softboxes whose reflections cross the faces
  reads as metal, as `examples/product/` does. Small parts need only a few watts.
- **glTF is millimetres and Y-up.** Scale the imported roots by `0.001`; a
  model exported in metres comes out a thousand times too small. Never STEP:
  Blender does not open it without an extra plugin.
- **Cycles on the GPU needs a real device.** Without OptiX/CUDA it falls back
  to CPU and a still takes minutes, not the seconds a GPU render takes. An
  animation in Cycles is half an hour or more; Eevee is the animation engine.
- **A referenced Poly Haven id must be fetched first.** A missing file fails
  the run naming the `blender.assets` entry that fetches it; the script never
  downloads anything.
- **WSL only retries interop.** The first launch of a Windows `blender.exe`
  from WSL can fail on `UtilAcceptVsock`; that failure alone is retried once,
  so a broken script is never rendered twice.
