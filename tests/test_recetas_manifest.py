"""The recetas manifest, its index entry and the input contract.

The registry suite runs without the core, so the input contract is asserted
as data: ``facet run`` validates pieces against these fields before the
runner sees them. The package is a stdlib-only CPU python-env — no models,
no heavy requirements — writing text plans under the ``text`` facet, and
``index.toml`` is the only way a package reaches the registry.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "recetas"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["plan"]
INPUTS = CAPABILITY["inputs"]
RECIPES = ["video-explicativo", "render-arq", "material-voz", "demo-herramienta"]


def test_the_package_is_a_light_stdlib_text_python_env() -> None:
    assert MANIFEST["name"] == "recetas"
    assert MANIFEST["facet"] == "text"
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
    assert MANIFEST["capabilities"].keys() == {"plan"}


def test_receta_is_the_required_closed_enum() -> None:
    field = INPUTS["receta"]
    assert field["type"] == "enum"
    assert field["values"] == RECIPES
    assert field["required"] is True
    assert "plan.json" in field["description"]


def test_the_verify_threshold_counts_at_least_one_step() -> None:
    assert CAPABILITY["verify"]["thresholds"] == {"steps_min": 1}


def test_the_index_carries_the_package_as_the_tail_append() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "recetas" in names
    assert names.index("recetas") == len(names) - 1
    assert names.index("whisper-subs") == names.index("recetas") - 1


def test_the_root_readme_lists_recetas_under_the_text_facet() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "| text | recetas |" in readme
    assert "| text | ascii |" in readme
    assert "| text | texforge |" in readme
