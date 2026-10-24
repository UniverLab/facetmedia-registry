"""Pure ASCII-art helpers: no facet imports, only Pillow, NumPy, pyfiglet.

Four modes turn a greyscale source into text rows sampled at half the
column density (each row covers twice the height of a column's width):

- ``densidad`` maps brightness through a dark-to-light ramp;
- ``trazo`` maps Sobel edges to stroke directions, flat areas to dots;
- ``braille`` thresholds each cell's 2x4 sub-blocks into a braille cell;
- ``forma`` picks, per cell, the Sometype Mono glyph whose rendered
  bitmap has the smallest mean squared difference to the cell.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import numpy as np
import pyfiglet
from PIL import Image, ImageDraw, ImageFont

#: Dark-to-light ramp for ``densidad`` (index 0 is the darkest ink).
RAMP = "@%#*+=-:. "
#: Braille dot bit per (row, column) inside a 4x2 cell; base is U+2800.
BRAILLE_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))
BRAILLE_BASE = 0x2800
#: Stroke characters for ``trazo`` by edge direction bin: the stroke runs
#: perpendicular to the gradient, so a vertical edge gets ``│``.
STROKES = ("─", "╲", "│", "╱")
#: Half a direction bin in degrees: a stroke rounds to the nearest 45°.
STROKE_OFFSET = 22.5
#: Width of one stroke direction bin in degrees.
STROKE_STEP = 45.0
#: Rows sample at half the column density: each cell is twice as tall.
ASPECT = 0.5
#: Below this Sobel magnitude a trazo cell is flat (dot or blank).
TRAZO_FLAT = 0.10
#: At or above this magnitude a trazo edge gets a stroke, else a dot.
TRAZO_STRONG = 0.25
#: Mid grey: darker than this is ink, lighter is paper.
MID_GREY = 0.5
#: Pixel size the Sometype Mono atlas and the PNG render use.
FONT_SIZE = 32
#: Printable ASCII, the only characters the ``forma`` atlas holds.
GLYPHS = [chr(code) for code in range(0x20, 0x7F)]
#: Display names for the banner fonts.
FONT_NAMES = {
    "dos_rebel": "DOS Rebel",
    "ansi_shadow": "ANSI Shadow",
    "standard": "Standard",
    "small": "Small",
}


def load_image(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Greyscale (0..1, 0 is black) and RGB arrays of an image file."""
    image = Image.open(path).convert("RGB")
    rgb = np.asarray(image, dtype=np.float64) / 255.0
    grey = rgb @ np.array([0.2126, 0.7152, 0.0722])
    return grey, (rgb * 255.0 + 0.5).astype(np.uint8)


def grid_shape(img_w: int, img_h: int, width: int) -> tuple[int, int]:
    """``(columns, rows)`` for an image at the requested column count."""
    rows = max(1, round(img_h * width / (2.0 * img_w)))
    return width, rows


def sample_grid(grey: np.ndarray, width: int) -> np.ndarray:
    """Downsample a 0..1 grey array to its ``(rows, columns)`` grid."""
    _, rows = grid_shape(grey.shape[1], grey.shape[0], width)
    small = Image.fromarray((grey * 255.0 + 0.5).astype(np.uint8)).resize(
        (width, rows), Image.BILINEAR
    )
    return np.asarray(small, dtype=np.float64) / 255.0


def sample_color(rgb: np.ndarray, width: int) -> np.ndarray:
    """Mean RGB colour per grid cell as a ``(rows, columns, 3)`` array."""
    _, rows = grid_shape(rgb.shape[1], rgb.shape[0], width)
    small = Image.fromarray(rgb).resize((width, rows), Image.BILINEAR)
    return np.asarray(small, dtype=np.uint8)


def to_densidad(grey: np.ndarray, width: int) -> list[str]:
    """Map each grid cell's brightness through :data:`RAMP`."""
    grid = sample_grid(grey, width)
    n = len(RAMP)
    cells = np.clip((grid * n).astype(int), 0, n - 1)
    return ["".join(RAMP[i] for i in row) for row in cells]


def stroke_index(dy: float, dx: float) -> int:
    """The :data:`STROKES` bin for a gradient, perpendicular to the edge.

    ``dy`` and ``dx`` are the Sobel components; the stroke follows the
    edge, which runs at right angles to the gradient, so the bin is read
    from ``atan2(dy, dx) + 90`` folded into ``[0, 180)``.
    """
    degrees = (np.degrees(np.arctan2(dy, dx)) + 90.0) % 180.0
    return int((degrees + STROKE_OFFSET) // STROKE_STEP) % len(STROKES)


def to_trazo(grey: np.ndarray, width: int) -> list[str]:
    """Map Sobel edges to stroke directions, flat cells to dots or blanks."""
    grid = sample_grid(grey, width)
    dy, dx = np.gradient(grid)
    magnitude = np.hypot(dx, dy)
    lines: list[str] = []
    for r in range(grid.shape[0]):
        row: list[str] = []
        for c in range(grid.shape[1]):
            if magnitude[r, c] < TRAZO_FLAT:
                row.append("·" if grid[r, c] < MID_GREY else " ")
                continue
            stroke = STROKES[stroke_index(dy[r, c], dx[r, c])]
            row.append(stroke if magnitude[r, c] >= TRAZO_STRONG else "·")
        lines.append("".join(row))
    return lines


def to_braille(grey: np.ndarray, width: int) -> list[str]:
    """Threshold each cell's 2x4 sub-blocks into one braille character."""
    columns, rows = grid_shape(grey.shape[1], grey.shape[0], width)
    fine = Image.fromarray((grey * 255.0 + 0.5).astype(np.uint8)).resize(
        (columns * 2, rows * 4), Image.BILINEAR
    )
    dots = (np.asarray(fine, dtype=np.float64) / 255.0 < MID_GREY).reshape(rows, 4, columns, 2)
    weights = np.array(BRAILLE_BITS)
    codes = BRAILLE_BASE + (dots * weights[None, :, None, :]).sum(axis=(1, 3))
    return ["".join(chr(code) for code in row) for row in codes]


class Atlas(NamedTuple):
    """The ``forma`` glyph atlas: characters and their ink bitmaps."""

    chars: list[str]
    maps: np.ndarray  # float (n_chars, cell_h, cell_w), 1 is ink
    cell_w: int
    cell_h: int


def glyph_atlas(font_path: str | Path, size: int = FONT_SIZE) -> Atlas:
    """Render every printable ASCII glyph into ``(advance, line height)`` cells.

    Returns the atlas, pasting each glyph's ink at the baseline into a
    cell of the font's advance width by line height, never stretching it.
    """
    font = ImageFont.truetype(str(font_path), size)
    ascent, _descent = font.getmetrics()
    cell_w = max(1, int(round(font.getlength("M"))))
    cell_h = ascent + _descent
    maps = np.zeros((len(GLYPHS), cell_h, cell_w), dtype=np.float64)
    for i, char in enumerate(GLYPHS):
        cell = Image.new("L", (cell_w, cell_h), 255)
        ImageDraw.Draw(cell).text((0, 0), char, font=font, fill=0, anchor="la")
        maps[i] = 1.0 - np.asarray(cell, dtype=np.float64) / 255.0
    return Atlas(GLYPHS, maps, cell_w, cell_h)


def cell_inks(grey: np.ndarray, width: int, atlas: Atlas) -> np.ndarray:
    """Downsample a 0..1 grey array to one ink cell per grid cell."""
    columns, rows = grid_shape(grey.shape[1], grey.shape[0], width)
    wide = Image.fromarray((grey * 255.0 + 0.5).astype(np.uint8)).resize(
        (columns * atlas.cell_w, rows * atlas.cell_h), Image.BILINEAR
    )
    cells = np.asarray(wide, dtype=np.float64) / 255.0
    return 1.0 - cells.reshape(rows, atlas.cell_h, columns, atlas.cell_w).transpose(0, 2, 1, 3)


def to_forma(grey: np.ndarray, width: int, atlas: Atlas) -> list[str]:
    """Pick per cell the atlas glyph with the smallest squared difference.

    One matrix of glyph bitmaps against all cells: a single matmul gives
    every glyph-to-cell squared distance, the argmin per cell is the art.
    """
    inks = cell_inks(grey, width, atlas)
    rows, columns = inks.shape[0], inks.shape[1]
    flat_glyphs = atlas.maps.reshape(len(atlas.chars), -1)
    flat_cells = inks.reshape(rows * columns, -1)
    glyph_sq = (flat_glyphs**2).sum(axis=1)[:, None]
    cell_sq = (flat_cells**2).sum(axis=1)[None, :]
    best = np.argmin(glyph_sq - 2.0 * flat_glyphs @ flat_cells.T + cell_sq, axis=0)
    picked = [atlas.chars[i] for i in best.tolist()]
    return ["".join(picked[r * columns : (r + 1) * columns]) for r in range(rows)]


def shape_error(grey: np.ndarray, width: int, atlas: Atlas, lines: list[str]) -> float:
    """Mean per-cell bitmap squared error of rendered lines (``forma`` wins)."""
    inks = cell_inks(grey, width, atlas)
    rows, columns = inks.shape[0], inks.shape[1]
    table = {char: atlas.maps[i] for i, char in enumerate(atlas.chars)}
    blank = np.zeros((atlas.cell_h, atlas.cell_w), dtype=np.float64)
    total = 0.0
    for r in range(rows):
        for c in range(columns):
            glyph = table.get(lines[r][c], blank)
            diff = glyph - inks[r, c]
            total += float((diff * diff).mean())
    return total / max(1, rows * columns)


#: The ``trazo`` marks: they fill their cell when the art is re-rendered.
STROKE_CHARS = frozenset("─╲│╱·")


def braille_dots(char: str) -> np.ndarray | None:
    """The 4x2 dot bits of a braille character, or None outside U+2800."""
    code = ord(char)
    if not BRAILLE_BASE <= code <= BRAILLE_BASE + 0xFF:
        return None
    value = code - BRAILLE_BASE
    return np.array([[bool(value & bit) for bit in row] for row in BRAILLE_BITS])


def braille_cell(dots: np.ndarray, atlas: Atlas) -> np.ndarray:
    """One braille character as ink: its 4x2 dots padded into the cell."""
    sub_h, sub_w = atlas.cell_h // 4, atlas.cell_w // 2
    return np.pad(
        np.kron(dots, np.ones((sub_h, sub_w))),
        ((0, atlas.cell_h - 4 * sub_h), (0, atlas.cell_w - 2 * sub_w)),
    )


def cell_bitmap(
    char: str, glyphs: dict[str, np.ndarray], atlas: Atlas, blank: np.ndarray, solid: np.ndarray
) -> np.ndarray:
    """One character's ink cell: an atlas glyph, braille dots, a stroke, blank.

    Every mode the package emits is re-renderable: ``densidad`` and
    ``forma`` are printable ASCII, ``braille`` decodes to its dot bits,
    and ``trazo``'s marks fill their cell.
    """
    glyph = glyphs.get(char)
    if glyph is not None:
        return glyph
    dots = braille_dots(char)
    if dots is not None:
        return braille_cell(dots, atlas)
    return solid if char in STROKE_CHARS else blank


def render_text_bitmap(lines: list[str], atlas: Atlas) -> np.ndarray:
    """Re-render text lines as the art they are (unknown characters blank)."""
    rows = len(lines)
    columns = max((len(line) for line in lines), default=0)
    glyphs = {char: atlas.maps[i] for i, char in enumerate(atlas.chars)}
    blank = np.zeros((atlas.cell_h, atlas.cell_w), dtype=np.float64)
    solid = np.ones((atlas.cell_h, atlas.cell_w), dtype=np.float64)
    canvas = np.zeros((rows * atlas.cell_h, columns * atlas.cell_w), dtype=np.float64)
    for r, line in enumerate(lines):
        for c in range(columns):
            char = line[c] if c < len(line) else " "
            canvas[
                r * atlas.cell_h : (r + 1) * atlas.cell_h,
                c * atlas.cell_w : (c + 1) * atlas.cell_w,
            ] = cell_bitmap(char, glyphs, atlas, blank, solid)
    return 1.0 - canvas  # back to grey: 0 is black, 1 is white


def downsample_to_grid(grey: np.ndarray, columns: int, rows: int) -> np.ndarray:
    """Downsample a 0..1 grey array to exactly ``(rows, columns)``."""
    small = Image.fromarray((grey * 255.0 + 0.5).astype(np.uint8)).resize(
        (columns, rows), Image.BILINEAR
    )
    return np.asarray(small, dtype=np.float64) / 255.0


def pearson(first: np.ndarray, second: np.ndarray) -> float:
    """Pearson correlation of two grids, 0.0 when either side is flat."""
    a = first.reshape(-1).astype(np.float64)
    b = second.reshape(-1).astype(np.float64)
    a -= a.mean()
    b -= b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denom == 0.0:
        return 0.0
    return float((a * b).sum() / denom)


def ink_ratio(lines: list[str]) -> float:
    """Fraction of non-space characters across all lines."""
    total = sum(len(line) for line in lines)
    if total == 0:
        return 0.0
    inked = sum(1 for line in lines for char in line if char not in (" ", "⠀"))
    return inked / total


def apply_ansi(lines: list[str], colors: np.ndarray) -> list[str]:
    """Wrap each character in its cell's mean colour as ANSI foreground."""
    tinted: list[str] = []
    for r, line in enumerate(lines):
        parts: list[str] = []
        for c, char in enumerate(line):
            red, green, blue = (int(v) for v in colors[r, c].tolist())
            parts.append(f"\x1b[38;2;{red};{green};{blue}m{char}\x1b[0m")
        tinted.append("".join(parts))
    return tinted


def charset_size(mode: str) -> int:
    """How many distinct characters a mode can emit."""
    if mode == "densidad":
        return len(RAMP)
    if mode == "trazo":
        return 2 + len(STROKES)
    if mode == "braille":
        return 256
    return len(GLYPHS)


def render_png(lines: list[str], font_path: str | Path, invert: bool) -> Image.Image:
    """Render text lines with Sometype Mono, black on white (inverted swap)."""
    font = ImageFont.truetype(str(font_path), FONT_SIZE)
    ascent, descent = font.getmetrics()
    cell_w = max(1, int(round(font.getlength("M"))))
    cell_h = ascent + descent
    columns = max((len(line) for line in lines), default=1)
    ink, paper = (255, 0) if invert else (0, 255)
    page = Image.new("L", (max(1, columns * cell_w), max(1, len(lines) * cell_h)), paper)
    canvas = ImageDraw.Draw(page)
    for r, line in enumerate(lines):
        canvas.text((0, r * cell_h), line, font=font, fill=ink, anchor="la")
    return page.convert("RGB")


def make_banner(text: str, font: str, width: int) -> list[str]:
    """Render a figlet banner, right-stripped, without edge blank lines."""
    rendered = pyfiglet.figlet_format(text, font=font, width=width)
    lines = [line.rstrip() for line in rendered.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def banner_svg(lines: list[str], cell_w: int = 8, cell_h: int = 16) -> str:
    """An SVG with one ``<rect>`` per non-space cell, in ``currentColor``.

    ``█`` is solid, ``░`` renders at 0.35 opacity, any other character at
    0.7. The SVG holds no text and needs no font: it takes the page colour.
    """
    columns = max((len(line) for line in lines), default=0)
    rows = len(lines)
    rects: list[str] = []
    for r, line in enumerate(lines):
        for c, char in enumerate(line):
            if char == " ":
                continue
            opacity = 1.0 if char == "█" else (0.35 if char == "░" else 0.7)
            rects.append(
                f'<rect x="{c * cell_w}" y="{r * cell_h}" '
                f'width="{cell_w}" height="{cell_h}" '
                f'fill="currentColor" opacity="{opacity}"/>'
            )
    joined = "\n".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{columns * cell_w}" height="{rows * cell_h}" '
        f'viewBox="0 0 {columns * cell_w} {rows * cell_h}" role="img">\n'
        f"{joined}\n</svg>\n"
    )
