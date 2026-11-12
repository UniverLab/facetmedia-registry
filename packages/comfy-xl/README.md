# comfy-xl

Stills, reference-guided edits and clips with ComfyUI on a 24 GB GPU:
`facet run comfy-xl.still <piece.toml>` turns each `[[inputs.image]]` entry
into `<name>.png` beside the piece file, `facet run comfy-xl.edit
<piece.toml>` does the same from one reference image, changing it by
instruction, and `facet run comfy-xl.clip <piece.toml>` animates a still
into `<name>.mp4`. All three belong to the **`image`** facet; the first two
write the **`image`** kind and show through the image viewer, the clip
writes the **`video`** kind and shows through the video viewer. A GPU with
24 GB of VRAM is required: about a minute per 1344 × 768 image on z-image,
and about 7 minutes per two-second clip on wan22-i2v-14b, about half that
on its `wan22-i2v-14b-fast` draft variant.

This package has not yet been run on a 24 GB GPU by the lab: the flows
mirror the official ComfyUI templates, and they ship marked as not yet run
on such hardware. On an 8 GB card, use `comfy` instead.

ComfyUI is the lab's own tool and facet treats it as an `[engine.server]`:
`facet pull comfy-xl` clones the pinned revision
`3c1b7a17fdf239d35ce98cc777756f572d089795` into the facet home, builds its
venv from its `requirements.txt`, and downloads the twelve models next to
it. For the duration of a verb facet starts
`main.py --listen 127.0.0.1 --port <free> --disable-pinned-memory`; the
runner reaches it through `FACET_SERVER_URL`. Nothing is installed globally.

## Piece format

The fields below are what `facet describe comfy-xl.still --json` reports.

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `image` | array | yes | — | at least one entry; each writes one PNG |
| `image[].name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; the asset base name |
| `image[].prompt` | string | yes | — | English; illustration, backgrounds or mood only |
| `image[].seed` | integer | yes | — | same seed and prompt give the same image |
| `image[].width` | integer | no | `1344` | 64 to 2048, a multiple of 64 |
| `image[].height` | integer | no | `768` | 64 to 2048, a multiple of 64 |
| `image[].steps` | integer | no | flow default | sampling steps, at least 1; the flow's own is 25 |
| `image[].cfg` | number | no | flow default | classifier-free guidance, at least 0; the flow's own is 4 |
| `image[].sampler` | string | no | flow default | sampler name; the flow's own is `res_multistep` |
| `image[].scheduler` | string | no | flow default | scheduler name; the flow's own is `simple` |
| `image[].shift` | number | no | flow default | model sampling shift, at least 0; the flow's own is 3 |
| `workflow` | enum | no | `"z-image"` | `"z-image"`; the one still flow |

```toml
[inputs]
image = [
  { name = "fondo-video", prompt = "Misty pine forest at dawn, soft volumetric light through the trees, muted teal and amber palette, large empty area of fog on the left", seed = 11 },
]
```

An unknown key in an entry — or in the piece's `[inputs]` — fails piece
validation with `invalid_input`.

## Edits

`comfy-xl.edit` iterates an image instead of rerolling it: one `source`
reference image for the whole piece, then one instruction per entry. The
edit is **guided by reference image, no denoise slider.** It is
reference-guided, not strength-guided. Editing keeps the framing and the
character and changes what the instruction says: a new material, another
palette, a different mood.

The fields below are what `facet describe comfy-xl.edit --json` reports.

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `source` | path | yes | — | reference image, relative to the piece; missing fails `invalid_input` |
| `image` | array | yes | — | at least one entry; each writes one PNG |
| `image[].name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; the asset base name |
| `image[].prompt` | string | yes | — | English instruction describing the edit |
| `image[].seed` | integer | yes | — | same seed, prompt and reference give the same image |
| `image[].width` | integer | no | `1344` | 64 to 2048, a multiple of 64 |
| `image[].height` | integer | no | `768` | 64 to 2048, a multiple of 64 |
| `image[].steps` | integer | no | flow default | sampling steps, at least 1; the flow's own is 40 |
| `image[].cfg` | number | no | flow default | classifier-free guidance, at least 0; the flow's own is 4 |
| `image[].sampler` | string | no | flow default | sampler name; the flow's own is `euler` |
| `image[].scheduler` | string | no | flow default | scheduler name; the flow's own is `simple` |
| `image[].shift` | number | no | flow default | model sampling shift, at least 0; the flow's own is 3.1 |

The entries take the same name, prompt, seed, width, height and sampling
knobs as `still`, so `verify`
and `preview` work unchanged; there is no `workflow` input, because an edit
always uses `qwen-image-edit`. The reference is scaled to the entry's
`width`/`height` before it is encoded as the edit latent, uploaded once per
run and guides every entry; a second reference image is a second piece.

## Clips

`comfy-xl.clip` animates a still: each entry carries its own `image`, the
clip's first frame, and a prompt in English that describes what moves. It
writes an MP4, the `video` kind, and is the one capability here for motion
**inside** the frame.

**Draft first.** A camera move over a still — a zoom, a pan, a slow push from
a flat image — belongs to HyperFrames with GSAP: seconds instead of minutes,
and reproducible frame by frame. Reach for Wan only when something inside
the picture has to move: fog advancing, steam rising, water rippling, light
drifting. Even then the motion guidance is narrow: do not spend seven
minutes on a move GSAP draws in one second.

The fields below are what `facet describe comfy-xl.clip --json` reports.

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `image` | array | yes | — | at least one entry; each writes one MP4 |
| `image[].name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; the asset base name |
| `image[].image` | path | yes | — | the clip's first frame, relative to the piece |
| `image[].prompt` | string | yes | — | English; describes the movement inside the frame |
| `image[].seed` | integer | yes | — | same seed, prompt and first frame give the same clip |
| `image[].width` | integer | no | `1280` | 64 to 2048, a multiple of 64 |
| `image[].height` | integer | no | `704` | 64 to 2048, a multiple of 64 |
| `image[].length` | integer | no | `49` | frames at 24 fps: `49` ≈ 2 s, `121` ≈ 5 s |
| `image[].steps` | integer | no | flow default | sampling steps, at least 1; the flow's own is 20 on wan22-i2v-14b and 4 on wan22-i2v-14b-fast |
| `image[].cfg` | number | no | flow default | classifier-free guidance, at least 0; the flow's own is 5 on wan22-i2v-14b and 1 on wan22-i2v-14b-fast |
| `image[].sampler` | string | no | flow default | sampler name; the flow's own is `euler` |
| `image[].scheduler` | string | no | flow default | scheduler name; the flow's own is `simple` |
| `image[].shift` | number | no | flow default | model sampling shift, at least 0; the flow's own is 8 |
| `image[].negative` | string | no | flow default | what to keep out of the clip; omitting it keeps Wan's official Chinese negative, and `wan22-i2v-14b-fast` at cfg 1 ignores it |
| `workflow` | enum | no | `"wan22-i2v-14b"` | `"wan22-i2v-14b"`, or `"wan22-i2v-14b-fast"` for a draft-only clip |

The length must be `4n+1` frames — 49, 121 — because the Wan latent keeps one
frame plus groups of four. The schema cannot express that, so piece validation
accepts any integer; an off-form length reaches ComfyUI and fails the run as
`runner_failed`. The clip is 1280 × 704 at 24 fps.

```toml
[inputs]
workflow = "wan22-i2v-14b"
image = [
  { name = "bosque-niebla", image = "fondo-video.png", seed = 51, prompt = "Fog drifting slowly between the pine trees at dawn, soft light rays shifting through the mist, very slow camera push in, calm and quiet, cinematic" },
]
```

Each entry's first frame is uploaded on its own: the runner posts it to
`/upload/image` (the same multipart protocol as an edit) and fills `$image`
with the name the server answers, so one piece can animate several different
stills. The log prints one `<file> uploaded as <name>` line per entry.

### Drafts

`workflow = "wan22-i2v-14b-fast"` runs the same two-stage Wan graph with
the two lightx2v 4-step LoRAs, four steps and a CFG of 1, so a clip takes
about half the time. It is a **draft**: halfway through it drifts from the
input image — the light and the composition change — so it is for trying a
movement, never a final render or a piece of an assembly. The runner names
every draft output `<name>-borrador.mp4` and its record carries
`properties.draft = true`, so no draft passes for a final.

## The no-data rule

Images carry image content only: no caption, no chart, no label, no logo, no
sign, no title, no watermark, no numbers. Text and figures belong in HTML or
SVG. A prompt that names one of those words (as a whole word, any case) is
rejected with `invalid_input` before anything runs; digits stay allowed, so
"85mm lens" passes. This holds for a still prompt, an edit instruction and a
clip's motion prompt: a generated frame carries no lettering either.
Illustrations, backgrounds and mood only.

## Flows

A **flow** is a ComfyUI API graph whose inputs written as `"$key"` are
filled, in order, from the flow's own `params`, then the entry. The still
piece's `workflow` input picks the one still flow, the clip's picks
`wan22-i2v-14b` or its `wan22-i2v-14b-fast` draft, and an edit always uses
`qwen-image-edit`. The package ships four, derived from the official
ComfyUI templates shipped with the pinned ComfyUI's
`comfyui_workflow_templates_json` 0.11.78:

| Flow | Models | Capability | Pick it for |
|------|--------|------------|-------------|
| `z-image` | Z-Image base unet, Qwen3 clip, Z-Image VAE | `still` | photographic realism at full precision |
| `qwen-image-edit` | Qwen-Image-Edit unet, Qwen2.5-VL clip, Qwen-Image VAE | `edit` | editing a reference image by instruction |
| `wan22-i2v-14b` | Wan 2.2 I2V 14B high- and low-noise unets, UMT5 clip, Wan 2.1 VAE | `clip` | movement inside a still: fog, steam, a slow push in |
| `wan22-i2v-14b-fast` | the same, plus the high- and low-noise lightx2v LoRAs | `clip` | motion drafts in half the time |

- `$prompt`, `$seed`, `$width`, `$height` and `$name` come from the entry;
  the edit and clip flows add `$image`, the uploaded reference or first frame,
  and the clip flow also takes `$length`.
- `$steps`, `$cfg`, `$sampler` (filled into `sampler_name`), `$scheduler`
  and `$shift` come from the flow's `params` unless the entry sets them.
  These are the defaults each flow ships, so a piece that sets none of them
  renders exactly as before:

  | Flow | steps | cfg | sampler | scheduler | shift |
  |------|-------|-----|---------|-----------|-------|
  | `z-image` | 25 | 4 | `res_multistep` | `simple` | 3 |
  | `qwen-image-edit` | 40 | 4 | `euler` | `simple` | 3.1 |
  | `wan22-i2v-14b` | 20 | 5 | `euler` | `simple` | 8 |
  | `wan22-i2v-14b-fast` | 4 | 1 | `euler` | `simple` | 8 |

  Setting a knob the selected flow does not carry fails before anything is
  submitted, with the client's unknown-key error; the run never reaches the
  server. Wan also runs at 24 fps with Wan's own Chinese negative prompt as
  the default, and the rapido draft keeps the same size, length and fps and
  adds `lora_strength` 1.0 for its lightx2v LoRAs.
- The unet, clip, vae and LoRAs load by the filenames of the manifest
  models. The high-noise Wan unet samples the first half of the steps, the
  low-noise unet the second; overriding `steps` keeps that split.

The edit and clip flows list `uploads`: instead of a value they take a local
file. Before filling the graph, the runner posts the piece's `source` — or
each clip entry's first frame — to the server's `/upload/image` endpoint (the
lab's multipart protocol, `overwrite` set) and fills `$image` with the name
the server answers, `subfolder/name` when it names one. One upload serves
every edit entry; a clip uploads once per entry. The run prints
`<file> uploaded as <name>` — the file's name and the name the server stored
— so the log shows what reached the server.

At run start the runner links each facet model into the checkout where
ComfyUI looks — the unet into `models/diffusion_models/`, the clip into
`models/text_encoders/`, the vae into `models/vae/` and each lightx2v LoRA
into `models/loras/` — as symlinks, refreshed on every run. The link target
is the file `facet pull` downloaded under `models/direct`; nothing is copied.

## Assets

One run writes one PNG per entry, each with a record (`kind = "image"`,
`mime = "image/png"`, `seed` the entry's seed, `params` the values actually
used — the flow's defaults merged with the entry, so the sampling knobs and
the negative prompt the flow supplied show too — and `properties` carrying
`width`, `height` and `seed`). A clip run writes one
MP4 per entry instead, with `kind = "video"` and `mime = "video/mp4"`. A
`wan22-i2v-14b-fast` draft writes `<name>-borrador.mp4` and adds
`draft = true` to its properties; every other record keeps `width`,
`height` and `seed` alone. The runner prints one `<name>.png ok` or
`<name>.mp4 ok` line per output, with no absolute path and no timing. An
edit or clip run uploads first, so its log starts with the
`<file> uploaded as <name>` lines and then the `<name>.png ok` or
`<name>.mp4 ok` lines.

## Verification and doctor

`verify` opens every PNG with Pillow and passes when its pixel size equals
the entry's `width` and `height`, reporting both as metrics and thresholds
(`verifier = "pillow"`). A clip's MP4 is probed with the FFmpeg binary that
`imageio-ffmpeg` ships: `verify` reads its resolution and frame rate, counts
its frames and passes when they equal the entry's `width`, `height`, 24 fps
and `length` (`verifier = "ffmpeg"`). A wrong size, a wrong frame rate or an
unreadable file is a failed verdict, never a crash.

`facet preview <name>.png` writes `<name>.png.preview.json` (the `image`
schema) with the name, prompt, seed and measured width and height, and the
image viewer shows the picture itself, click to enlarge. A clip's preview is
the `video` schema: name, prompt, seed, the probed width, height, frame count
as `length`, and `fps`, shown in the video viewer.

`facet doctor comfy-xl` runs the package's checks:

- `gpu` (quick): `nvidia-smi -L` sees an NVIDIA GPU.
- `gpu_free` (quick): no other process holds GPU memory, unless the server
  facet started answers `/system_stats`.
- `models` (quick): the twelve manifest models are present with their byte
  counts.
- `checkout` (quick): the pinned ComfyUI checkout exists with `main.py`.
- `server` (full): the started ComfyUI answers `/system_stats`.

Every pull-fixable failure names `facet pull comfy-xl` as its fix. The facet
readiness gate separately checks the GPU, VRAM, RAM and disk the manifest
declares, and the licence acceptance.

## Licences

The tool is ComfyUI (GPL-3.0-or-later); the runner's own dependencies are
Pillow (MIT-CMU) and imageio-ffmpeg (BSD-2-Clause, the FFmpeg binary `verify`
probes clips with). The twelve manifest models — the Z-Image base unet, its
Qwen3 clip and VAE, the two Wan 2.2 I2V 14B unets (high and low noise), the
UMT5 clip, the Wan 2.1 VAE, the two lightx2v LoRAs, and the Qwen-Image-Edit
unet with its Qwen2.5-VL clip and VAE — are Apache-2.0, commercial use
allowed, and no acceptance is needed.
The manifest records each model's direct URL and sha256, measured from the
lab's clone.

## Machine cost

`requirements` in the manifest: **GPU**, **24 GB VRAM**, **32 GB RAM**,
**95 GB disk**, exclusive (the default) on Linux — one heavy job at a time.
The first `facet pull comfy-xl` clones ComfyUI, builds its venv and
downloads the models; later runs are offline. On an 8 GB card, use `comfy`.
