"""The tiktok manifest: the publish facet's TikTok inbox-draft package."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "tiktok"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))

#: Longest one-line ``obtain`` hint the core wizard shows; mirrors the core limit.
MAX_OBTAIN_LEN = 300
#: Longest ``link`` address the core wizard shows; mirrors the core limit.
MAX_LINK_LIMIT = 200
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["post"]
INPUTS = CAPABILITY["inputs"]


def test_the_package_is_publish_on_the_publish_facet() -> None:
    assert MANIFEST["name"] == "tiktok"
    assert MANIFEST["version"] == "0.1.5"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "publish"
    assert MANIFEST["tool_name"] == "TikTok"


def test_the_package_is_a_light_cpu_python_env() -> None:
    assert MANIFEST["engine"]["type"] == "python-env"
    assert MANIFEST["engine"]["python"] == "3.12"
    assert MANIFEST["transport"]["type"] == "cli"
    assert MANIFEST["transport"]["entry"] == "runner.py"
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert "models" not in MANIFEST


def test_the_pyproject_is_stdlib_and_locked() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == []
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_the_secrets_are_the_app_pair_and_the_stored_tokens() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert set(secrets) == {
        "client-key",
        "client-secret",
        "access-token",
        "refresh-token",
        "open-id",
    }
    for entry in secrets.values():
        assert entry["required"] is True
        assert entry["description"]
    assert "client key" in secrets["client-key"]["description"]
    assert "refresh" in secrets["refresh-token"]["description"]


def test_every_secret_says_where_to_get_it_and_only_tokens_are_browser_minted() -> None:
    produced = {"access-token", "refresh-token", "open-id"}
    for entry in MANIFEST["secrets"]:
        obtain = entry.get("obtain")
        assert isinstance(obtain, str) and obtain, entry["name"]
        assert "\n" not in obtain and "\r" not in obtain, entry["name"]
        assert len(obtain) <= MAX_OBTAIN_LEN, entry["name"]
        if entry["name"] in produced:
            assert entry.get("produced_by") == "auth", entry["name"]
        else:
            assert "produced_by" not in entry, entry["name"]
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert "Login Kit" in secrets["client-key"]["obtain"]
    assert "http://127.0.0.1:8080/callback/" in secrets["client-key"]["obtain"]
    assert "video.upload" in secrets["access-token"]["obtain"]


def test_the_client_pair_links_to_where_it_is_created() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert secrets["client-key"]["link"] == "https://developers.tiktok.com/apps"
    assert secrets["client-secret"]["link"] == "https://developers.tiktok.com/apps"
    for name in ("access-token", "refresh-token", "open-id"):
        assert "link" not in secrets[name], name
    for entry in MANIFEST["secrets"]:
        link = entry.get("link")
        if link is None:
            continue
        assert link.startswith("https://"), entry["name"]
        assert len(link) <= MAX_LINK_LIMIT, entry["name"]


def test_the_capability_is_the_outward_post_with_the_post_viewer() -> None:
    assert CAPABILITY["kind"] == "post"
    assert CAPABILITY["outward"] is True
    assert CAPABILITY["preview"] == {"viewer": "post"}
    assert set(MANIFEST["capabilities"]) == {"post"}
    assert CAPABILITY["summary"]
    assert CAPABILITY["i18n"]["es"]["summary"]


def test_the_bundled_example_ships_with_its_clip() -> None:
    example = PACKAGE / "examples" / "inbox.toml"
    clip = PACKAGE / "examples" / "clip.mp4"
    assert example.is_file()
    assert clip.is_file()
    data = tomllib.loads(example.read_text(encoding="utf-8"))
    assert data["capability"] == "tiktok.post"
    assert data["inputs"]["caption"]
    assert data["inputs"]["video"] == "clip.mp4"
    assert "photos" not in data["inputs"]


def test_the_inputs_take_a_caption_and_exactly_one_media() -> None:
    assert INPUTS["caption"]["type"] == "string"
    assert INPUTS["caption"]["required"] is True
    assert INPUTS["video"]["type"] == "path"
    assert INPUTS["video"].get("required", False) is not True
    assert INPUTS["photos"]["type"] == "array"
    assert INPUTS["photos"].get("required", False) is not True
    assert INPUTS["photos"]["items"]["url"]["type"] == "string"
    assert INPUTS["photos"]["items"]["url"]["required"] is True


def test_the_root_readme_lists_tiktok_under_the_publish_facet() -> None:
    assert "| publish | tiktok |" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_registry_indexes_the_package_after_youtube() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "tiktok" in names
    assert names.index("youtube") == names.index("tiktok") - 1
    assert names.index("tiktok") == names.index("linkedin") - 1
    assert INDEX["facets"]["publish"]["label"] == "Publish"
    assert INDEX["facets"]["publish"]["i18n"]["es"]["label"] == "Publicación"
