---
name: comfy
description: Stills, reference-guided edits and short clips with ComfyUI, checked by pixel size and video probe.
---
# ComfyUI

Turn prompts into still illustrations with the lab's ComfyUI flows, iterate
one by instruction from a reference image, and animate a still into a short
clip. The capabilities write the `image` and `video` kinds and are checked by
pixel size and by probing the MP4.

## When to use

- `comfy.still` for illustration, backgrounds or mood: a scene, an object,
  an editorial drawing, a watercolor. Pick the flow with the piece's
  `workflow` input: `z-image-turbo` (the default) for photographic realism,
  about 8 s per 1344 × 768 image; `flux2-klein-4b` for palette, composition
  and empty space, about 6 s.
- `comfy.edit` to change an image you already have while keeping its framing
  and character: another style, palette or mood. It runs `flux2-klein-img2img`,
  guided by reference image with no denoise slider — reference-guided, not
  strength-guided. About 23 s per 1344 × 768 edit.
- `comfy.clip` to animate what is inside a still — fog advancing, steam
  rising, water rippling. `wan22-i2v` is movement-only: the prompt describes
  what moves inside the frame, never a camera move over a flat image. About
  7 minutes per two-second clip. `wan22-i2v-rapido` is the draft variant,
  about half the time, and it drifts.
- A camera move over a still — a zoom, a pan, a slow push — belongs to
  HyperFrames with GSAP first: seconds instead of minutes, reproducible
  frame by frame. Reach for Wan only when something inside the picture has
  to move. Even then a subtle camera move, even one the prompt names, barely
  registers; do not spend seven minutes on a move GSAP draws in one second.
- Never for anything a person must read. Text, numbers, labels, charts and
  logos belong in HTML or SVG; a generated image carries image content only.

## Pieces

One entry per image, each with its own seed and size:

```toml
[inputs]
image = [
  { name = "fondo-video", prompt = "Misty pine forest at dawn, soft volumetric light through the trees, muted teal and amber palette, large empty area of fog on the left", seed = 11 },
]
```

`width` defaults to 1344 and `height` to 768, each between 64 and 2048 and a
multiple of 64; say both per entry to change the shape. `workflow` picks the
still flow (`"z-image-turbo"` or `"flux2-klein-4b"`) or the clip flow
(`"wan22-i2v"` or `"wan22-i2v-rapido"`); an edit has no `workflow` input —
it always uses `flux2-klein-img2img`. The flow's own parameters (`steps = 8`,
`shift = 3` on z-image-turbo; `steps = 4` on klein) come from
`flows/<name>.json`, not from the piece. Each entry writes `<name>.png` —
or `<name>.mp4` for a clip — beside the piece file, so `--out build/` keeps
generated assets away from sources.

The prompt is English and carries the manifest's guard: a whole word such
as `text`, `label`, `chart`, `title`, `logo` or `sign` fails piece
validation with `invalid_input`. Digits are fine ("85mm lens"). The no-data
rule holds for a still prompt, an edit instruction and a clip's motion
prompt alike: a generated frame carries no lettering either.

## Flows

A **flow** is a ComfyUI API graph whose inputs written as `"$key"` are
filled, in order, from the flow's own `params`, then the entry — the
registry's form of the lab's `"$clave"`. The package ships five, copied from
the lab's `tools/comfy/` — all unchanged except the edit flow, whose params
open to 1344 × 768 (the lab's default 1024 × 1024); `references/flows.md`
documents
each graph's placeholders, params and uploads.

| Flow | Capability | Pick it for |
|------|------------|-------------|
| `z-image-turbo` | `still` | photographic realism, ~8 s |
| `flux2-klein-4b` | `still` | palette, composition and empty space, ~6 s |
| `flux2-klein-img2img` | `edit` | editing a reference image by instruction, ~23 s |
| `wan22-i2v` | `clip` | movement inside a still: fog, steam, ~7 min per 2 s |
| `wan22-i2v-rapido` | `clip` | motion drafts in half the time |

For clips, `length` is frames at 24 fps and must be `4n+1` — 49 ≈ 2 s,
121 ≈ 5 s — because the Wan latent keeps one frame plus groups of four. A
clip is 1280 × 704 at 24 fps and fills the GPU: about 7.8 GB of VRAM and
6.5 GB of RAM, with nothing else on the card. The machine needs 16 GB of
RAM and 40 GB of disk for the pull.

facet treats ComfyUI as an `[engine.server]`: `facet pull comfy` clones the
pinned revision `3c1b7a17fdf239d35ce98cc777756f572d089795`, builds its venv
from `requirements.txt` and downloads the ten models; for the duration of a
verb facet starts

```
python main.py --listen 127.0.0.1 --port <port> --disable-pinned-memory
```

and the runner reaches it through `FACET_SERVER_URL`. `--disable-pinned-memory`
is package-wide, not per-flow: the Wan flow peaked at 18 of 19 GB of RAM
without it, and it changes nothing for the still flows.
`references/server.md` has the full launch and health details;
`references/seeds.md` the seed behavior.

## Drafts

`workflow = "wan22-i2v-rapido"` runs the same Wan graph with FastWan's
`Wan2_2_5B_FastWanFullAttn_lora_rank_128_bf16.safetensors` LoRA, four steps
and a CFG of 1, so a clip takes about half the time. It is a **draft**:
halfway through it drifts from the input image — the light and the
composition change — so it is for trying a movement, never a final render or
a piece of an assembly. The runner names every draft output
`<name>-borrador.mp4` and its record carries `properties.draft = true`, so
no draft passes for a final. Wan2.2-TI2V-5B-Turbo was rejected (no declared
licence) and LTX-2 was rejected (own licence, quantized-only at 8 GB); the
lab's approved draft sample is `examples/bosque-niebla-rapido.mp4`.

## Judging the result

`verify` opens every `<name>.png` with Pillow and passes when its pixel size
equals the entry's `width` and `height`, reporting both. Read the image
preview's `name`, `prompt`, `seed`, `width` and `height`, and open the PNG
in the image viewer to look at it: the size says the flow ran, the picture
says whether the prompt worked. About 8 s per 1344 × 768 image on
z-image-turbo, about 6 s on flux2-klein-4b, about 23 s per edit.

A clip is a `video` kind: each entry writes `<name>.mp4`, and `verify` probes
it with FFmpeg and passes when its resolution, 24 fps and frame count (`49`
by default, about 2 s) equal the entry. In its preview, `length` is the frame
count and `fps` the rate. The lab's verdict on the three approved clips:
`bosque-niebla.mp4` (fog drifting between pine trees) and `taza-vapor.mp4`
(steam rising from a ceramic cup, static camera) are the reliable pair —
something visible inside the frame moves — while `calle-acuarela.mp4`'s slow
pan barely registered. All are in `examples/`, with `comparacion.jpg` for
the two still models and `README-img2img.md` for the edit.

## Licences

The tool is ComfyUI (GPL-3.0-or-later); the runner's own dependencies are
Pillow (MIT-CMU) and imageio-ffmpeg (BSD-2-Clause). The ten manifest models —
the Z-Image Turbo unet, the FLUX.2 klein 4B unet, the Wan 2.2 TI2V 5B unet,
their three VAEs, the Qwen clip the still and edit flows share (one file,
listed for both), the UMT5 clip Wan loads and the FastWan LoRA — are
Apache-2.0, commercial use allowed, and no acceptance is needed. Both still
models and the Wan fp8 unet are Apache-2.0.

## Pitfalls

- One heavy job at a time. Check `nvidia-smi` first: a second model on the
  same GPU overflows memory and takes minutes.
- The ComfyUI checkout and its models come from `facet pull comfy`; a
  missing checkout fails with `facet pull comfy` as its fix.
- Seeds are part of the result: change only the prompt to explore, then keep
  the seed of the image you approved.
- Generated images hold no text or data: no caption, no watermark, no
  numbers inside the picture.
- The edit and clip flows upload the reference or each first frame to the
  server's `/upload/image` before running; the log prints one
  `<file> uploaded as <name>` line per upload.
