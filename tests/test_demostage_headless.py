"""The demostage headless path: record, export, doctor, preview and the skill.

The test stands in for the person-installed ``demo`` binary: a stub on ``PATH``
logs every argv and cwd, writes the ``.rec`` from the score, and renders a
minimal gif and svg into the score's ``output_dir``. That proves the
record-before-export order, the ``gif,svg`` targets and both assets without a
real demo. The real headless probe (record exit 0, export svg/gif exit 0, no
TTY) is the contract test and runs only for the paste-back, behind
``DEMOSTAGE_REAL_PROBE=1``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "demostage"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
README = (PACKAGE / "README.md").read_text(encoding="utf-8")
VIDEO_SCHEMA: dict[str, Any] = json.loads(
    (ROOT / "schemas" / "preview" / "video.schema.json").read_text(encoding="utf-8")
)
IMAGE_SCHEMA: dict[str, Any] = json.loads(
    (ROOT / "schemas" / "preview" / "image.schema.json").read_text(encoding="utf-8")
)
HOST_HINT = "curl -fsSL https://get.univerlab.org/demostage | sh"
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
NAME = "cli-tour"
DESCRIPTION_MIN = 20
WIDTH = 1280
HEIGHT = 720
FPS = 15
FRAMES = 1
SEED = 42

#: The pull-time SDK surface the runner touches; the real one is copied in.
STUB_SDK = """
import json
import sys
from pathlib import Path


class Request:
    def __init__(self, data):
        self.verb = str(data.get("verb", ""))
        self.capability = str(data.get("capability", ""))
        self.depth = str(data.get("depth", "quick"))
        self.inputs = dict(data.get("inputs") or {})
        self.out_dir = Path(str(data.get("out_dir", "")))
        self.piece_dir = Path(str(data.get("piece_dir", "")))
        self.assets = [Path(str(item)) for item in data.get("assets") or []]
        self._models = {str(k): Path(str(v)) for k, v in (data.get("models") or {}).items()}

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def model_path(self, model_id):
        return self._models[model_id]


class Runner:
    def __init__(self):
        self._verbs = {}

    def verb(self, name):
        def register(function):
            self._verbs[name] = function
            return function

        return register

    def run(self, argv):
        verb, *rest = argv
        values = {rest[index]: rest[index + 1] for index in range(0, len(rest), 2)}
        result = self._verbs[verb](Request.from_file(values["--input"]))
        Path(values["--result"]).write_text(json.dumps(result))
        return 0

    def main(self):
        raise SystemExit(self.run(sys.argv[1:]))
"""

#: The stub demo. STUB_DEMO_LOG records argv/cwd, STUB_DEMO_VERSION and
#: STUB_DEMO_FAIL steer its answers, and it renders a 1280x720 single-frame gif.
STUB_DEMO = """#!__PYTHON__
import json
import os
import struct
import sys
import tomllib
from pathlib import Path


def _log():
    log = os.environ.get("STUB_DEMO_LOG")
    if not log:
        return
    entry = {"argv": sys.argv[1:], "cwd": os.getcwd()}
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry) + "\\n")


def _gif(width, height, delay):
    header = b"GIF89a"
    screen = struct.pack("<HH", width, height) + bytes([0x00, 0x00, 0x00])
    control = bytes([0x21, 0xF9, 0x04, 0x00]) + struct.pack("<H", delay) + bytes([0x00, 0x00])
    image = bytes([0x2C]) + struct.pack("<HHHH", 0, 0, width, height)
    image += bytes([0x00, 0x02, 0x02, 0x00, 0x00, 0x00, 0x3B])
    return header + screen + control + image


def _record(argv):
    score = tomllib.loads(Path(argv[0]).read_text(encoding="utf-8"))
    demo = score.get("demo", {})
    rec = {
        "name": demo.get("name", "demo"),
        "output_dir": demo.get("output_dir", "./dist"),
    }
    Path(argv[argv.index("-o") + 1]).write_text(json.dumps(rec), encoding="utf-8")
    return 0


def _export(argv):
    rec = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    folder = Path(rec["output_dir"])
    if not folder.is_absolute():
        folder = Path.cwd() / folder
    folder.mkdir(parents=True, exist_ok=True)
    name = rec["name"]
    (folder / (name + ".gif")).write_bytes(_gif(1280, 720, 10))
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"></svg>\\n'
    (folder / (name + ".svg")).write_text(svg, encoding="utf-8")
    return 0


def main():
    _log()
    args = sys.argv[1:]
    if args[:1] == ["--version"]:
        print("demo " + os.environ.get("STUB_DEMO_VERSION", "0.4.0"))
        return 0
    if os.environ.get("STUB_DEMO_FAIL") == "1":
        print("stub demo exploded", file=sys.stderr)
        return 3
    if args[:1] == ["record"]:
        return _record(args[1:])
    if args[:1] == ["export"]:
        return _export(args[1:])
    print("unknown verb", file=sys.stderr)
    return 2


raise SystemExit(main())
"""

REAL_SCORE = """[demo]
name = "demostage-probe"
output_dir = "./dist"

[typing]
base_ms = 10
salt_ms = 2
seed = 42

[layout]
width = 640
height = 360
fps = 15
font_family = "DejaVu Sans Mono"

[[layout.panes]]
id = "main"
type = "terminal"
x = 0
y = 0
width = 640
height = 360
font_size = 14

[[timeline]]
action = "focus"
pane = "main"

[[timeline]]
action = "type"
text = "echo hello"

[[timeline]]
action = "keypress"
key = "enter"

[[timeline]]
action = "wait_for_stdout"
match = "hello"

[[timeline]]
action = "terminate"
"""

REAL_PROBE = os.environ.get("DEMOSTAGE_REAL_PROBE") == "1" and shutil.which("demo") is not None


def _stubs(tmp_path: Path) -> tuple[Path, Path]:
    """The PYTHONPATH SDK stub and a PATH dir holding the stub ``demo``."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    (stub_dir / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    demo = bin_dir / "demo"
    demo.write_text(STUB_DEMO.replace("__PYTHON__", sys.executable), encoding="utf-8")
    demo.chmod(0o755)
    return stub_dir, bin_dir


def _environment(
    stub_dir: Path, bin_dir: Path, extra: dict[str, str] | None = None
) -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
    }
    if extra:
        env.update(extra)
    return env


def _piece(tmp_path: Path) -> tuple[Path, Path]:
    """A piece holding a hand-written score; returns the piece dir and score."""
    piece_dir = tmp_path / "piece"
    demo_dir = piece_dir / "demo"
    demo_dir.mkdir(parents=True)
    score = demo_dir / "demo.toml"
    score.write_text(
        f'[demo]\nname = "{NAME}"\noutput_dir = "./dist"\n\n'
        "[typing]\nseed = 42\n\n[layout]\nfps = 15\n\n"
        '[[timeline]]\naction = "terminate"\n',
        encoding="utf-8",
    )
    return piece_dir, score


def _request(
    verb: str,
    out: Path,
    piece: Path,
    inputs: dict[str, object],
    assets: tuple[Path, ...] = (),
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "demostage.demo",
        "depth": "quick",
        "inputs": dict(inputs),
        "out_dir": str(out),
        "piece_dir": str(piece),
        "assets": [str(path) for path in assets],
        "models": {},
    }


def _invoke(
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    env: dict[str, str],
    tag: str = "",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    input_path = tmp_path / f"{verb}{tag}-request.json"
    result_path = tmp_path / f"{verb}{tag}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            verb,
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return done, result_path


def _call(
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    env: dict[str, str],
    tag: str = "",
) -> dict[str, Any]:
    done, result_path = _invoke(verb, request, tmp_path, env, tag)
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8"))


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _run_cycle(
    tmp_path: Path, extra: dict[str, str] | None = None
) -> tuple[dict[str, Any], Path, list[dict[str, Any]], dict[str, str], Path]:
    """One run: its result, the score, the stub log, the env and the out dir."""
    stub_dir, bin_dir = _stubs(tmp_path)
    log = tmp_path / "demo.jsonl"
    settings = {"STUB_DEMO_LOG": str(log)}
    if extra:
        settings.update(extra)
    env = _environment(stub_dir, bin_dir, settings)
    piece_dir, score = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    result = _call(
        "run",
        _request("run", out, piece_dir, {"partitura": str(score)}),
        tmp_path,
        env,
    )
    return result, score, _read_lines(log), env, out


def test_run_records_then_exports_and_writes_both_assets(tmp_path: Path) -> None:
    result, score, entries, _env, out = _run_cycle(tmp_path)
    calls = [entry for entry in entries if entry["argv"][0] in {"record", "export"}]
    assert [entry["argv"][0] for entry in calls] == ["record", "export"]
    record, export = calls
    assert record["argv"][1] == str(score)
    assert record["argv"][record["argv"].index("-o") + 1].endswith("demo.rec")
    assert Path(record["cwd"]) == score.parent
    assert export["argv"][1] == "gif,svg"
    assert export["argv"][2].endswith("demo.rec")
    assert Path(export["cwd"]).name == "_demostage"

    gif, svg = result["assets"]
    assert (gif["file"], gif["kind"], gif["mime"]) == (f"{NAME}.gif", "video", "image/gif")
    assert (svg["file"], svg["kind"], svg["mime"]) == (
        f"{NAME}.svg",
        "image",
        "image/svg+xml",
    )
    assert (gif["name"], svg["name"]) == (NAME, NAME)
    assert gif["properties"]["width"] == WIDTH
    assert gif["properties"]["height"] == HEIGHT
    assert gif["properties"]["frames"] == FRAMES
    assert gif["properties"]["fps"] == FPS
    assert svg["properties"] == {"width": WIDTH, "height": HEIGHT}
    assert gif["seed"] == SEED and svg["seed"] == SEED
    assert gif["inputs"] == [str(score)] and svg["inputs"] == [str(score)]
    assert result["tool"] == {"name": "demostage", "version": "0.4.0"}
    assert (out / f"{NAME}.gif").is_file()
    assert (out / f"{NAME}.svg").is_file()


def test_a_failing_record_fails_the_run(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    env = _environment(stub_dir, bin_dir, {"STUB_DEMO_FAIL": "1"})
    piece_dir, score = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result_path = _invoke(
        "run",
        _request("run", out, piece_dir, {"partitura": str(score)}),
        tmp_path,
        env,
    )
    assert done.returncode != 0
    assert "exited 3" in done.stdout + done.stderr
    assert not result_path.exists()
    assert not (out / f"{NAME}.gif").exists()


def test_verify_reads_the_gif_and_svg_back(tmp_path: Path) -> None:
    result, _score, _entries, env, out = _run_cycle(tmp_path)
    assets = tuple(out / asset["file"] for asset in result["assets"])
    verdict = _call(
        "verify",
        _request("verify", out, out, {"partitura": str(_score)}, assets),
        tmp_path,
        env,
        tag="-verify",
    )
    assert [entry["passed"] for entry in verdict["assets"]] == [True, True]
    assert verdict["assets"][0]["metrics"]["frames"] == FRAMES
    assert verdict["assets"][1]["metrics"] == {"width": WIDTH, "height": HEIGHT}
    assert verdict["assets"][0]["verifier"] == "demostage"


def _assert_schema(data: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    """The preview schema's required keys, consts, patterns and minimums."""
    assert set(data) == set(schema["required"]), (set(data), set(schema["required"]))
    for key, rules in schema["properties"].items():
        value = data[key]
        if "const" in rules:
            assert value == rules["const"], key
        if rules.get("type") == "string":
            assert isinstance(value, str) and value, key
            if "pattern" in rules:
                assert re.fullmatch(rules["pattern"], value), (key, value)
        if rules.get("type") == "integer":
            assert isinstance(value, int) and value >= rules.get("minimum", 0), key
        if "maxLength" in rules:
            assert len(value) <= rules["maxLength"], key


def test_preview_writes_the_video_and_image_schemas(tmp_path: Path) -> None:
    result, score, _entries, env, out = _run_cycle(tmp_path)
    inputs = {"partitura": str(score)}
    gif = out / result["assets"][0]["file"]
    svg = out / result["assets"][1]["file"]

    preview = _call(
        "preview",
        _request("preview", out, out, inputs, (gif,)),
        tmp_path,
        env,
        tag="-preview-gif",
    )
    assert preview["assets"][0]["file"] == gif.name
    video = json.loads((out / f"{gif.name}.preview.json").read_text(encoding="utf-8"))
    _assert_schema(video, VIDEO_SCHEMA)
    assert video["kind"] == "video"
    assert video["name"] == gif.stem == result["assets"][0]["name"]
    assert (video["width"], video["height"], video["length"], video["fps"]) == (
        WIDTH,
        HEIGHT,
        FRAMES,
        FPS,
    )
    assert video["seed"] == SEED

    _call(
        "preview",
        _request("preview", out, out, inputs, (svg,)),
        tmp_path,
        env,
        tag="-preview-svg",
    )
    image = json.loads((out / f"{svg.name}.preview.json").read_text(encoding="utf-8"))
    _assert_schema(image, IMAGE_SCHEMA)
    assert image["kind"] == "image"
    assert image["name"] == svg.stem == result["assets"][1]["name"]
    assert (image["width"], image["height"]) == (WIDTH, HEIGHT)


def _doctor(tmp_path: Path, env: dict[str, str]) -> dict[str, Any]:
    out = tmp_path / "doctor-out"
    out.mkdir(exist_ok=True)
    result = _call(
        "doctor",
        _request("doctor", out, tmp_path / "piece", {}),
        tmp_path,
        env,
        tag="-doctor",
    )
    return {check["name"]: check for check in result["checks"]}


def test_doctor_passes_the_installed_demo(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    checks = _doctor(tmp_path, _environment(stub_dir, bin_dir))
    assert checks["demo"]["ok"] is True
    assert checks["demo"]["fix"] == ""
    assert "0.4.0" in checks["demo"]["detail"]


def test_doctor_reports_an_old_demo_with_the_install_hint(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    checks = _doctor(tmp_path, _environment(stub_dir, bin_dir, {"STUB_DEMO_VERSION": "0.3.0"}))
    assert checks["demo"]["ok"] is False
    assert checks["demo"]["fix"] == HOST_HINT
    assert "0.3.0" in checks["demo"]["detail"]
    assert "0.4.0" in checks["demo"]["detail"]


def test_doctor_reports_a_missing_demo_with_the_install_hint(tmp_path: Path) -> None:
    stub_dir, _bin_dir = _stubs(tmp_path)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    env = {**os.environ, "PYTHONPATH": str(stub_dir), "PATH": str(empty)}
    checks = _doctor(tmp_path, env)
    assert checks["demo"]["ok"] is False
    assert checks["demo"]["fix"] == HOST_HINT
    assert "not on PATH" in checks["demo"]["detail"]


def _front_matter() -> tuple[dict[str, str], str]:
    first, second, *rest = SKILL.split("---", 2)
    assert first == "" and second.strip().startswith("name:")
    meta = {}
    for line in second.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, rest[0]


def test_the_skill_front_matter_and_headings() -> None:
    meta, body = _front_matter()
    assert meta["name"] == "demostage"
    assert len(meta["description"]) >= DESCRIPTION_MIN
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_skill_teaches_the_headless_loop_and_the_dsl() -> None:
    _meta, body = _front_matter()
    assert "demostage.demo" in body
    assert "partitura" in body
    for action in ("focus", "type", "keypress", "wait_for_stdout", "terminate"):
        assert action in body, action
    assert body.index("record") < body.index("export")
    assert "capture" in body
    assert "interactive terminal" in body
    assert "TTY" in body
    assert "seed" in body and "font" in body


def test_the_readme_states_the_headless_path_and_the_exclusion() -> None:
    assert "demo record" in README
    assert "demo export" in README
    assert HOST_HINT in README
    assert "cargo install --path ." in README
    assert "capture" in README
    assert "TTY" in README
    assert "python-env" in README
    assert "engine.binary" in README


def test_the_manifest_is_a_headless_python_env_client() -> None:
    assert MANIFEST["name"] == "demostage"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["facet"] == "video"
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    assert "binary" not in MANIFEST["engine"]
    assert "models" not in MANIFEST
    assert MANIFEST["requirements"]["host_hint"] == HOST_HINT
    assert MANIFEST["requirements"]["gpu"] is False
    assert MANIFEST["requirements"]["exclusive"] is True
    assert MANIFEST["requirements"]["platforms"] == ["linux"]


def test_the_capability_takes_a_score_and_previews_video() -> None:
    capability = MANIFEST["capabilities"]["demo"]
    assert capability["kind"] == "video"
    assert capability["preview"] == {"viewer": "video"}
    inputs = capability["inputs"]
    assert set(inputs) == {"partitura"}
    assert inputs["partitura"]["type"] == "path"
    assert inputs["partitura"]["required"] is True
    assert "hand-written" in inputs["partitura"]["description"].lower()
    assert MANIFEST["licenses"] == [{"subject": "demostage", "spdx": "MIT"}]


def test_the_package_is_registered_and_is_its_own_uv_project() -> None:
    assert "demostage" in [package["name"] for package in INDEX["packages"]]
    assert (PACKAGE / "pyproject.toml").is_file()
    assert (PACKAGE / "uv.lock").is_file()


@pytest.mark.skipif(
    not REAL_PROBE,
    reason="real demo probe: set DEMOSTAGE_REAL_PROBE=1 (paste-back only)",
)
def test_real_headless_probe_records_and_exports_without_a_tty(tmp_path: Path) -> None:
    """Intelligence 66100863: record exit 0, export svg/gif exit 0, no TTY."""
    binary = shutil.which("demo")
    assert binary is not None
    piece = tmp_path / "demo"
    piece.mkdir()
    score = piece / "demo.toml"
    score.write_text(REAL_SCORE, encoding="utf-8")
    recording = piece / "demo.rec"
    record = subprocess.run(
        [binary, "record", str(score), "-o", str(recording)],
        cwd=piece,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert record.returncode == 0, record.stdout + record.stderr
    assert recording.is_file()
    for target in ("svg", "gif"):
        done = subprocess.run(
            [binary, "export", target, str(recording)],
            cwd=piece,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        assert done.returncode == 0, (target, done.stdout, done.stderr)
        assert (piece / "dist" / f"demostage-probe.{target}").is_file(), target
