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


def test_concat_args_cut_no_audio() -> None:
    args = graph.concat_args(
        [Path("a.mp4"), Path("b.mp4")],
        Path("out.mp4"),
        [1.0, 2.0],
        160,
        120,
        options=graph.ConcatOptions(
            transition="cut",
            transition_s=0.5,
            fps=30,
            crf=23,
            include_audio=False,
        ),
    )
    assert args[:4] == ["-i", "a.mp4", "-i", "b.mp4"]
    fc = args[args.index("-filter_complex") + 1]
    assert "scale=160:120:force_original_aspect_ratio=decrease" in fc
    assert "pad=160:120:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v0]" in fc
    assert "[v0][v1]concat=n=2:v=1:a=0[vout]" in fc
    assert args[args.index("-map") + 1] == "[vout]"
    assert "-an" in args
    assert args[-1] == "out.mp4"


def test_concat_args_xfade_with_audio() -> None:
    args = graph.concat_args(
        [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")],
        Path("out.mp4"),
        [2.0, 2.0, 2.0],
        320,
        240,
        options=graph.ConcatOptions(
            transition="fade",
            transition_s=0.5,
            fps=30,
            crf=23,
            include_audio=True,
        ),
    )
    fc = args[args.index("-filter_complex") + 1]
    assert "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a0]" in fc
    assert "xfade=transition=fade:duration=0.5:offset=1.5[xv1]" in fc
    assert "xfade=transition=fade:duration=0.5:offset=3[vout]" in fc
    assert "acrossfade=d=0.5[xa1]" in fc
    assert "acrossfade=d=0.5[aout]" in fc
    assert "[vout]" in args
    assert "[aout]" in args
    assert "-c:a" in args
    assert "aac" in args


def test_burn_subs_args_escapes_path_and_copies_audio() -> None:
    args = graph.burn_subs_args(
        Path("in.mp4"),
        Path("/tmp/a:b c.srt"),
        Path("out.mp4"),
        font_size=24,
        margin_v=40,
        crf=20,
        has_audio=True,
    )
    assert args[:2] == ["-i", "in.mp4"]
    vf = args[args.index("-vf") + 1]
    assert "subtitles=" in vf
    assert "\\:" in vf
    assert "\\ " in vf
    assert "Fontsize=24" in vf
    assert "MarginV=40" in vf
    assert "-c:a" in args
    assert "copy" in args
    assert args[-1] == "out.mp4"


def test_burn_subs_args_no_audio() -> None:
    args = graph.burn_subs_args(Path("in.mp4"), Path("subs.srt"), Path("out.mp4"), has_audio=False)
    assert "-an" in args
    assert "copy" not in args


def test_grade_args_with_fades() -> None:
    args = graph.grade_args(
        Path("in.mp4"),
        Path("out.mp4"),
        10.0,
        options=graph.GradeOptions(
            brightness=0.1,
            contrast=1.2,
            saturation=0.9,
            gamma=1.1,
            fade_in_s=0.5,
            fade_out_s=1.0,
            crf=22,
            has_audio=True,
        ),
    )
    vf = args[args.index("-vf") + 1]
    assert "eq=brightness=0.1:contrast=1.2:saturation=0.9:gamma=1.1" in vf
    assert "fade=t=in:st=0:d=0.5" in vf
    assert "fade=t=out:st=9:d=1" in vf
    assert "-c:a" in args
    assert "copy" in args
    assert args[args.index("-crf") + 1] == "22"


def test_grade_args_no_audio_no_fades() -> None:
    args = graph.grade_args(
        Path("in.mp4"),
        Path("out.mp4"),
        5.0,
        options=graph.GradeOptions(
            brightness=0.0,
            contrast=1.0,
            saturation=1.0,
            gamma=1.0,
            fade_in_s=0.0,
            fade_out_s=0.0,
            crf=23,
            has_audio=False,
        ),
    )
    vf = args[args.index("-vf") + 1]
    assert vf == "eq=brightness=0:contrast=1:saturation=1:gamma=1"
    assert "-an" in args


def test_concat_args_spec_keywords_equal_options() -> None:
    clips = [Path("a.mp4"), Path("b.mp4")]
    by_keywords = graph.concat_args(
        clips,
        Path("out.mp4"),
        [1.0, 2.0],
        160,
        120,
        transition="cut",
        transition_s=0.5,
        fps=30,
        crf=23,
        include_audio=False,
    )
    by_options = graph.concat_args(
        clips,
        Path("out.mp4"),
        [1.0, 2.0],
        160,
        120,
        options=graph.ConcatOptions(
            transition="cut",
            transition_s=0.5,
            fps=30,
            crf=23,
            include_audio=False,
        ),
    )
    assert by_keywords == by_options


def test_concat_args_defaults_match_explicit_spec_keywords() -> None:
    clips = [Path("a.mp4"), Path("b.mp4")]
    assert graph.concat_args(clips, Path("out.mp4"), [2.0, 2.0], 320, 240) == graph.concat_args(
        clips,
        Path("out.mp4"),
        [2.0, 2.0],
        320,
        240,
        transition="fade",
        transition_s=0.5,
        fps=30,
        crf=23,
        include_audio=False,
    )


def test_concat_args_rejects_options_and_keywords() -> None:
    try:
        graph.concat_args(
            [Path("a.mp4"), Path("b.mp4")],
            Path("out.mp4"),
            [1.0, 2.0],
            160,
            120,
            options=graph.ConcatOptions(),
            transition="cut",
        )
    except TypeError:
        return
    raise AssertionError("expected TypeError for options+keywords")


def test_concat_args_rejects_unknown_keyword() -> None:
    try:
        graph.concat_args(
            [Path("a.mp4"), Path("b.mp4")],
            Path("out.mp4"),
            [1.0, 2.0],
            160,
            120,
            no_such_option=1,
        )
    except TypeError:
        return
    raise AssertionError("expected TypeError for unknown keyword")


def test_grade_args_spec_keywords_equal_options() -> None:
    by_keywords = graph.grade_args(
        Path("in.mp4"),
        Path("out.mp4"),
        10.0,
        brightness=0.1,
        contrast=1.2,
        saturation=0.9,
        gamma=1.1,
        fade_in_s=0.5,
        fade_out_s=1.0,
        crf=22,
        has_audio=True,
    )
    by_options = graph.grade_args(
        Path("in.mp4"),
        Path("out.mp4"),
        10.0,
        options=graph.GradeOptions(
            brightness=0.1,
            contrast=1.2,
            saturation=0.9,
            gamma=1.1,
            fade_in_s=0.5,
            fade_out_s=1.0,
            crf=22,
            has_audio=True,
        ),
    )
    assert by_keywords == by_options


def test_grade_args_defaults_match_explicit_spec_keywords() -> None:
    assert graph.grade_args(Path("in.mp4"), Path("out.mp4"), 5.0) == graph.grade_args(
        Path("in.mp4"),
        Path("out.mp4"),
        5.0,
        brightness=0.0,
        contrast=1.0,
        saturation=1.0,
        gamma=1.0,
        fade_in_s=0.0,
        fade_out_s=0.0,
        crf=23,
        has_audio=True,
    )


def test_grade_args_rejects_options_and_keywords() -> None:
    try:
        graph.grade_args(
            Path("in.mp4"),
            Path("out.mp4"),
            5.0,
            options=graph.GradeOptions(),
            crf=20,
        )
    except TypeError:
        return
    raise AssertionError("expected TypeError for options+keywords")


def test_grade_args_rejects_unknown_keyword() -> None:
    try:
        graph.grade_args(Path("in.mp4"), Path("out.mp4"), 5.0, no_such_option=1)
    except TypeError:
        return
    raise AssertionError("expected TypeError for unknown keyword")
