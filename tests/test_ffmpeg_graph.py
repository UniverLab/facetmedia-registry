"""Tests for the ffmpeg package's pure command builders (no binary needed).

``graph`` builds every ffmpeg argument the runner runs, so these tests
pin the exact strings on fixed inputs: the mix filtergraph with ducking,
without ducking and with offsets; the convert arguments with cuts; the
two-pass loudnorm chain; and the loudnorm JSON parser on a block captured
from the bundled 7.0.2-static build (``input_i`` −27.40, offset 1.72).
The licence and the ``convert`` format enum come from the same build, so
the captured ``-version`` and ``-encoders`` lines are pinned too.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ffmpeg_graph", ROOT / "packages" / "ffmpeg" / "graph.py"
)
assert SPEC is not None and SPEC.loader is not None
graph = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(graph)

#: A loudnorm ``print_format=json`` stderr block captured from the bundled binary.
LOUDNORM_STDERR = """\
[Parsed_loudnorm_0 @ 0x79556c003040]
{
\t"input_i" : "-27.40",
\t"input_tp" : "-7.13",
\t"input_lra" : "3.60",
\t"input_thresh" : "-37.72",
\t"output_i" : "-17.72",
\t"output_tp" : "-1.50",
\t"output_lra" : "1.30",
\t"output_thresh" : "-28.00",
\t"normalization_type" : "dynamic",
\t"target_offset" : "1.72"
}
[out#0/null @ 0x213d7400] video:0KiB audio:3615KiB subtitle:0KiB
size=N/A time=00:00:09.70 bitrate=N/A speed=92.8x
"""

#: The captured measured values the two builders below receive.
MEASURED = {
    "input_i": -27.40,
    "input_tp": -7.13,
    "input_lra": 3.60,
    "input_thresh": -37.72,
    "target_offset": 1.72,
}

#: A ``-version`` first line captured from imageio-ffmpeg 0.6.0's binary.
VERSION_LINE = (
    "ffmpeg version 7.0.2-static https://johnvansickle.com/ffmpeg/  "
    "Copyright (c) 2000-2024 the FFmpeg developers"
)

#: The head and the four codec-enum encoders of a captured ``-encoders`` listing.
ENCODERS_TEXT = """\
Encoders:
 V..... = Video
 A..... = Audio
 S..... = Subtitle
 .F.... = Frame-level multithreading
 ..S... = Slice-level multithreading
 ...X.. = Codec is experimental
 ------
 A....D flac                 FLAC (Free Lossless Audio Codec)
 A....D libmp3lame           libmp3lame MP3 (MPEG audio layer 3) (codec mp3)
 A....D libopus              libopus Opus (codec opus)
 A....D pcm_s16le            PCM signed 16-bit little-endian
"""


def voice(start_s: float = 2.0, gain_db: float = 0.0) -> dict[str, object]:
    return {"role": "voice", "start_s": start_s, "gain_db": gain_db}


def bed(start_s: float = 0.0, gain_db: float = -6.0) -> dict[str, object]:
    return {"role": "bed", "start_s": start_s, "gain_db": gain_db}


class TestMixFiltergraph(unittest.TestCase):
    def test_with_ducking_and_offsets(self) -> None:
        got = graph.mix_filtergraph([voice(2.0, 0.0), bed(0.0, -6.0)], True, -12.0)
        self.assertEqual(
            got,
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=2000|2000,volume=0dB[l0];"
            "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=0|0,volume=-6dB[l1];"
            "[l0]anull[vsum];[l1]anull[bsum];"
            "[vsum]asplit=2[vout][vkey];[vkey]apad[vkeyp];"
            "[bsum][vkeyp]sidechaincompress=threshold=0.001:ratio=1.375:attack=20:release=300:makeup=1[bduck];"
            "[vout][bduck]amix=inputs=2:normalize=0[mix];"
            "[mix]alimiter=limit=0.891251[out]",
        )

    def test_without_ducking(self) -> None:
        got = graph.mix_filtergraph([voice(), bed()], False, -12.0)
        self.assertEqual(
            got,
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=2000|2000,volume=0dB[l0];"
            "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=0|0,volume=-6dB[l1];"
            "[l0]anull[vsum];[l1]anull[bsum];"
            "[vsum][bsum]amix=inputs=2:normalize=0[mix];"
            "[mix]alimiter=limit=0.891251[out]",
        )

    def test_two_voices_sum_and_deeper_duck(self) -> None:
        got = graph.mix_filtergraph([voice(0.0), voice(1.5), bed()], True, -30.0)
        self.assertIn("[l0][l1]amix=inputs=2:normalize=0[vsum]", got)
        self.assertIn("adelay=1500|1500", got)
        self.assertIn("ratio=3.14286", got)

    def test_single_layer_passes_through(self) -> None:
        got = graph.mix_filtergraph([voice(0.0)], True, -12.0)
        self.assertEqual(
            got,
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=0|0,volume=0dB[l0];"
            "[l0]anull[vsum];[vsum]alimiter=limit=0.891251[out]",
        )


class TestDuckRatio(unittest.TestCase):
    def test_minus_twelve(self) -> None:
        self.assertEqual(graph.num(graph.duck_ratio(-12.0)), "1.375")

    def test_minus_thirty(self) -> None:
        self.assertEqual(round(graph.duck_ratio(-30.0), 3), 3.143)


class TestNormalizeArgs(unittest.TestCase):
    def test_two_pass_chain(self) -> None:
        got = graph.normalize_args(Path("in.flac"), Path("out.wav"), -16.0, -1.5, MEASURED, 48000)
        self.assertEqual(
            got,
            [
                "-i",
                "in.flac",
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-27.4:measured_TP=-7.13"
                ":measured_LRA=3.6:measured_thresh=-37.72:offset=1.72"
                ":linear=true:print_format=summary"
                ",aresample=48000,alimiter=limit=0.841395:level=false",
                "out.wav",
            ],
        )

    def test_measure_args_decode_to_float_wav(self) -> None:
        self.assertEqual(
            graph.measure_args(Path("in.wav"), Path("m.wav")),
            ["-i", "in.wav", "-acodec", "pcm_f32le", "-f", "wav", "m.wav"],
        )


class TestConvertArgs(unittest.TestCase):
    def test_with_cuts_resample_channels_and_bitrate(self) -> None:
        got = graph.convert_args(
            Path("in.flac"),
            Path("out.ogg"),
            "ogg",
            cut=(0.0, 5.0),
            sample_rate_hz=44100,
            channels=1,
            bitrate_kbps=128,
        )
        self.assertEqual(
            got,
            [
                "-i",
                "in.flac",
                "-ss",
                "0",
                "-to",
                "5",
                "-ar",
                "44100",
                "-ac",
                "1",
                "-c:a",
                "libopus",
                "-b:a",
                "128k",
                "out.ogg",
            ],
        )

    def test_wav_without_options(self) -> None:
        got = graph.convert_args(Path("in.wav"), Path("out.wav"), "wav")
        self.assertEqual(got, ["-i", "in.wav", "-c:a", "pcm_s16le", "out.wav"])

    def test_flac_is_lossless_no_bitrate(self) -> None:
        got = graph.convert_args(Path("in.wav"), Path("out.flac"), "flac")
        self.assertEqual(got, ["-i", "in.wav", "-c:a", "flac", "out.flac"])

    def test_unknown_format_rejected(self) -> None:
        with self.assertRaises(ValueError):
            graph.convert_args(Path("in.wav"), Path("out.aac"), "aac")


class TestMixArgs(unittest.TestCase):
    def test_inputs_then_graph_then_map(self) -> None:
        got = graph.mix_args("GRAPH", [Path("a.flac"), Path("b.flac")], Path("out.wav"))
        self.assertEqual(
            got,
            [
                "-i",
                "a.flac",
                "-i",
                "b.flac",
                "-filter_complex",
                "GRAPH",
                "-map",
                "[out]",
                "out.wav",
            ],
        )


class TestLoudnormJson(unittest.TestCase):
    def test_captured_block_floats_only(self) -> None:
        got = graph.loudnorm_json(LOUDNORM_STDERR)
        self.assertEqual(
            got,
            {
                "input_i": -27.40,
                "input_tp": -7.13,
                "input_lra": 3.60,
                "input_thresh": -37.72,
                "output_i": -17.72,
                "output_tp": -1.50,
                "output_lra": 1.30,
                "output_thresh": -28.00,
                "target_offset": 1.72,
            },
        )

    def test_last_block_wins(self) -> None:
        first = '{\n"input_i" : "-9.99",\n"target_offset" : "0.00"\n}\n'
        self.assertEqual(graph.loudnorm_json(first + LOUDNORM_STDERR)["input_i"], -27.40)

    def test_no_block_raises(self) -> None:
        with self.assertRaises(ValueError):
            graph.loudnorm_json("no braces here")


class TestBuild(unittest.TestCase):
    def test_version_line_and_id(self) -> None:
        self.assertEqual(graph.version_line(VERSION_LINE + "\nlibavutil ..."), VERSION_LINE)
        self.assertEqual(graph.version_id(VERSION_LINE), "7.0.2-static")

    def test_encoder_names_skip_headers(self) -> None:
        names = graph.encoder_names(ENCODERS_TEXT)
        self.assertEqual(names, {"flac", "libmp3lame", "libopus", "pcm_s16le"})
        self.assertNotIn("=", names)

    def test_format_enum_matches_the_build(self) -> None:
        names = graph.encoder_names(ENCODERS_TEXT)
        self.assertEqual(set(graph.CODECS.values()), names)
        self.assertEqual(graph.LOSSY, {"mp3", "ogg"})


if __name__ == "__main__":
    unittest.main()
