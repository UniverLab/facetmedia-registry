"""The video-ops manifest, its index entry, and the six capability schemas."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "video-ops"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITIES = MANIFEST["capabilities"]
RAM_GB = 2
DISK_GB = 0.5
SUMMARY_LIMIT = 200
DEFAULT_CRF = 24
DEFAULT_CRF_23 = 23
MIN_CRF = 14
MAX_CRF = 38
MIN_WIDTH = 240
MAX_WIDTH = 3840
MAX_HEIGHT = 2160
MIN_FPS = 1
MAX_FPS = 60
CONCAT_MIN_FPS = 12
CONCAT_MAX_FPS = 60
CONCAT_DEFAULT_FPS = 30
DEFAULT_AUDIO_KBPS = 128
MIN_AUDIO_KBPS = 64
MAX_AUDIO_KBPS = 320
DEFAULT_AT_S = 0.0
MIN_CLIP_ITEMS = 2
DEFAULT_TRANSITION_S = 0.5
MIN_TRANSITION_S = 0.1
MAX_TRANSITION_S = 3.0
DEFAULT_FONT_SIZE = 22
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 72
DEFAULT_MARGIN_V = 36
MIN_MARGIN_V = 0
MAX_MARGIN_V = 300


def test_package_metadata_and_requirements() -> None:
    assert MANIFEST["name"] == "video-ops"
    assert MANIFEST["version"] == "0.2.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "video"
    assert MANIFEST["provider"] == "FFmpeg project · imageio (imageio-ffmpeg)"
    assert MANIFEST["tool_name"] == "FFmpeg Video Ops"
    assert (
        MANIFEST["description"]
        == "Deterministic CPU video editing with bundled FFmpeg: H.264/AAC transcode, "
        "audio muxing, frame extraction, xfade/acrossfade concat transitions, "
        "libass subtitle burning, and eq/fade color grading"
    )
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]


def test_licenses_and_pyproject_dependencies() -> None:
    licences = {entry["subject"]: entry["spdx"] for entry in MANIFEST["licenses"]}
    assert licences == {
        "imageio-ffmpeg": "BSD-2-Clause",
        "FFmpeg": "GPL-3.0-or-later",
        "pillow": "MIT-CMU",
    }
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == "0.2.0"
    assert pyproject["project"]["dependencies"] == [
        "imageio-ffmpeg==0.6.0",
        "pillow==13.0.0",
    ]
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_capabilities_kinds_viewers_and_i18n() -> None:
    assert set(CAPABILITIES) == {"transcode", "mux-audio", "frame", "concat", "burn-subs", "grade"}
    assert CAPABILITIES["transcode"]["kind"] == "video"
    assert CAPABILITIES["transcode"]["preview"] == {"viewer": "video"}
    assert CAPABILITIES["mux-audio"]["kind"] == "video"
    assert CAPABILITIES["mux-audio"]["preview"] == {"viewer": "video"}
    assert CAPABILITIES["frame"]["kind"] == "image"
    assert CAPABILITIES["frame"]["preview"] == {"viewer": "image"}
    assert CAPABILITIES["concat"]["kind"] == "video"
    assert CAPABILITIES["concat"]["preview"] == {"viewer": "video"}
    assert CAPABILITIES["burn-subs"]["kind"] == "video"
    assert CAPABILITIES["burn-subs"]["preview"] == {"viewer": "video"}
    assert CAPABILITIES["grade"]["kind"] == "video"
    assert CAPABILITIES["grade"]["preview"] == {"viewer": "video"}
    for cap in CAPABILITIES.values():
        es_summary = cap["i18n"]["es"]["summary"]
        assert isinstance(es_summary, str) and es_summary
        assert len(es_summary) <= SUMMARY_LIMIT


def test_transcode_inputs_schema() -> None:
    inputs = CAPABILITIES["transcode"]["inputs"]
    assert inputs["video"]["type"] == "path"
    assert inputs["video"]["required"] is True
    assert inputs["name"]["type"] == "string"
    assert inputs["name"]["required"] is True
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert inputs["crf"]["default"] == DEFAULT_CRF
    assert (inputs["crf"]["min"], inputs["crf"]["max"]) == (MIN_CRF, MAX_CRF)
    assert (inputs["max-width"]["min"], inputs["max-width"]["max"]) == (MIN_WIDTH, MAX_WIDTH)
    assert (inputs["fps"]["min"], inputs["fps"]["max"]) == (MIN_FPS, MAX_FPS)
    assert inputs["start-s"]["min"] == 0
    assert inputs["end-s"]["min"] == 0
    assert inputs["audio-bitrate-kbps"]["default"] == DEFAULT_AUDIO_KBPS
    assert (inputs["audio-bitrate-kbps"]["min"], inputs["audio-bitrate-kbps"]["max"]) == (
        MIN_AUDIO_KBPS,
        MAX_AUDIO_KBPS,
    )


def test_mux_audio_and_frame_inputs_schema() -> None:
    mux = CAPABILITIES["mux-audio"]["inputs"]
    assert mux["video"]["type"] == "path"
    assert mux["video"]["required"] is True
    assert mux["audio"]["type"] == "path"
    assert mux["audio"]["required"] is True
    assert mux["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert mux["audio-bitrate-kbps"]["default"] == DEFAULT_AUDIO_KBPS

    frame = CAPABILITIES["frame"]["inputs"]
    assert frame["video"]["type"] == "path"
    assert frame["video"]["required"] is True
    assert frame["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert frame["at-s"]["default"] == DEFAULT_AT_S
    assert frame["at-s"]["min"] == 0
    assert frame["format"]["type"] == "enum"
    assert frame["format"]["values"] == ["png", "jpg"]
    assert frame["format"]["default"] == "png"


def test_concat_inputs_schema() -> None:
    inputs = CAPABILITIES["concat"]["inputs"]
    clip = inputs["clip"]
    assert clip["type"] == "array"
    assert clip["min_items"] == MIN_CLIP_ITEMS
    assert clip["required"] is True
    assert clip["items"]["video"]["type"] == "path"
    assert clip["items"]["video"]["required"] is True
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert inputs["transition"]["type"] == "enum"
    assert inputs["transition"]["default"] == "fade"
    assert inputs["transition"]["values"] == [
        "cut",
        "fade",
        "fadeblack",
        "fadewhite",
        "dissolve",
        "wipeleft",
        "wiperight",
        "slideleft",
        "slideright",
        "smoothleft",
        "smoothright",
        "zoomin",
    ]
    assert inputs["transition-s"]["default"] == DEFAULT_TRANSITION_S
    assert (inputs["transition-s"]["min"], inputs["transition-s"]["max"]) == (
        MIN_TRANSITION_S,
        MAX_TRANSITION_S,
    )
    assert (inputs["width"]["min"], inputs["width"]["max"]) == (MIN_WIDTH, MAX_WIDTH)
    assert (inputs["height"]["min"], inputs["height"]["max"]) == (MIN_WIDTH, MAX_HEIGHT)
    assert inputs["fps"]["default"] == CONCAT_DEFAULT_FPS
    assert (inputs["fps"]["min"], inputs["fps"]["max"]) == (CONCAT_MIN_FPS, CONCAT_MAX_FPS)
    assert inputs["crf"]["default"] == DEFAULT_CRF_23
    assert (inputs["crf"]["min"], inputs["crf"]["max"]) == (MIN_CRF, MAX_CRF)


def test_burn_subs_inputs_schema() -> None:
    inputs = CAPABILITIES["burn-subs"]["inputs"]
    assert inputs["video"]["type"] == "path"
    assert inputs["video"]["required"] is True
    assert inputs["subtitles"]["type"] == "path"
    assert inputs["subtitles"]["required"] is True
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert inputs["font-size"]["default"] == DEFAULT_FONT_SIZE
    assert (inputs["font-size"]["min"], inputs["font-size"]["max"]) == (
        MIN_FONT_SIZE,
        MAX_FONT_SIZE,
    )
    assert inputs["margin-v"]["default"] == DEFAULT_MARGIN_V
    assert (inputs["margin-v"]["min"], inputs["margin-v"]["max"]) == (MIN_MARGIN_V, MAX_MARGIN_V)
    assert inputs["crf"]["default"] == DEFAULT_CRF_23


def test_grade_inputs_schema() -> None:
    inputs = CAPABILITIES["grade"]["inputs"]
    assert inputs["video"]["type"] == "path"
    assert inputs["video"]["required"] is True
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert inputs["brightness"]["default"] == 0.0
    assert (inputs["brightness"]["min"], inputs["brightness"]["max"]) == (-1.0, 1.0)
    assert inputs["contrast"]["default"] == 1.0
    assert (inputs["contrast"]["min"], inputs["contrast"]["max"]) == (0.2, 3.0)
    assert inputs["saturation"]["default"] == 1.0
    assert (inputs["saturation"]["min"], inputs["saturation"]["max"]) == (0.0, 3.0)
    assert inputs["gamma"]["default"] == 1.0
    assert (inputs["gamma"]["min"], inputs["gamma"]["max"]) == (0.2, 3.0)
    assert inputs["fade-in-s"]["default"] == 0.0
    assert (inputs["fade-in-s"]["min"], inputs["fade-in-s"]["max"]) == (0.0, 10.0)
    assert inputs["fade-out-s"]["default"] == 0.0
    assert (inputs["fade-out-s"]["min"], inputs["fade-out-s"]["max"]) == (0.0, 10.0)
    assert inputs["crf"]["default"] == DEFAULT_CRF_23


def test_index_and_root_readme_list_video_ops() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert names.index("video-ops") == len(names) - 2
    assert names[-1] == "deepfilter"
    rows = [
        line
        for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| video | video-ops |")
    ]
    assert len(rows) == 1
    assert "concat" in rows[0]
    assert "subtitle" in rows[0].lower() or "subtitles" in rows[0].lower()
    assert "grading" in rows[0].lower() or "grade" in rows[0].lower()
