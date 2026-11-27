# video-ops

Deterministic CPU video post-processing with the static FFmpeg binary bundled by
`imageio-ffmpeg`: `video-ops.transcode` encodes H.264/AAC MP4 with `+faststart`,
optional downscale, fps cap, and time trim; `video-ops.mux-audio` replaces a
video's audio track without re-encoding the video stream; `video-ops.frame`
extracts a single PNG or JPG thumbnail frame at a timestamp; `video-ops.concat`
joins 2+ clips with `xfade` visual transitions and `acrossfade` audio
crossfades; `video-ops.burn-subs` burns `.srt`/`.vtt` subtitles via libass; and
`video-ops.grade` applies deterministic `eq` color grading with optional fades.
It belongs to the **`video`** facet and writes `video` (`transcode`,
`mux-audio`, `concat`, `burn-subs`, `grade`) and `image` (`frame`) assets.
Light package: **no models, no GPU, not exclusive**.

## Piece fields

`video-ops.transcode` — transcode a video to H.264/AAC MP4 with faststart:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `video` | path | yes | — | source video resolved relative to the piece file |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.mp4` |
| `crf` | integer | no | 24 | 14 to 38; lower means higher quality |
| `max-width` | integer | no | — | 240 to 3840; downscales wider sources only |
| `fps` | integer | no | — | 1 to 60; keeps source rate when omitted |
| `start-s` / `end-s` | number | no | — | trim timestamps in seconds (`-ss` / `-to`) |
| `audio-bitrate-kbps` | integer | no | 128 | 64 to 320, AAC bitrate |

`video-ops.mux-audio` — replace a video's audio track without re-encoding video:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `video` | path | yes | — | source video; video stream is copied untouched |
| `audio` | path | yes | — | replacement audio clip; encoded to AAC |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.mp4` |
| `audio-bitrate-kbps` | integer | no | 128 | 64 to 320, AAC bitrate |

`video-ops.frame` — extract a single PNG or JPG still frame:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `video` | path | yes | — | source video resolved relative to the piece file |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.<format>` |
| `at-s` | number | no | 0.0 | timestamp in seconds |
| `format` | enum | no | `png` | `png` or `jpg` |

`video-ops.concat` — join 2+ clips with xfade transitions and acrossfade audio:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `clip` | array | yes | — | min 2 items; each item has `video` (path) |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.mp4` |
| `transition` | enum | no | `fade` | `cut`, `fade`, `fadeblack`, `fadewhite`, `dissolve`, `wipeleft`, `wiperight`, `slideleft`, `slideright`, `smoothleft`, `smoothright`, `zoomin` |
| `transition-s` | number | no | 0.5 | 0.1 to 3.0; ignored for `cut` |
| `width` / `height` | integer | no | first clip | target canvas; clips scaled/padded before joining |
| `fps` | integer | no | 30 | 12 to 60 |
| `crf` | integer | no | 23 | 14 to 38 |

`video-ops.burn-subs` — burn SRT/VTT subtitles into a video with libass:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `video` | path | yes | — | source video resolved relative to the piece file |
| `subtitles` | path | yes | — | `.srt` or `.vtt` subtitle file |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.mp4` |
| `font-size` | integer | no | 22 | 10 to 72 |
| `margin-v` | integer | no | 36 | 0 to 300, bottom margin in pixels |
| `crf` | integer | no | 23 | 14 to 38 |

`video-ops.grade` — deterministic color grading and optional fades:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `video` | path | yes | — | source video resolved relative to the piece file |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.mp4` |
| `brightness` | number | no | 0.0 | -1.0 to 1.0 |
| `contrast` | number | no | 1.0 | 0.2 to 3.0 |
| `saturation` | number | no | 1.0 | 0.0 to 3.0 |
| `gamma` | number | no | 1.0 | 0.2 to 3.0 |
| `fade-in-s` | number | no | 0.0 | 0.0 to 10.0 seconds |
| `fade-out-s` | number | no | 0.0 | 0.0 to 10.0 seconds |
| `crf` | integer | no | 23 | 14 to 38 |

## Verification and doctor

`verify` probes video outputs via `ffmpeg -i` stderr and checks capability-specific
invariants:

- `transcode` / `mux-audio`: non-zero bytes, duration > 0, width and height > 0
  (plus an audio stream for `mux-audio`).
- `concat`: non-zero bytes, output duration within 0.35 s of the expected
  duration (`sum(durations)` for `cut`, else
  `sum(durations) - (n-1) * transition-s`), and output dimensions equal to the
  target canvas.
- `burn-subs` / `grade`: non-zero bytes, output duration within 0.2 s of the
  source duration, and output dimensions equal to the source dimensions.
- `frame`: image readable by Pillow with width and height > 0.

`facet doctor video-ops` checks:

- `binary` (quick): bundled ffmpeg runs `-version`.
- `encoders` (quick): `libx264` and `aac` are listed by `-encoders`.
- `imports` (quick): `PIL.Image` imports cleanly.
- `roundtrip` (full): generates a 1 s lavfi MP4, probes it, and extracts a PNG frame.

## Licences

- `imageio-ffmpeg` — `BSD-2-Clause`
- `FFmpeg` (static binary bundled in `imageio-ffmpeg`) — `GPL-3.0-or-later`
- `pillow` — `MIT-CMU`

## Bundled examples

`facet example <capability> --run` copies the capability's example with
`fixture.mp4`, `fixture.wav`, and `sample.srt` into a fresh folder and runs it
there:

- `video-ops.transcode` — `examples/transcode.toml`: `facet example video-ops.transcode --run`
- `video-ops.mux-audio` — `examples/mux-audio.toml`: `facet example video-ops.mux-audio --run`
- `video-ops.frame` — `examples/frame.toml`: `facet example video-ops.frame --run`
- `video-ops.concat` — `examples/concat.toml`: `facet example video-ops.concat --run`
- `video-ops.burn-subs` — `examples/burn-subs.toml`: `facet example video-ops.burn-subs --run`
- `video-ops.grade` — `examples/grade.toml`: `facet example video-ops.grade --run`
