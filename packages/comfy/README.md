# comfy

Still illustration from prompts with ComfyUI: `facet run comfy.still
<piece.toml>` turns each `[[inputs.image]]` entry into `<name>.png` beside the
piece file. It belongs to the **`image`** facet, writes the **`image`** kind
and shows through the image viewer. A GPU is required: one model at a time,
about 8 s per 1344 × 768 image.

ComfyUI is the lab's own tool (`~/Projects/open-source/ComfyUI`, 0.39.2) and
facet treats it as an `[engine.server]`: `facet pull comfy` clones the pinned
revision `3c1b7a17fdf239d35ce98cc777756f572d089795` into the facet home,
builds its venv from its `requirements.txt`, and downloads the three models
next to it. For the duration of a verb facet starts
`main.py --listen 127.0.0.1 --port <free>`; the runner reaches it through
`FACET_SERVER_URL`. Nothing is installed globally.

## Piece format

The fields below are what `facet describe comfy.still --json` reports.

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `image` | array | yes | — | at least one entry; each writes one PNG |
| `image[].name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; the asset base name |
| `image[].prompt` | string | yes | — | English; illustration, backgrounds or mood only |
| `image[].seed` | integer | yes | — | same seed and prompt give the same image |
| `image[].width` | integer | no | `1344` | 64 to 2048, a multiple of 64 |
| `image[].height` | integer | no | `768` | 64 to 2048, a multiple of 64 |

```toml
[inputs]
image = [
  { name = "fondo-video", prompt = "Misty pine forest at dawn, soft volumetric light through the trees, muted teal and amber palette, large empty area of fog on the left", seed = 11 },
  { name = "acuarela", prompt = "Loose watercolor painting of a colonial street in a small Andean town, colorful facades with wooden balconies, cobblestones, green mountains", seed = 14, width = 1344, height = 768 },
]
```

An unknown key in an entry — or in the piece's `[inputs]` — fails piece
validation with `invalid_input`, as the lab's `tools/comfy.py` errors on an
unknown key.

### The no-data rule

Images carry image content only: no caption, no chart, no label, no logo, no
sign, no title, no watermark, no numbers. Text and figures belong in HTML or
SVG. A prompt that names one of those words (as a whole word, any case) is
rejected with `invalid_input` before anything runs; digits stay allowed, so
"85mm lens" passes. Illustrations, backgrounds and mood only.

## Flows

A **flow** is a ComfyUI API graph whose inputs written as `"$key"` are
filled, in order, from the flow's own `params`, then the entry. The package
ships one, `flows/z-image-turbo.json`, copied unchanged from the lab's
`tools/comfy/z-image-turbo.json`:

- `$prompt`, `$seed`, `$width`, `$height` and `$name` come from the entry.
- `$steps` (8) and `$shift` (3) come from the flow's `params`.
- The unet, clip and vae load by the filenames of the three manifest models.

At run start the runner links each facet model into the checkout where
ComfyUI looks — the unet into `models/diffusion_models/`, the clip into
`models/text_encoders/`, the vae into `models/vae/` — as symlinks, refreshed
on every run. The link target is the file `facet pull` downloaded under
`models/direct`; nothing is copied.

## Assets

One run writes one PNG per entry, each with a record (`kind = "image"`,
`mime = "image/png"`, `seed` the entry's seed, `params` the entry, and
`properties` carrying `width`, `height` and `seed`). The runner prints one
`<name>.png ok` line per output, with no absolute path and no timing.

## Verification and doctor

`verify` opens every PNG with Pillow and passes when its pixel size equals
the entry's `width` and `height`, reporting both as metrics and thresholds
(`verifier = "pillow"`). A wrong size or an unreadable file is a failed
verdict, never a crash.

`facet preview <name>.png` writes `<name>.png.preview.json` (the `image`
schema) with the name, prompt, seed and measured width and height, and the
image viewer shows the picture itself, click to enlarge.

`facet doctor comfy` runs the package's checks:

- `gpu` (quick): `nvidia-smi -L` sees an NVIDIA GPU.
- `gpu_free` (quick): no other process holds GPU memory, unless the server
  facet started answers `/system_stats`.
- `models` (quick): the three manifest models are present with their byte
  counts.
- `checkout` (quick): the pinned ComfyUI checkout exists with `main.py`.
- `server` (full): the started ComfyUI answers `/system_stats`.

Every pull-fixable failure names `facet pull comfy` as its fix. The facet
readiness gate separately checks the GPU, RAM and disk the manifest
declares, and the licence acceptance.

## Licences

The tool is ComfyUI (GPL-3.0-or-later); the runner's own dependency is
Pillow (MIT-CMU). The three models — the Z-Image Turbo unet, its Qwen clip
and its VAE — are Apache-2.0, commercial use allowed, and no acceptance is
needed. The manifest records each model's direct URL and sha256, measured
from the lab's clone.

## Machine cost

`requirements` in the manifest: **GPU**, **16 GB RAM**, **25 GB disk**,
exclusive (the default) on Linux — one heavy job at a time. The first `facet
pull comfy` clones ComfyUI, builds its venv and downloads about 12.2 GB of
models; later runs are offline. One model fits the 8 GB reference GPU at a
time.
