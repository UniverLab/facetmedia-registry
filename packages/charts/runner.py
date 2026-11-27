"""The charts package runner: editorial data charts on CPU.

Written on the runner SDK (``facet_runner_sdk``, copied into every
environment). Four verbs: ``run`` reads the piece's ``data`` table (a
UTF-8 comma CSV with a header row, or a JSON array of row objects),
plots one series with matplotlib on the headless Agg backend — ``bar``,
``barh``, ``line`` or ``scatter`` — in an editorial style (no
top/right spines, hairline grid, generous margins, title plus subtitle
and source footer, direct value labels on twelve bars or fewer),
``verify`` re-opens the asset and checks PNG dimensions and
non-uniform pixels or the SVG root and drawing primitives, ``preview``
writes the image kind's fields per asset, and ``doctor`` checks the
matplotlib and Pillow imports, rendering a tiny 3-bar PNG at full
depth.
"""

from __future__ import annotations

import csv
import importlib
import json
import math
import re
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))

from facet_runner_sdk import Request, Runner

runner = Runner()

#: The preview records carry seed 0 (the render is deterministic).
SEED = 0
CHARTS = ("bar", "barh", "line", "scatter")
FORMATS = ("png", "svg")
DEFAULT_FORMAT = "png"
DEFAULT_ACCENT = "#E8C547"
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 675
#: Editorial tokens: neutral ink, muted secondary ink, paper, hairline grid.
INK = "#1A1A1A"
MUTED = "#6E6A5E"
PAPER = "#FFFFFF"
GRID = "#E3E0D6"
MIME = {".png": "image/png", ".svg": "image/svg+xml"}
_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_FLOAT_PREFIX = re.compile(r"^[0-9]+(?:\.[0-9]+)?")
_BAD_NAME = re.compile(r"[^a-z0-9-]+")
#: SVG elements that draw something (text counts: the title is content).
_SVG_PRIMITIVES = frozenset(
    {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text"}
)
#: Bars at or below this count carry direct value labels.
LABEL_BARS_MAX = 12
#: PNG and SVG dimensions verify within this many pixels of the request.
SIZE_TOLERANCE_PX = 2


@dataclass(frozen=True)
class Table:
    """One parsed series: x labels or positions and numeric y values."""

    xs: list[Any]
    ys: list[float]
    x_numeric: bool


@dataclass(frozen=True)
class Spec:
    """The piece's resolved inputs; the filename follows name and format."""

    data: Path
    name: str
    chart: str
    title: str
    subtitle: str
    source: str
    x: str
    y: str
    format: str
    accent: str
    width: int
    height: int

    @property
    def filename(self) -> str:
        """The asset filename: ``<name>.png`` or ``<name>.svg``."""
        return f"{self.name}.{self.format}"


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    """The CSV rows: UTF-8, comma-delimited, first row is the header."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=",")
        if reader.fieldnames is None:
            raise ValueError(f"{path}: no header row")
        return [dict(row) for row in reader]


def _read_json(path: Path) -> list[dict[str, Any]]:
    """The JSON rows: a non-empty top-level array of row objects."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path}: json data must be a non-empty array of row objects")
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index + 1} is not an object")
    return data


def _cell(path: Path, row: Any, key: str, index: int) -> Any:
    """One cell: every row carries the x and y keys with a real value."""
    if not isinstance(row, dict) or key not in row or row[key] is None:
        raise ValueError(f"{path}: row {index + 1} is missing {key!r}")
    return row[key]


def _parse_y(path: Path, raw: Any, key: str) -> float:
    """A y cell as a finite float; booleans and NaN never slip through."""
    if isinstance(raw, bool) or raw is None:
        raise ValueError(f"{path}: {key!r} must be numeric, got {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{path}: {key!r} must be numeric, got {raw!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{path}: {key!r} must be finite, got {raw!r}")
    return value


def _try_floats(values: list[Any]) -> list[float] | None:
    """The values as floats, or None when any one is not a finite number."""
    out: list[float] = []
    for raw in values:
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        out.append(value)
    return out


def load_table(path: Path, x_key: str, y_key: str, chart: str) -> Table:
    """Read ``path`` as CSV or JSON and return the x/y series for ``chart``.

    Scatter needs numeric x; line takes numeric x when every value parses
    and ordered category strings otherwise; bars use string labels. Raises
    ``ValueError`` on empty data, an unsupported extension, a missing
    column, or a non-numeric y.
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _read_csv(path)
    elif suffix == ".json":
        rows = _read_json(path)
    else:
        raise ValueError(f"{path}: unsupported data extension {suffix!r} (csv or json)")
    if not rows:
        raise ValueError(f"{path}: no data rows")
    raw_xs = [_cell(path, row, x_key, index) for index, row in enumerate(rows)]
    ys = [_parse_y(path, _cell(path, row, y_key, index), y_key) for index, row in enumerate(rows)]
    if chart == "scatter":
        numbers = _try_floats(raw_xs)
        if numbers is None:
            raise ValueError(f"{path}: {x_key!r} must be numeric for a scatter chart")
        return Table(xs=numbers, ys=ys, x_numeric=True)
    if chart == "line":
        numbers = _try_floats(raw_xs)
        if numbers is not None:
            return Table(xs=numbers, ys=ys, x_numeric=True)
    return Table(xs=[str(value) for value in raw_xs], ys=ys, x_numeric=False)


def _required_str(params: dict[str, Any], key: str) -> str:
    """A required non-empty string input."""
    raw = params.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"the piece has no {key}")
    return raw


def _dim(params: dict[str, Any], key: str, default: int) -> int:
    """An optional pixel dimension, a positive integer when present."""
    raw = params.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError(f"{key} must be an integer >= 1")
    return raw


def _resolve(params: dict[str, Any], req: Request) -> Spec:
    """The piece's inputs as a Spec; raises ``ValueError`` when refused."""
    raw_data = _required_str(params, "data")
    data = Path(raw_data)
    if not data.is_absolute():
        data = req.piece_dir / data
    if not data.is_file():
        raise ValueError(f"{data}: no such data file")
    if data.suffix.lower() not in (".csv", ".json"):
        raise ValueError(f"{data}: unsupported data extension (csv or json)")
    chart = _required_str(params, "chart")
    if chart not in CHARTS:
        raise ValueError(f"unknown chart {chart!r}")
    fmt = params.get("format", DEFAULT_FORMAT)
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    accent = params.get("accent", DEFAULT_ACCENT)
    if not isinstance(accent, str) or _HEX.fullmatch(accent) is None:
        raise ValueError(f"accent must be a #rrggbb hex color, got {accent!r}")
    return Spec(
        data=data,
        name=_required_str(params, "name"),
        chart=chart,
        title=_required_str(params, "title"),
        subtitle=str(params.get("subtitle") or ""),
        source=str(params.get("source") or ""),
        x=_required_str(params, "x"),
        y=_required_str(params, "y"),
        format=str(fmt),
        accent=accent,
        width=_dim(params, "width-px", DEFAULT_WIDTH),
        height=_dim(params, "height-px", DEFAULT_HEIGHT),
    )


def _style_axes(ax: Any) -> None:
    """The editorial frame: no top/right spines, hairline grid, ink text."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(MUTED)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=10)
    ax.set_facecolor(PAPER)


def _frame_figure(fig: Any, spec: Spec) -> None:
    """The title, subtitle and source footer with generous margins."""
    fig.text(0.08, 0.95, spec.title, fontsize=20, fontweight="bold", color=INK, ha="left", va="top")
    top = 0.86
    if spec.subtitle:
        fig.text(0.08, 0.895, spec.subtitle, fontsize=12, color=MUTED, ha="left", va="top")
        top = 0.82
    if spec.source:
        fig.text(0.08, 0.02, spec.source, fontsize=9, color=MUTED, ha="left", va="bottom")
    fig.subplots_adjust(left=0.08, right=0.97, top=top, bottom=0.16)


def _draw_bars(
    ax: Any, labels: list[str], ys: list[float], spec: Spec, *, horizontal: bool
) -> None:
    """Bars in the accent color with a hairline value grid and labels."""
    if horizontal:
        bars = ax.barh(labels, ys, color=spec.accent, edgecolor=PAPER, height=0.6)
        ax.xaxis.grid(True, linewidth=0.5, color=GRID, linestyle="-")
    else:
        bars = ax.bar(labels, ys, color=spec.accent, edgecolor=PAPER, width=0.6)
        ax.yaxis.grid(True, linewidth=0.5, color=GRID, linestyle="-")
    ax.set_axisbelow(True)
    if len(ys) <= LABEL_BARS_MAX:
        ax.bar_label(bars, labels=[f"{value:g}" for value in ys], fontsize=9, color=INK, padding=3)


def _draw_line(ax: Any, table: Table, spec: Spec) -> None:
    """A single accent line, dotted per point, over numbers or categories."""
    if table.x_numeric:
        ax.plot(table.xs, table.ys, color=spec.accent, linewidth=2.5, marker="o")
    else:
        positions = list(range(len(table.xs)))
        ax.plot(positions, table.ys, color=spec.accent, linewidth=2.5, marker="o")
        ax.set_xticks(positions, [str(value) for value in table.xs])
    ax.yaxis.grid(True, linewidth=0.5, color=GRID, linestyle="-")
    ax.set_axisbelow(True)


def _draw_scatter(ax: Any, table: Table, spec: Spec) -> None:
    """Accent dots with white edges over a light both-axes grid."""
    ax.scatter(table.xs, table.ys, color=spec.accent, s=36, edgecolors=PAPER, linewidths=0.8)
    ax.grid(True, linewidth=0.5, color=GRID, linestyle="-")
    ax.set_axisbelow(True)


def _draw(ax: Any, table: Table, spec: Spec) -> None:
    """One series in the chart's geometry."""
    if spec.chart == "bar":
        _draw_bars(ax, [str(value) for value in table.xs], table.ys, spec, horizontal=False)
    elif spec.chart == "barh":
        _draw_bars(ax, [str(value) for value in table.xs], table.ys, spec, horizontal=True)
    elif spec.chart == "line":
        _draw_line(ax, table, spec)
    else:
        _draw_scatter(ax, table, spec)


def _normalize_svg(dest: Path, width: int, height: int) -> None:
    """Stamp the requested pixel size onto the SVG root and viewBox."""
    ET.register_namespace("", _SVG_NS)
    ET.register_namespace("xlink", _XLINK_NS)
    tree = ET.parse(dest)
    root = tree.getroot()
    root.set("width", str(width))
    root.set("height", str(height))
    root.set("viewBox", f"0 0 {width} {height}")
    tree.write(dest, encoding="utf-8", xml_declaration=True)


def _render_table(table: Table, spec: Spec, dest: Path) -> None:
    """Plot the series headless at exactly width by height pixels."""
    matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg")
    pyplot = importlib.import_module("matplotlib.pyplot")
    figure, ax = pyplot.subplots(figsize=(spec.width / 100, spec.height / 100), dpi=100)
    figure.patch.set_facecolor(PAPER)
    try:
        _style_axes(ax)
        _draw(ax, table, spec)
        _frame_figure(figure, spec)
        if spec.format == "svg":
            figure.savefig(dest, format="svg")
            _normalize_svg(dest, spec.width, spec.height)
        else:
            figure.savefig(dest, format="png")
    finally:
        pyplot.close(figure)


def _asset(dest: Path, spec: Spec) -> dict[str, Any]:
    """One output record: image kind, measured size, seed 0."""
    return {
        "file": dest.name,
        "name": spec.name,
        "kind": "image",
        "mime": MIME["." + spec.format],
        "properties": {"width": spec.width, "height": spec.height},
        "params": {"chart": spec.chart, "title": spec.title},
        "seed": SEED,
        "inputs": [spec.data.name],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    spec = _resolve(params, req)
    table = load_table(spec.data, spec.x, spec.y, spec.chart)
    dest = req.out_dir / spec.filename
    _render_table(table, spec, dest)
    return {"tool": _tool(), "assets": [_asset(dest, spec)]}


def _expected(req: Request) -> dict[str, dict[str, int]]:
    """The output the inputs predict, by filename; empty on bad input."""
    try:
        spec = _resolve(dict(req.inputs), req)
        load_table(spec.data, spec.x, spec.y, spec.chart)
    except (OSError, ValueError, KeyError, csv.Error):
        return {}
    return {spec.filename: {"width": spec.width, "height": spec.height}}


def _is_uniform(path: Path) -> bool:
    """Whether the PNG is one flat color (a failed render)."""
    pil = importlib.import_module("PIL.Image")
    with pil.open(path) as image:
        small = image.convert("L").resize((32, 32))
        colors = small.getcolors(32 * 32)
        return colors is not None and len(colors) == 1


def _verify_png(path: Path, want: dict[str, int] | None) -> dict[str, Any]:
    """The PNG opens, matches the predicted size and is not one flat color."""
    thresholds: dict[str, Any] = dict(want) if want is not None else {}
    try:
        pil = importlib.import_module("PIL.Image")
        with pil.open(path) as image:
            image.verify()
        with pil.open(path) as image:
            width, height = image.size
        uniform = _is_uniform(path)
    except (OSError, ValueError) as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": "charts",
        }
    sized = want is None or (
        abs(width - want["width"]) <= SIZE_TOLERANCE_PX
        and abs(height - want["height"]) <= SIZE_TOLERANCE_PX
    )
    return {
        "file": path.name,
        "passed": sized and not uniform,
        "metrics": {"width": width, "height": height, "uniform": uniform},
        "thresholds": thresholds,
        "verifier": "charts",
    }


def _local(tag: str) -> str:
    """An element tag without its namespace."""
    return tag.rsplit("}", 1)[-1]


def _verify_svg(path: Path, want: dict[str, int] | None) -> dict[str, Any]:
    """The SVG parses, is an svg document and carries drawing primitives."""
    thresholds: dict[str, Any] = dict(want) if want is not None else {}
    try:
        root = ET.parse(path).getroot()
        primitives = sum(1 for element in root.iter() if _local(element.tag) in _SVG_PRIMITIVES)
    except (OSError, ValueError, ET.ParseError) as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": "charts",
        }
    passed = (
        _local(root.tag) == "svg"
        and path.stat().st_size > 0
        and primitives > 0
        and _svg_sized(root, want)
    )
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {"primitives": primitives, "bytes": path.stat().st_size},
        "thresholds": thresholds,
        "verifier": "charts",
    }


def _svg_sized(root: Any, want: dict[str, int] | None) -> bool:
    """The SVG width/height match the prediction, when there is one."""
    if want is None:
        return True
    width = _leading_float(root.get("width"))
    height = _leading_float(root.get("height"))
    if width is None or height is None:
        return True
    return (
        abs(width - want["width"]) <= SIZE_TOLERANCE_PX
        and abs(height - want["height"]) <= SIZE_TOLERANCE_PX
    )


def _leading_float(raw: Any) -> float | None:
    """The leading number of a dimension attribute (``1200``, ``1200px``)."""
    if not isinstance(raw, str):
        return None
    match = _FLOAT_PREFIX.match(raw.strip())
    return float(match.group(0)) if match else None


def _verify_asset(path: Path, expected: dict[str, dict[str, int]]) -> dict[str, Any]:
    """The file passes its format's checks against the predicted output."""
    want = expected.get(path.name)
    if path.suffix.lower() == ".png":
        return _verify_png(path, want)
    if path.suffix.lower() == ".svg":
        return _verify_svg(path, want)
    return {
        "file": path.name,
        "passed": False,
        "metrics": {"error": f"unknown extension {path.suffix!r}"},
        "thresholds": {},
        "verifier": "charts",
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    expected = _expected(req)
    return {"assets": [_verify_asset(Path(path), expected) for path in req.assets]}


def _asset_name(stem: str) -> str:
    """A stem folded into the record's ``[a-z0-9][a-z0-9-]*`` name shape."""
    name = _BAD_NAME.sub("-", stem.lower()).strip("-")
    return name or "chart"


def _preview_data(path: Path, name: str, prompt: str, width: int, height: int) -> dict[str, Any]:
    """The image schema's fields for one asset."""
    return {
        "preview": 1,
        "kind": "image",
        "summary": f"{name} · {width}×{height}"[:160],
        "name": name,
        "prompt": prompt,
        "seed": SEED,
        "width": width,
        "height": height,
    }


def _measure_png(path: Path) -> tuple[int, int]:
    """The PNG's own pixel size, read with Pillow."""
    pil = importlib.import_module("PIL.Image")
    with pil.open(path) as image:
        return image.size


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    prompt = f"{params.get('chart', 'chart')}: {params.get('title', '')}"
    fallback = (_dim(params, "width-px", DEFAULT_WIDTH), _dim(params, "height-px", DEFAULT_HEIGHT))
    entries = []
    for path in req.assets:
        asset = Path(path)
        size = _measure_png(asset) if asset.suffix.lower() == ".png" else fallback
        data = _preview_data(asset, _asset_name(asset.stem), prompt, size[0], size[1])
        preview_name = f"{asset.name}.preview.json"
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": asset.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_imports() -> dict[str, Any]:
    """Matplotlib and Pillow import (the runner cannot start without them)."""
    try:
        matplotlib = importlib.import_module("matplotlib")
        pil = importlib.import_module("PIL.Image")
    except ImportError as exc:
        return _check("imports", False, str(exc), "facet pull charts")
    return _check(
        "imports",
        True,
        f"matplotlib {matplotlib.__version__}, pillow {pil.__version__}",
    )


def _doctor_render() -> dict[str, Any]:
    """A tiny 3-bar PNG renders in a temp dir at exactly 400x300 (full only)."""
    spec = Spec(
        data=Path("doctor.csv"),
        name="doctor",
        chart="bar",
        title="doctor",
        subtitle="",
        source="",
        x="label",
        y="value",
        format="png",
        accent=DEFAULT_ACCENT,
        width=400,
        height=300,
    )
    table = Table(xs=["a", "b", "c"], ys=[1.0, 2.0, 3.0], x_numeric=False)
    try:
        with tempfile.TemporaryDirectory(prefix="charts-doctor-") as tmp:
            dest = Path(tmp) / spec.filename
            _render_table(table, spec, dest)
            size = _measure_png(dest)
    except (OSError, ValueError) as exc:
        return _check("render", False, str(exc), "facet pull charts")
    if size != (400, 300):
        return _check(
            "render", False, f"3-bar png is {size[0]}x{size[1]}, want 400x300", "facet pull charts"
        )
    return _check("render", True, "3-bar 400x300 png")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_imports()]
    if req.depth == "full":
        checks.append(_doctor_render())
    return {"checks": checks}


runner.main()
