"""The blender manifest, its index entry and the doctor contract it drives.

The registry suite runs without the core, so the host-app check is asserted as
data: ``facet doctor`` builds every ``machine_cannot`` message and its ``facet
config set`` fix from ``[engine.host_app]`` alone (core ``manifest_host.py`` and
``config.host_app_problem``), so the manifest's four values are the whole
contract. The minimum is pinned at ``5.2`` — the lab's default in
``tools/blender.sh`` and the installed 5.2.2 LTS, which a two-component
minimum accepts. v1 of the package is scene, animation and assets: the photo,
product and tour presets are gone, and the manifest carries no capability
named after one of them.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
SCENE = MANIFEST["capabilities"]["scene"]
ANIMATION = MANIFEST["capabilities"]["animation"]
ASSETS = MANIFEST["capabilities"]["assets"]
READ = (PACKAGE / "README.md").read_text(encoding="utf-8")
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
#: The docs with every run of whitespace collapsed, for phrase assertions.
FLAT_READ = " ".join(READ.split())
FLAT_SKILL = " ".join(SKILL.split())
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
#: The manifest's cost.
DISK_GB = 0.1
#: The smallest width a render may ask for, and the smallest sample count.
PIXEL_FLOOR = 64
SAMPLES_FLOOR = 1
#: What a scripted still and a scripted animation each declare.
SCENE_INPUTS = {"script", "name", "width", "height", "engine", "samples", "exposure", "seed"}
ANIMATION_INPUTS = SCENE_INPUTS | {"frames", "fps"}
#: The modules that belonged to the removed presets.
PRESET_MODULES = ("escena.py", "producto.py", "recorrido.py")
#: The capability ids v1 removed.
OLD_CAPABILITIES = ("blender.photo", "blender.product", "blender.tour")


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
    """The core renders the machine_cannot message from these two fields."""
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
    assert SCENE["kind"] == "image"
    assert SCENE["preview"] == {"viewer": "image"}


def test_the_manifest_lists_exactly_scene_animation_and_assets() -> None:
    """v1 is three capabilities; the presets' ids are gone from the manifest."""
    assert set(MANIFEST["capabilities"]) == {"scene", "animation", "assets"}
    for old in OLD_CAPABILITIES:
        assert old.split(".", 1)[1] not in MANIFEST["capabilities"]


def test_the_animation_is_the_video_kind_with_the_ffmpeg_recipe() -> None:
    """blender.animation is video kind, video viewer, frames and fps included."""
    assert ANIMATION["kind"] == "video"
    assert ANIMATION["preview"] == {"viewer": "video"}
    assert set(ANIMATION["inputs"]) == ANIMATION_INPUTS
    frames = ANIMATION["inputs"]["frames"]
    assert (frames["default"], frames["min"], frames["max"]) == (120, 1, 1440)
    fps = ANIMATION["inputs"]["fps"]
    assert (fps["default"], fps["min"], fps["max"]) == (24, 1, 60)
    assert frames["type"] == "integer" and fps["type"] == "integer"


def test_the_scene_inputs_are_the_script_and_the_output_settings() -> None:
    """The script is the piece's; everything else is the output facet owns."""
    assert set(SCENE["inputs"]) == SCENE_INPUTS
    script = SCENE["inputs"]["script"]
    assert script["type"] == "path"
    assert script["required"] is True
    assert "scene.camera" in script["description"]
    assert "relative" in script["description"]
    engine = SCENE["inputs"]["engine"]
    assert engine["type"] == "enum"
    assert engine["values"] == ["cycles", "eevee"]
    assert engine["default"] == "cycles"
    assert SCENE["inputs"]["exposure"]["default"] == 0.0
    assert (SCENE["inputs"]["exposure"]["min"], SCENE["inputs"]["exposure"]["max"]) == (-5, 5)
    for name in ("width", "height", "samples"):
        field = SCENE["inputs"][name]
        assert field["type"] == "integer", name
        assert field["min"] in (SAMPLES_FLOOR, PIXEL_FLOOR), name


def test_the_assets_capability_is_text_with_the_generic_preview() -> None:
    """blender.assets fetches Poly Haven files into the models dir: no Blender."""
    assert ASSETS["kind"] == "text"
    assert ASSETS["preview"] == {"viewer": "generic"}
    inputs = ASSETS["inputs"]
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
    assert "blender.scene" in body


def test_the_presets_are_gone() -> None:
    """Their modules, pieces and references are deleted, not merely unlisted."""
    for name in PRESET_MODULES:
        assert not (PACKAGE / name).exists(), name
    for piece in ("estudio.toml", "tour.toml", "estudio.glb"):
        assert not (PACKAGE / "examples" / piece).exists(), piece
    for reference in ("tour.md", "people-cars.md"):
        assert not (PACKAGE / "skill" / "references" / reference).exists(), reference
    for old in OLD_CAPABILITIES:
        assert old not in READ, old
        assert old not in SKILL, old
    assert not (PACKAGE / "examples" / "estudio.py").exists()


def test_the_examples_are_named_by_the_docs() -> None:
    """The docs point an agent at the three examples it copies and edits."""
    for folder, piece in (
        ("study-photo", "study-photo.toml"),
        ("product", "product.toml"),
        ("tour", "tour.toml"),
    ):
        assert (PACKAGE / "examples" / folder / piece).is_file(), piece
        assert folder in FLAT_READ or piece in FLAT_READ
        assert piece in FLAT_SKILL or folder in FLAT_SKILL


def test_the_readme_documents_the_contract_the_route_and_the_rule() -> None:
    """What a person needs: the host, the script's globals, and who owns what."""
    assert "facet config set blender.path" in READ
    assert "BLENDER_EXE" in READ
    assert "host-app" in READ
    assert "Never STEP" in READ
    assert "0.001" in READ
    assert "machine_cannot" in READ
    assert "FACET_PIECE_DIR" in READ
    assert "FACET_ASSETS" in READ
    assert "BLENDED" in READ
    assert "surface_render_method" in READ
    assert "facet owns only the output" in FLAT_READ
    assert "The script owns every creative choice" in FLAT_READ
