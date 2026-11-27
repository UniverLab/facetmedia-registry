---
name: upscale
description: Deterministic 2x and 4x image super-resolution using Real-ESRGAN ncnn Vulkan and Pillow without PyTorch.
---
# upscale

`upscale.enhance` turns a low-resolution PNG, JPEG, or WebP still into a
sharper 2x or 4x image using the pinned `realesrgan-ncnn-vulkan` Linux
binary (46.9 MB zip, zero PyTorch) and Pillow.

## When to use

- When an existing PNG, JPEG, or WebP still is too small for print,
  slides, or video frames and needs clean 2x or 4x super-resolution.
- When you want deterministic enhancement without installing PyTorch or
  CUDA toolkits (`realesrgan-ncnn-vulkan` uses Vulkan/ncnn).
- Use `realesrgan-x4plus` (default) for photos and realistic renders,
  `realesrgan-x4plus-anime` for anime and flat illustrations, and
  `realesr-animevideov3` for fast native 2x/4x upscaling.

## Pieces

```toml
capability = "upscale.enhance"

[inputs]
image = "fixture.png"
name = "fixture-4x"
scale = "4"
model = "realesrgan-x4plus"
format = "png"
```

- `image` (path, required): local PNG, JPEG, or WebP still resolved
  relative to the piece file.
- `name` (string, required, `^[a-z0-9][a-z0-9-]*$`): output asset base
  name; writes `<name>.<format>`.
- `scale` (`"2"` or `"4"`, default `"4"`): target scale factor.
- `model` (`"realesrgan-x4plus"`, `"realesrgan-x4plus-anime"`, or
  `"realesr-animevideov3"`, default `"realesrgan-x4plus"`).
- `format` (`"png"`, `"jpg"`, or `"webp"`, default `"png"`).

Note: `realesrgan-x4plus` and `realesrgan-x4plus-anime` only have 4x
weights. Requesting `scale = "2"` with them runs 4x first and downscales
with Pillow Lanczos (`Image.Resampling.LANCZOS`) to exact 2x dimensions.

## Judging the result

`verify` checks that every output opens cleanly in Pillow, matches the
expected format, has non-blank pixel extrema, and has exact
`(src_width * scale, src_height * scale)` dimensions. `preview` writes
`schemas/preview/image.schema.json` metadata with
`prompt = "upscale <scale>x (<model>) of <stem>"` and `seed = 0`.

`facet doctor upscale` checks the pinned zip, extracted binary and
`models/` directory, and Pillow at `quick` depth, and runs a 16x16 to
64x64 Vulkan upscale at `full` depth.

## Pitfalls

- **Vulkan required at runtime.** Headless machines without a Vulkan ICD
  fail `doctor --depth full` and `run`; check `facet doctor upscale`
  before batching jobs.
- **JPEG drops alpha.** Choosing `format = "jpg"` flattens/converts
  alpha channels to RGB; use `png` or `webp` to preserve transparency.
- **4x-only models at 2x.** Expect a brief 4x intermediate pass when
  combining `scale = "2"` with `realesrgan-x4plus` or
  `realesrgan-x4plus-anime`.

Sources and licences are listed in `skill/references/sources.md`.
