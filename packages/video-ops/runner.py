"""The video-ops package runner: transcode, mux-audio, and frame extraction.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` executes ``transcode``, ``mux-audio``, or
``frame`` with the static FFmpeg binary bundled by ``imageio-ffmpeg``;
``verify`` probes output streams or validates extracted images with Pillow;
``preview`` writes ``video`` or ``image`` preview JSON; ``doctor`` checks
the binary, encoders, Pillow import, and (at ``full`` depth) a synthetic
MP4-to-PNG roundtrip.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import graph
from facet_runner_sdk import Request, Runner

runner = Runner()

DEFAULT_CRF = 24
DEFAULT_AUDIO_BITRATE_KBPS = 128
DEFAULT_AT_S = 0.0
DEFAULT_FPS = 24
DEFAULT_SEED = 0
SUMMARY_MAX = 160
STDERR_TAIL_CHARS = 2000
FFMPEG_FLAGS = ("-nostdin", "-hide_banner", "-y")
REQUIRED_ENCODERS = ("aac", "libx264")
MIME = {
    "mp4": "video/mp4",
    "png": "image/png",
    "jpg": "image/jpeg",
}
_NAME_CLEAN_RE = re.compile(r"[^a-z0-9-]+")


def _exe() -> str:
    """Return the bundled static FFmpeg binary path from imageio-ffmpeg."""
    imageio_ffmpeg = importlib.import_module("imageio_ffmpeg")
    return str(imageio_ffmpeg.get_ffmpeg_exe())


def _pil_image() -> Any:
    """Lazily import PIL.Image so doctor can report broken environments."""
    return importlib.import_module("PIL.Image")


def _ffmpeg(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run one ffmpeg call; raise RuntimeError on non-zero exit."""
    done = subprocess.run(
        [_exe(), *FFMPEG_FLAGS, *args],
        capture_output=True,
        text=True,
        start_new_session=True,
        check=False,
    )
    if done.returncode != 0:
        tail = (done.stderr or "")[-STDERR_TAIL_CHARS:].strip()
        raise RuntimeError(f"ffmpeg exited {done.returncode}: {tail}")
    return done


def _probe_stderr(path: Path) -> dict[str, Any]:
    """Run ``ffmpeg -i <path>`` with check=False and parse stream metadata."""
    done = subprocess.run(
        [_exe(), *FFMPEG_FLAGS, "-i", str(path)],
        capture_output=True,
        text=True,
        start_new_session=True,
        check=False,
    )
    return graph.probe_stderr_parse(done.stderr or "")


@lru_cache(maxsize=1)
def _version_text() -> str:
    """Return ``ffmpeg -version`` output once per process."""
    return _ffmpeg(["-version"]).stdout


def _tool() -> dict[str, str]:
    """Return the tool identity record."""
    return {"name": "ffmpeg", "version": graph.version_line(_version_text())}


def _capability(req: Request) -> str:
    """Return the bare capability name (transcode, mux-audio, frame)."""
    return req.capability.rsplit(".", 1)[-1]


def _resolve_path(piece_dir: Path, raw: object) -> Path:
    """Resolve a piece path input relative to ``piece_dir`` when relative."""
    path = Path(str(raw))
    return path if path.is_absolute() else (piece_dir / path).resolve()


def _opt_float(params: Mapping[str, Any], key: str) -> float | None:
    value = params.get(key)
    return None if value is None else float(value)


def _opt_int(params: Mapping[str, Any], key: str) -> int | None:
    value = params.get(key)
    return None if value is None else int(value)


def _image_size(path: Path) -> tuple[int, int]:
    """Open an image with Pillow and return ``(width, height)``."""
    image_mod = _pil_image()
    with image_mod.open(path) as img:
        img.load()
        width, height = img.size
    return int(width), int(height)


def _preview_name(raw: str) -> str:
    """Normalize an asset name to match ``^[a-z0-9][a-z0-9-]*$``."""
    cleaned = _NAME_CLEAN_RE.sub("-", raw.lower()).strip("-")
    if not cleaned:
        return "asset"
    if not cleaned[0].isalnum():
        return f"a-{cleaned}"
    return cleaned


def _asset(
    name: str,
    file: str,
    kind: str,
    mime: str,
    properties: Mapping[str, Any],
    params: Mapping[str, Any],
    inputs: Sequence[Path],
) -> dict[str, Any]:
    """Build one asset record."""
    return {
        "file": file,
        "name": name,
        "kind": kind,
        "mime": mime,
        "properties": dict(properties),
        "params": dict(params),
        "seed": None,
        "inputs": [str(path) for path in inputs],
    }


def _run_transcode(
    params: Mapping[str, Any], out_dir: Path, piece_dir: Path
) -> list[dict[str, Any]]:
    """Transcode a video to H.264/AAC MP4 with faststart."""
    video = _resolve_path(piece_dir, params["video"])
    name = str(params["name"])
    opts = graph.TranscodeOptions(
        crf=int(params.get("crf", DEFAULT_CRF)),
        max_width=_opt_int(params, "max-width"),
        fps=_opt_int(params, "fps"),
        start_s=_opt_float(params, "start-s"),
        end_s=_opt_float(params, "end-s"),
        audio_bitrate_kbps=int(params.get("audio-bitrate-kbps", DEFAULT_AUDIO_BITRATE_KBPS)),
    )
    out = out_dir / f"{name}.mp4"
    _ffmpeg(graph.transcode_args(video, out, opts))
    props = _probe_stderr(out)
    resolved: dict[str, Any] = {
        "video": str(video),
        "name": name,
        "crf": opts.crf,
        "audio-bitrate-kbps": opts.audio_bitrate_kbps,
    }
    for key, val in (
        ("max-width", opts.max_width),
        ("fps", opts.fps),
        ("start-s", opts.start_s),
        ("end-s", opts.end_s),
    ):
        if val is not None:
            resolved[key] = val
    return [_asset(name, out.name, "video", MIME["mp4"], props, resolved, [video])]


def _run_mux_audio(
    params: Mapping[str, Any], out_dir: Path, piece_dir: Path
) -> list[dict[str, Any]]:
    """Replace a video's audio track without re-encoding video."""
    video = _resolve_path(piece_dir, params["video"])
    audio = _resolve_path(piece_dir, params["audio"])
    name = str(params["name"])
    kbps = int(params.get("audio-bitrate-kbps", DEFAULT_AUDIO_BITRATE_KBPS))
    out = out_dir / f"{name}.mp4"
    _ffmpeg(graph.mux_audio_args(video, audio, out, audio_bitrate_kbps=kbps))
    props = _probe_stderr(out)
    resolved = {
        "video": str(video),
        "audio": str(audio),
        "name": name,
        "audio-bitrate-kbps": kbps,
    }
    return [_asset(name, out.name, "video", MIME["mp4"], props, resolved, [video, audio])]


def _run_frame(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Extract a single still frame at ``at-s``."""
    video = _resolve_path(piece_dir, params["video"])
    name = str(params["name"])
    at_s = float(params.get("at-s", DEFAULT_AT_S))
    fmt = str(params.get("format", "png"))
    out = out_dir / f"{name}.{fmt}"
    _ffmpeg(graph.frame_args(video, out, at_s=at_s))
    width, height = _image_size(out)
    props = {"width": width, "height": height, "format": fmt}
    resolved = {
        "video": str(video),
        "name": name,
        "at-s": at_s,
        "format": fmt,
    }
    return [_asset(name, out.name, "image", MIME[fmt], props, resolved, [video])]


CAPABILITY_VERBS: dict[str, Callable[[Mapping[str, Any], Path, Path], list[dict[str, Any]]]] = {
    "transcode": _run_transcode,
    "mux-audio": _run_mux_audio,
    "frame": _run_frame,
}


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    """Execute the requested video-ops capability."""
    req.out_dir.mkdir(parents=True, exist_ok=True)
    verb = CAPABILITY_VERBS.get(_capability(req))
    if verb is None:
        known = ", ".join(sorted(CAPABILITY_VERBS))
        raise ValueError(f"{req.capability}: unknown capability (this runner has: {known})")
    return {"tool": _tool(), "assets": verb(dict(req.inputs), req.out_dir, req.piece_dir)}


def _verify_video(cap: str, path: Path) -> dict[str, Any]:
    """Verify non-zero size, duration > 0, dimensions > 0 (and audio on mux-audio)."""
    size = path.stat().st_size if path.is_file() else 0
    if size <= 0:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size},
            "thresholds": {},
            "verifier": f"ffmpeg {graph.version_id(_version_text())}",
        }
    try:
        props = _probe_stderr(path)
    except Exception as exc:  # catch-all: verify reports failure instead of crashing
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size, "error": str(exc)},
            "thresholds": {},
            "verifier": "ffmpeg",
        }
    dur = props.get("duration_s")
    width = props.get("width")
    height = props.get("height")
    audio_codec = props.get("audio_codec")
    stream_ok = bool(
        dur is not None
        and dur > 0
        and width is not None
        and width > 0
        and height is not None
        and height > 0
    )
    if cap == "mux-audio":
        stream_ok = stream_ok and bool(audio_codec)
    metrics = {
        "bytes": size,
        "duration_s": dur,
        "width": width,
        "height": height,
        "video_codec": props.get("video_codec"),
        "audio_codec": audio_codec,
    }
    return {
        "file": path.name,
        "passed": stream_ok,
        "metrics": metrics,
        "thresholds": {},
        "verifier": f"ffmpeg {graph.version_id(_version_text())}",
    }


def _verify_frame(path: Path) -> dict[str, Any]:
    """Verify an extracted image is readable by Pillow with positive dimensions."""
    size = path.stat().st_size if path.is_file() else 0
    if size <= 0:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size},
            "thresholds": {},
            "verifier": "pillow",
        }
    try:
        width, height = _image_size(path)
    except Exception as exc:  # catch-all: corrupt/non-image files fail verification cleanly
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size, "error": str(exc)},
            "thresholds": {},
            "verifier": "pillow",
        }
    return {
        "file": path.name,
        "passed": width > 0 and height > 0,
        "metrics": {"bytes": size, "width": width, "height": height},
        "thresholds": {},
        "verifier": "pillow",
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    """Verify every generated asset for the requested capability."""
    cap = _capability(req)
    if cap not in CAPABILITY_VERBS:
        raise ValueError(f"{req.capability}: no verifier for this capability")
    entries = [
        _verify_frame(path) if cap == "frame" else _verify_video(cap, path) for path in req.assets
    ]
    return {"assets": entries}


def _video_preview(cap: str, params: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """Build preview JSON matching ``schemas/preview/video.schema.json``."""
    props = _probe_stderr(path)
    width = int(props.get("width") or 1)
    height = int(props.get("height") or 1)
    dur = float(props.get("duration_s") or 0.0)
    fps = max(1, round(float(props.get("fps") or DEFAULT_FPS)))
    length = max(1, round(dur * fps))
    name = _preview_name(str(params.get("name") or path.stem))
    summary = f"{cap} · {width}x{height} · {dur:.1f}s @ {fps} fps"[:SUMMARY_MAX]
    return {
        "preview": 1,
        "kind": "video",
        "summary": summary,
        "name": name,
        "prompt": f"{cap} video {name}",
        "seed": DEFAULT_SEED,
        "width": width,
        "height": height,
        "length": length,
        "fps": fps,
    }


def _image_preview(params: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """Build preview JSON matching ``schemas/preview/image.schema.json``."""
    width, height = _image_size(path)
    name = _preview_name(str(params.get("name") or path.stem))
    summary = f"frame · {width}x{height}"[:SUMMARY_MAX]
    return {
        "preview": 1,
        "kind": "image",
        "summary": summary,
        "name": name,
        "prompt": f"frame {name}",
        "seed": DEFAULT_SEED,
        "width": width,
        "height": height,
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    """Write ``<asset>.preview.json`` for every asset."""
    req.out_dir.mkdir(parents=True, exist_ok=True)
    cap = _capability(req)
    params = dict(req.inputs)
    entries = []
    for path in req.assets:
        preview_name = f"{path.name}.preview.json"
        data = _image_preview(params, path) if cap == "frame" else _video_preview(cap, params, path)
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _verdict_check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    """Format one doctor check entry."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else "facet pull video-ops"}


def _doctor_binary() -> dict[str, Any]:
    """Check that the bundled ffmpeg binary runs ``-version``."""
    try:
        text = _version_text()
        build = graph.version_id(text)
    except Exception as exc:  # catch-all: doctor reports failure instead of crashing
        return _verdict_check("binary", False, f"the bundled ffmpeg does not run: {exc}")
    if not build:
        return _verdict_check("binary", False, "ffmpeg -version printed no version line")
    return _verdict_check("binary", True, f"ffmpeg {build} at {Path(_exe()).name}")


def _doctor_encoders() -> dict[str, Any]:
    """Check that libx264 and aac encoders are available in the bundled binary."""
    try:
        listed = graph.encoder_names(_ffmpeg(["-encoders"]).stdout)
    except Exception as exc:  # catch-all: report whatever went wrong
        return _verdict_check("encoders", False, f"ffmpeg -encoders failed: {exc}")
    missing = [codec for codec in REQUIRED_ENCODERS if codec not in listed]
    if missing:
        return _verdict_check("encoders", False, f"missing encoders: {', '.join(missing)}")
    return _verdict_check("encoders", True, ", ".join(REQUIRED_ENCODERS))


def _doctor_imports() -> dict[str, Any]:
    """Check that Pillow imports and report its version."""
    try:
        image_mod = _pil_image()
        pil_mod = importlib.import_module("PIL")
        version = getattr(pil_mod, "__version__", None)
        if version is None:
            version = importlib.metadata.version("pillow")
        _ = image_mod.new
    except Exception as exc:  # catch-all: report broken import
        return _verdict_check("imports", False, f"PIL.Image: {exc}")
    return _verdict_check("imports", True, f"PIL {version}")


def _doctor_roundtrip() -> dict[str, Any]:
    """Full depth: generate a 1 s synthetic lavfi MP4, probe it, and extract a PNG frame."""
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            mp4 = tmp / "roundtrip.mp4"
            _ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=duration=1:size=160x120:rate=25",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(mp4),
                ]
            )
            props = _probe_stderr(mp4)
            png = tmp / "frame.png"
            _ffmpeg(graph.frame_args(mp4, png, at_s=0.0))
            width, height = _image_size(png)
    except Exception as exc:  # catch-all: doctor reports failure cleanly
        elapsed = time.monotonic() - started
        return _verdict_check(
            "roundtrip", False, f"synthetic MP4-to-PNG roundtrip failed after {elapsed:.1f}s: {exc}"
        )
    elapsed = time.monotonic() - started
    ok = bool(
        props.get("duration_s")
        and props.get("width") == width
        and props.get("height") == height
        and width > 0
        and height > 0
    )
    return _verdict_check(
        "roundtrip",
        ok,
        f"1 s lavfi MP4 ({props.get('width')}x{props.get('height')}) -> "
        f"PNG ({width}x{height}) in {elapsed:.1f} s",
    )


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """Run quick or full environment checks."""
    checks = [_doctor_binary(), _doctor_encoders(), _doctor_imports()]
    if req.depth == "full":
        checks.append(_doctor_roundtrip())
    return {"checks": checks}


runner.main()
