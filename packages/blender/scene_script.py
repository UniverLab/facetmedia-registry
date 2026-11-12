"""Scripted scenes: the agent's own Blender script, facet's output settings.

``blender.scene`` renders one PNG from the script and ``blender.animation``
renders one MP4 from it, both from a factory-empty scene the script builds
itself: a ground plane, primitives, lights, a camera, keyframes — whatever
the recipes never foresaw. facet owns only the output: the resolution at
100 %, the engine and its samples, the seed, the exposure, and for an
animation the frame range, the frame rate and the FFmpeg MP4 block the tour
already uses (FFMPEG/MPEG4/H264). Everything else is the script's: the
world, the lights, the materials, the colour-management look and view
transform, the keyframes.

The script runs through ``runpy.run_path`` with its own directory as the
working directory and two globals: ``FACET_ASSETS``, the Poly Haven root
``blender.assets`` fills, and ``FACET_PIECE_DIR``, the script's directory.
It must set ``scene.camera``; a run without one fails loudly, and a still
whose luminance is flat fails as a uniform image (the camera's framing or
the lights are wrong). Paths travel through the host conversion the other
capabilities use, so a Windows host Blender opens them.

This module is imported by the runner, so it never imports the runner back:
inside Blender that module is ``__main__`` and importing it would execute
the entry twice (``producto.py`` says the same about itself).
"""

from __future__ import annotations

import hashlib
import json
import math
import ntpath
import os
import posixpath
import runpy
import traceback
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mp4

#: The two capabilities this module serves, each with the kind it writes.
CAPABILITIES = {"blender.scene": "image", "blender.animation": "video"}
#: A still whose luminance varies less than this is a uniform image.
UNIFORM_STDDEV = 0.002
#: The guard samples at most this many pixels, on a grid over the frame.
SAMPLE_PIXELS = 4096
#: The Rec. 709 luminance weights of one RGB triple.
LUMINANCE = (0.2126, 0.7152, 0.0722)
#: The preview's one-line summary cap, from the image schema.
SUMMARY_MAX = 160


@dataclass(frozen=True)
class Host:
    """The runner's helpers this module borrows instead of reimplementing."""

    path: Callable[[str], str]
    cycles: Callable[[Any, Any], None]
    png_size: Callable[[str], tuple[int, int]]
    polyhaven: Callable[[Any], Any]


@dataclass(frozen=True)
class Plan:
    """One run's owned output: the script, the name and every override."""

    name: str
    script: str
    width: int
    height: int
    engine: str
    samples: int
    exposure: float
    seed: int
    frames: int
    fps: int
    kind: str


def plan(kind: str, params: dict[str, Any]) -> Plan:
    """The piece's scripted render: its script and facet's output settings."""
    engine = str(params.get("engine") or ("cycles" if kind == "image" else "eevee"))
    samples = params.get("samples")
    if samples is None:
        samples = 128 if engine == "cycles" else 64
    return Plan(
        name=str(params["name"]),
        script=str(params["script"]),
        width=int(params.get("width", 1920)),
        height=int(params.get("height", 1080)),
        engine=engine,
        samples=int(samples),
        exposure=float(params.get("exposure", 0.0)),
        seed=int(params.get("seed", 0)),
        frames=int(params.get("frames", 120)),
        fps=int(params.get("fps", 24)),
        kind=kind,
    )


def verbs(capability: str, host: Host) -> dict[str, Any]:
    """The verb table of the scripted capability the request names."""
    kind = CAPABILITIES[capability]

    def run(bpy: Any, request: dict[str, Any]) -> dict[str, Any]:
        return _run(bpy, request, kind, host)

    def verify(bpy: Any, request: dict[str, Any]) -> dict[str, Any]:
        return _verify(bpy, request, kind, host)

    def preview(bpy: Any, request: dict[str, Any]) -> dict[str, Any]:
        return _preview(bpy, request, kind, host)

    def doctor(bpy: Any, request: dict[str, Any]) -> dict[str, Any]:
        return _doctor(bpy, request)

    return {"run": run, "verify": verify, "preview": preview, "doctor": doctor}


def _run(bpy: Any, request: dict[str, Any], kind: str, host: Host) -> dict[str, Any]:
    """Run the agent's script, apply facet's output settings and render."""
    params = dict(request.get("inputs") or {})
    drawing = plan(kind, params)
    script = _resolve(drawing.script, str(request.get("piece_dir") or ""))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _execute(host, script)
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("no camera: the script must set scene.camera")
    suffix = ".png" if kind == "image" else ".mp4"
    destination = f"{str(request['out_dir']).rstrip('/')}/{drawing.name}{suffix}"
    _settings(bpy, scene, drawing, host.path(destination), host)
    if kind == "image":
        bpy.ops.render.render(write_still=True)
        mean, stddev = _guard(bpy, destination, host)
    else:
        bpy.ops.render.render(animation=True)
        mean, stddev = None, None
    digest = hashlib.sha256(Path(host.path(script)).read_bytes()).hexdigest()
    return {
        "tool": {"name": "blender", "version": _version(bpy)},
        "assets": [_asset(drawing, digest, mean, stddev, params)],
    }


def _resolve(script: str, piece_dir: str) -> str:
    """The script's path: absolute as given, else relative to the piece.

    Inside the Windows build ``os.path.isabs`` reads a WSL path such as
    ``/home/x`` as relative, so a POSIX root counts as absolute too.
    """
    if posixpath.isabs(script) or ntpath.isabs(script) or not piece_dir:
        return script
    return f"{piece_dir.rstrip('/')}/{script}"


def _execute(host: Host, script: str) -> None:
    """Run the script with its own directory as cwd and the facet globals."""
    target = host.path(script)
    folder = os.path.dirname(target) or "."
    base = posixpath.basename(script.replace("\\", "/"))
    previous = os.getcwd()
    os.chdir(folder)
    try:
        runpy.run_path(
            target,
            init_globals={
                "FACET_ASSETS": str(host.polyhaven()),
                "FACET_PIECE_DIR": folder,
            },
        )
    except Exception as exc:
        lines = traceback.format_exception(exc)
        tail = "".join(lines[-2:]).strip()
        raise RuntimeError(f"script {base} failed: {type(exc).__name__}: {exc}\n{tail}") from exc
    finally:
        os.chdir(previous)


def _settings(bpy: Any, scene: Any, drawing: Plan, destination: str, host: Host) -> None:
    """facet's output settings over whatever the script set: they always win."""
    scene.render.resolution_x = drawing.width
    scene.render.resolution_y = drawing.height
    with suppress(TypeError, AttributeError):
        scene.render.resolution_percentage = 100
    if drawing.engine == "cycles":
        host.cycles(bpy, scene)
        scene.cycles.samples = drawing.samples
        scene.cycles.seed = drawing.seed
    else:
        scene.render.engine = "BLENDER_EEVEE"
        scene.eevee.taa_render_samples = drawing.samples
    scene.view_settings.exposure = drawing.exposure
    if drawing.kind == "video":
        scene.frame_start, scene.frame_end = 1, drawing.frames
        scene.render.fps = drawing.fps
        image = scene.render.image_settings
        image.media_type, image.file_format = "VIDEO", "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "HIGH"
        scene.render.use_file_extension = False
    scene.render.filepath = destination


def _guard(bpy: Any, destination: str, host: Host) -> tuple[float, float]:
    """The still's luminance mean and spread; a flat frame fails the run.

    The pixels are read as at most ``SAMPLE_PIXELS`` one-pixel slices on a
    stride over the frame, never as one whole-frame list: a 4K still is 67
    million floats and the guard needs 4 096 of them.
    """
    image = bpy.data.images.load(host.path(destination))
    try:
        width, height = image.size
        total = width * height
        stride = max(1, -(-total // SAMPLE_PIXELS))
        pixels = image.pixels
        sample = [pixels[index * 4 : index * 4 + 3] for index in range(0, total, stride)]
    finally:
        with suppress(Exception):
            bpy.data.images.remove(image)
    levels = [
        triple[0] * LUMINANCE[0] + triple[1] * LUMINANCE[1] + triple[2] * LUMINANCE[2]
        for triple in sample
    ]
    mean = sum(levels) / len(levels)
    stddev = math.sqrt(sum((level - mean) ** 2 for level in levels) / len(levels))
    if stddev < UNIFORM_STDDEV:
        raise RuntimeError(
            f"uniform image (luminance stddev {stddev:.6f}): "
            "check the camera's framing and the lights"
        )
    return mean, stddev


def _asset(
    drawing: Plan,
    digest: str,
    mean: float | None,
    stddev: float | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """One run's asset record: the clip, its format and the script it ran."""
    suffix = ".png" if drawing.kind == "image" else ".mp4"
    kind = "image" if drawing.kind == "image" else "video"
    mime = "image/png" if drawing.kind == "image" else "video/mp4"
    properties: dict[str, Any] = {
        "width": drawing.width,
        "height": drawing.height,
        "engine": drawing.engine,
        "samples": drawing.samples,
        "exposure": drawing.exposure,
        "seed": drawing.seed,
        "script_sha256": digest,
    }
    if drawing.kind == "image":
        properties["mean"] = mean
        properties["stddev"] = stddev
    else:
        properties["frames"] = drawing.frames
        properties["fps"] = drawing.fps
    return {
        "file": f"{drawing.name}{suffix}",
        "name": drawing.name,
        "kind": kind,
        "mime": mime,
        "properties": properties,
        "params": dict(params),
        "seed": drawing.seed,
        "inputs": [drawing.script],
    }


def _verify(bpy: Any, request: dict[str, Any], kind: str, host: Host) -> dict[str, Any]:
    """Measure each asset against the piece's own scripted recipe."""
    drawing = plan(kind, dict(request.get("inputs") or {}))
    paths = [str(item) for item in request.get("assets") or []]
    if kind == "image":
        thresholds: dict[str, Any] = {"width": drawing.width, "height": drawing.height}
        return {"assets": [_image_verdict(path, thresholds, host) for path in paths]}
    thresholds = {
        "width": drawing.width,
        "height": drawing.height,
        "frames": drawing.frames,
        "fps": drawing.fps,
    }
    return {"assets": [_clip_verdict(path, thresholds, host) for path in paths]}


def _image_verdict(path: str, thresholds: dict[str, Any], host: Host) -> dict[str, Any]:
    """One PNG's size against the piece's scripted recipe."""
    try:
        width, height = host.png_size(path)
    except (OSError, ValueError) as exc:
        return _verdict(path, False, {"error": str(exc)}, thresholds, "png")
    passed = width == thresholds["width"] and height == thresholds["height"]
    return _verdict(path, passed, {"width": width, "height": height}, thresholds, "png")


def _clip_verdict(path: str, thresholds: dict[str, Any], host: Host) -> dict[str, Any]:
    """One MP4's probe against the piece's scripted recipe."""
    try:
        metrics = mp4.probe(host.path(path))
    except (OSError, ValueError) as exc:
        return _verdict(path, False, {"error": str(exc)}, thresholds, "mp4")
    measured: dict[str, Any] = dict(metrics)
    passed = all(measured[key] == thresholds[key] for key in thresholds)
    return _verdict(path, passed, measured, thresholds, "mp4")


def _verdict(
    path: str,
    passed: bool,
    metrics: dict[str, Any],
    thresholds: dict[str, Any],
    verifier: str,
) -> dict[str, Any]:
    return {
        "file": posixpath.basename(path),
        "passed": passed,
        "metrics": metrics,
        "thresholds": thresholds,
        "verifier": verifier,
    }


def _preview(bpy: Any, request: dict[str, Any], kind: str, host: Host) -> dict[str, Any]:
    """Write the image or video kind's preview file beside each asset."""
    drawing = plan(kind, dict(request.get("inputs") or {}))
    base = posixpath.basename(drawing.script.replace("\\", "/"))
    entries: list[dict[str, Any]] = []
    for item in request.get("assets") or []:
        path = str(item)
        file_name = posixpath.basename(path)
        if kind == "image":
            data = _still_preview(drawing, base, path, host)
        else:
            data = _clip_preview(drawing, base, path, host)
        preview_name = f"{file_name}.preview.json"
        preview_path = host.path(f"{posixpath.dirname(path)}/{preview_name}")
        with open(preview_path, "w", encoding="utf-8") as handle:
            handle.write(_dump(data))
        entries.append({"file": file_name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _dump(data: dict[str, Any]) -> str:
    """One preview file's text: sorted keys, like the other capabilities."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n"


def _still_preview(drawing: Plan, base: str, path: str, host: Host) -> dict[str, Any]:
    """The image kind's preview: the asset, its size, its engine, its script."""
    width, height = host.png_size(path)
    return {
        "preview": 1,
        "kind": "image",
        "summary": f"{drawing.name} · {width}×{height} · {drawing.engine} · {base}"[:SUMMARY_MAX],
        "name": drawing.name,
        "prompt": f"{drawing.name} · scripted scene · {drawing.engine} · {base}",
        "seed": drawing.seed,
        "width": width,
        "height": height,
    }


def _clip_preview(drawing: Plan, base: str, path: str, host: Host) -> dict[str, Any]:
    """The video kind's preview: the clip, its probe and the script it ran."""
    probe = mp4.probe(host.path(path))
    summary = (
        f"{drawing.name} · {probe['width']}×{probe['height']} · "
        f"{probe['frames']}f @ {probe['fps']}fps · {drawing.engine} · {base}"
    )
    return {
        "preview": 1,
        "kind": "video",
        "summary": summary[:SUMMARY_MAX],
        "name": drawing.name,
        "prompt": f"{drawing.name} · scripted animation · {drawing.engine} · {base}",
        "seed": drawing.seed,
        "width": probe["width"],
        "height": probe["height"],
        "length": probe["frames"],
        "fps": probe["fps"],
    }


def _doctor(bpy: Any, request: dict[str, Any]) -> dict[str, Any]:
    """The Blender-side module a scripted render needs: bpy itself."""
    try:
        detail = f"bpy {bpy.app.version_string} imports"
    except AttributeError as exc:
        return {"checks": [{"name": "bpy", "ok": False, "detail": str(exc), "fix": ""}]}
    return {"checks": [{"name": "bpy", "ok": True, "detail": detail, "fix": ""}]}


def _version(bpy: Any) -> str:
    try:
        return str(bpy.app.version_string)
    except AttributeError:
        return "unknown"
