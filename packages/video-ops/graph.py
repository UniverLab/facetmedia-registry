"""Pure FFmpeg command building and stderr probing for the video-ops package.

stdlib only, no imports from the package environment: the runner wires
these functions to the bundled static binary, and
``tests/test_video_ops_graph.py`` asserts the exact argument lists and
parsed probe fields on fixed inputs.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
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
