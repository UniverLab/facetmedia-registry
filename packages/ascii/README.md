# ascii

ASCII art from images and figlet banners in the lab's font: `facet run
ascii.image` turns an image into text, `facet run ascii.banner` writes a
banner in the lab's figlet font (DOS Rebel by default). Both capabilities
write the `text` kind, show through the generic viewer, and are checked
by `verify`. CPU only, no network at run time: the only model is the
Sometype Mono font file, which arrives through `facet pull`.

## Capabilities and pieces

The fields below are what `facet describe ascii.image --json` and
`facet describe ascii.banner --json` report.

`ascii.image` — image to ASCII art (density, stroke, braille or shape
matching), checked by re-rendering:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `image` | path | yes | — | PNG, JPEG or WebP |
| `width` | integer | no | 80 | 16 to 400 columns |
| `mode` | enum | no | `forma` | `densidad`, `trazo`, `braille`, `forma` |
| `invert` | boolean | no | false | light ink on a dark source |
| `color` | enum | no | `none` | `none` or `ansi` 24-bit foreground |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*` |

`ascii.banner` — a text banner in the lab's figlet font:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `text` | string | yes | — | 1 to 40 characters |
| `font` | enum | no | `dos_rebel` | `dos_rebel`, `ansi_shadow`, `standard`, `small` |
| `width` | integer | no | 120 | 20 to 400, maximum line width |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*` |

Rows sample at half the column density: each row covers twice the height
of a column's width. `forma` renders each printable ASCII character in
Sometype Mono and picks, per cell, the glyph with the smallest squared
difference to the cell, vectorised as one glyph-bitmap matrix against
all cells. `run` writes `<name>.txt` always (plain), `<name>.ans` when
`color = "ansi"`, `<name>.png` rendering the text with Sometype Mono
(black on white, white on black when `invert`), and for banners
`<name>.svg` with one `<rect>` per non-space cell in `currentColor`
(`█` solid, `░` at 0.35 opacity, anything else at 0.7), needing no font.

## Verification and doctor

`ascii.image` re-renders `<name>.txt` as the art it is — Sometype Mono
glyphs for ASCII, decoded dot cells for braille, filled cells for
`trazo`'s marks — downsamples both it and the source to the grid, and
reports the Pearson correlation as `similarity`. It passes at
`similarity_min = 0.55` with every line exactly `columns` wide and the
ink ratio between 0.02 and 0.98, reporting `similarity`, `ink_ratio`,
`columns`, `rows`. `ascii.banner` passes when re-running pyfiglet gives
the same bytes, no line is wider than `width`, and one non-space
character exists, reporting `columns`, `rows`. The generic preview
(`<name>.txt.preview.json`) carries `columns`, `rows`, the mode or font,
and for images the verification metrics:

```json
{"fields": {"charset_size": 95, "columns": 100, "ink_ratio": 0.7192, "mode": "forma", "rows": 50, "similarity": 0.9625421776568691}, "kind": "text", "preview": 1, "summary": "100×50 · forma · similarity 0.96"}
```

```json
{"fields": {"columns": 60, "font": "dos_rebel", "rows": 9}, "kind": "text", "preview": 1, "summary": "DOS Rebel · 60×9"}
```

`facet doctor ascii` runs the package's own checks:

- `imports` (quick): Pillow, NumPy and pyfiglet import, with versions.
- `figlet_font` (quick): `dos_rebel` is in pyfiglet's fonts.
- `mono_font` (quick): Sometype Mono exists with its manifest size and
  opens with Pillow.
- `banner` (full): rendering `A` in `dos_rebel` gives non-empty lines.
- `image` (full): an 8x8 gradient converts with `forma` to an 8-column grid.

Every failing check names `facet pull ascii` as its fix.

## Licences

The tool chain is Pillow (MIT-CMU), NumPy (BSD-3-Clause) and pyfiglet (MIT).
The render font Sometype Mono is OFL-1.1 and commercial use is allowed.
The DOS Rebel figlet font ships bundled inside pyfiglet: its font file
names its author (Valerie Mates, 1994, after a font by Ron Bliss) and
carries no licence text, so the manifest records it as
`LicenseRef-DOS-Rebel-unspecified` and banners in this font are recorded
as non-commercial until the terms are confirmed — check before using one
to sell something.

## Examples

`examples/banner-canopy.toml` writes the lab wordmark (9 rows x 60
columns, byte-identical to the UniverLab README banner):

```toml
[inputs]
text = "canopy"
name = "canopy"
```

Its record (`canopy.txt.facet.json`, beside the asset; abridged here —
the file also carries the record version, the asset path, the creation
time, the facet and registry provenance, the model provenance, the
params digest, the input files and the licence section):

```json
{"bytes": 1178, "id": "sha256:d7849983b179b9bf052bae59e8446dd8079de6cb207642c7575791d3120f26bf", "kind": "text", "mime": "text/plain", "name": "canopy", "properties": {"columns": 60, "font": "dos_rebel", "rows": 9}, "provenance": {"capability": "ascii.banner", "params": {"font": "dos_rebel", "name": "canopy", "text": "canopy", "width": 120}, "package": {"name": "ascii", "version": "0.1.0"}, "tool": {"name": "facet ascii (Pillow, NumPy, pyfiglet)", "version": "0.1.0"}}, "verification": {"metrics": {"columns": 60, "rows": 9}, "status": "passed", "thresholds": {}, "verifier": "ascii-pyfiglet"}}
```

`examples/lamina.toml` converts a 512 px crop of one machine plate
(`examples/lamina.png`, 165 KB) with shape matching on a dark source.
Its `name` differs from the source's stem, so the rendered
`lamina-ascii.png` lands beside the plate instead of over it.

```toml
[inputs]
image = "lamina.png"
width = 100
mode = "forma"
invert = true
name = "lamina-ascii"
```

Its record (`lamina-ascii.txt.facet.json`, beside the asset; abridged here,
with the same extra sections as the banner's record above):

```json
{"bytes": 5050, "id": "sha256:87d18776d1f2000ed91520cad4c900e9385f3af04aefb10869f1ad0920d72896", "kind": "text", "mime": "text/plain", "name": "lamina-ascii", "properties": {"charset_size": 95, "columns": 100, "mode": "forma", "rows": 50}, "provenance": {"capability": "ascii.image", "params": {"color": "none", "image": "lamina.png", "invert": true, "mode": "forma", "name": "lamina-ascii", "width": 100}, "package": {"name": "ascii", "version": "0.1.0"}, "tool": {"name": "facet ascii (Pillow, NumPy, pyfiglet)", "version": "0.1.0"}}, "verification": {"metrics": {"columns": 100, "ink_ratio": 0.7192, "rows": 50, "similarity": 0.9625421776568691}, "status": "passed", "thresholds": {"similarity_min": 0.55}, "verifier": "ascii-rerender"}}
```
