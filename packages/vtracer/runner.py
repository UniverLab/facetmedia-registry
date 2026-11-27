"""The vtracer package runner: raster-to-SVG vectorization on CPU.

Written on the runner SDK (``facet_runner_sdk``, copied into every
environment). Four verbs: ``run`` traces the piece's ``image`` (PNG,
JPEG or WebP) into ``<name>.svg`` with VisionCortex VTracer and records
the measured raster size, ``verify`` parses each SVG with ElementTree
and checks its ``svg`` root, byte size and path count, ``preview``
writes the image kind's fields for each asset, and ``doctor`` checks the
vtracer and Pillow imports plus a tiny synthetic trace.

Heavy imports go through ``importlib`` inside the functions, so the pure
XML side (verify) still answers when vtracer or Pillow is broken.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from facet_runner_sdk import Request, Runner

runner = Runner()

#: The trace is deterministic given the inputs; the seed labels the record.
SEED = 0
#: What the piece's image may be; vtracer reads each of these itself.
SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
#: The two-block fixture the doctor traces: size and the split column.
DOCTOR_SIZE = 32
DOCTOR_SPLIT = DOCTOR_SIZE // 2
#: The two colour modes the manifest declares.
COLORMODES = ("color", "binary")
DEFAULT_COLORMODE = "color"
#: The three path fittings the manifest declares.
MODES = ("spline", "polygon", "none")
DEFAULT_MODE = "spline"
#: The speckle filter the manifest declares: default, minimum, maximum.
DEFAULT_SPECKLE = 4
MIN_SPECKLE = 0
MAX_SPECKLE = 128
#: The colour precision the manifest declares: default, minimum, maximum.
DEFAULT_PRECISION = 6
MIN_PRECISION = 1
MAX_PRECISION = 8
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PULL_FIX = "facet pull vtracer"


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _image(params: dict[str, Any], req: Request) -> Path:
    """The piece's source raster, resolved against the piece directory."""
    raw = params.get("image")
    if not raw:
        raise ValueError("the piece has no image")
    path = Path(str(raw))
    if not path.is_absolute():
        path = req.piece_dir / path
    if not path.is_file():
        raise ValueError(f"{path}: no such image")
    if path.suffix.lower() not in SUFFIXES:
        raise ValueError(f"{path}: vtracer traces png, jpg, jpeg or webp, not {path.suffix!r}")
    return path


def _name(params: dict[str, Any]) -> str:
    """The asset base name; the runner writes ``<name>.svg``."""
    raw = params.get("name")
    if not raw:
        raise ValueError("the piece has no name")
    name = str(raw)
    if _NAME.fullmatch(name) is None:
        raise ValueError(f"name {name!r} must match ^[a-z0-9][a-z0-9-]*$")
    return name


def _enum(params: dict[str, Any], key: str, values: tuple[str, ...], default: str) -> str:
    """One of the manifest's enum values, defaulting when omitted."""
    value = str(params.get(key) or default)
    if value not in values:
        raise ValueError(f"{key} {value!r} is not one of {', '.join(values)}")
    return value


def _bounded_int(params: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    """An integer input inside its manifest range, defaulting when omitted."""
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer, got {value!r}")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} {value} is outside {minimum}..{maximum}")
    return value


def _raster_size(path: Path) -> tuple[int, int]:
    """The source raster's pixel size, read with Pillow."""
    pil_image = importlib.import_module("PIL.Image")
    with pil_image.open(path) as image:
        return int(image.width), int(image.height)


def _trace(
    source: Path, out: Path, colormode: str, mode: str, speckle: int, precision: int
) -> None:
    """Trace the raster into the SVG; vtracer reads and writes the files."""
    vtracer = importlib.import_module("vtracer")
    vtracer.convert_image_to_svg_py(
        str(source),
        str(out),
        colormode=colormode,
        mode=mode,
        filter_speckle=speckle,
        color_precision=precision,
    )


def _asset(
    path: Path, name: str, params: dict[str, Any], width: int, height: int
) -> dict[str, Any]:
    """One output record: the SVG beside the measured raster size."""
    return {
        "file": path.name,
        "name": name,
        "kind": "image",
        "mime": "image/svg+xml",
        "properties": {"width": width, "height": height},
        "params": {
            "image": str(params.get("image", "")),
            "name": name,
            "colormode": str(params.get("colormode") or DEFAULT_COLORMODE),
            "mode": str(params.get("mode") or DEFAULT_MODE),
            "filter-speckle": params.get("filter-speckle", DEFAULT_SPECKLE),
            "color-precision": params.get("color-precision", DEFAULT_PRECISION),
        },
        "seed": SEED,
        "inputs": [str(params.get("image", ""))],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    source = _image(params, req)
    name = _name(params)
    colormode = _enum(params, "colormode", COLORMODES, DEFAULT_COLORMODE)
    mode = _enum(params, "mode", MODES, DEFAULT_MODE)
    speckle = _bounded_int(params, "filter-speckle", DEFAULT_SPECKLE, MIN_SPECKLE, MAX_SPECKLE)
    precision = _bounded_int(
        params, "color-precision", DEFAULT_PRECISION, MIN_PRECISION, MAX_PRECISION
    )
    width, height = _raster_size(source)
    out = req.out_dir / f"{name}.svg"
    _trace(source, out, colormode, mode, speckle, precision)
    return {"tool": _tool(), "assets": [_asset(out, name, params, width, height)]}


def _local(tag: str) -> str:
    """The tag without its XML namespace, so ``<svg`` matches namespaced roots."""
    return tag.rsplit("}", 1)[-1]


def _parse_svg(path: Path) -> tuple[str, int, int]:
    """The SVG's root name, path count and byte size; raises when unreadable."""
    size = path.stat().st_size
    root = ET.parse(path).getroot()
    paths = sum(1 for element in root.iter() if _local(element.tag) == "path")
    return _local(root.tag), paths, size


def _verify_asset(path: Path) -> dict[str, Any]:
    """The file parses as XML with an ``svg`` root, bytes and a path."""
    thresholds: dict[str, Any] = {"min_bytes": 1, "min_paths": 1}
    try:
        root, count, size = _parse_svg(path)
    except (OSError, ValueError, ET.ParseError) as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": "vtracer",
        }
    passed = root == "svg" and size > 0 and count >= 1
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {"root": root, "path_count": count, "bytes": size},
        "thresholds": thresholds,
        "verifier": "vtracer",
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    return {"assets": [_verify_asset(path) for path in req.assets]}


def _preview_data(path: Path, width: int, height: int, prompt: str) -> dict[str, Any]:
    """The image schema's fields; the size is measured from the source raster."""
    name = path.stem
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


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    raw = params.get("image")
    stem = Path(str(raw)).stem if raw else ""
    prompt = f"trace of {stem}" if stem else "trace"
    width, height = _raster_size(_image(params, req))
    entries = []
    for path in req.assets:
        data = _preview_data(path, width, height, prompt)
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
    """vtracer and Pillow import, with versions."""
    found: list[str] = []
    broken: list[str] = []
    for module_name in ("vtracer", "PIL.Image"):
        try:
            module = importlib.import_module(module_name)
            found.append(f"{module_name} {getattr(module, '__version__', 'unknown')}")
        except Exception as exc:  # one broken import must not hide the other
            broken.append(f"{module_name}: {exc}")
    if broken:
        return _check("imports", False, "; ".join(broken), PULL_FIX)
    return _check("imports", True, ", ".join(found))


def _two_block(path: Path) -> None:
    """A crisp 32x32 fixture: red left, blue right, beating the speckle filter."""
    pil_image = importlib.import_module("PIL.Image")
    image = pil_image.new("RGB", (DOCTOR_SIZE, DOCTOR_SIZE))
    pixels = image.load()
    for y in range(DOCTOR_SIZE):
        for x in range(DOCTOR_SIZE):
            pixels[x, y] = (200, 30, 30) if x < DOCTOR_SPLIT else (30, 60, 200)
    image.save(path)


def _doctor_trace() -> dict[str, Any]:
    """A tiny synthetic PNG traces to an SVG that parses with a path."""
    try:
        with tempfile.TemporaryDirectory(prefix="vtracer-doctor-") as folder:
            source = Path(folder) / "doctor.png"
            out = Path(folder) / "doctor.svg"
            _two_block(source)
            _trace(source, out, DEFAULT_COLORMODE, DEFAULT_MODE, DEFAULT_SPECKLE, DEFAULT_PRECISION)
            _root, count, _size = _parse_svg(out)
    except (OSError, ValueError, ET.ParseError) as exc:
        return _check("trace", False, str(exc), PULL_FIX)
    if count < 1:
        return _check("trace", False, "the synthetic trace holds no <path>", PULL_FIX)
    return _check("trace", True, f"32x32 two-block traces to {count} paths")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_imports()]
    if req.depth == "full":
        checks.append(_doctor_trace())
    return {"checks": checks}


runner.main()
