"""The whisper-subs manifest, its index entry and the input contract.

The registry suite runs without the core, so the input contract is
asserted as data: ``facet run`` validates pieces against these fields
before the runner sees them, and the runner's own checks cover what the
schema cannot express (the cues' order). The package is a stdlib-only
CPU python-env — no models, no heavy requirements — the capability is
``whisper-subs.subtitulos`` of kind ``text`` with the generic viewer
(the facet/kind split whisper set), and ``index.toml`` is the only way
a package reaches the registry.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "whisper-subs"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["subtitulos"]
INPUTS = CAPABILITY["inputs"]


def test_the_package_is_a_light_stdlib_python_env() -> None:
    assert MANIFEST["name"] == "whisper-subs"
    assert MANIFEST["facet"] == "voice"
    assert MANIFEST["engine"]["type"] == "python-env"
    assert MANIFEST["engine"]["python"] == "3.12"
    assert MANIFEST["transport"]["type"] == "cli"
    assert MANIFEST["transport"]["entry"] == "runner.py"
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert requirements["ram_gb"] == 1
    assert [license_["spdx"] for license_ in MANIFEST["licenses"]] == ["MIT"]
    assert "models" not in MANIFEST


def test_the_pyproject_carries_no_dependencies_and_its_lock() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == []
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_capability_is_text_with_the_generic_viewer() -> None:
    assert CAPABILITY["kind"] == "text"
    assert CAPABILITY["preview"] == {"viewer": "generic"}
    assert MANIFEST["capabilities"].keys() == {"subtitulos"}


def test_origen_is_a_required_path_relative_to_the_piece() -> None:
    field = INPUTS["origen"]
    assert field["type"] == "path"
    assert field["required"] is True
    assert "relative to the piece" in field["description"]
    assert field["description"].count("_") >= 1  # start_s, the critical key


def test_formato_is_the_srt_vtt_enum_with_srt_as_its_manifest_default() -> None:
    field = INPUTS["formato"]
    assert field["type"] == "enum"
    assert field["values"] == ["srt", "vtt"]
    assert field["default"] == "srt"
    assert "required" not in field or field["required"] is False


def test_the_verify_threshold_counts_at_least_one_cue() -> None:
    assert CAPABILITY["verify"]["thresholds"] == {"cues_min": 1}


def test_the_index_carries_the_package_as_an_append() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "whisper-subs" in names
    assert names.index("whisper-subs") == names.index("recetas") - 1
    assert names.index("recetas") == len(names) - 1
    assert names.index("pillow") == names.index("rembg") + 1  # the prior tail holds
    assert (PACKAGE / "package.toml").is_file()
