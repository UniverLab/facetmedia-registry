---
name: ascii
description: ASCII art from images and figlet banners in the lab's font, verified.
---
# ASCII

Turn images into ASCII art and write banners in the lab's figlet font.
Both capabilities write the `text` kind and are checked by `verify`.

## When to use

- `ascii.banner` for CLI and README banners in the lab's style. The
  default font `dos_rebel` is the font of the UniverLab README banners.
- `ascii.image` for text renderings of images: plates, diagrams, photos
  that must live in a terminal, a README, or a commit message.

## Pieces

Banner in the lab's font (`examples/banner-canopy.toml`):

```toml
[inputs]
text = "canopy"
name = "canopy"
```

Image to ASCII with shape matching (`examples/lamina.toml`):

```toml
[inputs]
image = "lamina.png"
width = 100
mode = "forma"
invert = true
name = "lamina"
```

Run it with `--out build/`: without it the rendered `<name>.png` lands
in the piece's directory and overwrites the source plate.

`ascii.image` also takes `invert` (light ink on a dark source) and
`color` (`none` or `ansi` 24-bit foreground). `ascii.banner` takes
`font` (`dos_rebel`, `ansi_shadow`, `standard`, `small`) and `width`.

## Judging the result

`ascii.image` re-renders the `.txt` as the art it is (glyphs for ASCII,
dot cells for braille, filled cells for `trazo`'s marks), downsamples
both it and the source to the grid, and reports the Pearson correlation
as `similarity`. It passes at `similarity_min = 0.55` with every line
exactly `columns` wide and the ink ratio between 0.02 and 0.98. When it
fails, change the mode before anything else: `forma` for shapes,
`trazo` for line art, `braille` for fine detail, `densidad` for photos.
`ascii.banner` passes when re-running pyfiglet gives the same bytes,
no line is wider than `width`, and one non-space character exists.
Read `columns`, `rows`, `similarity`, and `ink_ratio` from the generic
preview's `fields`. Size `width` against the terminal or README the
art goes into.

## Pitfalls

- DOS Rebel banners are recorded as non-commercial: the font file names
  its author and carries no licence, so check the terms before using a
  banner to sell something.
- `color = "ansi"` suits terminals only; committed files stay plain.
- Generated images hold no text or data: the `.png` is a rendering of
  the `.txt`, never a new source of words.
