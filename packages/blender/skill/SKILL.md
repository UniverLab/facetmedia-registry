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
- When a person should watch the model instead of a single still:
  `blender.recorrido` orbits the same glTF in Eevee and writes an MP4.
- When the scene needs a human scale: `blender.foto` and `blender.recorrido`
  take a prebuilt people `.blend` (`personas-blend`) and one `personas` item
  per person. The blend comes from the lab flow, never from this package.
  Each collection is named for the person, its single root stands on the
  floor the sun casts on, and the people face -y by default. They load after
  the model is dressed, so their own MPFB materials are never re-dressed.
- When the scene needs cars for scale or setting: both scenes take a prebuilt
  car `.blend` (`autos-blend`) and one `autos` item per car. The lab builds it
  once from the Quaternius Cars pack (CC0, real proportions, low poly), and
  the package only places it. Each car hangs from an anchor EMPTY at the
  centre of its base and faces -y too; keep cars about 1.5 m from a 2.5 m
  wall, which hides them from a camera at 52°.
- Not for stills from prompts (use `comfy.still`), and not for a line view of
  a part (use `cad.solid`'s SVG).

What the lab kept and what it rejected:

- **Kenney Car Kit (CC0)** is stylised: large wheels, toy shapes. It is for
  stylised pieces only, never for a realistic scene.
- **Sketchfab** is out for now: almost every car is CC-BY and its API asks for
  the person's account and token.
- **D5 Render** is out: a closed GUI application, Windows only, with no
  scripts.

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

Omit `escala` to fit the whole model; set it smaller to crop in.

Run it with `facet run blender.foto <piece>.toml --out build/`; the asset lands
as `<model>-foto.png` beside the piece unless `--out` says otherwise.

A tour over the same study (`examples/recorrido.toml`), the lab's start and
end triples written out:

```toml
[inputs]
model = "estudio.glb"
azimut = [{ inicio = -75, fin = -15 }]
elevacion = [{ inicio = 55, fin = 40 }]
distancia = [{ inicio = 14.0, fin = 10.5 }]
focal = 30
seconds = 10
fps = 24
```

`blender.recorrido` renders 240 frames at 1280x720 in ~100 s with Eevee. Run
it with `facet run blender.recorrido <piece>.toml`; the clip lands as
`<model>-recorrido.mp4`.

A product photo has no example piece because no STL ships: point `part` at the
STL `cad.solid` wrote.

```toml
[inputs]
part = "escuadra.stl"
material = "aluminio-cepillado"
backdrop = "grafito"
```

People and cars are piece data on a scene, not separate pieces. The keys are
hyphenated, exactly as facet resolves them:

```toml
[inputs]
model = "estudio.glb"
personas-blend = "personas.blend"
personas = [
  { nombre = "luis", x = 3.0, y = 2.6, giro = 90 },
  { nombre = "ana", x = 4.5, y = 3.85, giro = 180 },
  { nombre = "sara", x = 1.45, y = -1.3, giro = 180 },
]
autos-blend = "autos.blend"
autos = [
  { nombre = "sedan", x = -2.7, y = 0.8, giro = 0 },
  { nombre = "camioneta", x = -5.1, y = 0.8, giro = 0 },
]
```

Those placements are the lab's triple as the reference example, never a
default: omit `personas` or `autos` and nothing is added. `personas-blend` and
`autos-blend` are optional too; a scene without them has no people and no cars.

The lab's people catalog holds 14 outfits, 6 pairs of shoes, 10 hairstyles and
23 skins; the arms sit 40° down from the A pose, and the car faces are smooth
below 30°. Those are the blend's own facts, so the package reads them, never
regenerates them.

`blender.assets` is the fetching half: a piece lists Poly Haven ids (`{ id,
res }` items) and the runner downloads them once into the shared models dir,
writing `<name>.assets.json` as the receipt `verify` re-checks.

## Dressing the scene

`blender.foto` and `blender.recorrido` render the fetched Poly Haven sky,
textures and plants when the piece asks for them; without them the procedural
sky, the flat colours and the empty ground stay exactly as they are. The three
inputs are arrays of fixed-field items, the way `camera` is, and the runner
reads only the first `cielo` item:

```toml
[inputs]
model = "estudio.glb"
cielo = [{ id = "kloppenheim_06_puresky", giro = 200, fuerza = 1.0 }]
texturas = [
  { prefijo = "suelo", id = "aerial_grass_rock", lado = 3.0, matiz = 0.5, saturacion = 1.0, valor = 0.9 },
  { prefijo = "piso", id = "brushed_concrete", lado = 2.0, matiz = 0.5, saturacion = 1.0, valor = 1.0 },
]
plantas = [
  { id = "shrub_02", x = 7.4, y = 2.25, giro = 90 },
]
```

- `cielo` holds one `{ id, giro, fuerza }` item: the HDRI id, its turn about Z
  in degrees (200 by default, which sets where the sun falls) and the
  background strength (1.0 by default). With it the scene has no `sol` lamp:
  the HDRI lights the render and `use_sun_shadow` pulls the shadows out of it.
- `texturas` holds one `{ prefijo, id, lado, matiz, saturacion, valor }` item
  per dressed prefix: the texture id, the tile side in metres (2.0 by default)
  and the hue/saturation/value adjust (0.5, 1.0 and 1.0 by default). A prefix
  without an item keeps its flat `MATERIALS` colour, and the ground plane
  `suelo` is textured by the item with `prefijo = "suelo"`. Two items with the
  same `prefijo` fail the run with `texturas: prefijo repetido: <prefijo>`.
- `plantas` holds one `{ id, x, y, giro }` item per plant: the model id, its
  place in metres on the ground level and its turn about Z (0 by default).
  Plants stand the way people and cars do, after the dressing, so no prefix
  check touches them.
- A referenced id must already be fetched: a missing folder or file fails the
  run before rendering with the `blender.assets` entry that fetches it. Foto
  and recorrido never download.

These ids are verified on polyhaven.com; the id is the last part of the
asset's URL:

| Kind | Id |
|------|-----|
| sky | `kloppenheim_06_puresky` |
| textures | `aerial_grass_rock`, `brick_pavement_02`, `brushed_concrete` |
| plant models | `shrub_02`, `potted_plant_01`, `jacaranda_tree`, `grass_medium_01`, `island_tree_01` |

Plant models are heavy, so use few: `potted_plant_01` is about 96k polygons
and `island_tree_01` about 3.7M. Fetch the set first with one `blender.assets`
piece:

```toml
[inputs]
name = "estudio-dressing"
assets = [
  { id = "kloppenheim_06_puresky", res = "2k" },
  { id = "aerial_grass_rock", res = "2k" },
  { id = "brushed_concrete", res = "2k" },
  { id = "shrub_02", res = "1k" },
]
```

## Judging the result

`verify` measures the PNG header: it passes at exactly 1600x1000, the recipe's
size. `preview` writes `<asset>.preview.json` for the image kind with `name`,
`prompt` (the recipe line), `seed`, `width` and `height`, and the viewer shows
the photo itself. A tour is checked by the MP4 probe instead: width, height,
frame count and fps from the file itself, against the piece's entry.

Beyond the size, a person judges the photo: the model stands on the floor
plane, the sun casts a shadow, the walls are not white-clipped and the rooms
read through the windows; people stand on that same floor at the right scale
and cars sit on their wheels, not through the pavement.

`references/tour.md` has the Eevee flags, the smoothstep move and the ffmpeg
settings Blender writes the MP4 with. `references/people-cars.md` has the two
prebuilt-blend contracts, the placement item shapes and the lab triples.

`facet doctor blender` resolves the host Blender (`blender.path`,
`BLENDER_EXE`, `PATH`) and fails `machine_cannot` below 5.2; the package's own
`doctor` verb — bpy, the glTF importer, Cycles and, on request, the OptiX
device — answers when `runner.py` is run directly. No check reads the people
or car pack folder: that state lives in the lab, outside this package.

## Pitfalls

- **glTF, never STEP.** Blender does not open STEP without an extra plugin.
  Export with `Assembly.export("piece.glb")` in CadQuery, one element per
  piece, and the element's name is the piece's name in Blender.
- **The glTF is in millimetres and Y-up.** The runner scales the top-level
  pieces by 0.001 to metres; a model exported in metres comes out tiny.
- **A piece without a material prefix fails the whole run** with
  `piezas sin material: [...]`. The accepted prefixes are `muros`, `piso`,
  `vidrio`, `cama`, `almohada`, `mesa`, `sillas`, `suelo` and `pavimento`
  (the keys of `MATERIALS` in `escena.py`); the prefix is the start of each
  glTF element name, as the cad export names it. Rename the piece in its
  model with one of them; nothing is rendered half-dressed.
- **Do not raise the exposure to brighten a dark photo.** Under
  `AgX - Medium High Contrast` at -0.6, `sol + cielo` washes the colours out;
  move the sun or lower `exposure` instead of lighting the scene harder.
- **Cycles on the GPU needs a real device.** Without OptiX/CUDA it falls back
  to CPU and the render takes minutes, not the 11 s the recipe is measured at.
- **A tour is Eevee, a still is Cycles.** Cycles takes about 45 minutes for
  240 frames; Eevee does them in ~100 s. A still renders in 8-10 s per image
  at 128-160 samples with denoising, ~11 s in the lab's measurement.
- **A name the blend does not hold fails the run loudly.** The runner raises,
  and facet reports it as `runner_failed`; it never skips the person or car
  silently.
- **A missing blend is refused before the runner starts.** A path input that
  does not resolve is a core pre-run `not_found` (exit 2), not a Blender
  error: check the path relative to the piece file.
- **WSL only retries interop.** The first launch of a Windows `blender.exe`
  from WSL can fail on `UtilAcceptVsock`; that failure alone is retried once,
  so a broken scene is never rendered twice.
