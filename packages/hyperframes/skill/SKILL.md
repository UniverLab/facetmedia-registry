---
name: hyperframes
description: Render checked HTML+GSAP compositions to MP4 with the pinned HyperFrames CLI, then verify the clip by an ffprobe probe.
---
# HyperFrames

`hyperframes.render` turns an authored HTML+GSAP composition into an MP4. The
package wraps the pinned CLI: it runs `check` first, then renders at most two
workers, and never reimplements either step.

## When to use

- When a piece is a short video, an animated diagram or a Three.js scene with
  HTML text, authored in HTML+GSAP and bundled by `build.mjs`.
- When the composition is self-contained and vendored: no remote script,
  stylesheet, font or media URL outside `hyperframes.json`'s `$schema` and
  `registry` values.
- When the host has a Chromium at `HYPERFRAMES_BROWSER_PATH` and `ffmpeg` plus
  `ffprobe` on `PATH`; otherwise `doctor` fails `machine_cannot` before a run.

## Pieces

```toml
[inputs]
composicion = "video"
prompt = "A calm product teaser with a slow push in"
seed = 0
audio = [{ clip = "assets/voz.wav" }]
```

`composicion` names the directory holding `hyperframes.json`, `index.tmpl`,
`build.mjs` and `assets/`. The template is never named `.html`. Each audio clip
is copied into the composition by its file name and enters as `<audio>`.
`fps` passes `--fps`; without it the composition's `data-fps` applies.

## Judging the result

`verify` probes the MP4 with `ffprobe`: a video stream with positive width,
height, frame count and frame rate passes. `preview` writes the video kind's
ten fields, with the summary `{name} · {width}x{height} · {length}f @ {fps}fps ·
seed {seed}`. Read the check output too: it is the gate that rejected broken
timelines before the render. A person then watches the clip.

## Pitfalls

- **Remote URLs are refused.** Vendor every asset into the composition; only
  `$schema` and `registry` in `hyperframes.json` may stay remote.
- **Host ffmpeg is required.** Without it the run fails
  `ffmpeg and ffprobe are required to encode video (sudo apt-get install -y ffmpeg)`;
  nothing is installed on the host.
- **Host Chromium is required.** Set `HYPERFRAMES_BROWSER_PATH`, for example to
  `/usr/bin/google-chrome`; the package never downloads a browser.
- **Workers are fixed at 2.** The cap protects the lab machine and is not a
  piece input.
- **`check` runs before every render.** A failing check aborts the run with its
  own output; fix the timeline or the composition, never the runner.
