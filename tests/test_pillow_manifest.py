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
    assert MANIFEST["version"] == "0.2.0"
    assert CAPABILITY["kind"] == "image"
    assert CAPABILITY["preview"] == {"viewer": "image"}
    assert MANIFEST["capabilities"].keys() == {"base", "retouch"}


def test_the_retouch_capability_declares_all_inputs() -> None:
    retouch = MANIFEST["capabilities"]["retouch"]
    assert retouch["kind"] == "image"
    assert retouch["preview"] == {"viewer": "image"}
    assert retouch["summary"]
    assert retouch["i18n"]["es"]["summary"]
    inputs = retouch["inputs"]
    expected_keys = {
        "image",
        "name",
        "format",
        "aspect",
        "rotate-deg",
        "flip",
        "autocontrast",
        "brightness",
        "contrast",
        "saturation",
        "warmth",
        "sharpen",
        "pad-px",
        "pad-color",
    }
    assert set(inputs.keys()) == expected_keys
    assert inputs["image"]["type"] == "path" and inputs["image"]["required"] is True
    assert inputs["name"]["type"] == "string" and inputs["name"]["required"] is True
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert inputs["format"]["values"] == ["png", "jpeg", "webp"]
    assert inputs["format"]["default"] == "png"
    assert inputs["aspect"]["values"] == ["1:1", "4:5", "16:9", "9:16", "3:2", "4:3"]
    max_deg = 180
    max_factor = 3.0
    max_pad = 400
    assert inputs["rotate-deg"]["min"] == -max_deg and inputs["rotate-deg"]["max"] == max_deg
    assert inputs["flip"]["values"] == ["none", "horizontal", "vertical"]
    assert inputs["autocontrast"]["type"] == "boolean"
    assert inputs["brightness"]["default"] == 1.0
    assert inputs["contrast"]["default"] == 1.0
    assert inputs["saturation"]["default"] == 1.0
    assert inputs["warmth"]["min"] == -1.0 and inputs["warmth"]["max"] == 1.0
    assert inputs["sharpen"]["min"] == 0.0 and inputs["sharpen"]["max"] == max_factor
    assert inputs["pad-px"]["type"] == "integer" and inputs["pad-px"]["max"] == max_pad
    assert inputs["pad-color"]["default"] == "#F6F3EC"


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
