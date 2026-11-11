"""The freecad manifest, its index entry and the doctor contract it drives.

The registry suite runs without the core, so the host-app check is asserted as
data: ``facet doctor`` builds the ``machine_cannot`` message and its
``facet config set`` fix from ``[engine.host_app]`` alone, so the manifest's
four values are the whole contract. The minimum is pinned at FreeCAD
``1.1.4`` — the lab's FreeCAD build — and the capability is the document kind
with the generic viewer, like the deck package's paginated documents.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "freecad"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["drawing"]
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
MINIMUM = "1.1.4"
#: The disk the package itself costs: it ships no environment.
DISK_GB = 0.1


def _versions(value: str) -> tuple[int, int, int]:
    """The core's comparison: a dotted version padded to three components."""
    parts = [int(part) for part in value.split(".") if part.isdigit()]
    return tuple(parts + [0] * (3 - len(parts)))  # type: ignore[return-value]


def test_the_host_app_is_freecad_at_least_1_1_4() -> None:
    """``[engine.host_app]`` is the whole host contract the core reads."""
    app = MANIFEST["engine"]["host_app"]
    assert app["app"] == "freecad"
    assert app["min_version"] == MINIMUM
    assert app["config_key"] == "freecad.path"
    assert app["env"] == "FREECAD_EXE"
    assert VERSION_RE.fullmatch(app["min_version"])
    assert CONFIG_KEY_RE.fullmatch(app["config_key"])
    assert ENV_RE.fullmatch(app["env"])


def test_the_engine_is_host_app_with_a_cli_transport_and_no_python() -> None:
    """A host-app package builds no environment: ``engine.python`` is forbidden."""
    assert MANIFEST["name"] == "freecad"
    assert MANIFEST["facet"] == "cad"
    assert MANIFEST["engine"]["type"] == "host-app"
    assert "python" not in MANIFEST["engine"]
    assert MANIFEST["transport"]["type"] == "cli"
    assert MANIFEST["transport"]["entry"] == "runner.py"
    template = MANIFEST["transport"]["invocation_template"]
    for token in ("{{app}}", "{{entry}}", "{{verb}}", "{{input}}", "{{result}}"):
        assert token in template
    # freecadcmd parses dashed args after --pass as its own options; -- stops it.
    tokens = template.split()
    assert tokens.index("--") < tokens.index("--input")


def test_the_freecad_1_1_4_build_satisfies_the_minimum() -> None:
    """The installed 1.1.4 passes; anything below does not."""
    minimum = MANIFEST["engine"]["host_app"]["min_version"]
    assert _versions("1.1.4") >= _versions(minimum)
    assert _versions("1.1.5") >= _versions(minimum)
    assert _versions("1.1.3") < _versions(minimum)
    assert _versions("1.0.0") < _versions(minimum)


def test_the_missing_host_fails_with_the_exact_key_and_fix() -> None:
    """The core renders the machine_cannot message from these two fields."""
    app = MANIFEST["engine"]["host_app"]
    fix = f"facet config set {app['config_key']} /path/to/{app['app']}"
    message = (
        f"{app['app']} {app['min_version']}+ not found "
        f"(config {app['config_key']}, env {app['env']}, PATH all empty); fix: {fix}"
    )
    assert fix == "facet config set freecad.path /path/to/freecad"
    assert message == (
        "freecad 1.1.4+ not found (config freecad.path, env FREECAD_EXE, PATH all empty); "
        "fix: facet config set freecad.path /path/to/freecad"
    )
    too_old = (
        f"freecad 1.1.3 found, needs {app['min_version']}+ (config {app['config_key']}); fix: {fix}"
    )
    assert "1.1.3 found, needs 1.1.4+" in too_old
    assert fix in too_old


def test_the_package_is_never_installed_but_only_located() -> None:
    """No environment, no models, no download: the disk cost is the package."""
    requirements = MANIFEST["requirements"]
    assert requirements["disk_gb"] <= DISK_GB
    assert requirements["gpu"] is False
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert "host_libs" not in requirements
    assert "host_hint" not in requirements
    assert "models" not in MANIFEST
    assert not (PACKAGE / "pyproject.toml").exists()
    assert (PACKAGE / "freecad_run.py").is_file()


def test_the_index_carries_the_package_after_svganim() -> None:
    """Packages load only from index entries; an unindexed dir is never offered."""
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "freecad" in names
    assert names.index("freecad") == names.index("svganim") + 1
    assert (PACKAGE / "package.toml").is_file()


def test_the_capability_is_the_document_kind_with_the_generic_viewer() -> None:
    """No document schema exists, so the generic viewer is the contract."""
    assert CAPABILITY["kind"] == "document"
    assert CAPABILITY["preview"] == {"viewer": "generic"}
    assert MANIFEST["capabilities"].keys() == {"drawing"}


def test_the_inputs_are_the_script_and_the_part_as_required_paths() -> None:
    assert set(INPUTS) == {"script", "part"}
    for name in ("script", "part"):
        assert INPUTS[name]["type"] == "path", name
        assert INPUTS[name]["required"] is True, name
        assert "relative to the piece" in INPUTS[name]["description"], name
    assert "-01.svg" in INPUTS["script"]["description"]
    assert "STEP" in INPUTS["part"]["description"]


def test_the_skill_validates_in_the_core_format() -> None:
    first, second, *rest = SKILL.split("---", 2)
    assert first == "" and second.strip().startswith("name:")
    frontmatter = second.strip().splitlines()
    assert "name: freecad" in frontmatter
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX
    body = rest[0]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)
    assert "freecad.drawing" in body


def test_the_readme_documents_the_host_contract_the_wrapper_and_the_rule() -> None:
    """The five things a person needs: host, key, version, wrapper, use cases."""
    assert "facet config set freecad.path" in READ
    assert "FREECAD_EXE" in READ
    assert "host-app" in READ
    assert MINIMUM in READ
    assert "machine_cannot" in READ
    assert "freecad_run.py" in READ
    assert "UtilAcceptVsock" in READ
    assert "Nothing is ever installed" in READ
    assert "TechDraw" in READ
    assert "cad" in READ
