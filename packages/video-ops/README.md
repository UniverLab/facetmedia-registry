# video-ops

Deterministic CPU video post-processing with the static FFmpeg binary bundled by
`imageio-ffmpeg`: `video-ops.transcode` encodes H.264/AAC MP4 with `+faststart`,
optional downscale, fps cap, and time trim; `video-ops.mux-audio` replaces a
video's audio track without re-encoding the video stream; and `video-ops.frame`
extracts a single PNG or JPG thumbnail frame at a timestamp. It belongs to the
**`video`** facet and writes `video` (`transcode`, `mux-audio`) and `image`
(`frame`) assets. Light package: **no models, no GPU, not exclusive**.

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

## Verification and doctor

`verify` probes video outputs via `ffmpeg -i` stderr (non-zero bytes, duration
> 0, width and height > 0, plus an audio stream for `mux-audio`) and validates
extracted frames by opening them with Pillow (width and height > 0).

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
`fixture.mp4` and `fixture.wav` into a fresh folder and runs it there:

- `video-ops.transcode` — `examples/transcode.toml`: `facet example video-ops.transcode --run`
- `video-ops.mux-audio` — `examples/mux-audio.toml`: `facet example video-ops.mux-audio --run`
- `video-ops.frame` — `examples/frame.toml`: `facet example video-ops.frame --run`
