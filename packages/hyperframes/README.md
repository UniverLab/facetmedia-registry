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

## Verifying

`verify` probes the MP4 with the host `ffprobe`: a video stream with a positive
width, height, frame count and frame rate passes, and the metrics are the
probe's. `preview` writes `<asset>.preview.json` with exactly the video
schema's ten fields. `doctor` reports two checks: the Chromium executable at
`HYPERFRAMES_BROWSER_PATH`, and `ffmpeg` plus `ffprobe` on `PATH`.

`facet doctor hyperframes` classifies a missing browser or ffmpeg as
`machine_cannot` with the fix in the check. Run `facet pull hyperframes` once;
after that the render has no network at all.
