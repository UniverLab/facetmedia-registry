"""The svganim manifest: a node-engine package pinning opentype.js and sharp.

The registry suite runs without the core, so every rule the core's
``manifest/node.py`` applies is asserted here as data: an npm name, a semver
version, an SRI integrity, a ``registry.npmjs.org`` tarball computed from the
name and version, the first row as the entry package, and the sharp closure
the range walk needs. The capability is the image kind with the image viewer,
its two inputs are paths, and the index carries the package.
"""

from __future__ import annotations

import base64
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "svganim"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
READ = (PACKAGE / "README.md").read_text(encoding="utf-8")
RUNNER = (PACKAGE / "runner.js").read_text(encoding="utf-8")
ENGINE = MANIFEST["engine"]["node"]
PINS = ENGINE["packages"]

#: The core's node grammar, repeated so the registry suite needs no core.
NAME_RE = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z")
SEMVER_RE = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z")
INTEGRITY_ALGOS = frozenset({"sha256", "sha384", "sha512"})
PIN_COUNT = 7
RAM_GB = 2
DISK_GB = 1
RUNTIME = "22.21.0"
RUNTIME_SHA256 = "262b84b02f7e2bc017d4bdb81fec85ca0d6190a5cd0781d2d6e84317c08871f8"
TEMPLATE = "{{node}} {{entry}} {{verb}} --input {{input}} --result {{result}}"

#: The seven pinned rows, in the manifest's order, exactly as resolved.
EXPECTED_ORDER = (
    "opentype.js",
    "sharp",
    "semver",
    "detect-libc",
    "@img/colour",
    "@img/sharp-libvips-linux-x64",
    "@img/sharp-linux-x64",
)
EXPECTED_PINS = {
    "opentype.js": (
        "2.0.0",
        "sha512-kCyjv6xdDY1W/jLWZ/L3QhhTlKUqDZMQ5+Jdlw12b3dXkKNpYBqqlMMj0YDQPShWF"
        "TMwgZI1hG14kN3XUDSg/A==",
    ),
    "sharp": (
        "0.35.5",
        "sha512-Ywn4OnzGukp7CDMrp08RQ50YKmuwG47brZgIVPTvBaaAfQlRlygrRqSrxdCi"
        "L9M+LlzLBiJ68IR1QqvzHyjC7g==",
    ),
    "semver": (
        "7.8.6",
        "sha512-9lpSSU4Mly3mrtruwLs1eLK6+gzbzqeBFwRNjIjE+9LuDpWdYctrQlQ3ej1Ilgi"
        "7gknpsTRnPoLP8DpCHqHIJw==",
    ),
    "detect-libc": (
        "2.1.2",
        "sha512-Btj2BOOO83o3WyH59e8MgXsxEQVcarkUOpEYrubB0urwnN10yQ364rsiByU11"
        "nZlqWYZm05i/of7io4mzihBtQ==",
    ),
    "@img/colour": (
        "1.1.0",
        "sha512-Td76q7j57o/tLVdgS746cYARfSyxk8iEfRxewL9h4OMzYhbW4TAcppl0mT4eyq"
        "Xddh6L/jwoM75mo7ixa/pCeQ==",
    ),
    "@img/sharp-libvips-linux-x64": (
        "1.3.4",
        "sha512-GJ//SSXbnwSDes02umB3nDJLFcQzw8a18V8fyhqr6tV515tOEMdImjjxj1AoafMRz56"
        "F3PHgftnj1QEKSU1zkw==",
    ),
    "@img/sharp-linux-x64": (
        "0.35.5",
        "sha512-SxFtLTeJInhAA9Q836kux2vZNeOBQEx658qvbboZScr0wIARym3IcGmW7KpVD5sbVg0"
        "Ojy+udFQdayYIZyoNog==",
    ),
}


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


def test_the_header_names_the_image_facet_and_the_pinned_contract() -> None:
    assert MANIFEST["name"] == "svganim"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b1,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "image"
    assert MANIFEST["tool_name"] == "svganim"
    assert "svganim" in MANIFEST["provider"].lower()


def test_the_engine_is_node_with_the_shared_runtime_and_no_browser() -> None:
    assert MANIFEST["engine"]["type"] == "node"
    assert ENGINE["runtime"] == RUNTIME
    assert ENGINE["runtime_sha256"] == RUNTIME_SHA256
    assert "python" not in MANIFEST["engine"]
    assert "browser" not in MANIFEST
    assert "CHROME_PATH" not in RUNNER
    assert "CHROME_PATH" not in READ


def test_the_exactly_seven_pins_are_the_spec_closure_in_order() -> None:
    assert len(PINS) == PIN_COUNT
    assert tuple(row["name"] for row in PINS) == EXPECTED_ORDER
    assert PINS[0]["name"] == "opentype.js"
    pairs = [(row["name"], row["version"]) for row in PINS]
    assert len(pairs) == len(set(pairs))
    for name, (version, integrity) in EXPECTED_PINS.items():
        row = _pin(name, version)
        assert row is not None, name
        assert row["integrity"] == integrity, name
        assert row["tarball"] == _expected_tarball(name, version), name


def test_every_pin_meets_the_core_node_rules() -> None:
    """Name, semver, SRI integrity and the registry tarball rule, row by row."""
    for row in PINS:
        assert NAME_RE.fullmatch(row["name"]), row["name"]
        assert SEMVER_RE.fullmatch(row["version"]), row
        algo, sep, digest = str(row["integrity"]).partition("-")
        assert sep and algo in INTEGRITY_ALGOS, row
        base64.b64decode(digest, validate=True)
        assert row["tarball"] == _expected_tarball(row["name"], row["version"]), row


def test_the_closure_holds_the_sharp_rows_the_range_walk_needs() -> None:
    """require('sharp') resolves only with the API package and its dependencies."""
    assert _pin("sharp", "0.35.5") is not None
    assert _pin("semver", "7.8.6") is not None
    assert _pin("detect-libc", "2.1.2") is not None
    assert _pin("@img/colour", "1.1.0") is not None
    assert _pin("@img/sharp-libvips-linux-x64", "1.3.4") is not None
    assert _pin("@img/sharp-linux-x64", "0.35.5") is not None


def test_no_browser_package_is_pinned() -> None:
    names = {row["name"] for row in PINS}
    assert not ({"chromium", "chrome", "puppeteer", "playwright"} & names)


def test_the_transport_stages_the_runner_with_the_node_template() -> None:
    transport = MANIFEST["transport"]
    assert transport["type"] == "cli"
    assert transport["entry"] == "runner.js"
    assert transport["invocation_template"] == TEMPLATE
    assert (PACKAGE / "runner.js").is_file()


def test_the_licenses_cover_the_tool_and_sharp() -> None:
    licenses = {(item["subject"], item["spdx"]) for item in MANIFEST["licenses"]}
    assert licenses == {("opentype.js", "MIT"), ("sharp", "Apache-2.0")}


def test_the_requirements_fit_the_reference_machine() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is True
    assert requirements["platforms"] == ["linux"]


def test_the_capability_is_the_image_kind_with_two_path_inputs() -> None:
    capability = MANIFEST["capabilities"]["bake"]
    assert capability["kind"] == "image"
    assert capability["preview"] == {"viewer": "image"}
    inputs = capability["inputs"]
    assert set(inputs) == {"guion", "datos"}
    for name in ("guion", "datos"):
        assert inputs[name]["type"] == "path", name
        assert inputs[name]["required"] is True, name
    assert "Node script" in inputs["guion"]["description"]
    assert "argv[2]" in inputs["datos"]["description"]


def test_the_index_carries_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "svganim" in names


def test_the_readme_documents_the_contract_and_the_escalation() -> None:
    for token in (
        "opentype.js",
        "sharp",
        "@keyframes",
        "<path>",
        "density: 144",
        "runner_failed",
        "HyperFrames",
        "guion",
        "datos",
        "NODE_PATH",
    ):
        assert token in READ, token
    assert "when to escalate to video" in READ.lower()
