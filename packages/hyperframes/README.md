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

- **`HYPERFRAMES_BROWSER_PATH` (required).** HyperFrames needs a Chromium
  executable, and this package takes the host's, for example
  `export HYPERFRAMES_BROWSER_PATH=/usr/bin/google-chrome`. The runner inherits
  it; it never downloads a browser.
- **No `[browser]` table.** Core's `pull()` returns from `_pull_node` before
  `_fetch_browser`, and `_pull_node` never fetches a browser, so a browser table
  on a node package would never land under `<home>/browsers/`. The host bridge
  above is the whole browser story.
- **`HYPERFRAMES_NO_TELEMETRY=1` and `HYPERFRAMES_SKIP_SKILLS=1`** are set by
  the runner on every CLI call, per the lab rule.
- **`PATH` is inherited**, so the host `ffmpeg` and `ffprobe` are found.
- **Host ffmpeg is required.** No facet mechanism provisions it: the
  `ffmpeg-static`/`ffprobe-static` tarballs hold only an `install.js` downloader
  and no script runs at install time. Without both binaries the run fails with
  `ffmpeg and ffprobe are required to encode video (sudo apt-get install -y ffmpeg)`
  (`machine_cannot`), and nothing is installed on the host.

## The composition

`composicion` is a directory resolved relative to the piece, holding:

- `hyperframes.json`, the CLI's own manifest;
- `index.tmpl`, the entry template — **never named `.html`**, which HyperFrames
  reads as a second composition;
- `build.mjs`, the bundler script that writes `index.html` from the template;
- `assets/`, the vendored media.

The composition must be self-contained. The runner refuses any `http(s)` URL in
the copied tree except the `$schema` and `registry` metadata values in
`hyperframes.json`, naming the file and the URL; vendor remote assets instead.
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

`hyperframes.diagrama` renders a checked composition with a Mermaid SVG inserted
into it and a GSAP timeline that draws the diagram. It runs the same
`check`-then-`render` path as `hyperframes.render`, with these inputs on top:
`diagrama-svg` (the SVG produced by `tools/mermaid.sh`, for example `ciclo.svg`
or `arquitectura.svg`) and `animacion`, an array of `{ selector, at, kind, dur }`
steps where `kind` is `show`, `draw` or `fade` and `dur` defaults to `0.4`.

The runner copies the SVG beside the composition (so a `build.mjs` in the
composition reaches it as `../<file>.svg`), validates every `animacion[].selector`
against the ids and data-ids the SVG actually carries, and only then injects a
paused timeline into `index.tmpl` before `check`. An unknown id throws a plain
`Error`, exit 1, which facet reports as `runner_failed`; nothing renders.

### Stable Mermaid ids

Selectors are the classic silent failure, so these id shapes are verbatim:

- **Flow nodes**: `my-svg-flowchart-<id>-<n>`; select them by prefix with
  `[id^="my-svg-flowchart-<id>-"]` (helper `node(id)`).
- **Flow and architecture edges**: `my-svg-L_<origen>_<destino>_0`; select by
  exact id `#my-svg-L_<origen>_<destino>_0` (helpers `edge(from, to)` and
  `byId`).
- **Edge labels**: `.edgeLabels [data-id="L_<origen>_<destino>_0"]` (helper
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
  `index.tmpl` at `<!-- DIAGRAMA -->`. The runner never rewrites the SVG.
- **Use the font Mermaid measured with**: `@font-face { src: local('Ubuntu') }`.
  Another build of the font overflows the boxes by about 2px and `check` fails.
- **`fontSize` is 22px at 1080p** in the SVG style; Mermaid's default is too
  small for video.
- **GSAP is vendored**, not loaded from a CDN, like every other composition
  asset.

### Approved examples

Both proofs live in the Grafics lab and pass `check`:

- `projects/prueba-diagramas/video/` draws `ciclo.svg`, a flowchart with nodes,
  edges, edge labels and the `my-svg-gpu` singleton.
- `projects/prueba-diagramas/video-arquitectura/` draws `arquitectura.svg`, an
  architecture diagram with groups, services and `polygon.arrow` arrowheads.

## 3D turns

`hyperframes.giro` renders a checked Three.js scene that turns an embedded CAD
model on a camera orbit: a camera-friendly clip in seconds instead of a Cycles
frame run. It runs the same `check`-then-`render` path as `hyperframes.render`,
with these inputs on top:

- **`modelo-glb`** (path, required): the model, resolved relative to the piece
  file and embedded as base64 into the composition's GLB placeholder before
  `check`, so the render fetches nothing.
- **`orbita-radio`** (`9`), **`orbita-altura`** (`11`), **`orbita-desde`**
  (`-0.9`, radians), **`orbita-vuelta`** (`0.55`, fraction of a full turn over
  the clip): the camera orbit.
- **`centro-x`** (`3.0`), **`centro-y`** (`0.6`), **`centro-z`** (`-2.25`): the
  point the camera looks at; glTF is Y-up, so `centro-z` is the negated
  floor-plane Y.
- **`duracion`** (`8`, seconds): the span `renderAt(t)` maps over.

They are **flat scalars, not an `orbita` table or a `centro` array**: the
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
same check inside `giroSetup`) **skips the top-level `vendor/` subtree**: the
vendored third-party files carry license and documentation URLs in comments that
are never fetched, so scanning them would reject the package's own vendor files
before `check`. The composition's own files remain fully scanned.

The **offline `build.mjs`** in the piece produces this vendored tree and sets up
the composition; the runner never executes it. The runner-side **`giroSetup`**
then does only the runtime injection: it base64-embeds `modelo-glb` into the
`/* GLB */""` placeholder and writes the eight scalars into the `DATA` literal
at `/* GIRO */`.

Use it for camera-friendly video where a simple lit scene and crisp HTML text
are enough; Cycles stays for photoreal staging with bounced light.

### Approved example

The lab proof is
`/home/jheisonmblivecom/Academic/Deriverables/Grafics/projects/prueba-render-arq/giro/`
(`renderAt`/`hf-seek`/`waitUntil`/`DATA.orbita` shape, GLB embed); its CDN
script/importmap lines are the pre-vendor source the shipped composition
vendors locally.

## Verifying

`verify` probes every asset with the host `ffprobe`: a video stream with a
positive width, height, frame count and frame rate passes, and the metrics are
the probe's. For `hyperframes.loop` assets the verdict adds two format checks
the probe cannot express: a `gif` must carry the `NETSCAPE2.0` looping block
(ffprobe reports no loop count, so the runner inspects the bytes), and a
`mov-alpha` MOV must have an alpha channel (`pix_fmt` matching `argb`, `rgba`,
`yuva`, …); an opaque MOV fails. `preview` writes `<asset>.preview.json` with
exactly the video schema's ten fields, and its summary carries the `format`
label for loop assets. `doctor` reports two checks: the Chromium executable at
`HYPERFRAMES_BROWSER_PATH`, and `ffmpeg` plus `ffprobe` on `PATH`.

`facet doctor hyperframes` classifies a missing browser or ffmpeg as
`machine_cannot` with the fix in the check. Run `facet pull hyperframes` once;
after that the render has no network at all.
