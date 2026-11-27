# upscale

Deterministic 2x and 4x image super-resolution using the pinned
[Real-ESRGAN ncnn Vulkan](https://github.com/xinntao/Real-ESRGAN) Linux
release (`v0.2.5.0`, MIT / BSD-3-Clause, zero PyTorch) and Pillow:
`facet run upscale.enhance` upscales one PNG, JPEG, or WebP still to
`<name>.<format>`.

## Capabilities and pieces

`upscale.enhance` — 2x and 4x image super-resolution, image kind:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `image` | path | yes | — | PNG, JPEG, or WebP still, resolved relative to the piece |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.<format>` |
| `scale` | enum | no | `4` | `2` or `4` |
| `model` | enum | no | `realesrgan-x4plus` | `realesrgan-x4plus`, `realesrgan-x4plus-anime`, or `realesr-animevideov3` |
| `format` | enum | no | `png` | `png`, `jpg`, or `webp` |

Both `realesrgan-x4plus` and `realesrgan-x4plus-anime` are 4x-only models.
When `scale = "2"` is requested with either of those models, the runner
upscales 4x to a temporary PNG and downscales with Pillow
`Image.Resampling.LANCZOS` to exact `(width * 2, height * 2)`.
`realesr-animevideov3` runs natively at both `2` and `4`.

## Verification, preview, and doctor

- `verify` re-opens each output with Pillow and checks exact
  `(src_width * scale, src_height * scale)` dimensions, valid format
  matching the suffix, and non-blank pixel extrema.
- `preview` writes `<asset>.preview.json` conforming to
  `schemas/preview/image.schema.json` with
  `prompt = "upscale <scale>x (<model>) of <image-stem>"` and `seed = 0`.
- `doctor`: `quick` checks the pinned zip byte size, extracted binary and
  `models/` directory, and Pillow; `full` upscales a synthetic 16x16 PNG
  to 64x64 in a temporary directory and reports clearly if Vulkan is
  unavailable.

## Bundled examples

- `upscale.enhance` — `examples/enhance.toml`: `facet example upscale.enhance --run`
