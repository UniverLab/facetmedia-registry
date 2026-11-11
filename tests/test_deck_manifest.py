"""The deck manifest: a document-kind node package pinned to the shared browser.

The registry suite runs without the core, so every rule the core's
``manifest/node.py`` applies is asserted here as data: an npm name, a semver
version, an SRI integrity, a ``registry.npmjs.org`` tarball computed from the
name and version, and the first row as the entry package. The capability is the
document kind with the generic viewer, and the index carries the entry facet
loads packages from.
"""

from __future__ import annotations

import base64
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "deck"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
READ = (PACKAGE / "README.md").read_text(encoding="utf-8")
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
ENGINE = MANIFEST["engine"]["node"]
PINS = ENGINE["packages"]

#: The core's node grammar, repeated so the registry suite needs no core.
NAME_RE = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z")
SEMVER_RE = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z")
INTEGRITY_ALGOS = frozenset({"sha256", "sha384", "sha512"})
NPM_HOST = "registry.npmjs.org"
RUNTIME = "22.21.0"
RUNTIME_SHA256 = "262b84b02f7e2bc017d4bdb81fec85ca0d6190a5cd0781d2d6e84317c08871f8"
PLAYWRIGHT = "playwright-core"
PLAYWRIGHT_VERSION = "1.64.0"
PLAYWRIGHT_INTEGRITY = (
    "sha512-T9r+MZkTECl2+oUcZ26YgZzTrYidTsIhYYkJix+6iDOymOb1FB2RLLSOxRGnZGv5D"
    "Stt+aduIVbt+E8WygXYpg=="
)
PDFJS = "pdfjs-dist"
PDFJS_VERSION = "3.11.174"
PDFJS_INTEGRITY = (
    "sha512-TdTZPf1trZ8/UFu5Cx/GXB7GZM30LT+wWUNfsi6Bq8ePLnb+woNKtDymI2mxZYBpMbo"
    "nNFqKmiz684DIfnd8dA=="
)
RAM_GB = 4
DISK_GB = 2
TEMPLATE = "{{node}} {{entry}} {{verb}} --input {{input}} --result {{result}}"
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
PIN_COUNT = 2


def _expected_tarball(name: str, version: str) -> str:
    """npm's tarball URL: a scoped name drops the scope in the file name."""
    base = name.rpartition("/")[2]
    return f"https://registry.npmjs.org/{name}/-/{base}-{version}.tgz"


def test_the_header_names_the_presentation_facet_and_the_pinned_contract() -> None:
    assert MANIFEST["name"] == "deck"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b1,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["provider"] == "facet"
    assert MANIFEST["tool_name"] == "Deck"
    assert MANIFEST["facet"] == "presentation"
    assert "PDF" in MANIFEST["description"]


def test_the_engine_is_node_with_the_shared_runtime_and_no_python() -> None:
    assert MANIFEST["engine"]["type"] == "node"
    assert ENGINE["runtime"] == RUNTIME
    assert ENGINE["runtime_sha256"] == RUNTIME_SHA256
    assert "python" not in MANIFEST["engine"]


def test_the_closure_pins_playwright_core_and_pdfjs_dist() -> None:
    assert len(PINS) == PIN_COUNT
    entry = PINS[0]
    assert entry["name"] == PLAYWRIGHT
    assert entry["version"] == PLAYWRIGHT_VERSION
    assert entry["version"].startswith("1.64.")
    assert entry["tarball"] == _expected_tarball(PLAYWRIGHT, PLAYWRIGHT_VERSION)
    assert entry["integrity"] == PLAYWRIGHT_INTEGRITY
    pdfjs = PINS[1]
    assert pdfjs["name"] == PDFJS
    assert pdfjs["version"] == PDFJS_VERSION
    assert pdfjs["tarball"] == _expected_tarball(PDFJS, PDFJS_VERSION)
    assert pdfjs["integrity"] == PDFJS_INTEGRITY


def test_every_pin_meets_the_core_node_rules() -> None:
    """Name, semver, SRI integrity and the registry tarball rule, row by row."""
    for row in PINS:
        assert NAME_RE.fullmatch(row["name"]), row["name"]
        assert SEMVER_RE.fullmatch(row["version"]), row
        algo, sep, digest = str(row["integrity"]).partition("-")
        assert sep and algo in INTEGRITY_ALGOS, row
        base64.b64decode(digest, validate=True)
        assert row["tarball"] == _expected_tarball(row["name"], row["version"]), row


def test_the_transport_stages_the_runner_with_the_node_template() -> None:
    transport = MANIFEST["transport"]
    assert transport["type"] == "cli"
    assert transport["entry"] == "runner.js"
    assert transport["invocation_template"] == TEMPLATE
    assert (PACKAGE / "runner.js").is_file()


def test_the_licenses_name_both_pins_and_never_chromium() -> None:
    licenses = {(item["subject"], item["spdx"]) for item in MANIFEST["licenses"]}
    assert licenses == {(PLAYWRIGHT, "Apache-2.0"), (PDFJS, "Apache-2.0")}
    assert not any("chromium" in subject.lower() for subject, _ in licenses)


def test_the_requirements_are_the_lab_machine_with_no_host_libs() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is False
    assert requirements["platforms"] == ["linux"]
    assert "host_libs" not in requirements


def test_the_capability_is_the_document_kind_with_the_slide_inputs() -> None:
    capability = MANIFEST["capabilities"]["slides"]
    assert capability["kind"] == "document"
    assert capability["preview"] == {"viewer": "generic"}
    inputs = capability["inputs"]
    assert set(inputs) == {"source", "prompt", "seed"}
    assert inputs["source"]["type"] == "path"
    assert inputs["source"]["required"] is True
    assert "@page" in inputs["source"]["description"]
    assert inputs["prompt"]["type"] == "string"
    assert inputs["prompt"]["required"] is True
    assert inputs["seed"]["type"] == "integer"
    assert (inputs["seed"]["default"], inputs["seed"]["min"]) == (0, 0)


def test_the_page_capability_is_the_document_kind_with_the_piece_inputs() -> None:
    capability = MANIFEST["capabilities"]["page"]
    assert capability["kind"] == "document"
    assert capability["preview"] == {"viewer": "generic"}
    inputs = capability["inputs"]
    assert set(inputs) == {"source", "prompt", "seed"}
    assert inputs["source"]["type"] == "path"
    assert inputs["source"]["required"] is True
    assert inputs["prompt"]["type"] == "string"
    assert inputs["prompt"]["required"] is True
    assert inputs["seed"]["type"] == "integer"
    assert (inputs["seed"]["default"], inputs["seed"]["min"]) == (0, 0)


def test_the_index_carries_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "deck" in names
    assert names.count("deck") == 1


def test_the_presenter_capability_orders_notes_by_page() -> None:
    capability = MANIFEST["capabilities"]["presenter"]
    assert capability["kind"] == "document"
    assert capability["preview"] == {"viewer": "generic"}
    inputs = capability["inputs"]
    assert set(inputs) == {"source", "notes"}
    assert inputs["source"]["type"] == "path"
    assert inputs["source"]["required"] is True
    assert inputs["notes"]["type"] == "array"
    assert inputs["notes"]["required"] is True
    assert inputs["notes"]["min_items"] == 1
    items = inputs["notes"]["items"]
    assert set(items) == {"page", "text"}
    assert items["page"]["type"] == "integer"
    assert items["page"]["required"] is True
    assert items["page"]["min"] == 1
    assert items["text"]["type"] == "string"
    assert items["text"]["required"] is True


def test_the_presenter_files_ship_beside_the_runner() -> None:
    css_file = PACKAGE / "presenter" / "runner.css"
    js_file = PACKAGE / "presenter" / "runner.js"
    assert css_file.is_file()
    assert js_file.is_file()
    css = css_file.read_text(encoding="utf-8")
    js = js_file.read_text(encoding="utf-8")
    assert ".pz-grid" in css
    assert "window.__PZ_NOTES__" in js
    assert "pz-presenter" in js


def test_the_raster_files_ship_beside_the_runner() -> None:
    assert (PACKAGE / "raster.js").is_file()
    assert (PACKAGE / "pdfgrab.html").is_file()


def test_the_presenter_runner_reports_the_manifest_version() -> None:
    runner = (PACKAGE / "runner.js").read_text(encoding="utf-8")
    found = re.search(r'const PACKAGE_VERSION = "([^"]+)";', runner)
    assert found is not None
    assert found.group(1) == MANIFEST["version"]


def test_the_skill_names_the_presenter_capability() -> None:
    assert "deck.slides" in SKILL
    assert "deck.page" in SKILL
    assert "deck.presenter" in SKILL


def test_the_examples_ship_the_approved_print_piece() -> None:
    for suffix in ("html", "pdf", "png"):
        assert (PACKAGE / "examples" / f"modelos-de-lenguaje.{suffix}").is_file(), suffix


def test_the_readme_documents_the_presenter_runner() -> None:
    assert "## The presenter runner" in READ
    assert "deck.presenter" in READ
    assert ".present.html" in READ
    assert ".notes.md" in READ
    assert "`--open` flag stays out" in READ


def test_the_skill_stub_validates_in_the_core_format() -> None:
    first, second, *rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: deck" in frontmatter
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX
    body = rest[0]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)
    assert "deck.slides" in body


def test_the_readme_documents_the_format_outputs_and_host_contract() -> None:
    assert RUNTIME in READ
    assert PLAYWRIGHT_VERSION in READ
    assert "@page" in READ
    assert "preferCSSPageSize" in READ
    assert "page-01.png" in READ
    assert "FACET_BROWSER" in READ
    assert PDFJS in READ
    assert "pdfgrab.html" in READ
    assert "poppler" not in READ
    assert "pdftoppm" not in READ
    assert "[browser]" in READ
