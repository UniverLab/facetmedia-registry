# audiogram

Audio-reactive waveform or frequency-bars MP4 videos from an audio
clip, over a clean editorial card or a cover image. `audiogram.render`
decodes any FFmpeg-readable clip to mono, computes per-frame FFT bar
heights or peak waveform envelopes deterministically in NumPy, draws
RGB frames with Pillow, and pipes them plus the original audio into the
static FFmpeg binary bundled by `imageio-ffmpeg` (`libx264`, `yuv420p`,
`aac`, `+faststart`). It belongs to the **`video`** facet and writes
`video` assets. Light package: **no models, no GPU, not exclusive**.

## Piece fields

`audiogram.render` — render an audio-reactive MP4 from an audio clip:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `audio` | path | yes | — | source clip resolved relative to the piece file |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.mp4` |
| `style` | enum | — | `bars` | `bars` FFT frequency bars, `waveform` centered amplitude line |
| `aspect` | enum | — | `1:1` | `16:9` 1280x720, `9:16` 720x1280, `1:1` 1080x1080 |
| `cover` | path | — | — | optional backdrop image, scaled to fill and dimmed |
| `title` | string | — | — | optional short title drawn above the visualizer |
| `background` | string | — | `#111315` | `#rrggbb` card color when `cover` is omitted |
| `accent` | string | — | `#E8C547` | `#rrggbb` color of the bars or waveform |
| `fps` | integer | — | `24` | 12–30 frames per second |
| `crf` | integer | — | `23` | 14–38 libx264 quality |

## Verification and doctor

`verify` checks the MP4 is non-zero, its pixels match the aspect
canvas, its duration matches the source audio within 0.2 s, it carries
an audio stream, and frames at two timestamps differ above the motion
floor (the visualizer reacts to the audio). `preview` writes the video
schema's fields per asset (`prompt` is `render video <name>`, `seed`
is 0). `doctor` checks the FFmpeg binary and the NumPy, soundfile and
Pillow imports at `quick` depth, and renders plus verifies a 1 s 440 Hz
synthetic sine audiogram in a temp dir at `full` depth.

## Licences

| Subject | SPDX |
|---|---|
| imageio-ffmpeg | BSD-2-Clause |
| FFmpeg | GPL-3.0-or-later |
| numpy | BSD-3-Clause |
| soundfile | BSD-3-Clause |
| pillow | MIT-CMU |

## Bundled examples

- `examples/render.toml` — a bars-style square card from the bundled
  2 s fixture tone (`fixture.wav`).
