"""Pure format writers for the whisper package: SRT cues and the JSON sidecar.

Stdlib only, so the tests import this module without the package environment
and no model is ever needed. ``run`` builds the segments once from
faster-whisper and both writers take that same list: ``to_srt`` renders the
cues, ``to_json`` the timed record that ``verify`` and ``preview`` read back.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: Time units a timestamp is built from.
MILLISECONDS_PER_SECOND = 1000
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
MILLISECONDS_PER_MINUTE = MILLISECONDS_PER_SECOND * SECONDS_PER_MINUTE
MILLISECONDS_PER_HOUR = MILLISECONDS_PER_MINUTE * MINUTES_PER_HOUR
#: Digits kept for a timestamp's milliseconds and for the JSON's numbers.
TIMESTAMP_DECIMALS = 3
PROBABILITY_DECIMALS = 4


def format_timestamp(seconds: float) -> str:
    """``HH:MM:SS,mmm`` for one offset in seconds, rounded to the millisecond."""
    total = max(round(float(seconds) * MILLISECONDS_PER_SECOND), 0)
    hours, rest = divmod(total, MILLISECONDS_PER_HOUR)
    minutes, rest = divmod(rest, MILLISECONDS_PER_MINUTE)
    whole, millis = divmod(rest, MILLISECONDS_PER_SECOND)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def to_srt(segments: Sequence[Mapping[str, Any]]) -> str:
    """One numbered cue per segment, timestamped, blank line separated."""
    blocks = [
        f"{number}\n{format_timestamp(segment['start_s'])} --> "
        f"{format_timestamp(segment['end_s'])}\n{str(segment['text']).strip()}\n"
        for number, segment in enumerate(segments, start=1)
    ]
    return "\n".join(blocks)


def to_json(
    language: str,
    language_probability: float,
    duration_s: float,
    segments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The sidecar: the detected language, the audio's duration, every segment."""
    return {
        "language": language,
        "language_probability": round(float(language_probability), PROBABILITY_DECIMALS),
        "duration_s": round(float(duration_s), TIMESTAMP_DECIMALS),
        "segments": [_segment(segment) for segment in segments],
    }


def _segment(segment: Mapping[str, Any]) -> dict[str, Any]:
    """One segment with its words, both rounded, in a fixed key order."""
    words = segment.get("words") or []
    return {
        "start_s": round(float(segment["start_s"]), TIMESTAMP_DECIMALS),
        "end_s": round(float(segment["end_s"]), TIMESTAMP_DECIMALS),
        "text": str(segment["text"]).strip(),
        "avg_logprob": round(float(segment["avg_logprob"]), PROBABILITY_DECIMALS),
        "no_speech_prob": round(float(segment["no_speech_prob"]), PROBABILITY_DECIMALS),
        "words": [_word(word) for word in words],
    }


def _word(word: Mapping[str, Any]) -> dict[str, Any]:
    """One timed word; the model's leading space is dropped."""
    return {
        "start_s": round(float(word["start_s"]), TIMESTAMP_DECIMALS),
        "end_s": round(float(word["end_s"]), TIMESTAMP_DECIMALS),
        "word": str(word["word"]).strip(),
        "probability": round(float(word["probability"]), PROBABILITY_DECIMALS),
    }
