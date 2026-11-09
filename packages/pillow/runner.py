"""The pillow package runner: base image ops on CPU.

Written on the runner SDK (``facet_runner_sdk``, copied into every
environment). Four verbs: ``run`` opens the piece's ``imagen`` and applies
each table of ``operaciones`` in order in memory — ``convertir``
re-encodes between png/jpeg/webp with an optional mode, ``redimensionar``
resizes exact or aspect-preserving, ``hoja`` lays a contact sheet with
2 px white dividers — writing one ``<imagen-stem>-<i>-<operacion>.<ext>``
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
MODOS = {"RGB", "RGBA", "L"}
OPS = ("convertir", "redimensionar", "hoja")
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
_OP_NAME = re.compile(r"-(\d+)-(convertir|redimensionar|hoja)\.[a-z0-9]+$", re.IGNORECASE)
_OP_SUFFIX = re.compile(r"-\d+-(?:convertir|redimensionar|hoja)$", re.IGNORECASE)
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


def _imagen(params: dict[str, Any], req: Request) -> Path:
    """The piece's source image, resolved against the piece directory."""
    raw = params.get("imagen")
    if not raw:
        raise ValueError("the piece has no imagen")
    path = Path(str(raw))
    if not path.is_absolute():
        path = req.piece_dir / path
    if not path.is_file():
        raise ValueError(f"{path}: no such imagen")
    return path


def _ops(params: dict[str, Any]) -> list[dict[str, Any]]:
    """The operation tables, each naming a known ``operacion``."""
    raw = params.get("operaciones")
    if not isinstance(raw, list) or not raw:
        raise ValueError("the piece has no operaciones")
    ops: list[dict[str, Any]] = []
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"operaciones[{position}]: not an operation table")
        opname = item.get("operacion")
        if opname not in OPS:
            raise ValueError(f"operaciones[{position}]: pillow: operacion desconocida {opname!r}")
        ops.append(item)
    return ops


def _positive_int(op: dict[str, Any], key: str, index: int, opname: str) -> int | None:
    """An optional integer input that must be >= 1 when present."""
    value = op.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"operaciones[{index}]: pillow {opname}: {key} debe ser un entero >= 1")
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


def _convertir(image: Image.Image, op: dict[str, Any], index: int) -> tuple[Image.Image, str]:
    """Re-encode between png/jpeg/webp with an optional mode."""
    formato = op.get("formato")
    if formato is None:
        raise ValueError(f"operaciones[{index}]: pillow convertir: falta formato")
    if formato not in CONVERT_EXT:
        raise ValueError(f"operaciones[{index}]: pillow convertir: formato desconocido {formato!r}")
    modo = op.get("modo")
    if modo is not None and modo not in MODOS:
        raise ValueError(f"operaciones[{index}]: pillow convertir: modo desconocido {modo!r}")
    if modo == "RGBA" and formato == "jpeg":
        raise ValueError(
            f"operaciones[{index}]: pillow convertir: modo RGBA incompatible con formato jpeg, "
            "usa png o webp"
        )
    out = image.convert(str(modo)) if modo else image
    if formato == "jpeg":
        out = _jpeg_rgb(out, flatten=modo is None)
    return out, CONVERT_EXT[str(formato)]


def _redimensionar(image: Image.Image, op: dict[str, Any], index: int) -> Image.Image:
    """Resize exact with both dims, aspect-preserving with one, Lanczos."""
    ancho = _positive_int(op, "ancho", index, "redimensionar")
    alto = _positive_int(op, "alto", index, "redimensionar")
    if ancho is None and alto is None:
        raise ValueError(f"operaciones[{index}]: pillow redimensionar: falta ancho o alto")
    width, height = image.size
    if ancho is None:
        assert alto is not None
        size = (max(1, round(width * alto / height)), alto)
    elif alto is None:
        size = (ancho, max(1, round(height * ancho / width)))
    else:
        size = (ancho, alto)
    return image.resize(size, Image.Resampling.LANCZOS)


def _hoja(image: Image.Image, op: dict[str, Any], index: int) -> tuple[Image.Image, str]:
    """Tile the image into a row-major sheet with 2 px white dividers."""
    columnas = _positive_int(op, "columnas", index, "hoja")
    filas = _positive_int(op, "filas", index, "hoja")
    if columnas is None or filas is None:
        raise ValueError(f"operaciones[{index}]: pillow hoja: faltan columnas o filas")
    tile_w = image.width // columnas
    tile_h = image.height // filas
    if tile_w < 1 or tile_h < 1:
        raise ValueError(
            f"operaciones[{index}]: pillow hoja: la imagen es demasiado pequeña "
            f"para {columnas}x{filas} tiles"
        )
    alpha = _has_alpha(image)
    sheet = Image.new(
        "RGBA" if alpha else "RGB",
        (
            columnas * tile_w + (columnas - 1) * DIVIDER,
            filas * tile_h + (filas - 1) * DIVIDER,
        ),
        (255, 255, 255, 255) if alpha else "white",
    )
    for row in range(filas):
        for col in range(columnas):
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
    opname = str(op["operacion"])
    if opname == "convertir":
        return _convertir(image, op, index)
    if opname == "redimensionar":
        return _redimensionar(image, op, index), ext
    return _hoja(image, op, index)


def _apply_ops(req: Request) -> tuple[Path, list[Produced]]:
    """Open ``imagen`` and run every op in order, collecting the outputs."""
    params = dict(req.inputs)
    imagen = _imagen(params, req)
    ops = _ops(params)
    ext = imagen.suffix.lower() if imagen.suffix.lower() in MIME else ".png"
    with Image.open(imagen) as source:
        current = source.copy()
    produced: list[Produced] = []
    for index, op in enumerate(ops, start=1):
        current, ext = _apply_op(current, op, index, ext)
        opname = str(op["operacion"])
        produced.append(Produced(f"{imagen.stem}-{index}-{opname}{ext}", current, ext))
    return imagen, produced


def _asset(item: Produced, path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """One output record: image kind, measured size, seed 0."""
    width, height = item.image.size
    return {
        "file": path.name,
        "name": _asset_name(path.stem),
        "kind": "image",
        "mime": MIME.get(path.suffix.lower(), "image/png"),
        "properties": {"width": width, "height": height},
        "params": {"imagen": str(params.get("imagen", ""))},
        "seed": SEED,
        "inputs": [str(params.get("imagen", ""))],
    }


def _asset_name(stem: str) -> str:
    """A stem folded into the record's ``[a-z0-9][a-z0-9-]*`` name shape."""
    name = _BAD_NAME.sub("-", stem.lower()).strip("-")
    return name or "image"


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    _imagen_path, produced = _apply_ops(req)
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
        _imagen_path, produced = _apply_ops(req)
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
    """The imagen's stem, or empty when the request carries no imagen."""
    raw = params.get("imagen")
    return Path(str(raw)).stem if raw else ""


def _prompt(path: Path, stem: str) -> str:
    """``pillow <operacion> of <stem>`` parsed back from the asset name."""
    if not stem:
        stem = _OP_SUFFIX.sub("", path.name.rsplit(".", 1)[0])
    match = _OP_NAME.search(path.name)
    op = match.group(2) if match else "operacion"
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
