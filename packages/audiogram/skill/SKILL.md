---
name: audiogram
description: Audio-reactive waveform or frequency-bars MP4 videos over an editorial card or cover image, rendered on CPU with NumPy, soundfile and Pillow.
---
# Audiogram

`audiogram.render` turns one audio clip — a voice note, a podcast
excerpt, a music bed — into an audio-reactive MP4 video: FFT frequency
bars or a centered amplitude waveform drawn over a clean editorial card
or a cover image. Rendered on CPU with NumPy (analysis), soundfile
(audio I/O) and Pillow (frames), encoded with the static FFmpeg binary
bundled by `imageio-ffmpeg` (`libx264`, `yuv420p`, `aac`,
`+faststart`). No models, no GPU.

## When to use

- When a **voice note, podcast excerpt or music bed** needs a shareable
  video: use `audiogram.render` with `style = "bars"` for an energetic
  frequency display or `style = "waveform"` for a calm amplitude line.
- When the clip needs a **portrait or landscape cut** for a feed: set
  `aspect` to `"9:16"`, `"16:9"` or `"1:1"` (default `"1:1"`).
- When the video needs a **face or brand**: pass `cover` (any image
  FFmpeg and Pillow open) for a dimmed full-bleed backdrop, plus a
  short `title` drawn cleanly on the card.
- When the card must match a palette: set `background` (default
  `"#111315"`) and `accent` (default `"#E8C547"`), both `#rrggbb`.
- It **does not transcribe, clean or edit audio**: use `whisper`,
  `ffmpeg` or `video-ops` for those steps first, then render.

## Pieces

```toml
capability = "audiogram.render"

[inputs]
audio = "voice-note.wav"
name = "voice-note-card"
style = "bars"
```

`audio` is the source clip, resolved relative to the piece file: any
clip decodable by the bundled FFmpeg. `name` is the asset base name
(`[a-z0-9][a-z0-9-]*`); the runner writes `<name>.mp4` at the canvas
for the aspect (`16:9` is 1280x720, `9:16` is 720x1280, `1:1` is
1080x1080), at `fps` frames per second (default 24, 12–30) and `crf`
quality (default 23, 14–38).

`style` is `"bars"` (default, 64 log-scaled FFT bars rising from a
baseline) or `"waveform"` (a centered peak-amplitude line, one span per
pixel column). Both are computed deterministically from the mono mix:
the same audio, title and colors always render the same frames.
`cover` is an optional backdrop image scaled to fill and dimmed so the
accent stays legible; without it the card is the flat `background`
color. `title` is an optional short line drawn centered above the
visualizer.

## Judging the result

- The MP4 is non-empty, its pixels match the aspect canvas exactly, its
  duration matches the source audio within 0.2 s, and it carries an
  audio stream — `verify` checks all four.
- The visualizer actually reacts: `verify` decodes frames at two
  timestamps and requires a mean per-pixel difference above the motion
  floor. A flat render (constant tone, broken analysis) fails here.
- Every asset ships a `video`-kind preview (`<name>.mp4.preview.json`)
  with probed width, height, frame count and fps; `prompt` is
  `render video <name>` and `seed` is 0.
- `doctor` checks the FFmpeg binary plus the NumPy, soundfile and
  Pillow imports at `quick` depth, and renders plus verifies a 1 s
  440 Hz synthetic sine audiogram in a temp dir at `full` depth.

## Pitfalls

- A **constant-amplitude tone** (test sine, hum) renders near-static
  bars: the motion check fails, correctly — real voice and music move.
- A **very short clip** (under one frame at `fps`) is refused; a clip
  under ~0.5 s leaves the motion check little to compare.
- `cover` images resolve relative to the piece file like `audio` does;
  a missing path fails the piece before any frame renders.
- Colors must be `#rrggbb`; named colors and short `#rgb` forms are
  refused.
- Long clips render one Pillow frame per output frame: fine for voice
  notes and excerpts, slow for full albums — trim first.
