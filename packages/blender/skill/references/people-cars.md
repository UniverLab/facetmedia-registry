# People and cars

Neither Poly Haven nor this package makes a person or a car. Each blend is
built once, outside this package, and `blender.photo` and `blender.tour`
load it as a path input and place its collections.

## The people blend: `people-blend`

A generator script builds the people blend with MPFB 2 (MakeHuman for Blender; the code is
GPL, the people it makes are CC0). Each person is described as the dictionary
`HumanService.deserialize_from_dict` takes: traits from 0 to 1 (age 0.5 is 25
years), skin, hair and clothes by package file name. Three people take about
10 s. The blend stores one collection per person, named with the person's
name, and the collection's single root object is the skeleton.

Contract:

- One collection per person, named by the `name` a placement item uses.
- A single root object (the armature), its origin at the person's base.
- The people face -y by default, like the cars.
- The package does not scale people with the model: they are placed in metres
  in the scene's own axes.

Pose fix: the package ships no poses and the skeleton comes in an A pose. The
build lowers the arms by rotating `upperarm01.L` by -40° and `upperarm01.R`
by +40° in Z. With the sign reversed they rise. The catalog
used is 14 outfits, 6 pairs of shoes, 10 hairstyles and 23 skins, in three
ages; they read a little generic up close, which is fine for an aerial view.

Placement item, one per person:

```toml
{ name = "luis", x = 3.0, y = 2.6, rotation = 90 }
```

`name` is the collection name; `x` and `y` are metres in the scene's axes;
`rotation` turns about Z in degrees from the -y facing. A name the blend does not
hold fails the run loudly.

## The car blend: `cars-blend`

A generator script imports the Quaternius Cars pack (CC0, real proportions, low poly,
about 1,500 faces per car): `NormalCar1` (sedan, 4.2 m), `NormalCar2`
(compact, 3.3 m), `SUV` (camioneta), `Taxi`, `SportsCar`, `SportsCar2` and
`Cop`. The files live in the lab's `assets/quaternius-cars/`, in FBX except
`SUV` and `Cop`, which are `.blend`. The download is a public Google Drive
folder fetched with `gdown`, which sometimes fails on Drive's download limit.

The build replaces the pack's materials by name (`Windows`, `Black`, `Grey`,
`Headlights`, `TailLights`); everything else is bodywork and takes the car's
own `pintura` with a clear coat. It smooths faces below 30° so the faceted
model reads smooth, and it turns every car to face -y.

Contract:

- One collection per car, named by the `name` a placement item uses.
- The collection hangs from an anchor EMPTY at the centre of the car's base.
- The car faces -y by default.
- `escena.py` loads and places cars with the same function it uses for people.

Placement item, one per car:

```toml
{ name = "sedan", x = -2.7, y = 0.8, rotation = 0 }
```

The lab's two placements are `("sedan", -2.7, 0.8, 0)` and
`("camioneta", -5.1, 0.8, 0)`, from `escena.py`; the generator also builds a
`compacto` collection that page never places. These are the reference example,
never a default.

Two placement notes from the lab:

- **Wall framing:** closer than about 1.5 m to a 2.5 m wall, the wall hides a
  car from a camera at 52°. Keep the cars out from the wall.
- **Colour:** a silver car reads white in the sun; use a colour with body.
  Up close the models read as low poly; for an aerial view they pass as real.

## Order of operations

The runner imports the glTF, scales the millimetre roots to metres, finds the
floor, dresses every piece with its material, and only then adds people and
cars on that floor. People come after the model is dressed, so a missing
material fails before any person is placed. People and cars are added before
the sky and camera, so they are lit and filmed like the rest of the scene.

## What fails, and where

- **A missing blend is a core pre-run `not_found`.** `people-blend` and
  `cars-blend` are path inputs; facet resolves them relative to the piece
  file before Blender starts. A path that does not resolve fails with
  `not_found` (exit 2), with no render attempted.
- **A name the blend does not hold is a runner failure.** The runner raises,
  and facet reports `runner_failed` (exit 9). There is no silent skip.
- **The doctor has no pack-folder check.** The package's `doctor` verb checks
  bpy, the glTF importer, Cycles and, on request, the OptiX device; the host
  app itself is facet's own check at the 5.2 floor. Nothing here verifies
  that the MPFB or Quaternius files are installed: that state belongs to the
  lab and the blend the piece points at.
