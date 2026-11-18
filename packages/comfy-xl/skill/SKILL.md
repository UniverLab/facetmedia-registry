---
name: comfy-xl
description: Stills, reference-guided edits and short clips on a 24 GB GPU with ComfyUI, checked by pixel size and video probe.
---
# ComfyUI XL

Turn prompts into still illustrations with the lab's 24 GB ComfyUI flows,
iterate one by instruction from a reference image, and animate a still into
a short clip. The capabilities write the `image` and `video` kinds and are
checked by pixel size and by probing the MP4.

This package needs a GPU with 24 GB of VRAM: the manifest declares
`vram_gb = 24` and facet refuses a smaller card. The flows mirror the
official ComfyUI templates but have not yet been run on such a GPU by the
lab — they ship marked as not yet run on a 24 GB GPU. On an 8 GB card, use
`comfy` instead.

## When to use

- `comfy-xl.still` for illustration, backgrounds or mood: a scene, an
  object, an editorial drawing, a watercolor. It runs `z-image`, the Z-Image
  base model at full precision — photographic realism, slower than the 8 GB
  turbo, about a minute per 1344 × 768 image.
- `comfy-xl.edit` to change an image you already have while keeping its
  framing and character: another style, palette or mood. It runs
  `qwen-image-edit`, guided by reference image with no denoise slider —
  reference-guided, not strength-guided.
- `comfy-xl.clip` to animate what is inside a still — fog advancing, steam
  rising, water rippling. `wan22-i2v-14b` is movement-only: the prompt
  describes what moves inside the frame, never a camera move over a flat
  image. About 7 minutes per two-second clip. `wan22-i2v-14b-fast` is the
  draft variant, about half the time, and it drifts.
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
  { name = "video-still", prompt = "Misty pine forest at dawn, soft volumetric light through the trees, muted teal and amber palette, large empty area of fog on the left", seed = 11 },
]
```

For a still, `width` defaults to 1344 and `height` to 768, each between 64 and
2048 and a multiple of 64; for `comfy-xl.edit` and `comfy-xl.clip`, omitting
`width`/`height` follows the source's aspect at the flow's pixel count, and a
pair more than 5 % off it is refused — crop the source first for another framing.
`workflow` picks the still flow (`"z-image"`, used when omitted) or the clip flow
(`"wan22-i2v-14b"` or `"wan22-i2v-14b-fast"`, omitting it uses
`"wan22-i2v-14b"`); an edit has no `workflow` input — it always
uses `qwen-image-edit`. Any of the three takes `flow` instead: a path to
the piece's own flow file, exclusive with `workflow`. An entry may also
set `steps`, `cfg`, `sampler`, `scheduler` and `shift`; each defaults to
the flow's own value — the Flows section lists every flow's defaults — so
a piece that sets none renders exactly as before.
Each entry writes `<name>.png` — or `<name>.mp4` for a clip — beside the
piece file, so `--out build/` keeps generated assets away from sources.

The prompt is English and carries the manifest's guard: a whole word from
this list fails piece validation with `invalid_input` — caption, captions,
chart, graph, label, labels, letter, letters, logo, sign, text, title, word,
words. A refused word is refused even negated ("no text") and inside a
phrase ("folded letter"): the pattern scans the words, not the intent.
Digits are fine ("85mm lens"). The no-data rule holds for a still prompt, an
edit instruction and a clip's motion prompt alike: a generated frame carries
no lettering either.

### Edits

`comfy-xl.edit` takes exactly one reference image, `source`, at the
`[inputs]` level — one for the whole piece, not one per entry. Each
`[[inputs.image]]` entry carries its own `name`, `seed`, `width`, `height`
and `prompt`, and never an `image` key (piece validation refuses one):

```toml
[inputs]
source = "reference.png"

[[inputs.image]]
name = "new-material"
seed = 31
width = 1344
height = 768
prompt = "Edit the reference image into brushed copper, keeping the framing, the subject and the large flat shapes"
```

A clip is the mirror image: it takes no `source`, and `image` goes inside
each entry as that clip's first frame — `[[inputs.image]]` with
`image = "video-still.png"` beside its `prompt`, `seed`, `width` and
`height`.

## Prompting

Word order changes the picture: the model weighs the start of the prompt most,
so lead with what matters. The order that works across these flows is
**subject → action or style → context → lighting → camera**. Lighting carries
the most quality weight; name one light and one lens instead of piling on
style words.

`z-image` runs 25 steps at CFG 4, so guidance is real — but no negative input
is exposed, and an "avoid X" clause still has nowhere to go. Write the
positive form of every avoidance: "sharp focus" for no blur, "neutral
backdrop" for no clutter, "window light from the side" for no flat light.
Lock the seed and change exactly one dial per run (steps, CFG or one prompt
clause) to learn what the prompt is doing; run three seeds and keep the best.

For an edit, write the instruction in three parts — **target, change,
preservation** — in one sentence or three: "Replace the jacket's colour with
deep indigo. Preserve its cut, folds, lighting and position. Keep the face,
background and camera framing unchanged." One operation per run: a second
change applied on top of the first compounds drift. If unrelated detail moves,
restart from the original reference, never from the damaged output.

For a clip, describe motion, not content: **subject → motion → camera →
scene**. Name the movement with concrete verbs, one scene per clip, and only
what is visible in the first frame — the image already decides what appears.
Keep "static, still image, frozen, motionless, no movement" in a custom
negative. On `wan22-i2v-14b-fast`, CFG 1 makes the negative inert, so a fast
draft tells you nothing about prompt-following.

facet's no-lettering rule is a deliberate product divergence, not a model
limit: the frames carry no type, so public advice about quoted brand words and
hex colours does not apply here. `references/prompting.md` has the full
skeletons and cue lists.

## Flows

A **flow** is a ComfyUI API graph whose inputs written as `"$key"` are
filled, in order, from the flow's own `params`, then the entry — the
registry's form of the lab's `"$clave"`. The package ships four, derived
from the official ComfyUI templates shipped with the pinned ComfyUI's
`comfyui_workflow_templates_json` 0.11.78 — the still size opens to
1344 × 768 and the clip to 1280 × 704; `references/flows.md` documents
each graph's placeholders, params and uploads.

| Flow | Capability | Pick it for |
|------|------------|-------------|
| `z-image` | `still` | photographic realism at full precision, ~1 min |
| `qwen-image-edit` | `edit` | editing a reference image by instruction |
| `wan22-i2v-14b` | `clip` | movement inside a still: fog, steam, ~7 min per 2 s |
| `wan22-i2v-14b-fast` | `clip` | motion drafts in half the time |

Each flow's sampling knobs and their defaults. An entry may set any of the
five on any flow and wins over the flow; omitting one keeps this value, so a
piece that sets none renders exactly as before:

| Flow | `steps` | `cfg` | `sampler` | `scheduler` | `shift` |
|------|---------|-------|-----------|-------------|---------|
| `z-image` | 25 | 4 | `res_multistep` | `simple` | 3 |
| `qwen-image-edit` | 40 | 4 | `euler` | `simple` | 3.1 |
| `wan22-i2v-14b` | 20 | 5 | `euler` | `simple` | 8 |
| `wan22-i2v-14b-fast` | 4 | 1 | `euler` | `simple` | 8 |

For clips, `length` is frames at 24 fps and must be `4n+1` — 49 ≈ 2 s,
121 ≈ 5 s — because the Wan latent keeps one frame plus groups of four. A
clip is 1280 × 704 at 24 fps and fills the GPU. The machine needs 32 GB of
RAM and 95 GB of disk for the pull.

facet treats ComfyUI as an `[engine.server]`: `facet pull comfy-xl` clones
the pinned revision `3c1b7a17fdf239d35ce98cc777756f572d089795`, builds its
venv from `requirements.txt` and downloads the twelve models; for the
duration of a verb facet starts

```
python main.py --listen 127.0.0.1 --port <port> --disable-pinned-memory
```

and the runner reaches it through `FACET_SERVER_URL`. `--disable-pinned-memory`
is package-wide, not per-flow. `references/server.md` has the full launch
and health details; `references/seeds.md` the seed behavior.

## Your own flow

A still, an edit or a clip can run the piece's own flow file instead of a
package flow: `flow = "own-flow.json"` in `[inputs]`, resolved relative
to the piece. The file has the package shape — `about`, `params` with the
defaults, and `graph` with `"$key"` placeholders — and an edit or clip flow
keeps `"uploads": ["image"]`, or the reference never reaches the server.
Copy a package flow from `packages/comfy-xl/flows/`; `examples/own-flow.toml`
runs such a copy of `z-image` with steps 30. `flow` and `workflow`
together fail before the server starts. Every model file the graph names
(any `*_name` loader input) must be one of the manifest's pinned files, or
the run fails naming it and listing the allowed ones. Unknown node classes
fail with ComfyUI's own error; facet installs no custom nodes. VRAM is the
author's: a 24 GB card runs the package flows.

When you author an edit graph, derive the sampler's latent from the scaled
source rather than from an empty latent at another size: an edit inherits its
geometry from the reference, and a mismatched empty latent silently
resynthesises a plastic-looking image instead of failing. Validate node
schemas with `/object_info`, match IMAGE (`[B,H,W,C]` float) against MASK
(`[B,H,W]`) across every link, and keep a save or preview sink on the terminal
node.

## Drafts

`workflow = "wan22-i2v-14b-fast"` runs the same two-stage Wan graph with
the two lightx2v 4-step LoRAs (`wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise`
and `..._low_noise`), four steps and a CFG of 1, so a clip takes about half
the time. It is a **draft**: halfway through it drifts from the input image
— the light and the composition change — so it is for trying a movement,
never a final render or a piece of an assembly. The runner names every draft
output `<name>-borrador.mp4` and its record carries `properties.draft = true`,
so no draft passes for a final.

## Judging the result

`verify` opens every `<name>.png` with Pillow and passes when its pixel size
equals the entry's `width` and `height`, reporting both. Read the image
preview's `name`, `prompt`, `seed`, `width` and `height`, and open the PNG
in the image viewer to look at it: the size says the flow ran, the picture
says whether the prompt worked.

A clip is a `video` kind: each entry writes `<name>.mp4`, and `verify` probes
it with FFmpeg and passes when its resolution, 24 fps and frame count (`49`
by default, about 2 s) equal the entry. In its preview, `length` is the frame
count and `fps` the rate.

## Licences

The tool is ComfyUI (GPL-3.0-or-later); the runner's own dependencies are
Pillow (MIT-CMU) and imageio-ffmpeg (BSD-2-Clause). The twelve manifest
models — the Z-Image base unet, its Qwen3 clip and VAE, the two Wan 2.2 I2V
14B unets (high and low noise), their UMT5 clip, the Wan 2.1 VAE, the two
lightx2v LoRAs, and the Qwen-Image-Edit unet with its Qwen2.5-VL clip and
VAE — are Apache-2.0, commercial use allowed, and no acceptance is needed.

## Pitfalls

- One heavy job at a time. Check `nvidia-smi` first: a second model on the
  same GPU overflows memory and takes minutes.
- The ComfyUI checkout and its models come from `facet pull comfy-xl`; a
  missing checkout fails with `facet pull comfy-xl` as its fix.
- Seeds are part of the result: change only the prompt to explore, then keep
  the seed of the image you approved.
- All four flows carry the five sampling knobs, so any of them may be set on
  any entry; one a selected flow lacks would fail with the client's
  unknown-key error before the server starts.
- Generated images hold no text or data: no caption, captions, chart, graph,
  label, labels, letter, letters, logo, sign, text, title, word, words — even
  negated ("no text") or inside a phrase ("folded letter"). The prompt
  pattern refuses those words anywhere, any case; digits stay allowed, so
  "85mm lens" passes.
- The edit and clip flows upload the reference or each first frame to the
  server's `/upload/image` before running; the log prints one
  `<file> uploaded as <name>` line per upload.

Sources for these rules, with their licences, are in
`skill/references/sources.md`.
