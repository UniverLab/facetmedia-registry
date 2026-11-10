# The composition

A `composicion` directory is what every hyperframes capability renders. It is
resolved relative to the piece file and shipped self-contained.

## What the directory holds

```text
<composicion>/
├── hyperframes.json   the CLI's own manifest
├── index.tmpl         the entry template, never named .html
├── build.mjs          writes index.html from index.tmpl
├── index.html         the author's offline build output
├── assets/            vendored media (images, fonts, audio, the SVG, the GLB)
└── vendor/            pinned third-party code (gsap.min.js, three.module.js, …)
```

- **`hyperframes.json`** carries the `$schema` and `registry` values. Those two
  are the only remote URLs a composition may hold; every other asset is
  vendored.
- **`index.tmpl`** is the entry template. It is never named `.html`, because
  HyperFrames reads a `.html` file as a second composition.
- **`build.mjs`** is the piece author's offline bundler. It writes
  `index.html` from `index.tmpl`, and for a capability it also inlines the
  Mermaid SVG or the character. The runner never executes it.
- **`index.html`** is the copy the runner edits: every setup reads and writes
  the copied `index.html`, the file HyperFrames renders, so `build.mjs` must
  keep the runner's markers in the `index.html` it writes.
- **`assets/`** holds the composition's own media.
- **`vendor/`** holds pinned third-party code. The remote-URL scan skips the
  top-level `vendor/` subtree, because license and documentation URLs in those
  files are comments the render never fetches; the composition's own files are
  scanned in full.

## The offline half and the runner half

The split is the same in every capability:

| Half | Who runs it | What it produces |
|------|-------------|------------------|
| Offline | the piece author's `build.mjs` | `index.html` keeping the runner's markers, the vendored tree and the inlined SVG or character |
| Runner-side | the package runner in the copied composition | the runtime values: audio injection, the GLB, the eight orbit scalars, the mouth cues, `AUDIO_START`, the SUBS and AUDIOS markers and the timeline |

The runner copies the composition into `<out>/composition` and runs its
capability setup there before `check`. `build.mjs` is never executed by the
runner.

Each audio item's `clip` is copied into the composition by its file name and
enters as `<audio>`. A composition that fetches an asset at render time is
refused, naming the file and the URL.

See `references/timeline.md` for what animates, `references/id-maps.md` for the
ids and markers each capability reads, and `references/limits.md` for the
machine rules.
