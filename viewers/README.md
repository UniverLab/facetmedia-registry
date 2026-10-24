# Viewers

A **viewer** is the person-facing half of a preview: a static web app facet
serves on `127.0.0.1` when you run `facet preview <asset>`. A capability picks
its viewer with `[capabilities.<c>.preview] viewer`; the core's default is
`generic`, so a package must name the viewer it wants. In this registry a
viewer is named after the asset **kind** it renders (`audio`, `text`, `cad`,
...) — `viewers/<kind>/` — and each capability that writes that kind sets
`viewer = "<kind>"`. A viewer the registry does not have falls back to
`generic`. The preview contract is defined by the core:
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
  package that writes that kind — and the capability names that viewer, so the
  kind is what picks it.

## Layout

```text
viewers/
├── _kit/               # shared CSS + ES modules: tokens, loading, header, plots
├── _examples/<kind>/   # fake asset + .facet.json + .preview.json; screens/ is local
└── <kind>/
    ├── index.html      # the viewer's entry point
    └── *.js            # ES modules, no build step
```

Try one without a package: `python3 scripts/serve-example.py <kind>` serves
`/viewer/`, `/kit/` and `/asset/` on 127.0.0.1 (the same three routes
`facet preview` serves) and prints the URL to open. Check them by hand with
`node scripts/check-viewers.mjs [kind ...]`: with `playwright-core`
resolvable and the system Chrome, it opens each example in light and dark at
1280x800 and 390x844, exercises the audio click-to-seek and the CAD view
enlargement, fails on any console error, page error, failed request or HTTP
status >= 400, and saves a screenshot of each case under
`_examples/<kind>/screens/` (gitignored).

Every viewer opens with the same header, `_kit/header.js`: the asset's name
and kind, the verification verdict with its metrics against their
thresholds, the licences with a visible `non-commercial` badge when the
tool's licence or a model's forbids commercial use, and the provenance
(capability, package version, registry commit, models, parameters)
collapsed.

The viewers here are `generic` (any preview: summary, fields, the asset),
`audio` (player, waveform with silences and the playhead, loudness against the
target, speech alignment) and `cad` (views that enlarge, solid and drawing
measurements); each has a runnable example under `_examples/`.
