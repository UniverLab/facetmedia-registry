"""Probe an MP4/MOV container for dimensions and duration.

Reads ISO-BMFF boxes without decoding media: ``tkhd`` carries width and
height as 16.16 fixed-point values and ``mvhd`` carries duration in the
movie timescale. The ``moov`` box may appear after ``mdat``, so the scan
walks top-level boxes in order and skips large media payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

#: A vertical video no longer than this is treated as a Short.
SHORTS_MAX_S = 180

HEADER_SIZE = 8
LARGE_HEADER_SIZE = 16
FULL_BOX_MIN = 4
MVHD_V0_MIN = 20
MVHD_V1_MIN = 32
MVHD_READ_SIZE = 32
TKHD_V0_MIN = 84
TKHD_V1_MIN = 96
TKHD_READ_SIZE = 96
FIXED_POINT_SHIFT = 16


@dataclass(frozen=True)
class VideoInfo:
    """The probed video geometry and duration."""

    width: int
    height: int
    duration_s: float


def probe(path: str | Path) -> VideoInfo | None:
    """Return ``VideoInfo`` for ``path``, or ``None`` on any read/parse error."""
    try:
        with Path(path).open("rb") as handle:
            width, height, duration_s = _scan(handle)
        if width <= 0 or height <= 0 or duration_s is None:
            return None
        return VideoInfo(width=width, height=height, duration_s=float(duration_s))
    except Exception:
        return None


def _read_box_header(handle: BinaryIO, offset: int, end: int) -> tuple[bytes, int, int] | None:
    if offset + HEADER_SIZE > end:
        return None
    handle.seek(offset)
    header = handle.read(HEADER_SIZE)
    if len(header) < HEADER_SIZE:
        return None
    box_size = int.from_bytes(header[:4], "big")
    box_type = header[4:8]
    header_len = HEADER_SIZE
    if box_size == 1:
        ext = handle.read(HEADER_SIZE)
        if len(ext) < HEADER_SIZE:
            return None
        box_size = int.from_bytes(ext, "big")
        header_len = LARGE_HEADER_SIZE
    elif box_size == 0:
        box_size = end - offset
    if box_size < header_len or offset + box_size > end:
        return None
    return box_type, offset + header_len, box_size - header_len


def _scan(handle: BinaryIO) -> tuple[int, int, float | None]:
    width = 0
    height = 0
    duration_s: float | None = None
    size = _file_size(handle)
    offset = 0
    while offset + HEADER_SIZE <= size:
        parsed = _read_box_header(handle, offset, size)
        if parsed is None:
            break
        box_type, payload, payload_size = parsed
        if box_type == b"moov":
            w, h, d = _scan_moov(handle, payload, payload_size)
            if w:
                width = w
            if h:
                height = h
            if d is not None:
                duration_s = d
            if width and height and duration_s is not None:
                return width, height, duration_s
        offset = payload + payload_size
    return width, height, duration_s


def _scan_moov(handle: BinaryIO, start: int, size: int) -> tuple[int, int, float | None]:
    width = 0
    height = 0
    duration_s: float | None = None
    end = start + size
    offset = start
    while offset + HEADER_SIZE <= end:
        parsed = _read_box_header(handle, offset, end)
        if parsed is None:
            break
        box_type, payload, payload_size = parsed
        if box_type == b"mvhd":
            duration_s = _read_mvhd(handle, payload, payload_size)
        elif box_type == b"trak":
            w, h = _scan_trak(handle, payload, payload_size)
            if w and h:
                width, height = w, h
        offset = payload + payload_size
    return width, height, duration_s


def _scan_trak(handle: BinaryIO, start: int, size: int) -> tuple[int, int]:
    width = 0
    height = 0
    end = start + size
    offset = start
    while offset + HEADER_SIZE <= end:
        parsed = _read_box_header(handle, offset, end)
        if parsed is None:
            break
        box_type, payload, payload_size = parsed
        if box_type == b"tkhd":
            w, h = _read_tkhd(handle, payload, payload_size)
            if w and h:
                width, height = w, h
        offset = payload + payload_size
    return width, height


def _read_mvhd(handle: BinaryIO, payload: int, size: int) -> float | None:
    if size < FULL_BOX_MIN:
        return None
    handle.seek(payload)
    data = handle.read(min(size, MVHD_READ_SIZE))
    if len(data) < FULL_BOX_MIN:
        return None
    version = data[0]
    if version == 1:
        if len(data) < MVHD_V1_MIN:
            return None
        timescale = int.from_bytes(data[20:24], "big")
        duration = int.from_bytes(data[24:32], "big")
    else:
        if len(data) < MVHD_V0_MIN:
            return None
        timescale = int.from_bytes(data[12:16], "big")
        duration = int.from_bytes(data[16:20], "big")
    if timescale <= 0:
        return None
    return duration / timescale


def _read_tkhd(handle: BinaryIO, payload: int, size: int) -> tuple[int, int]:
    if size < FULL_BOX_MIN:
        return 0, 0
    handle.seek(payload)
    data = handle.read(min(size, TKHD_READ_SIZE))
    if len(data) < FULL_BOX_MIN:
        return 0, 0
    version = data[0]
    if version == 1:
        if len(data) < TKHD_V1_MIN:
            return 0, 0
        width = int.from_bytes(data[88:92], "big") >> FIXED_POINT_SHIFT
        height = int.from_bytes(data[92:96], "big") >> FIXED_POINT_SHIFT
    else:
        if len(data) < TKHD_V0_MIN:
            return 0, 0
        width = int.from_bytes(data[76:80], "big") >> FIXED_POINT_SHIFT
        height = int.from_bytes(data[80:84], "big") >> FIXED_POINT_SHIFT
    if width < 0 or height < 0:
        return 0, 0
    return int(width), int(height)


def _file_size(handle: BinaryIO) -> int:
    handle.seek(0, 2)
    size = handle.tell()
    handle.seek(0)
    return size
