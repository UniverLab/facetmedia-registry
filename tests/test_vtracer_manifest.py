"""The vtracer manifest, its index entry and the trace schema it declares.

The registry suite runs without the core, so the input contract is
asserted as data: ``facet run`` validates pieces against these fields
before the runner sees them. The package is a CPU python-env with the
pinned vtracer wheel and Pillow, the capability is ``vtracer.trace`` of
kind image with the image viewer, and ``index.toml`` plus the root
README row are the only way a package reaches the registry.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "vtracer"
RAM_GB = 1
DISK_GB = 0.2
SUMMARY_LIMIT = 200
DEFAULT_SPECKLE = 4
MIN_SPECKLE = 0
MAX_SPECKLE = 128
DEFAULT_PRECISION = 6
MIN_PRECISION = 1
MAX_PRECISION = 8
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["trace"]
INPUTS = CAPABILITY["inputs"]


def test_the_package_is_a_cpu_python_env_with_vtracer() -> None:
    assert MANIFEST["name"] == "vtracer"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "image"
    assert MANIFEST["provider"] == "VisionCortex · VTracer"
    assert MANIFEST["tool_name"] == "VTracer"
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]


def test_the_licences_name_vtracer_and_pillow() -> None:
    licences = {entry["subject"]: entry["spdx"] for entry in MANIFEST["licenses"]}
    assert licences == {"vtracer": "MIT", "pillow": "MIT-CMU"}
    assert "models" not in MANIFEST


def test_the_pyproject_pins_vtracer_and_pillow() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == ["vtracer==0.6.15", "pillow==13.0.0"]
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_capability_is_trace_image_with_the_image_viewer() -> None:
    assert CAPABILITY["kind"] == "image"
    assert CAPABILITY["preview"] == {"viewer": "image"}
    assert MANIFEST["capabilities"].keys() == {"trace"}


def test_the_summaries_cover_english_and_spanish() -> None:
    assert CAPABILITY["summary"].startswith("Trace a crisp raster image")
    spanish = CAPABILITY["i18n"]["es"]["summary"]
    assert spanish.startswith("Convierte una imagen")
    assert len(spanish) <= SUMMARY_LIMIT


def test_image_and_name_are_required() -> None:
    assert INPUTS["image"] == {
        "type": "path",
        "required": True,
        "description": INPUTS["image"]["description"],
    }
    assert "relative to the piece" in INPUTS["image"]["description"]
    assert INPUTS["name"]["type"] == "string"
    assert INPUTS["name"]["required"] is True
    assert INPUTS["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"


def test_the_enums_carry_their_values_and_defaults() -> None:
    assert INPUTS["colormode"]["type"] == "enum"
    assert INPUTS["colormode"]["values"] == ["color", "binary"]
    assert INPUTS["colormode"]["default"] == "color"
    assert INPUTS["mode"]["type"] == "enum"
    assert INPUTS["mode"]["values"] == ["spline", "polygon", "none"]
    assert INPUTS["mode"]["default"] == "spline"


def test_the_integers_carry_their_ranges_and_defaults() -> None:
    speckle = INPUTS["filter-speckle"]
    assert speckle["type"] == "integer"
    assert speckle["default"] == DEFAULT_SPECKLE
    assert (speckle["min"], speckle["max"]) == (MIN_SPECKLE, MAX_SPECKLE)
    precision = INPUTS["color-precision"]
    assert precision["type"] == "integer"
    assert precision["default"] == DEFAULT_PRECISION
    assert (precision["min"], precision["max"]) == (MIN_PRECISION, MAX_PRECISION)


def test_the_index_carries_the_package_as_an_append() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert names.index("vtracer") == len(names) - 1
    assert (PACKAGE / "package.toml").is_file()


def test_the_root_readme_lists_vtracer_under_image() -> None:
    rows = [
        line
        for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| image | vtracer |")
    ]
    assert len(rows) == 1
