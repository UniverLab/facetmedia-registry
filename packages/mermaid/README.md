# mermaid

Render a `.mmd` Mermaid diagram to SVG and PNG with the pinned
`@mermaid-js/mermaid-cli` (12.0.0) and the pinned Chromium that `facet pull` installs. `mermaid.diagram`
is the package's only capability: it wraps `mmdc`, never reimplements it, and
Mermaid is the lab's only diagram tool — what it cannot draw is authored by
hand in HTML/CSS/SVG and animated in HyperFrames.

## What it wraps

- **Node**: `22.21.0`, the same pinned runtime every node-engine package
  uses, with the sha256 of nodejs.org's `node-v22.21.0-linux-x64.tar.gz`.
- **mermaid-cli**: `12.0.0`, the first `[[engine.node.packages]]` entry; its
  `src/cli.js` is the CLI the staged `runner.js` spawns. The other rows are
  the pinned production closure resolved from registry.npmjs.org with tarball
  and SRI integrity, the same procedure hyperframes used.
- **The pinned Chromium.** `facet pull mermaid` installs it once (~200 MB,
  shared by the three packages); `run` reads it from `FACET_BROWSER` and writes
  a puppeteer config pointing at it; `PUPPETEER_SKIP_DOWNLOAD=1` is set on
  every CLI call. The `[browser]` table pins Chromium 158.0.8127.18.
- **Iconify packs.** Every render passes
  `--iconPacksNamesAndUrls` with `logos` and `mdi`, so `architecture-beta`
  services can use `logos:<brand>` and `mdi:<icon>` beside the bundled
  `cloud`, `database`, `disk`, `internet` and `server` icons.

Because a tarball carries no `node_modules`, `runner.js` links each declared
package's `dependencies`, non-optional `peerDependencies` and the linux-x64
`optionalDependencies` into the importing package's own `node_modules`,
picking the highest extracted version that satisfies each range — including
the npm hyphen (`1 - 3`) and bare partial (`3`, `0.6`) ranges the d3 packages
use. A range with no extracted version fails the verb loudly.

## The .mmd header

The style lives in the file's YAML front matter, not in flags:

```yaml
---
config:
  theme: base
  themeVariables:
    primaryColor: "#eef3fb"
    primaryBorderColor: "#2a78d6"
    lineColor: "#555"
    fontFamily: "Ubuntu"
    fontSize: "22px"
---
flowchart LR
  ...
```

`run` validates the header before the CLI runs and a violation throws a plain
Error — facet reports `runner_failed`, exit 1, naming the trap:

- **`theme` is required** under `config`; without the `---` header there is no
  style contract at all.
- **`fontFamily` names one installed family.** A YAML list, or the literal
  `"Ubuntu Sans"`, renders serif — the trap the lab hit. Write
  `fontFamily: "Ubuntu"`.

`invalid_input` is facet-side piece/schema errors only; it cannot come out of
the runner.

## Traps ported from the lab

- **`fontFamily` takes one installed family.** A list or `"Ubuntu Sans"`
  renders serif (above).
- **`direction` inside a subgraph linked from outside is ignored.** To keep a
  subgraph's boxes in a row, chain them with invisible links:
  `a ~~~ b ~~~ c`, as `cycle.mmd` does.
- **`fontSize` for video.** The default is small at 1080p; the approved
  patterns use `fontSize: "22px"`.
- **A bottom (`B`) port arrow crosses the service label.** Split a service's
  exit through a `junction` (`reparto` in `architecture.mmd`), then fan out
  with `R`/`L`/`B` ports.
- **`architecture-beta`** gives groups (`group ... in ...`), services with
  icons and port arrows; the bundled icons are `cloud`, `database`, `disk`,
  `internet`, `server`, plus Iconify `logos:`/`mdi:`.
- **`look: handDrawn`** gives the Excalidraw-style drawing approved as
  `cycle-hand.png`.

## Rejected alternatives

D2, Excalidraw and Python `diagrams` were compared and rejected; Mermaid is
the lab's only diagram tool. What Mermaid cannot express is drawn by hand in
HTML/CSS/SVG and animated in HyperFrames (`hyperframes.diagram` consumes the
SVG this package writes, using its stable `my-svg-*` ids).

## Approved references

- `cycle.mmd` → `cycle.svg` + `cycle.png`, and the hand-drawn
  `cycle-hand.png`, under `examples/`.
- `architecture.mmd` → `architecture.svg` + `architecture.png`, same folder.

## Environment

- **`FACET_BROWSER` (set by `facet pull`).** The pinned Chromium executable.
  `doctor` reports the fix `facet pull mermaid` when it is missing.
- **`FACET_NODE` and `FACET_NODE_PATH`** are set by facet; the runner refuses
  to run outside it.
- **`PUPPETEER_SKIP_DOWNLOAD=1`** is set by the runner on every CLI call.

## The verbs

- `run` resolves `diagram` relative to the piece, validates the header,
  renders `<name>.svg` and `<name>.png` (PNG at `-s 2`) into `out_dir`, and
  reports both as image assets.
- `verify` checks each asset: an SVG must carry an `<svg>` element, a PNG a
  valid signature.
- `preview` writes `<asset>.preview.json` in the image kind's shape, deriving
  the prompt from the diagram's type line and using seed 0.
- `doctor` reports the extracted mermaid-cli package and the Chrome check;
  a missing Chromium names `facet pull mermaid`.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `mermaid.diagram` — `examples/diagram.toml`: `facet example mermaid.diagram --run`

The first run pulls mermaid-cli and the pinned Chromium.
