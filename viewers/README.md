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

## Look

Every viewer wears facet's night surface, as the facet brand manual
(internal-docs, `brand/facet`, version 0.4, 2026-11-13) fixes it:

- **One surface, always night.** `--fondo` is `#161616`: a terminal in a night
  gallery. There is no light variant and no `prefers-color-scheme` switch.
- **One text colour.** `--hueso` (`#e7ded1`) for text, `--hueso-tenue`
  (`#9a938a`) for secondary text. Rules and borders are `--regla` (Hueso at
  16% alpha) and raised areas `--panel` (Hueso at 4%).
- **One accent, `--senal` (`#e8c547`),** which marks only what is verified: a
  check that passed, a measure in range, an accepted licence. It appears a
  few times per screen and is never decoration. A failure is the word
  `failed` with a `✗`, in Hueso tenue — never a red.
- **Three faces,** vendored as `.ttf` under `_kit/fonts/` from `google/fonts`
  at commit `8b0a1d0`, each folder with its `OFL.txt`: Old Standard TT for
  titles, EB Garamond for long text, and Sometype Mono for every label,
  metric, file name, capability id, number and date.
- **Facets are lines, never coloured cards:** one line per facet, separated
  by `--regla`.
- **The grain** (`_kit/grain.js`): a fixed canvas behind the content, grey
  between 40 and 240, alpha 0.085, redrawn every 90 ms at a quarter of the
  viewport's resolution and scaled up without smoothing. It never covers the
  text. Under `prefers-reduced-motion: reduce` it is drawn once and stays
  still.

The six tokens are the only colours a viewer's CSS or JS may use; the check in
`tests/test_viewers_look.py` fails on a hex colour or an `rgb(` anywhere in
`viewers/` outside `_kit/base.css`.

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
  kind is what picks it. A kind the core previews itself needs neither: the
  `document` kind (a paginated PDF plus one PNG per page) has no schema here,
  and its viewer shows the pages the preview lists.

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
`/viewer/`, `/kit/` and `/asset/` on 127.0.0.1 (the same routes
`facet preview` serves) and prints the URL to open. The `gallery` example has
a folder rather than one asset, so it also answers `/gallery.json`,
`/thumb/<n>` and `/open/<n>`, the routes `facet preview <folder>` serves. Check
them by hand with `node scripts/check-viewers.mjs [kind ...]`: with
`playwright-core` resolvable and the system Chrome, it opens each example
under both colour-scheme preferences (the surface stays night either way) at
1280x800 and 390x844, exercises the audio click-to-seek, the
CAD view enlargement, the image enlargement and the gallery's kind filter,
open link and back button, fails on any console error, page error, failed
request or HTTP status >= 400, and saves a screenshot of each case under
`_examples/<kind>/screens/` (gitignored).

Every viewer that renders one asset (`audio`, `cad`, `document`, `generic`,
`image`, `video`) opens with the same header line, `_kit/header.js`:
`facetMedia · <capability id> · <asset name>` in Sometype Mono, with
`facetMedia` in Hueso, and the verification verdict at the right — `✓ passed`
in Señal, `✗ failed` in Hueso tenue — above a thin `--regla` rule. Below it:
the metrics against their thresholds, the licences with a visible
`non-commercial` badge when the tool's licence or a model's forbids commercial
use, and the provenance (capability, package version, registry commit, models,
parameters) collapsed. The gallery browses a folder rather than one asset, so
it opens with that folder's name and its asset count instead, and each card
carries its own `✓ verified` or `✗ failed`.

The viewers here are `generic` (any preview: summary, fields, the asset),
`gallery` (a whole folder from `facet preview <folder>`: one card per asset,
filterable by kind, each opening its own viewer), `audio` (player, waveform
with silences and the playhead, loudness against the target, speech
alignment), `cad` (views that enlarge, solid and drawing measurements),
`document` (a paginated PDF page by page: thumbnails, the selected page, the
PDF a click away), `image` (the still itself, click to enlarge, with its
prompt, seed and pixel size) and `video` (the clip in a player, with its
motion prompt, seed, frame count and rate); each has a runnable example under
`_examples/`.
