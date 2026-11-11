"""The pillow manifest, its index entry and the op schema it declares.

The registry suite runs without the core, so the input contract is
asserted as data: ``facet run`` validates pieces against these fields
before the runner sees them, and the runner's own checks cover what the
schema cannot express (per-op required fields). The package is a CPU
python-env with a pinned Pillow, the capability is ``pillow.base`` of
kind image with the image viewer, and ``index.toml`` is the only way a
package reaches the registry.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "pillow"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["base"]
INPUTS = CAPABILITY["inputs"]
OPS = INPUTS["operations"]["items"]


def test_the_package_is_a_cpu_python_env_with_pillow() -> None:
    assert MANIFEST["name"] == "pillow"
    assert MANIFEST["facet"] == "image"
    assert MANIFEST["engine"]["type"] == "python-env"
    assert MANIFEST["engine"]["python"] == "3.12"
    assert MANIFEST["transport"]["type"] == "cli"
    assert MANIFEST["transport"]["entry"] == "runner.py"
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert [license_["spdx"] for license_ in MANIFEST["licenses"]] == ["MIT-CMU"]
    assert "models" not in MANIFEST


def test_the_pyproject_pins_pillow_13() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == ["pillow==13.0.0"]
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_capability_is_base_image_with_the_image_viewer() -> None:
    assert CAPABILITY["kind"] == "image"
    assert CAPABILITY["preview"] == {"viewer": "image"}
    assert MANIFEST["capabilities"].keys() == {"base"}


def test_image_is_a_required_path_relative_to_the_piece() -> None:
    field = INPUTS["image"]
    assert field["type"] == "path"
    assert field["required"] is True
    assert "relative to the piece" in field["description"]


def test_operations_is_a_required_array_with_the_op_enum() -> None:
    field = INPUTS["operations"]
    assert field["type"] == "array"
    assert field["required"] is True
    assert field["min_items"] == 1
    op = OPS["op"]
    assert op["type"] == "enum"
    assert op["values"] == ["convert", "resize", "sheet"]
    assert op["required"] is True


def test_the_op_fields_carry_their_enums_and_minimums() -> None:
    assert OPS["format"]["type"] == "enum"
    assert OPS["format"]["values"] == ["png", "jpeg", "webp"]
    assert "required" not in OPS["format"] or OPS["format"]["required"] is False
    assert OPS["mode"]["type"] == "enum"
    assert OPS["mode"]["values"] == ["RGB", "RGBA", "L"]
    for key in ("width", "height", "columns", "rows"):
        assert OPS[key]["type"] == "integer", key
        assert OPS[key]["min"] == 1, key


def test_the_index_carries_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "pillow" in names
    assert names.index("pillow") == names.index("rembg") + 1
    assert (PACKAGE / "package.toml").is_file()
