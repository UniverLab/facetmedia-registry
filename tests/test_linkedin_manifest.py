"""The linkedin manifest: the publish facet's LinkedIn organization-post package."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "linkedin"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))

#: Longest one-line ``obtain`` hint the core wizard shows; mirrors the core limit.
MAX_OBTAIN_LEN = 300
#: Longest ``link`` address the core wizard shows; mirrors the core limit.
MAX_LINK_LIMIT = 200
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["post"]
INPUTS = CAPABILITY["inputs"]


def test_the_package_is_publish_on_the_publish_facet() -> None:
    assert MANIFEST["name"] == "linkedin"
    assert MANIFEST["version"] == "0.1.3"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "publish"
    assert MANIFEST["tool_name"] == "LinkedIn"


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


def test_the_licences_name_the_linkedin_api_terms() -> None:
    subjects = [entry["subject"] for entry in MANIFEST["licenses"]]
    assert any("LinkedIn" in subject for subject in subjects)


def test_the_secrets_are_the_app_pair_tokens_and_org() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert set(secrets) == {
        "client-id",
        "client-secret",
        "access-token",
        "refresh-token",
        "org-id",
    }
    for entry in secrets.values():
        assert entry["required"] is True
        assert entry["description"]
    assert "client id" in secrets["client-id"]["description"]
    assert "refresh" in secrets["refresh-token"]["description"]
    assert "organization" in secrets["org-id"]["description"]


def test_every_secret_says_where_to_get_it_and_only_tokens_are_browser_minted() -> None:
    produced = {"access-token", "refresh-token"}
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
    assert "Developer Portal" in secrets["client-id"]["obtain"]
    assert "Create an app" in secrets["client-id"]["obtain"]
    assert "Share on LinkedIn" in secrets["client-id"]["obtain"]
    assert "Sign In with LinkedIn using OpenID Connect" in secrets["client-id"]["obtain"]
    assert "Products tab" in secrets["client-id"]["obtain"]
    assert "Auth tab" in secrets["client-id"]["obtain"]
    assert "Auth tab" in secrets["client-secret"]["obtain"]
    assert "organization scopes" in secrets["access-token"]["obtain"]
    assert "urn:li:organization" in secrets["org-id"]["obtain"]


def test_the_client_pair_links_to_where_it_is_created() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert secrets["client-id"]["link"] == "https://www.linkedin.com/developers/apps"
    assert secrets["client-secret"]["link"] == "https://www.linkedin.com/developers/apps"
    for name in ("access-token", "refresh-token", "org-id"):
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


def test_the_bundled_example_ships_with_its_still() -> None:
    example = PACKAGE / "examples" / "post.toml"
    still = PACKAGE / "examples" / "banco.png"
    assert example.is_file()
    assert still.is_file()
    data = tomllib.loads(example.read_text(encoding="utf-8"))
    assert data["capability"] == "linkedin.post"
    assert data["inputs"]["author"] == "urn:li:organization:1234567"
    assert data["inputs"]["text"]
    assert data["inputs"]["images"] == [
        {"path": "banco.png", "alt": "La escuadra del laboratorio sobre el banco de trabajo."}
    ]


def test_the_runner_dispatches_through_the_cli_transport() -> None:
    text = (PACKAGE / "runner.py").read_text(encoding="utf-8")
    assert text.rstrip().endswith("runner.main()")


def test_the_inputs_take_an_org_author_text_and_up_to_twenty_images() -> None:
    assert INPUTS["author"]["type"] == "string"
    assert INPUTS["author"]["required"] is True
    assert "urn:li:organization" in INPUTS["author"]["pattern"]
    assert INPUTS["text"]["type"] == "string"
    assert INPUTS["text"]["required"] is True
    assert INPUTS["images"]["type"] == "array"
    assert INPUTS["images"].get("required", False) is not True
    assert INPUTS["images"]["items"]["path"]["type"] == "path"
    assert INPUTS["images"]["items"]["path"]["required"] is True
    assert INPUTS["images"]["items"]["alt"]["type"] == "string"
    assert INPUTS["images"]["items"]["alt"]["required"] is True


def test_the_root_readme_lists_linkedin_under_the_publish_facet() -> None:
    assert "| publish | linkedin |" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_registry_indexes_the_package_after_tiktok() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "linkedin" in names
    assert names.index("tiktok") == names.index("linkedin") - 1
    assert INDEX["facets"]["publish"]["label"] == "Publish"
    assert INDEX["facets"]["publish"]["i18n"]["es"]["label"] == "Publicación"
