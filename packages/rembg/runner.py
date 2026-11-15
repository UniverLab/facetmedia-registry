"""The rembg package runner: photo background removal on CPU.

Written on the runner SDK (``facet_runner_sdk``, copied into every
environment). Four verbs: ``run`` cuts the background out of the piece's
``photo`` with rembg's U2NetP on ``CPUExecutionProvider`` and writes the
alpha PNG plus a checkerboard ``-checkerboard`` PNG for edge review, ``verify``
re-opens both PNGs with Pillow, ``preview`` writes the image preview
file of each, ``doctor`` checks the imports and the weights' sha256.

Heavy imports go through ``importlib`` inside the functions, so the pure
PNG side (verify, preview, doctor) still answers when rembg or
onnxruntime is broken; the weights arrive through ``facet pull`` and are
found through ``U2NET_HOME``, the directory rembg itself downloads into.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from facet_runner_sdk import Request, Runner
from PIL import Image, ImageDraw, ImageFilter

runner = Runner()

#: The manifest model id and the session rembg builds for it.
MODEL_ID = "u2netp"
MODEL_NAME = "u2netp"
#: CPU only: the manifest declares gpu = false and the lab measured this.
PROVIDERS = ["CPUExecutionProvider"]
#: The checkerboard tile of the ``-checkerboard`` review image, as in the lab.
CHECKER_TILE = 32
CHECKER_FILL = "#d8dde2"
PULL_FIX = "facet pull rembg"
#: The cutout is deterministic given the weights; the seed labels the record.
SEED = 0
#: Clean paper: the mask threshold, the filter sizes and the paper sampling.
PAPER_THRESHOLD = 40
MAXFILTER = 15
BLUR = 6
BORDER_ROWS = 30
BORDER_INSET = 300
GRAIN_SIGMA = 1.6
GRAIN_SEED = 7
#: What the doctor proves importable, with the distribution each comes from.
DOCTOR_IMPORTS = (
    ("rembg", "rembg"),
    ("onnxruntime", "onnxruntime"),
    ("PIL", "pillow"),
)
_BAD_NAME = re.compile(r"[^a-z0-9-]+")


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity and the weights hash."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _capability(req: Request) -> str:
    """The bare capability name (cutout or paper) this request asked for."""
    return req.capability.rsplit(".", 1)[-1]


def _photo(params: dict[str, Any], req: Request) -> Path:
    """The piece's photo, resolved against the piece directory."""
    raw = params.get("photo")
    if not raw:
        raise ValueError("the piece has no photo")
    path = Path(str(raw))
    if not path.is_absolute():
        path = req.piece_dir / path
    if not path.is_file():
        raise ValueError(f"{path}: no such photo")
    return path


def _plate(params: dict[str, Any], req: Request) -> Path:
    """The piece's plate, resolved against the piece directory."""
    raw = params.get("plate")
    if not raw:
        raise ValueError("the piece has no plate")
    path = Path(str(raw))
    if not path.is_absolute():
        path = req.piece_dir / path
    if not path.is_file():
        raise ValueError(f"{path}: no such plate")
    return path


def _weights(req: Request) -> Path:
    """The pulled u2netp.onnx; rembg finds it through ``U2NET_HOME``."""
    return req.model_path(MODEL_ID)


def _session(req: Request) -> Any:
    """A U2NetP session on CPU, pointed at the pulled weights."""
    rembg = importlib.import_module("rembg")
    os.environ["U2NET_HOME"] = str(_weights(req).parent)
    return rembg.new_session(MODEL_NAME, providers=list(PROVIDERS))


def _checkerboard(cutout: Image.Image) -> Image.Image:
    """The cutout over a white/checkerboard, for judging edges by eye."""
    checker = Image.new("RGB", cutout.size, "white")
    draw = ImageDraw.Draw(checker)
    for y in range(0, checker.height, CHECKER_TILE):
        for x in range(0, checker.width, CHECKER_TILE):
            if (x // CHECKER_TILE + y // CHECKER_TILE) % 2:
                draw.rectangle(
                    (x, y, x + CHECKER_TILE - 1, y + CHECKER_TILE - 1), fill=CHECKER_FILL
                )
    checker.paste(cutout, mask=cutout.getchannel("A"))
    return checker


def _asset_name(stem: str) -> str:
    """A stem folded into the record's ``[a-z0-9][a-z0-9-]*`` name shape."""
    name = _BAD_NAME.sub("-", stem.lower()).strip("-")
    return name or "cutout"


def _size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _paper_color(rgb: np.ndarray) -> np.ndarray:
    """The border median: 30 rows top and bottom, 300 px in from each side.

    A plate smaller than the scan the numbers were tuned on keeps the same
    shape at its own scale (a tenth of the height, a quarter of the width),
    so the border is never empty and the paper never comes out black.
    """
    height, width = rgb.shape[:2]
    rows = max(1, min(BORDER_ROWS, height // 10))
    inset = min(BORDER_INSET, width // 4)
    border = np.concatenate(
        [
            rgb[:rows, inset : width - inset].reshape(-1, 3),
            rgb[height - rows :, inset : width - inset].reshape(-1, 3),
        ]
    )
    return np.median(border, axis=0)


def _paper_mask(mask: Image.Image) -> Image.Image:
    """The plate silhouette: threshold 40, MaxFilter 15, GaussianBlur 6."""
    return (
        mask.convert("L")
        .point(lambda value: 255 if value > PAPER_THRESHOLD else 0)
        .filter(ImageFilter.MaxFilter(MAXFILTER))
        .filter(ImageFilter.GaussianBlur(BLUR))
    )


def _clean_paper(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Object pixels kept, everything else blended into even paper with grain."""
    alpha = np.asarray(mask, dtype=float)[..., None] / 255
    rgb = np.asarray(image, dtype=float)
    paper = _paper_color(rgb)
    rng = np.random.default_rng(GRAIN_SEED)
    grain = rng.normal(0, GRAIN_SIGMA, rgb.shape[:2])[..., None]
    clean = np.clip(paper + grain, 0, 255)
    return Image.fromarray((rgb * alpha + clean * (1 - alpha)).astype(np.uint8))


def _asset(
    photo: Path, path: Path, params: dict[str, Any], checkerboard: bool = False
) -> dict[str, Any]:
    """One output record: both PNGs share the photo's stem as their name."""
    width, height = _size(path)
    properties: dict[str, Any] = {"width": width, "height": height}
    if checkerboard:
        properties["checkerboard"] = True
    return {
        "file": path.name,
        "name": _asset_name(photo.stem),
        "kind": "image",
        "mime": "image/png",
        "properties": properties,
        "params": {"photo": str(params["photo"])},
        "seed": SEED,
        "inputs": [str(params["photo"])],
    }


def _paper_asset(plate: Path, path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """The clean-paper output record, named after the plate's stem."""
    width, height = _size(path)
    return {
        "file": path.name,
        "name": _asset_name(plate.stem),
        "kind": "image",
        "mime": "image/png",
        "properties": {"width": width, "height": height},
        "params": {"plate": str(params["plate"])},
        "seed": SEED,
        "inputs": [str(params["plate"])],
    }


def _run_cutout(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    photo = _photo(params, req)
    rembg = importlib.import_module("rembg")
    cutout = rembg.remove(Image.open(photo).convert("RGBA"), session=_session(req))
    stem = photo.stem
    cutout_path = req.out_dir / f"{stem}.png"
    checkerboard_path = req.out_dir / f"{stem}-checkerboard.png"
    cutout.save(cutout_path)
    _checkerboard(cutout).save(checkerboard_path)
    assets = [
        _asset(photo, cutout_path, params),
        _asset(photo, checkerboard_path, params, checkerboard=True),
    ]
    return {"tool": _tool(), "assets": assets}


def _run_paper(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    plate = _plate(params, req)
    rembg = importlib.import_module("rembg")
    image = Image.open(plate).convert("RGB")
    mask = rembg.remove(image, session=_session(req), only_mask=True)
    clean = _clean_paper(image, _paper_mask(mask))
    path = req.out_dir / f"{plate.stem}-paper.png"
    clean.save(path)
    return {"tool": _tool(), "assets": [_paper_asset(plate, path, params)]}


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    if _capability(req) == "paper":
        return _run_paper(req)
    return _run_cutout(req)


def _expected_mode(req: Request, path: Path) -> str:
    """RGBA for the cutout, RGB for its ``-checkerboard`` sibling and for clean paper.

    The piece's ``photo`` names both files exactly; without it the ``-checkerboard``
    suffix is the fallback.
    """
    if _capability(req) == "paper":
        return "RGB"
    photo = dict(req.inputs).get("photo")
    if photo:
        stem = Path(str(photo)).stem
        if path.name == f"{stem}-checkerboard.png":
            return "RGB"
        if path.name == f"{stem}.png":
            return "RGBA"
    return "RGB" if path.name.endswith("-checkerboard.png") else "RGBA"


def _is_flat(extrema: Any) -> bool:
    """Every band holds one value: a uniform image, never a real cutout or paper."""
    bands = extrema if isinstance(extrema[0], tuple) else (extrema,)
    return all(low == high for low, high in bands)


def _verify_asset(req: Request, path: Path) -> dict[str, Any]:
    """The PNG opens, is a PNG, and carries the mode its role demands."""
    expected = _expected_mode(req, path)
    thresholds: dict[str, Any] = {"mode": expected}
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
    with Image.open(path) as image:
        flat = _is_flat(image.getextrema())
    thresholds["flat"] = False
    passed = path.suffix == ".png" and mode == expected and not flat
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {"mode": mode, "width": width, "height": height, "flat": flat},
        "thresholds": thresholds,
        "verifier": "pillow",
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    return {"assets": [_verify_asset(req, path) for path in req.assets]}


def _preview_data(path: Path, name: str, prompt: str) -> dict[str, Any]:
    """The image schema's fields, measured from the PNG itself."""
    width, height = _size(path)
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


def _preview_source(req: Request, params: dict[str, Any]) -> tuple[str, str]:
    """The input's stem and the prompt that labels the record."""
    if _capability(req) == "paper":
        plate = params.get("plate")
        stem = Path(str(plate)).stem if plate else ""
        return stem, f"clean paper of {stem}" if stem else "clean paper"
    photo = params.get("photo")
    stem = Path(str(photo)).stem if photo else ""
    return stem, f"cutout of {stem}" if stem else "cutout"


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    stem, prompt = _preview_source(req, params)
    name = _asset_name(stem)
    entries = []
    for path in req.assets:
        data = _preview_data(path, name, prompt)
        preview_name = f"{path.name}.preview.json"
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _doctor_imports(depth: str = "quick") -> dict[str, Any]:
    """rembg, onnxruntime and Pillow, each with its version.

    The quick depth only finds each module and reads its installed version:
    importing onnxruntime and rembg cold overruns the 10 s quick budget. The
    full depth imports them, so a module present but broken still fails.
    """
    found: list[str] = []
    broken: list[str] = []
    for module_name, distribution in DOCTOR_IMPORTS:
        try:
            if depth != "full":
                if importlib.util.find_spec(module_name) is None:
                    raise ModuleNotFoundError(f"No module named {module_name!r}")
                found.append(f"{module_name} {_version(distribution)}")
                continue
            module = importlib.import_module(module_name)
            found.append(f"{module_name} {getattr(module, '__version__', _version(distribution))}")
        except Exception as exc:  # catch-all: one broken import must not hide the rest
            broken.append(f"{module_name}: {exc}")
    if broken:
        return _check("imports", False, "; ".join(broken), PULL_FIX)
    return _check("imports", True, ", ".join(found))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_model() -> dict[str, Any]:
    models = _manifest().get("models")
    for model in models if isinstance(models, list) else []:
        if str(model.get("id")) == MODEL_ID:
            return model
    raise ValueError(f"package.toml has no model {MODEL_ID!r}")


def _doctor_weights(req: Request) -> dict[str, Any]:
    """u2netp.onnx exists and hashes to the sha256 the manifest declares."""
    model = _manifest_model()
    want = str(model["sha256"])
    want_bytes = int(model["bytes"])
    try:
        path = _weights(req)
    except KeyError:
        return _check("weights", False, f"{MODEL_ID}: not in this request", PULL_FIX)
    if not path.is_file():
        return _check("weights", False, f"{MODEL_ID}: missing at {path}", PULL_FIX)
    size = path.stat().st_size
    if size != want_bytes:
        return _check(
            "weights",
            False,
            f"{MODEL_ID}: {size} bytes, manifest says {want_bytes}",
            PULL_FIX,
        )
    got = _sha256(path)
    if got != want:
        return _check(
            "weights",
            False,
            f"{MODEL_ID}: sha256 {got[:12]}…, manifest says {want[:12]}…",
            PULL_FIX,
        )
    return _check("weights", True, f"{MODEL_ID} {size} B, sha256 verified")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    return {"checks": [_doctor_imports(req.depth), _doctor_weights(req)]}


runner.main()
