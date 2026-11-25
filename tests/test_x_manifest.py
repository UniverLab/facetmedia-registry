"""The x manifest: the publish facet's second outward package.

The registry suite runs without the core, so the checks here read the
manifest as data. The package is ``x`` 0.2.1 on the publish facet,
floored at the facet release that brought it (0.1.0b2): older cores skip
it before reading the rest. The capability is ``x.post`` of kind post,
the one outward kind, with the post viewer; the credentials are the
developer's OAuth 2.0 client ID and secret plus the brand account's
access and refresh tokens from the browser sign-in, all required;
``rates.json`` beside the runner is the dated price table no manifest
key may carry; and ``index.toml`` is the only way the package reaches
the registry.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "x"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))

#: Longest one-line ``obtain`` hint the core wizard shows; mirrors the core limit.
MAX_OBTAIN_LEN = 300
#: Longest ``link`` address the core wizard shows; mirrors the core limit.
MAX_LINK_LIMIT = 200
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["post"]
INPUTS = CAPABILITY["inputs"]
POSTS = INPUTS["posts"]["items"]
IMAGES = INPUTS["images"]["items"]
#: The bundled price table, read 2026-11-17, which no manifest key may carry.
POST_NO_URL = 0.015
POST_WITH_URL = 0.2
READ_POST = 0.005
READ_USER = 0.01
URL_LENGTH = 23


def test_the_package_is_publish_on_the_publish_facet() -> None:
    assert MANIFEST["name"] == "x"
    assert MANIFEST["version"] == "0.2.1"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "publish"
    assert MANIFEST["tool_name"] == "X"


def test_the_package_is_a_light_cpu_python_env() -> None:
    assert MANIFEST["engine"]["type"] == "python-env"
    assert MANIFEST["engine"]["python"] == "3.12"
    assert MANIFEST["transport"]["type"] == "cli"
    assert MANIFEST["transport"]["entry"] == "runner.py"
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert [(entry["subject"], entry["spdx"]) for entry in MANIFEST["licenses"]] == [
        ("X API (X Corp)", "LicenseRef-X-API-Terms")
    ]
    assert "models" not in MANIFEST
    assert "uses" not in MANIFEST


def test_the_pyproject_is_stdlib_only_and_locked() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == []
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_manifest_carries_no_rates_key() -> None:
    flat = json.dumps(MANIFEST).lower()
    assert "rates" not in flat
    assert "0.015" not in flat and "0.200" not in flat


def test_the_rates_file_is_the_dated_price_table() -> None:
    rates = json.loads((PACKAGE / "rates.json").read_text(encoding="utf-8"))
    assert rates["date"] == "2026-11-17"
    assert rates["currency"] == "USD"
    assert rates["post_no_url"] == POST_NO_URL
    assert rates["post_with_url"] == POST_WITH_URL
    assert rates["read_post"] == READ_POST
    assert rates["read_user"] == READ_USER
    assert rates["url_length"] == URL_LENGTH


def test_the_secrets_are_the_client_pair_and_the_sign_in_tokens() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert set(secrets) == {
        "client-id",
        "client-secret",
        "access-token",
        "refresh-token",
    }
    for entry in secrets.values():
        assert entry["required"] is True
        assert entry["description"]
    assert "client id" in secrets["client-id"]["description"].lower()
    assert "client secret" in secrets["client-secret"]["description"].lower()
    assert "access token" in secrets["access-token"]["description"].lower()
    assert "refresh token" in secrets["refresh-token"]["description"].lower()


def test_the_typed_secrets_say_where_to_get_them() -> None:
    for entry in MANIFEST["secrets"]:
        obtain = entry.get("obtain")
        assert isinstance(obtain, str) and obtain, entry["name"]
        assert "\n" not in obtain and "\r" not in obtain, entry["name"]
        assert len(obtain) <= MAX_OBTAIN_LEN, entry["name"]
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert "developer.x.com" in secrets["client-id"]["obtain"]
    assert "Keys and Tokens" in secrets["client-id"]["obtain"]
    assert "OAuth 2.0" in secrets["client-secret"]["description"]


def test_the_tokens_are_produced_by_the_sign_in() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    for name in ("access-token", "refresh-token"):
        assert secrets[name].get("produced_by") == "auth", name
        assert "sign-in" in secrets[name]["obtain"], name
    for name in ("client-id", "client-secret"):
        assert "produced_by" not in secrets[name], name


def test_the_client_pair_links_to_where_it_is_created() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert secrets["client-id"]["link"] == "https://console.x.com"
    assert secrets["client-secret"]["link"] == "https://console.x.com"
    for name in ("access-token", "refresh-token"):
        assert "link" not in secrets[name], name
    for entry in MANIFEST["secrets"]:
        link = entry.get("link")
        if link is None:
            continue
        assert link.startswith("https://"), entry["name"]
        assert len(link) <= MAX_LINK_LIMIT, entry["name"]


def test_the_capability_is_the_outward_post() -> None:
    assert CAPABILITY["kind"] == "post"
    assert CAPABILITY["outward"] is True
    assert CAPABILITY["preview"] == {"viewer": "post"}
    assert set(MANIFEST["capabilities"]) == {"post"}
    assert "cost" in CAPABILITY["summary"].lower()
    assert CAPABILITY["i18n"]["es"]["summary"]


def test_posts_is_a_required_thread_array() -> None:
    field = INPUTS["posts"]
    assert field["type"] == "array"
    assert field["required"] is True
    assert field["min_items"] == 1
    assert POSTS["text"]["type"] == "string"
    assert POSTS["text"]["required"] is True
    assert "lang" not in POSTS
    assert POSTS["video"]["type"] == "path"
    assert POSTS["gif"]["type"] == "path"


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


def test_the_root_readme_lists_x_under_the_publish_facet() -> None:
    assert "| publish | x |" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_registry_indexes_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "x" in names
    assert names.index("bluesky") == names.index("x") - 1
    assert names.index("youtube") == names.index("x") + 1
    assert names.index("youtube") == names.index("tiktok") - 1
    assert INDEX["facets"]["publish"]["label"] == "Publish"
    assert INDEX["facets"]["publish"]["i18n"]["es"]["label"] == "Publicación"
