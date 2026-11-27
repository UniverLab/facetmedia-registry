"""The vtracer runner against a stub SDK and a stub vtracer, no wheel install.

The runner is a subprocess of the host ``python``. Its ``PYTHONPATH``
carries a stub ``facet_runner_sdk`` (the pull-time SDK surface) and a stub
``vtracer`` module whose ``convert_image_to_svg_py`` records its keyword
arguments and writes a minimal namespaced SVG — or garbage, or a
path-less SVG, depending on ``VTRACER_STUB_MODE`` — so the test can prove
the run record, the option plumbing, the previews, the verify verdicts
and both doctor depths without the real wheel.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import PIL.Image

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "vtracer"
RUNNER = PACKAGE / "runner.py"
FIXTURE_SIZE = 32
FIXTURE_SPLIT = FIXTURE_SIZE // 2
LEFT = (200, 30, 30)
RIGHT = (30, 60, 200)
SPECKLE = 8
PRECISION = 3
DEFAULT_SPECKLE = 4
DEFAULT_PRECISION = 6
PREVIEW_FIELDS = {
    "preview",
    "kind",
    "summary",
    "name",
    "prompt",
    "seed",
    "width",
    "height",
}

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

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))


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

#: A deterministic vtracer: records its kwargs, writes a minimal SVG.
#: VTRACER_STUB_MODE picks the payload: ok (one path), empty (no paths),
#: garbage (not XML at all).
STUB_VTRACER = """
import json
import os
from pathlib import Path

__version__ = "0.6.15"
LOG = os.environ.get("VTRACER_STUB_LOG", "")
MODE = os.environ.get("VTRACER_STUB_MODE", "ok")


def convert_image_to_svg_py(image_path, out_path, **kwargs):
    if LOG:
        Path(LOG).write_text(json.dumps({"image": image_path, "out": out_path} | kwargs))
    if MODE == "garbage":
        Path(out_path).write_bytes(b"not xml at all")
    elif MODE == "empty":
        Path(out_path).write_text(
            '<svg version="1.1" xmlns="http://www.w3.org/2000/svg"></svg>',
            encoding="utf-8",
        )
    else:
        Path(out_path).write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg version="1.1" xmlns="http://www.w3.org/2000/svg">'
            '<path d="M0,0L32,0L32,32L0,32Z"/></svg>',
            encoding="utf-8",
        )
"""


def _stub_modules(tmp_path: Path, *, vtracer: bool = True) -> Path:
    """A directory holding the stub SDK (and the stub vtracer), for PYTHONPATH."""
    folder = tmp_path / "stub-modules"
    folder.mkdir(exist_ok=True)
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    stub = folder / "vtracer.py"
    if vtracer:
        stub.write_text(STUB_VTRACER, encoding="utf-8")
    else:
        stub.unlink(missing_ok=True)
    return folder


def _piece(tmp_path: Path) -> Path:
    """The piece dir with a crisp 32x32 two-block raster to trace."""
    piece = tmp_path / "piece"
    piece.mkdir(exist_ok=True)
    image = PIL.Image.new("RGB", (FIXTURE_SIZE, FIXTURE_SIZE))
    pixels = image.load()
    assert pixels is not None
    for y in range(FIXTURE_SIZE):
        for x in range(FIXTURE_SIZE):
            pixels[x, y] = LEFT if x < FIXTURE_SPLIT else RIGHT
    image.save(piece / "fixture.png")
    return piece


def _request(
    verb: str,
    out_dir: Path,
    piece_dir: Path,
    assets: tuple[Path, ...] = (),
    inputs: dict[str, object] | None = None,
    depth: str = "quick",
) -> dict[str, object]:
    if inputs is None:
        inputs = {"image": "fixture.png", "name": "fixture"}
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "vtracer.trace",
        "depth": depth,
        "inputs": inputs,
        "out_dir": str(out_dir),
        "piece_dir": str(piece_dir),
        "assets": [str(path) for path in assets],
    }


def _call(
    stub_dir: Path,
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    env: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    input_path = tmp_path / f"{verb}-request.json"
    result_path = tmp_path / f"{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
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
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return done, result


def _environment(stub_dir: Path, tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "VTRACER_STUB_LOG": str(tmp_path / "vtracer-args.json"),
        "VTRACER_STUB_MODE": os.environ.get("VTRACER_STUB_MODE", "ok"),
    }


def _run_ok(
    tmp_path: Path, inputs: dict[str, object] | None = None
) -> tuple[Path, Path, dict[str, Any]]:
    """A passing run: the out dir, the piece dir and the decoded result."""
    stub_dir = _stub_modules(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    piece = _piece(tmp_path)
    done, _result = _call(
        stub_dir,
        "run",
        _request("run", out_dir, piece, inputs=inputs),
        tmp_path,
        _environment(stub_dir, tmp_path),
    )
    assert done.returncode == 0, done.stderr
    result_path = tmp_path / "run-result.json"
    return out_dir, piece, json.loads(result_path.read_text(encoding="utf-8"))


def test_run_traces_the_raster_into_a_named_svg(tmp_path: Path) -> None:
    out_dir, _piece_dir, result = _run_ok(tmp_path)
    assert result is not None
    assert result["tool"]["name"] == "VTracer"
    (asset,) = result["assets"]
    assert asset["file"] == "fixture.svg"
    assert asset["name"] == "fixture"
    assert asset["kind"] == "image"
    assert asset["mime"] == "image/svg+xml"
    assert asset["properties"] == {"width": 32, "height": 32}
    assert asset["seed"] == 0
    assert asset["inputs"] == ["fixture.png"]
    assert (out_dir / "fixture.svg").is_file()


def test_run_passes_the_options_through_to_vtracer(tmp_path: Path) -> None:
    _out_dir, _piece_dir, result = _run_ok(
        tmp_path,
        {
            "image": "fixture.png",
            "name": "logo",
            "colormode": "binary",
            "mode": "polygon",
            "filter-speckle": SPECKLE,
            "color-precision": PRECISION,
        },
    )
    assert result is not None
    (asset,) = result["assets"]
    assert asset["file"] == "logo.svg"
    assert asset["params"]["colormode"] == "binary"
    assert asset["params"]["mode"] == "polygon"
    recorded = json.loads((tmp_path / "vtracer-args.json").read_text(encoding="utf-8"))
    assert recorded["colormode"] == "binary"
    assert recorded["mode"] == "polygon"
    assert recorded["filter_speckle"] == SPECKLE
    assert recorded["color_precision"] == PRECISION


def test_run_defaults_match_the_manifest(tmp_path: Path) -> None:
    _out_dir, _piece_dir, _result = _run_ok(tmp_path)
    recorded = json.loads((tmp_path / "vtracer-args.json").read_text(encoding="utf-8"))
    assert recorded["colormode"] == "color"
    assert recorded["mode"] == "spline"
    assert recorded["filter_speckle"] == DEFAULT_SPECKLE
    assert recorded["color_precision"] == DEFAULT_PRECISION


def _run_fails(tmp_path: Path, inputs: dict[str, object]) -> None:
    stub_dir = _stub_modules(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    piece = _piece(tmp_path)
    done, result = _call(
        stub_dir,
        "run",
        _request("run", out_dir, piece, inputs=inputs),
        tmp_path,
        _environment(stub_dir, tmp_path),
    )
    assert done.returncode != 0
    assert result is None


def test_run_rejects_a_missing_image(tmp_path: Path) -> None:
    _run_fails(tmp_path, {"image": "absent.png", "name": "fixture"})


def test_run_rejects_an_unsupported_suffix(tmp_path: Path) -> None:
    piece = _piece(tmp_path)
    (piece / "notes.txt").write_text("not an image", encoding="utf-8")
    _run_fails(tmp_path, {"image": "notes.txt", "name": "fixture"})


def test_run_rejects_a_missing_or_bad_name(tmp_path: Path) -> None:
    _run_fails(tmp_path, {"image": "fixture.png"})
    _run_fails(tmp_path, {"image": "fixture.png", "name": "NOT A NAME"})


def test_run_rejects_unknown_enums_and_out_of_range_integers(tmp_path: Path) -> None:
    base: dict[str, object] = {"image": "fixture.png", "name": "fixture"}
    _run_fails(tmp_path, base | {"colormode": "sepia"})
    _run_fails(tmp_path, base | {"mode": "curves"})
    _run_fails(tmp_path, base | {"filter-speckle": 129})
    _run_fails(tmp_path, base | {"filter-speckle": True})
    _run_fails(tmp_path, base | {"color-precision": 0})
    _run_fails(tmp_path, base | {"color-precision": "many"})


def test_verify_passes_a_good_trace_and_counts_its_path(tmp_path: Path) -> None:
    out_dir, piece, _result = _run_ok(tmp_path)
    stub_dir = _stub_modules(tmp_path)
    _done, result = _call(
        stub_dir,
        "verify",
        _request("verify", out_dir, piece, assets=(out_dir / "fixture.svg",)),
        tmp_path,
        _environment(stub_dir, tmp_path),
    )
    assert result is not None
    (asset,) = result["assets"]
    assert asset["passed"] is True
    assert asset["metrics"]["path_count"] == 1
    assert asset["metrics"]["bytes"] > 0
    assert asset["thresholds"] == {"min_bytes": 1, "min_paths": 1}
    assert asset["verifier"] == "vtracer"


def _verify_one(tmp_path: Path, payload: bytes) -> dict[str, Any]:
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    piece = _piece(tmp_path)
    asset = out_dir / "fixture.svg"
    asset.write_bytes(payload)
    stub_dir = _stub_modules(tmp_path)
    _done, result = _call(
        stub_dir,
        "verify",
        _request("verify", out_dir, piece, assets=(asset,)),
        tmp_path,
        _environment(stub_dir, tmp_path),
    )
    assert result is not None
    (entry,) = result["assets"]
    return entry


def test_verify_fails_corrupt_svg_and_pathless_svg(tmp_path: Path) -> None:
    corrupt = _verify_one(tmp_path, b"not xml at all")
    assert corrupt["passed"] is False
    assert corrupt["verifier"] == "vtracer"
    plain = _verify_one(tmp_path, b'<svg version="1.1" xmlns="http://www.w3.org/2000/svg"></svg>')
    assert plain["passed"] is False
    assert plain["metrics"]["path_count"] == 0
    wrong_root = _verify_one(tmp_path, b"<html><path d='M0,0'/></html>")
    assert wrong_root["passed"] is False


def test_verify_fails_a_missing_file(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    piece = _piece(tmp_path)
    stub_dir = _stub_modules(tmp_path)
    _done, result = _call(
        stub_dir,
        "verify",
        _request("verify", out_dir, piece, assets=(out_dir / "absent.svg",)),
        tmp_path,
        _environment(stub_dir, tmp_path),
    )
    assert result is not None
    (entry,) = result["assets"]
    assert entry["passed"] is False


def test_preview_writes_the_image_schema_fields(tmp_path: Path) -> None:
    out_dir, piece, _result = _run_ok(tmp_path)
    stub_dir = _stub_modules(tmp_path)
    _done, result = _call(
        stub_dir,
        "preview",
        _request("preview", out_dir, piece, assets=(out_dir / "fixture.svg",)),
        tmp_path,
        _environment(stub_dir, tmp_path),
    )
    assert result is not None
    (entry,) = result["assets"]
    assert entry == {
        "file": "fixture.svg",
        "preview": "fixture.svg.preview.json",
        "images": [],
    }
    data = json.loads((out_dir / "fixture.svg.preview.json").read_text(encoding="utf-8"))
    assert set(data) == PREVIEW_FIELDS
    assert data["preview"] == 1
    assert data["kind"] == "image"
    assert data["name"] == "fixture"
    assert data["prompt"] == "trace of fixture"
    assert data["seed"] == 0
    assert (data["width"], data["height"]) == (32, 32)


def test_doctor_quick_reports_the_stub_imports(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    _done, result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out_dir, _piece(tmp_path)),
        tmp_path,
        _environment(stub_dir, tmp_path),
    )
    assert result is not None
    (check,) = result["checks"]
    assert check["name"] == "imports"
    assert check["ok"] is True
    assert "vtracer" in check["detail"]


def test_doctor_quick_fails_without_vtracer(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path, vtracer=False)
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    _done, result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out_dir, _piece(tmp_path)),
        tmp_path,
        _environment(stub_dir, tmp_path),
    )
    assert result is not None
    (check,) = result["checks"]
    assert check["name"] == "imports"
    assert check["ok"] is False
    assert check["fix"] == "facet pull vtracer"


def test_doctor_full_traces_the_synthetic_fixture(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    _done, result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out_dir, _piece(tmp_path), depth="full"),
        tmp_path,
        _environment(stub_dir, tmp_path),
    )
    assert result is not None
    assert [check["name"] for check in result["checks"]] == ["imports", "trace"]
    assert all(check["ok"] for check in result["checks"])


def test_doctor_full_fails_when_the_trace_has_no_path(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    env = _environment(stub_dir, tmp_path) | {"VTRACER_STUB_MODE": "empty"}
    _done, result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out_dir, _piece(tmp_path), depth="full"),
        tmp_path,
        env,
    )
    assert result is not None
    trace = result["checks"][-1]
    assert trace["name"] == "trace"
    assert trace["ok"] is False
