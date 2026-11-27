# deepfilter — neural voice noise suppression

`facet run deepfilter.enhance` suppresses the background noise of a voice
clip with [DeepFilterNet3](https://github.com/Rikorose/DeepFilterNet)
(**MIT**) and writes `<name>.wav`: 48 kHz mono, neural, on CPU. One
capability, `deepfilter.enhance`, in the **`audio`** facet, writing the
**`audio`** kind. The DeepFilterNet3 license is **MIT** with commercial use
allowed and no acceptance step.

## The pinned binary

DeepFilterNet3 ships as a static musl binary holding the neural net — no
PyTorch, no GPU, no system toolchain — and the manifest pins that exact
file:

| Field | Value |
|-------|-------|
| `id` | `deep-filter-0.5.6-linux-x86_64` |
| `url` | `https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-x86_64-unknown-linux-musl` |
| `sha256` | `70775e251eee44c0f2451a1e833326cf8bcbbe304d3e7cd12851e6fce72ef7da` |
| `bytes` | `36417296` |
| `path` | `deep-filter-0.5.6-linux-x86_64/deep-filter` |
| `spdx` | `MIT` |

`facet pull deepfilter` streams the binary into `models/direct/` under that
`path` and verifies the sha256 before it lands. The runner makes it
executable (`chmod 0o755`) when the pull laid it down read-only, then shells
out to it. The manifest declares no `[engine.binary]`.

## Why a python-env engine and not `[engine.binary]`

facet's `[engine.binary]` packages assume the tool speaks the runner
protocol — `run --input <request> --result <result>`. `deep-filter` does
not: its argv is `deep-filter -D -a <db> [--pf] -o <dir> <wav>`, an
unrelated command line with its own flags. So the package is a
**python-env** subprocess client: `runner.py` owns the four verbs, resolves
the pinned binary through `req.model_path(...)`, decodes the input with the
bundled imageio-ffmpeg binary, and shells out to `deep-filter`. The signal
measurements live in the registry's `lib/audiopreview.py`, copied into the
environment as `facet_lib.audiopreview` (`uses = ["audiopreview"]` in the
manifest).

## The command

Every run is the same argv, in this order:

```
deep-filter -D -a <atten-lim-db> [--pf] -o <tmp_out_dir> <tmp_in_wav>
```

`deep-filter` writes the enhanced WAV inside `<tmp_out_dir>` beside the
input's file name; the runner takes that file (falling back to the single
`.wav` in the directory) and moves it to the job out dir as `<name>.wav`.

## Piece fields

The fields below are what `facet describe deepfilter.enhance --json`
reports for this manifest.

`deepfilter.enhance` — suppress noise in a voice clip with the
DeepFilterNet3 neural denoiser at 48 kHz:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `audio` | path | yes | — | source audio or video the bundled FFmpeg decodes |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.wav` |
| `channel` | enum | no | `auto` | `auto`, `mix`, `left`, `right` |
| `atten-lim-db` | number | no | `100.0` | 0 to 100, maximum noise attenuation in dB |
| `post-filter` | boolean | no | `true` | extra attenuation of residual noise |

The chain the lab runs on a noisy take is `deepfilter.enhance` →
`ffmpeg.normalize` (loudness target) → `video-ops.mux-audio` (voice back
under the picture). Neural denoising is not loudness: the output keeps
roughly the input's level, so always follow with `ffmpeg.normalize` when a
platform target applies.
