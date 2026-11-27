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
from PIL import Image, ImageColor, ImageEnhance, ImageFilter, ImageOps

runner = Runner()

CAP_BASE = "pillow.base"
CAP_RETOUCH = "pillow.retouch"

#: The ops are deterministic; the seed labels the record (rembg precedent).
SEED = 0
#: The version the package pins in pyproject.toml; doctor proves it.
PILLOW_VERSION = "13.0.0"
CONVERT_EXT = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
MODES = {"RGB", "RGBA", "L"}
OPS = ("convert", "resize", "sheet")
_ASPECTS: dict[str, tuple[int, int]] = {
    "1:1": (1, 1),
    "4:5": (4, 5),
    "16:9": (16, 9),
    "9:16": (9, 16),
    "3:2": (3, 2),
    "4:3": (4, 3),
}
_FLIPS = ("none", "horizontal", "vertical")
_RETOUCH_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAX_PAD_PX = 400
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
        current = ImageOps.exif_transpose(source.copy())
    produced: list[Produced] = []
    for index, op in enumerate(ops, start=1):
        current, ext = _apply_op(current, op, index, ext)
        opname = str(op["op"])
        produced.append(Produced(f"{source_path.stem}-{index}-{opname}{ext}", current, ext))
    return source_path, produced


@dataclass(frozen=True)
class RetouchParams:
    """Validated inputs for ``pillow.retouch``."""

    name: str
    fmt: str
    aspect: str | None
    rotate_deg: float
    flip: str
    autocontrast: bool
    brightness: float
    contrast: float
    saturation: float
    warmth: float
    sharpen: float
    pad_px: int
    pad_color: str


def _num_in_range(
    params: dict[str, Any], key: str, default: float, low: float, high: float
) -> float:
    raw = params.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(f"pillow retouch: {key} must be a number")
    val = float(raw)
    if val < low or val > high:
        raise ValueError(f"pillow retouch: {key} must be between {low} and {high}")
    return val


def _validate_retouch(params: dict[str, Any]) -> RetouchParams:
    """Validate and normalize ``pillow.retouch`` inputs."""
    name = params.get("name")
    if not isinstance(name, str) or not _RETOUCH_NAME.match(name):
        raise ValueError("pillow retouch: name must match ^[a-z0-9][a-z0-9-]*$")
    fmt = params.get("format", "png")
    if fmt not in CONVERT_EXT:
        raise ValueError(f"pillow retouch: unknown format {fmt!r}")
    aspect = params.get("aspect")
    if aspect is not None and aspect not in _ASPECTS:
        raise ValueError(f"pillow retouch: unknown aspect {aspect!r}")
    flip = params.get("flip", "none")
    if flip not in _FLIPS:
        raise ValueError(f"pillow retouch: unknown flip {flip!r}")
    autocontrast = params.get("autocontrast", False)
    if not isinstance(autocontrast, bool):
        raise ValueError("pillow retouch: autocontrast must be a boolean")
    pad_raw = params.get("pad-px", 0)
    if isinstance(pad_raw, bool) or not isinstance(pad_raw, int) or not 0 <= pad_raw <= _MAX_PAD_PX:
        raise ValueError(f"pillow retouch: pad-px must be an integer between 0 and {_MAX_PAD_PX}")
    pad_color = params.get("pad-color", "#F6F3EC")
    if not isinstance(pad_color, str):
        raise ValueError("pillow retouch: pad-color must be a hex color string")
    ImageColor.getrgb(pad_color)
    return RetouchParams(
        name=name,
        fmt=str(fmt),
        aspect=str(aspect) if aspect is not None else None,
        rotate_deg=_num_in_range(params, "rotate-deg", 0.0, -180.0, 180.0),
        flip=str(flip),
        autocontrast=autocontrast,
        brightness=_num_in_range(params, "brightness", 1.0, 0.2, 3.0),
        contrast=_num_in_range(params, "contrast", 1.0, 0.2, 3.0),
        saturation=_num_in_range(params, "saturation", 1.0, 0.0, 3.0),
        warmth=_num_in_range(params, "warmth", 0.0, -1.0, 1.0),
        sharpen=_num_in_range(params, "sharpen", 0.0, 0.0, 3.0),
        pad_px=pad_raw,
        pad_color=pad_color,
    )


def _center_crop_aspect(image: Image.Image, aspect: str) -> Image.Image:
    """Center-crop ``image`` to ``aspect`` without stretching."""
    aw, ah = _ASPECTS[aspect]
    w, h = image.size
    if w * ah > h * aw:
        new_w = min(w, max(1, round(h * aw / ah)))
        left = (w - new_w) // 2
        return image.crop((left, 0, left + new_w, h))
    if w * ah < h * aw:
        new_h = min(h, max(1, round(w * ah / aw)))
        top = (h - new_h) // 2
        return image.crop((0, top, w, top + new_h))
    return image


def _apply_warmth(rgb: Image.Image, warmth: float) -> Image.Image:
    """Apply deterministic white-balance warmth shift via a 256-entry RGB LUT."""
    shift = warmth * 24.0
    r_lut = [min(255, max(0, round(i + shift))) for i in range(256)]
    g_lut = list(range(256))
    b_lut = [min(255, max(0, round(i - shift))) for i in range(256)]
    return rgb.point(r_lut + g_lut + b_lut)


def _flatten_alpha(image: Image.Image, color: str) -> Image.Image:
    """Composite an image with alpha onto ``color`` and return RGB."""
    if not _has_alpha(image):
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    bg_rgb = ImageColor.getrgb(color)
    base = Image.new("RGBA", rgba.size, (bg_rgb[0], bg_rgb[1], bg_rgb[2], 255))
    base.alpha_composite(rgba)
    return base.convert("RGB")


def _grade_rgb(rgb: Image.Image, cfg: RetouchParams) -> Image.Image:
    """Apply tonal, color-grading, and sharpening steps to an RGB image."""
    if cfg.autocontrast:
        rgb = ImageOps.autocontrast(rgb, cutoff=1)
    if cfg.warmth != 0.0:
        rgb = _apply_warmth(rgb, cfg.warmth)
    if cfg.brightness != 1.0:
        rgb = ImageEnhance.Brightness(rgb).enhance(cfg.brightness)
    if cfg.contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(cfg.contrast)
    if cfg.saturation != 1.0:
        rgb = ImageEnhance.Color(rgb).enhance(cfg.saturation)
    if cfg.sharpen > 0.0:
        rgb = rgb.filter(
            ImageFilter.UnsharpMask(radius=1.5, percent=int(round(cfg.sharpen * 100)), threshold=3)
        )
    return rgb


def _retouch_pipeline(source: Image.Image, cfg: RetouchParams) -> Image.Image:
    """Run the deterministic ``pillow.retouch`` pipeline on an opened image."""
    img = ImageOps.exif_transpose(source.copy())
    if cfg.flip == "horizontal":
        img = ImageOps.mirror(img)
    elif cfg.flip == "vertical":
        img = ImageOps.flip(img)
    if cfg.rotate_deg != 0.0:
        img = img.rotate(cfg.rotate_deg, expand=True)
    if cfg.aspect is not None:
        img = _center_crop_aspect(img, cfg.aspect)
    alpha: Image.Image | None = None
    if cfg.fmt == "jpeg":
        bg = cfg.pad_color if cfg.pad_px > 0 else "#FFFFFF"
        rgb = _flatten_alpha(img, bg)
    elif _has_alpha(img):
        rgba = img.convert("RGBA")
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
    else:
        rgb = img.convert("RGB")
    rgb = _grade_rgb(rgb, cfg)
    out = Image.merge("RGBA", (*rgb.split(), alpha)) if alpha is not None else rgb
    if cfg.pad_px > 0:
        fill = ImageColor.getcolor(cfg.pad_color, out.mode)
        out = ImageOps.expand(out, border=cfg.pad_px, fill=fill)
    return out


def _apply_retouch(req: Request) -> tuple[Path, list[Produced]]:
    """Open ``image`` and run the ``pillow.retouch`` pipeline."""
    params = dict(req.inputs)
    source_path = _image_path(params, req)
    cfg = _validate_retouch(params)
    with Image.open(source_path) as source:
        out = _retouch_pipeline(source, cfg)
    ext = CONVERT_EXT[cfg.fmt]
    return source_path, [Produced(f"{cfg.name}{ext}", out, ext)]


def _produce(req: Request) -> tuple[Path, list[Produced]]:
    """Dispatch by capability to produce the in-memory outputs."""
    if req.capability == CAP_BASE:
        return _apply_ops(req)
    if req.capability == CAP_RETOUCH:
        return _apply_retouch(req)
    raise ValueError(f"pillow: unknown capability {req.capability!r}")


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
    _image_source, produced = _produce(req)
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
        _image_source, produced = _produce(req)
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


def _aspect_ok(width: int, height: int, req: Request) -> bool:
    """For unpadded ``pillow.retouch`` with ``aspect``, check aspect within 1 px."""
    if req.capability != CAP_RETOUCH:
        return True
    params = dict(req.inputs)
    aspect = params.get("aspect")
    pad_px = params.get("pad-px", 0)
    if aspect is None or pad_px != 0 or aspect not in _ASPECTS:
        return True
    aw, ah = _ASPECTS[str(aspect)]
    return abs(width * ah - height * aw) <= max(aw, ah)


def _verify_asset(path: Path, expected: dict[str, Produced], req: Request) -> dict[str, Any]:
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
            and _aspect_ok(width, height, req)
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
    return {"assets": [_verify_asset(path, expected, req) for path in req.assets]}


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


def _retouch_prompt(stem: str) -> str:
    """``pillow retouch of <stem>`` for ``pillow.retouch`` previews."""
    return f"pillow retouch of {stem}" if stem else "pillow retouch"


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    stem = _source_stem(params)
    entries = []
    for path in req.assets:
        prompt = _retouch_prompt(stem) if req.capability == CAP_RETOUCH else _prompt(path, stem)
        data = _preview_data(path, _asset_name(path.stem), prompt)
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
