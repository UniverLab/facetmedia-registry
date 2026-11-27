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
REFRAME_WIDTH = 1080
REFRAME_HEIGHT_9_16 = 1920
REFRAME_HEIGHT_4_5 = 1350
REFRAME_HEIGHT_16_9 = 608
ATEMPO_MIN = 0.5
ATEMPO_MAX = 2.0
CHAIN_TOLERANCE = 1e-9
BASE_WIDTH = 160
BASE_HEIGHT = 120
OVERLAY_MARGIN = 24


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


def test_even_rounds_to_nearest_even() -> None:
    assert graph._even(REFRAME_WIDTH) == REFRAME_WIDTH
    assert graph._even(607.5) == REFRAME_HEIGHT_16_9
    assert graph._even(1350.0) == REFRAME_HEIGHT_4_5
    assert graph._even(1920.4) == REFRAME_HEIGHT_9_16


def test_atempo_chain_splits_out_of_range_factors() -> None:
    assert graph._atempo_chain(1.0) == [1.0]
    assert graph._atempo_chain(0.5) == [0.5]
    assert graph._atempo_chain(2.0) == [2.0]
    assert graph._atempo_chain(4.0) == [2.0, 2.0]
    assert graph._atempo_chain(3.0) == [2.0, 1.5]
    assert graph._atempo_chain(0.25) == [0.5, 0.5]
    for factor in (0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 8.0):
        parts = graph._atempo_chain(factor)
        assert all(ATEMPO_MIN <= part <= ATEMPO_MAX for part in parts)
        product = 1.0
        for part in parts:
            product *= part
        assert abs(product - factor) < CHAIN_TOLERANCE


def test_overlay_xy_corners_and_center() -> None:
    margin = str(OVERLAY_MARGIN)
    assert graph._overlay_xy("top-left", OVERLAY_MARGIN) == (margin, margin)
    assert graph._overlay_xy("top-right", OVERLAY_MARGIN) == (f"W-w-{margin}", margin)
    assert graph._overlay_xy("bottom-left", OVERLAY_MARGIN) == (margin, f"H-h-{margin}")
    assert graph._overlay_xy("bottom-right", OVERLAY_MARGIN) == (
        f"W-w-{margin}",
        f"H-h-{margin}",
    )
    assert graph._overlay_xy("center", OVERLAY_MARGIN) == ("(W-w)/2", "(H-h)/2")


def test_reframe_dims_are_exact_and_even() -> None:
    dims = graph._reframe_dims("9:16", REFRAME_WIDTH)
    assert dims == (REFRAME_WIDTH, REFRAME_HEIGHT_9_16)
    assert graph._reframe_dims("1:1", REFRAME_WIDTH) == (REFRAME_WIDTH, REFRAME_WIDTH)
    dims_4_5 = graph._reframe_dims("4:5", REFRAME_WIDTH)
    assert dims_4_5 == (REFRAME_WIDTH, REFRAME_HEIGHT_4_5)
    dims_16_9 = graph._reframe_dims("16:9", REFRAME_WIDTH)
    assert dims_16_9 == (REFRAME_WIDTH, REFRAME_HEIGHT_16_9)
    for aspect in ("9:16", "1:1", "4:5", "16:9"):
        width, height = graph._reframe_dims(aspect, 721)
        assert width % 2 == 0 and height % 2 == 0


def test_overlay_args_fullscreen_defaults() -> None:
    args = graph.overlay_args(Path("base.mp4"), Path("logo.png"), Path("out.mp4"), 160, 120)
    assert args == [
        "-i",
        "base.mp4",
        "-i",
        "logo.png",
        "-filter_complex",
        "[1:v]scale=160:120[ov];[0:v][ov]overlay=0:0:eof_action=pass,format=yuv420p[vout]",
        "-map",
        "[vout]",
        "-map",
        "0:a",
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "out.mp4",
    ]


def test_overlay_args_corner_with_scale_and_enable_window() -> None:
    args = graph.overlay_args(
        Path("base.mp4"),
        Path("clip.mp4"),
        Path("out.mp4"),
        160,
        120,
        position="bottom-right",
        scale_width=64,
        margin_px=10,
        start_s=1.0,
        end_s=2.5,
    )
    fc = args[args.index("-filter_complex") + 1]
    assert "[1:v]scale=64:-2[ov]" in fc
    assert "overlay=W-w-10:H-h-10:enable='between(t,1,2.5)':eof_action=pass" in fc


def test_overlay_args_fullscreen_ignores_scale_width() -> None:
    args = graph.overlay_args(
        Path("base.mp4"),
        Path("clip.mp4"),
        Path("out.mp4"),
        160,
        120,
        position="fullscreen",
        scale_width=64,
    )
    fc = args[args.index("-filter_complex") + 1]
    assert "[1:v]scale=160:120[ov]" in fc
    assert "scale=64" not in fc


def test_overlay_args_no_audio_maps_no_stream() -> None:
    args = graph.overlay_args(
        Path("base.mp4"), Path("logo.png"), Path("out.mp4"), 160, 120, has_audio=False
    )
    assert "-an" in args
    assert "0:a" not in args


def test_overlay_args_options_match_keywords() -> None:
    by_keywords = graph.overlay_args(
        Path("base.mp4"),
        Path("clip.mp4"),
        Path("out.mp4"),
        160,
        120,
        position="top-left",
        margin_px=8,
        start_s=0.5,
        crf=20,
        has_audio=False,
    )
    by_options = graph.overlay_args(
        Path("base.mp4"),
        Path("clip.mp4"),
        Path("out.mp4"),
        160,
        120,
        options=graph.OverlayOptions(
            position="top-left", margin_px=8, start_s=0.5, crf=20, has_audio=False
        ),
    )
    assert by_keywords == by_options


def test_overlay_args_rejects_options_and_keywords() -> None:
    try:
        graph.overlay_args(
            Path("b.mp4"),
            Path("o.png"),
            Path("out.mp4"),
            160,
            120,
            options=graph.OverlayOptions(),
            crf=20,
        )
    except TypeError:
        return
    raise AssertionError("expected TypeError for options+keywords")


def test_speed_args_faster_with_audio() -> None:
    args = graph.speed_args(Path("vid.mp4"), Path("out.mp4"), 2.0)
    assert args == [
        "-i",
        "vid.mp4",
        "-vf",
        "setpts=PTS/2",
        "-af",
        "atempo=2",
        "-c:a",
        "aac",
        "-c:v",
        "libx264",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "out.mp4",
    ]


def test_speed_args_chains_atempo_outside_tempo_range() -> None:
    slow = graph.speed_args(Path("vid.mp4"), Path("out.mp4"), 0.5)
    assert slow[slow.index("-af") + 1] == "atempo=0.5"
    fast = graph.speed_args(Path("vid.mp4"), Path("out.mp4"), 4.0)
    assert fast[fast.index("-af") + 1] == "atempo=2,atempo=2"
    assert "setpts=PTS/4" in fast


def test_speed_args_drops_audio_without_keep_or_source() -> None:
    no_keep = graph.speed_args(Path("v.mp4"), Path("o.mp4"), 2.0, keep_audio=False)
    assert "-an" in no_keep
    no_src = graph.speed_args(Path("v.mp4"), Path("o.mp4"), 2.0, has_audio=False)
    assert "-an" in no_src
    assert "-af" not in no_src


def test_reframe_args_crop_centers_and_scales() -> None:
    args = graph.reframe_args(Path("vid.mp4"), Path("out.mp4"), "9:16")
    vf = args[args.index("-vf") + 1]
    assert vf == (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,format=yuv420p"
    )
    assert "-c:a" in args and "copy" in args
    assert args[-1] == "out.mp4"


def test_reframe_args_blur_pad_uses_backdrop() -> None:
    args = graph.reframe_args(Path("vid.mp4"), Path("out.mp4"), "1:1", mode="blur-pad", width=720)
    vf = args[args.index("-vf") + 1]
    assert "[0:v]split=2[bg_src][fg_src]" in vf
    assert "[bg_src]scale=720:720,boxblur=20:5[bg]" in vf
    assert "force_original_aspect_ratio=decrease" in vf
    assert "[bg][fg]overlay=(W-w)/2:(H-h)/2" in vf


def test_reframe_args_no_audio() -> None:
    args = graph.reframe_args(Path("vid.mp4"), Path("out.mp4"), "4:5", width=720, has_audio=False)
    assert "-an" in args
    assert "-c:a" not in args
