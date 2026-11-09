"""Pure sidecar reader and SRT/VTT writers for the whisper-subs package.

Stdlib only, so the tests import this module without the package
environment and no model is ever needed. The input is a whisper JSON
sidecar — ``segments`` carrying ``start_s``/``end_s``/``text`` — read and
validated in order: every cue must end after it starts and start at or
after the previous cue ends (touching boundaries allowed; overlaps and
regressions are rejected, each naming its 1-based cue). ``to_srt`` and
``to_vtt`` render the same cues, and ``parse_timings`` reads a rendered
file back for ``verify``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any

#: Time units a timestamp is built from.
MILLISECONDS_PER_SECOND = 1000
MILLISECONDS_PER_MINUTE = 60 * MILLISECONDS_PER_SECOND
MILLISECONDS_PER_HOUR = 60 * MILLISECONDS_PER_MINUTE
#: One timestamp's digits: ``HH:MM:SS[.,]mmm``.
TIMESTAMP_FIELDS = r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})"
#: One cue's timing line: a start stamp, the arrow, an end stamp.
TIMESTAMP_PAIR = re.compile(rf"{TIMESTAMP_FIELDS}\s*-->\s*{TIMESTAMP_FIELDS}")


@dataclass(frozen=True)
class Cue:
    """One sidecar segment: the seconds it starts and ends at, and its text."""

    start_s: float
    end_s: float
    text: str


def format_timestamp(seconds: float, sep: str = ",") -> str:
    """``HH:MM:SS{sep}mmm`` for one offset in seconds, rounded to the ms."""
    total = max(round(float(seconds) * MILLISECONDS_PER_SECOND), 0)
    hours, rest = divmod(total, MILLISECONDS_PER_HOUR)
    minutes, rest = divmod(rest, MILLISECONDS_PER_MINUTE)
    whole, millis = divmod(rest, MILLISECONDS_PER_SECOND)
    return f"{hours:02d}:{minutes:02d}:{whole:02d}{sep}{millis:03d}"


def read_sidecar(path: Path) -> list[Cue]:
    """The whisper sidecar at ``path`` as cues, every timing validated.

    The sidecar must be a JSON object with a non-empty ``segments`` list;
    each segment carries its ``start_s``, its ``end_s`` and its ``text``.
    A malformed value is a ``ValueError`` naming the 1-based cue.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name}: the sidecar is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: the sidecar is not a JSON object")
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError(f"{path.name}: the sidecar carries no segments")
    return [_cue(segment, index) for index, segment in enumerate(segments, start=1)]


def _cue(segment: Any, index: int) -> Cue:
    """One sidecar segment as a ``Cue``, its timing checked in place."""
    if not isinstance(segment, dict):
        raise ValueError(f"cue {index}: not a JSON object")
    start = _seconds(segment, "start_s", index)
    end = _seconds(segment, "end_s", index)
    if start >= end:
        raise ValueError(f"cue {index}: start_s {start} must be below end_s {end}")
    return Cue(start, end, str(segment.get("text", "")).strip())


def _seconds(segment: dict[str, Any], key: str, index: int) -> float:
    """One timing field: a real number — a bool is not a number here."""
    value = segment.get(key)
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"cue {index}: {key} must be a number")
    return float(value)


def validate_cues(cues: Sequence[Cue]) -> None:
    """The cues must run in order: no overlap, no regression.

    A cue starts at or after the previous one ends — cue boundaries that
    touch are allowed — else a ``ValueError`` names both cues.
    """
    previous: Cue | None = None
    for index, cue in enumerate(cues, start=1):
        if previous is not None and cue.start_s < previous.end_s:
            raise ValueError(f"cue {index}: starts before cue {index - 1} ends")
        previous = cue


def _blocks(cues: Sequence[Cue], sep: str, numbered: bool) -> list[str]:
    """One rendering block per cue: each ends its line, blank-line apart."""
    blocks = []
    for number, cue in enumerate(cues, start=1):
        stamp = f"{format_timestamp(cue.start_s, sep)} --> {format_timestamp(cue.end_s, sep)}"
        identifier = f"{number}\n" if numbered else ""
        blocks.append(f"{identifier}{stamp}\n{cue.text}\n")
    return blocks


def to_srt(cues: Sequence[Cue]) -> str:
    """SubRip: numbered cues with comma times, joined by a blank, one ``\\n``."""
    if not cues:
        return ""
    return "\n".join(_blocks(cues, sep=",", numbered=True))


def to_vtt(cues: Sequence[Cue]) -> str:
    """WebVTT: the header, then unnumbered cues with dot times."""
    return "WEBVTT\n\n" + "\n".join(_blocks(cues, sep=".", numbered=False))


def parse_timings(subtitles: str) -> list[tuple[int, int]]:
    """Every cue's ``(start_ms, end_ms)`` read back from a rendered file.

    SRT and VTT share the arrow line, and ``[.,]`` accepts both their
    thousandths separators; a file with no arrow line parses to no cues.
    """
    return [
        (
            _milliseconds(*match.group(1, 2, 3, 4)),
            _milliseconds(*match.group(5, 6, 7, 8)),
        )
        for match in TIMESTAMP_PAIR.finditer(subtitles)
    ]


def _milliseconds(hours: str, minutes: str, seconds: str, millis: str) -> int:
    """One ``HH:MM:SS.mmm`` stamp's total milliseconds."""
    return (
        int(hours) * MILLISECONDS_PER_HOUR
        + int(minutes) * MILLISECONDS_PER_MINUTE
        + int(seconds) * MILLISECONDS_PER_SECOND
        + int(millis)
    )
