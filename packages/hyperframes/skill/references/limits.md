# Render limits

The package wraps the pinned HyperFrames CLI; the machine and the runner set
the limits, and they are not piece inputs.

- **`check` first, always.** `run` executes `hyperframes check` in the
  composition and aborts with the check output when it fails; only then does it
  render. Never render an unchecked composition.
- **`--workers 2` at most.** The cap protects the lab machine.
- **Vendoring rule.** Every asset is vendored. The runner refuses any `http(s)`
  URL in the copied tree except the `$schema` and `registry` values in
  `hyperframes.json`, naming the file and the URL.
- **`vendor/` scan exemption.** The remote-URL scan skips the top-level
  `vendor/` subtree: vendored third-party files carry license and documentation
  URLs in comments that are never fetched. The composition's own files remain
  fully scanned.
- **Pinned Chromium, `FACET_BROWSER`.** `facet pull hyperframes` installs the
  pinned Chromium once (~200 MB, shared by the three packages); the runner
  reads the executable from `FACET_BROWSER`.
- **Pinned `ffmpeg` and `ffprobe`, `FACET_FFMPEG`/`FACET_FFPROBE`.**
  `facet pull hyperframes` installs the pinned GPL-3.0 build once (~150 MB).
  Without both binaries the run fails `machine_cannot` with
  `ffmpeg and ffprobe are required to encode video; run facet pull hyperframes`.
  The HyperFrames CLI keeps finding `ffmpeg` through the `PATH` core prepends.
- **Node `22.21.0` and HyperFrames `0.8.143`** are pinned; `HYPERFRAMES_NO_TELEMETRY=1`
  and `HYPERFRAMES_SKIP_SKILLS=1` are set on every CLI call.

## hyperframes.render

`render` uses the full limit set above: `check` first, `--workers 2`, the
vendored tree, the pinned Chromium and the pinned `ffmpeg`/`ffprobe`. `fps` passes
`--fps`; the composition's `data-fps` applies when it is omitted.

## hyperframes.loop

`loop` shares every `render` limit and adds two format checks to `verify`:

- **`gif`** must carry the `NETSCAPE2.0` looping block; ffprobe reports no loop
  count, so the runner checks the bytes itself.
- **`mov-alpha`** must have an alpha channel (`pix_fmt` matching `argb`,
  `rgba`, `yuva`, …); an opaque MOV fails.

## hyperframes.diagrama

- **Selectors validate before `check`.** Every `animacion[].selector` is
  checked against the ids and data-ids the SVG actually carries. An unknown id
  throws a plain `Error`, exit 1, which facet reports as `runner_failed`;
  nothing renders.
- **Remote SVG URLs are refused**, except the `w3.org` namespaces.
- **`build.mjs` owns the `>` fix.** Mermaid writes `>` as `&gt;` inside the
  SVG's `<style>`; browsers decode it, the HyperFrames CSS parser does not.
  `build.mjs` replaces `&gt;` with `>` inside `<style>` and inserts the SVG into
  `index.html` at `<!-- DIAGRAMA -->`. The runner never rewrites the SVG.
- **Use the font Mermaid measured with**: `@font-face { src: local('Ubuntu') }`.
  Another build of the font overflows the boxes by about 2px and `check` fails.
- **`fontSize` is 22px at 1080p** in the SVG style; Mermaid's default is too
  small for video.
- **GSAP is vendored**, never loaded from a CDN.

## hyperframes.giro

- **The scene is a pure function of time.** The runner requires `renderAt`,
  `hf-seek` and `event.detail.waitUntil`, and rejects `requestAnimationFrame`
  and `performance.now()` before `check`.
- **The composition is vendored**: `vendor/gsap.min.js` (GSAP 3.14.2),
  `vendor/three.module.js` and `vendor/three/addons/loaders/GLTFLoader.js`
  (Three.js 0.170.0). The importmap must pin `three` and `three/addons/` to
  `./vendor/` paths.
- **The offline `build.mjs` produces the vendored tree**; the runner never
  executes it. Runner-side `giroSetup` only base64-embeds `modelo-glb` into
  `/* GLB */""` and writes the eight scalars into `const DATA = {` at
  `/* GIRO */`.
- **WebGL runs through software (SwiftShader)**, so heavy scenes render slowly.
  Keep the scene light and the text in HTML over the canvas.

## hyperframes.personaje

- **Drawn SVG characters only.** Human avatars generated from a photo were
  rejected for falling into the uncanny valley.
- **Rhubarb comes from the registry's own rhubarb package.** Pull it with
  `facet pull rhubarb` (`packages/rhubarb`). The command is
  `rhubarb -r phonetic -f json --dialogFile <texto.txt> <voz.wav> -o bocas.json`.
  The phonetic recognizer is required because the default one is English-only;
  Spanish needs `-r phonetic`.
- **The runner validates before `check`**: every letter in `bocas.json` has its
  `#boca-<letter>` shape, and the rest rule `.boca { opacity: 0; } #boca-X { opacity: 1; }`
  exists in `index.html` or the SVG. A failure throws a plain `Error`, exit 1,
  which facet reports as `runner_failed`.

## hyperframes.narrado

- **Markers are required exactly once**: one `<!-- SUBS -->`, one
  `<!-- AUDIOS -->`, and a positive `data-duration` on the
  `data-composition-id` tag. A missing or duplicated marker, a bad `.srt` or a
  cue past `data-duration` is `runner_failed`, exit 1; `check` and `render` do
  not run.
- **Final loudness is the runner's job.** The runner brings `narrado` and
  `personaje` videos to `target-lufs` (default -14 LUFS, the
  streaming-platform level) with two-pass EBU R128 `loudnorm` at true peak
  -1.0 dBTP, copying the video stream and re-encoding the audio as AAC, and
  `verify` checks integrated loudness within ±1 LU with true peak at or below
  -0.5 dBTP. Prepare the inputs offline: run every voice file through ffmpeg
  `normalize` with `target-lufs=-16.0` and `true-peak-db=-1.5`, then ffmpeg
  `mix` the voice layers (`role=voice`, `gain-db=0.0`) over the bed
  (`role=bed`) with `ducking=true`, `duck-db=-12.0` and `target-lufs=-16.0`.
- **Sources are the real packages**: voices are voicestudio files (one engine
  per file, so narrator and clone voices arrive as separate `voz` clips), the
  bed is already mixed offline with the ffmpeg package, and the `.srt` comes
  from whisper `transcribe`. The runner never probes audio provenance.
- **The offline `build.mjs` produces the vendored `assets/` and `vendor/`
  tree**; the runner never executes it.
