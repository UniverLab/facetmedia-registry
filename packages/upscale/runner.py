"""The upscale package runner: 2x and 4x image super-resolution via Real-ESRGAN ncnn Vulkan.

Four verbs on ``facet_runner_sdk``:
- ``run``: extracts the pinned ``realesrgan-ncnn-vulkan`` release zip once beside
  the archive, upscales the input image (using native 2x/4x for
  ``realesr-animevideov3``, or 4x + Pillow LANCZOS downscale for 2x on 4x-only
  models), and returns one ``image`` asset with measured dimensions and bytes.
- ``verify``: re-opens outputs with Pillow and checks exact scaled dimensions,
  valid format, and non-blank pixel extrema.
- ``preview``: emits ``<asset>.preview.json`` matching ``schemas/preview/image.schema.json``.
- ``doctor``: ``quick`` checks zip, extracted binary, models dir, and Pillow;
  ``full`` upscales a synthetic 16x16 PNG to 64x64 in a temp directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import PIL
from facet_runner_sdk import Request, Runner
from PIL import Image

runner = Runner()

MODEL_ID = "realesrgan-ncnn-vulkan-20220424-ubuntu"
TOOL = {"name": "Real-ESRGAN", "version": "0.2.5.0"}
VERIFIER = "upscale"
BINARY_NAME = "realesrgan-ncnn-vulkan"
EXTRACT_DIRNAME = "_extracted"
MARKER_NAME = "zip.sha256"
SEED = 0
RUN_TIMEOUT_S = 300

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
BAD_NAME_RE = re.compile(r"[^a-z0-9-]+")
MODELS = ("realesrgan-x4plus", "realesrgan-x4plus-anime", "realesr-animevideov3")
NATIVE_2X_MODELS = frozenset({"realesr-animevideov3"})
SCALES = ("2", "4")
FORMATS: dict[str, tuple[str, str]] = {
    "png": ("PNG", "image/png"),
    "jpg": ("JPEG", "image/jpeg"),
    "webp": ("WEBP", "image/webp"),
}


def _manifest() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "package.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _find_extracted(root: Path) -> tuple[Path, Path] | None:
    """Locate binary and models/ in either flat or 1-subdir zip layout."""
    if not root.is_dir():
        return None
    flat_bin = root / BINARY_NAME
    flat_models = root / "models"
    if flat_bin.is_file() and flat_models.is_dir():
        return flat_bin, flat_models
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        sub_bin = child / BINARY_NAME
        sub_models = child / "models"
        if sub_bin.is_file() and sub_models.is_dir():
            return sub_bin, sub_models
    return None


def _ensure_binary(archive: Path) -> tuple[Path, Path]:
    """Extract the pinned zip once beside ``archive`` and return ``(binary, models_dir)``."""
    if not archive.is_file():
        raise RuntimeError(f"{archive}: Real-ESRGAN zip is missing; run facet pull upscale")
    digest = _sha256(archive)
    root = archive.parent / EXTRACT_DIRNAME
    marker = root / MARKER_NAME
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest:
        found = _find_extracted(root)
        if found is not None:
            found[0].chmod(0o755)
            return found
    return _unpack(archive, root, digest)


def _unpack(archive: Path, root: Path, digest: str) -> tuple[Path, Path]:
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(root)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"{archive}: cannot extract Real-ESRGAN zip: {exc}") from exc
    found = _find_extracted(root)
    if found is None:
        raise RuntimeError(f"{archive}: zip lacks {BINARY_NAME} and models/")
    binary, models_dir = found
    binary.chmod(0o755)
    (root / MARKER_NAME).write_text(digest + "\n", encoding="utf-8")
    return binary, models_dir


def _resolve_source(params: Mapping[str, Any], req: Request) -> Path:
    raw = str(params.get("image", "")).strip()
    if not raw:
        raise ValueError("upscale.enhance: 'image' input is required")
    candidate = Path(raw)
    if not candidate.is_absolute():
        base = Path(str(req.piece_dir)) if str(req.piece_dir) else Path(".")
        candidate = base / candidate
    if not candidate.is_file():
        raise FileNotFoundError(f"{candidate}: source image not found")
    return candidate


def _validate_inputs(params: Mapping[str, Any]) -> tuple[str, str, str, str]:
    name = str(params.get("name", ""))
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"upscale.enhance: invalid name {name!r}")
    scale = str(params.get("scale", "4"))
    if scale not in SCALES:
        raise ValueError(f"upscale.enhance: invalid scale {scale!r}")
    model = str(params.get("model", "realesrgan-x4plus"))
    if model not in MODELS:
        raise ValueError(f"upscale.enhance: invalid model {model!r}")
    fmt = str(params.get("format", "png"))
    if fmt not in FORMATS:
        raise ValueError(f"upscale.enhance: invalid format {fmt!r}")
    return name, scale, model, fmt


def _invoke(
    binary: Path,
    src: Path,
    dst: Path,
    *,
    model: str,
    models_dir: Path,
    scale: str,
    fmt: str,
) -> None:
    argv: Sequence[str] = [
        str(binary),
        "-i",
        str(src),
        "-o",
        str(dst),
        "-n",
        model,
        "-m",
        str(models_dir),
        "-s",
        scale,
        "-f",
        fmt,
    ]
    try:
        done = subprocess.run(
            argv,
            cwd=str(dst.parent),
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{BINARY_NAME} could not run: {exc}") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()[-3:]
        raise RuntimeError(f"{BINARY_NAME} exited {done.returncode}: {' / '.join(detail)}")


def _save_downscaled_2x(tmp_4x: Path, out_path: Path, src_size: tuple[int, int], fmt: str) -> None:
    target_size = (src_size[0] * 2, src_size[1] * 2)
    pil_fmt = FORMATS[fmt][0]
    with Image.open(tmp_4x) as img:
        resized = img.resize(target_size, Image.Resampling.LANCZOS)
        if fmt == "jpg" and resized.mode != "RGB":
            resized = resized.convert("RGB")
        resized.save(out_path, format=pil_fmt)


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    name, scale, model, fmt = _validate_inputs(params)
    src = _resolve_source(params, req)
    with Image.open(src) as img:
        src_w, src_h = img.size

    binary, models_dir = _ensure_binary(req.model_path(MODEL_ID))
    out_dir = Path(os.path.abspath(req.out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.{fmt}"

    if scale == "2" and model not in NATIVE_2X_MODELS:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_4x = Path(tmp_dir) / "upscale_4x.png"
            _invoke(binary, src, tmp_4x, model=model, models_dir=models_dir, scale="4", fmt="png")
            _save_downscaled_2x(tmp_4x, out_path, (src_w, src_h), fmt)
    else:
        _invoke(binary, src, out_path, model=model, models_dir=models_dir, scale=scale, fmt=fmt)

    with Image.open(out_path) as out_img:
        width, height = out_img.size

    return {
        "tool": dict(TOOL),
        "assets": [
            {
                "file": out_path.name,
                "name": name,
                "kind": "image",
                "mime": FORMATS[fmt][1],
                "properties": {
                    "width": width,
                    "height": height,
                    "bytes": out_path.stat().st_size,
                },
                "params": {
                    "image": str(params.get("image", "")),
                    "scale": scale,
                    "model": model,
                    "format": fmt,
                },
                "seed": SEED,
                "inputs": [str(params.get("image", ""))],
            }
        ],
    }


def _non_blank(img: Image.Image) -> bool:
    extrema = img.convert("RGB").getextrema()
    return any(lo != hi for lo, hi in extrema)


def _verify_one(
    path: Path, src_size: tuple[int, int], scale: int, expected_fmt: str
) -> dict[str, Any]:
    want_w, want_h = src_size[0] * scale, src_size[1] * scale
    want_pil_fmt = FORMATS[expected_fmt][0]
    thresholds = {"width": want_w, "height": want_h, "format": want_pil_fmt}
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
            pil_fmt = (img.format or "").upper()
            non_blank = _non_blank(img)
    except (OSError, ValueError) as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": VERIFIER,
        }

    suffix_ok = path.suffix.lower() == f".{expected_fmt}"
    passed = (
        suffix_ok and pil_fmt == want_pil_fmt and width == want_w and height == want_h and non_blank
    )
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {
            "width": width,
            "height": height,
            "format": pil_fmt,
            "non_blank": non_blank,
        },
        "thresholds": thresholds,
        "verifier": VERIFIER,
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    scale = int(str(params.get("scale", "4")))
    expected_fmt = str(params.get("format", "png"))
    if expected_fmt not in FORMATS:
        expected_fmt = "png"
    src = _resolve_source(params, req)
    with Image.open(src) as img:
        src_size = img.size
    return {
        "assets": [_verify_one(path, src_size, scale, expected_fmt) for path in req.assets],
    }


def _asset_name(stem: str) -> str:
    cleaned = BAD_NAME_RE.sub("-", stem.lower()).strip("-")
    return cleaned or "image"


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    scale = str(params.get("scale", "4"))
    model = str(params.get("model", "realesrgan-x4plus"))
    raw_img = str(params.get("image", ""))
    entries = []
    for path in req.assets:
        src_stem = Path(raw_img).stem if raw_img else path.stem
        with Image.open(path) as img:
            width, height = img.size
        name = _asset_name(path.stem)
        data = {
            "preview": 1,
            "kind": "image",
            "summary": f"{name} · {width}×{height}"[:160],
            "name": name,
            "prompt": f"upscale {scale}x ({model}) of {src_stem}",
            "seed": SEED,
            "width": width,
            "height": height,
        }
        preview_name = f"{path.name}.preview.json"
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_zip(req: Request) -> dict[str, Any]:
    expected = {str(m["id"]): int(m["bytes"]) for m in _manifest().get("models", [])}
    want = expected.get(MODEL_ID, 0)
    try:
        archive = req.model_path(MODEL_ID)
    except KeyError:
        return _check("zip", False, f"{MODEL_ID}: not in request", "facet pull upscale")
    if not archive.is_file():
        return _check("zip", False, f"{archive}: missing", "facet pull upscale")
    actual = archive.stat().st_size
    if want and actual != want:
        return _check(
            "zip", False, f"{archive}: {actual} bytes, manifest says {want}", "facet pull upscale"
        )
    return _check("zip", True, f"{MODEL_ID} {actual} B")


def _doctor_binary(req: Request) -> dict[str, Any]:
    try:
        binary, models_dir = _ensure_binary(req.model_path(MODEL_ID))
    except (KeyError, OSError, RuntimeError) as exc:
        return _check("binary", False, str(exc), "facet pull upscale")
    if not os.access(binary, os.X_OK):
        return _check("binary", False, f"{binary}: not executable", "facet pull upscale")
    if not models_dir.is_dir():
        return _check(
            "binary", False, f"{models_dir}: models directory missing", "facet pull upscale"
        )
    return _check("binary", True, f"{binary} + {models_dir}")


def _doctor_imports() -> dict[str, Any]:
    version = str(getattr(PIL, "__version__", "unknown"))
    return _check("imports", True, f"pillow {version}")


def _doctor_full(req: Request) -> dict[str, Any]:
    try:
        binary, models_dir = _ensure_binary(req.model_path(MODEL_ID))
    except (KeyError, OSError, RuntimeError) as exc:
        return _check("vulkan", False, str(exc), "facet pull upscale")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        src = tmp / "in.png"
        dst = tmp / "out.png"
        img = Image.new("RGB", (16, 16), (40, 120, 200))
        img.putpixel((0, 0), (240, 240, 240))
        img.save(src, format="PNG")
        try:
            _invoke(
                binary,
                src,
                dst,
                model="realesrgan-x4plus",
                models_dir=models_dir,
                scale="4",
                fmt="png",
            )
            with Image.open(dst) as out:
                w, h = out.size
        except (RuntimeError, OSError, ValueError) as exc:
            return _check("vulkan", False, f"Vulkan/ncnn upscale failed: {exc}")
        if (w, h) != (64, 64):
            return _check("vulkan", False, f"expected 64x64 output, got {w}x{h}")
    return _check("vulkan", True, "16x16 -> 64x64 PNG via realesrgan-x4plus")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_zip(req), _doctor_binary(req), _doctor_imports()]
    if req.depth == "full":
        checks.append(_doctor_full(req))
    return {"checks": checks}


if __name__ == "__main__":
    runner.main()
