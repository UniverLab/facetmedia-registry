# rembg

Background removal from photos with rembg's U2NetP on CPU:
`facet run rembg.cutout` turns a photo into an alpha PNG and, beside it,
a checkerboard `-damero` PNG so a person can judge thin edges. CPU only,
no GPU flag; the only model is the `u2netp` ONNX weights file, which
arrives through `facet pull rembg` and is checked by sha256 in `doctor`.

## Capabilities and pieces

`rembg.cutout` — background removal, image kind:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `foto` | path | yes | — | PNG, JPEG or WebP, resolved relative to the piece |

`run` writes two assets into the output directory: `<foto-stem>.png`,
the RGBA cutout, and `<foto-stem>-damero.png`, the cutout pasted over a
white-and-grey checkerboard (32 px tiles, the lab's `vista-damero.png`
recipe). Both records carry the foto's stem as their name, seed 0 — the
cutout is deterministic given the weights, so the seed only labels the
record — and `properties` with the measured `width`/`height` (the
damero adds `"damero": true`).

## Verification and preview

`verify` re-opens each PNG with Pillow: it must be a readable PNG at the
run's size, RGBA for the cutout and RGB for the `-damero` file (the
piece's `foto` names both exactly; the `-damero` suffix is the fallback
when no `foto` is in the request). `preview` writes the image kind's
fields for each asset — `prompt` is `cutout of <foto-stem>`, `seed` 0,
`width`/`height` measured from the PNG — matching
`schemas/preview/image.schema.json`.

A person judges the result on the damero asset: semi-transparent fringes,
halo pixels and missed wisps show against the checkerboard while the
alpha PNG stays untouched for compositing. `facet doctor rembg` runs two
checks, both quick:

- `imports`: rembg, onnxruntime and Pillow import, with versions.
- `weights`: `u2netp.onnx` exists at its manifest size and hashes to the
  manifest's sha256.

Every failing check names `facet pull rembg` as its fix.

## Lab measurements

Ported from the lab's `projects/prueba-fondos/remover.py`
(`new_session("u2netp", providers=["CPUExecutionProvider"])`): on the
lab's `entrada.png` (1344×768) rembg 2.0.67's U2NetP cutout took 1.48 s on
CPU, 66.59 % of pixels transparent, and the damero view kept the figure,
the book and the lamp — the three subjects the photo was shot for. The
package pins rembg 2.0.86, the newest release the dependency audit
accepts; the session call and the weights are unchanged.

## Licences

rembg's code is MIT (Daniel Gatis). The U2NetP weights are U-2-Net,
Apache-2.0 (xuebinqin et al.), fetched from rembg's pinned release URL;
the manifest records the sha256, size, licence and terms URL. The rest of
the chain: onnxruntime (MIT), Pillow (MIT-CMU), NumPy (BSD-3-Clause),
plus rembg's own dependencies (pymatting MIT, scikit-image BSD-3-Clause,
scipy BSD-3-Clause, pooch BSD-3-Clause, tqdm MIT, jsonschema MIT).
