"""The hyperframes manifest: the first node-engine package, its pins and its skill.

The registry suite runs without the core, so every rule the core's
``manifest/node.py`` applies is asserted here as data: an npm name, a semver
version, an SRI integrity, a ``registry.npmjs.org`` tarball computed from the
name and version, the first row as the entry package, and the peer the range
walk needs. The capability is the video kind, the preview viewer is the video
viewer, and the index carries the entry facet loads packages from.
"""

from __future__ import annotations

import base64
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "hyperframes"
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
#: The pinned closure the range walk resolved; ``string-width`` needs two rows.
PIN_COUNT = 71
STRING_WIDTH_ROWS = 2
RAM_GB = 4
DISK_GB = 2
RUNTIME = "22.21.0"
RUNTIME_SHA256 = "262b84b02f7e2bc017d4bdb81fec85ca0d6190a5cd0781d2d6e84317c08871f8"
TEMPLATE = "{{node}} {{entry}} {{verb}} --input {{input}} --result {{result}}"
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200


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


def test_the_header_names_the_video_facet_and_the_pinned_contract() -> None:
    assert MANIFEST["name"] == "hyperframes"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b1,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["provider"] == "HeyGen (hyperframes)"
    assert MANIFEST["tool_name"] == "HyperFrames"
    assert MANIFEST["facet"] == "video"
    assert "MP4" in MANIFEST["description"]


def test_the_engine_is_node_with_the_pinned_runtime_and_no_python() -> None:
    assert MANIFEST["engine"]["type"] == "node"
    assert ENGINE["runtime"] == RUNTIME
    assert ENGINE["runtime_sha256"] == RUNTIME_SHA256
    assert "python" not in MANIFEST["engine"]
    assert "browser" not in MANIFEST


def test_the_71_pins_are_the_resolved_closure() -> None:
    assert len(PINS) == PIN_COUNT
    assert PINS[0]["name"] == "hyperframes"
    assert PINS[0]["version"] == "0.8.143"
    widths = {row["version"] for row in PINS if row["name"] == "string-width"}
    assert widths == {"7.2.0", "8.3.0"}
    names = [row["name"] for row in PINS]
    assert names.count("string-width") == STRING_WIDTH_ROWS
    assert all(names.count(name) == 1 for name in set(names) - {"string-width"})


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
    """hyperframes needs giget ^3.2.0; the node-server peer needs hono ^4."""
    giget = _pin("giget", "3.3.1")
    hono = _pin("hono", "4.13.17")
    assert giget is not None
    assert hono is not None
    assert _pin("@hono/node-server", "2.1.6") is not None
    assert _pin("string-width", "7.2.0") is not None
    assert _pin("string-width", "8.3.0") is not None


def test_ffmpeg_static_never_lands_because_no_install_script_runs() -> None:
    names = {row["name"] for row in PINS}
    assert "ffmpeg-static" not in names
    assert "ffprobe-static" not in names


def test_the_transport_stages_the_runner_with_the_node_template() -> None:
    transport = MANIFEST["transport"]
    assert transport["type"] == "cli"
    assert transport["entry"] == "runner.js"
    assert transport["invocation_template"] == TEMPLATE
    assert (PACKAGE / "runner.js").is_file()


def test_the_licenses_cover_the_tool_and_the_notable_dependencies() -> None:
    licenses = {(item["subject"], item["spdx"]) for item in MANIFEST["licenses"]}
    assert licenses == {
        ("hyperframes", "Apache-2.0"),
        ("sharp", "Apache-2.0"),
        ("esbuild", "MIT"),
        ("puppeteer-core", "Apache-2.0"),
    }
    assert not any("chromium" in subject.lower() for subject, _ in licenses)


def test_the_requirements_fit_the_reference_machine() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is True
    assert requirements["platforms"] == ["linux"]


def test_the_capability_is_the_video_kind_with_the_piece_inputs() -> None:
    capability = MANIFEST["capabilities"]["render"]
    assert capability["kind"] == "video"
    assert capability["preview"] == {"viewer": "video"}
    inputs = capability["inputs"]
    assert set(inputs) == {"composicion", "audio", "prompt", "seed", "fps"}
    assert inputs["composicion"]["type"] == "path"
    assert inputs["composicion"]["required"] is True
    assert "index.tmpl" in inputs["composicion"]["description"]
    assert "preview" not in inputs
    assert inputs["audio"]["type"] == "array"
    assert inputs["audio"]["default"] == []
    assert inputs["audio"]["items"]["clip"]["type"] == "path"
    assert inputs["audio"]["items"]["clip"]["required"] is True
    assert inputs["prompt"]["type"] == "string"
    assert inputs["prompt"]["required"] is True
    assert inputs["seed"]["type"] == "integer"
    assert (inputs["seed"]["default"], inputs["seed"]["min"]) == (0, 0)
    assert inputs["fps"]["type"] == "integer"
    assert "required" not in inputs["fps"]


def test_loop_capability_declares_formats_and_reuses_render_inputs_shape() -> None:
    loop = MANIFEST["capabilities"]["loop"]
    assert loop["kind"] == "video"
    assert loop["preview"] == {"viewer": "video"}
    inputs = loop["inputs"]
    assert set(inputs) == {"composicion", "audio", "prompt", "seed", "fps", "format"}
    render_inputs = MANIFEST["capabilities"]["render"]["inputs"]
    for name in ("composicion", "audio", "prompt", "seed", "fps"):
        assert inputs[name] == render_inputs[name]
    fmt = inputs["format"]
    assert fmt["type"] == "enum"
    assert fmt["values"] == ["gif", "mov-alpha"]
    assert fmt["required"] is True


def test_the_index_carries_the_package_after_ffmpeg() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "hyperframes" in names
    assert names.index("hyperframes") == names.index("ffmpeg") + 1


def test_the_skill_stub_validates_in_the_core_format() -> None:
    first, second, *rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: hyperframes" in frontmatter
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX
    body = rest[0]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)
    assert "hyperframes.render" in body
    assert "hyperframes.narrado" in body


GIRO_SCALARS = {
    "orbita-radio": 9,
    "orbita-altura": 11,
    "orbita-desde": -0.9,
    "orbita-vuelta": 0.55,
    "centro-x": 3.0,
    "centro-y": 0.6,
    "centro-z": -2.25,
    "duracion": 8,
}


def test_giro_capability_declares_flat_scalars_only() -> None:
    """An orbita table or centro array would fail package load; only scalars ship."""
    giro = MANIFEST["capabilities"]["giro"]
    assert giro["kind"] == "video"
    assert giro["preview"] == {"viewer": "video"}
    inputs = giro["inputs"]
    assert set(inputs) == {
        "composicion",
        "modelo-glb",
        *GIRO_SCALARS,
        "prompt",
        "seed",
        "fps",
    }
    assert inputs["composicion"]["type"] == "path"
    assert inputs["composicion"]["required"] is True
    assert inputs["modelo-glb"]["type"] == "path"
    assert inputs["modelo-glb"]["required"] is True
    for name, default in GIRO_SCALARS.items():
        assert inputs[name]["type"] == "number", name
        assert inputs[name]["default"] == default, name
    assert inputs["prompt"]["type"] == "string"
    assert inputs["prompt"]["required"] is True
    assert (inputs["seed"]["default"], inputs["seed"]["min"]) == (0, 0)
    assert "required" not in inputs["fps"]
    assert all(field["type"] != "array" for field in inputs.values())


def test_narrado_capability_assembles_voice_music_and_subtitles() -> None:
    narrado = MANIFEST["capabilities"]["narrado"]
    assert narrado["kind"] == "video"
    assert narrado["preview"] == {"viewer": "video"}
    inputs = narrado["inputs"]
    assert set(inputs) == {
        "composicion",
        "voz",
        "musica",
        "subtitulos",
        "prompt",
        "seed",
        "fps",
    }
    assert inputs["composicion"]["type"] == "path"
    assert inputs["composicion"]["required"] is True
    voz = inputs["voz"]
    assert voz["type"] == "array"
    assert voz["required"] is True
    assert voz["min_items"] == 1
    assert voz["items"]["clip"]["type"] == "path"
    assert voz["items"]["clip"]["required"] is True
    for name in ("musica", "subtitulos"):
        assert inputs[name]["type"] == "path"
        assert inputs[name]["required"] is True
    assert inputs["prompt"]["type"] == "string"
    assert inputs["prompt"]["required"] is True
    assert (inputs["seed"]["default"], inputs["seed"]["min"]) == (0, 0)
    assert "required" not in inputs["fps"]


def test_the_readme_documents_the_contract_and_the_traps() -> None:
    assert RUNTIME in READ
    assert "0.8.143" in READ
    assert "HYPERFRAMES_BROWSER_PATH" in READ
    assert "[browser]" in READ
    assert "check" in READ
    assert "--workers 2" in READ
    assert "index.tmpl" in READ
    assert "timeline" in READ
    assert (
        "ffmpeg and ffprobe are required to encode video (sudo apt-get install -y ffmpeg)" in READ
    )
