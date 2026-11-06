# comfy

Stills and reference-guided edits with ComfyUI: `facet run comfy.still
<piece.toml>` turns each `[[inputs.image]]` entry into `<name>.png` beside the
piece file, and `facet run comfy.edit <piece.toml>` does the same from one
reference image, changing it by instruction. Both belong to the **`image`**
facet, write the **`image`** kind and show through the image viewer. A GPU is
required: one model at a time, about 8 s per 1344 × 768 image on
z-image-turbo, about 6 s on flux2-klein-4b, about 23 s per edit.

ComfyUI is the lab's own tool (`~/Projects/open-source/ComfyUI`, 0.39.2) and
facet treats it as an `[engine.server]`: `facet pull comfy` clones the pinned
revision `3c1b7a17fdf239d35ce98cc777756f572d089795` into the facet home,
builds its venv from its `requirements.txt`, and downloads the six models
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
| `workflow` | enum | no | `"z-image-turbo"` | `"z-image-turbo"` or `"flux2-klein-4b"`; picks the still flow |

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

## Edits

`comfy.edit` iterates an image instead of rerolling it: one `source`
reference image for the whole piece, then one instruction per entry. The lab's
verdict on `flux2-klein-img2img` holds here: **guided by reference image, no
denoise slider.** It is reference-guided, not strength-guided. Editing keeps
the framing and the character and changes what the instruction says: a
linocut restyle, another palette, a different mood. Trying amounts of change
is not what this capability is for; if a gradual transformation needs a
strength knob, that is a separate flow.

The fields below are what `facet describe comfy.edit --json` reports.

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `source` | path | yes | — | reference image, relative to the piece; missing fails `invalid_input` |
| `image` | array | yes | — | at least one entry; each writes one PNG |
| `image[].name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; the asset base name |
| `image[].prompt` | string | yes | — | English instruction describing the edit |
| `image[].seed` | integer | yes | — | same seed, prompt and reference give the same image |
| `image[].width` | integer | no | `1344` | 64 to 2048, a multiple of 64 |
| `image[].height` | integer | no | `768` | 64 to 2048, a multiple of 64 |

The entries have the same five fields and defaults as `still`, so `verify`
and `preview` work unchanged; there is no `workflow` input, because an edit
always uses `flux2-klein-img2img`. The reference is uploaded once per run and
guides every entry; a second reference image is a second piece.

```toml
[inputs]
source = "flux2-klein-4b/ilustracion-editorial.png"
image = [
  { name = "iteracion-grabado", seed = 242, prompt = "Edit the reference image into a two-color linocut print in deep indigo and warm cream. Preserve the woman reading under the desk lamp, the framing, and the large geometric shapes. Use rough carved edges and visible paper grain. Do not add lettering or symbols." },
]
```

That pair is the lab's approved piece
(`projects/prueba-imagen/img2img.toml`): `iteracion-grabado.png` came from
`ilustracion-editorial.png` in 22.7 s at 1344 × 768, keeping the character
and framing while turning the picture into a blue and cream print.

## The no-data rule

Images carry image content only: no caption, no chart, no label, no logo, no
sign, no title, no watermark, no numbers. Text and figures belong in HTML or
SVG. A prompt that names one of those words (as a whole word, any case) is
rejected with `invalid_input` before anything runs; digits stay allowed, so
"85mm lens" passes. This holds for a still prompt and for an edit
instruction. Illustrations, backgrounds and mood only.

## Flows

A **flow** is a ComfyUI API graph whose inputs written as `"$key"` are
filled, in order, from the flow's own `params`, then the entry. The still
piece's `workflow` input picks one of the two still flows; an edit always
uses `flux2-klein-img2img`. The package ships three, all copied unchanged
from the lab's `tools/comfy/`:

| Flow | Models | Capability | Pick it for |
|------|--------|------------|-------------|
| `z-image-turbo` | Z-Image Turbo unet, the shared Qwen clip, the Z-Image VAE | `still` | photographic realism |
| `flux2-klein-4b` | FLUX.2 klein 4B unet, the shared Qwen clip, the FLUX.2 VAE | `still` | palette, composition and empty space |
| `flux2-klein-img2img` | FLUX.2 klein 4B unet, the shared Qwen clip, the FLUX.2 VAE | `edit` | editing a reference image by instruction |

- `$prompt`, `$seed`, `$width`, `$height` and `$name` come from the entry;
  the edit flow adds `$image`, the uploaded reference.
- `$steps` and `$shift` come from the flow's `params`; klein has no
  `$shift` (its params are width 1344, height 768, seed 0, steps 4).
- The unet, clip and vae load by the filenames of the manifest models;
  all three flows share the one Qwen clip file.

Only the edit flow lists `uploads`: instead of a value it takes a local file.
Before filling the graph, the runner posts the piece's `source` to the
server's `/upload/image` endpoint (the lab's multipart protocol, `overwrite`
set) and fills `$image` with the name the server answers, `subfolder/name`
when it names one. One upload serves every entry. The run prints
`<file> uploaded as <name>` — the reference's file name and the name the
server stored — so the log shows what reached the server.

At run start the runner links each facet model into the checkout where
ComfyUI looks — the unet into `models/diffusion_models/`, the clip into
`models/text_encoders/`, the vae into `models/vae/` — as symlinks, refreshed
on every run. The link target is the file `facet pull` downloaded under
`models/direct`; nothing is copied.

## Assets

One run writes one PNG per entry, each with a record (`kind = "image"`,
`mime = "image/png"`, `seed` the entry's seed, `params` the entry, and
`properties` carrying `width`, `height` and `seed`). The runner prints one
`<name>.png ok` line per output, with no absolute path and no timing. An edit
run also uploads the piece's `source` first, so its log starts with the
`<file> uploaded as <name>` line and then the same `<name>.png ok` lines.

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
- `models` (quick): the six manifest models are present with their byte
  counts.
- `checkout` (quick): the pinned ComfyUI checkout exists with `main.py`.
- `server` (full): the started ComfyUI answers `/system_stats`.

Every pull-fixable failure names `facet pull comfy` as its fix. The facet
readiness gate separately checks the GPU, RAM and disk the manifest
declares, and the licence acceptance.

## Licences

The tool is ComfyUI (GPL-3.0-or-later); the runner's own dependency is
Pillow (MIT-CMU). The six models — the Z-Image Turbo unet, the FLUX.2 klein
4B unet, their two VAEs and the Qwen clip all three flows share — are
Apache-2.0, commercial use allowed, and no acceptance is needed. The manifest
records each model's direct URL and sha256, measured from the lab's clone.

## Machine cost

`requirements` in the manifest: **GPU**, **16 GB RAM**, **25 GB disk**,
exclusive (the default) on Linux — one heavy job at a time. The first `facet
pull comfy` clones ComfyUI, builds its venv and downloads about 20.2 GB of
models (the shared Qwen clip downloads once); later runs are offline. One
model fits the 8 GB reference GPU at a time.
