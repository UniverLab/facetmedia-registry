"""The demostage package runner: terminal demos from hand-written scores.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` executes a hand-written ``demo.toml`` score with
``demo record`` and renders the recording to a gif and an animated svg with
``demo export``; ``verify`` reads both files back; ``preview`` writes the video
and image previews; ``doctor`` checks the person-installed binary and its
version.

The demo CLI does not speak the runner protocol — its verbs are
``capture/record/export/edit/doctor``, never ``run --input/--result`` — so the
package is a python-env subprocess client, not an ``[engine.binary]`` package.
``demo record`` allocates its own PTY, so no caller terminal is needed;
``demo capture`` is deliberately absent because it reads stdin from an
interactive terminal a facet runner does not have, and scores are written by
hand anyway.
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from facet_runner_sdk import Request, Runner

runner = Runner()

TOOL_NAME = "demostage"
#: The oldest demo the runner accepts; older installs lack the svg export.
MIN_VERSION = (0, 4, 0)
HOST_HINT = "curl -fsSL https://get.univerlab.org/demostage | sh"
RECORDING_NAME = "demo.rec"
WORK_DIRNAME = "_demostage"
DEFAULT_OUTPUT_DIR = "./dist"
DEFAULT_FPS = 15
DEFAULT_SEED = 0
RUN_TIMEOUT_S = 900
VERSION_TIMEOUT_S = 15
TAIL_LINES = 3
SUMMARY_MAX = 160
GIF_MAGIC = (b"GIF87a", b"GIF89a")
GIF_HEADER_BYTES = 13
GIF_CONTROL_DELAY_BYTES = 3
VIEWBOX_PARTS = 4
GIF_TRAILER = 0x3B
GIF_EXTENSION = 0x21
GIF_GRAPHIC_CONTROL = 0xF9
GIF_IMAGE = 0x2C
GIF_LOCAL_TABLE = 0x80
GIF_TABLE_MASK = 0x07
VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")
LENGTH_PATTERN = re.compile(r"\s*([0-9]+(?:\.[0-9]+)?)")
VERIFIER = "demostage"


def _demo() -> tuple[str, str]:
    """The person-installed ``demo`` binary and its version, checked here."""
    binary = shutil.which("demo")
    if binary is None:
        raise RuntimeError(f"demo is not on PATH; install it with: {HOST_HINT}")
    version = _version(binary)
    if _semver(version) < MIN_VERSION:
        minimum = _semver_text(MIN_VERSION)
        raise RuntimeError(
            f"demo {version} at {binary} is older than {minimum}; update it with: {HOST_HINT}"
        )
    return binary, version


def _version(binary: str) -> str:
    """The semantic version ``demo --version`` prints, as ``x.y.z``."""
    try:
        done = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"demo --version could not run: {exc}") from exc
    match = VERSION_PATTERN.search(done.stdout + done.stderr)
    if match is None:
        raise RuntimeError(
            f"demo --version printed no version: {(done.stdout + done.stderr).strip()!r}"
        )
    return match.group(0)


def _semver(value: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in value.split("."))
    return major, minor, patch


def _semver_text(value: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in value)


def _score(partitura: Path) -> dict[str, Any]:
    """The hand-written score, which must carry the ``[demo]`` table."""
    try:
        data = tomllib.loads(partitura.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{partitura.name}: cannot read the demo score: {exc}") from exc
    demo = data.get("demo")
    if not isinstance(demo, dict):
        raise ValueError(f"{partitura.name}: the score has no [demo] table")
    return data


def _demo_table(score: Mapping[str, Any]) -> Mapping[str, Any]:
    table = score.get("demo")
    return table if isinstance(table, Mapping) else {}


def _sanitize(name: str) -> str:
    """The demo binary's own filename rule: alphanumerics, dash and underscore."""
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "-" for character in name
    )
    return cleaned or "demo"


def _preview_name(stem: str) -> str:
    """The preview schemas' asset name: lowercase, alphanumerics and dash."""
    cleaned = re.sub(r"[^a-z0-9-]+", "-", stem.lower()).strip("-")
    return cleaned or "demo"


def _score_name(score: Mapping[str, Any], partitura: Path) -> str:
    raw = _demo_table(score).get("name")
    return _sanitize(raw) if isinstance(raw, str) and raw.strip() else _sanitize(partitura.stem)


def _fps(score: Mapping[str, Any]) -> int:
    layout = score.get("layout")
    value = layout.get("fps") if isinstance(layout, Mapping) else None
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1
        else DEFAULT_FPS
    )


def _seed(score: Mapping[str, Any]) -> int:
    typing = score.get("typing")
    value = typing.get("seed") if isinstance(typing, Mapping) else None
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else DEFAULT_SEED
    )


def _execute(argv: Sequence[str], cwd: Path) -> None:
    """Run one demo verb from its own directory; a non-zero exit fails the run."""
    try:
        done = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{Path(argv[0]).name} could not run: {exc}") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-TAIL_LINES:]
        raise RuntimeError(
            f"{Path(argv[0]).name} {argv[1] if len(argv) > 1 else ''} exited "
            f"{done.returncode}: {' / '.join(tail)}"
        )


def _export_dir(score: Mapping[str, Any], work: Path) -> Path:
    """Where the score says exports land, resolved against the export cwd."""
    raw = _demo_table(score).get("output_dir")
    declared = Path(raw) if isinstance(raw, str) and raw.strip() else Path(DEFAULT_OUTPUT_DIR)
    return declared if declared.is_absolute() else work / declared


def _collect(score: Mapping[str, Any], work: Path, stem: str) -> tuple[Path, Path]:
    """The gif and svg the export must have written, named by the score."""
    folder = _export_dir(score, work)
    gif = folder / f"{stem}.gif"
    svg = folder / f"{stem}.svg"
    for path in (gif, svg):
        if not path.is_file():
            raise RuntimeError(f"{path}: demo export wrote no {path.suffix} for {stem}")
    return gif, svg


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    partitura = Path(str(params["partitura"]))
    score = _score(partitura)
    binary, version = _demo()
    work = req.out_dir / WORK_DIRNAME
    work.mkdir(parents=True, exist_ok=True)
    recording = work / RECORDING_NAME
    _execute([binary, "record", str(partitura), "-o", str(recording)], partitura.parent)
    _execute([binary, "export", "gif,svg", str(recording)], work)
    stem = _score_name(score, partitura)
    gif, svg = _collect(score, work, stem)
    _place(gif, req.out_dir)
    _place(svg, req.out_dir)
    probe = _gif_probe(req.out_dir / gif.name)
    width, height = _svg_size(req.out_dir / svg.name)
    fps = _fps(score)
    seed = _seed(score)
    inputs = [str(partitura)]
    gif_path = req.out_dir / gif.name
    svg_path = req.out_dir / svg.name
    gif_name = _preview_name(gif_path.stem)
    svg_name = _preview_name(svg_path.stem)
    return {
        "tool": {"name": TOOL_NAME, "version": version},
        "assets": [
            _asset(
                params,
                gif_path,
                {"name": gif_name, "kind": "video", "mime": "image/gif"},
                {
                    "width": probe["width"],
                    "height": probe["height"],
                    "frames": probe["frames"],
                    "duration_s": probe["duration_s"],
                    "fps": fps,
                },
                seed,
                inputs,
            ),
            _asset(
                params,
                svg_path,
                {"name": svg_name, "kind": "image", "mime": "image/svg+xml"},
                {"width": width, "height": height},
                seed,
                inputs,
            ),
        ],
    }


def _place(path: Path, out_dir: Path) -> None:
    """Move an export into the run's output root unless it already lives there."""
    target = out_dir / path.name
    if path.resolve() != target.resolve():
        shutil.move(str(path), str(target))


def _asset(
    params: Mapping[str, Any],
    path: Path,
    meta: Mapping[str, str],
    properties: Mapping[str, Any],
    seed: int,
    inputs: Sequence[str],
) -> dict[str, Any]:
    return {
        "file": path.name,
        "name": meta["name"],
        "kind": meta["kind"],
        "mime": meta["mime"],
        "properties": dict(properties),
        "params": dict(params),
        "seed": seed,
        "inputs": list(inputs),
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    return {"assets": [_verdict(path) for path in req.assets]}


def _verdict(path: Path) -> dict[str, Any]:
    try:
        metrics = _measure(path)
    except (OSError, ValueError) as exc:
        return _entry(path.name, False, {"error": str(exc)})
    return _entry(path.name, True, metrics)


def _measure(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".gif":
        probe = _gif_probe(path)
        return {
            "width": probe["width"],
            "height": probe["height"],
            "frames": probe["frames"],
            "duration_s": probe["duration_s"],
        }
    if suffix == ".svg":
        width, height = _svg_size(path)
        return {"width": width, "height": height}
    raise ValueError(f"{path.name}: not a demostage gif or svg")


def _entry(file: str, passed: bool, metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "file": file,
        "passed": passed,
        "metrics": dict(metrics),
        "thresholds": {},
        "verifier": VERIFIER,
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    score = _param_score(params)
    entries = []
    for path in req.assets:
        data = _preview_data(path, score)
        name = f"{path.name}.preview.json"
        body = json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n"
        (req.out_dir / name).write_text(body, encoding="utf-8")
        entries.append({"file": path.name, "preview": name, "images": []})
    return {"assets": entries}


def _param_score(params: Mapping[str, Any]) -> dict[str, Any]:
    """The score behind an asset, when the record's params still point at it."""
    raw = params.get("partitura")
    if not isinstance(raw, str):
        return {}
    try:
        return _score(Path(raw))
    except ValueError:
        return {}


def _preview_data(path: Path, score: Mapping[str, Any]) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".gif":
        return _video_preview(path, score)
    if suffix == ".svg":
        return _image_preview(path, score)
    raise ValueError(f"{path.name}: preview a demostage gif or svg, not this file")


def _prompt(score: Mapping[str, Any], fallback: str) -> str:
    raw = _demo_table(score).get("name")
    label = raw.strip() if isinstance(raw, str) and raw.strip() else fallback
    return f"terminal demo from the score {label}"


def _video_preview(path: Path, score: Mapping[str, Any]) -> dict[str, Any]:
    """The video schema's fields, measured from the gif."""
    probe = _gif_probe(path)
    name = _preview_name(path.stem)
    fps = _fps(score)
    summary = (
        f"{name} · {probe['width']}×{probe['height']} · "
        f"{probe['frames']} frames · {probe['duration_s']} s @ {fps} fps"
    )
    return {
        "preview": 1,
        "kind": "video",
        "summary": summary[:SUMMARY_MAX],
        "name": name,
        "prompt": _prompt(score, name),
        "seed": _seed(score),
        "width": probe["width"],
        "height": probe["height"],
        "length": probe["frames"],
        "fps": fps,
    }


def _image_preview(path: Path, score: Mapping[str, Any]) -> dict[str, Any]:
    """The image schema's fields, for the animated terminal-only svg."""
    width, height = _svg_size(path)
    name = _preview_name(path.stem)
    summary = f"{name} · animated terminal demo · {width}×{height}"
    return {
        "preview": 1,
        "kind": "image",
        "summary": summary[:SUMMARY_MAX],
        "name": name,
        "prompt": _prompt(score, name),
        "seed": _seed(score),
        "width": width,
        "height": height,
    }


def _gif_probe(path: Path) -> dict[str, Any]:
    """The gif's screen size, frame count and summed delay, from its bytes."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{path.name}: cannot read the gif: {exc}") from exc
    if len(data) < GIF_HEADER_BYTES or data[:6] not in GIF_MAGIC:
        raise ValueError(f"{path.name}: not a gif")
    width, height = struct.unpack("<HH", data[6:10])
    position = _after_colour_table(data, 13, data[10])
    frames, delays = _gif_blocks(data, position)
    if frames < 1:
        raise ValueError(f"{path.name}: the gif has no frames")
    return {
        "width": width,
        "height": height,
        "frames": frames,
        "duration_s": round(sum(delays) / 100.0, 3),
    }


def _after_colour_table(data: bytes, position: int, packed: int) -> int:
    if packed & GIF_LOCAL_TABLE:
        return position + 3 * (2 ** ((packed & GIF_TABLE_MASK) + 1))
    return position


def _gif_blocks(data: bytes, position: int) -> tuple[int, list[int]]:
    """Walk the gif's extensions and image descriptors; count frames and delays."""
    frames = 0
    delays: list[int] = []
    pending = 0
    while position < len(data):
        block = data[position]
        if block == GIF_TRAILER:
            return frames, delays
        if block == GIF_EXTENSION:
            label = _byte(data, position + 1)
            position, first = _skip_subblocks(data, position + 2)
            if label == GIF_GRAPHIC_CONTROL and len(first) >= GIF_CONTROL_DELAY_BYTES:
                pending = first[1] | (first[2] << 8)
            continue
        if block == GIF_IMAGE:
            position = _after_image_descriptor(data, position)
            position, _ = _skip_subblocks(data, position)
            frames += 1
            delays.append(pending)
            pending = 0
            continue
        raise ValueError(f"unknown gif block 0x{block:02x}")
    raise ValueError("the gif has no trailer")


def _after_image_descriptor(data: bytes, position: int) -> int:
    """Past the 10-byte descriptor, its colour table and the code-size byte."""
    packed = _byte(data, position + 9)
    position = _after_colour_table(data, position + 10, packed)
    return position + 1


def _byte(data: bytes, position: int) -> int:
    if position >= len(data):
        raise ValueError("the gif ends inside a block")
    return data[position]


def _skip_subblocks(data: bytes, position: int) -> tuple[int, bytes]:
    """Past a sub-block chain, carrying the first block's bytes for delays."""
    first = b""
    while True:
        size = _byte(data, position)
        position += 1
        if size == 0:
            return position, first
        if position + size > len(data):
            raise ValueError("the gif ends inside a sub-block")
        if not first:
            first = data[position : position + size]
        position += size


def _svg_size(path: Path) -> tuple[int, int]:
    """The svg's declared width and height, falling back to its viewBox."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"{path.name}: cannot parse the svg: {exc}") from exc
    width = _dimension(root.get("width"))
    height = _dimension(root.get("height"))
    if width is None or height is None:
        box = _viewbox_size(root.get("viewBox"))
        width, height = box if box is not None else (None, None)
    if width is None or height is None:
        raise ValueError(f"{path.name}: the svg declares no width and height")
    return max(1, round(width)), max(1, round(height))


def _dimension(value: str | None) -> float | None:
    match = LENGTH_PATTERN.match(value) if value else None
    return float(match.group(1)) if match else None


def _viewbox_size(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    parts = re.split(r"[\s,]+", value.strip())
    if len(parts) != VIEWBOX_PARTS:
        return None
    try:
        return float(parts[2]), float(parts[3])
    except ValueError:
        return None


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    return {"checks": [_doctor_demo()]}


def _doctor_demo() -> dict[str, Any]:
    """The person-installed binary is on PATH and at the manifest's minimum."""
    binary = shutil.which("demo")
    if binary is None:
        return _check("demo", False, "demo is not on PATH", HOST_HINT)
    try:
        version = _version(binary)
    except RuntimeError as exc:
        return _check("demo", False, str(exc), HOST_HINT)
    minimum = _semver_text(MIN_VERSION)
    if _semver(version) < MIN_VERSION:
        return _check(
            "demo",
            False,
            f"{binary}: demo {version}, need {minimum} or newer",
            HOST_HINT,
        )
    return _check("demo", True, f"{binary}: demo {version}", "")


def _check(name: str, ok: bool, detail: str, fix: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "fix": fix}


if __name__ == "__main__":
    runner.main()
