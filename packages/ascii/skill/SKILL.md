---
name: ascii
description: ASCII art from images and figlet banners in the lab's font, verified.
---
# ASCII

Turn images into ASCII art, write banners in any figlet font, and list
every available font. All three capabilities write the `text` kind and
are checked by `verify`.

## When to use

- `ascii.banner` for CLI and README banners in the lab's style. The
  default font `dos_rebel` is the font of the UniverLab README banners.
  Any pyfiglet or figlet.js font works, for example
  `font = "Linguaholic Mini Block"`.
- `ascii.fonts` to see the full font list with its source, and a contact
  sheet of every font. Run it before picking an unfamiliar name.
- `ascii.image` for text renderings of images: plates, diagrams, photos
  that must live in a terminal, a README, or a commit message.

## Pieces

Banner in the lab's font (`examples/banner-canopy.toml`):

```toml
[inputs]
text = "canopy"
name = "canopy"
```

Banner in a figlet.js font (`font` takes any name `ascii.fonts` lists):

```toml
[inputs]
text = "canopy"
font = "Linguaholic Mini Block"
name = "canopy-lingua"
```

Every font, with a contact sheet (`examples/fonts-facet.toml`):

```toml
[inputs]
text = "facet"
name = "fonts"
```

It writes `fonts.txt` (`<name> (<source>)` per font) and `fonts.png`.

Sample before choosing: note the intended look first, then render the
text in every candidate font and compare each render against it — the
fonts sheet is the sampler, so never guess a font name. For images,
render the candidate modes and compare before committing.

Image to ASCII with shape matching (`examples/plate.toml`):

```toml
[inputs]
image = "plate.png"
width = 100
mode = "shape"
invert = true
name = "plate-ascii"
```

Run it with `--out build/`: without it the rendered `<name>.png` lands
in the piece's directory and overwrites the source plate.

`ascii.image` also takes `invert` (light ink on a dark source) and
`color` (`none` or `ansi` 24-bit foreground). `ascii.banner` takes
`font` and `width`. Font names ignore case, and spaces, hyphens and
underscores are equal, so `Linguaholic Mini Block`,
`linguaholic-mini-block` and `linguaholic_mini_block` are one font; when
pyfiglet and figlet.js both have a name, pyfiglet wins. An unknown name
is refused before rendering with `unknown font "<name>"; closest: <five
closest names>; list them with facet run ascii.fonts` — that surfaces as
`runner_failed` (exit 9) and writes no file.

## Judging the result

`ascii.image` re-renders the `.txt` as the art it is (glyphs for ASCII,
dot cells for braille, filled cells for `stroke`'s marks), downsamples
both it and the source to the grid, and reports the Pearson correlation
as `similarity`. It passes at `similarity_min = 0.55` with every line
exactly `columns` wide and the ink ratio between 0.02 and 0.98. When it
fails, change the mode before anything else: `shape` for shapes,
`stroke` for line art, `braille` for fine detail, `density` for photos.
`ascii.banner` passes when re-rendering the resolved font gives the same
bytes, no line is wider than `width`, and one non-space character exists.
`ascii.fonts` passes when `fonts.txt` and `fonts.png` exist and the
sheet's recorded font count equals the list's line count.
Read `columns`, `rows`, `similarity`, and `ink_ratio` from the generic
preview's `fields`. Size `width` against the terminal or README the
art goes into. Judge every render in a monospaced viewer or in the
re-rendered PNG only: a proportional font misrepresents spacing and
alignment, so judgement there is invalid. Pin `width` and `mode` for
runs that must reproduce: the same inputs give the same bytes, so
record both beside any committed art. A banner passes when re-rendering
the resolved font gives the same bytes, which is the identical-output
discipline the underlying engine aims for — a mismatch against real
FIGlet is a bug signal, not a style choice.

## Pitfalls

- An unknown `font` fails the run, it does not fall back to DOS Rebel.
  Run `ascii.fonts` first and copy the name exactly.
- The figlet.js collection is MIT at the repository level, but each font
  file keeps its own header note; check that note for commercial use.
- DOS Rebel banners are recorded as non-commercial: the font file names
  its author and carries no licence, so check the terms before using a
  banner to sell something.
- `color = "ansi"` suits terminals only; committed files stay plain.
- Generated images hold no text or data: the `.png` is a rendering of
  the `.txt`, never a new source of words.
- Divergence: the underlying engine also reads installed `.flf` files
  from system directories, but facet exposes only the fonts
  `ascii.fonts` lists, so runs stay reproducible.

Sources: [references/sources.md](references/sources.md) lists the public
sources the guidance above draws on, with their licences.
