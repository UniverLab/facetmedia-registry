"""The mermaid manifest: a node-engine package pinning mermaid-cli's closure.

The registry suite runs without the core, so every rule the core's
``manifest/node.py`` applies is asserted here as data: an npm name, a semver
version, an SRI integrity, a ``registry.npmjs.org`` tarball computed from the
name and version, the first row as the entry package, and the peer the range
walk needs. The capability is the image kind with the image viewer, the only
input is the ``.mmd`` file, and the index carries the package.
"""

from __future__ import annotations

import base64
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "mermaid"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
READ = (PACKAGE / "README.md").read_text(encoding="utf-8")
ENGINE = MANIFEST["engine"]["node"]
PINS = ENGINE["packages"]

#: The core's node grammar, repeated so the registry suite needs no core.
NAME_RE = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z")
SEMVER_RE = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z")
INTEGRITY_ALGOS = frozenset({"sha256", "sha384", "sha512"})
PIN_COUNT = 193
RAM_GB = 4
DISK_GB = 2
RUNTIME = "22.21.0"
RUNTIME_SHA256 = "262b84b02f7e2bc017d4bdb81fec85ca0d6190a5cd0781d2d6e84317c08871f8"
TEMPLATE = "{{node}} {{entry}} {{verb}} --input {{input}} --result {{result}}"


def _pin(name: str, version: str) -> dict[str, object] | None:
    """The first row naming ``name`` at ``version``, or ``None``."""
    for row in PINS:
        if row["name"] == name and row["version"] == version:
            return row
    return None


def _expected_tarball(name: str, version: str) -> str:
    """npm's tarball URL: a scoped name drops the scope in the file name."""
    base = name.rpartition("/")[2]
    return f"https://registry.npmjs.org/{name}/-/{base}-{version}.tgz"


def test_the_header_names_the_presentation_facet_and_the_pinned_contract() -> None:
    assert MANIFEST["name"] == "mermaid"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b1,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "presentation"
    assert "mermaid" in MANIFEST["tool_name"].lower() or "mermaid" in MANIFEST["provider"].lower()


def test_the_engine_is_node_with_the_shared_runtime() -> None:
    assert MANIFEST["engine"]["type"] == "node"
    assert ENGINE["runtime"] == RUNTIME
    assert ENGINE["runtime_sha256"] == RUNTIME_SHA256
    assert "python" not in MANIFEST["engine"]


def test_the_193_pins_are_the_resolved_closure() -> None:
    assert len(PINS) == PIN_COUNT
    assert PINS[0]["name"] == "@mermaid-js/mermaid-cli"
    assert PINS[0]["version"] == "12.0.0"
    names = [row["name"] for row in PINS]
    pairs = [(row["name"], row["version"]) for row in PINS]
    assert len(pairs) == len(set(pairs))
    for needed in ("mermaid", "puppeteer", "puppeteer-core", "katex", "commander"):
        assert needed in names, needed


def test_every_pin_meets_the_core_node_rules() -> None:
    """Name, semver, SRI integrity and the registry tarball rule, row by row."""
    for row in PINS:
        assert NAME_RE.fullmatch(row["name"]), row["name"]
        assert SEMVER_RE.fullmatch(row["version"]), row
        algo, sep, digest = str(row["integrity"]).partition("-")
        assert sep and algo in INTEGRITY_ALGOS, row
        base64.b64decode(digest, validate=True)
        assert row["tarball"] == _expected_tarball(row["name"], row["version"]), row


def test_the_closure_holds_the_peers_the_range_walk_needs() -> None:
    """mermaid-cli needs mermaid ^12 and puppeteer ^25; zenuml peers mermaid."""
    assert _pin("mermaid", "12.3.0") is not None
    assert _pin("puppeteer", "25.16.0") is not None
    assert _pin("puppeteer-core", "25.16.0") is not None
    assert _pin("@mermaid-js/mermaid-zenuml", "1.0.1") is not None
    assert _pin("@zenuml/core", "3.50.1") is not None


def test_no_browser_package_is_pinned() -> None:
    """chromium-bidi is a protocol library; no actual browser is pinned."""
    names = {row["name"] for row in PINS}
    assert not ({"chromium", "chrome", "playwright", "playwright-core"} & names)


def test_the_transport_stages_the_runner_with_the_node_template() -> None:
    transport = MANIFEST["transport"]
    assert transport["type"] == "cli"
    assert transport["entry"] == "runner.js"
    assert transport["invocation_template"] == TEMPLATE
    assert (PACKAGE / "runner.js").is_file()


def test_the_licenses_cover_the_tool_and_no_chromium() -> None:
    licenses = {(item["subject"], item["spdx"]) for item in MANIFEST["licenses"]}
    assert licenses == {("mermaid-cli", "MIT")}
    assert not any("chromium" in subject.lower() for subject, _ in licenses)


def test_the_requirements_fit_the_reference_machine() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is True
    assert requirements["platforms"] == ["linux"]


def test_the_capability_is_the_image_kind_with_the_mmd_input() -> None:
    capability = MANIFEST["capabilities"]["diagrama"]
    assert capability["kind"] == "image"
    assert capability["preview"] == {"viewer": "image"}
    inputs = capability["inputs"]
    assert set(inputs) == {"diagrama"}
    assert inputs["diagrama"]["type"] == "path"
    assert inputs["diagrama"]["required"] is True
    assert ".mmd" in inputs["diagrama"]["description"]


def test_the_index_carries_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "mermaid" in names


def test_the_readme_documents_the_contract_and_the_traps() -> None:
    for token in (
        "mermaid-cli",
        "fontFamily",
        "FACET_BROWSER",
        "PUPPETEER_SKIP_DOWNLOAD",
        "D2",
        "Excalidraw",
        "ciclo",
        "arquitectura",
        "architecture-beta",
        "runner_failed",
    ):
        assert token in READ, token
