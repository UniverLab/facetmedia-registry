---
name: mermaid
description: Render a .mmd Mermaid diagram to SVG and PNG with the pinned mermaid-cli and the system Chrome, never a downloaded browser.
---
# Mermaid

`mermaid.diagrama` turns a `.mmd` file into an SVG and a 2x PNG through the
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
- When the host has a system Chrome at `CHROME_PATH`; the package never
  downloads a browser.

## Pieces

```toml
[inputs]
diagrama = "ciclo.mmd"
```

`diagrama` names the `.mmd` file resolved relative to the piece. Its YAML
header carries `config.theme`, `config.themeVariables` (`primaryColor`,
`lineColor`, `fontFamily`, `fontSize`) and optionally `look: handDrawn` for
the Excalidraw-style drawing. `run` writes `<name>.svg` and `<name>.png`
beside each other in the output directory; `verify` checks the SVG element
and the PNG signature; `preview` writes the image kind's preview file.

## Judging the result

`verify` passes an SVG that carries an `<svg>` element and a PNG with a valid
signature. `preview` writes the image kind's fields — `preview`, `kind`,
`summary`, `name`, `prompt`, `seed`, `width`, `height` — deriving the prompt
from the diagram type line and a constant seed. A person then looks at the
PNG: overlaps, cut text and icon placement are judged by eye. The approved
references are `ciclo.mmd` and `arquitectura.mmd` under the lab's
`projects/prueba-diagramas/`.

## Pitfalls

- **`fontFamily` takes one installed family.** A YAML list or `"Ubuntu Sans"`
  renders serif; write `fontFamily: "Ubuntu"`.
- **`direction` inside a linked subgraph is ignored.** Chain the boxes with
  invisible links (`a ~~~ b ~~~ c`) to keep them in a row.
- **`fontSize` for video.** The default is small at 1080p; the approved
  patterns use `fontSize: "22px"`.
- **A bottom port arrow crosses the service label.** Split the exit through a
  `junction`, as `arquitectura.mmd` does with `reparto`.
- **Chrome is the host's.** Set `CHROME_PATH=/usr/bin/google-chrome`; the
  runner sets `PUPPETEER_SKIP_DOWNLOAD=1` and never pulls a browser.
