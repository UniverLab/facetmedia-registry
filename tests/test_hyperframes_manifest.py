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
PILLARS = ("## Timeline rules", "## SVG id maps", "## Render limits")
CAPABILITIES = (
    "hyperframes.render",
    "hyperframes.loop",
    "hyperframes.diagram",
    "hyperframes.turntable",
    "hyperframes.character",
    "hyperframes.narrated",
)
REFERENCES = PACKAGE / "skill" / "references"
EXAMPLES = PACKAGE / "examples"
EXAMPLE_PIECES = ("render", "loop", "diagram", "turntable", "character", "narrated")
COMPOSITION_FILES = ("hyperframes.json", "index.tmpl", "build.mjs", "assets", "index.html")
RENDER_SUFFIXES = frozenset({".mp4", ".gif", ".mov", ".webm", ".mkv"})
#: A reference the skill cites, as ``references/<name>.md``.
REFERENCE_RE = re.compile(r"references/([a-z0-9][a-z0-9-]*)\.md")
#: The contracts the three pillars port verbatim from the lab.
SKILL_TOKENS = (
    "gsap.timeline({ paused: true })",
    "window.__timelines",
    "textContent",
    "snap",
    "{ selector, at, kind, dur }",
    "renderAt",
    "hf-seek",
    "event.detail.waitUntil",
    "/* GLB */",
    "/* TURNTABLE */",
    "/* MOUTHS */[]",
    "const AUDIO_START",
    "audio-start",
    "data-start",
    "<!-- SUBS -->",
    "<!-- AUDIOS -->",
    "{ start, end, text }",
    "data-duration",
    "ducking=true",
    "duck-db=-12.0",
    "target-lufs=-16.0",
    "my-svg-flowchart-",
    "my-svg-L_",
    "mouth-X",
    "mouth-H",
    "#mouth-X",
    ".mouth { opacity: 0; }",
    "--workers 2",
    "vendor/",
    "FACET_BROWSER",
    "ffmpeg",
    "ffprobe",
    "check",
)
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: The loudness target narrated and character normalise to, in LUFS, and its range.
TARGET_LUFS_DEFAULT = -14.0
TARGET_LUFS_MIN = -24
TARGET_LUFS_MAX = -9


def _skill_body() -> str:
    """The skill's body, after the front matter the core parses."""
    _first, _second, body = SKILL.split("---", 2)
    return body


def _section(body: str, heading: str) -> str:
    """One ``##`` section, up to the next ``##`` heading."""
    rest = body[body.index(heading) + len(heading) :]
    next_heading = re.search(r"\n## ", rest)
    return rest[: next_heading.start()] if next_heading else rest


def _example_inputs(name: str) -> dict[str, object]:
    data = tomllib.loads((EXAMPLES / f"{name}.toml").read_text(encoding="utf-8"))
    return data["inputs"]


def _example_paths(name: str, inputs: dict[str, object]) -> list[Path]:
    """Every path input and array clip a sample declares, resolved beside it."""
    found: list[Path] = []
    for key, field in MANIFEST["capabilities"][name]["inputs"].items():
        value = inputs.get(key)
        if value is None:
            continue
        if field.get("type") == "path":
            found.append(EXAMPLES / str(value))
        elif field.get("type") == "array" and "clip" in field.get("items", {}):
            for item in value if isinstance(value, list) else []:
                if isinstance(item, dict):
                    found.append(EXAMPLES / str(item["clip"]))
    return found


def _composition_dir(name: str) -> Path:
    folder = "basic" if name in {"render", "loop"} else name
    return EXAMPLES / folder / "composition"


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
    assert MANIFEST["version"] == "0.1.2"
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
        ("FFmpeg (BtbN static build)", "GPL-3.0-or-later"),
    }
    assert not any("chromium" in subject.lower() for subject, _ in licenses)


def test_the_ffmpeg_table_pins_the_operator_measured_build() -> None:
    assert MANIFEST["ffmpeg"] == {
        "version": "n8.1.3-27-g8dca1586f4",
        "url": "https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-10-31-12-59/ffmpeg-n8.1.3-27-g8dca1586f4-linux64-gpl-8.1.tar.xz",
        "sha256": "41e9c565594c390622cf968d82fa4135d9e9a11d06c1515644288cbc844e3380",
    }


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
    assert set(inputs) == {"composition", "audio", "prompt", "seed", "fps"}
    assert inputs["composition"]["type"] == "path"
    assert inputs["composition"]["required"] is True
    assert "index.tmpl" in inputs["composition"]["description"]
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
    assert set(inputs) == {"composition", "audio", "prompt", "seed", "fps", "format"}
    render_inputs = MANIFEST["capabilities"]["render"]["inputs"]
    for name in ("composition", "audio", "prompt", "seed", "fps"):
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
    for capability in CAPABILITIES:
        assert capability in body, capability
    for name in EXAMPLE_PIECES:
        assert (EXAMPLES / f"{name}.toml").is_file(), name


def test_the_three_pillars_sit_between_pieces_and_judging() -> None:
    """The skill teaches timelines, id maps and limits before the verdict."""
    body = _skill_body()
    pieces = body.index("## Pieces")
    judging = body.index("## Judging the result")
    positions = [body.index(pillar) for pillar in PILLARS]
    assert pieces < judging
    assert all(pieces < position < judging for position in positions)
    assert positions == sorted(positions)


def test_each_pillar_has_one_row_per_capability() -> None:
    """Every capability appears once under every pillar, not only in the intro."""
    body = _skill_body()
    for pillar in PILLARS:
        section = _section(body, pillar)
        for capability in CAPABILITIES:
            assert section.count(f"### {capability}") == 1, (pillar, capability)


def test_the_skill_ports_the_timeline_id_and_limit_contracts() -> None:
    """The snippets and ids are ported, not summarised away."""
    body = _skill_body()
    for token in SKILL_TOKENS:
        assert token in body, token


def test_every_reference_the_skill_cites_exists() -> None:
    """A cited reference that is not on disk sends the reader nowhere."""
    body = _skill_body()
    cited = set(REFERENCE_RE.findall(body))
    assert cited == {"composition", "timeline", "id-maps", "limits"}
    for name in cited:
        path = REFERENCES / f"{name}.md"
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_each_reference_covers_every_capability() -> None:
    """The three contract references carry one section per capability."""
    for name in ("timeline", "id-maps", "limits"):
        text = (REFERENCES / f"{name}.md").read_text(encoding="utf-8")
        for capability in CAPABILITIES:
            assert f"## {capability}" in text, (name, capability)


def test_the_six_example_pieces_parse_and_stay_inside_their_manifest_inputs() -> None:
    """A sample input is a key facet resolves for that capability, never a typo."""
    for name in EXAMPLE_PIECES:
        inputs = _example_inputs(name)
        declared = set(MANIFEST["capabilities"][name]["inputs"])
        assert set(inputs) <= declared, name


def test_every_example_input_path_resolves() -> None:
    """The samples ship beside their piece file; a dead path sends nobody anywhere."""
    for name in EXAMPLE_PIECES:
        for path in _example_paths(name, _example_inputs(name)):
            assert path.exists(), (name, path)


def test_every_example_ships_a_complete_composition() -> None:
    """Each sample is a composition, not a bare piece file."""
    for name in EXAMPLE_PIECES:
        comp = _composition_dir(name)
        for entry in COMPOSITION_FILES:
            assert (comp / entry).exists(), (name, entry)


def test_examples_carry_no_binary_renders() -> None:
    """Binary renders stay out of the repository; only inputs ship."""
    renders = [
        path
        for path in EXAMPLES.rglob("*")
        if path.is_file() and path.suffix.lower() in RENDER_SUFFIXES
    ]
    assert renders == []


TURNTABLE_SCALARS = {
    "orbit-radius": 9,
    "orbit-height": 11,
    "orbit-start": -0.9,
    "orbit-fraction": 0.55,
    "center-x": 3.0,
    "center-y": 0.6,
    "center-z": -2.25,
    "duration": 8,
}


def test_turntable_capability_declares_flat_scalars_only() -> None:
    """An orbit table or center array would fail package load; only scalars ship."""
    turntable = MANIFEST["capabilities"]["turntable"]
    assert turntable["kind"] == "video"
    assert turntable["preview"] == {"viewer": "video"}
    inputs = turntable["inputs"]
    assert set(inputs) == {
        "composition",
        "model-glb",
        *TURNTABLE_SCALARS,
        "prompt",
        "seed",
        "fps",
    }
    assert inputs["composition"]["type"] == "path"
    assert inputs["composition"]["required"] is True
    assert inputs["model-glb"]["type"] == "path"
    assert inputs["model-glb"]["required"] is True
    for name, default in TURNTABLE_SCALARS.items():
        assert inputs[name]["type"] == "number", name
        assert inputs[name]["default"] == default, name
    assert inputs["prompt"]["type"] == "string"
    assert inputs["prompt"]["required"] is True
    assert (inputs["seed"]["default"], inputs["seed"]["min"]) == (0, 0)
    assert "required" not in inputs["fps"]
    assert all(field["type"] != "array" for field in inputs.values())


def test_narrated_capability_assembles_voice_music_and_subtitles() -> None:
    narrated = MANIFEST["capabilities"]["narrated"]
    assert narrated["kind"] == "video"
    assert narrated["preview"] == {"viewer": "video"}
    inputs = narrated["inputs"]
    assert set(inputs) == {
        "composition",
        "voice",
        "music",
        "subtitles",
        "music-volume",
        "target-lufs",
        "prompt",
        "seed",
        "fps",
    }
    assert inputs["composition"]["type"] == "path"
    assert inputs["composition"]["required"] is True
    voice = inputs["voice"]
    assert voice["type"] == "array"
    assert voice["required"] is True
    assert voice["min_items"] == 1
    assert voice["items"]["clip"]["type"] == "path"
    assert voice["items"]["clip"]["required"] is True
    assert voice["items"]["start"]["type"] == "number"
    assert (voice["items"]["start"]["default"], voice["items"]["start"]["min"]) == (0, 0)
    volumen = inputs["music-volume"]
    assert volumen["type"] == "number"
    assert (volumen["default"], volumen["min"], volumen["max"]) == (0.25, 0, 1)
    target = inputs["target-lufs"]
    assert target["type"] == "number"
    assert target["default"] == TARGET_LUFS_DEFAULT
    assert (target["min"], target["max"]) == (TARGET_LUFS_MIN, TARGET_LUFS_MAX)
    assert "required" not in target
    for name in ("music", "subtitles"):
        assert inputs[name]["type"] == "path"
        assert inputs[name]["required"] is True
    assert inputs["prompt"]["type"] == "string"
    assert inputs["prompt"]["required"] is True
    assert (inputs["seed"]["default"], inputs["seed"]["min"]) == (0, 0)
    assert "required" not in inputs["fps"]


def test_character_capability_declares_the_loudness_target() -> None:
    target = MANIFEST["capabilities"]["character"]["inputs"]["target-lufs"]
    assert target["type"] == "number"
    assert target["default"] == TARGET_LUFS_DEFAULT
    assert (target["min"], target["max"]) == (TARGET_LUFS_MIN, TARGET_LUFS_MAX)
    assert "required" not in target


def test_the_readme_documents_the_contract_and_the_traps() -> None:
    assert RUNTIME in READ
    assert "0.8.143" in READ
    assert "FACET_BROWSER" in READ
    assert "[browser]" in READ
    assert "check" in READ
    assert "--workers 2" in READ
    assert "index.tmpl" in READ
    assert "timeline" in READ
    assert "[ffmpeg]" in READ
    assert "facet pull hyperframes" in READ


def _retired(prefix: str, *fragments: str) -> str:
    """Assemble a retired name at runtime.

    The acceptance greps scan the tests too, so the old literals never
    appear in this file's source; the runtime values are still exact.
    """
    return prefix + "".join(fragments)


OLD_CAPABILITIES = (
    _retired("hyperframes.", "dia", "grama"),
    _retired("hyperframes.", "giro"),
    _retired("hyperframes.", "personaje"),
    _retired("hyperframes.", "narrado"),
)
OLD_INPUTS = (
    "composicion",
    "diagrama-svg",
    "animacion",
    "modelo-glb",
    "orbita-radio",
    "orbita-altura",
    "orbita-desde",
    "orbita-vuelta",
    "centro-x",
    "centro-y",
    "centro-z",
    _retired("", "dura", "cion"),
    "personaje-svg",
    "audio-inicio",
    "volumen-musica",
    "bocas",
    "dialogo",
)


def test_old_spanish_names_are_absent() -> None:
    """The rename keeps no alias: the old ids and keys appear nowhere."""
    manifest_text = (PACKAGE / "package.toml").read_text(encoding="utf-8")
    for old in (*OLD_CAPABILITIES, *OLD_INPUTS):
        assert old not in manifest_text, old
    assert '"voz"' not in manifest_text
    for old in OLD_CAPABILITIES:
        assert old not in _skill_body(), old
        assert old not in READ, old
