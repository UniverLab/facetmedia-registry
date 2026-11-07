"""The MP4 probe: width, height, frames and fps from a clip's own boxes.

``verify`` must read an MP4 on a host that ships no Python environment, so
this module is the standard library alone — no ffprobe, no imageio-ffmpeg, no
third-party package at all. It walks just the ISO BMFF boxes it needs:

- ``ftyp`` proves the file is an MP4 at all;
- ``moov/mvhd`` carries the movie timescale and duration;
- ``avc1`` (or ``hvc1``) inside the sample description carries the size;
- ``stts`` sums to the frame count.

No frame is decoded: the probe reads the file's bytes once and walks only the
boxes it needs, so a 10 s clip is a short scan rather than a full decode.
"""

from __future__ import annotations

import posixpath

#: ``ftyp`` at offset 4, the box every ISO BMFF file starts with.
FTYP_OFFSET = 4
FTYP = b"ftyp"
#: A box header is a 32-bit size plus a four-character type.
BOX_HEADER_BYTES = 8
#: A full box's version byte and flags, before the count a sample table lists.
STD_FULL_BOX_BYTES = 8
#: A 32-bit box size of 1 means a 64-bit size follows the header.
EXTENDED_SIZE = 1
#: A visual sample entry's fields sit this far into its body.
ENTRY_FIELDS_OFFSET = 24
#: What the probe says about a file whose signature is not an MP4.
NO_MP4 = "not an MP4 (no ftyp box)"


def probe(value: str) -> dict[str, int]:
    """An MP4's width, height, frames and fps, from its boxes alone."""
    with open(value, "rb") as handle:
        data = handle.read()
    if len(data) < BOX_HEADER_BYTES or data[FTYP_OFFSET : FTYP_OFFSET + len(FTYP)] != FTYP:
        raise ValueError(f"{posixpath.basename(value)}: {NO_MP4}")
    moov = find_box(data, 0, len(data), b"moov")
    if moov is None:
        raise ValueError(f"{posixpath.basename(value)}: no moov box")
    timescale, duration = movie_timing(data, moov[0], moov[1])
    width, height = picture_size(data, moov[0], moov[1])
    frames = frame_count(data, moov[0], moov[1])
    fps = round(timescale / duration * frames) if duration else 0
    return {"width": width, "height": height, "frames": frames, "fps": fps}


def box_extent(data: bytes, position: int) -> tuple[bytes, int, int]:
    """One box's ``(kind, body_start, body_end)`` at ``position``."""
    size = int.from_bytes(data[position : position + 4], "big")
    kind = data[position + 4 : position + 8]
    body = position + BOX_HEADER_BYTES
    if size == EXTENDED_SIZE:
        size = int.from_bytes(data[body : body + 8], "big")
        body += 8
    return kind, body, position + size


def field(data: bytes, position: int, size: int, end: int) -> int:
    """An unsigned big-endian field, refused when it would run past its box.

    A truncated or lying file must come back as a ``ValueError`` the verdict
    can report, never as an ``IndexError`` escaping the caller.
    """
    if position < 0 or size < 0 or end > len(data) or position + size > end:
        raise ValueError("box body too short")
    return int.from_bytes(data[position : position + size], "big")


def find_box(data: bytes, start: int, end: int, kind: bytes) -> tuple[int, int] | None:
    """``(body_start, body_end)`` of the first box of ``kind`` in a range."""
    position = start
    limit = min(end, len(data))
    while position + BOX_HEADER_BYTES <= limit:
        found, body, box_end = box_extent(data, position)
        if box_end > end or box_end <= position:
            return None
        if found == kind:
            return body, box_end
        position = box_end
    return None


def descend(data: bytes, start: int, end: int, path: tuple[bytes, ...]) -> tuple[int, int] | None:
    """Walk a chain of container boxes from ``start``; ``None`` if any is absent."""
    span: tuple[int, int] | None = (start, end)
    for kind in path:
        if span is None:
            return None
        span = find_box(data, span[0], span[1], kind)
    return span


def movie_timing(data: bytes, start: int, end: int) -> tuple[int, int]:
    """The movie's timescale and duration in ticks."""
    mvhd = find_box(data, start, end, b"mvhd")
    if mvhd is None:
        raise ValueError("no mvhd box")
    body, limit = mvhd
    # Version 0 puts timescale at +12 and duration at +16; version 1 widens both.
    if field(data, body, 1, limit) == 1:
        timescale = field(data, body + 20, 4, limit)
        duration = field(data, body + 24, 8, limit)
    else:
        timescale = field(data, body + 12, 4, limit)
        duration = field(data, body + 16, 4, limit)
    return timescale, duration


def picture_size(data: bytes, start: int, end: int) -> tuple[int, int]:
    """The visual sample entry's width and height, from ``avc1`` (or ``hvc1``)."""
    stbl = descend(data, start, end, (b"trak", b"mdia", b"minf", b"stbl"))
    stsd = None if stbl is None else find_box(data, stbl[0], stbl[1], b"stsd")
    if stsd is None:
        raise ValueError("no stsd box")
    # ``stsd`` is a full box: 4 version/flag bytes then the entry count, so its
    # sample entries start 8 bytes into the body.
    for kind in (b"avc1", b"hvc1"):
        box = find_box(data, stsd[0] + STD_FULL_BOX_BYTES, stsd[1], kind)
        if box is not None:
            body, limit = box
            width = field(data, body + ENTRY_FIELDS_OFFSET, 2, limit)
            height = field(data, body + ENTRY_FIELDS_OFFSET + 2, 2, limit)
            return width, height
    raise ValueError("no avc1 sample description")


def frame_count(data: bytes, start: int, end: int) -> int:
    """The number of samples ``stts`` lists, which is the frame count."""
    box = descend(data, start, end, (b"trak", b"mdia", b"minf", b"stbl", b"stts"))
    if box is None:
        raise ValueError("no stts box")
    body, limit = box
    count = field(data, body + 4, 4, limit)
    position = body + STD_FULL_BOX_BYTES
    # Each entry is a sample count and a delta: 8 bytes. A file that claims
    # more entries than fit is refused instead of walking past its own end.
    if count * STD_FULL_BOX_BYTES > limit - position:
        raise ValueError("stts entry count exceeds the box")
    total = 0
    for _ in range(count):
        total += field(data, position, 4, limit)
        position += STD_FULL_BOX_BYTES
    return total
