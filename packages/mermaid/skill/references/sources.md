# Sources behind the mermaid skill

Every tip in this skill is written in facet's own words. No passage is quoted
from these sources; only facts and practices are taken from them.

| # | URL | Maintainer | Licence | Taken |
|---|-----|------------|---------|-------|
| S4 | https://mermaid.js.org/intro/syntax-reference.html | mermaid-js | None stated on page | Frontmatter config form; breakage-word behavior (`end`, `o`/`x` ids); unknown keys ignored silently. |
| S5 | https://mermaid.js.org/config/theming.html | mermaid-js | None stated on page | v12 default theme/look/layout per diagram type; reverting to the older appearance; `base` as the customizable theme. |
| S6 | https://raw.githubusercontent.com/mermaid-js/mermaid-cli/master/README.md | mermaid-js | None stated on page | Renderer flags facet does not expose (dark/transparent backgrounds, stylesheet, sizing) — documented as out of surface. |
| S7 | https://mermaid.js.org/syntax/flowchart.html | mermaid-js | None stated on page | `end`/`o`/`x` parse breakage; unicode and Markdown label quoting; v12 default appearance. |
| S8 | https://mermaid.js.org/syntax/architecture.html | mermaid-js | None stated on page | `align row\|column` directives; fcose spacing knobs; `seed` determinism semantics. |
| S9 | https://mermaid.js.org/syntax/mindmap.html | mermaid-js | None stated on page | Depth-based coloring and the gradient caveat under the base theme. |
| S10 | https://mermaid.js.org/syntax/timeline.html | mermaid-js | None stated on page | Top-down direction and line-break wrapping in timelines. |
| S-seq | https://mermaid.js.org/syntax/sequenceDiagram.html | mermaid-js | None stated on page | Explicit participant ordering, `actor`, `autonumber`, activate/deactivate, typed participants. |
