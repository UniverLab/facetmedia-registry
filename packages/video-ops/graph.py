"""Pure FFmpeg command building and stderr probing for the video-ops package.

stdlib only, no imports from the package environment: the runner wires
these functions to the bundled static binary, and
``tests/test_video_ops_graph.py`` asserts the exact argument lists and
parsed probe fields on fixed inputs.
"""

from __future__ import annotations

import re
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


@dataclass(frozen=True)
class TranscodeOptions:
    """Optional parameters for ``transcode_args``."""

    crf: int = 24
    max_width: int | None = None
    fps: int | None = None
    start_s: float | None = None
    end_s: float | None = None
    audio_bitrate_kbps: int = 128


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
