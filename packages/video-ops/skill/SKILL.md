---
name: video-ops
description: Deterministic CPU video editing with bundled FFmpeg: transcode, mux, frames, concat, subtitles, grading, overlays, speed, reframe, jumpcut, and stylized FX.
---
# Video Ops

Post-process existing video clips deterministically on CPU using the static
FFmpeg binary bundled by `imageio-ffmpeg`: `video-ops.transcode` encodes
web-ready H.264/AAC MP4 (`libx264`, `yuv420p`, `aac`) with `+faststart`, optional downscaling, frame-rate
capping, and trimming; `video-ops.mux-audio` swaps in a cleaned audio track
without re-encoding the video stream; `video-ops.frame` extracts a PNG or JPG
thumbnail frame at a chosen timestamp; `video-ops.concat` joins 2+ clips with
`xfade` visual transitions and `acrossfade` audio crossfades (or a hard cut);
`video-ops.burn-subs` burns `.srt`/`.vtt` subtitles into video via the FFmpeg
`subtitles` (libass) filter; `video-ops.grade` applies deterministic `eq`
color grading with optional fade-in/fade-out; `video-ops.overlay` composites
a PNG logo, alpha MOV, or PiP clip over base footage; `video-ops.speed`
changes playback speed with synchronized audio; and `video-ops.reframe`
reframes footage to vertical or square via center crop or blurred pillarbox.

## When to use

- When a **rendered or recorded video** needs web-compatible H.264/AAC MP4
  encoding, smaller dimensions (`max-width`), lower frame rate (`fps`), or
  trimming (`start-s` / `end-s`): use `video-ops.transcode`.
- When you already have a **good video stream and a cleaned voice/mix audio
  clip** (for example from `ffmpeg.clean` or `ffmpeg.mix`) and want to combine
  them without losing video quality or spending CPU re-encoding video: use
  `video-ops.mux-audio`.
- When you need a **thumbnail or still frame** from a video at a specific
  timestamp: use `video-ops.frame`.
- When you need to **join clips with transitions** (intro/outro, scene changes):
  use `video-ops.concat`. A common chain is `hyperframes` intro/outro clips +
  `video-ops.concat` + `whisper-subs` transcript shaping + `video-ops.burn-subs`
  to produce a finished captioned video.
- When you have **SRT/VTT subtitles** (for example from `whisper-subs`) and
  need them permanently burned into the video: use `video-ops.burn-subs`.
- When a video needs **deterministic color correction** (brightness, contrast,
  saturation, gamma) or simple fade-in/fade-out: use `video-ops.grade`.
- When a **logo, alpha animation, or PiP clip** must be composited over base
  footage at a corner, center, or fullscreen: use `video-ops.overlay`.
- When footage must run **faster (timelapse) or slower (slow-motion)** with
  audio kept in sync: use `video-ops.speed`.
- When landscape footage must be delivered **vertical (9:16, 4:5) or square
  (1:1)** via center crop or a blurred pillarbox backdrop: use
  `video-ops.reframe`.
- When a talking-head or screencast recording has **silence or dead air** that
  should be automatically cut with a verifiable `.cuts.json` EDL sidecar: use
  `video-ops.jumpcut`.
- When footage needs **stylized visual finishes** (film grain, chromatic
  aberration, halation, scanlines, vignette, or seeded glitch pulses) via
  curated presets or explicit overrides: use `video-ops.fx`.
- It **does not generate video, transcribe audio, or clean audio**: use
  `comfy`, `hyperframes`, `demostage`, `whisper-subs`, or `ffmpeg` for those
  steps first.

## Pieces

Transcode a clip to H.264/AAC MP4 with CRF 24 and `+faststart`
(`examples/transcode.toml`):

```toml
capability = "video-ops.transcode"

[inputs]
video = "fixture.mp4"
name = "fixture-transcoded"
crf = 24
audio-bitrate-kbps = 128
```

Replace a video's audio track without re-encoding video
(`examples/mux-audio.toml`):

```toml
capability = "video-ops.mux-audio"

[inputs]
video = "fixture.mp4"
audio = "fixture.wav"
name = "fixture-muxed"
audio-bitrate-kbps = 128
```

Extract a PNG frame at 0.5 s (`examples/frame.toml`):

```toml
capability = "video-ops.frame"

[inputs]
video = "fixture.mp4"
name = "fixture-frame"
at-s = 0.5
format = "png"
```

Join two clips with a 0.5 s fade transition (`examples/concat.toml`):

```toml
capability = "video-ops.concat"

[[inputs.clip]]
video = "fixture.mp4"

[[inputs.clip]]
video = "fixture.mp4"

[inputs]
name = "fixture-concat"
transition = "fade"
transition-s = 0.5
fps = 30
crf = 23
```

Burn SRT subtitles into a video (`examples/burn-subs.toml`):

```toml
capability = "video-ops.burn-subs"

[inputs]
video = "fixture.mp4"
subtitles = "sample.srt"
name = "fixture-subs"
font-size = 22
margin-v = 36
crf = 23
```

Apply color grading with fades (`examples/grade.toml`):

```toml
capability = "video-ops.grade"

[inputs]
video = "fixture.mp4"
name = "fixture-graded"
brightness = 0.0
contrast = 1.05
saturation = 1.1
gamma = 1.0
fade-in-s = 0.2
fade-out-s = 0.2
crf = 23
```

Composite a PNG logo centered over base footage (`examples/overlay.toml`):

```toml
capability = "video-ops.overlay"

[inputs]
base = "fixture.mp4"
overlay = "logo.png"
name = "fixture-overlay"
position = "center"
crf = 23
```

Double playback speed keeping audio in sync (`examples/speed.toml`):

```toml
capability = "video-ops.speed"

[inputs]
video = "fixture.mp4"
name = "fixture-speed"
factor = 2.0
keep-audio = true
crf = 23
```

Reframe landscape footage to vertical 9:16 (`examples/reframe.toml`):

```toml
capability = "video-ops.reframe"

[inputs]
video = "fixture.mp4"
name = "fixture-reframe"
aspect = "9:16"
mode = "crop"
width = 1080
crf = 23
```

Note that `max-width` in `video-ops.transcode` only downscales sources wider
than `max-width` (`scale='min(iw,<w>)':-2`); narrower sources keep their
original width, and `-2` keeps height divisible by 2 for `yuv420p`. `start-s`
and `end-s` are absolute timestamps (`-ss` / `-to`), not durations. `concat`
normalizes every clip to the target canvas (scale + pad + `setsar=1` + fps +
`yuv420p`) before applying `xfade` or `concat`; when `transition = "cut"` the
`transition-s` value is ignored. `concat` includes audio only when every clip
has an audio stream.

## Judging the result

`verify` checks each output according to its capability:

- `video-ops.transcode`: non-zero file size, probed `duration_s > 0`, and
  positive `width` and `height`.
- `video-ops.mux-audio`: non-zero file size, probed `duration_s > 0`, positive
  `width` and `height`, and a present `audio_codec` stream.
- `video-ops.frame`: non-zero file size and a valid Pillow-readable image with
  positive `width` and `height`.
- `video-ops.concat`: non-zero file size, output duration within 0.35 s of the
  expected duration (`sum(durations)` for `cut`, else
  `sum(durations) - (n-1) * transition-s`), and output dimensions equal to the
  target canvas.
- `video-ops.burn-subs` and `video-ops.grade`: non-zero file size, output
  duration within 0.2 s of the source duration, and output dimensions equal to
  the source dimensions.
- `video-ops.overlay`: non-zero file size, output duration within 0.25 s of
  the base duration, and output dimensions equal to the base dimensions.
- `video-ops.speed`: non-zero file size, output duration within 0.25 s of
  `source duration / factor`, and output dimensions equal to the source
  dimensions.
- `video-ops.reframe`: non-zero file size, output duration within 0.25 s of
  the source duration, and output dimensions equal to the target canvas.
- `video-ops.jumpcut`: non-zero file size, valid monotonic `<name>.cuts.json`
  sidecar EDL, `output_duration_s <= source_duration_s + 0.15`, and probed MP4
  duration within 0.35 s of the kept segment sum (`examples/jumpcut.toml`).
- `video-ops.fx`: non-zero file size, output duration within 0.25 s of the
  source duration, and output dimensions equal to the source dimensions
  (`examples/fx.toml`).

Previews write `<asset>.preview.json` matching the `video` schema for MP4
outputs (`length` and `fps` derived from the probed stream) and the `image`
schema for extracted frames.

## Pitfalls

- `imageio-ffmpeg` ships no `ffprobe` binary; stream metadata is parsed from
  `ffmpeg -i` stderr, which exits with code 1 by design when no output is given.
- `mux-audio` uses `-c:v copy` and `-shortest`: if the replacement audio is
  shorter than the video, the output ends when the shorter stream ends.
- `concat` requires at least two clips; clips are scaled/padded to the target
  canvas before joining. If any clip lacks audio, the output is video-only
  (`-an`) to avoid silent-track mismatches.
- `burn-subs` uses the FFmpeg `subtitles` filter (libass). Subtitle file paths
  with special characters are escaped, but keep names simple when possible.
- Always run `facet doctor video-ops` if a run fails; `facet pull video-ops`
  restores the bundled binary and Pillow environment.

See [references/sources.md](references/sources.md) for upstream references.
