"""The deepfilter manifest: registration, pin, inputs, licences and docs rows.

The package registers ``deepfilter`` in ``index.toml`` and in the root
README's ``audio`` rows; the manifest pins the one static binary and the six
licences; the ``enhance`` capability carries the kebab-case inputs with the
English and Spanish summaries.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "deepfilter"
MANIFEST: dict[str, Any] = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
README = (ROOT / "README.md").read_text(encoding="utf-8")
MODEL_ID = "deep-filter-0.5.6-linux-x86_64"
MODEL_URL = (
    "https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/"
    "deep-filter-0.5.6-x86_64-unknown-linux-musl"
)
MODEL_BYTES = 36417296
MODEL_SHA256 = "70775e251eee44c0f2451a1e833326cf8bcbbe304d3e7cd12851e6fce72ef7da"
DISK_GB = 0.2
ATTEN_DEFAULT = 100.0
ATTEN_MIN = 0
ATTEN_MAX = 100


def _inputs() -> dict[str, Any]:
    return MANIFEST["capabilities"]["enhance"]["inputs"]


def test_the_package_registers_its_name_version_facet_and_protocol() -> None:
    assert MANIFEST["name"] == "deepfilter"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["facet"] == "audio"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["uses"] == ["audiopreview"]
    assert MANIFEST["provider"] == "Hendrik Schröter (DeepFilterNet3)"
    assert MANIFEST["tool_name"] == "DeepFilterNet3"


def test_the_engine_is_a_python_env_cli_client() -> None:
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    assert "binary" not in MANIFEST["engine"]
    assert "server" not in MANIFEST["engine"]


def test_the_requirements_fit_a_cpu_box() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == 1
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]


def test_the_licences_cover_the_tool_and_its_decoders() -> None:
    assert [(item["subject"], item["spdx"]) for item in MANIFEST["licenses"]] == [
        ("DeepFilterNet3", "MIT"),
        ("imageio-ffmpeg", "BSD-2-Clause"),
        ("FFmpeg (binary bundled in imageio-ffmpeg)", "GPL-3.0-or-later"),
        ("soundfile", "BSD-3-Clause"),
        ("pyloudnorm", "MIT"),
        ("numpy", "BSD-3-Clause"),
    ]


def test_the_model_pin_is_the_static_musl_binary() -> None:
    (model,) = MANIFEST["models"]
    assert model["id"] == MODEL_ID
    assert model["url"] == MODEL_URL
    assert model["sha256"] == MODEL_SHA256
    assert model["bytes"] == MODEL_BYTES
    assert model["path"] == "deep-filter-0.5.6-linux-x86_64/deep-filter"
    assert model["spdx"] == "MIT"
    assert model["commercial_use"] is True
    assert model["requires_acceptance"] is False


def test_the_capability_is_audio_with_the_audio_viewer() -> None:
    capability = MANIFEST["capabilities"]["enhance"]
    assert capability["kind"] == "audio"
    assert capability["preview"] == {"viewer": "audio"}
    assert "Suppress" in capability["summary"] or "suppress" in capability["summary"]
    assert "ruido" in capability["i18n"]["es"]["summary"]


def test_the_audio_and_name_inputs_are_required_paths_and_names() -> None:
    inputs = _inputs()
    assert inputs["audio"]["type"] == "path"
    assert inputs["audio"]["required"] is True
    assert inputs["name"]["type"] == "string"
    assert inputs["name"]["required"] is True
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"


def test_the_channel_enum_defaults_to_auto() -> None:
    channel = _inputs()["channel"]
    assert channel["type"] == "enum"
    assert channel["values"] == ["auto", "mix", "left", "right"]
    assert channel["default"] == "auto"


def test_the_attenuation_input_is_a_bounded_number() -> None:
    atten = _inputs()["atten-lim-db"]
    assert atten["type"] == "number"
    assert atten["default"] == ATTEN_DEFAULT
    assert atten["min"] == ATTEN_MIN
    assert atten["max"] == ATTEN_MAX


def test_the_post_filter_input_defaults_to_true() -> None:
    post = _inputs()["post-filter"]
    assert post["type"] == "boolean"
    assert post["default"] is True


def test_the_package_is_registered_in_the_index() -> None:
    names = [package["name"] for package in INDEX["packages"]]
    assert "deepfilter" in names


def test_the_root_readme_carries_the_audio_row() -> None:
    assert "| audio | deepfilter |" in README


def test_the_package_has_its_own_uv_project_without_torch() -> None:
    assert (PACKAGE / "pyproject.toml").is_file()
    assert (PACKAGE / "uv.lock").is_file()
    pyproject = (PACKAGE / "pyproject.toml").read_text(encoding="utf-8")
    assert "torch" not in pyproject.lower()
