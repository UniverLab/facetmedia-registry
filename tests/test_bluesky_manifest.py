"""The bluesky manifest: the publish facet's first outward package.

The registry suite runs without the core, so the checks here read the
manifest as data. The package is ``bluesky`` 0.1.0 on the publish facet,
floored at the facet release that brought it (0.1.0b2): older cores skip
it before reading the rest. The capability is ``bluesky.post`` of kind
post, the one outward kind, with the post viewer; the credentials are the
handle and an app password, both required; and ``index.toml`` is the only
way the package reaches the registry.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "bluesky"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["post"]
INPUTS = CAPABILITY["inputs"]
POSTS = INPUTS["posts"]["items"]
IMAGES = INPUTS["images"]["items"]


def test_the_package_is_publish_on_the_publish_facet() -> None:
    assert MANIFEST["name"] == "bluesky"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "publish"
    assert MANIFEST["tool_name"] == "Bluesky"


def test_the_package_is_a_light_cpu_python_env() -> None:
    assert MANIFEST["engine"]["type"] == "python-env"
    assert MANIFEST["engine"]["python"] == "3.12"
    assert MANIFEST["transport"]["type"] == "cli"
    assert MANIFEST["transport"]["entry"] == "runner.py"
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert [entry["spdx"] for entry in MANIFEST["licenses"]] == ["MIT"]
    assert "models" not in MANIFEST
    assert "uses" not in MANIFEST


def test_the_pyproject_is_stdlib_only_and_locked() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == []
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_secrets_are_the_handle_and_an_app_password() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert set(secrets) == {"handle", "app-password"}
    for entry in secrets.values():
        assert entry["required"] is True
        assert entry["description"]
    assert "handle" in secrets["handle"]["description"].lower()
    assert "app password" in secrets["app-password"]["description"].lower()


def test_the_capability_is_the_outward_post() -> None:
    assert CAPABILITY["kind"] == "post"
    assert CAPABILITY["outward"] is True
    assert CAPABILITY["preview"] == {"viewer": "post"}
    assert set(MANIFEST["capabilities"]) == {"post"}
    assert "post" in CAPABILITY["summary"].lower() or "Post" in CAPABILITY["summary"]
    assert CAPABILITY["i18n"]["es"]["summary"]


def test_posts_is_a_required_thread_array() -> None:
    field = INPUTS["posts"]
    assert field["type"] == "array"
    assert field["required"] is True
    assert field["min_items"] == 1
    assert POSTS["text"]["type"] == "string"
    assert POSTS["text"]["required"] is True
    assert POSTS["lang"]["type"] == "string"
    assert POSTS["lang"].get("required", False) is False
    assert POSTS["video"]["type"] == "path"
    assert POSTS["card-url"]["type"] == "string"
    assert POSTS["card-title"]["type"] == "string"
    assert POSTS["card-description"]["type"] == "string"
    assert POSTS["card-thumb"]["type"] == "path"


def test_images_name_their_post_and_require_alt() -> None:
    field = INPUTS["images"]
    assert field["type"] == "array"
    assert field.get("required", False) is False
    assert IMAGES["post"]["type"] == "integer"
    assert IMAGES["post"]["required"] is True
    assert IMAGES["post"]["min"] == 1
    assert IMAGES["path"]["type"] == "path"
    assert IMAGES["path"]["required"] is True
    assert IMAGES["alt"]["type"] == "string"
    assert IMAGES["alt"]["required"] is True


def test_the_root_readme_lists_bluesky_under_the_publish_facet() -> None:
    assert "| publish | bluesky |" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_registry_indexes_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "bluesky" in names
    assert names.index("recipes") == names.index("bluesky") - 1
    assert names.index("bluesky") == names.index("x") - 1
    assert INDEX["facets"]["publish"]["label"] == "Publish"
    assert INDEX["facets"]["publish"]["i18n"]["es"]["label"] == "Publicación"
