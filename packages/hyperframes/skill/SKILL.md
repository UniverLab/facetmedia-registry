---
name: hyperframes
description: Render checked HTML+GSAP compositions to MP4 with the pinned HyperFrames CLI, then verify the clip by an ffprobe probe.
---
# HyperFrames

`hyperframes.render` turns an authored HTML+GSAP composition into an MP4.
`hyperframes.loop` renders the same composition to a looping GIF or an
alpha-channel MOV. `hyperframes.diagrama` inserts a Mermaid SVG (`diagrama-svg`)
into a checked composition and draws it from an `animacion` list of
`{ selector, at, kind, dur }` steps; every selector is validated against the
SVG's ids before anything renders. `hyperframes.giro` embeds a `.glb` model and
turns it on a camera orbit from eight flat scalar inputs. `hyperframes.personaje`
speaks a hand-drawn SVG character with Rhubarb mouth cues timed to the voice.
`hyperframes.narrado` assembles a narrated piece from `composicion`, `voz`
voice clips, the `musica` bed and the whisper `subtitulos` `.srt`. The
package wraps the pinned CLI: it runs
`check` first, then renders at most two workers, and never reimplements either
step.

The skill has three pillars: the timeline rules, the SVG and DOM id maps, and
the render limits. Each pillar has one row per capability. The full contracts
live in `references/composition.md`, `references/timeline.md`,
`references/id-maps.md` and `references/limits.md`.

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
`index.html`, `build.mjs` and `assets/`. The template is never named `.html`.
The runner injects the recipe values into the copied `index.html`, the file
HyperFrames renders. Each audio clip
is copied into the composition by its file name and enters as `<audio>`.
`fps` passes `--fps`; without it the composition's `data-fps` applies. The
composition layout and the offline/runner split are in
`references/composition.md`.

Every capability ships a runnable sample under `examples/`: `render.toml` and
`loop.toml` share `basic/composicion`, and the other four use
`<capability>/composicion` with their inputs beside the piece file.

## Timeline rules

Animation lives in one paused `gsap.timeline()` registered in
`window.__timelines`, keyed by the composition's `data-composition-id`. The
render seeks each frame by time, so counters tween `textContent` with `snap`,
never `onUpdate`. See `references/timeline.md` for the snippets.

### hyperframes.render

The composition carries its own paused `gsap.timeline({ paused: true })` on
`window.__timelines`; nothing is injected. `fps` only changes the export rate.
See `references/timeline.md`.

### hyperframes.loop

The same source and the same paused timeline as `render`; `format` only chooses
the export (`gif` or `mov-alpha`). See `references/timeline.md`.

### hyperframes.diagrama

`animacion` is an ordered list of `{ selector, at, kind, dur }` steps, `kind`
one of `show`, `draw` or `fade`, `dur` defaulting to `0.4`. The runner validates
the selectors and injects a paused timeline that draws edges with
`strokeDashoffset`. See `references/timeline.md`.

### hyperframes.giro

The scene is a pure `renderAt(t)` called from `hf-seek`; `event.detail.waitUntil`
makes HyperFrames wait for the model. The runner base64-embeds the model at
`/* GLB */""` and writes the eight scalars at `/* GIRO */`, inside
`const DATA = {`. See `references/timeline.md`.

### hyperframes.personaje

The template carries the `/* BOCAS */[]` marker and one
`const AUDIO_START = <number>;`. The timeline is one `tl.set` per mouth change,
shifted by `audio-inicio`, which must match the voice `<audio data-start>`. See
`references/timeline.md`.

### hyperframes.narrado

`index.html` carries one `<!-- SUBS -->` marker, one `<!-- AUDIOS -->` marker
and a positive `data-duration`. The runner parses the `.srt` into
`{ start, end, text }` cues and burns them in as `.sub` divs. Each `voz` item
is `{ clip, inicio }`: `inicio` (default 0) is the seconds on the composition
timeline where that clip starts and must sit inside `data-duration`;
`volumen-musica` (default 0.25, about −12 dB) is the bed's `data-volume` under
the voices. See `references/timeline.md`.

`check` rejects (`sweep_static`) a composition whose timeline stops changing
before `data-duration` ends: the timeline must keep moving across the whole
`data-duration`. Keep something animating until the end, such as a reveal
spread over the whole duration or a looping element. Example (not shipped
with the package): a bar tweened across the full duration with
`tl.fromTo('#barra', { scaleX: 0 }, { scaleX: 1, duration: <data-duration>, ease: 'none' }, 0);`.

## SVG id maps

Selectors pass review and fail the render, so the generated ids are ported
verbatim and built by string concatenation, never a `${}` template. See
`references/id-maps.md`.

### hyperframes.render

The timeline is keyed by `data-composition-id`; clips are addressed by their own
ids and timed with `data-start`, `data-duration` and `data-track-index`. See
`references/id-maps.md`.

### hyperframes.loop

Identical ids to `render`; a loop adds no map, only a different output file. See
`references/id-maps.md`.

### hyperframes.diagrama

Flow nodes are `my-svg-flowchart-<id>-<n>` selected with
`[id^="my-svg-flowchart-<id>-"]`; flow and architecture edges are
`my-svg-L_<origen>_<destino>_0`; edge labels are
`.edgeLabels [data-id="L_<origen>_<destino>_0"]`; services and groups are
`#my-svg-service-<id>` and `#my-svg-group-<id>`, with `#my-svg-gpu` for the
singleton; the arrowhead is the `polygon.arrow` at `path.nextElementSibling`.
Helpers `node`, `edge`, `label` and `byId` are in `references/id-maps.md`.

### hyperframes.giro

The two markers are `/* GLB */""` and `/* GIRO */`; the importmap pins `three`
and `three/addons/` to `./vendor/` paths, and the timeline is keyed by
`data-composition-id`. See `references/id-maps.md`.

### hyperframes.personaje

The character SVG carries one `.boca` shape per Rhubarb letter, ids `boca-X` …
`boca-H` (X rest, A closed, B teeth, C open, D wide open, E round, F pursed, G
teeth on lip, H tongue). The rest rule `.boca { opacity: 0; } #boca-X { opacity: 1; }`
keeps `#boca-X` visible at frame 0. See `references/id-maps.md`.

### hyperframes.narrado

The markers are `<!-- SUBS -->` and `<!-- AUDIOS -->`; cues are
`{ start, end, text }`; subtitles are `.sub` divs `#s0`, `#s1`, … and audio
elements are `#voz-1`, `#voz-2`, … and `#musica`. See `references/id-maps.md`.

## Render limits

The machine and the runner set the limits, and they are not piece inputs:
`check` first, then `--workers 2` at most; everything vendored; the host
Chromium at `HYPERFRAMES_BROWSER_PATH`; host `ffmpeg` and `ffprobe` on `PATH`.
The remote-URL scan skips the top-level `vendor/` subtree. See
`references/limits.md`.

### hyperframes.render

`check` first, `--workers 2`, the vendored tree, the host Chromium and the host
`ffmpeg`/`ffprobe`. See `references/limits.md`.

### hyperframes.loop

Every `render` limit, plus `verify` fails a `gif` without the `NETSCAPE2.0`
looping block and a `mov-alpha` without an alpha `pix_fmt`. See
`references/limits.md`.

### hyperframes.diagrama

Every selector is validated before `check`; an unknown id is `runner_failed`,
exit 1, and nothing renders. `build.mjs` owns the `&gt;` fix inside `<style>`,
the SVG uses the Ubuntu font at `fontSize` 22px, and GSAP is vendored. See
`references/limits.md`.

### hyperframes.giro

The scene must carry `renderAt`, `hf-seek` and `event.detail.waitUntil`, and
must not use `requestAnimationFrame` or `performance.now()`. The vendored tree
is `vendor/gsap.min.js`, `vendor/three.module.js` and
`vendor/three/addons/loaders/GLTFLoader.js`; the offline `build.mjs` produces
it and the runner never executes it. WebGL is software-only. See
`references/limits.md`.

### hyperframes.personaje

Only drawn SVG characters. Rhubarb runs offline
(`rhubarb -r phonetic -f json --dialogFile <texto.txt> <voz.wav> -o bocas.json`);
the runner validates every mouth shape and the rest rule before `check`. See
`references/limits.md`.

### hyperframes.narrado

Loudness is an offline author duty: ffmpeg `normalize` with
`target-lufs=-16.0` and `true-peak-db=-1.5`, then ffmpeg `mix` the voice layers
over the bed with `ducking=true`, `duck-db=-12.0` and `target-lufs=-16.0`. The
markers are required exactly once and every cue must fit `data-duration`.
`verify` fails a `narrado` or `personaje` MP4 with no audio stream. See
`references/limits.md`.

## Judging the result

`verify` probes the MP4 with `ffprobe`: a video stream with positive width,
height, frame count and frame rate passes, and a `narrado` or `personaje`
asset additionally needs an audio stream. `preview` writes the video kind's
ten fields, with the summary `{name} · {width}x{height} · {length}f @ {fps}fps ·
seed {seed}`. Read the check output too: it is the gate that rejected broken
timelines before the render. A person then watches the clip.

The approved lab proofs stay in the lab, referenced by absolute path:

- `render` and `loop`: `/home/jheisonmblivecom/Academic/Deriverables/Grafics/projects/modelos-de-lenguaje/video/`.
- `diagrama`: `/home/jheisonmblivecom/Academic/Deriverables/Grafics/projects/prueba-diagramas/video/`
  and `/home/jheisonmblivecom/Academic/Deriverables/Grafics/projects/prueba-diagramas/video-arquitectura/`.
- `giro`: `/home/jheisonmblivecom/Academic/Deriverables/Grafics/projects/prueba-render-arq/giro/`.
- `personaje`: `/home/jheisonmblivecom/Academic/Deriverables/Grafics/projects/prueba-personaje/`.
- `narrado`: `/home/jheisonmblivecom/Academic/Deriverables/Grafics/projects/demo-hackaton/video/`.

## Pitfalls

- **Remote URLs are refused.** Vendor every asset into the composition; only
  `$schema` and `registry` in `hyperframes.json` may stay remote. The `vendor/`
  subtree is exempt from the scan.
- **Host ffmpeg is required.** Without it the run fails
  `ffmpeg and ffprobe are required to encode video (sudo apt-get install -y ffmpeg)`;
  nothing is installed on the host.
- **Host Chromium is required.** Set `HYPERFRAMES_BROWSER_PATH`, for example to
  `/usr/bin/google-chrome`; the package never downloads a browser.
- **Workers are fixed at 2.** The cap protects the lab machine and is not a
  piece input.
- **`check` runs before every render.** A failing check aborts the run with its
  own output; fix the timeline or the composition, never the runner.
