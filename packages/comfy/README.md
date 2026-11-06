# comfy

Stills, reference-guided edits and clips with ComfyUI: `facet run comfy.still
<piece.toml>` turns each `[[inputs.image]]` entry into `<name>.png` beside the
piece file, `facet run comfy.edit <piece.toml>` does the same from one
reference image, changing it by instruction, and `facet run comfy.clip
<piece.toml>` animates a still into `<name>.mp4`. All three belong to the
**`image`** facet; the first two write the **`image`** kind and show through
the image viewer, the clip writes the **`video`** kind and shows through the
video viewer. A GPU is required: one model at a time, about 8 s per
1344 × 768 image on z-image-turbo, about 6 s on flux2-klein-4b, about 23 s
per edit, and about 7 minutes per two-second clip on wan22-i2v, about half
that on its `wan22-i2v-rapido` draft variant.

ComfyUI is the lab's own tool (`~/Projects/open-source/ComfyUI`, 0.39.2) and
facet treats it as an `[engine.server]`: `facet pull comfy` clones the pinned
revision `3c1b7a17fdf239d35ce98cc777756f572d089795` into the facet home,
builds its venv from its `requirements.txt`, and downloads the ten models
next to it. For the duration of a verb facet starts
`main.py --listen 127.0.0.1 --port <free> --disable-pinned-memory`; the
runner reaches it through `FACET_SERVER_URL`. The flag is package-wide: the
Wan flow peaked at 18 of 19 GB of RAM without it, and it changes nothing for
the still flows. Nothing is installed globally.

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

## Clips

`comfy.clip` animates a still: each entry carries its own `image`, the clip's
first frame, and a prompt in English that describes what moves. It writes an
MP4, the `video` kind, and is the one capability here for motion **inside**
the frame.

**Draft first.** A camera move over a still — a zoom, a pan, a slow push from
a flat image — belongs to HyperFrames with GSAP: seconds instead of minutes,
and reproducible frame by frame. Reach for Wan only when something inside
the picture has to move: fog advancing, steam rising, water rippling, light
drifting. Even then the motion guidance is narrow: steam and fog read clearly
in a two-second clip, while a subtle camera move, even one the prompt names,
barely registers. Do not spend seven minutes on a move GSAP draws in one
second.

The fields below are what `facet describe comfy.clip --json` reports.

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
| `workflow` | enum | no | `"wan22-i2v"` | `"wan22-i2v"`, or `"wan22-i2v-rapido"` for a draft-only clip |

The length must be `4n+1` frames — 49, 121 — because the Wan latent keeps one
frame plus groups of four. The schema cannot express that, so piece validation
accepts any integer; an off-form length reaches ComfyUI and fails the run as
`runner_failed`. The clip is 1280 × 704 at 24 fps.

```toml
[inputs]
workflow = "wan22-i2v"
image = [
  { name = "bosque-niebla", image = "fondo-video.png", seed = 51, prompt = "Fog drifting slowly between the pine trees at dawn, soft light rays shifting through the mist, very slow camera push in, calm and quiet, cinematic" },
]
```

Each entry's first frame is uploaded on its own: the runner posts it to
`/upload/image` (the same multipart protocol as an edit) and fills `$image`
with the name the server answers, so one piece can animate several different
stills. The log prints one `<file> uploaded as <name>` line per entry.

The lab approved three clips
(`projects/prueba-video-ia/clips.toml`), two seconds each at 1280 × 704,
about seven minutes per clip on a fully used GPU: `bosque-niebla.mp4` (fog
drifting between pine trees), `taza-vapor.mp4` (steam rising from a ceramic
cup, static camera) and `calle-acuarela.mp4` (a slow pan along a watercolor
street). The forest and the cup are the reliable pair: something visible
inside the frame moves.

### Drafts

`workflow = "wan22-i2v-rapido"` runs the same Wan graph with FastWan's
`Wan2_2_5B_FastWanFullAttn_lora_rank_128_bf16.safetensors` LoRA, four steps
and a CFG of 1, so a clip takes about half the time. It is a **draft**:
halfway through it drifts from the input image — the light and the
composition change — so it is for trying a movement, never a final render or
a piece of an assembly. The runner names every draft output
`<name>-borrador.mp4` and its record carries `properties.draft = true`, so
no draft passes for a final. The lab's approved sample is
`projects/prueba-video-ia/bosque-niebla-rapido.mp4`.

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
piece's `workflow` input picks one of the two still flows, the clip's picks
`wan22-i2v` or its `wan22-i2v-rapido` draft, and an edit always uses
`flux2-klein-img2img`. The package ships five, copied from the lab's
`tools/comfy/` — all unchanged except the edit flow, whose params open to
1344 × 768 (the lab's default 1024 × 1024):

| Flow | Models | Capability | Pick it for |
|------|--------|------------|-------------|
| `z-image-turbo` | Z-Image Turbo unet, the shared Qwen clip, the Z-Image VAE | `still` | photographic realism |
| `flux2-klein-4b` | FLUX.2 klein 4B unet, the shared Qwen clip, the FLUX.2 VAE | `still` | palette, composition and empty space |
| `flux2-klein-img2img` | FLUX.2 klein 4B unet, the shared Qwen clip, the FLUX.2 VAE | `edit` | editing a reference image by instruction |
| `wan22-i2v` | Wan 2.2 TI2V 5B unet, the UMT5 clip, the Wan 2.2 VAE | `clip` | movement inside a still: fog, steam, a slow push in |
| `wan22-i2v-rapido` | Wan 2.2 TI2V 5B unet, the UMT5 clip, the Wan 2.2 VAE, the FastWan LoRA | `clip` | motion drafts in half the time |

- `$prompt`, `$seed`, `$width`, `$height` and `$name` come from the entry;
  the edit and clip flows add `$image`, the uploaded reference or first frame,
  and the clip flow also takes `$length`.
- `$steps` and `$shift` come from the flow's `params`; klein has no
  `$shift` (its params are width 1344, height 768, seed 0, steps 4). Wan's
  params are width 1280, height 704, length 49, steps 20, cfg 5, shift 8 and
  24 fps, with Wan's own Chinese negative prompt as the default. The rapido
  draft keeps the same size, length and fps with steps 4, cfg 1 and
  `lora_strength` 1.0 for its FastWan LoRA.
- The unet, clip, vae and LoRA load by the filenames of the manifest models;
  the three still and edit flows share the one Qwen clip file, while both
  Wan flows load the one UMT5 clip and VAE and the rapido draft adds the
  FastWan LoRA.

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
`models/text_encoders/`, the vae into `models/vae/` and the FastWan LoRA into
`models/loras/` — as symlinks, refreshed on every run. The link target is
the file `facet pull` downloaded under `models/direct`; nothing is copied.

## Assets

One run writes one PNG per entry, each with a record (`kind = "image"`,
`mime = "image/png"`, `seed` the entry's seed, `params` the entry, and
`properties` carrying `width`, `height` and `seed`). A clip run writes one
MP4 per entry instead, with `kind = "video"` and `mime = "video/mp4"`. A
`wan22-i2v-rapido` draft writes `<name>-borrador.mp4` and adds `draft = true`
to its properties; every other record keeps `width`, `height` and `seed`
alone. The runner prints one `<name>.png ok` or `<name>.mp4 ok` line per
output, with no absolute path and no timing. An edit or clip run uploads
first, so its log starts with the `<file> uploaded as <name>` lines and then
the `<name>.png ok` or `<name>.mp4 ok` lines.

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

`facet doctor comfy` runs the package's checks:

- `gpu` (quick): `nvidia-smi -L` sees an NVIDIA GPU.
- `gpu_free` (quick): no other process holds GPU memory, unless the server
  facet started answers `/system_stats`.
- `models` (quick): the ten manifest models are present with their byte
  counts.
- `checkout` (quick): the pinned ComfyUI checkout exists with `main.py`.
- `server` (full): the started ComfyUI answers `/system_stats`.

Every pull-fixable failure names `facet pull comfy` as its fix. The facet
readiness gate separately checks the GPU, RAM and disk the manifest
declares, and the licence acceptance.

## Licences

The tool is ComfyUI (GPL-3.0-or-later); the runner's own dependencies are
Pillow (MIT-CMU) and imageio-ffmpeg (BSD-2-Clause, the FFmpeg binary `verify`
probes clips with). The ten manifest models — the Z-Image Turbo unet, the
FLUX.2 klein 4B unet, the Wan 2.2 TI2V 5B unet, their three VAEs, the Qwen
clip the still and edit flows share (one file, listed for both), the UMT5
clip Wan loads and the FastWan LoRA — are Apache-2.0, commercial use allowed,
and no acceptance is needed.
The manifest records each model's direct URL and sha256, measured from the
lab's clone.

## Machine cost

`requirements` in the manifest: **GPU**, **16 GB RAM**, **40 GB disk**,
exclusive (the default) on Linux — one heavy job at a time. The first `facet
pull comfy` clones ComfyUI, builds its venv and downloads about 34.3 GB of
models (the shared Qwen clip downloads once); later runs are offline. A still
or an edit fits the 8 GB reference GPU with room to spare; a clip fills it,
about 7.8 GB of VRAM and 6.5 GB of RAM, so nothing else may hold the GPU.
