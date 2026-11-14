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

The seven tokens are the only colours a viewer's CSS or JS may use; the check in
`tests/test_viewers_look.py` fails on a hex colour or an `rgb(` anywhere in
`viewers/` outside `_kit/base.css`. `--slide-black` is reserved for the letterbox
behind a slide deck or a clip: only the slides and video viewers may name it, and
only there — the slides audience window and blackout, and the video stage.

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
1280x800 and 390x844, exercises the audio play/pause, click, drag and arrow
seek and its metric lines, the CAD views from a click and from the keyboard
and the measures beside their expectations, the document's page step and jump
with its PDF link, the image's fit/1:1 toggle, pan and the checkerboard it
draws over a transparent cut-out, the video clip's play, scrub and frame step,
the GIF's line, the generic text, JSON, subtitle (SRT and VTT), ASCII and copy
branches, and the gallery's kind filter, open link and back button, fails on
any console error, page error, failed request or HTTP status >= 400, and saves
a screenshot of each case under `_examples/<kind>/screens/` (gitignored). A
kind with more than one example asset (`video` with its GIF, `generic` with
its JSON, SRT, VTT, ASCII and banner files, `image` with a photo and a
transparent cut-out) is opened once per asset, the name swapped in the URL.

Every viewer that renders one asset (`audio`, `cad`, `document`, `generic`,
`image`, `video`, `slides`) opens with the same header line, `_kit/header.js`:
`facetMedia · <capability id> · <asset name>` in Sometype Mono, with
`facetMedia` in Hueso, and the verification verdict at the right — `✓ passed`
in Señal, `✗ failed` in Hueso tenue — above a thin `--regla` rule. Below it:
the metrics against their thresholds, the licences with a visible
`non-commercial` badge when the tool's licence or a model's forbids commercial
use, and the provenance (capability, package version, registry commit, models,
parameters) collapsed. The gallery browses a folder rather than one asset, so
it opens with that folder's name and its asset count instead, and each card
carries its own `✓ verified` or `✗ failed`.

The viewers here are `generic` (any preview: summary, fields, the asset — and a
real branch for the text kinds: numbered lines for `text/plain`, pretty-printed
`application/json`, a time-and-text cue list for `application/x-subrip` and
`text/vtt`, and ASCII art at its natural width with a sideways scroll when the
record carries `columns`, each with a copy button), `gallery` (a whole folder
from `facet preview <folder>`: one card per asset, filterable by kind, each
opening its own viewer), `audio` (a play/pause button and space, a waveform with
silences and the played part in Hueso over the rest in Hueso tenue, scrubbable
by click and drag, the time in Sometype Mono with ←/→ seeking a second, the
momentary loudness against its dashed target, the integrated LUFS, true peak,
duration, sample rate and `peak_limited`, and the speech alignment), `cad`
(every view the preview lists as a large panel that enlarges from a click or
Enter, the solid's measures beside the volume and bounding box its parameters
expected, the drawing's layers and audit), `document` (a paginated PDF page by page:
thumbnails, the selected page, the PDF a click away), `image` (the still fitted
by default, 1:1 pixels on a click or Z with a drag to pan, a checkerboard behind
transparent PNGs, its pixels and file size), `video` (by the record's mime: a
clip letterboxed on the slide black with play/pause, a scrub bar, the time and
the frame number, `,`/`.` stepping a frame and F for full screen; a GIF looped
on the same stage with its `GIF · loops · <frames> frames · <fps> fps` line; a
file the browser cannot play falling back to the preview's first image or its
kind, with the asset one click away; resolution, fps, frames, duration and any
audio streams and loudness the record verifies) and `slides` (a deck's preview as
its presentation player: the default surface with the current slide, a
thumbnail strip and a `present` action; `?role=audience` for the full-screen
audience window; `?role=presenter` for the current and next slides with notes,
a counter and a clock, synced over a `BroadcastChannel`); each has a runnable
example under `_examples/`.
