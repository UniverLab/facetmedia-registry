"""The texforge package teaches a long document, its staged project and its host.

The skill is the only place an agent learns the package, so these tests pin
what a person reads: the front matter and the four headings the core requires
in order, the capability id ``texforge.document`` with every input named, and
the person-installed binary rule. The manifest checks pin the public shape a
pull and a `facet registry validate` rely on.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "texforge"
EXAMPLES = PACKAGE / "examples"
REFERENCES = PACKAGE / "skill" / "references"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
README = (PACKAGE / "README.md").read_text(encoding="utf-8")
MANIFEST: dict[str, Any] = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
INSTALL_LINE = (
    "curl -fsSL https://raw.githubusercontent.com/UniverLab/texforge/main/scripts/install.sh | sh"
)
#: The one runnable piece the skill cites, by base name.
EXAMPLE = "hello-world"
#: A reference the skill cites, as ``references/<name>.md``.
REFERENCE_RE = re.compile(r"references/([a-z0-9][a-z0-9-]*)\.md")
#: The real keys the runner writes into the staged ``project.toml``.
STAGED_KEYS = (
    "[document]",
    "[build]",
    "title =",
    "author =",
    'template = "general"',
    "entry =",
    "bibliography",
    "embedded",
)
#: The exact argv the runner shells out to, in the reference's own lines.
INVOCATIONS = (
    "texforge build",
    "texforge check",
    "texforge pdf info",
    "texforge pdf check",
    "texforge preview --out <dir>",
)


def _front_matter() -> tuple[dict[str, str], str]:
    """The skill's front matter and body, split the way the core parses it."""
    first, second, *rest = SKILL.split("---", 2)
    assert first == "" and second.strip().startswith("name:")
    meta: dict[str, str] = {}
    for line in second.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, rest[0]


def test_skill_front_matter_and_headings_order() -> None:
    """The core's contract: name=texforge, a 20-200 description, four headings."""
    meta, body = _front_matter()
    assert meta["name"] == "texforge"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX
    assert "\n" not in meta["description"]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_skill_names_the_capability_and_every_input() -> None:
    _, body = _front_matter()
    assert "texforge.document" in body
    for name in MANIFEST["capabilities"]["document"]["inputs"]:
        assert name in body, name


def test_the_skill_says_the_binary_is_person_installed() -> None:
    _, body = _front_matter()
    assert "person-installed" in body
    assert "0.10.0" in body
    assert "texforge init" in body


def test_the_manifest_declares_a_python_env_cli_runner() -> None:
    assert MANIFEST["name"] == "texforge"
    assert MANIFEST["facet"] == "text"
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    engine = MANIFEST["engine"]
    assert "server" not in engine
    assert "binary" not in engine
    assert "host_app" not in engine
    assert "host_libs" not in MANIFEST["requirements"]


def test_the_host_hint_is_the_install_line() -> None:
    """A machine without texforge is told how to install it, the manifest's own."""
    assert MANIFEST["requirements"]["host_hint"] == INSTALL_LINE


def test_the_capability_is_a_document_with_the_document_viewer() -> None:
    document = MANIFEST["capabilities"]["document"]
    assert document["kind"] == "document"
    assert document["preview"] == {"viewer": "document"}
    inputs = document["inputs"]
    assert set(inputs) == {"main", "name", "author"}
    assert inputs["main"]["type"] == "path"
    assert inputs["main"]["required"] is True
    assert inputs["name"]["type"] == "string"
    assert inputs["name"]["required"] is True
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert inputs["author"]["type"] == "string"
    assert inputs["author"]["required"] is True


def test_the_readme_documents_the_staged_project_and_the_verify_rule() -> None:
    """The page a person reads: the real keys, no init, check + info, warnings."""
    assert "[document]" in README
    assert "[build]" in README
    assert 'title = "tesis"' in README
    assert 'template = "general"' in README
    assert "texforge init" in README
    assert "texforge check" in README
    assert "texforge pdf info" in README
    assert "warnings-only" in README or "never gated" in README
    assert "texforge preview" in README
    assert INSTALL_LINE in README
    assert "person-installed" in README
    assert "deck" in README


def test_the_package_is_registered_in_the_index() -> None:
    index = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
    names = [package["name"] for package in index["packages"]]
    assert "texforge" in names


def test_the_package_has_its_own_uv_project() -> None:
    """The registry wants a pyproject and a lock beside the runner."""
    assert (PACKAGE / "pyproject.toml").is_file()
    assert (PACKAGE / "uv.lock").is_file()


def test_every_reference_the_skill_cites_exists() -> None:
    """A cited reference that is not on disk sends the reader nowhere."""
    _, body = _front_matter()
    cited = set(REFERENCE_RE.findall(body))
    assert cited, "the skill cites at least one reference"
    for name in cited:
        path = REFERENCES / f"{name}.md"
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_the_build_reference_carries_the_keys_and_the_invocations() -> None:
    """The reference ports the real keys and the five command lines, not prose."""
    text = (REFERENCES / "build.md").read_text(encoding="utf-8")
    for key in STAGED_KEYS:
        assert key in text, key
    for command in INVOCATIONS:
        assert command in text, command


def test_the_example_is_a_runnable_piece() -> None:
    """The piece parses, stays inside ``texforge.document`` and ships its source."""
    _, body = _front_matter()
    assert f"examples/{EXAMPLE}.toml" in body
    inputs = tomllib.loads((EXAMPLES / f"{EXAMPLE}.toml").read_text(encoding="utf-8"))["inputs"]
    document = MANIFEST["capabilities"]["document"]["inputs"]
    assert set(inputs) <= set(document)
    assert re.fullmatch(document["name"]["pattern"], inputs["name"])
    assert inputs["name"] == EXAMPLE
    assert (EXAMPLES / inputs["main"]).is_file()
