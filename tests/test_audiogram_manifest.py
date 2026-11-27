"""The audiogram manifest, its index entry and the render schema it declares.

The registry suite runs without the core, so the input contract is
asserted as data: ``facet run`` validates pieces against these fields
before the runner sees them, and the runner's own checks cover what the
schema cannot express (missing audio, bad colors, sub-frame clips). The
package is a CPU python-env with pinned imageio-ffmpeg, NumPy,
soundfile and Pillow, the capability is ``audiogram.render`` of kind
video with the video viewer, and ``index.toml`` is the only way a
package reaches the registry.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "audiogram"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["render"]
INPUTS = CAPABILITY["inputs"]
DISK_GB = 0.3
DEFAULT_FPS = 24
FPS_MIN = 12
FPS_MAX = 30
DEFAULT_CRF = 23
CRF_MIN = 14
CRF_MAX = 38
DEFAULT_BACKGROUND = "#111315"
DEFAULT_ACCENT = "#E8C547"


def test_the_package_is_a_cpu_python_env_for_video() -> None:
    assert MANIFEST["name"] == "audiogram"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "video"
    assert MANIFEST["provider"] == "UniverLab · NumPy + Pillow + FFmpeg"
    assert MANIFEST["tool_name"] == "Audiogram"
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == 1
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert [license_["spdx"] for license_ in MANIFEST["licenses"]] == [
        "BSD-2-Clause",
        "GPL-3.0-or-later",
        "BSD-3-Clause",
        "BSD-3-Clause",
        "MIT-CMU",
    ]
    assert [license_["subject"] for license_ in MANIFEST["licenses"]] == [
        "imageio-ffmpeg",
        "FFmpeg",
        "numpy",
        "soundfile",
        "pillow",
    ]
    assert "models" not in MANIFEST


def test_the_pyproject_pins_the_four_render_dependencies() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == [
        "imageio-ffmpeg==0.6.0",
        "numpy==2.5.4",
        "pillow==13.0.0",
        "soundfile==0.13.1",
    ]
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_capability_is_render_video_with_the_video_viewer() -> None:
    assert CAPABILITY["kind"] == "video"
    assert CAPABILITY["preview"] == {"viewer": "video"}
    assert MANIFEST["capabilities"].keys() == {"render"}
    assert "summary" in CAPABILITY and CAPABILITY["summary"]
    assert "summary" in CAPABILITY["i18n"]["es"] and CAPABILITY["i18n"]["es"]["summary"]


def test_the_capability_declares_exactly_the_ten_inputs() -> None:
    assert set(INPUTS) == {
        "audio",
        "name",
        "style",
        "aspect",
        "cover",
        "title",
        "background",
        "accent",
        "fps",
        "crf",
    }


def _field(name: str) -> dict[str, Any]:
    field = INPUTS[name]
    assert isinstance(field, dict), name
    return field


def test_audio_and_name_are_required() -> None:
    assert _field("audio")["required"] is True
    assert _field("audio")["type"] == "path"
    assert _field("name")["required"] is True
    assert _field("name")["type"] == "string"
    assert _field("name")["pattern"] == "^[a-z0-9][a-z0-9-]*$"


def test_style_and_aspect_are_enums_with_defaults() -> None:
    assert _field("style")["type"] == "enum"
    assert _field("style")["values"] == ["bars", "waveform"]
    assert _field("style")["default"] == "bars"
    assert _field("aspect")["type"] == "enum"
    assert _field("aspect")["values"] == ["16:9", "9:16", "1:1"]
    assert _field("aspect")["default"] == "1:1"


def test_cover_and_title_are_optional_paths_and_strings() -> None:
    assert _field("cover")["type"] == "path"
    assert _field("cover").get("required", False) is False
    assert _field("title")["type"] == "string"
    assert _field("title").get("required", False) is False


def test_colors_fps_and_crf_carry_their_defaults() -> None:
    assert _field("background")["type"] == "string"
    assert _field("background")["default"] == DEFAULT_BACKGROUND
    assert _field("accent")["type"] == "string"
    assert _field("accent")["default"] == DEFAULT_ACCENT
    assert _field("fps")["type"] == "integer"
    assert _field("fps")["default"] == DEFAULT_FPS
    assert (_field("fps")["min"], _field("fps")["max"]) == (FPS_MIN, FPS_MAX)
    assert _field("crf")["type"] == "integer"
    assert _field("crf")["default"] == DEFAULT_CRF
    assert (_field("crf")["min"], _field("crf")["max"]) == (CRF_MIN, CRF_MAX)


def test_the_index_carries_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "audiogram" in names
    assert (PACKAGE / "package.toml").is_file()


def test_the_root_readme_lists_audiogram_under_video() -> None:
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if line.startswith("| video | audiogram |")]
    assert len(rows) == 1


def test_the_bundled_example_is_tagged_and_self_contained() -> None:
    piece = PACKAGE / "examples" / "render.toml"
    data = tomllib.loads(piece.read_text(encoding="utf-8"))
    assert data["capability"] == "audiogram.render"
    assert (piece.parent / str(data["inputs"]["audio"])).is_file()
