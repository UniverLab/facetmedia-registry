"""Pure command-builder and stderr-parser tests for packages/video-ops/graph.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "video_ops_graph", ROOT / "packages" / "video-ops" / "graph.py"
)
assert SPEC is not None and SPEC.loader is not None
graph = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = graph
SPEC.loader.exec_module(graph)

SAMPLE_STDERR = (
    "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':\n"
    "  Metadata:\n"
    "    major_brand     : isom\n"
    "  Duration: 00:01:02.50, start: 0.000000, bitrate: 1200 kb/s\n"
    "  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), "
    "yuv420p(progressive), 1280x720 [SAR 1:1 DAR 16:9], 1050 kb/s, "
    "29.97 fps, 29.97 tbr, 30k tbn (default)\n"
    "  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), "
    "48000 Hz, stereo, fltp, 128 kb/s (default)\n"
)

EXPECTED_DURATION = 62.5
EXPECTED_WIDTH = 1280
EXPECTED_HEIGHT = 720
EXPECTED_FPS = 29.97


def test_transcode_args_defaults() -> None:
    args = graph.transcode_args(Path("in.mov"), Path("out.mp4"))
    assert args == [
        "-i",
        "in.mov",
        "-c:v",
        "libx264",
        "-crf",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "out.mp4",
    ]


def test_transcode_args_with_scale_fps_and_trim() -> None:
    opts = graph.TranscodeOptions(
        crf=20,
        max_width=1280,
        fps=30,
        start_s=1.5,
        end_s=5.0,
        audio_bitrate_kbps=192,
    )
    args = graph.transcode_args(Path("in.mp4"), Path("out.mp4"), opts)
    assert args == [
        "-i",
        "in.mp4",
        "-ss",
        "1.5",
        "-to",
        "5",
        "-vf",
        "scale='min(iw,1280)':-2,fps=30",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "out.mp4",
    ]


def test_mux_audio_args() -> None:
    args = graph.mux_audio_args(
        Path("vid.mp4"), Path("voice.wav"), Path("muxed.mp4"), audio_bitrate_kbps=160
    )
    assert args == [
        "-i",
        "vid.mp4",
        "-i",
        "voice.wav",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-shortest",
        "-movflags",
        "+faststart",
        "muxed.mp4",
    ]


def test_frame_args() -> None:
    args = graph.frame_args(Path("vid.mp4"), Path("thumb.png"), at_s=2.25)
    assert args == ["-ss", "2.25", "-i", "vid.mp4", "-frames:v", "1", "-q:v", "2", "thumb.png"]


def test_probe_stderr_parse() -> None:
    parsed = graph.probe_stderr_parse(SAMPLE_STDERR)
    assert parsed == {
        "duration_s": EXPECTED_DURATION,
        "width": EXPECTED_WIDTH,
        "height": EXPECTED_HEIGHT,
        "video_codec": "h264",
        "audio_codec": "aac",
        "fps": EXPECTED_FPS,
    }


def test_probe_stderr_parse_handles_video_only_and_empty() -> None:
    video_only = (
        "  Duration: 00:00:01.00, start: 0.0\n"
        "  Stream #0:0: Video: hevc, yuv420p, 320x240, 24 fps\n"
    )
    parsed = graph.probe_stderr_parse(video_only)
    assert parsed["audio_codec"] is None
    assert parsed["video_codec"] == "hevc"
    assert graph.probe_stderr_parse("") == {
        "duration_s": None,
        "width": None,
        "height": None,
        "video_codec": None,
        "audio_codec": None,
        "fps": None,
    }


def test_version_and_encoder_helpers() -> None:
    ver = "ffmpeg version 7.0.2-static https://johnvansickle.com/ffmpeg/\nline2\n"
    assert (
        graph.version_line(ver) == "ffmpeg version 7.0.2-static https://johnvansickle.com/ffmpeg/"
    )
    assert graph.version_id(ver) == "7.0.2-static"
    encoders = " V..... libx264              libx264 H.264\n A..... aac                  AAC\n"
    assert graph.encoder_names(encoders) == {"libx264", "aac"}
