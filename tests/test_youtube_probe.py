"""Video probe: ISO-BMFF mvhd/tkhd parsing without decoding."""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "youtube"


def _load_probe():
    spec = importlib.util.spec_from_file_location("youtube_video_meta", PACKAGE / "video_meta.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["youtube_video_meta"] = module
    spec.loader.exec_module(module)
    return module


probe_mod = _load_probe()


def box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def mvhd_v0(timescale: int, duration: int) -> bytes:
    data = bytearray(96)
    data[0] = 0
    struct.pack_into(">I", data, 12, timescale)
    struct.pack_into(">I", data, 16, duration)
    return bytes(data)


def mvhd_v1(timescale: int, duration: int) -> bytes:
    data = bytearray(108)
    data[0] = 1
    struct.pack_into(">I", data, 20, timescale)
    struct.pack_into(">Q", data, 24, duration)
    return bytes(data)


def tkhd_v0(width: int, height: int) -> bytes:
    data = bytearray(84)
    data[0] = 0
    struct.pack_into(">I", data, 76, width << 16)
    struct.pack_into(">I", data, 80, height << 16)
    return bytes(data)


def tkhd_v1(width: int, height: int) -> bytes:
    data = bytearray(96)
    data[0] = 1
    struct.pack_into(">I", data, 88, width << 16)
    struct.pack_into(">I", data, 92, height << 16)
    return bytes(data)


def make_mp4(mvhd: bytes, tkhd: bytes, moov_after_mdat: bool = False) -> bytes:
    trak = box(b"trak", box(b"tkhd", tkhd))
    moov = box(b"moov", box(b"mvhd", mvhd) + trak)
    ftyp = box(b"ftyp", b"isom" + b"\x00\x00\x00\x00" + b"isom")
    if moov_after_mdat:
        mdat = box(b"mdat", b"\x00" * 64)
        return ftyp + mdat + moov
    return ftyp + moov


def test_probe_reads_mvhd_v0_and_tkhd(tmp_path: Path) -> None:
    path = tmp_path / "v0.mp4"
    width, height = 1920, 1080
    duration_s = 5.0
    path.write_bytes(make_mp4(mvhd_v0(1000, 5000), tkhd_v0(width, height)))
    info = probe_mod.probe(path)
    assert info is not None
    assert info.width == width
    assert info.height == height
    assert info.duration_s == duration_s


def test_probe_reads_mvhd_v1_and_tkhd_v1(tmp_path: Path) -> None:
    path = tmp_path / "v1.mp4"
    width, height = 1080, 1920
    duration_s = 2.0
    path.write_bytes(make_mp4(mvhd_v1(48000, 96000), tkhd_v1(width, height)))
    info = probe_mod.probe(path)
    assert info is not None
    assert info.width == width
    assert info.height == height
    assert info.duration_s == duration_s


def test_probe_finds_moov_after_mdat(tmp_path: Path) -> None:
    path = tmp_path / "late.mp4"
    width, height = 720, 1280
    duration_s = 3.0
    path.write_bytes(make_mp4(mvhd_v0(30, 90), tkhd_v0(width, height), moov_after_mdat=True))
    info = probe_mod.probe(path)
    assert info is not None
    assert info.width == width
    assert info.height == height
    assert info.duration_s == duration_s


def test_probe_returns_none_on_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not an mp4 at all")
    assert probe_mod.probe(bad) is None
    assert probe_mod.probe(tmp_path / "missing.mp4") is None
    assert probe_mod.SHORTS_MAX_S == 3 * 60
