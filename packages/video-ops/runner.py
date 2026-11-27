"""The video-ops package runner: transcode, mux-audio, frame extraction, concat,
subtitle burning, and color grading.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` executes ``transcode``, ``mux-audio``,
``frame``, ``concat``, ``burn-subs``, or ``grade`` with the static FFmpeg
binary bundled by ``imageio-ffmpeg``;
``verify`` probes output streams or validates extracted images with Pillow;
``preview`` writes ``video`` or ``image`` preview JSON; ``doctor`` checks
the binary, encoders, Pillow import, and (at ``full`` depth) a synthetic
MP4-to-PNG roundtrip.
"""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fx_jumpcut
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
CONCAT_DURATION_TOL_S = 0.35
SOURCE_DURATION_TOL_S = 0.2
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


def _run_concat(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Join clips with xfade/acrossfade transitions or cut concat."""
    clips_in = params["clip"]
    if not isinstance(clips_in, list):
        raise ValueError("concat: clip must be an array")
    clip_paths = [_resolve_path(piece_dir, str(item["video"])) for item in clips_in]
    name = str(params["name"])
    transition = str(params.get("transition", "fade"))
    transition_s = float(params.get("transition-s", 0.5))
    fps = int(params.get("fps", 30))
    crf = int(params.get("crf", 23))

    probes = [_probe_stderr(path) for path in clip_paths]
    durations: list[float] = []
    for index, probe in enumerate(probes):
        dur = probe.get("duration_s")
        if dur is None or float(dur) <= 0:
            raise ValueError(f"concat: clip {index} has no readable duration: {clip_paths[index]}")
        durations.append(float(dur))

    target_width = _opt_int(params, "width")
    target_height = _opt_int(params, "height")
    first_w = probes[0].get("width")
    first_h = probes[0].get("height")
    if target_width is None:
        if first_w is None or int(first_w) <= 0:
            raise ValueError("concat: first clip has no readable width")
        target_width = int(first_w)
    if target_height is None:
        if first_h is None or int(first_h) <= 0:
            raise ValueError("concat: first clip has no readable height")
        target_height = int(first_h)

    include_audio = all(bool(p.get("audio_codec")) for p in probes)
    out = out_dir / f"{name}.mp4"
    _ffmpeg(
        graph.concat_args(
            clip_paths,
            out,
            durations,
            target_width,
            target_height,
            transition=transition,
            transition_s=transition_s,
            fps=fps,
            crf=crf,
            include_audio=include_audio,
        )
    )
    props = _probe_stderr(out)
    resolved: dict[str, Any] = {
        "clip": [{"video": str(p)} for p in clip_paths],
        "name": name,
        "transition": transition,
        "transition-s": transition_s,
        "width": target_width,
        "height": target_height,
        "fps": fps,
        "crf": crf,
    }
    return [_asset(name, out.name, "video", MIME["mp4"], props, resolved, clip_paths)]


def _run_burn_subs(
    params: Mapping[str, Any], out_dir: Path, piece_dir: Path
) -> list[dict[str, Any]]:
    """Burn SRT/VTT subtitles into a video with libass."""
    video = _resolve_path(piece_dir, params["video"])
    subtitles = _resolve_path(piece_dir, params["subtitles"])
    name = str(params["name"])
    font_size = int(params.get("font-size", 22))
    margin_v = int(params.get("margin-v", 36))
    crf = int(params.get("crf", 23))
    probe = _probe_stderr(video)
    has_audio = bool(probe.get("audio_codec"))
    out = out_dir / f"{name}.mp4"
    _ffmpeg(
        graph.burn_subs_args(
            video,
            subtitles,
            out,
            font_size=font_size,
            margin_v=margin_v,
            crf=crf,
            has_audio=has_audio,
        )
    )
    props = _probe_stderr(out)
    resolved = {
        "video": str(video),
        "subtitles": str(subtitles),
        "name": name,
        "font-size": font_size,
        "margin-v": margin_v,
        "crf": crf,
    }
    return [_asset(name, out.name, "video", MIME["mp4"], props, resolved, [video, subtitles])]


def _run_grade(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Apply eq color grading and optional fades to a video."""
    video = _resolve_path(piece_dir, params["video"])
    name = str(params["name"])
    brightness = float(params.get("brightness", 0.0))
    contrast = float(params.get("contrast", 1.0))
    saturation = float(params.get("saturation", 1.0))
    gamma = float(params.get("gamma", 1.0))
    fade_in_s = float(params.get("fade-in-s", 0.0))
    fade_out_s = float(params.get("fade-out-s", 0.0))
    crf = int(params.get("crf", 23))
    probe = _probe_stderr(video)
    duration_s = float(probe.get("duration_s") or 0.0)
    has_audio = bool(probe.get("audio_codec"))
    out = out_dir / f"{name}.mp4"
    _ffmpeg(
        graph.grade_args(
            video,
            out,
            duration_s,
            brightness=brightness,
            contrast=contrast,
            saturation=saturation,
            gamma=gamma,
            fade_in_s=fade_in_s,
            fade_out_s=fade_out_s,
            crf=crf,
            has_audio=has_audio,
        )
    )
    props = _probe_stderr(out)
    resolved = {
        "video": str(video),
        "name": name,
        "brightness": brightness,
        "contrast": contrast,
        "saturation": saturation,
        "gamma": gamma,
        "fade-in-s": fade_in_s,
        "fade-out-s": fade_out_s,
        "crf": crf,
    }
    return [_asset(name, out.name, "video", MIME["mp4"], props, resolved, [video])]


IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})


def _run_overlay(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Composite a PNG, alpha MOV, or PiP clip over base footage."""
    base = _resolve_path(piece_dir, params["base"])
    overlay = _resolve_path(piece_dir, params["overlay"])
    name = str(params["name"])
    probe = _probe_stderr(base)
    dims = (int(probe.get("width") or 0), int(probe.get("height") or 0))
    if min(dims) <= 0:
        raise ValueError(f"overlay: base has no readable dimensions: {base}")
    out = out_dir / f"{name}.mp4"
    built = graph.overlay_args(
        base,
        overlay,
        out,
        *dims,
        has_audio=bool(probe.get("audio_codec")),
        position=str(params.get("position", "fullscreen")),
        scale_width=_opt_int(params, "scale-width"),
        margin_px=int(params.get("margin-px", 24)),
        start_s=float(params.get("start-s", 0.0)),
        end_s=_opt_float(params, "end-s"),
        crf=int(params.get("crf", 23)),
    )
    if overlay.suffix.lower() in IMAGE_SUFFIXES:
        # Still images emit one frame: loop the logo and stop at the base end.
        built[2:2] = ["-loop", "1"]
        built.insert(len(built) - 1, "-shortest")
    _ffmpeg(built)
    props = _probe_stderr(out)
    resolved = {**params, "base": str(base), "overlay": str(overlay)}
    return [_asset(name, out.name, "video", MIME["mp4"], props, resolved, [base, overlay])]


def _run_speed(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Change playback speed with synchronized video and audio."""
    video, name = _resolve_path(piece_dir, params["video"]), str(params["name"])
    factor = float(params["factor"])
    crf = int(params.get("crf", 23))
    keep_audio = bool(params.get("keep-audio", True))
    has_audio = bool(_probe_stderr(video).get("audio_codec"))
    out = out_dir / f"{name}.mp4"
    args = graph.speed_args(video, out, factor, keep_audio=keep_audio, has_audio=has_audio, crf=crf)
    _ffmpeg(args)
    resolved = {**params, "video": str(video), "factor": factor}
    return [_asset(name, out.name, "video", MIME["mp4"], _probe_stderr(out), resolved, [video])]


def _run_reframe(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Reframe footage to a vertical or square canvas."""
    video, name = _resolve_path(piece_dir, params["video"]), str(params["name"])
    aspect = str(params["aspect"])
    mode = str(params.get("mode", "crop"))
    width = int(params.get("width", 1080))
    crf = int(params.get("crf", 23))
    has_audio = bool(_probe_stderr(video).get("audio_codec"))
    out = out_dir / f"{name}.mp4"
    _ffmpeg(
        graph.reframe_args(video, out, aspect, mode=mode, width=width, crf=crf, has_audio=has_audio)
    )
    resolved = {**params, "video": str(video), "aspect": aspect, "mode": mode, "width": width}
    return [_asset(name, out.name, "video", MIME["mp4"], _probe_stderr(out), resolved, [video])]


def _run_jumpcut(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Remove silence segments and write ``<name>.mp4`` + ``<name>.cuts.json``."""
    return fx_jumpcut.run_jumpcut(params, out_dir, piece_dir, _ops())


def _run_fx(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Apply deterministic stylized visual finishes."""
    return fx_jumpcut.run_fx(params, out_dir, piece_dir, _ops())


CAPABILITY_VERBS: dict[str, Callable[[Mapping[str, Any], Path, Path], list[dict[str, Any]]]] = {
    "transcode": _run_transcode,
    "mux-audio": _run_mux_audio,
    "frame": _run_frame,
    "concat": _run_concat,
    "burn-subs": _run_burn_subs,
    "grade": _run_grade,
    "overlay": _run_overlay,
    "speed": _run_speed,
    "reframe": _run_reframe,
    "jumpcut": _run_jumpcut,
    "fx": _run_fx,
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


def _video_metrics(path: Path) -> tuple[int, dict[str, Any] | None, str | None]:
    size = path.stat().st_size if path.is_file() else 0
    if size <= 0:
        return size, None, "empty output"
    try:
        return size, _probe_stderr(path), None
    except Exception as exc:  # catch-all: verify reports failure instead of crashing
        return size, None, str(exc)


def _verify_concat(path: Path, params: Mapping[str, Any], piece_dir: Path) -> dict[str, Any]:
    """Verify concat output duration and dimensions."""
    verifier = f"ffmpeg {graph.version_id(_version_text())}"
    size, props, err = _video_metrics(path)
    if props is None:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size, "error": err},
            "thresholds": {},
            "verifier": verifier,
        }
    try:
        clips_in = params["clip"]
        clip_paths = [_resolve_path(piece_dir, str(item["video"])) for item in clips_in]
        durations = []
        for clip_path in clip_paths:
            probe = _probe_stderr(clip_path)
            dur = probe.get("duration_s")
            if dur is None:
                raise ValueError(f"missing duration for {clip_path}")
            durations.append(float(dur))
        transition = str(params.get("transition", "fade"))
        transition_s = float(params.get("transition-s", 0.5))
        if transition == "cut":
            expected = sum(durations)
        else:
            expected = sum(durations) - (len(durations) - 1) * transition_s
        target_width = _opt_int(params, "width")
        target_height = _opt_int(params, "height")
        if target_width is None:
            target_width = int(_probe_stderr(clip_paths[0]).get("width") or 0)
        if target_height is None:
            target_height = int(_probe_stderr(clip_paths[0]).get("height") or 0)
    except Exception as exc:  # catch-all: bad inputs fail verification cleanly
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size, "error": str(exc)},
            "thresholds": {},
            "verifier": verifier,
        }

    out_dur = float(props.get("duration_s") or 0.0)
    out_w = int(props.get("width") or 0)
    out_h = int(props.get("height") or 0)
    passed = bool(
        size > 0
        and abs(out_dur - expected) <= CONCAT_DURATION_TOL_S
        and out_w == target_width
        and out_h == target_height
    )
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {
            "bytes": size,
            "duration_s": props.get("duration_s"),
            "expected_duration_s": round(expected, 3),
            "width": props.get("width"),
            "height": props.get("height"),
            "target_width": target_width,
            "target_height": target_height,
        },
        "thresholds": {"duration_tolerance_s": CONCAT_DURATION_TOL_S},
        "verifier": verifier,
    }


def _verify_burn_subs_or_grade(
    path: Path,
    params: Mapping[str, Any],
    piece_dir: Path,
    video_key: str = "video",
    duration_divisor: float = 1.0,
    dims: tuple[int, int] | None = None,
    tol: float = SOURCE_DURATION_TOL_S,
) -> dict[str, Any]:
    """Verify duration/dimensions, with optional re-key, scaling, or reframe canvas."""
    verifier = f"ffmpeg {graph.version_id(_version_text())}"
    size, props, err = _video_metrics(path)
    if props is None:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size, "error": err},
            "thresholds": {},
            "verifier": verifier,
        }
    try:
        source = _resolve_path(piece_dir, params[video_key])
        src = _probe_stderr(source)
        src_dur = float(src.get("duration_s") or 0.0) / duration_divisor
        dims = dims or (int(src.get("width") or 0), int(src.get("height") or 0))
    except Exception as exc:  # catch-all
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size, "error": str(exc)},
            "thresholds": {},
            "verifier": verifier,
        }
    out_dur = float(props.get("duration_s") or 0.0)
    out_w = int(props.get("width") or 0)
    out_h = int(props.get("height") or 0)
    passed = bool(
        size > 0
        and abs(out_dur - src_dur) <= tol
        and out_w == dims[0]
        and out_h == dims[1]
        and dims[0] > 0
        and dims[1] > 0
    )
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {
            "bytes": size,
            "duration_s": props.get("duration_s"),
            "source_duration_s": src.get("duration_s"),
            "width": props.get("width"),
            "height": props.get("height"),
            "source_width": dims[0],
            "source_height": dims[1],
        },
        "thresholds": {"duration_tolerance_s": tol},
        "verifier": verifier,
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
    params = dict(req.inputs)
    entries = []
    for path in req.assets:
        if cap == "frame":
            entries.append(_verify_frame(path))
        elif cap == "concat":
            entries.append(_verify_concat(path, params, req.piece_dir))
        elif cap in {"burn-subs", "grade"}:
            entries.append(_verify_burn_subs_or_grade(path, params, req.piece_dir))
        elif cap == "overlay":
            entries.append(
                _verify_burn_subs_or_grade(path, params, req.piece_dir, video_key="base", tol=0.25)
            )
        elif cap == "speed":
            entries.append(
                _verify_burn_subs_or_grade(
                    path, params, req.piece_dir, duration_divisor=float(params["factor"]), tol=0.25
                )
            )
        elif cap == "reframe":
            dims = graph._reframe_dims(str(params["aspect"]), int(params.get("width", 1080)))
            entries.append(
                _verify_burn_subs_or_grade(path, params, req.piece_dir, dims=dims, tol=0.25)
            )
        elif cap == "jumpcut":
            entries.append(fx_jumpcut.verify_jumpcut(path, _ops()))
        elif cap == "fx":
            entries.append(_verify_burn_subs_or_grade(path, params, req.piece_dir, tol=0.25))
        else:
            entries.append(_verify_video(cap, path))
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


def _ops() -> fx_jumpcut.RunnerOps:
    """Build the callback bundle passed to ``fx_jumpcut``."""
    return fx_jumpcut.RunnerOps(
        resolve_path=_resolve_path,
        probe_stderr=_probe_stderr,
        ffmpeg=_ffmpeg,
        asset=_asset,
        video_metrics=_video_metrics,
        version_text=_version_text,
        exe=_exe,
        image_size=_image_size,
        pil_image=_pil_image,
    )


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """Run quick or full environment checks."""
    return {"checks": fx_jumpcut.doctor_checks(req.depth, _ops())}


runner.main()
