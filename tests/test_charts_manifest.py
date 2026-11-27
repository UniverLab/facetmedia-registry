"""The charts manifest, its index entry and the render schema it declares.

The registry suite runs without the core, so the input contract is
asserted as data: ``facet run`` validates pieces against these fields
before the runner sees them, and the runner's own checks cover what the
schema cannot express (missing columns, non-numeric cells). The package
is a CPU python-env with pinned matplotlib and Pillow, the capability
is ``charts.render`` of kind image with the image viewer, and
``index.toml`` is the only way a package reaches the registry.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "charts"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["render"]
INPUTS = CAPABILITY["inputs"]
DISK_GB = 0.3
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 675


def test_the_package_is_a_cpu_python_env_with_matplotlib_and_pillow() -> None:
    assert MANIFEST["name"] == "charts"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "presentation"
    assert MANIFEST["provider"] == "Matplotlib Development Team"
    assert MANIFEST["tool_name"] == "Editorial Charts"
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == 1
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert [license_["spdx"] for license_ in MANIFEST["licenses"]] == [
        "PSF-2.0",
        "BSD-3-Clause",
        "MIT-CMU",
    ]
    assert "models" not in MANIFEST


def test_the_pyproject_pins_matplotlib_and_pillow() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == [
        "matplotlib==3.11.2",
        "pillow==13.0.0",
    ]
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_capability_is_render_image_with_the_image_viewer() -> None:
    assert CAPABILITY["kind"] == "image"
    assert CAPABILITY["preview"] == {"viewer": "image"}
    assert MANIFEST["capabilities"].keys() == {"render"}
    assert "summary" in CAPABILITY and CAPABILITY["summary"]
    assert "summary" in CAPABILITY["i18n"]["es"] and CAPABILITY["i18n"]["es"]["summary"]


def test_the_capability_declares_exactly_the_twelve_inputs() -> None:
    assert set(INPUTS) == {
        "data",
        "name",
        "chart",
        "title",
        "subtitle",
        "source",
        "x",
        "y",
        "format",
        "accent",
        "width-px",
        "height-px",
    }


def _field(name: str) -> dict[str, Any]:
    field = INPUTS[name]
    assert isinstance(field, dict), name
    return field


def test_data_name_chart_title_x_y_are_required() -> None:
    for name in ("data", "name", "chart", "title", "x", "y"):
        assert _field(name)["required"] is True, name
    assert _field("data")["type"] == "path"
    assert _field("chart")["type"] == "enum"
    assert _field("chart")["values"] == ["bar", "barh", "line", "scatter"]
    for name in ("name", "title", "x", "y"):
        assert _field(name)["type"] == "string", name
    assert _field("name")["pattern"] == "^[a-z0-9][a-z0-9-]*$"


def test_subtitle_and_source_are_optional_strings() -> None:
    for name in ("subtitle", "source"):
        field = _field(name)
        assert field["type"] == "string", name
        assert field.get("required", False) is False, name


def test_format_accent_and_dims_carry_their_defaults() -> None:
    assert _field("format")["type"] == "enum"
    assert _field("format")["values"] == ["png", "svg"]
    assert _field("format")["default"] == "png"
    assert _field("accent")["type"] == "string"
    assert _field("accent")["default"] == "#E8C547"
    assert _field("width-px")["type"] == "integer"
    assert _field("width-px")["default"] == DEFAULT_WIDTH
    assert (_field("width-px")["min"], _field("width-px")["max"]) == (400, 3840)
    assert _field("height-px")["type"] == "integer"
    assert _field("height-px")["default"] == DEFAULT_HEIGHT
    assert (_field("height-px")["min"], _field("height-px")["max"]) == (300, 2160)


def test_the_index_carries_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "charts" in names
    assert (PACKAGE / "package.toml").is_file()


def test_the_root_readme_lists_charts_under_presentation() -> None:
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if line.startswith("| presentation | charts |")]
    assert len(rows) == 1


def test_the_bundled_example_is_tagged_and_self_contained() -> None:
    piece = PACKAGE / "examples" / "render.toml"
    data = tomllib.loads(piece.read_text(encoding="utf-8"))
    assert data["capability"] == "charts.render"
    assert (piece.parent / str(data["inputs"]["data"])).is_file()
