# Viewers

A **viewer** is the person-facing half of a preview: a static web app facet
serves on `127.0.0.1` when you run `facet preview <asset>`. One viewer per
asset **kind** (`audio`, `text`, `cad`, ...), named after the kind:
`viewers/<kind>/`. facet picks the viewer from the asset's kind, the same way
it picks the preview schema from `schemas/preview/<kind>.schema.json`. The
preview contract is defined by the core:
[docs/preview.md](https://github.com/UniverLab/facetmedia/blob/main/docs/preview.md).

## Rules

- **Static web apps only.** ES modules loaded directly by the browser — no
  build step, no bundler, no framework toolchain, no `node_modules`.
- **No network requests.** A viewer renders what the preview file and the
  files beside the asset give it; it never fetches anything beyond those
  local files.
- **Share `viewers/_kit/`.** Common helpers (loading `<asset>.preview.json`,
  formatting, layout) live in `viewers/_kit/` and are imported by every
  viewer; a viewer is the kind-specific part only.
- **One viewer per kind.** A new kind adds its preview schema in
  `schemas/preview/` and its viewer here, in the same change as the first
  package that writes that kind.

## Layout

```text
viewers/
├── _kit/               # shared ES modules: preview loading, formatting, layout
└── <kind>/
    ├── index.html      # the viewer's entry point
    └── *.js            # ES modules, no build step
```
