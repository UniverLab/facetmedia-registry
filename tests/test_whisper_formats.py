"""Tests for the whisper package's pure format writers (no model needed).

``formats`` turns the segment list faster-whisper returns into the two
derived assets. The cases pin what a reviewer reads: cues are numbered from
one and separated by a blank line, a timestamp rounds to the millisecond and
carries the hour when it crosses one (3599.9996 s is 01:00:00,000, not
00:59:59,999), and the sidecar keeps the detected language, the probability
and the duration plus one object per segment with its timed words, all
rounded and with the model's leading space dropped from each word.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "whisper_formats", ROOT / "packages" / "whisper" / "formats.py"
)
assert SPEC is not None and SPEC.loader is not None
formats = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(formats)

SEGMENTS = [
    {
        "start_s": 0.0,
        "end_s": 1.5,
        "text": " Hola.",
        "avg_logprob": -0.25,
        "no_speech_prob": 0.01234,
        "words": [{"start_s": 0.0, "end_s": 0.4, "word": " Hola", "probability": 0.98123}],
    },
    {
        "start_s": 3599.9996,
        "end_s": 3601.0,
        "text": " mundo ",
        "avg_logprob": -0.5,
        "no_speech_prob": 0.0,
        "words": [],
    },
]


class TestTimestamp(unittest.TestCase):
    def test_zero_pads_every_field(self) -> None:
        self.assertEqual(formats.format_timestamp(0), "00:00:00,000")
        self.assertEqual(formats.format_timestamp(1.5), "00:00:01,500")
        self.assertEqual(formats.format_timestamp(7384.25), "02:03:04,250")

    def test_hour_boundary_rounds_up_into_the_hour(self) -> None:
        self.assertEqual(formats.format_timestamp(3599.9996), "01:00:00,000")
        self.assertEqual(formats.format_timestamp(3600), "01:00:00,000")
        self.assertEqual(formats.format_timestamp(3601.0), "01:00:01,000")

    def test_negative_clamps_to_zero(self) -> None:
        self.assertEqual(formats.format_timestamp(-0.4), "00:00:00,000")


class TestSrt(unittest.TestCase):
    def test_cues_are_numbered_and_blank_line_separated(self) -> None:
        self.assertEqual(
            formats.to_srt(SEGMENTS),
            "1\n00:00:00,000 --> 00:00:01,500\nHola.\n\n2\n01:00:00,000 --> 01:00:01,000\nmundo\n",
        )

    def test_no_segments_write_nothing(self) -> None:
        self.assertEqual(formats.to_srt([]), "")


class TestJson(unittest.TestCase):
    def test_top_level_shape(self) -> None:
        data = formats.to_json("es", 0.99, 9.6406, SEGMENTS)
        self.assertEqual(
            sorted(data), ["duration_s", "language", "language_probability", "segments"]
        )
        self.assertEqual(data["language"], "es")
        self.assertEqual(data["language_probability"], 0.99)
        self.assertEqual(data["duration_s"], 9.641)
        self.assertEqual(len(data["segments"]), 2)

    def test_segment_and_word_shape(self) -> None:
        segment = formats.to_json("es", 0.99, 9.6406, SEGMENTS)["segments"][0]
        self.assertEqual(
            segment,
            {
                "start_s": 0.0,
                "end_s": 1.5,
                "text": "Hola.",
                "avg_logprob": -0.25,
                "no_speech_prob": 0.0123,
                "words": [{"start_s": 0.0, "end_s": 0.4, "word": "Hola", "probability": 0.9812}],
            },
        )

    def test_segment_without_words_has_an_empty_list(self) -> None:
        segment = formats.to_json("es", 0.99, 9.6406, SEGMENTS)["segments"][1]
        self.assertEqual(segment["words"], [])
        self.assertEqual(segment["text"], "mundo")
        self.assertEqual(segment["start_s"], 3600.0)


if __name__ == "__main__":
    unittest.main()
