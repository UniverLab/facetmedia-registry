---
name: comfy
description: Stills from prompts and reference-guided edits with ComfyUI, checked by pixel size.
---
# ComfyUI

Turn prompts into still illustrations with the lab's z-image-turbo flow on
ComfyUI, and iterate one by instruction from a reference image. The
capabilities write the `image` kind and are checked by pixel size.

## When to use

- `comfy.still` for illustration, backgrounds or mood: a scene, an object,
  an editorial drawing, a watercolor.
- `comfy.edit` to change an image you already have while keeping its framing
  and character: another style, palette or mood. It is guided by reference
  image and has no denoise slider.
- Never for anything a person must read. Text, numbers, labels, charts and
  logos belong in HTML or SVG; a generated image carries image content only.

## Pieces

One entry per image, each with its own seed and size:

```toml
[inputs]
image = [
  { name = "fondo-video", prompt = "Misty pine forest at dawn, soft volumetric light through the trees, muted teal and amber palette, large empty area of fog on the left", seed = 11 },
  { name = "foto-producto", prompt = "Studio product photograph of a handmade matte ceramic coffee cup on a raw concrete surface, soft window light from the left, shallow depth of field, 85mm lens", seed = 13 },
]
```

`width` defaults to 1344 and `height` to 768, each between 64 and 2048 and a
multiple of 64; say both per entry to change the shape. The flow's own
parameters (`steps = 8`, `shift = 3`) come from `flows/z-image-turbo.json`,
not from the piece. Each entry writes `<name>.png` beside the piece file, so
`--out build/` keeps generated stills away from sources.

The prompt is English and carries the manifest's guard: a whole word such
as `text`, `label`, `chart`, `title`, `logo` or `sign` fails piece
validation with `invalid_input`. Digits are fine ("85mm lens").

## Judging the result

`verify` opens every `<name>.png` with Pillow and passes when its pixel size
equals the entry's `width` and `height`, reporting both. Read the image
preview's `name`, `prompt`, `seed`, `width` and `height`, and open the PNG
in the image viewer to look at it: the size says the flow ran, the picture
says whether the prompt worked. About 8 s per 1344 × 768 image.

## Pitfalls

- One heavy job at a time. Check `nvidia-smi` first: a second model on the
  same GPU overflows memory and takes minutes.
- The ComfyUI checkout and its models come from `facet pull comfy`; a
  missing checkout fails with `facet pull comfy` as its fix.
- Seeds are part of the result: change only the prompt to explore, then keep
  the seed of the image you approved.
- Generated images hold no text or data: no caption, no watermark, no
  numbers inside the picture.
