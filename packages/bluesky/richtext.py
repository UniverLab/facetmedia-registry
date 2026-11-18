"""Rich-text facets for a Bluesky post: links, mentions and hashtags.

A facet marks a UTF-8 byte range of the post's text and the feature that
makes it clickable. URLs match inline, hashtags match inline, and mentions
resolve to DIDs through the directory service — a mention that does not
resolve stays plain text, so a mistyped handle never fails the send.
Grapheme counting follows the network's 300-grapheme limit closely enough
to warn: base plus combining marks, ZWJ-joined emoji and regional-indicator
pairs each count as one.

Requires: stdlib
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Any

#: The network's post-length limit in graphemes.
GRAPHEME_LIMIT = 300

#: Trailing punctuation a URL match never keeps (Bluesky trims the same set).
_URL_TRAIL = ".,;:!?)]}'\""

_URL_RE = re.compile(r"https?://[^\s<>\"]+")
_MENTION_RE = re.compile(r"(?<!\S)@([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)")
_TAG_RE = re.compile(r"(?<!\w)#([^\s!\"#$%&'()*+,\-./:;<=>?@\[\\\]^`{|}~]+)")


def _byte_span(text: str, start: int, end: int) -> tuple[int, int]:
    """The UTF-8 byte offsets of ``text[start:end]``, as facets index them."""
    encoded = text.encode("utf-8")
    return len(text[:start].encode("utf-8")), len(encoded) - len(text[end:].encode("utf-8"))


def _is_regional_indicator(char: str) -> bool:
    return "\U0001f1e6" <= char <= "\U0001f1ff"


def _is_extend(char: str) -> bool:
    return (
        unicodedata.combining(char) != 0
        or unicodedata.category(char) in {"Me", "Mn"}
        or char == "\ufe0f"
    )


def grapheme_count(text: str) -> int:
    """User-perceived characters: ZWJ runs, flag pairs and marks count once."""
    count = 0
    position = 0
    while position < len(text):
        char = text[position]
        if _is_regional_indicator(char) and position + 1 < len(text):
            following = text[position + 1]
            if _is_regional_indicator(following):
                position += 2
                count += 1
                continue
        position += 1
        while position < len(text) and _is_extend(text[position]):
            position += 1
        while position + 1 < len(text) and text[position] == "\u200d":
            position += 2
            while position < len(text) and _is_extend(text[position]):
                position += 1
        if position < len(text) and text[position] == "\u20e3":
            position += 1
        count += 1
    return count


def _spans_overlap(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < stop and begin < end for begin, stop in spans)


def find_spans(text: str) -> dict[str, list[tuple[int, int, str]]]:
    """The link, mention and tag spans of ``text``; links win overlaps."""
    links: list[tuple[int, int, str]] = []
    for match in _URL_RE.finditer(text):
        uri = match.group(0).rstrip(_URL_TRAIL)
        if uri:
            links.append((match.start(), match.start() + len(uri), uri))
    taken = [(start, end) for start, end, _ in links]
    mentions: list[tuple[int, int, str]] = []
    for match in _MENTION_RE.finditer(text):
        start, end = match.start(), match.end()
        if not _spans_overlap(start, end, taken):
            mentions.append((start, end, match.group(1)))
            taken.append((start, end))
    tags: list[tuple[int, int, str]] = []
    for match in _TAG_RE.finditer(text):
        start, end = match.start(), match.end()
        if not _spans_overlap(start, end, taken):
            tags.append((start, end, match.group(1).rstrip(_URL_TRAIL)))
            taken.append((start, end))
    return {"links": links, "mentions": mentions, "tags": tags}


def facets_for(
    text: str, resolve: Callable[[str], str | None] | None = None
) -> list[dict[str, Any]]:
    """The AT Protocol facets of ``text``; unresolvable mentions stay plain."""
    spans = find_spans(text)
    facets: list[dict[str, Any]] = []
    for start, end, uri in spans["links"]:
        byte_start, byte_end = _byte_span(text, start, end)
        facets.append(
            {
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": uri}],
            }
        )
    for start, end, handle in spans["mentions"]:
        if resolve is None:
            continue
        try:
            did = resolve(handle)
        except Exception:
            did = None
        if not did:
            continue
        byte_start, byte_end = _byte_span(text, start, end)
        facets.append(
            {
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [{"$type": "app.bsky.richtext.facet#mention", "did": did}],
            }
        )
    for start, end, tag in spans["tags"]:
        if not tag:
            continue
        byte_start, byte_end = _byte_span(text, start, end)
        facets.append(
            {
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}],
            }
        )
    facets.sort(key=lambda facet: facet["index"]["byteStart"])
    return facets
