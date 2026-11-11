---
name: mermaid
description: Render a .mmd Mermaid diagram to SVG and PNG with the pinned mermaid-cli and the pinned Chromium that `facet pull` installs.
---
# Mermaid

`mermaid.diagram` turns a `.mmd` file into an SVG and a 2x PNG through the
pinned `@mermaid-js/mermaid-cli`. The style — theme, colors, font, look —
lives in the file's YAML header, and the header traps are validated before
the CLI runs: a missing `theme` or a `fontFamily` that is a list or
`"Ubuntu Sans"` fails `runner_failed`, exit 1.

## When to use

- When a piece needs a flowchart, a sequence diagram, a timeline, a mindmap
  or an `architecture-beta` diagram with groups, services, port arrows and
  icons.
- When the lab's only diagram tool is enough; what Mermaid cannot draw is
  authored by hand in HTML/CSS/SVG and animated in HyperFrames instead.
  Mermaid wins the comparison on purpose: D2 duplicates it and its SVG is
  harder to animate, Excalidraw breaks groups, floats labels over arrows and
  needs a CDN, and Python `diagrams` needs Graphviz installed with `sudo`
  while `architecture-beta` already covers its cloud icons.
- When `facet pull mermaid` has installed the pinned Chromium the runner reads
  from `FACET_BROWSER`.

## Pieces

```toml
[inputs]
diagram = "ciclo.mmd"
```

`diagram` names the `.mmd` file resolved relative to the piece. Its YAML
header carries `config.theme`, `config.themeVariables` (`primaryColor`,
`lineColor`, `fontFamily`, `fontSize`) and optionally `look: handDrawn` for
the Excalidraw-style drawing. `run` writes `<name>.svg` and `<name>.png`
beside each other in the output directory; `verify` checks the SVG element
and the PNG signature; `preview` writes the image kind's preview file.

Copy the header verbatim from `references/headers.md`: `ciclo.mmd` uses
`theme: base` with `primaryColor`, `primaryBorderColor`, `lineColor`,
`fontFamily: "Ubuntu"` and `fontSize: "22px"`; `arquitectura.mmd` uses the
same theme with `fontFamily: "Ubuntu"` and `fontSize: "18px"`, plus the
`look: handDrawn` snippet. The full `architecture-beta` body — groups,
services, `L`/`R`/`T`/`B` ports, `cloud`/`database`/`disk`/`internet`/`server`
icons, Iconify `logos:`/`mdi:` icons and the `junction` split — is in
`references/architecture.md`. The approved diagrams ship as
`examples/ciclo.mmd` and `examples/arquitectura.mmd`, each with its SVG and
PNG beside it.

**Animating the SVG in HyperFrames.** Mermaid's SVG carries stable ids:
flowchart boxes `my-svg-flowchart-<id>-<n>`, arrows
`my-svg-L_<from>_<to>_0`, arrow labels
`[data-id="L_<from>_<to>_0"]` and groups `my-svg-<id>`. In
`architecture-beta` the ids are `my-svg-group-<id>`, `my-svg-service-<id>`
and `my-svg-L_<from>_<to>_0`, and each arrowhead is the
`polygon.arrow` that follows its `path`. Animate arrows by driving
`strokeDashoffset`. Build the selectors by concatenating text: the
HyperFrames packager rejects `${}` templates. Declare the font as
`@font-face { src: local('Ubuntu') }`, the same family Mermaid measured the
boxes with; with a Google Fonts file a label overflows 2 px and `check`
fails. Mermaid writes `>` as `&gt;` inside the SVG `<style>`; the browser
accepts it but the HyperFrames CSS parser does not, so the runner decodes it
and strips the SVG's xmlns attributes when it inserts the SVG into
`index.html` at `<!-- DIAGRAM -->`. `build.mjs` only copies `index.tmpl` to
`index.html`, and the template must not be named `.html` — HyperFrames would
read it as a second composition.

## Judging the result

`verify` passes an SVG that carries an `<svg>` element and a PNG with a valid
signature. `preview` writes the image kind's fields — `preview`, `kind`,
`summary`, `name`, `prompt`, `seed`, `width`, `height` — deriving the prompt
from the diagram type line and a constant seed. A person then looks at the
PNG: overlaps, cut text and icon placement are judged by eye. Compare against
the approved diagrams in `examples/`, and use the hand-drawn render at
`examples/ciclo-mano.png` as the reference for `look: handDrawn`.

## Pitfalls

- **`fontFamily` takes one installed family.** A YAML list or `"Ubuntu Sans"`
  renders serif; write `fontFamily: "Ubuntu"`.
- **`direction` inside a linked subgraph is ignored.** Chain the boxes with
  invisible links (`a ~~~ b ~~~ c`) to keep them in a row.
- **`fontSize` for video.** The default is small at 1080p; the approved
  patterns use `fontSize: "22px"`.
- **A bottom port arrow crosses the service label.** Split the exit through a
  `junction`, as `arquitectura.mmd` does with `reparto`.
- **Chromium is pinned.** `facet pull mermaid` installs it once (~200 MB,
  shared by the three packages); the runner reads `FACET_BROWSER` and sets
  `PUPPETEER_SKIP_DOWNLOAD=1`.
