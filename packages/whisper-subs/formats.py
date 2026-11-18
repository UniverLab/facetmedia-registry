"""Pure sidecar reader, readability shaper and SRT/VTT writers.

Stdlib only, so the tests import this module without the package
environment and no model is ever needed. The input is a whisper JSON
sidecar — ``segments`` carrying ``start_s``/``end_s``/``text`` plus the
word timings whisper always writes — read and validated in order: every
cue must end after it starts and start at or after the previous cue ends
(touching boundaries allowed; overlaps and regressions are rejected, each
naming its 1-based cue). ``shape_cues`` splits long segments, merges very
short contiguous ones and wraps text into lines; ``to_srt`` and ``to_vtt``
render the shaped cues, and ``parse_blocks`` reads a rendered file back
for ``verify``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any, NamedTuple

#: Time units a timestamp is built from.
MILLISECONDS_PER_SECOND = 1000
MILLISECONDS_PER_MINUTE = 60 * MILLISECONDS_PER_SECOND
MILLISECONDS_PER_HOUR = 60 * MILLISECONDS_PER_MINUTE
#: One timestamp's digits: ``HH:MM:SS[.,]mmm``.
TIMESTAMP_FIELDS = r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})"
#: One cue's timing line: a start stamp, the arrow, an end stamp.
TIMESTAMP_PAIR = re.compile(rf"{TIMESTAMP_FIELDS}\s*-->\s*{TIMESTAMP_FIELDS}")


@dataclass(frozen=True)
class Word:
    """One timed word: its text and the seconds it starts and ends at."""

    text: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class Cue:
    """One sidecar segment: the seconds it starts and ends at, and its text."""

    start_s: float
    end_s: float
    text: str
    words: tuple[Word, ...] = ()


@dataclass(frozen=True)
class Limits:
    """The readability limits a shaped cue must meet where speech allows."""

    max_cps: float = 20.0
    max_line_chars: int = 42
    max_lines: int = 2
    min_cue_s: float = 0.8
    max_cue_s: float = 7.0


class Block(NamedTuple):
    """One rendered cue read back: its ms bounds, text lines, longest line."""

    start_ms: int
    end_ms: int
    lines: tuple[str, ...]
    chars: int


#: Two cues merge only when the silence between them is at most this long.
MERGE_MAX_GAP_S = 0.25


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
    return Cue(start, end, str(segment.get("text", "")).strip(), _words(segment))


def _words(segment: dict[str, Any]) -> tuple[Word, ...]:
    """The segment's timed words; a segment without any shapes as one cue."""
    raw = segment.get("words") or []
    if not isinstance(raw, list):
        return ()
    timed = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        start = entry.get("start_s")
        end = entry.get("end_s")
        if isinstance(start, bool) or isinstance(end, bool):
            continue
        if not isinstance(start, Real) or not isinstance(end, Real):
            continue
        if float(start) >= float(end):
            continue
        timed.append(Word(str(entry.get("word", "")).strip(), float(start), float(end)))
    return tuple(timed)


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


def _wrap(text: str, max_line_chars: int) -> list[str]:
    """Greedy word-boundary lines; an overlong word stays whole on its line."""
    pieces = text.split()
    if not pieces:
        return [""]
    lines = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 1 + len(piece) <= max_line_chars:
            current += " " + piece
        else:
            lines.append(current)
            current = piece
    lines.append(current)
    return lines


def _piece_text(words: Sequence[Word]) -> str:
    """The subtitle text for a run of words, single-spaced."""
    return " ".join(word.text for word in words)


def _piece_violates(text: str, start_s: float, end_s: float, limits: Limits) -> bool:
    """A piece still over duration, reading speed or line count."""
    duration = end_s - start_s
    if duration > limits.max_cue_s:
        return True
    if duration > 0 and len(text) / duration > limits.max_cps:
        return True
    return len(_wrap(text, limits.max_line_chars)) > limits.max_lines


def _split_at(words: list[Word]) -> int:
    """The word boundary to cut at: the widest silence, middle one on ties."""
    pairs = zip(words, words[1:], strict=False)
    gaps = [round((later.start_s - first.end_s) * 1000) for first, later in pairs]
    widest = max(gaps)
    cuts = [index + 1 for index, gap in enumerate(gaps) if gap == widest]
    middle = len(words) / 2
    return min(cuts, key=lambda cut: (abs(cut - middle), cut))


def _split(cue: Cue, limits: Limits) -> list[Cue]:
    """A word-timed cue cut at word boundaries until each piece fits.

    A cue without word timings stays whole: there is no boundary to cut
    at, so it is kept as one cue and judged like any other.
    """
    if len(cue.words) <= 1:
        return [cue]
    pieces = [list(cue.words)]
    index = 0
    while index < len(pieces):
        piece = pieces[index]
        start = cue.start_s if index == 0 else piece[0].start_s
        end = cue.end_s if index == len(pieces) - 1 else piece[-1].end_s
        if len(piece) > 1 and _piece_violates(_piece_text(piece), start, end, limits):
            cut = _split_at(piece)
            pieces[index : index + 1] = [piece[:cut], piece[cut:]]
        else:
            index += 1
    return _pieces(cue, pieces)


def _pieces(cue: Cue, pieces: list[list[Word]]) -> list[Cue]:
    """Split pieces as cues: edges keep the segment's bounds, never backward."""
    total = len(pieces)
    timed = []
    for position, piece in enumerate(pieces):
        start = cue.start_s if position == 0 else piece[0].start_s
        edge = cue.end_s if position == total - 1 else piece[-1].end_s
        if timed:
            start = max(start, timed[-1].end_s)
        timed.append(Cue(start, max(start, edge), _piece_text(piece), tuple(piece)))
    return timed


def _mergeable(first: Cue, second: Cue, limits: Limits) -> bool:
    """A short cue joins its neighbour only across touching speech."""
    gap = second.start_s - first.end_s
    if gap < 0 or gap > MERGE_MAX_GAP_S:
        return False
    if first.end_s - first.start_s >= limits.min_cue_s:
        return False
    joined = f"{first.text} {second.text}".strip()
    if second.end_s - first.start_s > limits.max_cue_s:
        return False
    return len(_wrap(joined, limits.max_line_chars)) <= limits.max_lines


def _merge(first: Cue, second: Cue) -> Cue:
    """Two contiguous cues as one, the words carried along in order."""
    return Cue(
        first.start_s,
        second.end_s,
        f"{first.text} {second.text}".strip(),
        (*first.words, *second.words),
    )


def shape_cues(cues: Sequence[Cue], limits: Limits | None = None) -> list[Cue]:
    """The cues reshaped for reading: split long, merged short, wrapped.

    Word-timed segments split at word boundaries until each piece meets
    the limits where the speech allows; a segment without word timings is
    kept as one cue. Very short cues merge into the following contiguous
    cue — never across a silence gap. Every cue's text is wrapped into
    lines.
    """
    active = limits if limits is not None else Limits()
    split: list[Cue] = []
    for cue in cues:
        split.extend(_split(cue, active))
    merged = split
    changed = True
    while changed:
        changed = False
        forward: list[Cue] = []
        index = 0
        while index < len(merged):
            cue = merged[index]
            following = merged[index + 1] if index + 1 < len(merged) else None
            if following is not None and _mergeable(cue, following, active):
                forward.append(_merge(cue, following))
                index += 2
                changed = True
            else:
                forward.append(cue)
                index += 1
        merged = forward
    return [
        Cue(cue.start_s, cue.end_s, "\n".join(_wrap(cue.text, active.max_line_chars)), cue.words)
        for cue in merged
    ]


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


def parse_blocks(subtitles: str) -> list[Block]:
    """Every cue read back from a rendered file with its text lines.

    SRT and VTT share the arrow line, and ``[.,]`` accepts both their
    thousandths separators; a file with no arrow line parses to no cues.
    Each block carries its ms bounds, its text lines and the longest
    line's length, which is what ``verify`` judges readability from.
    """
    matches = list(TIMESTAMP_PAIR.finditer(subtitles))
    blocks = []
    for position, match in enumerate(matches):
        stop = matches[position + 1].start() if position + 1 < len(matches) else len(subtitles)
        lines = _block_lines(subtitles, match.end(), stop)
        longest = max((len(line) for line in lines), default=0)
        blocks.append(
            Block(
                _milliseconds(*match.group(1, 2, 3, 4)),
                _milliseconds(*match.group(5, 6, 7, 8)),
                tuple(lines),
                longest,
            )
        )
    return blocks


def _block_lines(subtitles: str, timing_end: int, stop: int) -> list[str]:
    """The text lines after one timing line, up to a blank line or stop."""
    newline = subtitles.find("\n", timing_end, stop)
    rest = subtitles[newline + 1 : stop] if newline != -1 else ""
    lines = []
    for line in rest.splitlines():
        if not line.strip():
            break
        lines.append(line.strip())
    return lines


def parse_timings(subtitles: str) -> list[tuple[int, int]]:
    """Every cue's ``(start_ms, end_ms)`` read back from a rendered file.

    SRT and VTT share the arrow line, and ``[.,]`` accepts both their
    thousandths separators; a file with no arrow line parses to no cues.
    """
    return [(block.start_ms, block.end_ms) for block in parse_blocks(subtitles)]


def _milliseconds(hours: str, minutes: str, seconds: str, millis: str) -> int:
    """One ``HH:MM:SS.mmm`` stamp's total milliseconds."""
    return (
        int(hours) * MILLISECONDS_PER_HOUR
        + int(minutes) * MILLISECONDS_PER_MINUTE
        + int(seconds) * MILLISECONDS_PER_SECOND
        + int(millis)
    )
