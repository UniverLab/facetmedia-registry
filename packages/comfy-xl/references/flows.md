# Flows

A **flow** is a ComfyUI API graph: a JSON object under `flows/` whose string
inputs written as `"$key"` are placeholders. Before each run the runner fills
them, in order, from the flow's own `params` first and then the piece's entry
(`runner.py::_values` / `_fill`): the entry wins over `params`, and a key
neither provides fails the run. The lab's `tools/comfy.py` called these
`"$clave"` entries; the registry writes `"$key"`.

The package ships four flows, derived from the official ComfyUI templates
shipped with the pinned ComfyUI's `comfyui_workflow_templates_json` 0.11.78
— the still and edit sizes open to 1344 × 768 and the clip to 1280 × 704:

| Flow file | Capability | Models loaded |
|-----------|------------|---------------|
| `z-image.json` | `still` | Z-Image base unet, Qwen3 clip, Z-Image VAE |
| `qwen-image-edit.json` | `edit` | Qwen-Image-Edit unet, Qwen2.5-VL clip, Qwen-Image VAE |
| `wan22-i2v-14b.json` | `clip` | Wan 2.2 I2V 14B high- and low-noise unets, UMT5 clip, Wan 2.1 VAE |
| `wan22-i2v-14b-rapido.json` | `clip` | The same, plus the high- and low-noise lightx2v LoRAs |

The unet, clip, vae and LoRAs load by the filenames of the manifest models.

## Placeholders per flow

- `z-image`: `$prompt`, `$seed`, `$width`, `$height`, `$name`, `$steps`,
  `$shift`, `$cfg`. Params: width 1344, height 768, seed 0, steps 25,
  shift 3, cfg 4 (the template's own defaults).
- `qwen-image-edit`: `$prompt`, `$seed`, `$width`, `$height`, `$name`,
  `$steps`, `$cfg`, `$shift`, `$image`. Params: image `""`, prompt `""`, name
  `"edit"`, width 1344, height 768, seed 0, steps 40, cfg 4, shift 3.1. The
  source is scaled to the requested size, VAE-encoded as the edit latent and
  conditioned by `TextEncodeQwenImageEditPlus` reference latents.
- `wan22-i2v-14b`: `$prompt`, `$negative`, `$seed`, `$width`, `$height`,
  `$length`, `$steps`, `$cfg`, `$shift`, `$fps`, `$image`, `$name`. Params:
  width 1280, height 704, length 49, seed 0, steps 20, cfg 5, shift 8,
  fps 24, and Wan's own Chinese negative prompt as the default. The
  high-noise stage samples steps 0–10, the low-noise stage steps 10 to the
  end; overriding `steps` keeps that split.
- `wan22-i2v-14b-rapido`: the same placeholders plus `$lora_strength`.
  Params: the same size, length and fps with steps 4, cfg 1 and
  `lora_strength` 1.0; the high-noise stage samples steps 0–2, the low-noise
  stage steps 2 to the end.

`$prompt`, `$seed`, `$width`, `$height`, `$length` and `$name` come from the
entry; `$image` comes from an upload (below); everything else comes from the
flow's `params` unless the entry repeats the key.

## Uploads

The edit and clip flows declare `uploads` (`["image"]`): instead of a value
they take a local file. Before filling the graph the runner posts the
piece's `source` — or each clip entry's first frame — to the server's
`/upload/image` endpoint (the lab's multipart protocol, `overwrite` set) and
fills `$image` with the name the server answers, `subfolder/name` when it
names one. One upload serves every edit entry; a clip uploads once per
entry. The run prints `<file> uploaded as <name>` — the file's name and the
name the server stored — so the log shows what reached the server.

## Clip length

`length` is frames at 24 fps and must be `4n+1` — 49, 121 — because the Wan
latent keeps one frame plus groups of four. The schema cannot express that,
so piece validation accepts any integer; an off-form length reaches ComfyUI
and fails the run as `runner_failed`.
