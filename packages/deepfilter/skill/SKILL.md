---
name: deepfilter
description: Suppress noise in a voice clip with the DeepFilterNet3 neural denoiser at 48 kHz, with verified duration, peak and loudness.
---
# deepfilter

`deepfilter.enhance` takes a recorded voice clip — or the audio track of a
video — and suppresses its background noise with the pinned DeepFilterNet3
static binary, writing one 48 kHz mono `<name>.wav`. No PyTorch, no GPU: the
binary carries the neural net and runs on CPU. One capability, one `audio`
asset, previewed through the audio viewer.

## When to use

- A **voice take has audible background noise**: room tone, hiss, hum, street
  rumble. `deepfilter.enhance` is the lab's neural route to a clean voice;
  `ffmpeg.clean` only applies the classic spectral denoise, high-pass and
  loudness normalisation.
- The recording chain is unknown: `enhance` decodes any format the bundled
  FFmpeg reads and picks the live channel automatically (`auto` keeps
  1-channel mono untouched, picks `left` or `right` when the stereo L/R RMS
  differs by 18 dB or more, and otherwise downmixes to mono).
- It **does not set loudness**: chain `deepfilter.enhance` →
  `ffmpeg.normalize` to bring the denoised voice to a loudness target, and
  `video-ops.mux-audio` to lay the result back under a video.

## Pieces

Enhance the lab's fixture voice clip, letting the channel be picked
automatically (`examples/enhance.toml`):

```toml
capability = "deepfilter.enhance"

[inputs]
audio = "voice-noisy.wav"
name = "voice-denoised"
```

Both `audio` and `name` are required and resolve relative to the piece.
`audio` is any local audio or video file the bundled FFmpeg decodes; `name`
is the asset base name (`[a-z0-9][a-z0-9-]*`) and the run writes
`<name>.wav`. Optional: `channel` (`auto`, `mix`, `left`, `right`;
default `auto`), `atten-lim-db` (maximum noise attenuation in dB, 0–100,
default 100.0, passed as `-a`), `post-filter` (extra attenuation of
residual noise, default true, passed as `--pf`).

The chain the lab runs on a noisy take is enhance, then normalise, then mux:

```toml
capability = "deepfilter.enhance"

[inputs]
audio = "take1.mp4"
name = "take1-denoised"
atten-lim-db = 100.0
post-filter = true
```

then `ffmpeg.normalize` on `take1-denoised.wav` to the platform's loudness
target, then `video-ops.mux-audio` to put the voice back under the picture.

## Judging the result

The run records `duration_s`, `sample_rate_hz`, `channels`, `lufs` and
`peak_dbfs` on the asset. `verify` passes the asset when the output is a
non-zero WAV at 48000 Hz, its duration stays within 0.15 s of the source's,
its peak sits at or under 0.0 dBFS, and its integrated loudness is finite
(a silent output measures non-finite). The preview is the `audio` preview
(`<name>.wav.preview.json` with the waveform, loudness and silences), as
`schemas/preview/audio.schema.json` fixes it. The doctor proves the binary
answers `--help` at `quick` depth and enhances a 1 s synthetic noisy clip
at `full` depth.

## Pitfalls

- Neural denoising is not loudness: the output keeps roughly the input's
  level, so always follow with `ffmpeg.normalize` when a platform target
  applies — never raise the denoised clip to a speech target by hand gain.
- `atten-lim-db` below 100 leaves more of the original bed audible; that is
  a choice, not a failure, and `verify` does not judge it.
- Turning `post-filter` off keeps more high-frequency breath at the cost of
  more residual hiss; leave it on unless the voice sounds gated.
- The binary is Linux-only and CPU-only: there is no GPU path and no other
  platform, so `facet pull deepfilter` on anything else fails at the
  manifest's `platforms` gate.
- Full guidance with sources: `references/sources.md`.
