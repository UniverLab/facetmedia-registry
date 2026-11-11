"""The blender manifest, its index entry and the doctor contract it drives.

The registry suite runs without the core, so the host-app check is asserted as
data: ``facet doctor`` builds every ``machine_cannot`` message and its ``facet
config set`` fix from ``[engine.host_app]`` alone (core ``manifest_host.py`` and
``config.host_app_problem``), so the manifest's four values are the whole
contract. The minimum is pinned at ``5.2`` — the lab's default in
``tools/blender.sh`` and the installed 5.2.2 LTS, which a two-component
minimum accepts. The capability is the image kind with the scene parameters the
approved render takes, and the index carries the entry facet loads packages
from.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["photo"]
INPUTS = CAPABILITY["inputs"]
READ = (PACKAGE / "README.md").read_text(encoding="utf-8")
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
#: The core's skill description bounds.
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: The core's ``min_version`` grammar: two or three dotted components.
VERSION_RE = re.compile(r"\d+\.\d+(\.\d+)?\Z")
#: The core's ``config_key`` grammar: dotted, lower case.
CONFIG_KEY_RE = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+\Z")
#: The core's ``env`` grammar: an environment variable name.
ENV_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
#: The manifest's cost and the approved exposure.
DISK_GB = 0.1
EXPOSURE = -0.6
#: The tour's frame-rate bounds, from the spec.
FPS_MIN = 12
FPS_MAX = 60
#: The dressing defaults the manifest pins for photo and tour alike.
ROTATION_DEFAULT = 200
SIZE_DEFAULT = 2.0


def _versions(value: str) -> tuple[int, int, int]:
    """The core's comparison: a dotted version padded to three components."""
    parts = [int(part) for part in value.split(".") if part.isdigit()]
    return tuple(parts + [0] * (3 - len(parts)))  # type: ignore[return-value]


def test_the_host_app_is_blender_at_least_5_2() -> None:
    """``[engine.host_app]`` is the whole host contract the core reads."""
    app = MANIFEST["engine"]["host_app"]
    assert app["app"] == "blender"
    assert app["min_version"] == "5.2"
    assert app["config_key"] == "blender.path"
    assert app["env"] == "BLENDER_EXE"
    # The core's grammar accepts each declared value.
    assert VERSION_RE.fullmatch(app["min_version"])
    assert CONFIG_KEY_RE.fullmatch(app["config_key"])
    assert ENV_RE.fullmatch(app["env"])


def test_the_engine_is_host_app_with_a_cli_transport_and_no_python() -> None:
    """A host-app package builds no environment: ``engine.python`` is forbidden."""
    assert MANIFEST["name"] == "blender"
    assert MANIFEST["facet"] == "image"
    assert MANIFEST["engine"]["type"] == "host-app"
    assert "python" not in MANIFEST["engine"]
    assert MANIFEST["transport"]["type"] == "cli"
    assert MANIFEST["transport"]["entry"] == "runner.py"


def test_the_env_is_the_lab_convention_for_blender() -> None:
    """The lab keeps BLENDER_EXE; the core's HOST_APPS default names the same."""
    assert MANIFEST["engine"]["host_app"]["env"] == "BLENDER_EXE"
    assert MANIFEST["engine"]["host_app"]["config_key"] == "blender.path"


def test_the_lab_blender_5_2_2_satisfies_the_minimum() -> None:
    """The installed 5.2.2 LTS passes; anything below 5.2 does not."""
    minimum = MANIFEST["engine"]["host_app"]["min_version"]
    assert _versions("5.2.2") >= _versions(minimum)
    assert _versions("5.2") >= _versions(minimum)
    assert _versions("5.1.1") < _versions(minimum)
    assert _versions("4.2.0") < _versions(minimum)


def test_the_missing_host_fails_with_the_exact_key_and_fix() -> None:
    """The core renders the machine_cannot message from these two fields.

    The message and the fix are built by ``config.host_app_problem`` from the
    manifest alone, so pinning them here pins what a person sees when Blender
    is absent or too old.
    """
    app = MANIFEST["engine"]["host_app"]
    fix = f"facet config set {app['config_key']} /path/to/{app['app']}"
    message = (
        f"{app['app']} {app['min_version']}+ not found "
        f"(config {app['config_key']}, env {app['env']}, PATH all empty); fix: {fix}"
    )
    assert fix == "facet config set blender.path /path/to/blender"
    assert message == (
        "blender 5.2+ not found (config blender.path, env BLENDER_EXE, PATH all empty); "
        "fix: facet config set blender.path /path/to/blender"
    )
    too_old = (
        f"blender 5.1.1 found, needs {app['min_version']}+ (config {app['config_key']}); fix: {fix}"
    )
    assert "5.1.1 found, needs 5.2+" in too_old
    assert fix in too_old


def test_the_package_is_never_installed_but_only_located() -> None:
    """No environment, no models, no download: the disk cost is the package."""
    requirements = MANIFEST["requirements"]
    assert requirements["disk_gb"] <= DISK_GB
    assert requirements["gpu"] is True
    assert requirements["exclusive"] is True
    assert requirements["platforms"] == ["linux"]
    assert "models" not in MANIFEST
    assert not (PACKAGE / "pyproject.toml").exists()


def test_the_index_carries_the_package_in_order() -> None:
    """Packages load only from index entries; an unindexed dir is never offered."""
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "blender" in names
    assert names.index("blender") == names.index("ascii") + 1
    assert (PACKAGE / "package.toml").is_file()


def test_the_capability_is_the_image_kind() -> None:
    assert CAPABILITY["kind"] == "image"
    assert CAPABILITY["preview"] == {"viewer": "image"}
    assert MANIFEST["capabilities"].keys() == {
        "photo",
        "assets",
        "product",
        "tour",
        "scene",
        "animation",
    }


def test_the_tour_is_the_video_kind_with_the_lab_recipe() -> None:
    """blender.tour is the Eevee camera tour: video kind, video viewer."""
    tour = MANIFEST["capabilities"]["tour"]
    assert tour["kind"] == "video"
    assert tour["preview"] == {"viewer": "video"}
    assert set(tour["inputs"]) == {
        "model",
        "azimuth",
        "elevation",
        "distance",
        "focal",
        "seconds",
        "fps",
        "seed",
        "people-blend",
        "people",
        "cars-blend",
        "cars",
        "sky",
        "textures",
        "plants",
    }
    assert tour["inputs"]["model"]["type"] == "path"
    assert tour["inputs"]["model"]["required"] is True
    assert "glb" in tour["inputs"]["model"]["description"]
    assert "STEP" in tour["inputs"]["model"]["description"]


def test_the_tour_pairs_carry_the_spec_ranges_and_defaults() -> None:
    """Each leg is one { start, end } item, the angle ranges photo already uses."""
    inputs = MANIFEST["capabilities"]["tour"]["inputs"]
    expected = {
        "azimuth": ((-75, -15), (-360, 360)),
        "elevation": ((55, 40), (-89, 89)),
        "distance": ((14.0, 10.5), (0.5, 200)),
    }
    for name, (defaults, (low, high)) in expected.items():
        field = inputs[name]
        assert field["type"] == "array", name
        assert set(field["items"]) == {"start", "end"}, name
        for key, value in zip(("start", "end"), defaults, strict=True):
            item = field["items"][key]
            assert item["default"] == value, (name, key)
            assert (item["min"], item["max"]) == (low, high), (name, key)


def test_the_tour_scalars_carry_the_spec_ranges() -> None:
    inputs = MANIFEST["capabilities"]["tour"]["inputs"]
    assert (inputs["focal"]["default"], inputs["focal"]["min"], inputs["focal"]["max"]) == (
        30,
        18,
        100,
    )
    assert (inputs["seconds"]["default"], inputs["seconds"]["min"]) == (10, 2)
    assert (inputs["seconds"]["max"], inputs["fps"]["default"]) == (60, 24)
    assert inputs["focal"]["type"] == "number"
    assert inputs["seconds"]["type"] == "integer" and inputs["fps"]["type"] == "integer"
    assert (inputs["fps"]["min"], inputs["fps"]["max"]) == (FPS_MIN, FPS_MAX)
    assert inputs["seed"]["type"] == "integer"
    assert inputs["seed"]["default"] == 0 and inputs["seed"]["min"] == 0


def test_the_assets_capability_is_text_with_the_generic_preview() -> None:
    """blender.assets fetches Poly Haven files into the models dir: no Blender."""
    assets = MANIFEST["capabilities"]["assets"]
    assert assets["kind"] == "text"
    assert assets["preview"] == {"viewer": "generic"}
    inputs = assets["inputs"]
    assert inputs["name"]["type"] == "string"
    assert inputs["name"]["required"] is True
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    fetch = inputs["assets"]
    assert fetch["type"] == "array"
    assert fetch["required"] is True
    assert fetch["min_items"] == 1
    assert fetch["items"]["id"]["required"] is True
    assert fetch["items"]["id"]["pattern"] == "^[a-z0-9][a-z0-9_-]*$"
    assert fetch["items"]["res"]["type"] == "enum"
    assert fetch["items"]["res"]["values"] == ["1k", "2k", "4k"]


def test_the_model_input_is_required_and_relative() -> None:
    """The glTF route: a path, resolved by facet relative to the piece file."""
    model = INPUTS["model"]
    assert model["type"] == "path"
    assert model["required"] is True
    assert "glb" in model["description"]
    assert "STEP" in model["description"]


def test_the_scene_parameters_are_camera_rotation_and_exposure() -> None:
    """The scene the approved render sets, no more and no less."""
    assert set(INPUTS) == {
        "model",
        "camera",
        "rotation",
        "exposure",
        "people-blend",
        "people",
        "cars-blend",
        "cars",
        "sky",
        "textures",
        "plants",
    }
    camera = INPUTS["camera"]
    assert camera["type"] == "array"
    assert set(camera["items"]) == {"azimuth", "elevation", "scale"}
    assert INPUTS["rotation"]["default"] == 0
    assert INPUTS["exposure"]["default"] == EXPOSURE
    assert INPUTS["exposure"]["min"] < EXPOSURE < INPUTS["exposure"]["max"]


def test_people_are_piece_data_on_both_scene_capabilities() -> None:
    """FR1: the prebuilt blend plus one placement item per person, both scenes."""
    for capability in ("photo", "tour"):
        inputs = MANIFEST["capabilities"][capability]["inputs"]
        blend = inputs["people-blend"]
        assert blend["type"] == "path", capability
        assert "required" not in blend, capability
        assert "Never generated here" in blend["description"], capability
        assert "projects/" not in blend["description"], capability
        people = inputs["people"]
        assert people["type"] == "array", capability
        assert people["default"] == [], capability
        assert "required" not in people, capability
        items = people["items"]
        assert set(items) == {"name", "x", "y", "rotation"}, capability
        assert items["name"]["type"] == "string"
        assert items["name"]["required"] is True
        for axis in ("x", "y"):
            assert items[axis]["type"] == "number", (capability, axis)
            assert items[axis]["required"] is True, (capability, axis)
        assert items["rotation"]["type"] == "number"
        assert items["rotation"]["default"] == 0
        assert "-y" in items["rotation"]["description"]


def test_cars_are_piece_data_on_both_scene_capabilities() -> None:
    """FR1: the prebuilt car blend plus one placement item per car, both scenes."""
    for capability in ("photo", "tour"):
        inputs = MANIFEST["capabilities"][capability]["inputs"]
        blend = inputs["cars-blend"]
        assert blend["type"] == "path", capability
        assert "required" not in blend, capability
        assert "Never generated here" in blend["description"], capability
        assert "projects/" not in blend["description"], capability
        cars = inputs["cars"]
        assert cars["type"] == "array", capability
        assert cars["default"] == [], capability
        assert "required" not in cars, capability
        items = cars["items"]
        assert set(items) == {"name", "x", "y", "rotation"}, capability
        assert items["name"]["type"] == "string"
        assert items["name"]["required"] is True
        for axis in ("x", "y"):
            assert items[axis]["type"] == "number", (capability, axis)
            assert items[axis]["required"] is True, (capability, axis)
        assert items["rotation"]["type"] == "number"
        assert items["rotation"]["default"] == 0
        assert "-y" in items["rotation"]["description"]


def test_the_skill_validates_in_the_core_format() -> None:
    first, second, *rest = SKILL.split("---", 2)
    assert first == "" and second.strip().startswith("name:")
    frontmatter = second.strip().splitlines()
    assert {"name: blender"} <= set(frontmatter)
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX
    body = rest[0]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)
    assert "blender.photo" in body


def _load_escena():
    """The lab's material set, loaded without Blender: escena needs no bpy."""
    spec = importlib.util.spec_from_file_location("blender_escena", PACKAGE / "escena.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_dressing_inputs_ride_on_both_scene_capabilities() -> None:
    """sky, textures and plants are arrays of fixed-field items, both scenes."""
    for capability in ("photo", "tour"):
        inputs = MANIFEST["capabilities"][capability]["inputs"]
        for name in ("sky", "textures", "plants"):
            field = inputs[name]
            assert field["type"] == "array", (capability, name)
            assert field["default"] == [], (capability, name)
            assert "required" not in field, (capability, name)
            assert "one" in field["description"], (capability, name)
        sky = inputs["sky"]["items"]
        assert set(sky) == {"id", "rotation", "strength"}, capability
        assert sky["id"]["type"] == "string" and sky["id"]["required"] is True
        assert sky["rotation"]["default"] == ROTATION_DEFAULT
        assert sky["rotation"]["type"] == "number"
        assert sky["strength"]["default"] == 1.0 and sky["strength"]["type"] == "number"
        cloth = inputs["textures"]["items"]
        assert set(cloth) == {"prefix", "id", "size", "hue", "saturation", "value"}
        assert cloth["prefix"]["type"] == "enum" and cloth["prefix"]["required"] is True
        assert cloth["id"]["type"] == "string" and cloth["id"]["required"] is True
        assert cloth["size"]["default"] == SIZE_DEFAULT and cloth["size"]["type"] == "number"
        assert (cloth["hue"]["default"], cloth["saturation"]["default"]) == (0.5, 1.0)
        assert cloth["value"]["default"] == 1.0
        greens = inputs["plants"]["items"]
        assert set(greens) == {"id", "x", "y", "rotation"}, capability
        assert greens["id"]["required"] is True
        assert greens["x"]["required"] is True and greens["y"]["required"] is True
        assert greens["rotation"]["default"] == 0
        for group in (sky, cloth, greens):
            for item in group.values():
                assert item["description"], (capability, item)


def test_the_prefix_enum_is_the_material_set() -> None:
    """The textures prefix enum is exactly the keys of escena.MATERIALS."""
    expected = set(_load_escena().MATERIALS)
    assert expected and "pavimento" in expected
    for capability in ("photo", "tour"):
        values = MANIFEST["capabilities"][capability]["inputs"]["textures"]["items"]["prefix"][
            "values"
        ]
        assert set(values) == expected, capability
        assert values == sorted(values), capability


def test_the_readme_documents_the_host_contract_the_route_and_the_rule() -> None:
    """The five things a person needs: host, glTF, scale, materials, exposure."""
    assert "facet config set blender.path" in READ
    assert "BLENDER_EXE" in READ
    assert "host-app" in READ
    assert "Never STEP" in READ
    assert "0.001" in READ
    assert "piezas sin material" in READ
    assert "AgX - Medium High Contrast" in READ
    assert "-0.6" in READ
    assert "machine_cannot" in READ
    assert "people-blend" in READ
