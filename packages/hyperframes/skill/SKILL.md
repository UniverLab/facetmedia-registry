---
name: hyperframes
description: Render checked HTML+GSAP compositions to MP4 with the pinned HyperFrames CLI, then verify the clip by an ffprobe probe.
---
# HyperFrames

`hyperframes.render` turns an authored HTML+GSAP composition into an MP4.
`hyperframes.loop` renders the same composition to a looping GIF or an
alpha-channel MOV. `hyperframes.diagram` inserts a Mermaid SVG (`diagram-svg`)
into a checked composition and draws it from an `animation` list of
`{ selector, at, kind, dur }` steps; every selector is validated against the
SVG's ids before anything renders. `hyperframes.turntable` embeds a `.glb` model and
turns it on a camera orbit from eight flat scalar inputs. `hyperframes.character`
speaks a hand-drawn SVG character with Rhubarb mouth cues timed to the voice.
`hyperframes.narrated` assembles a narrated piece from `composition`, `voice`
voice clips, the `music` bed and the whisper `subtitles` `.srt`. The
package wraps the pinned CLI: it runs
`check` first, then renders at most two workers, and never reimplements either
step.

The skill has three pillars: the timeline rules, the SVG and DOM id maps, and
the render limits, plus the authoring habits that keep a timeline correct under
seek. Each pillar has one row per capability. The full contracts live in
`references/composition.md`, `references/timeline.md`, `references/id-maps.md`
and `references/limits.md`.

## When to use

- When a piece is a short video, an animated diagram or a Three.js scene with
  HTML text, authored in HTML+GSAP and bundled by `build.mjs`.
- When the composition is self-contained and vendored: no remote script,
  stylesheet, font or media URL outside `hyperframes.json`'s `$schema` and
  `registry` values.
- When `facet pull hyperframes` has installed the pinned Chromium the runner
  reads from `FACET_BROWSER` and the pinned FFmpeg it reads from
  `FACET_FFMPEG` and `FACET_FFPROBE`;
  otherwise `doctor` fails `machine_cannot` before a run.

## Pieces

```toml
[inputs]
composition = "video"
prompt = "A calm product teaser with a slow push in"
seed = 0
audio = [{ clip = "assets/voice.wav" }]
```

`composition` names the directory holding `hyperframes.json`, `index.tmpl`,
`index.html`, `build.mjs` and `assets/`. The template is never named `.html`.
The runner injects the recipe values into the copied `index.html`, the file
HyperFrames renders. Each audio clip
is copied into the composition by its file name and enters as `<audio>`.
`fps` passes `--fps`; without it the composition's `data-fps` applies. The
composition layout and the offline/runner split are in
`references/composition.md`.

Every capability ships a runnable sample under `examples/`: `render.toml` and
`loop.toml` share `basic/composition`, and the other four use
`<capability>/composition` with their inputs beside the piece file.

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

### hyperframes.diagram

`animation` is an ordered list of `{ selector, at, kind, dur }` steps, `kind`
one of `show`, `draw` or `fade`, `dur` defaulting to `0.4`. The runner validates
the selectors and injects a paused timeline that draws edges with
`strokeDashoffset`. See `references/timeline.md`.

### hyperframes.turntable

The scene is a pure `renderAt(t)` called from `hf-seek`; `event.detail.waitUntil`
makes HyperFrames wait for the model. The runner base64-embeds the model at
`/* GLB */""` and writes the eight scalars at `/* TURNTABLE */`, inside
`const DATA = {`. See `references/timeline.md`.

### hyperframes.character

The template carries the `/* MOUTHS */[]` marker and one
`const AUDIO_START = <number>;`. The timeline is one `tl.set` per mouth change,
shifted by `audio-start`, which must match the voice `<audio data-start>`. See
`references/timeline.md`.

### hyperframes.narrated

`index.html` carries one `<!-- SUBS -->` marker, one `<!-- AUDIOS -->` marker
and a positive `data-duration`. The runner parses the `.srt` into
`{ start, end, text }` cues and burns them in as `.sub` divs. Each `voice` item
is `{ clip, start }`: `start` (default 0) is the seconds on the composition
timeline where that clip starts and must sit inside `data-duration`;
`music-volume` (default 0.25, about −12 dB) is the bed's `data-volume` under
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

### hyperframes.diagram

Flow nodes are `my-svg-flowchart-<id>-<n>` selected with
`[id^="my-svg-flowchart-<id>-"]`; flow and architecture edges are
`my-svg-L_<from>_<to>_0`; edge labels are
`.edgeLabels [data-id="L_<from>_<to>_0"]`; services and groups are
`#my-svg-service-<id>` and `#my-svg-group-<id>`, with `#my-svg-gpu` for the
singleton; the arrowhead is the `polygon.arrow` at `path.nextElementSibling`.
Helpers `node`, `edge`, `label` and `byId` are in `references/id-maps.md`.

### hyperframes.turntable

The two markers are `/* GLB */""` and `/* TURNTABLE */`; the importmap pins `three`
and `three/addons/` to `./vendor/` paths, and the timeline is keyed by
`data-composition-id`. See `references/id-maps.md`.

### hyperframes.character

The character SVG carries one `.mouth` shape per Rhubarb letter, ids `mouth-X` …
`mouth-H` (X rest, A closed, B teeth, C open, D wide open, E round, F pursed, G
teeth on lip, H tongue). The rest rule `.mouth { opacity: 0; } #mouth-X { opacity: 1; }`
keeps `#mouth-X` visible at frame 0. See `references/id-maps.md`.

### hyperframes.narrated

The markers are `<!-- SUBS -->` and `<!-- AUDIOS -->`; cues are
`{ start, end, text }`; subtitles are `.sub` divs `#s0`, `#s1`, … and audio
elements are `#voice-1`, `#voice-2`, … and `#music`. See `references/id-maps.md`.

## Render limits

The machine and the runner set the limits, and they are not piece inputs:
`check` first, then `--workers 2` at most; everything vendored; the pinned
Chromium at `FACET_BROWSER`; the pinned `ffmpeg` at `FACET_FFMPEG` and
`ffprobe` at `FACET_FFPROBE`.
The remote-URL scan skips the top-level `vendor/` subtree. See
`references/limits.md`.

### hyperframes.render

`check` first, `--workers 2`, the vendored tree, the pinned Chromium and the
pinned `ffmpeg`/`ffprobe`. See `references/limits.md`.

### hyperframes.loop

Every `render` limit, plus `verify` fails a `gif` without the `NETSCAPE2.0`
looping block and a `mov-alpha` without an alpha `pix_fmt`. See
`references/limits.md`.

### hyperframes.diagram

Every selector is validated before `check`; an unknown id is `runner_failed`,
exit 1, and nothing renders. The runner inserts the SVG at `<!-- DIAGRAM -->`,
decoding `&gt;` inside `<style>` and stripping xmlns attributes, the SVG uses
the Ubuntu font at `fontSize` 22px, and GSAP is vendored. See
`references/limits.md`.

### hyperframes.turntable

The scene must carry `renderAt`, `hf-seek` and `event.detail.waitUntil`, and
must not use `requestAnimationFrame` or `performance.now()`. The vendored tree
is `vendor/gsap.min.js`, `vendor/three.module.js` and
`vendor/three/addons/loaders/GLTFLoader.js`; the offline `build.mjs` produces
it and the runner never executes it. WebGL is software-only. See
`references/limits.md`.

### hyperframes.character

Only drawn SVG characters. Rhubarb runs offline
(`rhubarb -r phonetic -f json --dialogFile <dialogue.txt> <voice.wav> -o mouths.json`);
the runner validates every mouth shape and the rest rule before `check`. See
`references/limits.md`.

### hyperframes.narrated

Prepare the clips offline: ffmpeg `normalize` with `target-lufs=-16.0` and
`true-peak-db=-1.5`, then ffmpeg `mix` the voice layers over the bed with
`ducking=true`, `duck-db=-12.0` and `target-lufs=-16.0`. The runner brings the
finished `narrated` and `character` videos to `target-lufs` (default -14 LUFS,
the streaming-platform level, louder than the -16 clips by design) with
two-pass EBU R128 `loudnorm` at true peak -1.0 dBTP, and `verify` checks the
result within ±1 LU with true peak at or below -0.5 dBTP. The markers are
required exactly once and every cue must fit `data-duration`.
`verify` fails a `narrated` or `character` MP4 with no audio stream. See
`references/limits.md`.

## Authoring

`check` and the render seek the timeline frame by frame, at a second they pick,
in an order the author does not control. These habits keep the composition
correct on a direct seek, not only on continuous playback.

### Keep the clip anatomy legal

- A nested clip's `data-start` counts from the composition's start, not from
  its parent's.
- Every clip ends at or before the root `data-duration`.
- One `data-composition-id` per file. `data-end` and `data-layer` are legacy
  spellings, not extra knobs.
- Asset paths stay inside the project; nothing climbs above the root.
- Caption rows sit on one track with one index.

### Load the face before measuring it

Request the exact face — family, weight, size and the string about to be
measured — through `document.fonts.load`, build the tweens inside the resolved
promise, and assign `window.__timelines[id]` last. `document.fonts.ready` waits
only for faces something already asked for, so it can resolve while the text
still measures in the fallback font, and a timeline registered while it is
empty still satisfies `check`: the render then shows fallback-font geometry,
with underlines and boxes a few pixels off. Registering the timeline last is
what stops an empty timeline from passing as ready.

### Tween with both ends named

`tl.fromTo(target, from, to, position)` re-applies both ends on every seek, so a
backward or random seek lands where the tween intends. A bare `from` or `to`
remembered its start state once, on a timeline that only ran forward, and can
skip on the way back. Give every tween that matters an explicit position
argument instead of appending it: the timeline's layout must not depend on the
order the author's calls happen to run in.

### Move with transforms and opacity

Animate `x`, `y`, `scale`, `rotation` and `opacity`. Keep `top`, `left`, `width`
and `height` out of tweens: every seek re-runs them, layout on each seek is
slow, and the box can round to a different subpixel position from frame to
frame.

### Never drive media from the timeline

No `play()`, `currentTime`, `pause()` or seek call on `<audio>` or `<video>`.
The render jumps between frames, so media does not follow a timeline and a
played media element is not a tween. Declare timing with the element's own
attributes (`data-start`, `data-duration`, `data-volume`) and, when the frame
needs the media to move or resize, animate a wrapper `<div>` around it, never
the media element itself.

### Stay a pure function of time

No wall clock, no unseeded `Math.random`, no fetch after frame 0, `data-fps` and
the composition size fixed before the first frame, and a finite
`data-duration`. A seek may arrive at any second, in any order, and the same
second must always produce the same state; a value read from
`performance.now()` breaks both rules at once.

### Snapshot three points

Judge a composition at its first frame, at a state in the middle of a tween, and
at its end state: timeline code that plays smoothly can still be wrong when
seeked to directly. `verify` probes the encoded file, so the three stills are
the composition-side half of the check, never a replacement for it.

### Land the motion

- Landed elements hold still; only content still being spoken or pointed at
  keeps moving.
- Stagger entrances so each starts before the last settles; a row of cards that
  all wait for each other reads as one slow move.
- One idea per move. Position and scale and opacity changing together is three
  moves fighting for one beat.
- Overshoot belongs to physical objects. Never let text, UI or counters
  overshoot their target: a number that bounces past its value reads as an
  error.
- Parallax reads as depth when nearer layers move faster than farther ones.
- Pace to the length of the idea: a three-second idea gets short beats, not the
  rhythm of a twelve-second one.

### Cause every transition

A transition is caused by something already on screen — a button that zooms
through becomes the next scene, a card that grows becomes the next frame. Three
to five kinds per piece, about 0.4 s each, and never a dissolve between two
scenes that have nothing to do with each other.

### Hold in frames, seed the randomness

Count holds in frames, never in odd fractions of a second: a hold of 0.067 s at
15 fps drifts across the frame grid and steps unevenly. Seed every random
offset so the same piece renders the same way twice.

### Lock the visual grammar before coding scenes

Define a token palette and one visual grammar before writing scene markup or
tweens so colours, stroke weights and spacing stay consistent across cuts.
Drive any procedural motion or particles from seeded deterministic randomness
so re-renders match bit-for-bit, and keep surfaces clean — avoid
muddy drop shadows or cluttered frames that compete with the focal beat.

### Write the brief so the motion survives

When the agent writes the `prompt` rather than the composition, keep one shared
preamble of standing motion rules and reuse it for every piece, then name
exactly one spectacle beat per piece: the single exaggerated moment the brief is
built around. A burst of motion nobody named is the first thing dropped.

### Land reveals on the voice

In `narrated` and `character` pieces the voice is the clock: place reveals on
the word-level timestamps whisper produces, let a reveal land as its word is
spoken, and let the narration lead, because the visuals never hold the audio
back for a cut. Each `voice` item carries its own `start`, so time the reveals
against the same offsets. State the loudness relation in the brief ("under the
voice") instead of a bare "add music": the `music` bed arrives already mixed and
ducked by the ffmpeg package, and the runner normalises the finished video to
`target-lufs`.

facet pins GSAP and the paused-seek timeline while upstream's frame-adapter
contract also admits other seekable runtimes: the package's scope is GSAP, so
every composition here is a `gsap.timeline({ paused: true })`.

## Judging the result

`verify` probes the MP4 with `ffprobe`: a video stream with positive width,
height, frame count and frame rate passes, and a `narrated` or `character`
asset additionally needs an audio stream. It also runs the pinned tool's
`lint --json` on the source composition: it fails when `errorCount` is above
0, naming each error finding's code and location. For those two it also measures
integrated loudness and true peak with the pinned `ffmpeg`, adds both to the
metrics, and passes only within ±1 LU of `target-lufs` with true peak at or
below -0.5 dBTP. `preview` writes the video kind's
ten fields, with the summary `{name} · {width}x{height} · {length}f @ {fps}fps ·
seed {seed}`. Read the check output too: it is the gate that rejected broken
timelines before the render. A person then watches the clip.

The approved examples ship in `examples/`:

- `render` and `loop`: `basic/composition` (`render.toml`, `loop.toml`).
- `diagram`: `diagram/` (`diagram.toml`).
- `turntable`: `turntable/` (`turntable.toml`).
- `character`: `character/` (`character.toml`).
- `narrated`: `narrated/` (`narrated.toml`).

## Pitfalls

- **Remote URLs are refused.** Vendor every asset into the composition; only
  `$schema` and `registry` in `hyperframes.json` may stay remote. The `vendor/`
  subtree is exempt from the scan.
- **Pinned FFmpeg is required.** `facet pull hyperframes` installs it once
  (~150 MB); without it the run fails
  `ffmpeg and ffprobe are required to encode video; run facet pull hyperframes`.
- **Pinned Chromium is required.** `facet pull hyperframes` installs it once
  (~200 MB, shared by the three packages); the runner reads `FACET_BROWSER`.
- **Workers are fixed at 2.** The cap protects the lab machine and is not a
  piece input.
- **`check` runs before every render.** A failing check aborts the run with its
  own output; fix the timeline or the composition, never the runner.

Sources: `references/sources.md` lists every public source the authoring habits
above rely on, with its maintainer, licence and what was taken from it.
