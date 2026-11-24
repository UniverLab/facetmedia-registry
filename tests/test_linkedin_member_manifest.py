"""The linkedin-member manifest: the publish facet's personal LinkedIn profile package."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "linkedin-member"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))

#: Longest one-line ``obtain`` hint the core wizard shows; mirrors the core limit.
MAX_OBTAIN_LEN = 300
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["post"]
INPUTS = CAPABILITY["inputs"]


def test_the_package_is_publish_on_the_publish_facet() -> None:
    assert MANIFEST["name"] == "linkedin-member"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "publish"
    assert MANIFEST["tool_name"] == "LinkedIn Member"


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


def test_the_secrets_include_optional_refresh_and_auth_member_id() -> None:
    secrets = {entry["name"]: entry for entry in MANIFEST["secrets"]}
    assert set(secrets) == {
        "client-id",
        "client-secret",
        "access-token",
        "member-id",
        "refresh-token",
    }
    for name in ("client-id", "client-secret", "access-token", "member-id"):
        assert secrets[name]["required"] is True
        assert secrets[name]["description"]
    assert secrets["refresh-token"]["required"] is False
    assert secrets["refresh-token"]["description"]


def test_every_secret_says_where_to_get_it_and_auth_produced_ones() -> None:
    produced = {"access-token", "member-id", "refresh-token"}
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
    assert "w_member_social" in secrets["access-token"]["obtain"]
    assert "/v2/userinfo" in secrets["member-id"]["obtain"]


def test_the_capability_is_the_outward_post_with_no_author_input() -> None:
    assert CAPABILITY["kind"] == "post"
    assert CAPABILITY["outward"] is True
    assert CAPABILITY["preview"] == {"viewer": "post"}
    assert set(MANIFEST["capabilities"]) == {"post"}
    assert CAPABILITY["summary"]
    assert CAPABILITY["i18n"]["es"]["summary"]
    assert "author" not in INPUTS


def test_the_inputs_take_text_and_up_to_twenty_images() -> None:
    assert INPUTS["text"]["type"] == "string"
    assert INPUTS["text"]["required"] is True
    assert INPUTS["images"]["type"] == "array"
    assert INPUTS["images"].get("required", False) is not True
    assert INPUTS["images"]["items"]["path"]["type"] == "path"
    assert INPUTS["images"]["items"]["path"]["required"] is True
    assert INPUTS["images"]["items"]["alt"]["type"] == "string"
    assert INPUTS["images"]["items"]["alt"]["required"] is True


def test_the_bundled_example_ships_with_its_still() -> None:
    example = PACKAGE / "examples" / "post.toml"
    still = PACKAGE / "examples" / "banco.png"
    assert example.is_file()
    assert still.is_file()
    data = tomllib.loads(example.read_text(encoding="utf-8"))
    assert data["capability"] == "linkedin-member.post"
    assert "author" not in data["inputs"]
    assert data["inputs"]["text"]
    assert data["inputs"]["images"] == [
        {"path": "banco.png", "alt": "La escuadra del laboratorio sobre el banco de trabajo."}
    ]


def test_the_runner_dispatches_through_the_cli_transport() -> None:
    text = (PACKAGE / "runner.py").read_text(encoding="utf-8")
    assert text.rstrip().endswith("runner.main()")
    assert "packages/linkedin" not in text
    assert "linkedin_client" not in text


def test_the_root_readme_and_index_list_linkedin_member() -> None:
    assert "| publish | linkedin-member |" in (ROOT / "README.md").read_text(encoding="utf-8")
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "linkedin-member" in names
    assert names.index("linkedin-member") == len(names) - 1
