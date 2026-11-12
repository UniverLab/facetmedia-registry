# Flows

A **flow** is a ComfyUI API graph: a JSON object under `flows/` whose string
inputs written as `"$key"` are placeholders. Before each run the runner fills
them, in order, from the flow's own `params` first and then the piece's entry
(`runner.py::_values` / `_fill`): the entry wins over `params`, and a key
neither provides fails the run. The lab's `tools/comfy.py` called these
`"$clave"` entries; the registry writes `"$key"`.

The package ships five flows, copied from the lab's `tools/comfy/` — all
byte-identical except `flux2-klein-img2img.json`, whose params open to
1344 × 768 (the lab's default 1024 × 1024):

| Flow file | Capability | Models loaded |
|-----------|------------|---------------|
| `z-image-turbo.json` | `still` | Z-Image Turbo unet, Qwen clip, Z-Image VAE |
| `flux2-klein-4b.json` | `still` | FLUX.2 klein 4B unet, Qwen clip, FLUX.2 VAE |
| `flux2-klein-img2img.json` | `edit` | FLUX.2 klein 4B unet, Qwen clip, FLUX.2 VAE |
| `wan22-i2v.json` | `clip` | Wan 2.2 TI2V 5B unet, UMT5 clip, Wan 2.2 VAE |
| `wan22-i2v-fast.json` | `clip` | Wan 2.2 TI2V 5B unet, UMT5 clip, Wan 2.2 VAE, FastWan LoRA |

The unet, clip, vae and LoRA load by the filenames of the manifest models;
the three still and edit flows share the one Qwen clip file (`qwen_3_4b_fp8_mixed.safetensors`,
listed twice in the manifest as `z-image-qwen-clip` and `flux2-qwen-clip`),
while both Wan flows load the one UMT5 clip and VAE and the rapido draft
adds `Wan2_2_5B_FastWanFullAttn_lora_rank_128_bf16.safetensors`.

## Placeholders per flow

- `z-image-turbo`: `$prompt`, `$seed`, `$width`, `$height`, `$name`,
  `$steps`, `$shift`, `$cfg`, `$sampler`, `$scheduler`. Params: width 1344,
  height 768, seed 0, steps 8, shift 3, cfg 1, sampler `res_multistep`,
  scheduler `simple`.
- `flux2-klein-4b`: `$prompt`, `$seed`, `$width`, `$height`, `$name`,
  `$steps`, `$cfg`, `$sampler`. Params: width 1344, height 768, seed 0,
  steps 4, cfg 1, sampler `euler` (klein has no scheduler and no shift).
- `flux2-klein-img2img`: `$prompt`, `$seed`, `$width`, `$height`, `$name`,
  `$steps`, `$cfg`, `$sampler`, `$image`. Params: image `""`, prompt `""`,
  name `"edit"`, width 1344, height 768, seed 0, steps 4, cfg 1, sampler
  `euler`.
- `wan22-i2v`: `$prompt`, `$negative`, `$seed`, `$width`, `$height`,
  `$length`, `$steps`, `$cfg`, `$shift`, `$sampler`, `$scheduler`, `$fps`,
  `$image`, `$name`. Params: width 1280, height 704, length 49, seed 0,
  steps 20, cfg 5, shift 8, sampler `uni_pc`, scheduler `simple`, fps 24,
  and Wan's own Chinese negative prompt as the default.
- `wan22-i2v-fast`: the same placeholders plus `$lora_strength`. Params:
  the same size, length and fps with steps 4, cfg 1, sampler `euler`,
  scheduler `simple` and `lora_strength` 1.0.

`$prompt`, `$seed`, `$width`, `$height`, `$length`, `$name` and the five
sampling knobs come from the entry; `$image` comes from an upload (below);
everything else comes from the flow's `params` unless the entry repeats the
key. The flow's value is therefore the default: a piece that sets no knob
renders exactly as before, and one the selected flow does not carry
(`scheduler` or `shift` on either klein flow) fails with the client's
unknown-key error before the server starts.

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
