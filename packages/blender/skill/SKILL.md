---
name: blender
description: Daylight architectural photos of CadQuery glTF models through a host Blender's Cycles GPU, rendered in seconds and checked by pixel size.
---
# Blender

Render architecture from the CAD you already modelled: `blender.foto` takes
the glTF that `cad.solid` exported from a CadQuery `Assembly` and gives back
a daylight photo at 1600x1000. The package writes the `image` kind, so the
photo opens in the image viewer and its preview carries the size, the turning
and the exposure.

facet never installs Blender: it drives the one you already have. Name it once
with `facet config set blender.path /path/to/blender` (or `BLENDER_EXE`, or
put `blender` on `PATH`); `facet doctor blender` fails with
`machine_cannot` and that exact command when it is missing or older than 5.2.

## When to use

- When a person should see the CAD part or the flat model as architecture:
  a study, a facade, a room. The output is a photo, not a drawing.
- When the model is already a `cad.solid` piece with one CadQuery element per
  piece and a meaningful name (`muros`, `piso`, `cama`, ...), because the name
  is what decides each piece's material.
- When a person should see one finished part as a catalogue photo:
  `blender.producto` shoots the STL from `cad.solid` at 1200x1200, with the
  studio lights scaled to the part's own size.
- Not for stills from prompts (use `comfy.still`), and not for a line view of
  a part (use `cad.solid`'s SVG).

## Pieces

The lab's study, exported by `packages/cad/examples/plano-estudio.py` or the
Grafics `estudio.py` (`examples/estudio.toml`):

```toml
[inputs]
model = "estudio.glb"
```

A turned view with a different exposure:

```toml
[inputs]
model = "estudio.glb"
giro = 90
exposure = -0.9
camera = [{ azimut = 25, elevacion = 40, escala = 12 }]
```

Run it with `facet run blender.foto <piece>.toml --out build/`; the asset lands
as `<model>-foto.png` beside the piece unless `--out` says otherwise.

`blender.assets` is the fetching half: a piece lists Poly Haven ids (`{ id,
res }` items) and the runner downloads them once into the shared models dir,
writing `<name>.assets.json` as the receipt `verify` re-checks.

## Judging the result

`verify` measures the PNG header: it passes at exactly 1600x1000, the recipe's
size. `preview` writes `<asset>.preview.json` for the image kind with `name`,
`prompt` (the recipe line), `seed`, `width` and `height`, and the viewer shows
the photo itself.

Beyond the size, a person judges the photo: the model stands on the floor
plane, the sun casts a shadow, the walls are not white-clipped and the rooms
read through the windows. `facet doctor blender` resolves the host Blender
(`blender.path`, `BLENDER_EXE`, `PATH`) and fails `machine_cannot` below 5.2;
the package's own `doctor` verb — bpy, the glTF importer, Cycles and, on
request, the OptiX device — answers when `runner.py` is run directly.

## Pitfalls

- **glTF, never STEP.** Blender does not open STEP without an extra plugin.
  Export with `Assembly.export("piece.glb")` in CadQuery, one element per
  piece, and the element's name is the piece's name in Blender.
- **The glTF is in millimetres and Y-up.** The runner scales the top-level
  pieces by 0.001 to metres; a model exported in metres comes out tiny.
- **A piece without a material prefix fails the whole run** with
  `piezas sin material: [...]`. Add the prefix to `MATERIALS` in `runner.py`
  or rename the piece; nothing is rendered half-dressed.
- **Do not raise the exposure to brighten a dark photo.** Under
  `AgX - Medium High Contrast` at -0.6, `sol + cielo` washes the colours out;
  move the sun or lower `exposure` instead of lighting the scene harder.
- **Cycles on the GPU needs a real device.** Without OptiX/CUDA it falls back
  to CPU and the render takes minutes, not the 11 s the recipe is measured at.
- **WSL only retries interop.** The first launch of a Windows `blender.exe`
  from WSL can fail on `UtilAcceptVsock`; that failure alone is retried once,
  so a broken scene is never rendered twice.
