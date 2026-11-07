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

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["foto"]
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
    assert MANIFEST["capabilities"].keys() == {"foto", "assets", "producto"}


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


def test_the_scene_parameters_are_camera_giro_and_exposure() -> None:
    """The scene the approved render sets, no more and no less."""
    assert set(INPUTS) == {"model", "camera", "giro", "exposure"}
    camera = INPUTS["camera"]
    assert camera["type"] == "array"
    assert set(camera["items"]) == {"azimut", "elevacion", "escala"}
    assert INPUTS["giro"]["default"] == 0
    assert INPUTS["exposure"]["default"] == EXPOSURE
    assert INPUTS["exposure"]["min"] < EXPOSURE < INPUTS["exposure"]["max"]


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
    assert "blender.foto" in body


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
