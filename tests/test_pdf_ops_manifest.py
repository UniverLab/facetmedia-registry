"""The pdf-ops manifest, its index entry and the input contract it declares.

The registry suite runs without the core, so the input contract is
asserted as data: ``facet run`` validates pieces against these fields
before the runner sees them. The package is a CPU python-env with
pinned pikepdf, pypdfium2 and Pillow; its four capabilities are
``pdf-ops.merge``, ``pdf-ops.split``, ``pdf-ops.compress`` (document
kind, document viewer) and ``pdf-ops.rasterize`` (image kind, image
viewer); and ``index.toml`` is the only way a package reaches the
registry.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "pdf-ops"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITIES = MANIFEST["capabilities"]
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DISK_GB = 0.2
MERGE_MIN_ITEMS = 2
DPI_DEFAULT = 150
DPI_MIN = 72
DPI_MAX = 300


def test_the_package_is_a_cpu_python_env_with_pdf_tooling() -> None:
    assert MANIFEST["name"] == "pdf-ops"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "text"
    assert MANIFEST["provider"] == "pikepdf · pypdfium2"
    assert MANIFEST["tool_name"] == "PDF Ops"
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == 1
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert "models" not in MANIFEST


def test_the_licenses_name_each_pdf_dependency() -> None:
    by_subject = {entry["subject"]: entry["spdx"] for entry in MANIFEST["licenses"]}
    assert by_subject == {
        "pikepdf": "MPL-2.0",
        "pypdfium2": "Apache-2.0",
        "pillow": "MIT-CMU",
    }


def test_the_pyproject_pins_the_pdf_stack() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == [
        "pikepdf==10.18.3",
        "pypdfium2==5.15.2",
        "pillow==13.0.0",
    ]
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_index_registers_the_package() -> None:
    assert "pdf-ops" in [entry["name"] for entry in INDEX["packages"]]


def test_the_root_readme_lists_the_package_under_text() -> None:
    rows = [
        line
        for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| text | pdf-ops |")
    ]
    assert len(rows) == 1


def test_the_four_capabilities_have_kinds_and_viewers() -> None:
    assert set(CAPABILITIES) == {"merge", "split", "compress", "rasterize"}
    for name in ("merge", "split", "compress"):
        assert CAPABILITIES[name]["kind"] == "document"
        assert CAPABILITIES[name]["preview"] == {"viewer": "document"}
    assert CAPABILITIES["rasterize"]["kind"] == "image"
    assert CAPABILITIES["rasterize"]["preview"] == {"viewer": "image"}


def test_every_capability_summary_has_a_spanish_translation() -> None:
    for name, capability in CAPABILITIES.items():
        assert capability["summary"].strip(), name
        assert capability["i18n"]["es"]["summary"].strip(), name


def test_every_input_name_is_kebab_case() -> None:
    for name, capability in CAPABILITIES.items():
        for field in capability["inputs"]:
            assert field == field.lower().replace("_", "-"), f"{name}.{field}"
            assert " " not in field, f"{name}.{field}"


def _field(capability: str, dotted: str) -> dict[str, Any]:
    field: dict[str, Any] = CAPABILITIES[capability]["inputs"]
    for part in dotted.split("."):
        field = field[part]
    assert isinstance(field, dict), f"{capability}.{dotted}"
    return field


def test_merge_takes_an_array_of_two_or_more_path_tables() -> None:
    pdf = _field("merge", "pdf")
    assert pdf["type"] == "array"
    assert pdf["min_items"] == MERGE_MIN_ITEMS
    assert pdf["required"] is True
    path = _field("merge", "pdf.items.path")
    assert path["type"] == "path"
    assert path["required"] is True
    name = _field("merge", "name")
    assert name["type"] == "string"
    assert name["required"] is True
    assert name["pattern"] == NAME_PATTERN.pattern


def test_split_takes_a_pdf_a_pages_selection_and_a_name() -> None:
    assert _field("split", "pdf")["type"] == "path"
    assert _field("split", "pdf")["required"] is True
    pages = _field("split", "pages")
    assert pages["type"] == "string"
    assert pages["required"] is True
    assert _field("split", "name")["pattern"] == NAME_PATTERN.pattern


def test_compress_takes_a_pdf_and_a_name() -> None:
    assert set(CAPABILITIES["compress"]["inputs"]) == {"pdf", "name"}
    assert _field("compress", "pdf")["type"] == "path"
    assert _field("compress", "pdf")["required"] is True
    assert _field("compress", "name")["pattern"] == NAME_PATTERN.pattern


def test_rasterize_renders_at_a_bounded_dpi_with_optional_pages() -> None:
    assert _field("rasterize", "pdf")["type"] == "path"
    assert _field("rasterize", "name")["pattern"] == NAME_PATTERN.pattern
    pages = _field("rasterize", "pages")
    assert pages["type"] == "string"
    assert pages["required"] is False
    dpi = _field("rasterize", "dpi")
    assert dpi["type"] == "integer"
    assert dpi["default"] == DPI_DEFAULT
    assert dpi["min"] == DPI_MIN
    assert dpi["max"] == DPI_MAX
