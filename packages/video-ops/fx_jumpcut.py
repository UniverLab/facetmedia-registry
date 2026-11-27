"""Jumpcut silence removal, stylized FX, and doctor helpers for video-ops."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import graph

REQUIRED_ENCODERS = ("aac", "libx264")
JUMPCUT_SOURCE_TOL_S = 0.15
JUMPCUT_SUM_TOL_S = 0.35


@dataclass(frozen=True)
class RunnerOps:
    """Callbacks injected from ``runner.py`` to avoid circular imports."""

    resolve_path: Callable[[Path, object], Path]
    probe_stderr: Callable[[Path], dict[str, Any]]
    ffmpeg: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
    asset: Callable[
        [str, str, str, str, Mapping[str, Any], Mapping[str, Any], Sequence[Path]],
        dict[str, Any],
    ]
    video_metrics: Callable[[Path], tuple[int, dict[str, Any] | None, str | None]]
    version_text: Callable[[], str]
    exe: Callable[[], str]
    image_size: Callable[[Path], tuple[int, int]]
    pil_image: Callable[[], Any]


def run_jumpcut(
    params: Mapping[str, Any], out_dir: Path, piece_dir: Path, ops: RunnerOps
) -> list[dict[str, Any]]:
    """Detect silence, cut dead air, and emit ``<name>.mp4`` + ``<name>.cuts.json``."""
    video = ops.resolve_path(piece_dir, params["video"])
    name = str(params["name"])
    threshold_db = float(params.get("threshold-db", -35.0))
    min_silence_s = float(params.get("min-silence-s", 0.6))
    margin_s = float(params.get("margin-s", 0.12))
    crf = int(params.get("crf", 23))

    src_probe = ops.probe_stderr(video)
    source_duration_s = float(src_probe.get("duration_s") or 0.0)
    if source_duration_s <= 0:
        raise ValueError(f"jumpcut: video has no readable duration: {video}")
    has_audio = bool(src_probe.get("audio_codec"))

    if has_audio:
        detect_done = ops.ffmpeg(graph.silence_detect_args(video, threshold_db, min_silence_s))
        silences = graph.parse_silences(detect_done.stderr or "", duration_s=source_duration_s)
    else:
        silences = []
    segments = graph.keep_segments(source_duration_s, silences, margin_s)

    out = out_dir / f"{name}.mp4"
    ops.ffmpeg(graph.jumpcut_args(video, out, segments, has_audio=has_audio, crf=crf))
    props = ops.probe_stderr(out)

    output_duration_s = round(sum(end - start for start, end in segments), 3)
    src_dur_r = round(source_duration_s, 3)
    removed_s = round(max(0.0, src_dur_r - output_duration_s), 3)
    cuts_name = f"{name}.cuts.json"
    cuts_data = {
        "source_duration_s": src_dur_r,
        "output_duration_s": output_duration_s,
        "removed_s": removed_s,
        "segments": [{"start_s": round(s, 3), "end_s": round(e, 3)} for s, e in segments],
    }
    (out_dir / cuts_name).write_text(
        json.dumps(cuts_data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    props["cuts_file"] = cuts_name
    resolved = {
        **params,
        "video": str(video),
        "threshold-db": threshold_db,
        "min-silence-s": min_silence_s,
        "margin-s": margin_s,
        "crf": crf,
    }
    return [ops.asset(name, out.name, "video", "video/mp4", props, resolved, [video])]


def run_fx(
    params: Mapping[str, Any], out_dir: Path, piece_dir: Path, ops: RunnerOps
) -> list[dict[str, Any]]:
    """Apply deterministic stylized visual finishes to a video."""
    video = ops.resolve_path(piece_dir, params["video"])
    name = str(params["name"])
    preset = str(params.get("preset", "none"))
    seed = int(params.get("seed", 42))
    crf = int(params.get("crf", 23))
    overrides = {
        key: params.get(key)
        for key in ("grain", "chroma-px", "vignette", "halation", "scanlines", "glitch")
    }
    fx_vals = graph.resolve_fx(preset, overrides)
    has_audio = bool(ops.probe_stderr(video).get("audio_codec"))
    opts = graph.FxOptions(
        grain=float(fx_vals["grain"]),
        chroma_px=int(fx_vals["chroma_px"]),
        vignette=float(fx_vals["vignette"]),
        halation=float(fx_vals["halation"]),
        scanlines=bool(fx_vals["scanlines"]),
        glitch=float(fx_vals["glitch"]),
        seed=seed,
        has_audio=has_audio,
        crf=crf,
    )
    out = out_dir / f"{name}.mp4"
    ops.ffmpeg(graph.fx_args(video, out, options=opts))
    props = ops.probe_stderr(out)
    resolved = {
        **params,
        "video": str(video),
        "preset": preset,
        "seed": seed,
        "crf": crf,
        "grain": opts.grain,
        "chroma-px": opts.chroma_px,
        "vignette": opts.vignette,
        "halation": opts.halation,
        "scanlines": opts.scanlines,
        "glitch": opts.glitch,
    }
    return [ops.asset(name, out.name, "video", "video/mp4", props, resolved, [video])]


def _segments_monotonic(segments: object) -> tuple[bool, float]:
    """Check that EDL segments are non-empty, monotonic, and return their duration sum."""
    if not isinstance(segments, list) or not segments:
        return False, 0.0
    total = 0.0
    prev_end = 0.0
    for item in segments:
        if not isinstance(item, Mapping):
            return False, 0.0
        start_s = float(item["start_s"])
        end_s = float(item["end_s"])
        if start_s < 0 or end_s <= start_s or start_s < prev_end:
            return False, 0.0
        total += end_s - start_s
        prev_end = end_s
    return True, total


def verify_jumpcut(path: Path, ops: RunnerOps) -> dict[str, Any]:
    """Verify ``<name>.mp4`` and its ``<name>.cuts.json`` sidecar EDL."""
    verifier = f"ffmpeg {graph.version_id(ops.version_text())}"
    size, props, err = ops.video_metrics(path)
    if props is None:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size, "error": err},
            "thresholds": {},
            "verifier": verifier,
        }
    cuts_path = path.with_suffix(".cuts.json")
    try:
        cuts = json.loads(cuts_path.read_text(encoding="utf-8"))
        monotonic, seg_sum = _segments_monotonic(cuts.get("segments"))
        src_dur = float(cuts["source_duration_s"])
        out_dur_edl = float(cuts["output_duration_s"])
    except Exception as exc:  # catch-all: corrupt/missing EDL fails verification cleanly
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size, "error": str(exc)},
            "thresholds": {},
            "verifier": verifier,
        }

    probed_dur = float(props.get("duration_s") or 0.0)
    passed = bool(
        size > 0
        and monotonic
        and out_dur_edl <= src_dur + JUMPCUT_SOURCE_TOL_S
        and abs(probed_dur - seg_sum) <= JUMPCUT_SUM_TOL_S
    )
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {
            "bytes": size,
            "duration_s": props.get("duration_s"),
            "source_duration_s": src_dur,
            "output_duration_s": out_dur_edl,
            "segments_sum_s": round(seg_sum, 3),
            "segment_count": len(cuts["segments"]),
        },
        "thresholds": {
            "source_tolerance_s": JUMPCUT_SOURCE_TOL_S,
            "sum_tolerance_s": JUMPCUT_SUM_TOL_S,
        },
        "verifier": verifier,
    }


def _verdict_check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    """Format one doctor check entry."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else "facet pull video-ops"}


def _doctor_binary(ops: RunnerOps) -> dict[str, Any]:
    """Check that the bundled ffmpeg binary runs ``-version``."""
    try:
        text = ops.version_text()
        build = graph.version_id(text)
    except Exception as exc:  # catch-all: doctor reports failure instead of crashing
        return _verdict_check("binary", False, f"the bundled ffmpeg does not run: {exc}")
    if not build:
        return _verdict_check("binary", False, "ffmpeg -version printed no version line")
    return _verdict_check("binary", True, f"ffmpeg {build} at {Path(ops.exe()).name}")


def _doctor_encoders(ops: RunnerOps) -> dict[str, Any]:
    """Check that libx264 and aac encoders are available in the bundled binary."""
    try:
        listed = graph.encoder_names(ops.ffmpeg(["-encoders"]).stdout)
    except Exception as exc:  # catch-all: report whatever went wrong
        return _verdict_check("encoders", False, f"ffmpeg -encoders failed: {exc}")
    missing = [codec for codec in REQUIRED_ENCODERS if codec not in listed]
    if missing:
        return _verdict_check("encoders", False, f"missing encoders: {', '.join(missing)}")
    return _verdict_check("encoders", True, ", ".join(REQUIRED_ENCODERS))


def _doctor_imports(ops: RunnerOps) -> dict[str, Any]:
    """Check that Pillow imports and report its version."""
    try:
        image_mod = ops.pil_image()
        pil_mod = importlib.import_module("PIL")
        version = getattr(pil_mod, "__version__", None)
        if version is None:
            version = importlib.metadata.version("pillow")
        _ = image_mod.new
    except Exception as exc:  # catch-all: report broken import
        return _verdict_check("imports", False, f"PIL.Image: {exc}")
    return _verdict_check("imports", True, f"PIL {version}")


def _doctor_roundtrip(ops: RunnerOps) -> dict[str, Any]:
    """Full depth: generate a 1 s synthetic lavfi MP4, probe it, and extract a PNG frame."""
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            mp4 = tmp / "roundtrip.mp4"
            ops.ffmpeg(
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
            props = ops.probe_stderr(mp4)
            png = tmp / "frame.png"
            ops.ffmpeg(graph.frame_args(mp4, png, at_s=0.0))
            width, height = ops.image_size(png)
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


def doctor_checks(depth: str, ops: RunnerOps) -> list[dict[str, Any]]:
    """Run quick or full environment checks."""
    checks = [_doctor_binary(ops), _doctor_encoders(ops), _doctor_imports(ops)]
    if depth == "full":
        checks.append(_doctor_roundtrip(ops))
    return checks
