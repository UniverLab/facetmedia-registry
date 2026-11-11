"""The pillow package runner: base image ops on CPU.

Written on the runner SDK (``facet_runner_sdk``, copied into every
environment). Four verbs: ``run`` opens the piece's ``image`` and applies
each table of ``operations`` in order in memory — ``convert``
re-encodes between png/jpeg/webp with an optional mode, ``resize``
resizes exact or aspect-preserving, ``sheet`` lays a contact sheet with
2 px white dividers — writing one ``<image-stem>-<i>-<op>.<ext>``
file per op, ``verify`` re-opens the assets and compares suffix, mode and
size against a fresh in-memory pass, ``preview`` writes the image kind's
fields per asset, and ``doctor`` checks the Pillow import and version.
"""

from __future__ import annotations

import io
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import PIL
from facet_runner_sdk import Request, Runner
from PIL import Image

runner = Runner()

#: The ops are deterministic; the seed labels the record (rembg precedent).
SEED = 0
#: The version the package pins in pyproject.toml; doctor proves it.
PILLOW_VERSION = "13.0.0"
CONVERT_EXT = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
MODES = {"RGB", "RGBA", "L"}
OPS = ("convert", "resize", "sheet")
MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
#: The Pillow format per output ext, for verify's buffer round-trip.
_FILE_FORMAT = {".png": "PNG", ".jpg": "JPEG", ".webp": "WEBP", ".jpeg": "JPEG"}
#: The contact sheet's white gap between tiles; no outer border.
DIVIDER = 2
_OP_NAME = re.compile(r"-(\d+)-(convert|resize|sheet)\.[a-z0-9]+$", re.IGNORECASE)
_OP_SUFFIX = re.compile(r"-\d+-(?:convert|resize|sheet)$", re.IGNORECASE)
_BAD_NAME = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True)
class Produced:
    """One op's output: the filename it writes and the image it holds."""

    filename: str
    image: Image.Image
    ext: str


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _image_path(params: dict[str, Any], req: Request) -> Path:
    """The piece's source image, resolved against the piece directory."""
    raw = params.get("image")
    if not raw:
        raise ValueError("the piece has no image")
    path = Path(str(raw))
    if not path.is_absolute():
        path = req.piece_dir / path
    if not path.is_file():
        raise ValueError(f"{path}: no such image")
    return path


def _ops(params: dict[str, Any]) -> list[dict[str, Any]]:
    """The operation tables, each naming a known ``op``."""
    raw = params.get("operations")
    if not isinstance(raw, list) or not raw:
        raise ValueError("the piece has no operations")
    ops: list[dict[str, Any]] = []
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"operations[{position}]: not an operation table")
        opname = item.get("op")
        if opname not in OPS:
            raise ValueError(f"operations[{position}]: pillow: unknown op {opname!r}")
        ops.append(item)
    return ops


def _positive_int(op: dict[str, Any], key: str, index: int, opname: str) -> int | None:
    """An optional integer input that must be >= 1 when present."""
    value = op.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"operations[{index}]: pillow {opname}: {key} must be an integer >= 1")
    return value


def _has_alpha(image: Image.Image) -> bool:
    """Whether the image carries transparency Pillow can composite."""
    return "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info)


def _jpeg_rgb(image: Image.Image, *, flatten: bool) -> Image.Image:
    """JPEG is always RGB; an alpha source flattens onto white first."""
    if flatten and _has_alpha(image):
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        base.alpha_composite(rgba)
        return base.convert("RGB")
    return image.convert("RGB")


def _convert(image: Image.Image, op: dict[str, Any], index: int) -> tuple[Image.Image, str]:
    """Re-encode between png/jpeg/webp with an optional mode."""
    out_format = op.get("format")
    if out_format is None:
        raise ValueError(f"operations[{index}]: pillow convert: format is required")
    if out_format not in CONVERT_EXT:
        raise ValueError(f"operations[{index}]: pillow convert: unknown format {out_format!r}")
    mode = op.get("mode")
    if mode is not None and mode not in MODES:
        raise ValueError(f"operations[{index}]: pillow convert: unknown mode {mode!r}")
    if mode == "RGBA" and out_format == "jpeg":
        raise ValueError(
            f"operations[{index}]: pillow convert: mode RGBA is incompatible with jpeg, "
            "use png or webp"
        )
    out = image.convert(str(mode)) if mode else image
    if out_format == "jpeg":
        out = _jpeg_rgb(out, flatten=mode is None)
    return out, CONVERT_EXT[str(out_format)]


def _resize(image: Image.Image, op: dict[str, Any], index: int) -> Image.Image:
    """Resize exact with both dims, aspect-preserving with one, Lanczos."""
    width = _positive_int(op, "width", index, "resize")
    height = _positive_int(op, "height", index, "resize")
    if width is None and height is None:
        raise ValueError(f"operations[{index}]: pillow resize: width or height is required")
    source_width, source_height = image.size
    if width is None:
        assert height is not None
        size = (max(1, round(source_width * height / source_height)), height)
    elif height is None:
        size = (width, max(1, round(source_height * width / source_width)))
    else:
        size = (width, height)
    return image.resize(size, Image.Resampling.LANCZOS)


def _sheet(image: Image.Image, op: dict[str, Any], index: int) -> tuple[Image.Image, str]:
    """Tile the image into a row-major sheet with 2 px white dividers."""
    columns = _positive_int(op, "columns", index, "sheet")
    rows = _positive_int(op, "rows", index, "sheet")
    if columns is None or rows is None:
        raise ValueError(f"operations[{index}]: pillow sheet: columns or rows is required")
    tile_w = image.width // columns
    tile_h = image.height // rows
    if tile_w < 1 or tile_h < 1:
        raise ValueError(
            f"operations[{index}]: pillow sheet: the image is too small for {columns}x{rows} tiles"
        )
    alpha = _has_alpha(image)
    sheet = Image.new(
        "RGBA" if alpha else "RGB",
        (
            columns * tile_w + (columns - 1) * DIVIDER,
            rows * tile_h + (rows - 1) * DIVIDER,
        ),
        (255, 255, 255, 255) if alpha else "white",
    )
    for row in range(rows):
        for col in range(columns):
            tile = image.crop((col * tile_w, row * tile_h, (col + 1) * tile_w, (row + 1) * tile_h))
            if alpha:
                tile = tile.convert("RGBA")
                sheet.paste(
                    tile, (col * (tile_w + DIVIDER), row * (tile_h + DIVIDER)), tile.getchannel("A")
                )
            else:
                sheet.paste(tile, (col * (tile_w + DIVIDER), row * (tile_h + DIVIDER)))
    return sheet, ".png"


def _apply_op(
    image: Image.Image, op: dict[str, Any], index: int, ext: str
) -> tuple[Image.Image, str]:
    """One op on the in-memory image; returns the image and its output ext."""
    opname = str(op["op"])
    if opname == "convert":
        return _convert(image, op, index)
    if opname == "resize":
        return _resize(image, op, index), ext
    return _sheet(image, op, index)


def _apply_ops(req: Request) -> tuple[Path, list[Produced]]:
    """Open ``image`` and run every op in order, collecting the outputs."""
    params = dict(req.inputs)
    source_path = _image_path(params, req)
    ops = _ops(params)
    ext = source_path.suffix.lower() if source_path.suffix.lower() in MIME else ".png"
    with Image.open(source_path) as source:
        current = source.copy()
    produced: list[Produced] = []
    for index, op in enumerate(ops, start=1):
        current, ext = _apply_op(current, op, index, ext)
        opname = str(op["op"])
        produced.append(Produced(f"{source_path.stem}-{index}-{opname}{ext}", current, ext))
    return source_path, produced


def _asset(item: Produced, path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """One output record: image kind, measured size, seed 0."""
    width, height = item.image.size
    return {
        "file": path.name,
        "name": _asset_name(path.stem),
        "kind": "image",
        "mime": MIME.get(path.suffix.lower(), "image/png"),
        "properties": {"width": width, "height": height},
        "params": {"image": str(params.get("image", ""))},
        "seed": SEED,
        "inputs": [str(params.get("image", ""))],
    }


def _asset_name(stem: str) -> str:
    """A stem folded into the record's ``[a-z0-9][a-z0-9-]*`` name shape."""
    name = _BAD_NAME.sub("-", stem.lower()).strip("-")
    return name or "image"


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    _image_source, produced = _apply_ops(req)
    params = dict(req.inputs)
    assets = []
    for item in produced:
        path = req.out_dir / item.filename
        item.image.save(path)
        assets.append(_asset(item, path, params))
    return {"tool": _tool(), "assets": assets}


def _expected(req: Request) -> dict[str, Produced]:
    """The outputs a fresh pass predicts, by filename; empty on bad input."""
    try:
        _image_source, produced = _apply_ops(req)
    except (OSError, ValueError, KeyError):
        return {}
    return {item.filename: item for item in produced}


def _file_mode(item: Produced) -> str:
    """The mode the file re-opens in, predicted by a buffer round-trip.

    The in-memory image and the saved file can disagree on mode: webp folds
    grayscale and fully-opaque images to RGB on decode. Verify judges the
    file, so the expectation runs through the same save the runner does.
    """
    buffer = io.BytesIO()
    item.image.save(buffer, _FILE_FORMAT[item.ext])
    buffer.seek(0)
    with Image.open(buffer) as image:
        return image.mode


def _verify_asset(path: Path, expected: dict[str, Produced]) -> dict[str, Any]:
    """The file re-opens and matches the predicted suffix, mode and size."""
    want = expected.get(path.name)
    thresholds: dict[str, Any] = (
        {"mode": _file_mode(want), "width": want.image.width, "height": want.image.height}
        if want is not None
        else {}
    )
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            mode = image.mode
            width, height = image.size
    except (OSError, ValueError) as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": "pillow",
        }
    passed = (
        (path.suffix.lower() in MIME)
        if want is None
        else (
            path.suffix.lower() == want.ext
            and mode == thresholds["mode"]
            and (width, height) == (thresholds["width"], thresholds["height"])
        )
    )
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {"mode": mode, "width": width, "height": height},
        "thresholds": thresholds,
        "verifier": "pillow",
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    expected = _expected(req)
    return {"assets": [_verify_asset(path, expected) for path in req.assets]}


def _preview_data(path: Path, name: str, prompt: str) -> dict[str, Any]:
    """The image schema's fields, measured from the file itself."""
    with Image.open(path) as image:
        width, height = image.size
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


def _source_stem(params: dict[str, Any]) -> str:
    """The image's stem, or empty when the request carries no image."""
    raw = params.get("image")
    return Path(str(raw)).stem if raw else ""


def _prompt(path: Path, stem: str) -> str:
    """``pillow <op> of <stem>`` parsed back from the asset name."""
    if not stem:
        stem = _OP_SUFFIX.sub("", path.name.rsplit(".", 1)[0])
    match = _OP_NAME.search(path.name)
    op = match.group(2) if match else "op"
    return f"pillow {op} of {stem}" if stem else f"pillow {op}"


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    stem = _source_stem(params)
    entries = []
    for path in req.assets:
        data = _preview_data(path, _asset_name(path.stem), _prompt(path, stem))
        preview_name = f"{path.name}.preview.json"
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_imports() -> dict[str, Any]:
    """Pillow is the pinned version (the runner cannot start without it)."""
    version = str(getattr(PIL, "__version__", "unknown"))
    if version != PILLOW_VERSION:
        return _check(
            "imports",
            False,
            f"pillow {version}, the package pins {PILLOW_VERSION}",
            "facet pull pillow",
        )
    return _check("imports", True, f"pillow {version}")


def _doctor_ops() -> dict[str, Any]:
    """A 2x2 PNG round-trips through encode and decode (full depth only)."""
    try:
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(buffer, "PNG")
        buffer.seek(0)
        with Image.open(buffer) as image:
            image.verify()
    except (OSError, ValueError) as exc:
        return _check("ops", False, str(exc), "facet pull pillow")
    return _check("ops", True, "2x2 png encode/decode")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_imports()]
    if req.depth == "full":
        checks.append(_doctor_ops())
    return {"checks": checks}


runner.main()
