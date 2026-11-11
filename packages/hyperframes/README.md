# hyperframes

Render a checked HTML+GSAP composition to a verified MP4 with the pinned
HyperFrames CLI. `hyperframes.render` is the video provider: it wraps the CLI,
never reimplements it.

## What it wraps

- **Node**: `22.21.0`, pinned in `[engine.node]` with the sha256 of
  nodejs.org's `node-v22.21.0-linux-x64.tar.gz`.
- **HyperFrames**: `0.8.143`, the first `[[engine.node.packages]]` entry, so
  its `bin/hyperframes.mjs` is the CLI the staged `runner.js` spawns. The other
  70 rows are the pinned production closure; `string-width` appears twice
  (7.2.0 and 8.3.0) because no single version satisfies every requester.
- **`check` first, always.** `run` executes `hyperframes check` in the
  composition and aborts with the check output when it fails; only then does it
  render. It never renders an unchecked composition.
- **`--workers 2` at most**, fixed by the runner. The lab powers off under
  sustained load; the cap is not a piece input.

The npm tarballs are extracted under the facet home with no npm and no npx.
Because a tarball carries no `node_modules`, `runner.js` links each declared
package's `dependencies`, non-optional `peerDependencies` and the linux-x64
glibc `optionalDependencies` into the importing package's own `node_modules`,
picking the highest extracted version that satisfies each range. That is how
ESM finds them; `NODE_PATH` would not work. A range with no extracted version
fails the verb loudly.

## Environment

- **`[browser]` (declared).** `facet pull` fetches the pinned Chromium; the
  runner reads `FACET_BROWSER` and hands it to the HyperFrames CLI; the host
  needs no Chrome.
- **`HYPERFRAMES_NO_TELEMETRY=1` and `HYPERFRAMES_SKIP_SKILLS=1`** are set by
  the runner on every CLI call, per the lab rule.
- **`[ffmpeg]` (declared).** `facet pull hyperframes` downloads the pinned
  FFmpeg build once (~150 MB, GPL-3.0); the runner reads `ffmpeg` from
  `FACET_FFMPEG` and `ffprobe` from `FACET_FFPROBE`, and the HyperFrames CLI
  keeps finding `ffmpeg` through the `PATH` core prepends. Without both
  binaries the run fails with
  `ffmpeg and ffprobe are required to encode video; run facet pull hyperframes`
  (`machine_cannot`), and nothing is installed on the host.

## The composition

`composition` is a directory resolved relative to the piece, holding:

- `hyperframes.json`, the CLI's own manifest;
- `index.tmpl`, the author source — **never named `.html`**, which HyperFrames
  reads as a second composition;
- `index.html`, written from the template by `build.mjs`; the runner injects
  the recipe values into this copied file, the one HyperFrames renders, so
  `build.mjs` must keep the runner's markers in it;
- `build.mjs`, the bundler script that writes `index.html` from the template;
- `assets/`, the vendored media.

The composition must be self-contained. The runner refuses any `http(s)` URL in
the copied tree except the `$schema` and `registry` metadata values in
`hyperframes.json`, naming the file and the URL; vendor remote assets instead.
It skips the top-level `vendor/` subtree, because vendored third-party files
carry licence and documentation URLs in comments that are never fetched; the
composition's own files are scanned in full.
Each `audio` item's `clip` is copied into the composition by its file name and
enters as `<audio>`.

## Timeline rules

Animation lives in one paused `gsap.timeline()` registered on
`window.__timelines`; counters tween `textContent` with `snap`, never
`onUpdate`, because the render seeks each frame by time. Three.js scenes are a
pure `renderAt(t)` called from `hf-seek`; `requestAnimationFrame`,
`performance.now()` and remote imports are rejected by `check`. The lab's notes
are the authority.

## Loops and transparency

`hyperframes.loop` renders the same checked composition as `hyperframes.render` —
same `check` first, same `--workers 2` cap, same vendored-assets rule — with a
`format` input choosing the export:

- **`gif`** writes `<name>.gif` (`--format gif`, mime `image/gif`): the format
  for loops in feeds, docs and chat. The GIF carries the `NETSCAPE2.0` looping
  block, and `verify` fails the asset when that block is absent — ffprobe
  reports no loop count, so the runner checks the bytes itself.
- **`mov-alpha`** writes `<name>.mov` (`--format mov`, mime
  `video/quicktime`): a QuickTime MOV with an alpha channel, for overlays on
  other footage. `verify` requires the probed `pix_fmt` to carry alpha
  (`argb`, `rgba`, `yuva`, …); an opaque MOV fails.

## Diagrams

`hyperframes.diagram` renders a checked composition with a Mermaid SVG inserted
into it and a GSAP timeline that draws the diagram. It runs the same
`check`-then-`render` path as `hyperframes.render`, with these inputs on top:
`diagram-svg` (the SVG produced by `tools/mermaid.sh`, for example `ciclo.svg`
or `arquitectura.svg`) and `animation`, an array of `{ selector, at, kind, dur }`
steps where `kind` is `show`, `draw` or `fade` and `dur` defaults to `0.4`.

The runner copies the SVG beside the composition (so a `build.mjs` in the
composition reaches it as `../<file>.svg`), validates every `animation[].selector`
against the ids and data-ids the SVG actually carries, and only then injects a
paused timeline into `index.html` before `check`. An unknown id throws a plain
`Error`, exit 1, which facet reports as `runner_failed`; nothing renders.

### Stable Mermaid ids

Selectors are the classic silent failure, so these id shapes are verbatim:

- **Flow nodes**: `my-svg-flowchart-<id>-<n>`; select them by prefix with
  `[id^="my-svg-flowchart-<id>-"]` (helper `node(id)`).
- **Flow and architecture edges**: `my-svg-L_<from>_<to>_0`; select by
  exact id `#my-svg-L_<from>_<to>_0` (helpers `edge(from, to)` and
  `byId`).
- **Edge labels**: `.edgeLabels [data-id="L_<from>_<to>_0"]` (helper
  `label(from, to)`).
- **Architecture services and groups**: `#my-svg-service-<id>`,
  `#my-svg-group-<id>`, `#my-svg-group-lab`, `#my-svg-group-gpu`;
  **singletons**: `#my-svg-gpu`.
- **Arrowheads**: the `polygon.arrow` right after its edge path, i.e.
  `path.nextElementSibling`. `draw` fades the arrowhead in with the path.

### Timeline rules

- **Arrows draw with `strokeDashoffset`**: the runner sets
  `strokeDasharray`/`strokeDashoffset` to the path length and tweens the offset
  to zero. A `g` edge is resolved to its inner `path` first.
- **Build selectors by string concatenation**, never a `${}` template: the
  HyperFrames bundler rejects template literals in selectors.
- **`build.mjs` owns the `>` fix.** Mermaid writes `>` as `&gt;` inside the
  SVG's `<style>`; browsers decode it, the HyperFrames CSS parser does not.
  `build.mjs` replaces `&gt;` with `>` inside `<style>` and inserts the SVG into
  `index.html` at `<!-- DIAGRAM -->`. The runner never rewrites the SVG.
- **Use the font Mermaid measured with**: `@font-face { src: local('Ubuntu') }`.
  Another build of the font overflows the boxes by about 2px and `check` fails.
- **`fontSize` is 22px at 1080p** in the SVG style; Mermaid's default is too
  small for video.
- **GSAP is vendored**, not loaded from a CDN, like every other composition
  asset.

### Approved examples

Both shapes pass `check`:

- `examples/diagram/` draws a flowchart SVG with nodes, edges, edge labels
  and the `my-svg-gpu` singleton.
- the same path draws an architecture SVG with groups, services and
  `polygon.arrow` arrowheads (see
  `packages/mermaid/examples/arquitectura.svg`).

## 3D turns

`hyperframes.turntable` renders a checked Three.js scene that turns an embedded CAD
model on a camera orbit: a camera-friendly clip in seconds instead of a Cycles
frame run. It runs the same `check`-then-`render` path as `hyperframes.render`,
with these inputs on top:

- **`model-glb`** (path, required): the model, resolved relative to the piece
  file and embedded as base64 into the composition's GLB placeholder before
  `check`, so the render fetches nothing.
- **`orbit-radius`** (`9`), **`orbit-height`** (`11`), **`orbit-start`**
  (`-0.9`, radians), **`orbit-fraction`** (`0.55`, fraction of a full turn over
  the clip): the camera orbit.
- **`center-x`** (`3.0`), **`center-y`** (`0.6`), **`center-z`** (`-2.25`): the
  point the camera looks at; glTF is Y-up, so `center-z` is the negated
  floor-plane Y.
- **`duration`** (`8`, seconds): the span `renderAt(t)` maps over.

They are **flat scalars, not an `orbit` table or a `center` array**: the
registry input schema allows only `string`, `integer`, `number`, `boolean`,
`enum`, `path` and `array`, and array items must be tables (`schema.py`
`_check_array` rejects non-dict items). A table or number array would fail
package load and piece validation with `invalid_input` before the runner starts.

The scene is a **pure function of time**: `renderAt(t)` is called from the
`hf-seek` event and the runner validates the recipe before `check` — the
composition must carry `renderAt`, `hf-seek` and `event.detail.waitUntil`, and
must not use `requestAnimationFrame` or `performance.now()`, which `check`
rejects too. `event.detail.waitUntil(promise)` makes HyperFrames wait for the
model to load. Text stays in HTML over the canvas, so it is crisp.

### Vendoring

The composition is shipped self-contained under `vendor/`, such as:

```
vendor/gsap.min.js                        (GSAP 3.14.2)
vendor/three.module.js                    (Three.js 0.170.0)
vendor/three/addons/loaders/GLTFLoader.js (Three.js 0.170.0)
```

The importmap pins `three` and `three/addons/` to `./vendor/` paths and the
runner rejects any other value. The remote-URL scan (`refuseRemoteUrls`, and the
same check inside `turntableSetup`) **skips the top-level `vendor/` subtree**: the
vendored third-party files carry license and documentation URLs in comments that
are never fetched, so scanning them would reject the package's own vendor files
before `check`. The composition's own files remain fully scanned.

The **offline `build.mjs`** in the piece produces this vendored tree and sets up
the composition; the runner never executes it. The runner-side **`turntableSetup`**
reads and writes the copied `index.html` and does only the runtime injection:
it base64-embeds `model-glb` into the `/* GLB */""` placeholder and writes
the eight scalars into the `DATA` literal at `/* TURNTABLE */`.

Use it for camera-friendly video where a simple lit scene and crisp HTML text
are enough; Cycles stays for photoreal staging with bounced light.

### Approved example

The approved example is `examples/turntable/`
(`renderAt`/`hf-seek`/`waitUntil`/`DATA.orbit` shape, GLB embed); its CDN
script/importmap lines are the pre-vendor source the shipped composition
vendors locally.

## Characters

`hyperframes.character` makes a **hand-drawn** SVG character speak with
phonetic mouth sequences timed to the voice. It runs the same
`check`-then-`render` path as `hyperframes.render`, with these inputs on top:

- **`composition`** (path, required): the composition directory, resolved
  relative to the piece.
- **`character-svg`** (path, required): the character SVG, resolved relative to
  the piece, with one `.mouth` shape per Rhubarb letter and ids `mouth-X`…`mouth-H`.
- **`voice`** (path, required): the voice audio, resolved relative to the piece and
  copied into the composition root.
- **`mouths`** (path, required): `mouths.json`, resolved relative to the piece.
- **`audio-start`** (`0.5`): the shift applied to every mouth cue, matching the
  `<audio>` element's `data-start`.
- **`target-lufs`** (`-14`): the integrated loudness the finished video is
  normalised to, -24 to -9; `verify` passes within ±1 LU with true peak at or
  below -0.5 dBTP.

`prompt`, `seed` and `fps` behave as in `hyperframes.render`. The inputs are
flat, like `turntable`'s: the registry schema has no nested tables, so blinks and the
head sway stay fixed times in the template (`[1.6, 4.3, 7.1, 9.8]`) and are not
inputs.

### Mouth map

One shape per Rhubarb letter, in the character SVG under `#mouth`:

| id | letter | mouth |
| --- | --- | --- |
| `mouth-X` | X | rest |
| `mouth-A` | A | closed (m, b, p) |
| `mouth-B` | B | teeth (most consonants) |
| `mouth-C` | C | open (e) |
| `mouth-D` | D | wide open (a) |
| `mouth-E` | E | round (o) |
| `mouth-F` | F | pursed (u) |
| `mouth-G` | G | teeth on lip (f, v) |
| `mouth-H` | H | tongue (l) |

The CSS carries the rest state, because a `tl.set` at instant 0 never shows:

```css
.mouth { opacity: 0; } #mouth-X { opacity: 1; }
```

The runner requires that rule in `index.html` or in the SVG's own `<style>`; a
missing shape for a letter in `mouths.json` or a missing rest rule throws a plain
`Error`, exit 1, which facet reports as `runner_failed`. `check` and `render`
never run in that case.

### Offline half and runner half

- **Offline, the piece author's `build.mjs`** inlines the character into the
  composition and keeps the `/* MOUTHS */[]` placeholder empty. The mouth cues
  come only from the runner's `mouths` input. The runner never executes `build.mjs`.
- **Runner-side, `characterSetup`** runs in the copied composition before
  `check`: it validates the mouth shapes and the rest rule, writes the cues into
  `/* MOUTHS */[]`, and writes `audio-start` into
  `const AUDIO_START = <number>;`.

The timeline is one `tl.set` per mouth change, shifted by the audio start, so
the lips follow the voice:

```js
CUES.forEach(function (cue) {
  tl.set('.mouth', { opacity: 0 }, AUDIO_START + cue.start)
    .set('#mouth-' + cue.value, { opacity: 1 }, AUDIO_START + cue.start);
});
```

### The cue file

`mouths` comes from the upstream Rhubarb CLI, run offline, not from a registry
package:

```
rhubarb -r phonetic -f json --dialogFile <dialogue> <voice> -o mouths.json
```

The phonetic recognizer is required because the default one is English-only;
Spanish needs `-r phonetic`. The CLI is quick, about a second. It comes from
the registry's own rhubarb package: `facet pull rhubarb`
(`packages/rhubarb`).

### Drawn characters only

Only drawn SVG characters are supported. Human avatars generated from a photo
were rejected: the result falls into the uncanny valley, and that provider was
removed. The drawn path is the approved one.

### Approved example

The approved example is `examples/character/`: a fox speaking with the
person's voice, an 11.5 s composition whose 10.32 s of voice starts at
`data-start="0.5"`. Its `index.tmpl` carries the rest rule, the
nine `mouth-X`…`mouth-H` shapes and the cue timeline; its `build.mjs` copies
`index.tmpl` to `index.html` keeping `/* MOUTHS */[]` empty, and the runner's
`characterSetup` injects the cues from the `mouths` input into the copied
`index.html`.

## Narration

`hyperframes.narrated` completes a narrated piece on one checked timeline: voice
files, an instrumental bed and whisper subtitles are assembled by
`narratedSetup` in the copied composition before the same `check`-then-`render`
path as `hyperframes.render`. Its inputs are `composition`, `voice` (one
`{ clip, start }` table per voice file, at least one; `start` is the seconds
on the composition timeline where that clip starts, default 0), `music`,
`subtitles` (the `.srt`), `music-volume` (the bed's `data-volume` under the
voices, default 0.25 at about −12 dB, 0 to 1), `target-lufs` (the integrated
loudness the finished video is normalised to, number, default -14, -24 to -9),
plus `prompt`, `seed` and `fps`.

The sources are the real packages: voices are voicestudio files — one engine
per file, so narrator and clone voices arrive as separate `voice` clips and the
runner never probes audio provenance; `music` is the instrumental bed already
mixed offline with the ffmpeg package; `subtitles` is the `.srt` that whisper
`transcribe` writes beside `<name>.txt` and `<name>.json`.

The runner brings `narrated` and `character` videos to `target-lufs`
(default -14 LUFS, the streaming-platform level, louder than the -16 clips by
design): after the render it applies two-pass EBU R128 `loudnorm` at true peak
-1.0 dBTP, copying the video stream and re-encoding the audio as AAC, and the
asset is the normalised file. `verify` measures integrated loudness and true
peak, records both in `metrics`, and passes only within ±1 LU of `target-lufs`
with true peak at or below -0.5 dBTP (`thresholds` names both limits). Prepare
the inputs offline with the fixed recipe: run every voice file through ffmpeg
`normalize` with `target-lufs` `-16.0` and `true-peak-db` `-1.5`, then ffmpeg
`mix` the voice layers (`role` `voice`, `gain-db` `0.0`) over the bed (`role`
`bed`) with `ducking` `true`, `duck-db` `-12.0` and `target-lufs` `-16.0`. Any
assembly violation fails the run.

`index.html` must carry exactly one `<!-- SUBS -->` marker, exactly one
`<!-- AUDIOS -->` marker and a positive `data-duration` on the
`data-composition-id` tag, and its CSS must style `.sub`: the cues are
opacity-toggled divs burned into the frames, never a sidecar copy.
`narratedSetup` copies each `voice` clip and `music` into the composition root,
replaces the markers with
`<audio id="voice-N" src="<name>" data-start="<start>" data-duration="<duration-start>" data-track-index="<N>" data-volume="1">` /
`<audio id="music" src="<name>" data-start="0" data-duration="<duration>" data-track-index="<voices+1>" data-volume="<music-volume>">`
and `<div class="sub" id="sN">` lines, parses whisper's
`HH:MM:SS,mmm --> HH:MM:SS,mmm` cues (comma or dot milliseconds, text joined
by spaces) into `{ start, end, text }` rounded to 3 decimals, requires every
cue end to fit `data-duration`, and appends the opacity timeline that joins
`window.__timelines[...]`. A missing file, a bad `.srt`, a missing or
duplicated marker, an overlong cue, a `start` at or past `data-duration`, or
a `music-volume` outside 0..1 throws a plain `Error`, exit 1, which facet
reports as `runner_failed`; `check` and `render` never run.

The offline `build.mjs` produces the vendored `assets/` and `vendor/` tree;
the runner never executes it. The SUBS burn-in shape is proven in
`examples/narrated/`: voice clips, an instrumental bed and a whisper `.srt`
burned in as opacity cues at run time.

## Verifying

`verify` probes every asset with the pinned `ffprobe`: a video stream with a
positive width, height, frame count and frame rate passes, and the metrics are
the probe's. A `hyperframes.narrated` or `hyperframes.character` asset with no
audio stream fails, since the mix needs its voices; those two also need the
pinned `ffmpeg`, because `verify` measures integrated loudness and true peak with
a `loudnorm` pass, adds `integrated_lufs` and `true_peak_dbtp` to the metrics,
and passes only within ±1 LU of `target-lufs` with true peak at or below
-0.5 dBTP. For `hyperframes.loop` assets the verdict adds two format checks
the probe cannot express: a `gif` must carry the `NETSCAPE2.0` looping block
(ffprobe reports no loop count, so the runner inspects the bytes), and a
`mov-alpha` MOV must have an alpha channel (`pix_fmt` matching `argb`, `rgba`,
`yuva`, …); an opaque MOV fails. `preview` writes `<asset>.preview.json` with
exactly the video schema's ten fields, and its summary carries the `format`
label for loop assets. `doctor` reports two checks: the Chromium executable at
`FACET_BROWSER`, and `ffmpeg` at `FACET_FFMPEG` with `ffprobe` at `FACET_FFPROBE`.

`facet doctor hyperframes` classifies a missing browser or ffmpeg as
`machine_cannot` with the fix in the check. Run `facet pull hyperframes` once;
after that the render has no network at all.
