"""The youtube manifest: the publish facet's YouTube upload package."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "youtube"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))

#: Longest one-line ``obtain`` hint the core wizard shows; mirrors the core limit.
MAX_OBTAIN_LEN = 300
#: Longest ``link`` address the core wizard shows; mirrors the core limit.
MAX_LINK_LIMIT = 200
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["upload"]
INPUTS = CAPABILITY["inputs"]


def test_the_package_is_publish_on_the_publish_facet() -> None:
    assert MANIFEST["name"] == "youtube"
    assert MANIFEST["version"] == "0.1.1"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "publish"
    assert MANIFEST["tool_name"] == "YouTube"


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
        ("YouTube Data API (Google LLC)", "LicenseRef-YouTube-API-Terms")
    ]
    assert "models" not in MANIFEST


def test_the_pyproject_declares_google_deps_and_is_locked() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    assert any(dep.startswith("google-api-python-client") for dep in deps)
    assert any(dep.startswith("google-auth") for dep in deps)
    assert any(dep.startswith("google-auth-oauthlib") for dep in deps)
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_secrets_are_the_oauth_client_and_refresh_token() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert set(secrets) == {"client-id", "client-secret", "refresh-token"}
    for entry in secrets.values():
        assert entry["required"] is True
        assert entry["description"]
    assert "client" in secrets["client-id"]["description"].lower()
    assert "refresh" in secrets["refresh-token"]["description"].lower()


def test_every_secret_says_where_to_get_it_and_only_the_token_is_browser_minted() -> None:
    for entry in MANIFEST["secrets"]:
        obtain = entry.get("obtain")
        assert isinstance(obtain, str) and obtain, entry["name"]
        assert "\n" not in obtain and "\r" not in obtain, entry["name"]
        assert len(obtain) <= MAX_OBTAIN_LEN, entry["name"]
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert "Google Cloud Console" in secrets["client-id"]["obtain"]
    assert "YouTube Data API v3" in secrets["client-id"]["obtain"]
    assert "Desktop" in secrets["client-id"]["obtain"]
    assert secrets["refresh-token"].get("produced_by") == "auth"
    assert "produced_by" not in secrets["client-id"], "client-id"
    assert "produced_by" not in secrets["client-secret"], "client-secret"


def test_the_client_pair_links_to_where_it_is_created() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert secrets["client-id"]["link"] == "https://console.cloud.google.com/auth/overview"
    assert secrets["client-secret"]["link"] == "https://console.cloud.google.com/auth/overview"
    assert "link" not in secrets["refresh-token"], "refresh-token"
    for entry in MANIFEST["secrets"]:
        link = entry.get("link")
        if link is None:
            continue
        assert link.startswith("https://"), entry["name"]
        assert len(link) <= MAX_LINK_LIMIT, entry["name"]


def test_the_capability_is_the_outward_post_upload() -> None:
    assert CAPABILITY["kind"] == "post"
    assert CAPABILITY["outward"] is True
    assert CAPABILITY["preview"] == {"viewer": "post"}
    assert set(MANIFEST["capabilities"]) == {"upload"}
    assert CAPABILITY["summary"]
    assert CAPABILITY["i18n"]["es"]["summary"]


def test_the_bundled_example_ships_with_its_clip() -> None:
    example = PACKAGE / "examples" / "upload.toml"
    clip = PACKAGE / "examples" / "banco.mp4"
    assert example.is_file()
    assert clip.is_file()
    data = tomllib.loads(example.read_text(encoding="utf-8"))
    assert data["capability"] == "youtube.upload"
    assert data["inputs"]["video"] == "banco.mp4"
    assert data["inputs"]["privacy"] == "private"
    assert data["inputs"]["made-for-kids"] is False


def test_the_inputs_defaults_and_required_flags() -> None:
    assert INPUTS["video"]["type"] == "path"
    assert INPUTS["video"]["required"] is True
    assert INPUTS["title"]["type"] == "string"
    assert INPUTS["title"]["required"] is True
    assert INPUTS["description"]["type"] == "string"
    assert INPUTS["description"]["required"] is True
    assert INPUTS["tags"]["type"] == "array"
    assert INPUTS["tags"]["items"]["tag"]["type"] == "string"
    assert INPUTS["tags"]["items"]["tag"]["required"] is True
    assert INPUTS["category"]["type"] == "string"
    assert INPUTS["category"]["required"] is True
    assert INPUTS["category"]["pattern"] == "^[0-9]{1,3}$"
    assert INPUTS["privacy"]["type"] == "enum"
    assert INPUTS["privacy"]["values"] == ["private", "unlisted", "public"]
    assert INPUTS["privacy"]["default"] == "private"
    assert INPUTS["made-for-kids"]["type"] == "boolean"
    assert INPUTS["made-for-kids"]["required"] is True
    assert "default" not in INPUTS["made-for-kids"]
    assert INPUTS["thumbnail"]["type"] == "path"
    assert INPUTS["notify-subscribers"]["type"] == "boolean"
    assert INPUTS["notify-subscribers"]["default"] is True
    assert INPUTS["synthetic"]["type"] == "boolean"
    assert INPUTS["synthetic"]["default"] is False


def test_the_root_readme_lists_youtube_under_the_publish_facet() -> None:
    assert "| publish | youtube |" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_registry_indexes_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "youtube" in names
    assert names.index("x") == names.index("youtube") - 1
    assert names.index("youtube") == names.index("tiktok") - 1
    assert INDEX["facets"]["publish"]["label"] == "Publish"
    assert INDEX["facets"]["publish"]["i18n"]["es"]["label"] == "Publicación"
