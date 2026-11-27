"""Pure FFmpeg command building and stderr probing for the video-ops package.

stdlib only, no imports from the package environment: the runner wires
these functions to the bundled static binary, and
``tests/test_video_ops_graph.py`` asserts the exact argument lists and
parsed probe fields on fixed inputs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

#: Duration line from ``ffmpeg -i`` stderr, e.g. ``Duration: 00:00:05.12, ...``.
_DURATION_RE: Final[re.Pattern[str]] = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
#: Video stream line from ``ffmpeg -i`` stderr.
_VIDEO_RE: Final[re.Pattern[str]] = re.compile(
    r"Stream\s+#\d+:\d+[^:]*:\s*Video:\s*([^\s,(]+)(.*)$", re.MULTILINE
)
#: Audio stream line from ``ffmpeg -i`` stderr.
_AUDIO_RE: Final[re.Pattern[str]] = re.compile(
    r"Stream\s+#\d+:\d+[^:]*:\s*Audio:\s*([^\s,(]+)", re.MULTILINE
)
#: Pixel dimensions inside a video stream description, e.g. ``, 1280x720 [SAR ...``.
_SIZE_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|[\s,])(\d{2,5})x(\d{2,5})(?=[\s,]|$)")
#: Frame rate token in a video stream description.
_FPS_RE: Final[re.Pattern[str]] = re.compile(r"(\d+(?:\.\d+)?)\s*fps\b")
_TBR_RE: Final[re.Pattern[str]] = re.compile(r"(\d+(?:\.\d+)?)\s*tbr\b")
#: One ``ffmpeg -encoders`` listing line: six flag characters, then the name.
_ENCODER_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*[A-Z.]{6}\s+(\S+)")
MIN_CONCAT_CLIPS: Final[int] = 2
#: atempo filter accepts tempo values in [0.5, 2.0]; wider factors chain.
ATEMPO_MIN: Final[float] = 0.5
ATEMPO_MAX: Final[float] = 2.0
_SILENCE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"silence_(start|end):\s*([0-9]+(?:\.[0-9]+)?)"
)
_MIN_KEEP_SEGMENT_S: Final[float] = 0.05
FX_PRESETS: Final[dict[str, dict[str, Any]]] = {
    "none": {
        "grain": 0.0,
        "chroma_px": 0,
        "vignette": 0.0,
        "halation": 0.0,
        "scanlines": False,
        "glitch": 0.0,
    },
    "film": {
        "grain": 0.25,
        "chroma_px": 1,
        "vignette": 0.35,
        "halation": 0.25,
        "scanlines": False,
        "glitch": 0.0,
    },
    "vhs": {
        "grain": 0.45,
        "chroma_px": 4,
        "vignette": 0.40,
        "halation": 0.20,
        "scanlines": True,
        "glitch": 0.15,
    },
    "glitch": {
        "grain": 0.20,
        "chroma_px": 6,
        "vignette": 0.15,
        "halation": 0.0,
        "scanlines": False,
        "glitch": 0.65,
    },
    "crt": {
        "grain": 0.15,
        "chroma_px": 2,
        "vignette": 0.45,
        "halation": 0.30,
        "scanlines": True,
        "glitch": 0.0,
    },
}


@dataclass(frozen=True)
class TranscodeOptions:
    """Optional parameters for ``transcode_args``."""

    crf: int = 24
    max_width: int | None = None
    fps: int | None = None
    start_s: float | None = None
    end_s: float | None = None
    audio_bitrate_kbps: int = 128


@dataclass(frozen=True)
class ConcatOptions:
    """Optional parameters for ``concat_args``."""

    transition: str = "fade"
    transition_s: float = 0.5
    fps: int = 30
    crf: int = 23
    include_audio: bool = False


@dataclass(frozen=True)
class OverlayOptions:
    """Optional parameters for ``overlay_args``."""

    position: str = "fullscreen"
    scale_width: int | None = None
    margin_px: int = 24
    start_s: float = 0.0
    end_s: float | None = None
    crf: int = 23
    has_audio: bool = True


@dataclass(frozen=True)
class GradeOptions:
    """Optional parameters for ``grade_args``."""

    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0
    crf: int = 23
    has_audio: bool = True


@dataclass(frozen=True)
class FxOptions:
    """Optional parameters for ``fx_args``."""

    grain: float = 0.0
    chroma_px: int = 0
    vignette: float = 0.0
    halation: float = 0.0
    scanlines: bool = False
    glitch: float = 0.0
    seed: int = 42
    has_audio: bool = True
    crf: int = 23


def num(value: float) -> str:
    """Format a number for an ffmpeg argument in the shortest exact form."""
    return f"{value:g}"


def transcode_args(input: Path, output: Path, opts: TranscodeOptions | None = None) -> list[str]:
    """Build ffmpeg args for H.264/AAC faststart transcoding with optional scale and trim."""
    cfg = opts or TranscodeOptions()
    args = ["-i", str(input)]
    if cfg.start_s is not None:
        args.extend(["-ss", num(cfg.start_s)])
    if cfg.end_s is not None:
        args.extend(["-to", num(cfg.end_s)])
    filters: list[str] = []
    if cfg.max_width is not None:
        filters.append(f"scale='min(iw,{int(cfg.max_width)})':-2")
    if cfg.fps is not None:
        filters.append(f"fps={int(cfg.fps)}")
    if filters:
        args.extend(["-vf", ",".join(filters)])
    args.extend(
        [
            "-c:v",
            "libx264",
            "-crf",
            str(int(cfg.crf)),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            f"{int(cfg.audio_bitrate_kbps)}k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return args


def mux_audio_args(
    video: Path, audio: Path, output: Path, *, audio_bitrate_kbps: int = 128
) -> list[str]:
    """Build ffmpeg args to replace a video's audio without re-encoding video."""
    return [
        "-i",
        str(video),
        "-i",
        str(audio),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        f"{int(audio_bitrate_kbps)}k",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output),
    ]


def frame_args(video: Path, output: Path, *, at_s: float = 0.0) -> list[str]:
    """Build ffmpeg args to extract a single still frame at ``at_s``."""
    return ["-ss", num(at_s), "-i", str(video), "-frames:v", "1", "-q:v", "2", str(output)]


def probe_stderr_parse(stderr: str) -> dict[str, Any]:
    """Parse duration, dimensions, codecs, and fps from ``ffmpeg -i`` stderr."""
    duration_s: float | None = None
    dur_match = _DURATION_RE.search(stderr)
    if dur_match is not None:
        hours, minutes, seconds = dur_match.groups()
        duration_s = round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)

    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    fps: float | None = None
    vid_match = _VIDEO_RE.search(stderr)
    if vid_match is not None:
        video_codec = vid_match.group(1)
        rest = vid_match.group(2)
        size_match = _SIZE_RE.search(rest)
        if size_match is not None:
            width = int(size_match.group(1))
            height = int(size_match.group(2))
        fps_match = _FPS_RE.search(rest) or _TBR_RE.search(rest)
        if fps_match is not None:
            fps = float(fps_match.group(1))

    aud_match = _AUDIO_RE.search(stderr)
    audio_codec = aud_match.group(1) if aud_match is not None else None

    return {
        "duration_s": duration_s,
        "width": width,
        "height": height,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "fps": fps,
    }


def version_line(text: str) -> str:
    """Return the first line of ``ffmpeg -version``."""
    lines = text.splitlines()
    return lines[0].strip() if lines else ""


def version_id(text: str) -> str:
    """Return the build token after ``ffmpeg version``, e.g. ``7.0.2-static``."""
    rest = version_line(text).partition("ffmpeg version")[2]
    return rest.split()[0] if rest.strip() else ""


def encoder_names(text: str) -> set[str]:
    """Return the encoder names listed by ``ffmpeg -encoders``."""
    names: set[str] = set()
    for line in text.splitlines():
        match = _ENCODER_LINE.match(line)
        if match is not None and match.group(1) != "=":
            names.add(match.group(1))
    return names


def _escape_subtitles_path(path: Path | str) -> str:
    """Escape a subtitle path for the FFmpeg ``subtitles`` filter value."""
    raw = str(path)
    return (
        raw.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
        .replace(" ", "\\ ")
    )


def _concat_vf(target_width: int, target_height: int, fps: int) -> str:
    return (
        f"scale={int(target_width)}:{int(target_height)}"
        ":force_original_aspect_ratio=decrease,"
        f"pad={int(target_width)}:{int(target_height)}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,fps={int(fps)},format=yuv420p"
    )


def _resolve_concat_options(options: ConcatOptions | None, kwargs: dict[str, Any]) -> ConcatOptions:
    """Resolve ``concat_args`` settings from an options object or spec keywords."""
    if options is None:
        return ConcatOptions(**kwargs)
    if kwargs:
        raise TypeError("concat_args: pass either options or keywords, not both")
    return options


def _resolve_grade_options(options: GradeOptions | None, kwargs: dict[str, Any]) -> GradeOptions:
    """Resolve ``grade_args`` settings from an options object or spec keywords."""
    if options is None:
        return GradeOptions(**kwargs)
    if kwargs:
        raise TypeError("grade_args: pass either options or keywords, not both")
    return options


def concat_args(
    clips: Sequence[Path | str],
    output: Path | str,
    durations: Sequence[float],
    target_width: int,
    target_height: int,
    *,
    options: ConcatOptions | None = None,
    **kwargs: Any,
) -> list[str]:
    """Build ffmpeg args to join clips with xfade/acrossfade transitions or cut concat.

    Spec calling convention (every keyword optional)::

        concat_args(clips, output, durations, target_width, target_height,
                    transition="fade", transition_s=0.5, fps=30, crf=23,
                    include_audio=False)

    ``options`` carries the same fields as one object; pass either ``options``
    or keywords, never both. The keyword form exists because the spec fixes
    these parameter names, while the options object keeps this function under
    the repo's PLR0913 max-args gate (an explicit 10-parameter definition
    fails ``ruff strict``).
    """
    if len(clips) != len(durations):
        raise ValueError("clips and durations must have the same length")
    if len(clips) < MIN_CONCAT_CLIPS:
        raise ValueError("concat requires at least two clips")
    cfg = _resolve_concat_options(options, kwargs)

    args: list[str] = []
    for clip in clips:
        args.extend(["-i", str(clip)])

    vf = _concat_vf(target_width, target_height, cfg.fps)
    filters: list[str] = []
    for index in range(len(clips)):
        filters.append(f"[{index}:v]{vf}[v{index}]")
        if cfg.include_audio:
            filters.append(
                f"[{index}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{index}]"
            )

    if cfg.transition == "cut":
        if cfg.include_audio:
            chain = "".join(f"[v{i}][a{i}]" for i in range(len(clips)))
            filters.append(f"{chain}concat=n={len(clips)}:v=1:a=1[vout][aout]")
        else:
            chain = "".join(f"[v{i}]" for i in range(len(clips)))
            filters.append(f"{chain}concat=n={len(clips)}:v=1:a=0[vout]")
    else:
        v_prev = "v0"
        a_prev = "a0"
        for index in range(1, len(clips)):
            offset = sum(float(d) for d in durations[:index]) - float(cfg.transition_s) * index
            v_out = "vout" if index == len(clips) - 1 else f"xv{index}"
            filters.append(
                f"[{v_prev}][v{index}]xfade=transition={cfg.transition}"
                f":duration={num(cfg.transition_s)}:offset={num(offset)}[{v_out}]"
            )
            v_prev = v_out
            if cfg.include_audio:
                a_out = "aout" if index == len(clips) - 1 else f"xa{index}"
                filters.append(f"[{a_prev}][a{index}]acrossfade=d={num(cfg.transition_s)}[{a_out}]")
                a_prev = a_out

    args.extend(["-filter_complex", ";".join(filters), "-map", "[vout]"])
    if cfg.include_audio:
        args.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"])
    else:
        args.append("-an")
    args.extend(
        [
            "-c:v",
            "libx264",
            "-crf",
            str(int(cfg.crf)),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return args


def burn_subs_args(
    video: Path | str,
    subtitles: Path | str,
    output: Path | str,
    *,
    font_size: int = 22,
    margin_v: int = 36,
    crf: int = 23,
    has_audio: bool = True,
) -> list[str]:
    """Build ffmpeg args to burn subtitles into a video using libass."""
    escaped = _escape_subtitles_path(subtitles)
    vf = f"subtitles={escaped}:force_style='Fontsize={int(font_size)},MarginV={int(margin_v)}'"
    args = [
        "-i",
        str(video),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-crf",
        str(int(crf)),
        "-pix_fmt",
        "yuv420p",
    ]
    if has_audio:
        args.extend(["-c:a", "copy"])
    else:
        args.append("-an")
    args.extend(["-movflags", "+faststart", str(output)])
    return args


def _even(value: float) -> int:
    """Round to the nearest even integer (libx264 + yuv420p requirement)."""
    return int(round(float(value) / 2.0)) * 2


def _atempo_chain(factor: float) -> list[float]:
    """Split a speed factor into chained atempo values each in [0.5, 2.0]."""
    remaining = float(factor)
    parts: list[float] = []
    while remaining > ATEMPO_MAX:
        parts.append(ATEMPO_MAX)
        remaining /= ATEMPO_MAX
    while remaining < ATEMPO_MIN:
        parts.append(ATEMPO_MIN)
        remaining /= ATEMPO_MIN
    parts.append(remaining)
    return parts


def _overlay_xy(position: str, margin: int) -> tuple[str, str]:
    """Return overlay x:y expressions for a corner/center placement."""
    m = num(margin)
    if position == "top-left":
        return (m, m)
    if position == "top-right":
        return (f"W-w-{m}", m)
    if position == "bottom-left":
        return (m, f"H-h-{m}")
    if position == "bottom-right":
        return (f"W-w-{m}", f"H-h-{m}")
    return ("(W-w)/2", "(H-h)/2")


def _reframe_dims(aspect: str, width: int) -> tuple[int, int]:
    """Return exact even (target_width, target_height) for an aspect string."""
    wide, _, high = aspect.partition(":")
    target_w = _even(width)
    target_h = _even(target_w * float(high) / float(wide))
    return (target_w, target_h)


def _resolve_overlay_options(
    options: OverlayOptions | None, kwargs: dict[str, Any]
) -> OverlayOptions:
    """Resolve ``overlay_args`` settings from an options object or spec keywords."""
    if options is None:
        return OverlayOptions(**kwargs)
    if kwargs:
        raise TypeError("overlay_args: pass either options or keywords, not both")
    return options


def _overlay_enable(start_s: float, end_s: float | None) -> str:
    """Build the overlay enable expression for a [start, end] window."""
    if end_s is None:
        if float(start_s) <= 0:
            return ""
        return f"gte(t,{num(start_s)})"
    return f"between(t,{num(start_s)},{num(end_s)})"


def overlay_args(
    base: Path | str,
    overlay: Path | str,
    output: Path | str,
    base_width: int,
    base_height: int,
    *,
    options: OverlayOptions | None = None,
    **kwargs: Any,
) -> list[str]:
    """Build ffmpeg args to composite an overlay over base footage.

    Spec calling convention (every keyword optional)::

        overlay_args(base, overlay, output, base_width, base_height,
                     position="fullscreen", scale_width=None, margin_px=24,
                     start_s=0.0, end_s=None, crf=23, has_audio=True)

    ``options`` carries the same fields as one object; pass either ``options``
    or keywords, never both. ``eof_action=pass`` keeps base frames after a
    shorter overlay ends; ``fullscreen`` scales the overlay to the base canvas
    and ignores ``scale_width``.
    """
    cfg = _resolve_overlay_options(options, kwargs)
    if cfg.position == "fullscreen":
        prep = f"[1:v]scale={int(base_width)}:{int(base_height)}[ov]"
        x, y = "0", "0"
    elif cfg.scale_width is not None:
        prep = f"[1:v]scale={int(cfg.scale_width)}:-2[ov]"
        x, y = _overlay_xy(cfg.position, int(cfg.margin_px))
    else:
        prep = "[1:v]copy[ov]"
        x, y = _overlay_xy(cfg.position, int(cfg.margin_px))
    enable = _overlay_enable(float(cfg.start_s), cfg.end_s)
    suffix = f":enable='{enable}'" if enable else ""
    overlay_filter = f"[0:v][ov]overlay={x}:{y}{suffix}:eof_action=pass,format=yuv420p[vout]"
    args = ["-i", str(base), "-i", str(overlay)]
    args.extend(["-filter_complex", f"{prep};{overlay_filter}"])
    args.extend(["-map", "[vout]"])
    if cfg.has_audio:
        args.extend(["-map", "0:a", "-c:a", "copy"])
    else:
        args.append("-an")
    args.extend(
        [
            "-c:v",
            "libx264",
            "-crf",
            str(int(cfg.crf)),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return args


def speed_args(
    video: Path | str,
    output: Path | str,
    factor: float,
    *,
    keep_audio: bool = True,
    has_audio: bool = True,
    crf: int = 23,
) -> list[str]:
    """Build ffmpeg args for timelapse/slow-motion with synchronized audio."""
    args = ["-i", str(video), "-vf", f"setpts=PTS/{num(factor)}"]
    if keep_audio and has_audio:
        chain = ",".join(f"atempo={num(part)}" for part in _atempo_chain(float(factor)))
        args.extend(["-af", chain, "-c:a", "aac"])
    else:
        args.append("-an")
    args.extend(
        [
            "-c:v",
            "libx264",
            "-crf",
            str(int(crf)),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return args


def reframe_args(
    video: Path | str,
    output: Path | str,
    aspect: str,
    *,
    mode: str = "crop",
    width: int = 1080,
    crf: int = 23,
    has_audio: bool = True,
) -> list[str]:
    """Build ffmpeg args to reframe footage to a vertical/square canvas."""
    target_w, target_h = _reframe_dims(aspect, int(width))
    if mode == "blur-pad":
        vf = (
            "[0:v]split=2[bg_src][fg_src];"
            f"[bg_src]scale={target_w}:{target_h},boxblur=20:5[bg];"
            f"[fg_src]scale={target_w}:{target_h}"
            ":force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p"
        )
    else:
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},setsar=1,format=yuv420p"
        )
    args = ["-i", str(video), "-vf", vf, "-c:v", "libx264", "-crf", str(int(crf))]
    args.extend(["-pix_fmt", "yuv420p"])
    if has_audio:
        args.extend(["-c:a", "copy"])
    else:
        args.append("-an")
    args.extend(["-movflags", "+faststart", str(output)])
    return args


def grade_args(
    video: Path | str,
    output: Path | str,
    duration_s: float,
    *,
    options: GradeOptions | None = None,
    **kwargs: Any,
) -> list[str]:
    """Build ffmpeg args for eq color grading and optional fade-in/fade-out.

    Spec calling convention (every keyword optional)::

        grade_args(video, output, duration_s, brightness=0.0, contrast=1.0,
                   saturation=1.0, gamma=1.0, fade_in_s=0.0, fade_out_s=0.0,
                   crf=23, has_audio=True)

    ``options`` carries the same fields as one object; pass either ``options``
    or keywords, never both. The keyword form exists because the spec fixes
    these parameter names, while the options object keeps this function under
    the repo's PLR0913 max-args gate (an explicit 11-parameter definition
    fails ``ruff strict``).
    """
    cfg = _resolve_grade_options(options, kwargs)
    filters = [
        "eq="
        f"brightness={num(cfg.brightness)}:"
        f"contrast={num(cfg.contrast)}:"
        f"saturation={num(cfg.saturation)}:"
        f"gamma={num(cfg.gamma)}"
    ]
    if float(cfg.fade_in_s) > 0:
        filters.append(f"fade=t=in:st=0:d={num(cfg.fade_in_s)}")
    if float(cfg.fade_out_s) > 0:
        start = max(0.0, float(duration_s) - float(cfg.fade_out_s))
        filters.append(f"fade=t=out:st={num(start)}:d={num(cfg.fade_out_s)}")
    args = [
        "-i",
        str(video),
        "-vf",
        ",".join(filters),
        "-c:v",
        "libx264",
        "-crf",
        str(int(cfg.crf)),
        "-pix_fmt",
        "yuv420p",
    ]
    if cfg.has_audio:
        args.extend(["-c:a", "copy"])
    else:
        args.append("-an")
    args.extend(["-movflags", "+faststart", str(output)])
    return args


def resolve_fx(preset: str = "none", overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Merge explicit non-None overrides over ``FX_PRESETS[preset]``."""
    if preset not in FX_PRESETS:
        raise ValueError(f"unknown fx preset: {preset}")
    resolved = dict(FX_PRESETS[preset])
    if overrides:
        for key, value in overrides.items():
            norm = key.replace("-", "_")
            if norm in resolved and value is not None:
                resolved[norm] = value
    return resolved


def silence_detect_args(
    video: Path | str, threshold_db: float = -35.0, min_silence_s: float = 0.6
) -> list[str]:
    """Build ffmpeg args to run silencedetect and discard output."""
    return [
        "-i",
        str(video),
        "-af",
        f"silencedetect=noise={num(threshold_db)}dB:d={num(min_silence_s)}",
        "-f",
        "null",
        "-",
    ]


def parse_silences(stderr: str, duration_s: float | None = None) -> list[tuple[float, float]]:
    """Parse ``silence_start`` / ``silence_end`` pairs from ffmpeg stderr."""
    silences: list[tuple[float, float]] = []
    open_start: float | None = None
    for match in _SILENCE_TOKEN_RE.finditer(stderr):
        kind, raw_val = match.groups()
        val = float(raw_val)
        if kind == "start":
            open_start = val
        elif open_start is not None:
            if val > open_start:
                silences.append((open_start, val))
            open_start = None
    if open_start is not None and duration_s is not None and float(duration_s) > open_start:
        silences.append((open_start, float(duration_s)))
    return silences


def _merge_intervals(intervals: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sort and merge overlapping or touching ``(start, end)`` intervals."""
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged: list[tuple[float, float]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def keep_segments(
    duration_s: float, silences: Sequence[tuple[float, float]], margin_s: float = 0.12
) -> list[tuple[float, float]]:
    """Compute speech segments to keep by removing padded silence intervals."""
    total = float(duration_s)
    pad = float(margin_s)
    cuts: list[tuple[float, float]] = []
    for s_start, s_end in silences:
        cut_start = max(0.0, float(s_start) + pad)
        cut_end = min(total, float(s_end) - pad)
        if cut_end > cut_start:
            cuts.append((cut_start, cut_end))

    kept: list[tuple[float, float]] = []
    cursor = 0.0
    for cut_start, cut_end in _merge_intervals(cuts):
        seg_s = round(cursor, 3)
        seg_e = round(cut_start, 3)
        if seg_e - seg_s >= _MIN_KEEP_SEGMENT_S:
            kept.append((seg_s, seg_e))
        cursor = max(cursor, cut_end)
    tail_s = round(cursor, 3)
    tail_e = round(total, 3)
    if tail_e - tail_s >= _MIN_KEEP_SEGMENT_S:
        kept.append((tail_s, tail_e))
    return kept or [(0.0, round(total, 3))]


def jumpcut_args(
    video: Path | str,
    output: Path | str,
    segments: Sequence[tuple[float, float]],
    *,
    has_audio: bool = True,
    crf: int = 23,
) -> list[str]:
    """Build ffmpeg args to trim and concatenate kept speech segments."""
    if not segments:
        raise ValueError("jumpcut_args requires at least one segment")
    filters: list[str] = []
    for idx, (seg_s, seg_e) in enumerate(segments):
        s_txt = num(seg_s)
        e_txt = num(seg_e)
        filters.append(f"[0:v]trim=start={s_txt}:end={e_txt},setpts=PTS-STARTPTS[v{idx}]")
        if has_audio:
            filters.append(f"[0:a]atrim=start={s_txt}:end={e_txt},asetpts=PTS-STARTPTS[a{idx}]")
    if has_audio:
        chain = "".join(f"[v{idx}][a{idx}]" for idx in range(len(segments)))
        filters.append(f"{chain}concat=n={len(segments)}:v=1:a=1[vout][aout]")
    else:
        chain = "".join(f"[v{idx}]" for idx in range(len(segments)))
        filters.append(f"{chain}concat=n={len(segments)}:v=1:a=0[vout]")

    args = ["-i", str(video), "-filter_complex", ";".join(filters), "-map", "[vout]"]
    if has_audio:
        args.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"])
    else:
        args.append("-an")
    args.extend(
        [
            "-c:v",
            "libx264",
            "-crf",
            str(int(crf)),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return args


def _resolve_fx_options(options: FxOptions | None, kwargs: dict[str, Any]) -> FxOptions:
    """Resolve ``fx_args`` settings from an options object or spec keywords."""
    if options is None:
        return FxOptions(**kwargs)
    if kwargs:
        raise TypeError("fx_args: pass either options or keywords, not both")
    return options


def _fx_filters(cfg: FxOptions) -> str:
    """Build the deterministic -vf filter chain for ``fx_args``."""
    stages: list[str] = []
    if float(cfg.halation) > 0:
        sigma = round(2.0 + float(cfg.halation) * 10.0, 2)
        opacity = round(float(cfg.halation) * 0.45, 3)
        stages.append(
            f"split[hx0][hx1];[hx1]gblur=sigma={sigma}[hxb];"
            f"[hx0][hxb]blend=all_mode=screen:all_opacity={opacity}"
        )
    if int(cfg.chroma_px) > 0:
        px = int(cfg.chroma_px)
        stages.append(f"rgbashift=rh={px}:bh={-px}")
    if float(cfg.glitch) > 0:
        g = float(cfg.glitch)
        period = round(max(0.6, 3.0 - g * 2.0), 3)
        duty = round(0.08 + g * 0.14, 3)
        phase = round((int(cfg.seed) % 997) / 997.0 * period, 3)
        shift = max(2, int(round(g * 16)))
        noise_str = max(4, int(round(g * 45)))
        expr = f"lt(mod(t+{phase},{period}),{duty})"
        stages.append(f"rgbashift=rh={shift}:bh={-shift}:enable='{expr}'")
        stages.append(f"noise=alls={noise_str}:allf=t+u:all_seed={int(cfg.seed)}:enable='{expr}'")
    if float(cfg.grain) > 0:
        strength = max(1, int(round(float(cfg.grain) * 40)))
        stages.append(f"noise=alls={strength}:allf=t+u:all_seed={int(cfg.seed)}")
    if cfg.scanlines is True:
        stages.append("drawgrid=w=0:h=2:t=1:c=black@0.22")
    if float(cfg.vignette) > 0:
        angle = round(0.2 + float(cfg.vignette) * 0.9, 3)
        stages.append(f"vignette=angle={angle}")
    return ",".join(stages) if stages else "null"


def fx_args(
    video: Path | str,
    output: Path | str,
    *,
    options: FxOptions | None = None,
    **kwargs: Any,
) -> list[str]:
    """Build ffmpeg args for deterministic stylized visual finishes."""
    cfg = _resolve_fx_options(options, kwargs)
    args = [
        "-i",
        str(video),
        "-vf",
        _fx_filters(cfg),
        "-c:v",
        "libx264",
        "-crf",
        str(int(cfg.crf)),
        "-pix_fmt",
        "yuv420p",
    ]
    if cfg.has_audio:
        args.extend(["-c:a", "copy"])
    else:
        args.append("-an")
    args.extend(["-movflags", "+faststart", str(output)])
    return args
